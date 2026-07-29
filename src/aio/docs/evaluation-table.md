# Evaluation Table

## Evaluation Outputs

| Evaluation artifact | Input data | Runner / command | Scope | Cases | Detection / notification result | RCA result | Timing | Notes |
|---|---|---|---|---:|---|---|---|---|
| `evaluate/e2e_pipeline_report.json` | `dataset/RE2-SS` + `dataset/RE3-SS` | `python -B evaluate/e2e_pipeline.py --out evaluate/e2e_pipeline_report.json` | Offline benchmark detector/RCA baseline | 120 | Incident precision `1.00`, recall `1.00`, F1 `1.00` (`TP=120`, `FP=0`, `FN=0`) | RCA top-k precision `0.078`, recall `0.392`, F1 `0.131`; top-k hit `0.308` | N/A | Benchmark data only. No normal/no-incident cases, so `TN=0`. |
| `evaluate/current_pipeline_report.json` | `dataset/RE2-SS` + `dataset/RE3-SS` | `python -B evaluate/current_pipeline.py --out evaluate/current_pipeline_report.json` | Current anomaly engine on same benchmark set | 120 | Incident precision `1.00`, recall `1.00`, F1 `1.00` (`TP=120`, `FP=0`, `FN=0`) | RCA top-k precision `0.172`, recall `0.858`, F1 `0.286`; top-k hit `0.850` | N/A | Shows current engine improves RCA hit rate versus the legacy e2e baseline. |
| `evaluate/mandate15_live_report.json` | `evaluate/dataset/mandate15_live` | `python -m aiops.cli replay --dataset evaluate/dataset/mandate15_live --out evaluate/mandate15_live_report.json` | Mandate 15 live replay evidence | 4 | Precision `1.00`, recall `1.00`, false positives `0`, false negatives `0` | N/A | Average lead time `29.5s`; lead times `[0.0, 59.0]` | Uses live Prometheus capture cases for checkout normal, high-load healthy, real incident, and masking. |
| `evaluate/live_notification_eval_report.json` | `evaluate/dataset/mandate15_live` + `evaluate/dataset/mandate7b_live` | `python evaluate/live_notification_eval.py --progress` | Notification pipeline evaluation over live-labeled datasets | 12 total, 10 runnable | Notification precision `1.00`, recall `1.00`, F1 `1.00` (`TP=5`, `TN=5`, `FP=0`, `FN=0`) | Root top-1 precision `0.00`, recall `0.00`, F1 `0.00`; top-1 hit `0.00` | Average detection latency `402.6s`, min `195s`, max `836s` over 5 incident cases | Skips `mandate7b_live/burn_rate_normal_baseline` and `mandate7b_live/burn_rate_real_incident` because those are state-only evidence without `metric_series.json`. |

## Dataset / Evidence Inventory

| Path | Type | Case / artifact count | Source | Used by | Notes |
|---|---|---:|---|---|---|
| `dataset/RE2-SS` | Offline benchmark dataset | 90 cases with `simple_metrics.csv` | Prebuilt benchmark files | `e2e_pipeline.py`, `current_pipeline.py` | Not live Prometheus capture. Case IDs appear as `RE2-SS/...` in reports. |
| `dataset/RE3-SS` | Offline benchmark dataset | 30 cases with `simple_metrics.csv` | Prebuilt benchmark files | `e2e_pipeline.py`, `current_pipeline.py` | Not live Prometheus capture. Case IDs appear as `RE3-SS/...` in reports. |
| `evaluate/dataset/mandate15_live` | Live replay dataset | 4 labeled cases | `live_prometheus_capture` from `localhost:9090` | `aiops.cli replay`, `live_notification_eval.py` | Each case has `label.json`; Prometheus-captured cases also have `metric_series.json` and `simple_metrics.csv`. |
| `evaluate/dataset/mandate7b_live` | Live evidence dataset | 8 labeled case folders plus incident dump JSONs | Mostly `live_prometheus_capture`; burn-rate cases are `live_run_state` | `live_notification_eval.py`; Mandate 7b docs/evidence | Burn-rate case folders are state-only and get skipped by `live_notification_eval.py`; other cart/checkout cases are Prometheus captures. |
| `backups/mandate7b_live_original_before_precision_prune` | Backup snapshot | 3 incident dump JSONs | Archived before precision prune | Provenance only | Contains original `cart`, `checkout_memory`, and `checkout_p95` final incident dumps before pruning. |
| `backups/state_7b_before_precision_state_prune` | Backup state snapshot | 4 scenario state folders | Archived SQLite/JSONL runtime state | Provenance only | Contains `s2-cart`, `s3-burn-rate`, `s4-checkout-memory`, and `s5-checkout-p95` state before prune. |
| `backups/state/15` | Backup state snapshot | 3 scenario state folders | Archived SQLite/JSONL runtime state | Provenance only | Contains checkout, checkout-masking, and checkout-real-incident state for Mandate 15. |
| `backups/state/7b` | Backup state snapshot | 4 scenario state folders | Archived SQLite/JSONL runtime state | Provenance only | Contains current backed-up 7b state for cart, burn-rate, checkout-memory, and checkout-p95. |

## Short Read

`RE2-SS` and `RE3-SS` are benchmark datasets for offline detector/RCA evaluation. `mandate15_live` and most of `mandate7b_live` are live Prometheus capture datasets. The backup folders are not primary evaluation inputs; they preserve old live runtime state and incident dumps so the pruning/retuning history can be audited.
