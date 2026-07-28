# Change: Fix Accounting Outbox Reconciler DynamoDB Region Endpoint Fallback and TargetFramework Alignment

## Summary

Updated `OutboxReconciler` in `Accounting` microservice to construct `AmazonDynamoDBClient` with an explicit `AmazonDynamoDBConfig` region endpoint fallback (`AWS_REGION` -> `AWS_DEFAULT_REGION` -> `us-east-1`). Also updated `Accounting.csproj`, `Accounting.Tests.csproj`, and `Dockerfile` to target `net10.0`, aligning the compiled binary framework with the container runtime image (`aspnet:10.0`). This resolves both `AmazonClientException: No RegionEndpoint or ServiceURL configured` and framework launch errors (`Framework: 'Microsoft.NETCore.App', version '9.0.0'`).

## Context

During Accounting migration job execution, the container failed with framework mismatch error:
`Framework: 'Microsoft.NETCore.App', version '9.0.0' (arm64) ... The following frameworks were found: 10.0.10 at [/usr/share/dotnet/shared/Microsoft.NETCore.App]`.
Additionally, `OutboxReconciler` constructor threw `AmazonClientException: No RegionEndpoint or ServiceURL configured` when `AWS_REGION` was omitted.

* Why is this change needed now? The container base image uses .NET 10 (`aspnet:10.0`), but the project file targeted .NET 9 (`net9.0`). .NET 10 runtime refused to launch the .NET 9 binary. Furthermore, unconfigured AWS SDK region threw on client creation.
* Decisions: Updated project target framework to `net10.0` and configured `AmazonDynamoDBConfig` region fallback.

## Before

`Accounting.csproj` and `Accounting.Tests.csproj` targeted `net9.0`:

```xml
<TargetFramework>net9.0</TargetFramework>
```

When built inside the .NET 10 SDK Docker image and deployed to `aspnet:10.0`, the runtime rejected execution due to missing .NET 9 framework. `OutboxReconciler.cs` used parameterless `AmazonDynamoDBClient()`.

## After

`Accounting.csproj` and `Accounting.Tests.csproj` target `net10.0`:

```xml
<TargetFramework>net10.0</TargetFramework>
```

`Dockerfile` explicitly passes `-f net10.0` to `dotnet build` and `dotnet publish`. `OutboxReconciler.cs` resolves the region name dynamically with fallback (`us-east-1`).

## Technical Design Decisions

* **Target `.NET 10.0`:** Matches `CartService` and the `mcr.microsoft.com/dotnet/aspnet:10.0` base image across the platform repo.
* **Default region fallback (`us-east-1`):** Matches primary infrastructure region, allowing client initialization cleanly even if `AWS_REGION` is unset.

## Implementation Details

1. Updated `<TargetFramework>net10.0</TargetFramework>` in `Accounting.csproj` and `Accounting.Tests.csproj`.
2. Added `-f net10.0` flags to `dotnet build` and `dotnet publish` in `Dockerfile`.
3. Modified `OutboxReconciler` constructor in `src/Accounting/OutboxReconciler.cs`.
4. Appended `@hungxqt` change trail comments to modified files.

## Files Changed

**Core Code & Configuration:**
* `src/Accounting/Accounting.csproj` — Target `net10.0`.
* `src/Accounting/Accounting.Tests/Accounting.Tests.csproj` — Target `net10.0`.
* `src/Accounting/Dockerfile` — Added `-f net10.0` build and publish flags.
* `src/Accounting/OutboxReconciler.cs` — Added explicit `AmazonDynamoDBConfig` with fallback region `us-east-1`.

**Documentation:**
* `docs/changes/2026-07-28-fix-accounting-outbox-reconciler-dynamodb-region.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-chart/docs/changes/2026-07-28-fix-accounting-migration-kafka-addr-env.md`

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | `Accounting.dll` runs natively on .NET 10 runtime, and `OutboxReconciler` safely initializes. |
| **Infrastructure** | No change |
| **Deployment** | Eliminates framework launch failures and unconfigured AWS SDK region crashes. |
| **Performance** | No change |
| **Security** | No change |
| **Reliability** | Ensures process launches cleanly in container environment. |
| **Cost** | No change |
| **Backward compatibility** | Fully backward-compatible |
| **Observability** | No change |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Docker Build Alignment | `Dockerfile` (`sdk:10.0` / `aspnet:10.0`) & `Accounting.csproj` (`net10.0`) | ✅ Pass |

### Manual Verification

* Verified `Accounting.dll` targets `net10.0` for runtime compatibility with `aspnet:10.0`.

### Remaining Verification (Post-Merge)

* Verify container deployment in cluster.

## Migration or Deployment Notes

None.

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Incompatibility if deployed to older .NET 9 runtime container | Low | Low | Container image is pinned to `aspnet:10.0`. |

**Rollback procedure:**

Revert commit in `techx-corp-platform`.

<!-- Change trail: @hungxqt - 2026-07-28 - Add change document for Accounting TargetFramework and OutboxReconciler region fix. -->
