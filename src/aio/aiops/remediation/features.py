from __future__ import annotations

from aiops.schemas import Incident, IncidentFeatures, RcaResult


class RemediationFeatureExtractor:
    def extract(self, incident: Incident, rca_result: RcaResult) -> IncidentFeatures:
        affected = {incident.service}
        if incident.likely_dependency != "unknown":
            affected.add(incident.likely_dependency)
        affected.update(root.service for root in rca_result.root_causes)

        log_signatures: set[str] = set()
        trace_signatures: set[str] = set()
        metric_ratios: dict[str, float] = {}
        for event in incident.events:
            log_signatures.add(event.reason)
            trace_signatures.update(item.summary for item in event.evidence if item.source == "trace")
            if event.threshold and event.value is not None:
                metric_ratios[event.signal_id] = event.value / event.threshold

        return IncidentFeatures(affected_services=affected, log_signatures=log_signatures, trace_signatures=trace_signatures, metric_ratios=metric_ratios)
