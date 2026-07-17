from __future__ import annotations

from aiops.schemas import CandidateEvent, RuntimeConfig, SignalQuality


class Correlator:
    def __init__(
        self,
        runtime_config: RuntimeConfig | None = None,
        window_seconds: int = 0,
        confidence_threshold: float = 0.0,
        weights: dict[str, float] | None = None,
    ):
        self.environment = runtime_config.environment if runtime_config else "unknown"
        self.window_seconds = window_seconds
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
