# AIOps Block I/O Schema

This document describes the current code-level input/output contracts for each pipeline block. Use it to align owners before changing collectors, detectors, topology, remediation, or API contracts.

## Shared Schemas

### Observation

```json
{
  "signal_id": "checkout_bad_ratio_24h",
  "value": 0.02,
  "unit": "ratio",
  "window": "24h",
  "quality": "verified",
  "labels": {
    "service": "checkout"
  }
}
```

Fields:

- `signal_id`: stable signal identifier.
- `value`: numeric signal value, or `null` when missing/stale/invalid.
- `unit`: unit string, for example `ratio`, `seconds`, `count`.
- `window`: measurement window, for example `5m`, `24h`.
- `quality`: one of `unqualified`, `verified`, `fallback-only`, `missing`, `stale`, `invalid`.
- `labels`: source labels after normalization.

### Feature

```json
{
  "signal_id": "checkout_bad_ratio_24h",
  "value": 0.02,
  "unit": "ratio",
  "window": "24h",
  "quality": "verified",
  "status": "ready",
  "labels": {
    "service": "checkout"
  }
}
```

### MetricSeries

Used by the v0.0.1 anomaly/RCA path.

```json
{
  "service": "payment",
  "metric": "latency",
  "signal_id": "payment_latency",
  "points": [
    { "timestamp": 0, "value": 1.0 },
    { "timestamp": 1, "value": 20.0 }
  ]
}
```

`status` is produced by the feature builder:

- `ready`: quality is `verified`.
- `fallback`: quality is `fallback-only`.
- `unknown`: quality is `missing`, `stale`, `invalid`, or `unqualified`; value is forced to `null`.

### CandidateEvent

```json
{
  "detector_id": "ops01_checkout_slo",
  "flow": "checkout",
  "service": "checkout",
  "severity": "SEV1",
  "signal_id": "checkout_bad_ratio_24h",
  "value": 0.02,
  "threshold": 0.01,
  "quality": "verified",
  "reason": "threshold_breached",
  "runbook_id": "RB-CHECKOUT-SLO",
  "likely_dependency": "unknown",
  "confidence": 1.0,
  "contributing_signals": ["checkout_bad_ratio_24h"],
  "evidence": []
}
```

### Incident

```json
{
  "incident_id": "inc-abc123def456",
  "fingerprint": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "state": "open",
  "severity": "SEV1",
  "flow": "checkout",
  "service": "checkout",
  "likely_dependency": "payment",
  "occurrence_count": 1,
  "events": []
}
```

### RuntimeConfig

Loaded from `config/runtime.json`.

```json
{
  "schema_version": "1.0",
  "environment": "tf2",
  "topology": {
    "services": []
  },
  "signals": [],
  "detectors": [],
  "policy": {
    "protected_targets": [],
    "stateful_kinds": [],
    "non_actionable_flows": []
  },
  "rca": {
    "enabled": true
  }
}
```

Detector thresholds and detector confidences live in `config/runtime.json`. Other numeric tuning values stay in `.env`: no-data confidence, remediation replica count, and RCA hyperparameters.

## Block Contracts

### 1. Collector

Code: `aiops.collectors`

Input:

```json
{
  "observations": ["Observation"]
}
```

Output:

```json
{
  "observations": ["Observation"]
}
```

Current behavior: `StaticCollector` returns a copy of the observations passed into the API request. Future Prometheus/Grafana/Jaeger collectors must still output `list[Observation]`.

### 2. Qualification Gate

Code: `aiops.qualification.gate.QualificationGate`

Input:

```json
{
  "observations": ["Observation"]
}
```

Output:

```json
{
  "qualified_observations": ["Observation"]
}
```

Rules:

- If `quality != "unqualified"`, pass through unchanged.
- If `quality == "unqualified"`, output `quality = "fallback-only"` and `value = null`.

### 3. Normalization

Code: `aiops.normalization.normalizer.Normalizer`

Input:

```json
{
  "qualified_observations": ["Observation"]
}
```

Output:

```json
{
  "normalized_observations": ["Observation"]
}
```

Rules:

- Sorts `labels` by key.
- Does not change values, units, windows, or quality.

### 4. Feature Builder

Code: `aiops.features.builder.FeatureBuilder`

Input:

```json
{
  "normalized_observations": ["Observation"]
}
```

Output:

```json
{
  "features": ["Feature"]
}
```

Rules:

