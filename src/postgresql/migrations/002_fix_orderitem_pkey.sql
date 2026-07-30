-- Copyright The OpenTelemetry Authors
-- SPDX-License-Identifier: Apache-2.0

-- Migration: 002_fix_orderitem_pkey
-- Date: 2026-07-29
-- Author: @hungxqt
-- Purpose: Fix duplicate key violation (23505) on accounting.orderitem when inserting REFUND transactions.
--
-- Root cause: accounting.orderitem legacy PK was (order_id, product_id). When compensating REFUND rows
-- were inserted for cancelled orders with the same order_id and product_id, PostgreSQL rejected them
-- with 23505 because transaction_type was not part of the primary key.
--
-- Fix: Change PK on accounting.orderitem to (order_id, product_id, transaction_type).

BEGIN;

-- Drop legacy primary key constraint on accounting.orderitem
ALTER TABLE accounting.orderitem
    DROP CONSTRAINT orderitem_pkey;

-- Add new primary key constraint on (order_id, product_id, transaction_type)
ALTER TABLE accounting.orderitem
    ADD CONSTRAINT orderitem_pkey PRIMARY KEY (order_id, product_id, transaction_type);

COMMIT;

-- Change trail: @hungxqt - 2026-07-29 - Fix accounting.orderitem primary key layout to include transaction_type.
