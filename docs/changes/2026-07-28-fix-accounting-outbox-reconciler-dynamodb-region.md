# Change: Fix Accounting Outbox Reconciler DynamoDB Region Endpoint Fallback

## Summary

Updated `OutboxReconciler` in `Accounting` microservice to construct `AmazonDynamoDBClient` with an explicit `AmazonDynamoDBConfig` region endpoint fallback (`AWS_REGION` -> `AWS_DEFAULT_REGION` -> `us-east-1`). This prevents `Amazon.Runtime.AmazonClientException: No RegionEndpoint or ServiceURL configured` when running in environments where `AWS_REGION` is not explicitly exported.

## Context

During Accounting startup or migration job execution, the `OutboxReconciler` constructor threw an unhandled exception:
`Amazon.Runtime.AmazonClientException: No RegionEndpoint or ServiceURL configured` at `Accounting.OutboxReconciler..ctor`.

* Why is this change needed now? `AmazonDynamoDBClient()` parameterless constructor requires an `AWS_REGION` environment variable or AWS credential file config. If neither is available, the client initialization throws an exception and crashes the process.
* Decisions: Configured `AmazonDynamoDBConfig` explicitly in `OutboxReconciler` with a safe default (`us-east-1`) to ensure resilience regardless of container env variables.

## Before

`OutboxReconciler.cs` initialized the DynamoDB client with default parameterless constructor:

```csharp
_dynamoDb = new AmazonDynamoDBClient();
```

If `AWS_REGION` was omitted from the environment, construction failed immediately.

## After

`OutboxReconciler.cs` resolves the region name dynamically with fallback:

```csharp
var regionName = Environment.GetEnvironmentVariable("AWS_REGION")
    ?? Environment.GetEnvironmentVariable("AWS_DEFAULT_REGION")
    ?? "us-east-1";
var config = new AmazonDynamoDBConfig
{
    RegionEndpoint = Amazon.RegionEndpoint.GetBySystemName(regionName)
};
_dynamoDb = new AmazonDynamoDBClient(config);
```

## Technical Design Decisions

* **Default region fallback (`us-east-1`):** Matches the primary deployment region for techx-corp production and staging infrastructure, allowing the client to initialize cleanly even when `AWS_REGION` is unset.

## Implementation Details

1. Modified `OutboxReconciler` constructor in `src/Accounting/OutboxReconciler.cs`.
2. Appended `@hungxqt` change trail comment.

## Files Changed

**Core Code:**
* `src/Accounting/OutboxReconciler.cs` — Added explicit `AmazonDynamoDBConfig` with fallback region `us-east-1`.

**Documentation:**
* `docs/changes/2026-07-28-fix-accounting-outbox-reconciler-dynamodb-region.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-28-fix-accounting-migration-kafka-addr-env.md`

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | `OutboxReconciler` safely initializes even if `AWS_REGION` is not passed in environment. |
| **Infrastructure** | No change |
| **Deployment** | Eliminates pod startup crashes caused by unconfigured AWS SDK region. |
| **Performance** | No change |
| **Security** | No change |
| **Reliability** | Improves process robustness during startup and migration. |
| **Cost** | No change |
| **Backward compatibility** | Fully backward-compatible |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Build / Compile | `dotnet build src/Accounting/Accounting.csproj` | ✅ Pass |

### Manual Verification

* Verified `AmazonDynamoDBClient` initializes with `us-east-1` region endpoint when `AWS_REGION` environment variable is omitted.

### Remaining Verification (Post-Merge)

* Verify container deployment in cluster.

## Migration or Deployment Notes

None.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Incorrect fallback region if deployed outside `us-east-1` without `AWS_REGION` | Low | Low | `AWS_REGION` environment variable overrides fallback if set. |

**Rollback procedure:**

Revert commit in `techx-corp-platform`.

<!-- Change trail: @hungxqt - 2026-07-28 - Add change document for Accounting OutboxReconciler DynamoDB region fix. -->
