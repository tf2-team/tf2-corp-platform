// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"context"
	"errors"
	"strings"
	"testing"
)

type testDB struct {
	exists bool
	count  int
	err    error
}

func (t *testDB) OrderExists(ctx context.Context, orderID string) (bool, int, error) {
	return t.exists, t.count, t.err
}

type testDDB struct {
	exists bool
	err    error
}

func (t *testDDB) EventExists(ctx context.Context, eventID string) (bool, error) {
	return t.exists, t.err
}

type testJaeger struct {
	counts map[string]int
	err    error
}

func (t *testJaeger) GetChargedSpanCount(ctx context.Context, traceID string) (int, error) {
	if t.err != nil {
		return 0, t.err
	}
	return t.counts[traceID], nil
}

func TestParseDrillLogValidAndMalformed(t *testing.T) {
	validJSONL := `{"schemaVersion":"1","phase":"drill","testRequestId":"req-1","traceId":"t-1","startedAt":"2026-07-28T00:00:00Z","completedAt":"2026-07-28T00:00:01Z","httpStatus":200,"durationMs":100,"outcome":"success","orderId":"order-100"}`
	records, err := ParseDrillLog(strings.NewReader(validJSONL))
	if err != nil {
		t.Fatalf("ParseDrillLog error: %v", err)
	}
	if len(records) != 1 || records[0].OrderID != "order-100" {
		t.Fatalf("unexpected record: %+v", records)
	}

	malformedJSONL := `{"schemaVersion":"1", invalid-json`
	_, err = ParseDrillLog(strings.NewReader(malformedJSONL))
	if err == nil {
		t.Fatal("expected error for malformed JSONL")
	}
}

func TestReconcile_AllAcceptedDurable_Passes(t *testing.T) {
	records := []DrillRecord{
		{HTTPStatus: 200, OrderID: "order-1", TraceID: "t1", TestRequestID: "req1"},
	}
	db := &testDB{exists: true, count: 1}
	ddb := &testDDB{exists: false} // deleted outbox item after RDS ACK
	jaeger := &testJaeger{counts: map[string]int{"t1": 1}}

	res, code := Reconcile(records, db, ddb, jaeger)
	if code != ExitPass {
		t.Fatalf("Reconcile code = %d, want ExitPass (0); violations: %v", code, res.Violations)
	}
}

func TestReconcile_AcceptedOrderMissingDurable_Fails(t *testing.T) {
	records := []DrillRecord{
		{HTTPStatus: 200, OrderID: "order-missing", TraceID: "t1", TestRequestID: "req1"},
	}
	db := &testDB{exists: false, count: 0}
	ddb := &testDDB{exists: false}
	jaeger := &testJaeger{counts: map[string]int{"t1": 1}}

	res, code := Reconcile(records, db, ddb, jaeger)
	if code != ExitInvariantViolation {
		t.Fatalf("Reconcile code = %d, want ExitInvariantViolation (2)", code)
	}
	if len(res.Violations) == 0 {
		t.Fatal("expected violation for missing durable record")
	}
}

func TestReconcile_MultiplePaymentSpansPerRequest_Fails(t *testing.T) {
	records := []DrillRecord{
		{HTTPStatus: 200, OrderID: "order-dup-payment", TraceID: "t1", TestRequestID: "req-dup"},
	}
	db := &testDB{exists: true, count: 1}
	ddb := &testDDB{exists: true}
	jaeger := &testJaeger{counts: map[string]int{"t1": 2}}

	res, code := Reconcile(records, db, ddb, jaeger)
	if code != ExitInvariantViolation {
		t.Fatalf("Reconcile code = %d, want ExitInvariantViolation (2)", code)
	}
	if res.DuplicatePaymentSpans == 0 {
		t.Fatal("expected duplicate payment span violation")
	}
}

func TestReconcile_DataSourceUnavailable_ReturnsCode3(t *testing.T) {
	records := []DrillRecord{
		{HTTPStatus: 200, OrderID: "order-1", TraceID: "t1", TestRequestID: "req1"},
	}
	db := &testDB{err: errors.New("connection reset by peer")}
	ddb := &testDDB{exists: false}
	jaeger := &testJaeger{counts: map[string]int{"t1": 1}}

	_, code := Reconcile(records, db, ddb, jaeger)
	if code != ExitDataUnavailable {
		t.Fatalf("Reconcile code = %d, want ExitDataUnavailable (3)", code)
	}
}

func TestReconcile_MissingDDBItemRequiresSingleRDSRecord(t *testing.T) {
	records := []DrillRecord{
		{HTTPStatus: 200, OrderID: "order-ack-deleted", TraceID: "t1", TestRequestID: "req1"},
	}
	// Case A: DDB missing, RDS count = 1 -> PASS
	dbPass := &testDB{exists: true, count: 1}
	ddb := &testDDB{exists: false}
	jaeger := &testJaeger{counts: map[string]int{"t1": 1}}

	res, code := Reconcile(records, dbPass, ddb, jaeger)
	if code != ExitPass {
		t.Fatalf("Reconcile code = %d, want ExitPass (0); violations: %v", code, res.Violations)
	}

	// Case B: DDB missing, RDS count = 2 -> FAIL
	dbDup := &testDB{exists: true, count: 2}
	res2, code2 := Reconcile(records, dbDup, ddb, jaeger)
	if code2 != ExitInvariantViolation {
		t.Fatalf("Reconcile code = %d, want ExitInvariantViolation (2)", code2)
	}
	if len(res2.Violations) == 0 {
		t.Fatal("expected violation for non-unique RDS record when DDB item missing")
	}
}

// Change trail: @hungxqt - 2026-07-29 - Verify exact single RDS record ACK rule when DynamoDB item is absent.
