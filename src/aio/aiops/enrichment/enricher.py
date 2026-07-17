from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any, Protocol

from aiops.schemas import CandidateEvent, EvidenceItem, Feature
from aiops.schemas import RuntimeConfig
from aiops.shared.features import index_features


class JaegerClientLike(Protocol):
    def search_traces(self, service: str, limit: int = 20, start: int | None = None, end: int | None = None) -> dict: ...

    def trace_ui_url(self, trace_id: str) -> str: ...


class OpenSearchClientLike(Protocol):
    def search(self, index: str, body: dict) -> dict: ...


class KubernetesClientLike(Protocol):
    def get_deployment(self, namespace: str, name: str) -> dict: ...

    def list_pods(self, namespace: str) -> dict: ...


class Enricher:
    def __init__(
        self,
        runtime_config: RuntimeConfig | None = None,
        jaeger: JaegerClientLike | None = None,
        opensearch: OpenSearchClientLike | None = None,
        kubernetes: KubernetesClientLike | None = None,
        opensearch_index: str = "otel-logs-*",
    ):
        self.runtime_config = runtime_config
        self.jaeger = jaeger
        self.opensearch = opensearch
        self.kubernetes = kubernetes
        self.opensearch_index = opensearch_index

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
            evidence.extend(self._external_evidence(candidate))
            enriched.append(candidate.model_copy(update={"evidence": tuple(evidence)}))
        return enriched

    def _external_evidence(self, candidate: CandidateEvent) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        if self.jaeger is not None:
            items.extend(self._jaeger_evidence(candidate))
        if self.opensearch is not None:
            items.extend(self._opensearch_evidence(candidate))
        if self.kubernetes is not None:
            items.extend(self._kubernetes_evidence(candidate))
        return items

    def _jaeger_evidence(self, candidate: CandidateEvent) -> list[EvidenceItem]:
        try:
            start, end = _time_bounds(candidate)
            traces = self.jaeger.search_traces(
                candidate.likely_dependency if candidate.likely_dependency != "unknown" else candidate.service,
                limit=1,
                start=start * 1_000_000,
                end=end * 1_000_000,
            ).get("data", [])
            if not traces:
                return []
            trace = traces[0]
            trace_id = str(trace.get("traceID", "unknown"))
            spans = trace.get("spans", [])
            span = next((item for item in spans if _span_has_error(item)), spans[0] if spans else {})
            operation = span.get("operationName", "unknown")
            service = _span_service(trace, span)
            duration = span.get("duration", "unknown")
            link = self.jaeger.trace_ui_url(trace_id)
            return [EvidenceItem(source="trace", reference=link, summary=f"{service}/{operation} duration={duration} error_span={_span_has_error(span)}")]
        except Exception as exc:
            return [EvidenceItem(source="enrichment_failure", reference="jaeger", summary=type(exc).__name__)]

    def _opensearch_evidence(self, candidate: CandidateEvent) -> list[EvidenceItem]:
        try:
            start, end = _time_bounds(candidate)
            data = self.opensearch.search(
                self.opensearch_index,
                {
                    "size": 3,
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "multi_match": {
                                        "query": candidate.likely_dependency if candidate.likely_dependency != "unknown" else candidate.service,
                                        "fields": ["service.name", "k8s.deployment.name", "message", "body"],
                                    }
                                },
                                {"range": {"@timestamp": {"gte": _iso_utc(start), "lte": _iso_utc(end)}}},
                            ]
                        },
                    },
                },
            )
            hits = data.get("hits", {})
            total = hits.get("total", 0)
            if isinstance(total, dict):
                total = total.get("value", 0)
            excerpts = [_redact(_hit_text(hit)) for hit in hits.get("hits", [])[:3]]
            return [EvidenceItem(source="log", reference=f"{self.opensearch_index}:bounded-search", summary=f"count={total} excerpts={excerpts}")]
        except Exception as exc:
            return [EvidenceItem(source="enrichment_failure", reference="opensearch", summary=type(exc).__name__)]

    def _kubernetes_evidence(self, candidate: CandidateEvent) -> list[EvidenceItem]:
        service = self._service(candidate)
        if service is None:
            return []
        try:
            deployment = self.kubernetes.get_deployment(service.namespace, service.name)
            pods = self.kubernetes.list_pods(service.namespace).get("items", [])
            related_pods = [pod for pod in pods if pod.get("metadata", {}).get("name", "").startswith(f"{service.name}-")]
            restarts = sum(
                status.get("restartCount", 0)
                for pod in related_pods
                for status in pod.get("status", {}).get("containerStatuses", [])
            )
            ready = sum(1 for pod in related_pods if _pod_ready(pod))
            status = deployment.get("status", {})
            desired = deployment.get("spec", {}).get("replicas", 0)
            available = status.get("availableReplicas", 0)
            rollout = "complete" if desired == available and desired else "incomplete"
            return [
                EvidenceItem(
                    source="kubernetes",
                    reference=f"{service.namespace}/{service.name}",
                    summary=f"pod_restarts={restarts} ready_pods={ready}/{len(related_pods)} available_replicas={available}/{desired} rollout={rollout}",
                )
            ]
        except Exception as exc:
            return [EvidenceItem(source="enrichment_failure", reference="kubernetes", summary=type(exc).__name__)]

    def _service(self, candidate: CandidateEvent) -> Any:
        if self.runtime_config is None:
            return None
        target = candidate.likely_dependency if candidate.likely_dependency != "unknown" else candidate.service
        return next((service for service in self.runtime_config.topology.services if service.name == target), None)


def _span_has_error(span: dict) -> bool:
    return any(tag.get("key") == "error" and tag.get("value") for tag in span.get("tags", []))


def _span_service(trace: dict, span: dict) -> str:
    process_id = span.get("processID")
    return trace.get("processes", {}).get(process_id, {}).get("serviceName", "unknown")


def _hit_text(hit: dict) -> str:
    source = hit.get("_source", {})
    for key in ("message", "body", "log"):
        value = source.get(key)
        if value:
            return str(value)[:240]
    return str(source)[:240]


def _redact(value: str) -> str:
    value = re.sub(r"(?i)(password|token|secret|api[_-]?key)=\S+", r"\1=[REDACTED]", value)
    return re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[REDACTED_EMAIL]", value)


def _pod_ready(pod: dict) -> bool:
    return any(condition.get("type") == "Ready" and condition.get("status") == "True" for condition in pod.get("status", {}).get("conditions", []))


def _time_bounds(candidate: CandidateEvent) -> tuple[int, int]:
    end = candidate.timestamp or int(time.time())
    return end - _window_seconds(candidate.window), end


def _window_seconds(window: str) -> int:
    match = re.fullmatch(r"(\d+)([smhd])", window.strip())
    if not match:
        return 0
    value = int(match.group(1))
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]


def _iso_utc(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")
