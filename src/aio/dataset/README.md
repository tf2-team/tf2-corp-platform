# AIOps Evaluation Dataset

## Purpose

This directory contains the dataset used to evaluate the AIOps anomaly detection and RCA pipeline. Each case represents one fault-injection run and includes metrics, logs, the injection timestamp, and an expected root-cause label.

The current dataset does not include normal/no-incident cases. Every case in `label.json` has `expected_incident: true`, so TN/FP metrics are not very meaningful until a normal dataset is added.

## Dataset Source

The dataset is derived from RCAEval, a benchmark for root-cause analysis of microservice systems with telemetry data: <https://arxiv.org/abs/2412.17015>.

RCAEval provides large-scale microservice failure datasets and an evaluation environment for RCA. The paper reports three datasets with 735 failure cases collected from three microservice systems, covering multiple real-world fault types.

The local dataset subset is based on the Sock Shop microservice benchmark workload.

`RE2-SS` contains Sock Shop fault-injection runs collected from the running system. These cases cover resource and network-style faults such as CPU, memory, disk, latency/delay, packet loss, and socket/network pressure.

`RE3-SS` follows the same Sock Shop service context, but the faults are expert-seeded code-level failures. In other words, specialists injected faulty behavior into the application code or service behavior, then collected the resulting metrics/logs/traces for evaluation.

Both suites are used as labeled incident cases for testing whether the AIOps pipeline can detect an incident and rank the expected root-cause service.

## Directory Structure

```text
dataset/
  RE2-SS/
    <fault_name>/
      <run_id>/
        simple_metrics.csv
        metrics.csv
        logs.csv
        logts.csv
        inject_time.txt
        cluster_info.json
        pod-node-1.csv
        pod-node-2.csv
  RE3-SS/
    <fault_name>/
      <run_id>/
        simple_metrics.csv
        metrics.csv
        logs.csv
        traces.csv
        inject_time.txt
        metrics.png
```

Current summary:

| Item | Value |
|---|---:|
| Total cases | 120 |
| RE2-SS cases | 90 |
| RE3-SS cases | 30 |
| Fault scenarios | 39 |
| Normal/no-incident cases | 0 |
| Anomaly/incident cases | 120 |
| Samples per `simple_metrics.csv` | 1441 |
| Sample interval | 1 second |
| Duration per case | 1440 seconds / 24 minutes |
| Pre-injection window | 720 seconds / 12 minutes |
| Post-injection window | 720 seconds / 12 minutes |

## Label File

`label.json` is the main machine-readable label file for evaluators. Each record in `cases` maps to one dataset case.

Important fields:

| Field | Meaning |
|---|---|
| `case_id` | Case-relative path, for example `RE2-SS/payment_cpu/1`. |
| `suite` | Dataset suite: `RE2-SS` or `RE3-SS`. |
| `fault_name` | Scenario/fault folder name. |
| `run_id` | Repeated run ID for the same scenario. |
| `expected_incident` | Always `true` in the current dataset. |
| `root_cause_service` | Expected root-cause service, derived from the folder name. |
| `root_cause_metric_family` | Expected metric family when derivable: cpu, mem, disk, latency, error, socket. |
| `fault_type` | Fault suffix from the folder name, for example cpu, mem, delay, loss, f1. |
| `anomaly_window` | Window from `inject_time.txt` to the end of the case. |
| `data_window` | Start/end timestamp, duration, and sample count from `simple_metrics.csv`. |
| `row_counts` | Data row counts for each file in the case. |
| `column_counts` | Column counts for each file in the case. |
| `files` | Files present in the case directory. |

## Label Derivation

The current labels are weak labels derived from the folder name and `inject_time.txt`.

Service mapping:

```text
<prefix>_<fault_type> -> root_cause_service = <prefix>
```

Examples:

```text
payment_cpu      -> service payment, metric family cpu
catalogue_mem    -> service catalogue, metric family mem
orders_delay     -> service orders, metric family latency
user_loss        -> service user, metric family error
carts_socket     -> service carts, metric family socket
front-end_f1     -> service front-end, service-level fault
```

