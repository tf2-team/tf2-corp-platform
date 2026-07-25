#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging

from aiops.detectors.base import Detector, candidate_from_feature
from aiops.schemas import CandidateEvent, Feature
from aiops.shared.features import find_feature


logger = logging.getLogger(__name__)


class DependencyDetector(Detector):
    def __init__(
        self,
        detector_id: str,
        signal_id: str,
        threshold: float,
        flow: str,
        service: str,
        dependency: str,
        runbook_id: str,
        severity: str,
        confidence: float,
    ):
        self.detector_id = detector_id
        self.signal_id = signal_id
        self.threshold = threshold
        self.flow = flow
        self.service = service
        self.dependency = dependency
        self.runbook_id = runbook_id
        self.severity = severity
        self.confidence = confidence

    def evaluate(self, features: list[Feature]) -> list[CandidateEvent]:
        feature = find_feature(features, self.signal_id)
        if (
            feature is None
            or feature.status != "ready"
            or feature.feature_role not in {"diagnostic", "dependency_signal"}
            or feature.value is None
            or feature.value <= self.threshold
        ):
            return []
        logger.warning(
            "AIOPS_DETECT dependency_fire detector=%s signal=%s value=%s threshold=%s service=%s dependency=%s severity=%s confidence=%s",
            self.detector_id,
            feature.signal_id,
            feature.value,
            self.threshold,
            self.service,
            self.dependency,
            self.severity,
            self.confidence,
        )
        return [
            candidate_from_feature(
                feature,
                detector_id=self.detector_id,
                flow=self.flow,
                service=self.service,
                severity=self.severity,
                threshold=self.threshold,
                reason="dependency_signal_breached",
                runbook_id=self.runbook_id,
                likely_dependency=self.dependency,
                confidence=self.confidence,
            )
        ]
