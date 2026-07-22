# Evidence Corroboration and Trace RCA

## Goal

Use bounded OpenSearch log evidence and Jaeger trace evidence to improve metric anomaly confidence and identify upstream root causes without making telemetry integrations mandatory for detection.

## Data Flow

1. Run metric anomaly detection and the normal-growth gate as today.
2. Keep hard failures (`error_rate`, OOM, and decreasing `ready_pods`) at their metric confidence.
3. For remaining findings, query logs and traces for the affected service within the 900-second detection tail.
4. Adjust confidence from structured failure evidence.
5. Pass adjusted findings and trace root evidence to RCA.
6. Prefer the earliest failing service on a valid dependency path. Latency-only spans remain impact evidence, not root cause evidence.

## Corroboration Rules

| Evidence | Confidence |
| --- | --- |
| Hard metric failure | unchanged |
| Error log and error trace | `min(1.0, metric + 0.30)` |
| Error log or error trace | `min(1.0, metric + 0.15)` |
| No failure evidence | `metric * 0.50` |
| Integration unavailable or failed | unchanged |

Logs count as failure evidence only when the bounded query matches error severity or failure terms such as exception, timeout, connection refused, OOM, or retry exhausted. Ordinary service logs do not corroborate an anomaly.

Traces count as failure evidence when a span has `error=true`, OTel status `ERROR`, HTTP status at least 500, or a timeout marker. A slow span without a failure marker does not corroborate a root cause.

## Trace-Based RCA

Structured trace evidence records the failing service, operation, timestamp, trace reference, and failure kind. RCA may nominate a trace-derived service without a metric anomaly when:

- the service belongs to the configured topology;
- it is on a dependency path related to the affected service; and
- its failure span precedes downstream failures in the same trace.

The earliest valid failure span receives trace-root priority. Existing graph, drift, and correlation ranking remains the fallback when trace evidence is absent or unavailable.

## Integration Boundary

Reuse the existing `Enricher`, `JaegerClient`, and `OpenSearchClient`. Add one structured corroboration method to `Enricher`; do not add collectors or dependencies. The pipeline calls it after anomaly detection and before RCA. Existing candidate enrichment remains unchanged.

New hyperparameters:

- `evidence_window_seconds`: `900`
- `no_evidence_multiplier`: `0.50`
- `single_evidence_bonus`: `0.15`
- `dual_evidence_bonus`: `0.30`

## Failure Handling

An integration exception produces an unavailable state, not an empty-evidence state. Unavailable telemetry never lowers metric confidence and never stops the pipeline. Query results and excerpts continue to use the existing redaction behavior.

## Tests

- Hard failures bypass confidence reduction.
- One and two evidence sources apply the configured bonuses.
- Successful empty queries lower non-hard confidence.
- Failed or unconfigured integrations preserve confidence.
- Slow traces without failure markers do not become root causes.
- Earliest failing upstream span can become the RCA root.
- All external queries are bounded to the 900-second tail.
