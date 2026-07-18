from __future__ import annotations

from aiops.schemas import AnomalyFinding, CandidateEvent, RuntimeConfig, SignalQuality


class AdaptiveAnomalyEventBuilder:
    """Translate confirmed statistical findings into normal incident candidates."""

    def __init__(self, runtime_config: RuntimeConfig | None, score_threshold: float):
        self.score_threshold = score_threshold
        self._signals = {signal.id: signal for signal in runtime_config.signals} if runtime_config else {}
        self._service_flows = (
            {service.name: service.flow for service in runtime_config.topology.services}
            if runtime_config
            else {}
        )

    def build(self, findings: list[AnomalyFinding]) -> list[CandidateEvent]:
        return [self._build_one(finding) for finding in findings]

    def _build_one(self, finding: AnomalyFinding) -> CandidateEvent:
        signal = self._signals.get(finding.signal_id)
        flow = signal.flow if signal else self._service_flows.get(finding.service, "platform")
        window = signal.window if signal else "adaptive"
        severity, runbook_id = _routing(finding.service, finding.metric)
        return CandidateEvent(
            detector_id=f"adaptive_{_identifier(finding.service)}_{_identifier(finding.metric)}",
            timestamp=finding.timestamp,
            flow=flow,
            service=finding.service,
            severity=severity,
            signal_id=finding.signal_id,
            value=finding.score,
            unit="anomaly_score",
            window=window,
            threshold=self.score_threshold,
            quality=SignalQuality.VERIFIED,
            reason="adaptive_baseline_deviation",
            runbook_id=runbook_id,
            confidence=max(0.0, min(1.0, finding.score)),
            contributing_signals=(finding.signal_id,),
            labels={"algorithm": finding.algorithm, "metric": finding.metric, "baseline": "service_metric_history"},
        )


def _routing(service: str, metric: str) -> tuple[str, str]:
    lowered = metric.lower()
    if service == "checkout" and "latency" in lowered:
        return "SEV2", "RB-CHECKOUT-LATENCY"
    if service == "cart" and ("error" in lowered or "failure" in lowered):
        return "SEV2", "RB-CART-ERROR-RATE"
    if service == "product-catalog" and "cpu" in lowered:
        return "SEV3", "RB-PRODUCT-CATALOG-CPU"
    if any(token in lowered for token in ("error", "failure", "latency", "ready_pods", "oom", "memory")):
        return "SEV2", "RB-SERVICE-ERROR-RATE"
    return "SEV3", "RB-SERVICE-ERROR-RATE"


def _identifier(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_")
