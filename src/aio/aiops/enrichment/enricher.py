#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from aiops.config.hyperparameters import load_hyperparameters
from aiops.schemas import AnomalyFinding, CandidateEvent, EvidenceItem, Feature, TelemetryCorroboration
from aiops.schemas import RuntimeConfig
from aiops.shared.evidence import log_search_summary, trace_summary
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
        hyperparameters: dict[str, int | float] | None = None,
    ):
        hyperparameters = hyperparameters or load_hyperparameters(Path("config/hyperparameters.json"))["enrichment"]
        self.runtime_config = runtime_config
        self.jaeger = jaeger
        self.opensearch = opensearch
        self.kubernetes = kubernetes
        self.opensearch_index = opensearch_index
        self.corroboration_log_hits = int(hyperparameters["corroboration_log_hits"])
        self.corroboration_trace_limit = int(hyperparameters["corroboration_trace_limit"])
        self.corroboration_trace_max_request_seconds = float(hyperparameters["corroboration_trace_max_request_seconds"])
        self.trace_evidence_limit = int(hyperparameters["trace_evidence_limit"])
        self.log_evidence_hits = int(hyperparameters["log_evidence_hits"])
        self.log_excerpt_max_chars = int(hyperparameters["log_excerpt_max_chars"])

    def close(self) -> None:
        for client in (self.jaeger, self.opensearch, self.kubernetes):
            close = getattr(client, "close", None)
            if callable(close):
                close()

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

    def corroborate(self, findings: list[AnomalyFinding], window_seconds: int) -> dict[str, TelemetryCorroboration]:
        by_service: dict[str, list[AnomalyFinding]] = {}
        for finding in findings:
            by_service.setdefault(finding.service, []).append(finding)
        return {
            service: self._corroborate_service(service, max(item.timestamp for item in items), window_seconds)
            for service, items in by_service.items()
        }

    def _corroborate_service(self, service: str, end: int, window_seconds: int) -> TelemetryCorroboration:
        update: dict[str, Any] = {"service": service, "available_sources": set()}
        if self.opensearch is not None:
            try:
                data = self.opensearch.search(
                    self.opensearch_index,
                    {
                        "size": self.corroboration_log_hits,
                        "query": {
                            "bool": {
                                "must": [
                                    {"multi_match": {"query": service, "fields": ["service.name", "k8s.deployment.name"]}},
                                    {"simple_query_string": {"query": "exception | timeout | failed | failure | connection refused | oom | retry exhausted", "fields": ["message", "body", "log"]}},
                                ],
                                "filter": [{"range": {"@timestamp": {"gte": _iso_utc(end - window_seconds), "lte": _iso_utc(end)}}}],
                            }
                        },
                    },
                )
                update["available_sources"].add("log")
                hits = data.get("hits", {})
                total = hits.get("total", 0)
                count = int(total.get("value", 0) if isinstance(total, dict) else total)
                hit = next(iter(hits.get("hits", [])), {})
                excerpt = _redact(_hit_text(hit, self.log_excerpt_max_chars)) if hit else None
                classification = _classify_log(excerpt or "") if count else None
                update.update(
                    log_failure=classification == "hard_failure",
                    log_classification=classification,
                    log_failure_count=count,
                    log_failure_timestamp=_log_timestamp(hit, end) if hit else None,
                    log_reference=f"{hit.get('_index', self.opensearch_index)}/{hit.get('_id', 'unknown')}" if hit else None,
                    log_excerpt=excerpt,
                )
            except Exception:
                pass
        if self.jaeger is not None:
            try:
                traces = self.jaeger.search_traces(service, limit=self.corroboration_trace_limit, start=(end - window_seconds) * 1_000_000, end=end * 1_000_000).get("data", [])
                update["available_sources"].add("trace")
                failures = [
                    (_span_depth(trace, span), int(span.get("startTime", end * 1_000_000)) // 1_000_000, trace, span)
                    for trace in traces
                    for span in trace.get("spans", [])
                    if _span_is_corroborating_failure(span, window_seconds, self.corroboration_trace_max_request_seconds)
                ]
                if failures:
                    _, timestamp, trace, span = min(failures, key=lambda item: (item[0], item[1]))
                    trace_id = str(trace.get("traceID", "unknown"))
                    update.update(
                        trace_failure=True,
                        trace_root_service=_span_service(trace, span),
                        trace_failure_timestamp=timestamp,
                        trace_reference=self.jaeger.trace_ui_url(trace_id),
                        trace_id=trace_id,
                        trace_operation=str(span.get("operationName", "unknown")),
                        trace_status=_span_failure_status(span),
                        trace_duration_ms=float(span.get("duration", 0)) / 1000,
                    )
                    if self.opensearch is not None:
                        trace_log = self._trace_log_failure(trace_id, timestamp, window_seconds)
                        if trace_log.get("log_failure") or not update.get("log_failure"):
                            update.update(trace_log)
                elif traces:
                    trace = traces[0]
                    span = next((item for item in trace.get("spans", []) if not _span_is_control_stream(item)), {})
                    trace_id = str(trace.get("traceID", "unknown"))
                    if span:
                        update.update(
                            trace_root_service=_span_service(trace, span),
                            trace_reference=self.jaeger.trace_ui_url(trace_id),
                            trace_id=trace_id,
                            trace_operation=str(span.get("operationName", "unknown")),
                            trace_status=_span_status(span),
                            trace_duration_ms=float(span.get("duration", 0)) / 1000,
                        )
            except Exception:
                pass
        return TelemetryCorroboration(**update)

    def _trace_log_failure(self, trace_id: str, timestamp: int, window_seconds: int) -> dict[str, Any]:
        data = self.opensearch.search(
            self.opensearch_index,
            {
                "size": self.corroboration_log_hits,
                "query": {
                    "bool": {
                        "must": [
                            {"multi_match": {"query": trace_id, "fields": ["trace_id", "traceid", "trace.id", "span_id", "spanid", "message", "body", "log"]}},
                            {"simple_query_string": {"query": "exception | timeout | failed | failure | connection refused | oom | retry exhausted", "fields": ["message", "body", "log"]}},
                        ],
                        "filter": [{"range": {"@timestamp": {"gte": _iso_utc(timestamp - window_seconds), "lte": _iso_utc(timestamp + window_seconds)}}}],
                    }
                },
            },
        )
        hits = data.get("hits", {})
        total = hits.get("total", 0)
        count = int(total.get("value", 0) if isinstance(total, dict) else total)
        hit = next(iter(hits.get("hits", [])), {})
        excerpt = _redact(_hit_text(hit, self.log_excerpt_max_chars)) if hit else None
        classification = _classify_log(excerpt or "") if count else None
        return {
            "log_failure": classification == "hard_failure",
            "log_classification": classification,
            "log_failure_count": count,
            "log_failure_timestamp": _log_timestamp(hit, timestamp) if hit else None,
            "log_reference": f"{hit.get('_index', self.opensearch_index)}/{hit.get('_id', 'unknown')}" if hit else None,
            "log_excerpt": excerpt,
        }

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
                limit=self.trace_evidence_limit,
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
            link = self.jaeger.trace_ui_url(trace_id)
            status = _span_failure_status(span) if _span_has_failure(span) else _span_status(span)
            return [
                EvidenceItem(
                    source="trace",
                    reference=link,
                    summary=trace_summary(
                        trace_id,
                        str(operation),
                        status,
                        float(span.get("duration", 0) or 0) / 1000,
                        link,
                        downstream=service,
                        observed=not _span_has_failure(span),
                    ),
                )
            ]
        except Exception as exc:
            return [EvidenceItem(source="enrichment_failure", reference="jaeger", summary=type(exc).__name__)]

    def _opensearch_evidence(self, candidate: CandidateEvent) -> list[EvidenceItem]:
        try:
            start, end = _time_bounds(candidate)
            data = self.opensearch.search(
                self.opensearch_index,
                {
                    "size": self.log_evidence_hits,
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
            excerpts = [_redact(_hit_text(hit, self.log_excerpt_max_chars)) for hit in hits.get("hits", [])[: self.log_evidence_hits]]
            return [EvidenceItem(source="log", reference=f"{self.opensearch_index}:bounded-search", summary=log_search_summary(int(total), excerpts))]
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


def _span_has_failure(span: dict) -> bool:
    tags = {str(tag.get("key", "")).lower(): tag.get("value") for tag in span.get("tags", [])}
    status = str(tags.get("otel.status_code", tags.get("status.code", ""))).upper()
    try:
        http_error = int(tags.get("http.status_code", tags.get("http.response.status_code", 0))) >= 500
    except (TypeError, ValueError):
        http_error = False
    text = f"{span.get('operationName', '')} {tags}".lower()
    return _span_has_error(span) or status == "ERROR" or http_error or "timeout" in text or "timed out" in text


def _span_is_corroborating_failure(span: dict, window_seconds: int, max_request_seconds: float) -> bool:
    if not _span_has_failure(span):
        return False
    if _span_is_control_stream(span):
        return False
    duration_seconds = float(span.get("duration", 0) or 0) / 1_000_000
    return duration_seconds <= min(float(window_seconds), max_request_seconds)


def _span_is_control_stream(span: dict) -> bool:
    operation = str(span.get("operationName", "")).lower()
    return any(marker in operation for marker in ("eventstream", "event_stream", "subscribe", "watch"))


def _span_failure_status(span: dict) -> str:
    tags = {str(tag.get("key", "")).lower(): tag.get("value") for tag in span.get("tags", [])}
    status = str(tags.get("otel.status_code", tags.get("status.code", ""))).upper()
    if status:
        return status
    http_status = tags.get("http.status_code", tags.get("http.response.status_code"))
    return f"HTTP_{http_status}" if http_status else ("ERROR" if _span_has_error(span) else "TIMEOUT")


def _span_status(span: dict) -> str:
    tags = {str(tag.get("key", "")).lower(): tag.get("value") for tag in span.get("tags", [])}
    status = str(tags.get("otel.status_code", tags.get("status.code", ""))).upper()
    if status:
        return status
    http_status = tags.get("http.status_code", tags.get("http.response.status_code"))
    return f"HTTP_{http_status}" if http_status else "OK"


def _span_service(trace: dict, span: dict) -> str:
    process_id = span.get("processID")
    return trace.get("processes", {}).get(process_id, {}).get("serviceName", "unknown")


def _span_depth(trace: dict, span: dict) -> int:
    parents = {
        item.get("spanID"): next((ref.get("spanID") for ref in item.get("references", []) if ref.get("spanID")), None)
        for item in trace.get("spans", [])
    }
    depth = 0
    parent = parents.get(span.get("spanID"))
    seen = set()
    while parent and parent not in seen:
        seen.add(parent)
        depth += 1
        parent = parents.get(parent)
    return depth


def _hit_text(hit: dict, limit: int) -> str:
    source = hit.get("_source", {})
    for key in ("message", "body", "log"):
        value = source.get(key)
        if value:
            return str(value)[:limit]
    return str(source)[:limit]


def _classify_log(text: str) -> str:
    hard_markers = ("exception", "timeout", "timed out", "failed", "failure", "connection refused", "oom", "panic", "fatal", "unavailable", "retry exhausted")
    return "hard_failure" if any(marker in text.lower() for marker in hard_markers) else "soft_failure"


def _log_timestamp(hit: dict, fallback: int) -> int:
    value = hit.get("_source", {}).get("@timestamp")
    if not value:
        return fallback
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return fallback


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
