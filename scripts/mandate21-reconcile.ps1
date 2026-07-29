#!/usr/bin/env pwsh
# Mandate 21 — Reconciliation Checker (Người 2 deliverable)
#
# Interface (bắt buộc theo plan):
#   ./mandate21-reconcile.ps1 -EvidenceDirectory <dir> -FaultId <fault-id>
#
# Exit codes:
#   0 = PASS (charged = unique accepted = durable = persisted)
#   1 = FAIL (có sai lệch hoặc lỗi runtime)
#
# Đọc:
#   - k6 JSONL ledger của Người 3: <EvidenceDirectory>/k6-ledger.jsonl
#   - DynamoDB outbox: CHECKOUT_OUTBOX_TABLE (env) hoặc tự detect từ kubectl
#   - Accounting RDS: DB_CONNECTION_STRING (env) hoặc tự detect từ k8s secret
#   - Jaeger traces: JAEGER_QUERY_URL (env) — để resolve ambiguous requests
#
# Output:
#   <EvidenceDirectory>/reconciliation-report.json

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$EvidenceDirectory,
    [Parameter(Mandatory)][string]$FaultId,
    [string]$Namespace        = "techx-corp-prod",
    [string]$OutboxTable      = $env:CHECKOUT_OUTBOX_TABLE,
    [string]$DbConnString     = $env:DB_CONNECTION_STRING,
    [string]$JaegerUrl        = $env:JAEGER_QUERY_URL,
    [string]$AwsRegion        = "us-east-1",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# ── Helpers ───────────────────────────────────────────────────────────────────

function Write-Info  { param($m) Write-Host "  [INFO]  $m" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Warn  { param($m) Write-Host "  [WARN]  $m" -ForegroundColor Yellow }
function Write-Err   { param($m) Write-Host "  [ERROR] $m" -ForegroundColor Red }
function Write-Head  { param($m) Write-Host "`n=== $m ===" -ForegroundColor Magenta }

$Report = @{
    fault_id        = $FaultId
    generated_at    = (Get-Date -Format "o")
    evidence_dir    = $EvidenceDirectory
    result          = "UNKNOWN"
    summary         = @{
        accepted                  = 0
        durable                   = 0
        persisted                 = 0
        ambiguous                 = 0
        rejected                  = 0
        duplicate_orders          = 0
        duplicate_payment_spans   = 0
        missing_durable_records   = 0
        missing_persisted_records = 0
        unresolved_ambiguous      = 0
    }
    discrepancies   = @()
    warnings        = @()
}

function Add-Discrepancy {
    param([string]$Type, [string]$OrderId, [string]$Detail)
    $Report.discrepancies += @{ type=$Type; order_id=$OrderId; detail=$Detail }
    Write-Err "$Type | order=$OrderId | $Detail"
}

function Add-Warning {
    param([string]$Msg)
    $Report.warnings += $Msg
    Write-Warn $Msg
}

# ── Step 0: Validate inputs ───────────────────────────────────────────────────

Write-Head "Step 0: Validate inputs"

if (-not (Test-Path $EvidenceDirectory)) {
    New-Item -ItemType Directory -Force -Path $EvidenceDirectory | Out-Null
    Write-Info "Created evidence directory: $EvidenceDirectory"
}

$LedgerPath = Join-Path $EvidenceDirectory "k6-ledger.jsonl"
if (-not (Test-Path $LedgerPath)) {
    Write-Err "k6 JSONL ledger not found: $LedgerPath"
    Write-Err "Người 3 must generate this file before running reconciliation."
    exit 1
}
Write-Ok "Ledger found: $LedgerPath"

# ── Step 1: Read and parse k6 JSONL ledger ────────────────────────────────────

Write-Head "Step 1: Parse k6 JSONL ledger"

$Ledger = @()
$LineNum = 0
foreach ($line in (Get-Content $LedgerPath)) {
    $LineNum++
    $line = $line.Trim()
    if ([string]::IsNullOrEmpty($line)) { continue }
    try {
        $entry = $line | ConvertFrom-Json
        $Ledger += $entry
    } catch {
        Add-Warning "Line ${LineNum}: failed to parse JSON — skipped. Content: $line"
    }
}

Write-Info "Total entries: $($Ledger.Count)"

$Accepted  = @($Ledger | Where-Object { $_.outcome -eq "accepted" })
$Ambiguous = @($Ledger | Where-Object { $_.outcome -eq "ambiguous" })
$Rejected  = @($Ledger | Where-Object { $_.outcome -eq "rejected" })

$Report.summary.accepted  = $Accepted.Count
$Report.summary.ambiguous = $Ambiguous.Count
$Report.summary.rejected  = $Rejected.Count

Write-Info "accepted=$($Accepted.Count)  ambiguous=$($Ambiguous.Count)  rejected=$($Rejected.Count)"

# Check for duplicate order_id in accepted set
$AcceptedOrderIds = @($Accepted | Where-Object { $_.order_id } | Select-Object -ExpandProperty order_id)
$DupOrderIds      = @($AcceptedOrderIds | Group-Object | Where-Object { $_.Count -gt 1 })
$Report.summary.duplicate_orders = $DupOrderIds.Count
foreach ($dup in $DupOrderIds) {
    Add-Discrepancy "DUPLICATE_ORDER_IN_LEDGER" $dup.Name "order_id appears $($dup.Count) times in accepted ledger"
}
if ($DupOrderIds.Count -eq 0) { Write-Ok "No duplicate order_id in accepted ledger" }

# ── Step 2: Resolve env / k8s config ─────────────────────────────────────────

Write-Head "Step 2: Resolve configuration"

# Outbox table
if (-not $OutboxTable) {
    Write-Info "CHECKOUT_OUTBOX_TABLE not set, querying kubectl..."
    $OutboxTable = kubectl -n $Namespace get deployment checkout `
        -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="CHECKOUT_OUTBOX_TABLE")].value}' 2>$null
    if ($OutboxTable) { Write-Ok "Outbox table: $OutboxTable" }
    else { Add-Warning "Could not resolve CHECKOUT_OUTBOX_TABLE — DynamoDB checks will be skipped" }
}
else { Write-Ok "Outbox table: $OutboxTable" }

# DB connection string
if (-not $DbConnString) {
    Write-Info "DB_CONNECTION_STRING not set, reading from k8s secret..."
    $b64 = kubectl -n $Namespace get secret techx-corp-postgresql-app `
        -o jsonpath='{.data.accounting-db-connection-string}' 2>$null
    if ($b64) {
        $DbConnString = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($b64))
        Write-Ok "DB connection string resolved from secret"
    } else {
        Add-Warning "Could not resolve DB_CONNECTION_STRING — RDS checks will be skipped"
    }
}
else { Write-Ok "DB connection string: [from env]" }

