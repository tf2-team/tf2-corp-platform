# SLO Notification and RCA Priority

## Goal

When latency or error rate exceeds its configured SLO, always create an incident notification and use that breach to prioritize RCA.

## Design

- Enable the existing latency and service error-rate threshold detectors. Their incidents continue through the existing deduplication and notification flow.
- Feed breached SLO incidents into RCA as impact findings, even when the anomaly algorithms did not independently flag the metric.
- Keep latency as an impact signal only: it may drive correlation but must not appear as the primary root-cause metric.
- Keep error rate as a hard-failure signal and allow it to rank as a root cause.
- Correlate non-context RCA metrics against the latency/error-rate impact series so related dependency or infrastructure evidence receives priority.

## Data Flow

`SLO detector -> incident/dedup/notification -> impact finding -> RCA correlation -> ranked root cause`

Notification remains valid even when RCA cannot identify a credible cause. Existing evidence corroboration and normal-growth suppression remain unchanged.

## Verification

- A latency value above its SLO emits the configured notification.
- A service error-rate value above its SLO emits the configured notification.
- A latency breach increases correlation evidence for a matching non-latency RCA candidate without labeling latency as the root cause.
- Existing test suite remains green.
