#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class LiveExecutorClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.live_executor_url,
            token=settings.live_executor_token,
            account=settings.live_executor_account,
            transport=transport,
        )

    def submit_action(self, action: dict) -> dict:
        return self._http.post("/actions", json=action)
