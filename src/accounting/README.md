# Accounting Service

This service consumes new orders from a Kafka topic.

## Prerequisites

- **.NET 10 SDK** (constrained via `src/accounting/global.json` to feature band `10.0.100` with `latestFeature` roll-forward)

## Local Build & Test

To build the solution and run tests locally:

```cmd
cd /d src\accounting
dotnet build Accounting.sln
dotnet test Accounting.sln --configuration Release --verbosity minimal
```

## Docker Build

From the repository root (`techx-corp-platform`):

```cmd
docker compose build accounting
```

## Bump Dependencies

To bump all dependencies run in Package Manager:

```cmd
Update-Package -ProjectName Accounting
```

<!-- Change trail: @hungxqt - 2026-07-28 - Add .NET 10 SDK prerequisites, solution build/test commands, and CMD-first presentation. -->
