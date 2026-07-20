#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from aiops.schemas import Feature


def index_features(features: list[Feature]) -> dict[str, Feature]:
    return {feature.signal_id: feature for feature in features}


def find_feature(features: list[Feature], signal_id: str) -> Feature | None:
    return index_features(features).get(signal_id)


def feature_timestamp(feature: Feature) -> int:
    try:
        return int(float(feature.labels.get("sample_timestamp", "0")))
    except ValueError:
        return 0
