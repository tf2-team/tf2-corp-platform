# MANDATE25 real-flow test report

- Run ID: `20260727T015208Z`
- Overall: **FAIL**
- Product: `0PUK6V6EV0` (Solar System Color Imager)

## Results

| Surface | Scenario | Status | Elapsed ms | Result |
|---|---|---:|---:|---:|
| product-reviews | recovery/none | FALLBACK | 13813.0 | FAIL |
| shopping-copilot | recovery/none | GROUNDED | 4203.0 | PASS |

## Infrastructure errors

- None.

## Evidence policy

- No Prometheus, Jaeger, trace, or metric query is used.
- Each result is based on a real gRPC response from the Compose service. Container IDs and scenario JSON are retained beside this report.
- Recovery is verified by recreating the service with `BEDROCK_FAULT_MODE=none` and requiring a successful real request; same-process recovery requires runtime fault-control support in the service.

Raw evidence is stored beside this report in `summary.json` and per-case JSON files.
