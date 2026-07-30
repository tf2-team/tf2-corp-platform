# Change: Fix Audit Router Secret Contract

## Summary

Aligns the audit alert router with the production Terraform environment contract by resolving `DISCORD_WEBHOOK_SECRET_ARN` before the legacy secret-name variable, rejecting non-HTTPS webhook URLs, and emitting content-free CloudWatch Embedded Metric Format delivery evidence.

## Context

The live router received `DISCORD_WEBHOOK_SECRET_ARN`, while the application read `WEBHOOK_SECRET_NAME` and otherwise used an unrelated fallback name. SQS records were returned as partial batch failures and moved to the alert-ready DLQ after three receives, keeping the production alarm in `ALARM`.

## Before

The router ignored the Terraform-provided secret ARN. Secret lookup or delivery failures were returned through `batchItemFailures`, but successful and failed Discord deliveries did not emit the custom metrics expected by the infrastructure alarms.

## After

The router uses the configured secret ARN, retains `WEBHOOK_SECRET_NAME` only as a compatibility fallback, fails closed when no identifier exists, requires HTTPS, and emits aggregate success/failure metrics without including audit message content.

## Technical Design Decisions

The existing Terraform secret ARN is the authoritative production input because IAM already restricts `GetSecretValue` to that resource. Embedded Metric Format uses the existing Lambda log permission and avoids widening IAM with `cloudwatch:PutMetricData`. Direct `DISCORD_WEBHOOK_URL` support remains for existing tests and development.

## Implementation Details

1. Resolve the secret ARN before the legacy secret name.
2. Remove the hardcoded production fallback.
3. Validate webhook transport before caching or sending.
4. Emit `DiscordDeliverySuccess` and `DiscordDeliveryFailure` counts with the existing alarm dimensions.
5. Add regression tests for ARN precedence, missing configuration, HTTPS enforcement, and content-free metrics.

## Files Changed

**Application:**
* `src/audit-alert-router/router.py` — Corrected secret resolution and added delivery metrics.

**Tests:**
* `src/audit-alert-router/tests/test_router.py` — Added secret-contract and metric regression coverage.

**Documentation:**
* `docs/changes/2026-07-29-fix-audit-router-secret-contract.md` — This change record.

## Dependencies and Cross-Repository Impact

Related: `techx-corp-infra/docs/changes/2026-07-29-extend-audit-alarm-dlq-recovery.md`

The infra repository exports the existing router alarms and uses the delivery-failure alarm as a producer-health gate before historical DLQ deletion.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | Router reads the deployed secret ARN and reports failed SQS items as before. |
| **Infrastructure** | No resource change in this repository. |
| **Deployment** | Requires the existing production router deployment workflow after review. |
| **Performance** | One small EMF log record per processed batch. |
| **Security** | Removes an unrelated secret fallback and enforces HTTPS. |
| **Reliability** | Stops the configuration mismatch from redriving every alert. |
| **Cost** | Negligible CloudWatch log/metric volume. |
| **Backward compatibility** | Legacy `WEBHOOK_SECRET_NAME` remains supported. |
| **Observability** | Adds delivery success/failure metrics without message bodies. |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Router tests | `python -m pytest src\audit-alert-router\tests\test_router.py -q` | Pass - 9 tests |

### Manual Verification

Static review verifies that metric documents contain counts and fixed dimensions only.

### Remaining Verification (Post-Merge)

Deploy through the existing production workflow, verify the Lambda code hash, confirm successful Discord delivery, and prove the alert-ready DLQ count stops increasing.

## Migration or Deployment Notes

1. Merge and deploy the reviewed router artifact through the production workflow.
2. Confirm `DISCORD_WEBHOOK_SECRET_ARN` remains configured.
3. Verify `DiscordDeliveryFailure` remains zero and the DLQ stops growing.
4. Run the separately approved infra archive-before-delete workflow.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Secret contains an invalid URL | Low | High | Fail closed and retain the SQS message for retry/DLQ evidence. |
| Discord remains unavailable | Medium | Medium | Failure metric and partial batch response preserve the alert. |

**Rollback procedure:**

Redeploy the previously verified Lambda artifact. Do not clear or replay the DLQ as part of application rollback.

<!-- Change trail: @hungxqt - 2026-07-29 - Documented the router secret-contract and delivery metric correction. -->
