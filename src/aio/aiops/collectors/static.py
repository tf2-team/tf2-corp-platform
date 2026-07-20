#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from aiops.collectors.base import Collector
from aiops.schemas import Observation


class StaticCollector(Collector):
    def __init__(self, observations: list[Observation]):
        self._observations = observations

    def collect(self) -> list[Observation]:
        return list(self._observations)

