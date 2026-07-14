from __future__ import annotations

from aiops.schemas import CandidateEvent, EvidenceItem, Feature
from aiops.shared.features import index_features


class Enricher:
    def enrich(self, candidates: list[CandidateEvent], features: list[Feature]) -> list[CandidateEvent]:
        by_signal = index_features(features)
        enriched: list[CandidateEvent] = []
        for candidate in candidates:
            evidence = list(candidate.evidence)
            for signal_id in candidate.contributing_signals:
                feature = by_signal.get(signal_id)
                if feature is None:
                    continue
                evidence.append(
                    EvidenceItem(
                        source="feature",
                        reference=signal_id,
                        summary=f"{feature.window} {feature.unit} quality={feature.quality.value}",
                    )
                )
            enriched.append(candidate.model_copy(update={"evidence": tuple(evidence)}))
        return enriched
