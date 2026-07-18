# Evaluation Pipeline

Runner: `evaluate/e2e_pipeline.py`

The runner evaluates anomaly/incident detection and RCA top-K over the existing dataset folder:

```text
evaluate/dataset
```

It does not generate labels, catalog files, incident history, SQLite state, or audit files.

## Run

Run full dataset:

```bash
conda run -n capstone python -B evaluate/e2e_pipeline.py
```

Run first N cases:

```bash
conda run -n capstone python -B evaluate/e2e_pipeline.py --limit 10
```

Write a JSON report:

```bash
conda run -n capstone python -B evaluate/e2e_pipeline.py --out evaluate/report.json
```

## Arguments

`--dataset`

Dataset root. Default: `evaluate/dataset`.

`--top-k`

Number of RCA candidates to evaluate. Default: `AIOPS_RCA_TOP_K` from `.env`.

`--limit`

Maximum number of dataset cases to run. `0` means full dataset.

`--max-metrics`

Maximum metric series loaded per case before RCA. Default: `40`. The runner keeps the metrics with the largest last-point change so full-dataset runs stay practical.

`--incident-threshold`

Robust-score threshold for incident detection. Default: `1.0`. Lower values increase recall and can increase false positives if normal cases exist.

`--out`

Optional report output path. If omitted, only metrics are printed to stdout.

## Labels

The dataset has no explicit label file. The runner derives weak labels from folder names.

Example:

```text
evaluate/dataset/RE2-SS/payment_mem/1/simple_metrics.csv
```

Expected root service: `payment`

Expected metric family: `mem`

Metric family mapping:

```text
_cpu    -> cpu
_mem    -> mem
_disk   -> disk
_delay  -> latency
_loss   -> error
_socket -> socket
_f1..f4 -> service only
```

Every discovered case is treated as `expected_incident = true`. Because there are no normal/no-incident cases, incident `TN` and `FP` are expected to be `0`.

## Metrics

`incident`

Binary incident detection metric.

```text
TP: expected incident and predicted incident
FP: expected normal but predicted incident
TN: expected normal and predicted normal
FN: expected incident but predicted normal
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
f1        = 2 * precision * recall / (precision + recall)
```

`rca_top_k`

Service-level micro set-overlap over RCA top-K.

For each case:

```text
expected = [expected_root_service]
predicted = RCA top-K services
```

Then across all cases:

```text
TP: expected service appears in top-K
FP: predicted top-K service is not expected
FN: expected service is missing from top-K
TN: set to 0; not meaningful without a fixed universe of non-root-cause services
```

This metric answers: how clean is the top-K list?

`rca_top_k_hit`

Case-level hit-rate for RCA top-K.

A case is correct if top-K contains:

```text
expected service
and, when available, expected metric family
```

Example:

```text
expected folder: payment_mem
top-K candidate: payment with root metric containing "mem"
result: hit
```

This metric answers: did RCA include the right root cause anywhere in top-K?

## Current Notes

`rca_top_k.precision` can be low while `rca_top_k.recall` is high because top-K may contain the correct service plus several extra wrong services.

For ranking tasks, `TN` is usually not useful unless the service universe is explicitly defined.
