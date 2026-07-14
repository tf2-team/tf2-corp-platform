from __future__ import annotations

from aiops.schemas import Feature, Incident, VerificationResult
from aiops.shared.features import index_features


class VerificationEngine:
    def verify(self, incidents: list[Incident], features: list[Feature]) -> list[VerificationResult]:
        by_signal = index_features(features)
        results: list[VerificationResult] = []
        for incident in incidents:
            event = incident.events[-1]
            feature = by_signal.get(event.signal_id)
            if feature is None or feature.status != "ready":
                results.append(
                    VerificationResult(
                        incident_id=incident.incident_id,
                        status="inconclusive",
                        reason="verification_signal_unavailable",
                    )
                )
            elif event.threshold is not None and feature.value is not None and feature.value <= event.threshold:
                results.append(
                    VerificationResult(
                        incident_id=incident.incident_id,
                        status="recovered",
                        reason="threshold_passed",
                    )
                )
            else:
                results.append(
                    VerificationResult(
                        incident_id=incident.incident_id,
                        status="not_recovered",
                        reason="threshold_still_firing",
                    )
                )
        return results
