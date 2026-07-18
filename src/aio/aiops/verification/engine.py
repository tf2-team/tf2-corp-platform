from __future__ import annotations

from aiops.schemas import Feature, Incident, VerificationResult
from aiops.shared.features import index_features


class VerificationEngine:
    def verify(
        self,
        incidents: list[Incident],
        features: list[Feature],
        *,
        active_incident_ids: set[str] | None = None,
        available_metric_signal_ids: set[str] | None = None,
    ) -> list[VerificationResult]:
        by_signal = index_features(features)
        active_incident_ids = active_incident_ids or set()
        available_metric_signal_ids = available_metric_signal_ids or set()
        results: list[VerificationResult] = []
        for incident in incidents:
            event = incident.events[-1]
            feature = by_signal.get(event.signal_id)
            if incident.incident_id in active_incident_ids and event.reason == "adaptive_baseline_deviation":
                results.append(
                    VerificationResult(
                        incident_id=incident.incident_id,
                        status="not_recovered",
                        reason="adaptive_detector_still_firing",
                    )
                )
            elif feature is None and event.signal_id not in available_metric_signal_ids:
                results.append(
                    VerificationResult(
                        incident_id=incident.incident_id,
                        status="inconclusive",
                        reason="verification_signal_unavailable",
                    )
                )
            elif feature is not None and feature.status != "ready":
                results.append(
                    VerificationResult(
                        incident_id=incident.incident_id,
                        status="inconclusive",
                        reason="verification_signal_unavailable",
                    )
                )
            elif incident.incident_id not in active_incident_ids:
                results.append(
                    VerificationResult(
                        incident_id=incident.incident_id,
                        status="recovered",
                        reason="detector_no_longer_firing",
                    )
                )
            elif event.threshold is not None and feature is not None and feature.value is not None and feature.value <= event.threshold:
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