- `verified` becomes `status = "ready"`.
- `fallback-only` becomes `status = "fallback"`.
- All other qualities become `status = "unknown"` and `value = null`.

### 5. Detector Engine

Code: `aiops.detectors`

Input:

```json
{
  "features": ["Feature"],
  "detectors": ["DetectorDefinition"]
}
```

Output:

```json
{
  "candidates": ["CandidateEvent"]
}
```

Runtime detector config:

```json
{
  "id": "ops01_checkout_slo",
  "type": "threshold",
  "enabled": true,
  "signal_id": "checkout_bad_ratio_24h",
  "flow": "checkout",
  "service": "checkout",
  "severity": "SEV1",
  "runbook_id": "RB-CHECKOUT-SLO"
}
```

Supported detector types:

- `threshold`: emits when `feature.status == "ready"` and `feature.value > threshold`.
- `dependency`: same threshold rule, but sets `likely_dependency` and configured `confidence`.
- `no-data`: emits when configured signal has `status == "unknown"`.

Thresholds and confidences come from `config/runtime.json`:

```json
{
  "detector_thresholds": {
    "ops01_checkout_slo": 0.01
  },
  "detector_confidences": {
    "ops03_checkout_payment_dependency": 0.8
  }
}
```

Current gap: production anomaly/RCA detectors are intentionally not implemented yet.

### 6. Correlation

Code: `aiops.correlation.correlator.Correlator`

Input:

```json
{
  "candidates": ["CandidateEvent"]
}
```

Output:

```json
{
  "correlated_candidates": ["CandidateEvent"]
}
```

Rules:

- Groups candidates by `(flow, service)`.
- If any candidate has `likely_dependency != "unknown"`, that candidate becomes primary.
- `contributing_signals` is the unique ordered union from the group.
- `confidence` is the max confidence from the group.

### 7. Enrichment

Code: `aiops.enrichment.enricher.Enricher`

Input:

```json
{
  "correlated_candidates": ["CandidateEvent"],
  "features": ["Feature"]
}
```

Output:

```json
{
  "enriched_candidates": ["CandidateEvent"]
}
```

Added evidence item:

```json
{
  "source": "feature",
  "reference": "checkout_bad_ratio_24h",
  "summary": "24h ratio quality=verified"
}
```

Rules:

- For each `contributing_signals` item, attach feature evidence if the feature exists.
- If configured, query Jaeger/OpenSearch/Kubernetes only after candidates exist and attach bounded evidence:
  - `trace`: trace UI reference plus service/operation/duration/error-span summary.
  - `log`: bounded OpenSearch count/excerpts with simple redaction.
  - `kubernetes`: deployment replica/rollout and pod readiness/restart summary.
- Integration failures append `source="enrichment_failure"` evidence instead of blocking incident creation.

### 8. Incident Store / Deduplication

Code: `aiops.storage.sqlite.SQLiteIncidentStore`

Input:

```json
{
  "candidate": "CandidateEvent",
  "environment": "tf2"
}
```

Output:

```json
{
  "incident": "Incident"
}
```

Fingerprint fields:

```text
environment | detector_id | flow | service | likely_dependency
```

Rules:

- New fingerprint creates a new `Incident`.
- Existing fingerprint increments `occurrence_count`, appends event, and keeps the more severe severity by lexical `min`.
- Data is persisted to SQLite WAL.

### 9. Notification Builder

Code: `aiops.notifications.builder.NotificationBuilder`

Input:

```json
{
  "incidents": ["Incident"]
}
```

Output:

```json
{
  "notifications": [
    {
      "incident_id": "inc-abc123def456",
      "severity": "SEV1",
      "state": "open",
      "title": "checkout likely dependency: payment",
      "summary": "dependency_signal_breached on checkout_payment_error_rate_5m",
      "flow": "checkout",
      "service": "checkout",
      "likely_dependency": "payment",
      "runbook_id": "RB-CHECKOUT-DEPENDENCY"
    }
  ]
}
```

Rules:

- If dependency is known, title is `<flow> likely dependency: <dependency>`.
- Otherwise title is `<flow> incident`.

### 10. Policy / Remediation Engine

Code: `aiops.remediation.policy.PolicyEngine`

Input:

```json
{
  "incident": "Incident",
  "policy": "RuntimePolicyConfig",
  "mode": "observe | dry-run | live-approved"
}
```

Intermediate proposal:

