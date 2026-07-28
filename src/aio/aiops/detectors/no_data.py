#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging

from aiops.detectors.base import Detector, candidate_from_feature
from aiops.schemas import CandidateEvent, Feature, SignalQuality


logger = logging.getLogger(__name__)


class NoDataDetector(Detector):
    def __init__(
        self,
        required_signal_ids: list[str],
        detector_id: str,
        flow: str,
        service: str,
        severity: str,
        runbook_id: str,
        missing_confidence: float,
        unknown_confidence: float,
        stale_confidence: float | None = None,
    ):
        self.required_signal_ids = set(required_signal_ids)
        self.detector_id = detector_id
        self.flow = flow
        self.service = service
        self.severity = severity
        self.runbook_id = runbook_id
        self.missing_confidence = missing_confidence
        self.unknown_confidence = unknown_confidence
        self.stale_confidence = missing_confidence if stale_confidence is None else stale_confidence

    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        candidates: list[CandidateEvent] = []
        log_items: list[str] = []
        for feature in features:
            if feature.signal_id not in self.required_signal_ids or feature.status != "unknown":
                continue
            service = feature.labels.get("service") or feature.labels.get("service_name") or self.service
            flow = feature.labels.get("flow") or self.flow
            log_items.append(
                f"detector={self.detector_id} signal={feature.signal_id} quality={feature.quality.value} "
                f"service={service} severity={self.severity}"
            )
            candidates.append(
                candidate_from_feature(
                    feature,
                    detector_id=self.detector_id,
                    flow=flow,
                    service=service,
                    severity=self.severity,
                    threshold=None,
                    reason=f"signal_{feature.quality.value}",
                    runbook_id=self.runbook_id,
                    confidence=(
                        self.stale_confidence
                        if feature.quality == SignalQuality.STALE
                        else self.missing_confidence
                        if feature.quality == SignalQuality.MISSING
                        else self.unknown_confidence
                    ),
                )
            )
        if log_items:
            logger.warning("AIOPS_DETECT no_data_fire %s", " | ".join(log_items))
        return candidates
