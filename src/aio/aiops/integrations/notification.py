from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient
from aiops.schemas import NotificationMessage


class NotificationClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.notification_webhook_url,
            token=settings.notification_token,
            account=settings.notification_account,
            transport=transport,
        )

    def send(self, message: NotificationMessage) -> dict:
        return self._http.post("/", json=message.model_dump(mode="json"))