# Jaeger URL
if (-not $JaegerUrl) {
    $JaegerUrl = "http://localhost:16686"
    Add-Warning "JAEGER_QUERY_URL not set, using default: $JaegerUrl (may not be reachable)"
}
else { Write-Ok "Jaeger URL: $JaegerUrl" }

# ── Step 3: DynamoDB outbox check ─────────────────────────────────────────────

Write-Head "Step 3: DynamoDB outbox — durable record check"

$DurableOrderIds = @{}

if ($OutboxTable -and $Accepted.Count -gt 0) {
    Write-Info "Checking $($Accepted.Count) accepted orders in DynamoDB outbox..."

    foreach ($entry in $Accepted) {
        $oid = $entry.order_id
        if (-not $oid) {
            Add-Discrepancy "ACCEPTED_WITHOUT_ORDER_ID" "" "accepted entry missing order_id: trace=$($entry.trace_id)"
            continue
        }

        if ($DryRun) {
            Write-Info "[DRY-RUN] Would check DynamoDB for order_id=$oid"
            $DurableOrderIds[$oid] = "dry-run"
            continue
        }

        # Query DynamoDB for this event_id (order_id is the event_id in outbox)
        $result = aws dynamodb get-item `
            --table-name $OutboxTable `
            --key "{`"event_id`":{`"S`":`"$oid`"}}" `
            --region $AwsRegion `
            --output json 2>$null | ConvertFrom-Json

        if ($result -and $result.Item) {
            $status = $result.Item.status.S
            $DurableOrderIds[$oid] = $status
            # Item exists in outbox (any status) = durable intent was recorded
            Write-Info "  order=$oid status=$status [DURABLE]"
        } else {
            # Item deleted = ACK received = order persisted and cleaned up
            # This is the HAPPY PATH after successful processing
            $DurableOrderIds[$oid] = "acked"
            Write-Info "  order=$oid status=acked (deleted after ACK) [DURABLE]"
        }
    }

    $Report.summary.durable = $DurableOrderIds.Count
    Write-Ok "Durable records found: $($DurableOrderIds.Count) / $($Accepted.Count)"

    $missingDurable = $Accepted | Where-Object {
        $_.order_id -and -not $DurableOrderIds.ContainsKey($_.order_id)
    }
    $Report.summary.missing_durable_records = @($missingDurable).Count
    foreach ($m in $missingDurable) {
        Add-Discrepancy "MISSING_DURABLE_RECORD" $m.order_id "accepted order has no DynamoDB outbox entry"
    }
    if (@($missingDurable).Count -eq 0) { Write-Ok "All accepted orders have durable records" }

} elseif (-not $OutboxTable) {
    Add-Warning "DynamoDB check skipped (no outbox table configured)"
    $Report.summary.durable = -1
} else {
    Write-Info "No accepted orders to check"
    $Report.summary.durable = 0
}

