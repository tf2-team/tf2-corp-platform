from __future__ import annotations

import json
from pathlib import Path

from aiops.detectors import DependencyDetector, Detector, NoDataDetector, ThresholdDetector
from aiops.config.settings import Settings
from aiops.schemas import RuntimeConfig


def load_runtime_config(path: Path) -> RuntimeConfig:
    return RuntimeConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def build_detectors(
    config: RuntimeConfig,
    settings: Settings | None,
    no_data_hyperparameters: dict[str, float],
    detector_hyperparameters: dict | None = None,
) -> list[Detector]:
    detectors: list[Detector] = []
    detector_hyperparameters = detector_hyperparameters or {}
    thresholds = detector_hyperparameters.get("thresholds") or config.detector_thresholds
    confidences = detector_hyperparameters.get("confidences") or config.detector_confidences
    for item in config.detectors:
        if not item.enabled:
            continue
        if item.type == "threshold":
            detectors.append(
                ThresholdDetector(
                    detector_id=item.id,
                    signal_id=item.signal_id or "",
                    threshold=thresholds[item.id],
                    flow=item.flow,
                    service=item.service,
                    severity=item.severity,
                    runbook_id=item.runbook_id,
                )
            )
        elif item.type == "dependency":
            detectors.append(
                DependencyDetector(
                    detector_id=item.id,
                    signal_id=item.signal_id or "",
                    threshold=thresholds[item.id],
                    flow=item.flow,
                    service=item.service,
                    dependency=item.dependency or "unknown",
                    severity=item.severity,
                    confidence=confidences[item.id],
                    runbook_id=item.runbook_id,
                )
            )
        elif item.type == "no-data":
            detectors.append(
                NoDataDetector(
                    item.signal_ids,
                    detector_id=item.id,
                    flow=item.flow,
                    service=item.service,
                    severity=item.severity,
                    runbook_id=item.runbook_id,
                    missing_confidence=no_data_hyperparameters["missing_confidence"],
                    unknown_confidence=no_data_hyperparameters["unknown_confidence"],
                )
            )
    return detectors
