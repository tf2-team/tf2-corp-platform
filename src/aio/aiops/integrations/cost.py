from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class CostClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.cdo_cost_url, token=settings.cdo_cost_token, account=settings.cdo_cost_account, transport=transport
        )

    def get_status(self) -> dict:
        return self._http.get("/status")
