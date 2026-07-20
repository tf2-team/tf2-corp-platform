#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class AieClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(settings.aie_status_url, token=settings.aie_token, account=settings.aie_account, transport=transport)

    def get_status(self) -> dict:
        return self._http.get("/status")

