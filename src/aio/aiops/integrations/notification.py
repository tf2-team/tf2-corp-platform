#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from aiops.config import Settings
from aiops.config.hyperparameters import load_hyperparameters
from aiops.integrations.http import HttpApiClient
from aiops.schemas import NotificationMessage


DISCORD_WEBHOOK_HOSTS = frozenset(
    {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}
)
DISCORD_COLORS = {
    "SEV1": 0xE74C3C,
    "SEV2": 0xE67E22,
    "SEV3": 0xF1C40F,
    "SEV4": 0x3498DB,
}


class NotificationAdapter(Protocol):
    def send(self, message: NotificationMessage) -> dict[str, Any]: ...

    def close(self) -> None: ...


class JsonWebhookNotificationAdapter:
    """Send the platform NotificationMessage contract to a generic JSON webhook."""

    def __init__(
        self,
        webhook_url: str,
        token: str = "",
        account: str = "",
        transport: httpx.BaseTransport | None = None,
    ):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if account:
            headers["X-AIOps-Account"] = account
        self._webhook_url = webhook_url
        self._client = httpx.Client(headers=headers, transport=transport, timeout=10.0)

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        return _post(self._client, self._webhook_url, message.model_dump(mode="json"))

    def close(self) -> None:
        self._client.close()


class DiscordNotificationAdapter:
    """Translate NotificationMessage into a Discord webhook embed."""

    def __init__(
        self,
        webhook_url: str,
        user_rca_thresholds: tuple[float, float],
        transport: httpx.BaseTransport | None = None,
        user_facing: bool = False,
    ):
        self._webhook_url = webhook_url
        self._client = httpx.Client(transport=transport, timeout=10.0)
        self._user_facing = user_facing
        self._user_rca_thresholds = user_rca_thresholds

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        return _post(self._client, self._webhook_url, _discord_payload(message, self._user_rca_thresholds, self._user_facing))

    def close(self) -> None:
        self._client.close()


class NotificationClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        notification_config = load_hyperparameters(settings.hyperparameters_path)["notification"]
        user_rca_thresholds = (
            float(notification_config["user_rca_medium_confidence_score"]),
            float(notification_config["user_rca_high_confidence_score"]),
        )
        channels = [
            ("dev", settings.notification_dev_webhook_url),
            ("user", settings.notification_user_webhook_url),
        ]
        channels = [(name, url) for name, url in channels if url] or [("default", settings.notification_webhook_url)]
        self._adapters = [
            (name, _notification_adapter(settings, url, transport, user_facing=name == "user", user_rca_thresholds=user_rca_thresholds))
            for name, url in channels
        ]

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        if len(self._adapters) == 1:
            return self._adapters[0][1].send(message)
        with ThreadPoolExecutor(max_workers=len(self._adapters)) as executor:
            responses = executor.map(lambda item: item[1].send(message), self._adapters)
            return {name: response for (name, _), response in zip(self._adapters, responses)}

    def close(self) -> None:
        for _, adapter in self._adapters:
            adapter.close()


def _notification_adapter(
    settings: Settings,
    webhook_url: str,
    transport: httpx.BaseTransport | None,
    user_rca_thresholds: tuple[float, float],
    user_facing: bool = False,
) -> NotificationAdapter:
    provider = settings.notification_provider
    if provider == "auto":
        provider = "discord" if _is_discord_webhook(webhook_url) else "generic"
    if provider == "discord":
        return DiscordNotificationAdapter(
            webhook_url,
            transport=transport,
            user_facing=user_facing,
            user_rca_thresholds=user_rca_thresholds,
        )
    return JsonWebhookNotificationAdapter(
        webhook_url,
        token=settings.notification_token,
        account=settings.notification_account,
        transport=transport,
    )


def _is_discord_webhook(webhook_url: str) -> bool:
    parsed = urlparse(webhook_url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in DISCORD_WEBHOOK_HOSTS
        and parsed.path.startswith("/api/webhooks/")
    )


def _post(client: httpx.Client, webhook_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(webhook_url, json=payload)
    response.raise_for_status()
    decoded = HttpApiClient._decode_response(response)
    return decoded if isinstance(decoded, dict) else {"response": decoded}


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _discord_payload(
    message: NotificationMessage,
    user_rca_thresholds: tuple[float, float],
    user_facing: bool = False,
) -> dict[str, Any]:
    fields = [
        ("State", message.state),
        ("Service", message.service),
        ("Flow", message.flow),
        ("Runbook", message.runbook_id),
    ]
    if message.likely_dependency != "unknown":
        fields.insert(3, ("Likely dependency", message.likely_dependency))
    return {
        "username": "TF2 AIOps",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": _truncate(f"[{message.severity}] {message.title}", 256),
                "description": _truncate(_user_summary(message, user_rca_thresholds) if user_facing else message.summary, 3500),
                "color": DISCORD_COLORS.get(message.severity.upper(), 0x95A5A6),
                "timestamp": datetime.now(UTC).isoformat(),
                "fields": [
                    {
                        "name": name,
                        "value": _truncate(str(value) or "unknown", 256),
                        "inline": name in {"State", "Service", "Flow"},
                    }
                    for name, value in fields
                ],
                "footer": {"text": _truncate(f"Incident {message.incident_id}", 256)},
            }
        ],
    }


def _user_summary(message: NotificationMessage, thresholds: tuple[float, float]) -> str:
    if "Detected: rca_root_cause" not in message.summary:
        return message.summary
    lines = message.summary.splitlines()
    score = next((float(line.split(":", 1)[1]) for line in lines if line.startswith("RCA score:")), 0.0)
    metrics = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("Metric:")), "")
    metric_line = f"Metrics: {metrics or 'unknown'}."
    evidence = []
    in_evidence = False
    for line in lines:
        if line == "Evidence:":
            in_evidence = True
        elif in_evidence and line.startswith(("Action:", "Runbook:")):
            break
        elif in_evidence and "score" not in line.lower() and "evidence_strength" not in line.lower():
            evidence.append(line)
    evidence_block = "\nEvidence:\n" + "\n".join(evidence) if evidence else ""
    medium_score, high_score = thresholds
    if score < medium_score:
        confidence = "This root cause has low confidence and cannot yet be confirmed."
    elif score < high_score:
        confidence = "This root cause is fairly reliable, but should still be verified."
    else:
        return f"The root cause was identified with very high confidence: {message.service}.\n{metric_line}{evidence_block}\nRunbook: {message.runbook_id}"
    alternatives = (
        f"Other possible root causes: {metrics}."
        if "," in metrics
        else "I have not found any other possible root causes."
    )
    return f"{confidence}\nCurrent root cause: {message.service}.\n{metric_line}\n{alternatives}{evidence_block}\nRunbook: {message.runbook_id}"
