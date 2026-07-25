#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from abc import ABC, abstractmethod

from aiops.schemas import CandidateEvent, Feature
from aiops.shared.features import feature_timestamp


class Detector(ABC):
    @abstractmethod
    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        raise NotImplementedError


def candidate_from_feature(
    feature: Feature,
    *,
    detector_id: str,
    flow: str,
    service: str,
    severity: str,
    threshold: float | None,
    reason: str,
    runbook_id: str,
    confidence: float,
    likely_dependency: str = "unknown",
) -> CandidateEvent:
    return CandidateEvent(
        detector_id=detector_id,
        timestamp=feature_timestamp(feature),
        flow=flow,
        service=service,
        severity=severity,
        signal_id=feature.signal_id,
        value=feature.value,
        unit=feature.unit,
        window=feature.window,
        threshold=threshold,
        quality=feature.quality,
        reason=reason,
        runbook_id=runbook_id,
        likely_dependency=likely_dependency,
        confidence=confidence,
        contributing_signals=(feature.signal_id,),
        labels=feature.labels,
    )
