#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

_WEBHOOK_URL_CACHE: Optional[str] = None
func_get_secret = None


def _require_https_webhook_url(url: str) -> str:
    if not isinstance(url, str) or not url.startswith("https://"):
        raise RuntimeError("Discord webhook URL must use HTTPS")
    return url


def get_webhook_url() -> str:
    global _WEBHOOK_URL_CACHE
    if _WEBHOOK_URL_CACHE:
        return _WEBHOOK_URL_CACHE

    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url:
        _WEBHOOK_URL_CACHE = _require_https_webhook_url(url)
        return _WEBHOOK_URL_CACHE

    secret_id = (
        os.environ.get("DISCORD_WEBHOOK_SECRET_ARN")
        or os.environ.get("WEBHOOK_SECRET_NAME")
    )
    if not secret_id:
        raise RuntimeError("Discord webhook secret identifier is not configured")

    if func_get_secret:
        url = func_get_secret(secret_id)
    else:
        try:
            import boto3

            client = boto3.client("secretsmanager")
            res = client.get_secret_value(SecretId=secret_id)
            secret_str = res.get("SecretString", "")
            if secret_str.startswith("http"):
                url = secret_str
            else:
                data = json.loads(secret_str)
                url = data.get("url") or data.get("webhook_url") or data.get("DISCORD_WEBHOOK_URL")
        except Exception as e:
            raise RuntimeError(f"Failed to retrieve webhook secret: {e}") from e

    if not url:
        raise RuntimeError("Webhook URL not found in secret or environment")

    _WEBHOOK_URL_CACHE = _require_https_webhook_url(url)
    return url


def _emit_delivery_metrics(successes: int, failures: int) -> None:
    namespace = os.environ.get(
        "AUDIT_DETECTION_EVIDENCE_NAMESPACE", "TechX/Mandate11"
    )
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": namespace,
                            "Dimensions": [["Pipeline", "Channel"]],
                            "Metrics": [
                                {"Name": "DiscordDeliverySuccess", "Unit": "Count"},
                                {"Name": "DiscordDeliveryFailure", "Unit": "Count"},
                            ],
                        }
                    ],
                },
                "Pipeline": "audit-detection",
                "Channel": "discord",
                "DiscordDeliverySuccess": successes,
                "DiscordDeliveryFailure": failures,
            },
            sort_keys=True,
        )
    )


def post_to_discord(webhook_url: str, message: str, timeout: float = 5.0) -> bool:
    if len(message) > 2000:
        message = message[:1997] + "..."

    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "TechX-AuditAlertRouter/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def handler(event: Dict[str, Any], context: Any = None) -> Dict[str, List[Dict[str, str]]]:
    failed_items: List[Dict[str, str]] = []
    records = event.get("Records", [])

    try:
        webhook_url = get_webhook_url()
    except Exception:
        _emit_delivery_metrics(0, len(records))
        return {"batchItemFailures": [{"itemIdentifier": r.get("messageId", "")} for r in records if "messageId" in r]}

    successful_items = 0
    for record in records:
        msg_id = record.get("messageId", "")
        body = record.get("body", "")

        if not body:
            failed_items.append({"itemIdentifier": msg_id})
            continue

        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and "Detail" in parsed:
                content = parsed.get("Detail")
            elif isinstance(parsed, dict) and "Message" in parsed:
                content = parsed.get("Message")
            elif isinstance(parsed, dict):
                content = json.dumps(parsed)
            else:
                content = str(parsed)
        except Exception:
            failed_items.append({"itemIdentifier": msg_id})
            continue

        ok = post_to_discord(webhook_url, content)
        if not ok:
            failed_items.append({"itemIdentifier": msg_id})
        else:
            successful_items += 1

    _emit_delivery_metrics(successful_items, len(failed_items))
    return {"batchItemFailures": failed_items}

# Change trail: @hungxqt - 2026-07-29 - Align the router with the Terraform secret ARN and emit delivery evidence.
