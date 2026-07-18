# Labeled Detection and RCA Evaluation

Runner: `evaluate/e2e_pipeline.py`

The runner evaluates the same configured EWMA/STL and Isolation Forest anomaly
engine used by the runtime, then evaluates RCA top-K. It does not infer truth
from folder names: a reviewer-provided label file is mandatory so that normal
periods, false positives, recall, and lead time are measurable.

## Input

Each case directory contains `simple_metrics.csv`. Case IDs are the directories'
paths relative to the dataset root. Labels use this structure:

```json
{
  "cases": {
    "incident/payment_failure_01": {
      "expected_incident": true,
      "expected_root_service": "payment",
      "expected_root_metric": "error_rate",
      "incident_start_timestamp": 1784203200
    },
    "normal/steady_traffic_01": {
      "expected_incident": false
    }
  }
}
```

See `evaluate/labels.example.json`. The real label file should be supplied by
the incident injector or reviewer and must include both incident and normal
cases. Every detected incident case needs an incident start timestamp for a
valid Mandate 7b lead-time report.

## Run

Set required runtime settings through the process environment and disable dotenv
loading when the run must not read local env files:

```powershell
$env:AIOPS_ENV_FILE = "disabled"
python -B evaluate/e2e_pipeline.py `
  --dataset evaluate/dataset `
  --labels path/to/reviewer-labels.json `
  --out evaluate/report.json
```

Arguments:

- `--dataset`: dataset root; default `evaluate/dataset`.
- `--labels`: explicit labels; default `<dataset>/labels.json`.
- `--top-k`: RCA candidate count; default from `config/hyperparameters.json`.
- `--limit`: maximum cases; `0` means all cases.
- `--max-metrics`: maximum series per case; default `40`.
- `--out`: optional full JSON report.

The command fails when there are no cases, the labels file is absent, or any
discovered case lacks a label. `valid_for_mandate_7b` is false when the set has
no incident cases, no normal cases, or detected incidents lack timing labels.

## Metrics

- `incident`: TP/FP/TN/FN, precision, recall, and F1 across the full labeled set.
- `lead_time`: mean and median seconds from labeled incident start to first fire.
- `rca_top_k_hit`: case-level rate where the expected root service/metric appears.
- `rca_top_k`: micro set-overlap showing how clean the candidate list is.

Do not present `labels.example.json` as measurement evidence; it documents the
contract only. Mandate 7b numbers must come from the actual injected/replayed
incident set and its normal observation period.
