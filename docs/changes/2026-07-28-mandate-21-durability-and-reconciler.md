# Change: Mandate 21 Order Durability, Accounting Migration, Reconciler, and Audit Alert Router

## Summary

Implemented outbox pattern state machine (Prepare -> Activate -> RemovePrepared) in Checkout service to guarantee order durability before payment charge. Updated Accounting primary key layout for shipping entities to `(order_id, transaction_type)` with advisory locks and duplicate checks in `--migrate-only` mode. Created Mandate 21 reconciler Go CLI tool with CloudWatch watch mode and implemented the production SQS-to-Discord audit alert router with Lambda deployment workflow.

## Context

Mandate 21 requires zero order loss or un-durable payment charges during fault injection drills. Previously, payment charges occurred before outbox persistence, risking payment charges for lost orders. Accounting database shipping primary key layout caused lock contention or duplicate key errors during concurrent transactions.

## Before

* Checkout service invoked payment service before outbox state preparation, leading to potential card charges without durable database outbox records.
* Accounting shipping entity used `(shipping_tracking_id, transaction_type)` primary key, risking conflicts on reprocessed orders.
* Missing automated reconciler for cross-referencing ledger JSONL, DynamoDB, RDS PostgreSQL, and Jaeger payment spans.
* Missing real production SQS-to-Discord audit alert router handler.

## After

* Checkout service calls `Outbox.Prepare` before card charge, then atomically calls `Outbox.Activate` after payment or `Outbox.RemovePrepared` if payment fails.
* Accounting shipping entity primary key updated to `(order_id, transaction_type)` with PostgreSQL advisory lock `20260728` migration support.
* Mandate 21 reconciler CLI verifies durability invariants, exiting 0 for pass, 2 for invariant violation, and 3 for data source error, with 1-minute CloudWatch heartbeat watch mode.
* Audit alert router Lambda handles SQS records, delivers to Discord webhook with partial batch failure reporting (`batchItemFailures`), and is deployable via GitHub Actions.

## Technical Design Decisions

* Enforced explicit outbox states `prepared`, `pending`, and `published`. The outbox worker only publishes `pending` items.
* Used PostgreSQL advisory lock `20260728` to prevent race conditions during migration.
* Implemented fail-closed CloudWatch watch mode metric (`AcceptedOrderWithoutDurableRecord`) emitting `1` on missing data sources or durability gaps.

## Implementation Details

1. Added `Prepare`, `Activate`, and `RemovePrepared` methods in `src/checkout/outbox/store.go`.
2. Updated `PlaceOrder` flow in `src/checkout/main.go`.
3. Added `DatabaseMigrator.cs` in `src/accounting/`.
4. Created Go reconciliation tool under `tools/mandate21-reconcile/`.
5. Created Python Lambda handler under `src/audit-alert-router/` with unit tests.
6. Created deployment workflow `.github/workflows/audit-alert-router-deploy.yml`.

## Files Changed

* `src/checkout/outbox/store.go` — Added Prepare, Activate, RemovePrepared methods.
* `src/checkout/outbox/store_test.go` — Added outbox state machine unit tests.
* `src/checkout/main.go` — Reordered PlaceOrder to enforce outbox durability before payment.
* `src/accounting/Consumer.cs` — Separated Protobuf decode errors from DB persistence errors.
* `src/accounting/Entities.cs` — Updated ShippingEntity primary key attributes.
* `src/accounting/DatabaseMigrator.cs` — Created advisory lock DB migration logic.
* `src/accounting/Program.cs` — Added `--migrate-only` CLI execution mode.
* `src/accounting/Accounting.csproj` — Adjusted SDK target and dependencies.
* `src/accounting/Accounting.sln` — Added test project.
* `src/accounting/Accounting.Tests/Accounting.Tests.csproj` — Created test project.
* `src/accounting/Accounting.Tests/MigrationTests.cs` — Added migration unit tests.
* `tools/mandate21-reconcile/go.mod` — Created Go module for reconciler.
* `tools/mandate21-reconcile/main.go` — Implemented reconciler CLI and watch mode.
* `tools/mandate21-reconcile/main_test.go` — Added reconciler unit tests.
* `src/audit-alert-router/router.py` — Implemented audit alert router Lambda handler.
* `src/audit-alert-router/tests/test_router.py` — Added unit tests for router handler.
* `.github/workflows/audit-alert-router-deploy.yml` — Added production deployment workflow.
* `docs/changes/2026-07-28-mandate-21-durability-and-reconciler.md` — This change record.

## Dependencies and Cross-Repository Impact

* `techx-corp-chart`: Requires PreSync migration Job executing Accounting `--migrate-only` before app rollout.
* `techx-corp-infra`: Requires IAM policy update for Lambda deployment role.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Guarantees order outbox record exists before card charge |
| **Infrastructure** | Adds Lambda deployment capabilities for audit router |
| **Deployment** | Database migration runs as PreSync Helm hook |
| **Performance** | Zero overhead on successful checkout path |
| **Security** | Zero card details or secrets logged in reconciler/router |
| **Reliability** | Eliminates order loss and duplicate payment anomalies |
| **Cost** | No cost increase |
| **Backward compatibility** | Fully backward compatible HTTP/Protobuf API |
| **Observability** | Adds CloudWatch heartbeat metric for durability watch |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Checkout tests | `go test ./...` in `src/checkout` | ✅ Pass |
| Accounting tests | `dotnet test src\accounting\Accounting.sln` | ✅ Pass |
| Reconciler tests | `go test ./...` in `tools/mandate21-reconcile` | ✅ Pass |
| Audit Router tests | `python -m pytest src\audit-alert-router\tests` | ✅ Pass |

## Migration or Deployment Notes

None.

## Risks and Rollback

**Rollback procedure:**
Revert commit in `techx-corp-platform`.

# Change trail: @hungxqt - 2026-07-28 - Mandate 21 Platform changes for order durability, reconciler, and audit router.
