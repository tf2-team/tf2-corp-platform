#!/usr/bin/env pwsh
# Test script for 001_fix_shipping_pkey.sql
# Usage: ./test_migration.ps1

param([string]$ContainerName = "pg-migration-test")

$MigrationFile = "$PSScriptRoot\001_fix_shipping_pkey.sql"
$PASS = 0
$FAIL = 0

function Write-Pass { param($msg) Write-Host "  [PASS] $msg" -ForegroundColor Green;  $script:PASS++ }
function Write-Fail { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red;    $script:FAIL++ }
function Write-Section { param($msg) Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

function Invoke-Psql {
    param([string]$Sql, [switch]$AllowFail)
    $out = docker exec $ContainerName psql -U test -d testdb -t -A -c $Sql 2>&1
    if ($LASTEXITCODE -ne 0 -and -not $AllowFail) {
        throw "SQL error ($LASTEXITCODE): $out"
    }
    return ($out -join "`n")
}

function Run-Migration {
    $out = docker exec $ContainerName psql -U test -d testdb -f /tmp/migration.sql 2>&1
    $exit = $LASTEXITCODE
    $hasError = ($out | Where-Object { $_ -match "ERROR:" }) -ne $null
    if ($hasError) { return @{ OK=$false; Output=$out } }
    return @{ OK=$true; Output=$out }
}

function Reset-Schema {
    docker exec $ContainerName psql -U test -d testdb -c "DROP TABLE IF EXISTS accounting.shipping; DROP TABLE IF EXISTS accounting.orderitem; DROP TABLE IF EXISTS accounting.`"order`"; DROP SCHEMA IF EXISTS accounting CASCADE;" 2>&1 | Out-Null
    docker exec $ContainerName psql -U test -d testdb -c @"
CREATE SCHEMA accounting;
CREATE TABLE accounting."order" (
    order_id TEXT PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
);
CREATE TABLE accounting.shipping (
    shipping_tracking_id TEXT NOT NULL,
    shipping_cost_currency_code TEXT NOT NULL,
    shipping_cost_units BIGINT NOT NULL,
    shipping_cost_nanos INT NOT NULL,
    street_address TEXT, city TEXT, state TEXT, country TEXT, zip_code TEXT,
    order_id TEXT NOT NULL,
    transaction_type VARCHAR(10) NOT NULL DEFAULT 'CHARGE',
    PRIMARY KEY (shipping_tracking_id, transaction_type),
    FOREIGN KEY (order_id) REFERENCES accounting."order"(order_id) ON DELETE CASCADE
);
"@ 2>&1 | Out-Null
}

# ── Setup ──────────────────────────────────────────────────────────────────────
Write-Section "Setup: start disposable PostgreSQL container"

docker rm -f $ContainerName 2>&1 | Out-Null
docker run -d --name $ContainerName `
    -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=testdb `
    -p 15432:5432 postgres:15 2>&1 | Out-Null

Write-Host "  Waiting for PostgreSQL..."
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $r = docker exec $ContainerName pg_isready -U test 2>&1
    if ($r -match "accepting") { Write-Host "  Ready." -ForegroundColor Green; break }
}

docker cp $MigrationFile "${ContainerName}:/tmp/migration.sql" 2>&1 | Out-Null
Write-Host "  Migration file copied."

# ── TC1: Normal migration — no duplicates ──────────────────────────────────────
Write-Section "TC1: Normal migration (clean data, no duplicates)"
Reset-Schema

Invoke-Psql @"
INSERT INTO accounting."order" (order_id) VALUES ('o1'),('o2'),('o3');
INSERT INTO accounting.shipping (shipping_tracking_id,shipping_cost_currency_code,shipping_cost_units,shipping_cost_nanos,order_id,transaction_type)
VALUES ('TRACK-1','USD',8,0,'o1','CHARGE'),('TRACK-2','USD',5,0,'o2','CHARGE'),('TRACK-3','USD',3,0,'o3','CHARGE');
"@ | Out-Null

$res = Run-Migration
if ($res.OK) { Write-Pass "Migration ran without ERROR" }
else         { Write-Fail "Migration failed: $($res.Output)" }

$pk = Invoke-Psql "SELECT kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name WHERE tc.table_schema='accounting' AND tc.table_name='shipping' AND tc.constraint_type='PRIMARY KEY' ORDER BY kcu.ordinal_position;"
if ($pk -match "order_id" -and $pk -match "transaction_type") { Write-Pass "PK is now (order_id, transaction_type)" }
else { Write-Fail "PK columns unexpected: $pk" }

$cnt = (Invoke-Psql "SELECT COUNT(*) FROM accounting.shipping;").Trim()
if ($cnt -eq "3") { Write-Pass "All 3 rows retained" }
else { Write-Fail "Expected 3 rows, got $cnt" }

# ── TC2: Duplicate rows (production scenario) ─────────────────────────────────
Write-Section "TC2: Duplicate rows — production scenario (PENDING_SHIPPING collision)"
Reset-Schema

# Insert orders; only 1 row per (shipping_tracking_id, transaction_type) fits old PK.
# Simulate 2 rows with same old-PK via different tracking IDs but same order_id.
Invoke-Psql @"
INSERT INTO accounting."order" (order_id) VALUES ('oA'),('oB'),('oC');
INSERT INTO accounting.shipping (shipping_tracking_id,shipping_cost_currency_code,shipping_cost_units,shipping_cost_nanos,order_id,transaction_type)
VALUES
  ('TRACK-A1','USD',8,0,'oA','CHARGE'),
  ('TRACK-A2','USD',8,0,'oA','CHARGE'),
  ('TRACK-B1','USD',5,0,'oB','CHARGE'),
  ('TRACK-B2','USD',5,0,'oB','CHARGE'),
  ('TRACK-C1','USD',3,0,'oC','CHARGE');
"@ | Out-Null

$res2 = Run-Migration
if ($res2.OK) { Write-Pass "Migration completed with duplicate data" }
else          { Write-Fail "Migration failed: $($res2.Output)" }

$cnt2 = (Invoke-Psql "SELECT COUNT(*) FROM accounting.shipping;").Trim()
if ($cnt2 -eq "3") { Write-Pass "Dedup: 3 rows remain (1 per order_id)" }
else               { Write-Fail "Expected 3 rows after dedup, got $cnt2" }

$dup2 = (Invoke-Psql "SELECT COUNT(*) FROM (SELECT order_id,transaction_type FROM accounting.shipping GROUP BY order_id,transaction_type HAVING COUNT(*)>1) s;").Trim()
if ($dup2 -eq "0") { Write-Pass "No duplicate (order_id, transaction_type) after migration" }
else               { Write-Fail "Duplicates still exist: $dup2" }

# ── TC3: Idempotent replay — same order processed twice ───────────────────────
Write-Section "TC3: Idempotent replay (same order_id inserted twice)"
Reset-Schema

Invoke-Psql @"
INSERT INTO accounting."order" (order_id) VALUES ('oX');
INSERT INTO accounting.shipping (shipping_tracking_id,shipping_cost_currency_code,shipping_cost_units,shipping_cost_nanos,order_id,transaction_type)
VALUES ('TRACK-X','USD',8,0,'oX','CHARGE');
"@ | Out-Null

Run-Migration | Out-Null

# After migration, new PK is (order_id, transaction_type). Insert same order again.
$dup = Invoke-Psql "INSERT INTO accounting.shipping (shipping_tracking_id,shipping_cost_currency_code,shipping_cost_units,shipping_cost_nanos,order_id,transaction_type) VALUES ('TRACK-X2','USD',8,0,'oX','CHARGE');" -AllowFail
if ($dup -match "duplicate key" -or $dup -match "unique constraint") {
    Write-Pass "Duplicate insert rejected by new PK (order_id, transaction_type)"
} else {
    Write-Fail "Expected duplicate key error, got: $dup"
}

$cnt3 = (Invoke-Psql "SELECT COUNT(*) FROM accounting.shipping WHERE order_id='oX';").Trim()
if ($cnt3 -eq "1") { Write-Pass "Exactly 1 row for oX" }
else               { Write-Fail "Expected 1 row, got $cnt3" }

# ── TC4: OutboxReconciler forward-fix ─────────────────────────────────────────
Write-Section "TC4: OutboxReconciler forward-fix (order in RDS, replay ACK)"
Reset-Schema

Invoke-Psql @"
INSERT INTO accounting."order" (order_id,status) VALUES ('oStale','PENDING');
INSERT INTO accounting.shipping (shipping_tracking_id,shipping_cost_currency_code,shipping_cost_units,shipping_cost_nanos,order_id,transaction_type)
VALUES ('TRACK-STALE','USD',8,0,'oStale','CHARGE');
"@ | Out-Null

Run-Migration | Out-Null

# OutboxReconciler: dbContext.Orders.AnyAsync(o => o.Id == orderId)
$exists = (Invoke-Psql "SELECT EXISTS(SELECT 1 FROM accounting.`"order`" WHERE order_id='oStale');").Trim()
if ($exists -eq "t") { Write-Pass "OutboxReconciler can find order in RDS → will replay ACK" }
else                 { Write-Fail "Order not found in RDS: $exists" }

$ship = (Invoke-Psql "SELECT COUNT(*) FROM accounting.shipping WHERE order_id='oStale' AND transaction_type='CHARGE';").Trim()
if ($ship -eq "1") { Write-Pass "Shipping row accessible via new PK" }
else               { Write-Fail "Shipping row not found: $ship" }

# ── Teardown ──────────────────────────────────────────────────────────────────
Write-Section "Teardown"
docker rm -f $ContainerName 2>&1 | Out-Null
Write-Host "  Container removed." -ForegroundColor Green

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Section "Summary"
Write-Host "  PASS: $PASS" -ForegroundColor Green
Write-Host "  FAIL: $FAIL" -ForegroundColor $(if ($FAIL -gt 0) { "Red" } else { "Green" })
if ($FAIL -gt 0) {
    Write-Host "`n  RESULT: FAIL — do NOT apply to production" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n  RESULT: PASS — migration safe to apply to production" -ForegroundColor Green
    exit 0
}
