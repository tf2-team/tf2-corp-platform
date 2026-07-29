# Change: Fix Accounting orderitem Primary Key Refund Migration

## Summary

Updated the Accounting `--migrate-only` preflight database migrator (`DatabaseMigrator.cs`) and Entity Framework model (`Entities.cs`) to validate and migrate both `accounting.shipping` and `accounting.orderitem` primary keys. Widened `accounting.orderitem` primary key from legacy `(order_id, product_id)` to `(order_id, product_id, transaction_type)` under PostgreSQL advisory lock `20260728` within a single transaction without using `CASCADE`.

## Context

Production database retained the legacy `accounting.orderitem` primary key `(order_id, product_id)`. When an order was cancelled, Accounting attempted to record a compensating `REFUND` transaction using the existing `order_id` and `product_id`. PostgreSQL rejected the duplicate primary key with error `23505`. The previous `DatabaseMigrator` checked only `accounting.shipping` and returned early when `shipping` was at its desired layout, skipping `orderitem` validation entirely and causing Accounting to repeatedly fail and retry on cancelled order messages.

## Before

* `DatabaseMigrator.cs` evaluated only `accounting.shipping` primary key layout and returned early when `shipping` was valid.
* `accounting.orderitem` primary key remained `(order_id, product_id)`, rejecting `REFUND` rows for existing `(order_id, product_id)` entries.
* EF model `OrderItemEntity` declared `[PrimaryKey(nameof(ProductId), nameof(OrderId), nameof(TransactionType))]`, out of alignment with canonical database key ordering `(OrderId, ProductId, TransactionType)`.
* Repeating PostgreSQL 23505 errors occurred during order cancellations, causing consumer offset seek loops.

## After

* `DatabaseMigrator.cs` inspects both `accounting.shipping` and `accounting.orderitem` primary key specifications (`{order_id, transaction_type}` and `{order_id, product_id, transaction_type}`) before deciding migration is a no-op.
* Legacy `accounting.orderitem` layout `{order_id, product_id}` (in any column order) is migrated to `{order_id, product_id, transaction_type}` under advisory lock `20260728` without `CASCADE`.
* `transaction_type` columns are preflight-validated for existence and non-null values, and target primary keys are checked for duplicates prior to schema modification.
* Postconditions re-verify both primary keys from `information_schema` prior to transaction commit.
* EF model `OrderItemEntity` key order is aligned to `(OrderId, ProductId, TransactionType)`.
* Compensating `REFUND` rows insert successfully alongside original `CHARGE` rows.

## Technical Design Decisions

* Enforced fail-closed validation for unknown or partial table layouts.
* Used single PostgreSQL transaction with advisory lock `20260728` and non-CASCADE `ALTER TABLE` operations to prevent destructive cascade drops on foreign keys.
* Re-read primary key column definitions from `information_schema` as an explicit postcondition check before committing transaction.

## Implementation Details

1. Updated `DatabaseMigrator.cs` to manage table-specific primary key checks for `shipping` and `orderitem`, preflight non-null/duplicate constraints, execute alterations without `CASCADE`, and verify postconditions.
2. Updated `OrderItemEntity` in `Entities.cs` to align EF key ordering with canonical database column sequence.
3. Extended `Accounting.Tests/MigrationTests.cs` to test multi-table layout guards, legacy column order independence, and fail-closed handling of unexpected column sets.
4. Created `002_fix_orderitem_pkey.sql` and `test_orderitem_migration.ps1` under `src/postgresql/migrations/` to test `--migrate-only` against PostgreSQL.

## Files Changed

* `src/accounting/DatabaseMigrator.cs` — Added multi-table layout validation, orderitem PK migration, and postcondition verification.
* `src/accounting/Entities.cs` — Aligned OrderItemEntity primary key order to (OrderId, ProductId, TransactionType).
* `src/accounting/Accounting.Tests/MigrationTests.cs` — Added unit test coverage for orderitem layout checks and multi-table migration logic.
* `src/postgresql/migrations/002_fix_orderitem_pkey.sql` — Added standalone SQL migration script for orderitem primary key.
* `src/postgresql/migrations/test_orderitem_migration.ps1` — Created PostgreSQL integration test script verifying --migrate-only and refund insertion.
* `docs/changes/2026-07-29-fix-accounting-orderitem-refund-migration.md` — Platform change record.

## Dependencies and Cross-Repository Impact

* `techx-corp-chart`: Helm PreSync hook executes Accounting `--migrate-only` to apply the updated schema prior to workload rollout.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Resolves 23505 errors during order cancellation, enabling successful insertion of REFUND transactions |
| **Infrastructure** | No infrastructure changes |
| **Deployment** | PreSync migration hook updates orderitem schema automatically |
| **Performance** | Zero impact on normal operation; eliminates CPU/log overhead from continuous offset retries |
| **Security** | Zero credential logging; error payloads remain sanitized |
| **Reliability** | Eliminates consumer stuck offset loops during order cancellation |
| **Cost** | No cost change |
| **Backward compatibility** | Fully backward compatible; widened primary key supports existing CHARGE rows |
| **Observability** | Eliminates recurring 23505 database error logs |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Accounting Unit Tests | `dotnet test src/accounting/Accounting.sln` | ✅ Pass |
| Integration Scenario | `pwsh src/postgresql/migrations/test_orderitem_migration.ps1` | ✅ Pass |

## Migration or Deployment Notes

PreSync Helm migration job automatically executes `--migrate-only` before application pods roll over.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Duplicate target keys existing prior to migration | Low | Medium | Preflight duplicate check aborts transaction and exits non-zero before ALTER TABLE |

**Rollback procedure:**
Revert application PR. Note that widening the primary key to include `transaction_type` remains compatible with previous Accounting versions, so database primary key does not need to be shrunk back.

# Change trail: @hungxqt - 2026-07-29 - Fix Accounting orderitem primary key for refund processing.
