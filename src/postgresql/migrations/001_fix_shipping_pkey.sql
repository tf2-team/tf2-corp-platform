-- Copyright The OpenTelemetry Authors
-- SPDX-License-Identifier: Apache-2.0

-- Migration: 001_fix_shipping_pkey
-- Date: 2026-07-28
-- Author: CDO-03 / TF2 (Người 2 - Mandate 21)
-- Purpose: Fix duplicate key violation on accounting.shipping
--
-- Root cause: checkout service sets ShippingTrackingId = "PENDING_SHIPPING" for
-- all orders. The original PK (shipping_tracking_id, transaction_type) means
-- every order generates (PENDING_SHIPPING, CHARGE), causing a duplicate key
-- error on every second order processed by Accounting. This produces
-- ~891 shipping_pkey errors / 5 min and ~297 order_parse_failed / 5 min.
--
-- Fix: Change PK to (order_id, transaction_type), which is unique per order.
-- OrderItemEntity already uses (order_id, product_id, transaction_type) — this
-- aligns the shipping table with the same pattern.
--
-- Safety:
--   1. Runs inside a single transaction — any failure rolls back completely.
--   2. Deduplicates rows BEFORE changing the PK to avoid constraint errors.
--   3. Dedup keeps the row with the lowest ctid (insertion order) per
--      (order_id, transaction_type) group — deterministic and auditable.
--   4. If the new PK already has duplicates after dedup (should be impossible),
--      the ALTER TABLE will fail and the transaction rolls back.

BEGIN;

-- Step 1: Remove duplicate (order_id, transaction_type) rows.
-- Keep the first-inserted row (lowest ctid) per group.
-- This handles the current data where every row has
-- shipping_tracking_id = 'PENDING_SHIPPING'.
DELETE FROM accounting.shipping
WHERE ctid NOT IN (
    SELECT MIN(ctid)
    FROM accounting.shipping
    GROUP BY order_id, transaction_type
);

-- Step 2: Drop the old primary key constraint.
ALTER TABLE accounting.shipping
    DROP CONSTRAINT shipping_pkey;

-- Step 3: Add the new primary key on (order_id, transaction_type).
ALTER TABLE accounting.shipping
    ADD CONSTRAINT shipping_pkey PRIMARY KEY (order_id, transaction_type);

-- Step 4: Verify — this should return 0 rows after the migration.
-- If it returns rows, something went wrong (transaction will still commit,
-- but the operator should check). We log via RAISE NOTICE for visibility.
DO $$
DECLARE
    dup_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO dup_count
    FROM (
        SELECT order_id, transaction_type
        FROM accounting.shipping
        GROUP BY order_id, transaction_type
        HAVING COUNT(*) > 1
    ) sub;

    IF dup_count > 0 THEN
        RAISE EXCEPTION 'Post-migration check FAILED: % duplicate (order_id, transaction_type) pairs found', dup_count;
    ELSE
        RAISE NOTICE 'Post-migration check PASSED: no duplicate (order_id, transaction_type) pairs';
    END IF;
END;
$$;

COMMIT;