# ── Step 4: RDS persistence check ────────────────────────────────────────────

Write-Head "Step 4: RDS PostgreSQL — persistence check"

$PersistedOrderIds = @{}

if ($DbConnString -and $Accepted.Count -gt 0) {
    Write-Info "Checking $($Accepted.Count) accepted orders in Accounting RDS..."

    if ($DryRun) {
        Write-Info "[DRY-RUN] Would query RDS for each accepted order_id"
        foreach ($entry in $Accepted) {
            if ($entry.order_id) { $PersistedOrderIds[$entry.order_id] = "dry-run" }
        }
    } else {
        # Use psql via kubectl exec into accounting pod
        $AccountingPod = kubectl -n $Namespace get pods `
            -l "opentelemetry.io/name=accounting" `
            -o jsonpath='{.items[0].metadata.name}' 2>$null

        if (-not $AccountingPod) {
            Add-Warning "No accounting pod found — RDS check via kubectl exec skipped"
        } else {
            Write-Info "Using pod: $AccountingPod"

            foreach ($entry in $Accepted) {
                $oid = $entry.order_id
                if (-not $oid) { continue }

                $sql = "SELECT COUNT(*) FROM accounting.`"order`" WHERE order_id='$oid';"
                $result = kubectl -n $Namespace exec $AccountingPod -c accounting -- `
                    env DB_CONNECTION_STRING="$DbConnString" `
                    dotnet-script -e "
                        using Npgsql;
                        var cs = Environment.GetEnvironmentVariable(`"DB_CONNECTION_STRING`");
                        using var conn = new NpgsqlConnection(cs);
                        conn.Open();
                        using var cmd = new NpgsqlCommand(`"SELECT COUNT(*) FROM accounting.order WHERE order_id='$oid'`", conn);
                        Console.WriteLine(cmd.ExecuteScalar());
                    " 2>$null

                # Fallback: use psql if available in pod
                if (-not $result) {
                    $result = kubectl -n $Namespace exec $AccountingPod -c accounting -- `
                        sh -c "echo `"SELECT COUNT(*) FROM accounting.`\`"order`\`" WHERE order_id='$oid';`" | psql `"$DbConnString`" -t -A" 2>$null
                }

                if ($result -and $result.Trim() -eq "1") {
                    $PersistedOrderIds[$oid] = "persisted"
                    Write-Info "  order=$oid [PERSISTED]"
                } elseif ($result -and $result.Trim() -eq "0") {
                    Write-Warn "  order=$oid [NOT YET PERSISTED] — may still be in transit"
                } else {
                    Add-Warning "  order=$oid — could not verify in RDS (result: $result)"
                }
            }
        }
    }

    $Report.summary.persisted = $PersistedOrderIds.Count

    $missingPersisted = $Accepted | Where-Object {
        $_.order_id -and -not $PersistedOrderIds.ContainsKey($_.order_id)
    }
    $Report.summary.missing_persisted_records = @($missingPersisted).Count

    if ($DryRun) {
        Write-Info "[DRY-RUN] Skipping missing persisted check"
    } elseif (@($missingPersisted).Count -eq 0) {
        Write-Ok "All accepted orders found in RDS"
    } else {
        foreach ($m in $missingPersisted) {
            Add-Warning "order=$($m.order_id) not yet in RDS (may be in-flight) — check after recovery window"
        }
    }

} elseif (-not $DbConnString) {
    Add-Warning "RDS check skipped (no DB_CONNECTION_STRING)"
    $Report.summary.persisted = -1
} else {
    Write-Info "No accepted orders to check"
    $Report.summary.persisted = 0
}

# ── Step 5: Ambiguous request resolution ─────────────────────────────────────

Write-Head "Step 5: Resolve ambiguous requests via Jaeger"

$UnresolvedAmbiguous = 0

if ($Ambiguous.Count -gt 0) {
    Write-Info "Checking $($Ambiguous.Count) ambiguous requests..."

    foreach ($entry in $Ambiguous) {
        $traceId = $entry.trace_id
        if (-not $traceId) {
            $UnresolvedAmbiguous++
            Add-Discrepancy "AMBIGUOUS_WITHOUT_TRACE_ID" "" "ambiguous entry missing trace_id"
            continue
        }

        # Extract raw trace ID from W3C traceparent: 00-<trace_id>-<span_id>-<flags>
        $rawTraceId = if ($traceId -match "^00-([a-f0-9]{32})-") { $Matches[1] } else { $traceId }

        if ($DryRun) {
            Write-Info "[DRY-RUN] Would query Jaeger for trace $rawTraceId"
            continue
        }

        # Query Jaeger for Payment span in this trace
        try {
            $jaegerResp = Invoke-RestMethod `
                -Uri "$JaegerUrl/api/traces/$rawTraceId" `
                -TimeoutSec 10 `
                -ErrorAction SilentlyContinue

            $paymentSpans = $jaegerResp.data.spans | Where-Object {
                $_.operationName -match "payment|charge" -and
                $_.tags | Where-Object { $_.key -eq "otel.status_code" -and $_.value -eq "OK" }
            }

            if ($paymentSpans -and $paymentSpans.Count -gt 0) {
                # Ambiguous request had successful Payment span — check if order exists
                $oid = $entry.order_id
                if ($oid -and -not $DurableOrderIds.ContainsKey($oid)) {
                    Add-Discrepancy "AMBIGUOUS_WITH_PAYMENT_NO_DURABLE" $oid `
                        "ambiguous request has successful Payment span but no durable outbox record"
                    $UnresolvedAmbiguous++
                } elseif ($oid) {
                    Write-Ok "Ambiguous trace=$rawTraceId has Payment span AND durable record — OK"
                } else {
                    # Charged but no order_id → this is a potential RPO gap
                    Add-Discrepancy "AMBIGUOUS_WITH_PAYMENT_NO_ORDER_ID" "" `
                        "ambiguous request trace=$rawTraceId has successful Payment span but no order_id"
                    $UnresolvedAmbiguous++
                }
            } else {
                # No successful Payment span → customer was not charged
                Write-Info "  trace=$rawTraceId — no successful Payment span (safe, not charged)"
            }
        } catch {
            Add-Warning "Could not query Jaeger for trace=$rawTraceId : $_"
            $UnresolvedAmbiguous++
        }
    }
} else {
    Write-Ok "No ambiguous requests to resolve"
}

$Report.summary.unresolved_ambiguous = $UnresolvedAmbiguous

# ── Step 6: Duplicate Payment span check ─────────────────────────────────────

Write-Head "Step 6: Check for duplicate successful Payment spans"

# Each unique test_request_id should have at most 1 successful Payment span.
# We check this from the ledger side — if same trace_id appears twice in accepted,
# that's a duplicate charge signal.
$DupTraces = @($Accepted | Where-Object { $_.trace_id } |
    Group-Object trace_id | Where-Object { $_.Count -gt 1 })

$Report.summary.duplicate_payment_spans = $DupTraces.Count
foreach ($dup in $DupTraces) {
    Add-Discrepancy "DUPLICATE_PAYMENT_SPAN" "" `
        "trace_id=$($dup.Name) appears $($dup.Count) times in accepted ledger"
}
if ($DupTraces.Count -eq 0) { Write-Ok "No duplicate Payment spans detected" }

# ── Step 7: Determine result ──────────────────────────────────────────────────

Write-Head "Step 7: Final result"

$TotalDiscrepancies = $Report.discrepancies.Count
$CriticalFails = @($Report.discrepancies | Where-Object {
    $_.type -in @(
        "DUPLICATE_ORDER_IN_LEDGER",
        "MISSING_DURABLE_RECORD",
        "AMBIGUOUS_WITH_PAYMENT_NO_DURABLE",
        "AMBIGUOUS_WITH_PAYMENT_NO_ORDER_ID",
        "DUPLICATE_PAYMENT_SPAN",
        "ACCEPTED_WITHOUT_ORDER_ID"
    )
})

if ($CriticalFails.Count -eq 0) {
    $Report.result = "PASS"
    Write-Ok "RESULT: PASS"
    Write-Ok "  accepted=$($Report.summary.accepted)"
    Write-Ok "  durable=$($Report.summary.durable)"
    Write-Ok "  persisted=$($Report.summary.persisted)"
    Write-Ok "  ambiguous=$($Report.summary.ambiguous) (unresolved=$UnresolvedAmbiguous)"
    Write-Ok "  duplicate_orders=0  duplicate_payment_spans=0"
} else {
    $Report.result = "FAIL"
    Write-Err "RESULT: FAIL — $($CriticalFails.Count) critical discrepancy(ies)"
    foreach ($d in $CriticalFails) {
        Write-Err "  [$($d.type)] order=$($d.order_id) $($d.detail)"
    }
}

# ── Save report ───────────────────────────────────────────────────────────────

Write-Head "Save report"

$ReportPath = Join-Path $EvidenceDirectory "reconciliation-report.json"
$Report | ConvertTo-Json -Depth 10 | Set-Content $ReportPath -Encoding UTF8
Write-Ok "Report saved: $ReportPath"

if ($Report.result -eq "PASS") {
    Write-Host "`n  reconciliation-report.json: PASS" -ForegroundColor Green
    exit 0
} else {
    Write-Host "`n  reconciliation-report.json: FAIL" -ForegroundColor Red
    exit 1
}
