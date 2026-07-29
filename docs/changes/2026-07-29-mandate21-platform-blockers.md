# Change: Mandate 21 Platform Order Durability, Reconciler Enforcements, and Audit Router CI

## Summary

Enforced mandatory outbox check in production checkout, added 1-minute CloudWatch metric publisher for `AcceptedOrderWithoutDurableRecord`, updated Go reconciler to strictly require exact single RDS PostgreSQL record for ACK when DynamoDB item is absent, and updated audit alert router GitHub Actions workflow with pytest/import smoke test and deployment verification.

## Context

Mandate 21 requires continuous verification of order durability during availability zone fault drills. In production, checkout must never charge payments without guaranteeing durable intent in DynamoDB, and any violation must emit CloudWatch metrics to breach FIS stop alarms. Additionally, the Go reconciler and audit alert router CI workflow require strict validation contracts.

## Before

* Checkout outbox path had no dedicated 1-minute CloudWatch metric publisher for `TechX/Mandate21/AcceptedOrderWithoutDurableRecord`.
* Reconciler treated absent DynamoDB outbox items as durable without asserting that RDS PostgreSQL contained exactly one record.
* Audit alert router deployment workflow lacked automated pre-deployment pytest/import smoke tests and deployed handler/code SHA verification.

## After

* Checkout service enforces mandatory outbox readiness in production before payment charge and publishes `TechX/Mandate21/AcceptedOrderWithoutDurableRecord` metrics every 1 minute.
* Go reconciler CLI strictly asserts `rdsCount == 1` when DynamoDB item is absent before acknowledging durability.
* Audit alert router CI/CD workflow executes pytest and import smoke tests, updates Lambda code, waits for update completion, and verifies deployed handler (`router.handler`) and code SHA.

## Technical Design Decisions

* **Metric Retain on Failure:** If `PutMetricData` fails to publish, the counter is retained so CloudWatch missing data continues to fail closed.
* **Exact Single RDS Record ACK:** In-flight checkout events deleted from DynamoDB after RDS persistence ACK are verified against PostgreSQL with `SELECT COUNT(*) WHERE order_id = $1` returning exactly `1`.

## Implementation Details

1. Updated `src/checkout/main.go` and `src/checkout/go.mod` to add CloudWatch `TechX/Mandate21/AcceptedOrderWithoutDurableRecord` 1-minute metric reporter and production outbox guard.
2. Updated `tools/mandate21-reconcile/main.go` and `main_test.go` to enforce `rdsCount == 1` when DynamoDB item is absent.
3. Updated `.github/workflows/audit-alert-router-deploy.yml` with pytest/import smoke tests and `aws lambda wait function-updated` deployment verification.

## Files Changed

**Configuration & Source:**
* `src/checkout/go.mod` — Added `github.com/aws/aws-sdk-go-v2/service/cloudwatch` dependency.
* `src/checkout/go.sum` — Updated module checksums for CloudWatch SDK.
* `src/checkout/main.go` — Added 1-minute CloudWatch metric reporter and mandatory production outbox guard.
* `tools/mandate21-reconcile/main.go` — Enforced exact single RDS record ACK rule for missing DynamoDB items.
* `tools/mandate21-reconcile/main_test.go` — Added unit test for missing DynamoDB item single RDS record ACK rule.
* `.github/workflows/audit-alert-router-deploy.yml` — Added pytest/import smoke test and deployment verification steps.

**Documentation:**
* `docs/changes/2026-07-29-mandate21-platform-blockers.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-infra/docs/changes/2026-07-29-mandate21-infra-blockers.md`
* Related: `techx-corp-chart/docs/changes/2026-07-29-mandate21-chart-blockers.md`

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Checkout enforces outbox in production and publishes durability metrics; reconciler strictly asserts single RDS record ACK |
| **Infrastructure** | No direct Terraform changes in platform repo |
| **Deployment** | Router Lambda deployment workflow runs automated pytest/import smoke tests and verifies deployed handler |
| **Performance** | Asynchronous 1-minute metric publication adds zero overhead to checkout request path |
| **Security** | Zero sensitive payment data logged or exposed in metrics |
| **Reliability** | Fail-closed metric retention guarantees FIS stop alarm triggers on durability violations |
| **Cost** | Negligible cost for CloudWatch `PutMetricData` (1 metric every 1 minute) |
| **Backward compatibility** | Fully backward-compatible |
| **Observability** | Publishes `TechX/Mandate21/AcceptedOrderWithoutDurableRecord` CloudWatch metric |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Checkout Unit Tests | `go test ./...` in `src/checkout` | ✅ Pass |
| Reconciler Unit Tests | `go test -v ./...` in `tools/mandate21-reconcile` | ✅ Pass |
| Router Unit Tests | `python -m pytest src/audit-alert-router/tests/` | ✅ Pass |

### Manual Verification

* Verified `go test ./...` in `src/checkout` passes after `go mod tidy`.
* Verified `tools/mandate21-reconcile` unit tests pass for all 6 test cases.

### Remaining Verification (Post-Merge)

* Deploy router Lambda to production via GitHub Actions and verify CloudWatch alarm state.

## Migration or Deployment Notes

None.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| CloudWatch rate limit on PutMetricData | Low | Low | Metric errors are logged and counter is retained for next ticker cycle |

**Rollback procedure:**

Revert git commit in `techx-corp-platform`.

<!-- Change trail: @hungxqt - 2026-07-29 - Document Mandate 21 platform blocker resolutions and durability metrics. -->
