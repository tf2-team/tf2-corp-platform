#!/usr/bin/env pwsh
# Test script for Accounting orderitem primary key migration
# Usage: ./test_orderitem_migration.ps1

param([string]$ContainerName = "pg-orderitem-migration-test")

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
    PRIMARY KEY (order_id, transaction_type),
    FOREIGN KEY (order_id) REFERENCES accounting."order"(order_id) ON DELETE CASCADE
);

CREATE TABLE accounting.orderitem (
    item_cost_currency_code TEXT NOT NULL,
    item_cost_units BIGINT NOT NULL,
    item_cost_nanos INT NOT NULL,
    product_id TEXT NOT NULL,
    quantity INT NOT NULL,
    order_id TEXT NOT NULL,
    transaction_type VARCHAR(10) NOT NULL DEFAULT 'CHARGE',
    PRIMARY KEY (order_id, product_id),
    FOREIGN KEY (order_id) REFERENCES accounting."order"(order_id) ON DELETE CASCADE
);
"@ 2>&1 | Out-Null
}

Write-Section "Setup: start disposable PostgreSQL container"
docker rm -f $ContainerName 2>&1 | Out-Null
docker run -d --name $ContainerName `
    -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=testdb `
    -p 25432:5432 postgres:15 2>&1 | Out-Null

Write-Host "  Waiting for PostgreSQL..."
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $r = docker exec $ContainerName pg_isready -U test 2>&1
    if ($r -match "accepting") { Write-Host "  Ready." -ForegroundColor Green; break }
}

try {
    Write-Section "TC1: Legacy orderitem PK (order_id, product_id) -> Migrate to 3-column key"
    Reset-Schema

    # Insert observed production CHARGE data
    Invoke-Psql @"
INSERT INTO accounting."order" (order_id, status) VALUES ('order-101', 'PENDING');
INSERT INTO accounting.shipping (shipping_tracking_id, shipping_cost_currency_code, shipping_cost_units, shipping_cost_nanos, order_id, transaction_type)
VALUES ('TRACK-101', 'USD', 10, 0, 'order-101', 'CHARGE');
INSERT INTO accounting.orderitem (item_cost_currency_code, item_cost_units, item_cost_nanos, product_id, quantity, order_id, transaction_type)
VALUES ('USD', 50, 0, 'prod-A', 2, 'order-101', 'CHARGE');
"@ | Out-Null

    Write-Host "  Running --migrate-only entry point..."
    $connStr = "Host=localhost;Port=25432;Database=testdb;Username=test;Password=test"
    $appDir = Resolve-Path "$PSScriptRoot/../../accounting"
    $env:DB_CONNECTION_STRING = $connStr

    $migRes = dotnet run --project "$appDir/Accounting.csproj" -- --migrate-only 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "--migrate-only completed successfully"
    } else {
        Write-Fail "--migrate-only failed: $migRes"
    }

    # Verify 3-column key on accounting.orderitem
    $pk = Invoke-Psql @"
SELECT kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
WHERE tc.table_schema = 'accounting'
  AND tc.table_name = 'orderitem'
  AND tc.constraint_type = 'PRIMARY KEY'
ORDER BY kcu.ordinal_position;
"@
    if ($pk -match "order_id" -and $pk -match "product_id" -and $pk -match "transaction_type") {
        Write-Pass "accounting.orderitem PK is now (order_id, product_id, transaction_type)"
    } else {
        Write-Fail "accounting.orderitem PK columns unexpected: $pk"
    }

    # Verify REFUND row insertion (which previously failed with 23505)
    $refundRes = Invoke-Psql @"
INSERT INTO accounting.orderitem (item_cost_currency_code, item_cost_units, item_cost_nanos, product_id, quantity, order_id, transaction_type)
VALUES ('USD', -50, 0, 'prod-A', -2, 'order-101', 'REFUND');
"@ -AllowFail

    $itemCount = (Invoke-Psql "SELECT COUNT(*) FROM accounting.orderitem WHERE order_id = 'order-101';").Trim()
    if ($itemCount -eq "2") {
        Write-Pass "Successfully inserted compensating REFUND row alongside CHARGE row (2 rows total for order-101)"
    } else {
        Write-Fail "Expected 2 orderitem rows (CHARGE + REFUND), got $itemCount. Error: $refundRes"
    }

    Write-Section "TC2: Idempotency check — rerun --migrate-only on already migrated database"
    $rerunRes = dotnet run --project "$appDir/Accounting.csproj" -- --migrate-only 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "Rerun --migrate-only completed successfully (no-op)"
    } else {
        Write-Fail "Rerun --migrate-only failed: $rerunRes"
    }

} finally {
    Write-Section "Teardown"
    docker rm -f $ContainerName 2>&1 | Out-Null
    Write-Host "  Container removed." -ForegroundColor Green
}

Write-Section "Summary"
Write-Host "  PASS: $PASS" -ForegroundColor Green
Write-Host "  FAIL: $FAIL" -ForegroundColor $(if ($FAIL -gt 0) { "Red" } else { "Green" })
if ($FAIL -gt 0) {
    Write-Host "`n  RESULT: FAIL — migration test failed" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n  RESULT: PASS — migration test verified successfully" -ForegroundColor Green
    exit 0
}

# Change trail: @hungxqt - 2026-07-29 - Add PostgreSQL integration test for orderitem primary key refund migration.
