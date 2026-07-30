# SLO Notification and RCA Priority

## Goal

When latency or error rate exceeds its configured SLO, always create an incident notification and use that breach to prioritize RCA.

## Design

- Enable the existing latency and service error-rate threshold detectors. Their incidents continue through the existing deduplication and notification flow.
- Feed breached SLO incidents into RCA as impact findings, even when the anomaly algorithms did not independently flag the metric.
- Keep latency and error rate as impact signals only: they may drive correlation but must not appear in `root_cause_metrics`.
- Keep error rate as a hard-failure gate so normal-growth suppression cannot hide a real SLO failure.
- When either signal breaches, correlate non-context RCA metrics against it. When both breach, use the stronger correlation from both impact series for each candidate.

## Data Flow

`SLO detector -> incident/dedup/notification -> impact finding -> RCA correlation -> ranked root cause`

Notification remains valid even when RCA cannot identify a credible cause. Existing evidence corroboration and normal-growth suppression remain unchanged.

## Verification

- A latency value above its SLO emits the configured notification.
- A service error-rate value above its SLO emits the configured notification.
- A latency or error-rate breach increases correlation evidence for matching non-impact RCA candidates without labeling either impact signal as the root cause.
- Error-rate findings still activate the hard-failure gate.
- Existing test suite remains green.