```json
{
  "action_type": "restart",
  "target": "payment",
  "target_kind": "Deployment",
  "replicas": 3,
  "mutating": true,
  "verification_defined": true,
  "rollback_defined": true,
  "cost_changing": false,
  "cost_status_current": true,
  "approved": false
}
```

Output:

```json
{
  "allowed": false,
  "result": "dry-run-recorded",
  "reasons": ["mode_not_live_approved"],
  "executed": false
}
```

Rules:

- No proposal is created for `incident.flow` in `non_actionable_flows`.
- Blocks protected targets, stateful targets, single replica targets, missing verification, missing rollback, stale cost status, and missing approval.
- `observe` and `dry-run` never execute.
- `live-approved` can allow only approved safe proposals.

### 11. Verification

Code: `aiops.verification.engine.VerificationEngine`

Input:

```json
{
  "incidents": ["Incident"],
  "features": ["Feature"]
}
```

Output:

```json
{
  "verification_results": [
    {
      "incident_id": "inc-abc123def456",
      "status": "not_recovered",
      "reason": "threshold_still_firing"
    }
  ]
}
```

Rules:

- Missing or non-ready verification feature returns `inconclusive`.
- If event has a threshold and latest feature value is `<= threshold`, returns `recovered`.
- Otherwise returns `not_recovered`.

### 12. Pipeline API

Code: `aiops.api.app`

Request:

```json
{
  "observations": ["Observation"],
  "metric_series": ["MetricSeries"]
}
```

Response:

```json
{
  "observations": ["Observation"],
  "features": ["Feature"],
  "candidates": ["CandidateEvent"],
  "incidents": ["Incident"],
  "notifications": ["NotificationMessage"],
  "policy_decisions": ["PolicyDecision"],
  "verification_results": ["VerificationResult"],
  "rca_result": {
    "anomalies": ["AnomalyFinding"],
    "root_causes": ["RootCauseCandidate"]
  }
}
```

### 12a. v0.0.1 Anomaly / RCA

Code: `aiops.anomaly`, `aiops.rca`

Input:

```json
{
  "metric_series": ["MetricSeries"]
}
```

Output:

```json
{
  "anomalies": [
    {
      "algorithm": "ewma_stl",
      "service": "payment",
      "metric": "latency",
      "signal_id": "payment_latency",
      "score": 13.3,
      "timestamp": 7
    }
  ],
  "root_causes": [
    {
      "service": "payment",
      "score": 19.0,
      "root_cause_metrics": ["latency", "error"],
      "evidence": ["latency robust_score=19.000"]
    }
  ]
}
```

Rules:

- `ewma_stl`: univariate EWMA with optional seasonal residual.
- `isolation_forest`: per-service multivariate isolation-style score using robust metric deviations.
- `baro_bocpd`: calls BARO `baro.anomaly_detection.bocpd` on a DataFrame shaped like `time, <service>_<metric>, ...`.
- `graph_traversal_rca`: propagates service anomaly scores through `config/runtime.json` topology.
- `robust_score_rca`: calls BARO `baro.root_cause_analysis.robust_scorer`; ranks are mapped back from `<service>_<metric>` into `RootCauseCandidate`.

Endpoints:

- `GET /health/live` -> `HealthResponse`
- `POST /api/v1/pipeline/run` -> `PipelineResult`
- `GET /api/v1/incidents` -> `list[Incident]`
- `POST /api/v1/events/grafana` -> `GrafanaNormalizedEvent`

### 13. Grafana Webhook

Input:

```json
{
  "receiver": "aiops",
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "CheckoutSLOBreach",
        "severity": "SEV1"
      },
      "startsAt": "2026-07-14T00:00:00Z",
      "annotations": {}
    }
  ]
}
```

Output:

```json
{
  "schema_version": "1.0",
  "source": "grafana",
  "status": "firing",
  "alert_id": "CheckoutSLOBreach",
  "received_at": "2026-07-15T00:00:00+00:00",
  "starts_at": "2026-07-14T00:00:00Z",
  "ends_at": null,
  "labels": {
    "alertname": "CheckoutSLOBreach",
    "severity": "SEV1"
  },
  "annotations_redacted": {},
  "links": {
    "generator": null,
    "dashboard": null,
    "panel": null
  }
}
```

Rules:

- Requires `x-aiops-grafana-secret`.
- Uses first alert in payload.
- Redacts by truncating annotation values to 2048 chars.
