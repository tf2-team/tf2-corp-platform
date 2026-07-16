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
) -> list[Detector]:
    detectors: list[Detector] = []
    for item in config.detectors:
        if not item.enabled:
            continue
        if item.type == "threshold":
            detectors.append(
                ThresholdDetector(
                    detector_id=item.id,
                    signal_id=item.signal_id or "",
                    threshold=config.detector_thresholds[item.id],
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
                    threshold=config.detector_thresholds[item.id],
                    flow=item.flow,
                    service=item.service,
                    dependency=item.dependency or "unknown",
                    severity=item.severity,
                    confidence=config.detector_confidences[item.id],
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
