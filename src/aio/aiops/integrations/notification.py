#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from aiops.config import Settings
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


class DiscordNotificationAdapter:
    """Translate NotificationMessage into a Discord webhook embed."""

    def __init__(self, webhook_url: str, transport: httpx.BaseTransport | None = None):
        self._webhook_url = webhook_url
        self._client = httpx.Client(transport=transport, timeout=10.0)

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        return _post(self._client, self._webhook_url, _discord_payload(message))


class NotificationClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        provider = settings.notification_provider
        if provider == "auto":
            provider = "discord" if _is_discord_webhook(settings.notification_webhook_url) else "generic"

        if provider == "discord":
            self._adapter: NotificationAdapter = DiscordNotificationAdapter(
                settings.notification_webhook_url,
                transport=transport,
            )
        else:
            self._adapter = JsonWebhookNotificationAdapter(
                settings.notification_webhook_url,
                token=settings.notification_token,
                account=settings.notification_account,
                transport=transport,
            )

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        return self._adapter.send(message)


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


def _discord_payload(message: NotificationMessage) -> dict[str, Any]:
    fields = [
        ("State", message.state),
        ("Service", message.service),
        ("Flow", message.flow),
        ("Likely dependency", message.likely_dependency),
        ("Runbook", message.runbook_id),
    ]
    return {
        "username": "TF2 AIOps",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": _truncate(f"[{message.severity}] {message.title}", 256),
                "description": _truncate(message.summary, 3500),
                "color": DISCORD_COLORS.get(message.severity.upper(), 0x95A5A6),
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