Metric-family mapping:

| Suffix | `root_cause_metric_family` |
|---|---|
| `_cpu` | `cpu` |
| `_mem` | `mem` |
| `_disk` | `disk` |
| `_delay` | `latency` |
| `_loss` | `error` |
| `_socket` | `socket` |
| `_f1`, `_f2`, `_f3`, `_f4` | `null`; service-only evaluation |

Anomaly window:

```text
case_start = first time in simple_metrics.csv
inject_time = value in inject_time.txt
case_end = last time in simple_metrics.csv
```

All 120 cases currently have the same time shape:

```text
inject_time - case_start = 720 seconds
case_end - inject_time = 720 seconds
case_end - case_start = 1440 seconds
```

This means the first 12 minutes are the baseline/pre-injection window and the last 12 minutes are the post-injection/anomaly window.

## File Contract

### `simple_metrics.csv`

Compact metric table used directly by the current evaluator. Each record is one timestamp at a 1-second interval.

Record format:

```text
time,<service>_cpu,<service>_mem,<service>_diskio,<service>_socket,<service>_workload,<service>_error,<service>_latency-50,<service>_latency-90,...
```

Statistics:

| Suite | Files | Rows per file | Columns |
|---|---:|---:|---:|
| RE2-SS | 90 | 1441 | 75-83 |
| RE3-SS | 30 | 1441 | 81-108 |

### `metrics.csv`

Expanded metric table with raw metric names. Each record is also one timestamp at a 1-second interval.

Statistics:

| Suite | Files | Rows per file | Columns |
|---|---:|---:|---:|
| RE2-SS | 90 | 1441 | 434-443 |
| RE3-SS | 30 | 1441 | 438-551 |

### `logs.csv`

Raw log records for the case window.

Common fields:

```text
time,timestamp,container_name,message,level,req_path,error
```

RE3-SS log files currently have 6 columns, while RE2-SS log files have 7 columns. Row counts vary by traffic and fault, ranging roughly from 41k to 93k records per case.

### `logts.csv`

Only present in RE2-SS. This is a log-template time-series file where each column after `time` represents a template ID/container template count.

Statistics:

```text
90 files, 96-97 rows, 50-575 columns
```

### `traces.csv`

Present in some RE3-SS cases. The current files contain trace headers but no trace rows.

Fields:

```text
time,traceID,spanID,serviceName,methodName,operationName,startTimeMillis,startTime,duration,statusCode,parentSpanID
```

### `inject_time.txt`

Contains the Unix timestamp for the fault injection start. The evaluator uses this timestamp to define the anomaly window.

### `cluster_info.json`, `pod-node-*.csv`

Present in RE2-SS. `cluster_info.json` describes log templates and container mappings. `pod-node-*.csv` files contain pod-to-node placement snapshots.

## Data Characteristics

- The dataset is case-based time-series data, not independent tabular records.
- Each case has a 12-minute baseline window and a 12-minute anomaly window.
- Labels are service-level RCA labels. Metric-family labels are available only for cpu/mem/disk/delay/loss/socket suffixes.
- The dataset is incident-only: there are no normal/no-incident cases.
- Because of this imbalance, the dataset is more useful for RCA hit-rate and recall than for full binary classification precision with TN.
- `simple_metrics.csv` is the main input for the current evaluator. The remaining files are evidence/debug data or inputs for future evaluator extensions.
- Some service names come from the original dataset and differ from the current TechX runtime naming, for example `front-end`, `catalogue`, `carts`, and `orders`. Add aliases if this dataset needs to be evaluated directly against the current runtime topology.

## Running the Evaluator

From `src/aio`:

```powershell
.\.venv\Scripts\python.exe evaluate\e2e_pipeline.py --dataset dataset --out evaluate\e2e_pipeline_report.json
```

Or run the current pipeline evaluator:

```powershell
.\.venv\Scripts\python.exe evaluate\current_pipeline.py --dataset dataset --out evaluate\current_pipeline_report.json
```
