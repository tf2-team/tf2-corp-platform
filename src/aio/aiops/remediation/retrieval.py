from __future__ import annotations

from aiops.schemas import IncidentFeatures, IncidentHistoryRecord


class HistoryRetriever:
    def __init__(self, weights: dict[str, float], top_k: int):
        self.weights = weights
        self.top_k = top_k

    def top_matches(self, current: IncidentFeatures, history: list[IncidentHistoryRecord]) -> list[tuple[IncidentHistoryRecord, float]]:
        scored = [(record, self._similarity(current, record)) for record in history]
        return [(record, score) for record, score in sorted(scored, key=lambda item: item[1], reverse=True)[: self.top_k] if score > 0]

    def _similarity(self, current: IncidentFeatures, record: IncidentHistoryRecord) -> float:
        parts = {
            "service": self._jaccard(current.affected_services, record.affected_services),
            "log": self._jaccard(current.log_signatures, record.log_signatures),
            "trace": self._jaccard(current.trace_signatures, record.trace_signatures),
            "metric": self._metric_similarity(current.metric_ratios, record.metric_ratios),
        }
        total_weight = sum(self.weights.values()) or 1.0
        return sum(parts[key] * self.weights.get(key, 0.0) for key in parts) / total_weight

    def _jaccard(self, left: set[str], right: set[str]) -> float:
        if not left and not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _metric_similarity(self, left: dict[str, float], right: dict[str, float]) -> float:
        common = set(left) & set(right)
        if not common:
            return 0.0
        scores = [1 / (1 + abs(left[key] - right[key])) for key in common]
        return sum(scores) / len(scores)
