#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

from aiops.schemas import ActionCatalogItem


class ActionCatalog:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, ActionCatalogItem]:
        items = [ActionCatalogItem.model_validate(item) for item in json.loads(self.path.read_text(encoding="utf-8"))]
        return {item.action_id: item for item in items}
