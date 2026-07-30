# ADR-DETECT-002 — Mandate 7b Live Detection Measurement

> Status: Accepted  
> Owner: Nguyễn Qúy Hưng, Ngô Nguyên Phúc  
> Reviewers:  Phan Đức Huy 
> Last updated: 2026-07-30  
> Related report: `MANDATE-07b-api-runtime-draft.md`

## Context

Mandate #7b requires live proof that an injected fault produces visible detector output, plus precision, recall, and lead-time measured over a labeled incident set. The evidence must be reproducible without adding latency to the application path, creating heavy infrastructure, or allowing the detector to mutate Kubernetes or Flagd.

## Decision

Use the existing in-repository AIOps runtime in `dry-run` mode against live Prometheus telemetry. Each labeled scenario uses an isolated state store and records:

1. A clean baseline/no-alert period.
2. An operator-controlled Flagd fault-start timestamp.
3. The first detector fire and incident fingerprint.
4. Metric/dashboard impact and recovery evidence.
5. A labeled dataset containing labels, captured metric series, and the final unfiltered incident dump.

The primary submission pools three labeled claims:


| Label | Claim                                           | Primary incident   | Lead-time |
| ----- | ----------------------------------------------- | ------------------ | --------- |
| L1    | Cart HTTP error-rate                            | `inc-533e7f658c8f` | 212s      |
| L2    | Checkout p95 latency                            | `inc-97d2a7043a2b` | 322s      |
| L3    | Checkout memory anomaly (saturation substitute) | `inc-788d322c0b2f` | 328s      |


Burn-rate detection is supplemental impact/no-spam proof and is excluded from the labeled-set denominator.

## Measurement Contract

- **Recall:** caught labeled primary incidents / total labeled primary incidents (`3/3 = 100%`).
- **Precision:** fault-attributable fires / all fires in the three isolated stores (`9/11 = 81.8%`).
- **Lead-time:** first detector-fire timestamp minus recorded fault-start timestamp (mean approximately `287s`).
- **Duplicate control:** repeated breaches with the same fingerprint increment `occurrence_count`; they do not create a new incident.
- **False positives:** retain and disclose unrelated detector/RCA fires in the denominator rather than silently removing them.



## Alternatives Considered



### One anecdotal live run

Rejected because it cannot support precision or recall and does not represent the three signal types selected in #7a.

### Combine every run in one state store

Rejected because stale incidents and fingerprints would contaminate scenario attribution and lead-time.

### Treat every same-fault spillover as a false positive

Rejected for the primary mandate-style precision because cart failure legitimately affects both cart and checkout. The report still separates primary TP, same-fault related fires, and unrelated FP so reviewers can recompute a stricter metric.

## Safety and Constraints

- AIOps runtime remains `dry-run`.
- Only the human operator changes Flagd.
- The detector does not mutate Flagd or Kubernetes.
- Collection reads existing telemetry and is off the user request path.
- No new telemetry or ML cluster is introduced.
- State is isolated per scenario through dedicated state, RCA-history, and audit paths.



## Known Limitations

- L3 is a transparent substitute: attempted `local-adHighCpu` did not produce a defensible ad CPU rise; the observed live fire was checkout `memory_usage_bytes`.
- L1 and L2 use separate runs of the same `cartFailure` fault family.
- The mean lead-time is approximately 4.8 minutes and should be improved by tuning evaluation windows without increasing alert noise.
- Precision is reduced by two unrelated latency/RCA fires retained as false positives.



## Evidence and Traceability

- Labeled dataset commit: `[f06f209](https://github.com/tf2-team/tf2-corp-platform/commit/f06f209)`
- Live evidence/runtime commit: `[8a656ac](https://github.com/tf2-team/tf2-corp-platform/commit/8a656ac)`
- Evidence report: `MANDATE-07b-api-runtime-draft.md`
- Scenario metadata: `s2-rerun-meta.txt`, `s3-burn-rate-meta.txt`, `s4-rerun-meta.txt`, `s5-checkout-p95-meta.txt`
- Screenshot pack: `evidence/`



## Consequences

This decision produces a reproducible, reviewable evidence pack and a clear measurement denominator. It also makes the caveats visible: the saturation substitution, same-fault relationship, and remaining false positives must stay in the Jira submission.

## Sign-Off


| Role     | Name                         | Decision | Date | Evidence/comment                                |
| -------- | ---------------------------- | -------- | ---- | ----------------------------------------------- |
| Owner | Ngô Nguyên Phúc, Nguyễn Qúy Hưng | Done | 2026-07-30 | Confirm labeled-set contract and caveats. |
| Reviewer | Phan Đức Huy | Done | 2026-07-30 | Confirm formulas, evidence, and dry-run safety. |


