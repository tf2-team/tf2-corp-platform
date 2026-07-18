from __future__ import annotations

import logging

from aiops.schemas import CandidateEvent, RuntimeConfig, SignalQuality


logger = logging.getLogger(__name__)


class Correlator:
    def __init__(
        self,
        runtime_config: RuntimeConfig | None = None,
        window_seconds: int = 0,
        suppress_window_seconds: int = 900,
        topology_max_hops: int = 2,
        confidence_threshold: float = 0.0,
        weights: dict[str, float] | None = None,
    ):
        self.environment = runtime_config.environment if runtime_config else "unknown"
        self.window_seconds = window_seconds
        self.suppress_window_seconds = suppress_window_seconds
        self.topology_max_hops = topology_max_hops
        self.confidence_threshold = confidence_threshold
        self.weights = weights or {}
        self.topology = {item.name: set(item.dependencies) for item in runtime_config.topology.services} if runtime_config else {}

    def correlate(self, candidates: list[CandidateEvent]) -> list[CandidateEvent]:
        grouped: dict[tuple[str, str, str, int], list[CandidateEvent]] = {}
        for candidate in candidates:
            event = candidate if candidate.environment != "unknown" else candidate.model_copy(update={"environment": self.environment})
            bucket = event.timestamp // self.window_seconds if self.window_seconds else 0
            grouped.setdefault((event.environment, event.flow, event.service, bucket), []).append(event)

        correlated: list[CandidateEvent] = []
        for group in grouped.values():
            primary_signal = next((item for item in group if item.likely_dependency == "unknown"), group[0])
            dependency, components = self._rank_dependency(group, primary_signal)
            logger.debug(
                "AIOPS_BLOCK correlate_group service=%s flow=%s candidates=%s primary=%s dependency=%s components=%s",
                primary_signal.service,
                primary_signal.flow,
                [item.detector_id for item in group],
                primary_signal.detector_id,
                dependency.detector_id if dependency else None,
                components,
            )
            if dependency is None:
                correlated.extend(self._merge_same_impact(group))
                continue
            primary = dependency or primary_signal
            contributing = tuple(dict.fromkeys(signal for item in group for signal in item.contributing_signals))
            confidence = max(dependency.confidence, sum(components.values())) if dependency else max(item.confidence for item in group)
            confidence = max(0.0, min(1.0, confidence))
            correlated.append(
                primary.model_copy(
                    update={
                        "confidence": confidence,
                        "contributing_signals": contributing,
                        "severity": min(item.severity for item in group),
                        "likely_dependency": dependency.likely_dependency if dependency else "unknown",
                        "runbook_id": dependency.runbook_id if dependency else primary_signal.runbook_id,
                        "correlation_components": components,
                    }
                )
            )
        return correlated

    def _merge_same_impact(self, group: list[CandidateEvent]) -> list[CandidateEvent]:
        adaptive = [item for item in group if item.reason == "adaptive_baseline_deviation"]
        remaining = [item for item in group if item.reason != "adaptive_baseline_deviation"]
        merged: list[CandidateEvent] = []
        if adaptive:
            merged.append(self._merge_adaptive_group(adaptive) if len(adaptive) > 1 else adaptive[0])

        impact_groups: dict[str, list[CandidateEvent]] = {}
        for item in remaining:
            impact = item.labels.get("impact", "")
            if impact:
                impact_groups.setdefault(impact, []).append(item)
            else:
                merged.append(item)
        for items in impact_groups.values():
            merged.append(self._merge_impact_group(items) if len(items) > 1 else items[0])
        return merged

    def _merge_impact_group(self, group: list[CandidateEvent]) -> CandidateEvent:
        primary = min(group, key=lambda item: (item.severity, -item.confidence, item.detector_id))
        contributing = tuple(dict.fromkeys(signal for item in group for signal in item.contributing_signals))
        detector_ids = sorted({item.detector_id for item in group})
        return primary.model_copy(
            update={
                "confidence": max(item.confidence for item in group),
                "contributing_signals": contributing,
                "severity": min(item.severity for item in group),
                "labels": {**primary.labels, "correlated_detectors": ",".join(detector_ids)},
            }
        )

    def _merge_adaptive_group(self, group: list[CandidateEvent]) -> CandidateEvent:
        primary = min(group, key=lambda item: (item.severity, -item.confidence, item.detector_id))
        contributing = tuple(dict.fromkeys(signal for item in group for signal in item.contributing_signals))
        metrics = sorted({item.labels.get("metric", item.signal_id) for item in group})
        return primary.model_copy(
            update={
                "detector_id": f"adaptive_{primary.service.replace('-', '_')}_correlated",
                "confidence": max(item.confidence for item in group),
                "contributing_signals": contributing,
                "severity": min(item.severity for item in group),
                "labels": {**primary.labels, "correlated_metrics": ",".join(metrics)},
            }
        )

    def _rank_dependency(self, group: list[CandidateEvent], primary: CandidateEvent) -> tuple[CandidateEvent | None, dict[str, float]]:
        ranked = [
            (candidate, self._score(candidate, primary, group))
            for candidate in group
            if candidate.likely_dependency != "unknown"
        ]
        if not ranked:
            return None, {}
        candidate, components = max(ranked, key=lambda item: max(item[0].confidence, sum(item[1].values())))
        return (candidate, components) if max(candidate.confidence, sum(components.values())) >= self.confidence_threshold else (None, {})

    def _score(self, candidate: CandidateEvent, primary: CandidateEvent, group: list[CandidateEvent]) -> dict[str, float]:
        components: dict[str, float] = {}
        if any(item.quality == SignalQuality.VERIFIED for item in group):
            components["verified_primary_signal"] = self.weights.get("verified_primary_signal", 0.0)
        if candidate.timestamp and primary.timestamp and candidate.timestamp <= primary.timestamp:
            components["temporal_precedence"] = self.weights.get("temporal_precedence", 0.0)
        if candidate.likely_dependency in self.topology.get(candidate.service, set()):
            components["topology_path"] = self.weights.get("topology_path", 0.0)
        if {"operation", "rpc", "method", "span"} & candidate.labels.keys():
            components["operation_specificity"] = self.weights.get("operation_specificity", 0.0)
        if any(item.source in {"trace", "log", "kubernetes"} for item in candidate.evidence):
            components["trace_log_kubernetes_corroboration"] = self.weights.get("trace_log_kubernetes_corroboration", 0.0)
        if candidate.quality != SignalQuality.VERIFIED:
            components["stale_or_missing_evidence_penalty"] = self.weights.get("stale_or_missing_evidence_penalty", 0.0)
        return components
