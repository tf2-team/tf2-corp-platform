from __future__ import annotations

from aiops.schemas import Feature


def index_features(features: list[Feature]) -> dict[str, Feature]:
    return {feature.signal_id: feature for feature in features}


def find_feature(features: list[Feature], signal_id: str) -> Feature | None:
    return index_features(features).get(signal_id)
