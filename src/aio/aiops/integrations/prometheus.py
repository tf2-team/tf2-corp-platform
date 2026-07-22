#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import httpx

from aiops.config import Settings
from aiops.integrations.http import HttpApiClient


class PrometheusClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._http = HttpApiClient(
            settings.prometheus_base_url,
            token=settings.prometheus_token,
            account=settings.prometheus_account,
            transport=transport,
            timeout=settings.prometheus_timeout_seconds,
        )

    def query(self, query: str, time: str | None = None) -> dict:
        params = {"query": query}
        if time is not None:
            params["time"] = time
        return self._http.get("/api/v1/query", params=params)

    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        return self._http.get("/api/v1/query_range", params={"query": query, "start": start, "end": end, "step": step})

    def targets(self) -> dict:
        return self._http.get("/api/v1/targets")
