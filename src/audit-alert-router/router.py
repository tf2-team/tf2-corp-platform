# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

_WEBHOOK_URL_CACHE: Optional[str] = None
func_get_secret = None


def get_webhook_url() -> str:
    global _WEBHOOK_URL_CACHE
    if _WEBHOOK_URL_CACHE:
        return _WEBHOOK_URL_CACHE

    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url:
        _WEBHOOK_URL_CACHE = url
        return url

    secret_name = os.environ.get("WEBHOOK_SECRET_NAME", "techx-audit-alert-router")
    if func_get_secret:
        url = func_get_secret(secret_name)
    else:
        try:
            import boto3

            client = boto3.client("secretsmanager")
            res = client.get_secret_value(SecretId=secret_name)
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

    _WEBHOOK_URL_CACHE = url
    return url


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
        return {"batchItemFailures": [{"itemIdentifier": r.get("messageId", "")} for r in records if "messageId" in r]}

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

    return {"batchItemFailures": failed_items}

# Change trail: @hungxqt - 2026-07-28 - Add audit alert router Lambda handler with Discord webhook delivery and partial batch failure support.
