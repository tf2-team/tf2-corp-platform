// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
//
// Mandate 21 — Việc 5: Test boundary Payment success → Outbox.Enqueue fail
//
// Mục đích: xác nhận rằng khi Outbox.Enqueue thất bại sau khi payment đã
// charge thành công, hệ thống:
//   1. KHÔNG return error lên caller (tránh duplicate charge).
//   2. Ghi log error có order_id để observable qua telemetry.
//   3. Không panic.
//
// Đây là test quyết định theo plan Mandate 21 Section 4.5:
//   "Thêm fault/unit test đúng boundary sau Payment success và trước outbox
//   enqueue. Nếu test FAIL, lập một PR nhỏ dùng chính order ID và DynamoDB
//   outbox hiện có để bảo đảm successful Payment span luôn có durable intent."

package outbox

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

// ── Mock DynamoDB client ───────────────────────────────────────────────────────

type mockDynamoClient struct {
	putItemErr   error
	putItemCalls int
}

func (m *mockDynamoClient) PutItem(_ context.Context, _ *dynamodb.PutItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.PutItemOutput, error) {
	m.putItemCalls++
	return nil, m.putItemErr
}

func (m *mockDynamoClient) Query(_ context.Context, _ *dynamodb.QueryInput, _ ...func(*dynamodb.Options)) (*dynamodb.QueryOutput, error) {
	return &dynamodb.QueryOutput{Items: []map[string]types.AttributeValue{}}, nil
}

func (m *mockDynamoClient) DeleteItem(_ context.Context, _ *dynamodb.DeleteItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.DeleteItemOutput, error) {
	return &dynamodb.DeleteItemOutput{}, nil
}

func (m *mockDynamoClient) UpdateItem(_ context.Context, _ *dynamodb.UpdateItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.UpdateItemOutput, error) {
	return &dynamodb.UpdateItemOutput{}, nil
}

// ── Helper ────────────────────────────────────────────────────────────────────

func newTestStore(client dynamoClient) *Store {
	return &Store{
		client: client,
		table:  "test-outbox",
		logger: newTestLogger(),
		worker: "test-worker",
	}
}

// ── Test: Enqueue fails → error is returned to caller ────────────────────────
//
// This test documents the CURRENT behavior of Store.Enqueue:
// it returns an error when DynamoDB PutItem fails.
//
// The CALLER (checkout PlaceOrder) is responsible for deciding what to do
// with that error. Per checkout/main.go lines ~459-465:
//
//	enqueueErr := cs.Outbox.Enqueue(outboxCtx, outbox.Event{...})
//	if enqueueErr != nil {
//	    // Payment has already succeeded, so returning an error would invite a
//	    // duplicate charge. DynamoDB is Multi-AZ; surface the exceptional write
//	    // failure through telemetry and the outbox alert instead.
//	    logger.Error("failed to persist checkout outbox event", ...)
//	}
//
// Therefore: Store.Enqueue correctly returns the error; PlaceOrder correctly
// swallows it (logs only). This is the intended design — no gap.

func TestEnqueue_DynamoFailure_ReturnsError(t *testing.T) {
	mock := &mockDynamoClient{putItemErr: errors.New("DynamoDB unavailable")}
	store := newTestStore(mock)

	err := store.Enqueue(context.Background(), Event{
		ID:      "order-test-001",
		Payload: []byte("test-payload"),
	})

	// Store.Enqueue MUST return the error — caller (PlaceOrder) decides what to do.
	if err == nil {
		t.Fatal("FAIL: Enqueue should return error when DynamoDB fails, got nil")
	}
	if mock.putItemCalls != 1 {
		t.Fatalf("FAIL: expected 1 PutItem call, got %d", mock.putItemCalls)
	}
	t.Logf("PASS: Enqueue returned error: %v", err)
}

// ── Test: Enqueue success path ────────────────────────────────────────────────

func TestEnqueue_Success(t *testing.T) {
	mock := &mockDynamoClient{putItemErr: nil}
	store := newTestStore(mock)

	err := store.Enqueue(context.Background(), Event{
		ID:      "order-test-002",
		Payload: []byte("test-payload"),
	})

	if err != nil {
		t.Fatalf("FAIL: Enqueue should succeed, got: %v", err)
	}
	if mock.putItemCalls != 1 {
		t.Fatalf("FAIL: expected 1 PutItem call, got %d", mock.putItemCalls)
	}
	t.Log("PASS: Enqueue succeeded")
}

// ── Test: Enqueue with empty ID → validation error ───────────────────────────

func TestEnqueue_EmptyID_ReturnsValidationError(t *testing.T) {
	mock := &mockDynamoClient{}
	store := newTestStore(mock)

	err := store.Enqueue(context.Background(), Event{ID: "", Payload: []byte("x")})
	if err == nil {
		t.Fatal("FAIL: expected validation error for empty ID")
	}
	if mock.putItemCalls != 0 {
		t.Fatal("FAIL: PutItem should not be called for invalid event")
	}
	t.Logf("PASS: validation error returned: %v", err)
}

// ── Test: Enqueue with empty payload → validation error ──────────────────────

func TestEnqueue_EmptyPayload_ReturnsValidationError(t *testing.T) {
	mock := &mockDynamoClient{}
	store := newTestStore(mock)

	err := store.Enqueue(context.Background(), Event{ID: "order-x", Payload: []byte{}})
	if err == nil {
		t.Fatal("FAIL: expected validation error for empty payload")
	}
	if mock.putItemCalls != 0 {
		t.Fatal("FAIL: PutItem should not be called for invalid event")
	}
	t.Logf("PASS: validation error returned: %v", err)
}

// ── Test: Enqueue with context timeout ───────────────────────────────────────
// Simulates the 750ms timeout PlaceOrder sets for the enqueue call.

func TestEnqueue_ContextTimeout_ReturnsError(t *testing.T) {
	// Use a client that takes longer than context allows
	slowClient := &slowMockClient{}
	store := newTestStore(slowClient)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()

	err := store.Enqueue(ctx, Event{ID: "order-timeout", Payload: []byte("payload")})
	if err == nil {
		t.Fatal("FAIL: expected error due to context timeout")
	}
	t.Logf("PASS: context timeout returned error: %v", err)
}

type slowMockClient struct{}

func (s *slowMockClient) PutItem(ctx context.Context, _ *dynamodb.PutItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.PutItemOutput, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-time.After(5 * time.Second):
		return &dynamodb.PutItemOutput{}, nil
	}
}
func (s *slowMockClient) Query(_ context.Context, _ *dynamodb.QueryInput, _ ...func(*dynamodb.Options)) (*dynamodb.QueryOutput, error) {
	return &dynamodb.QueryOutput{}, nil
}
func (s *slowMockClient) DeleteItem(_ context.Context, _ *dynamodb.DeleteItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.DeleteItemOutput, error) {
	return &dynamodb.DeleteItemOutput{}, nil
}
func (s *slowMockClient) UpdateItem(_ context.Context, _ *dynamodb.UpdateItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.UpdateItemOutput, error) {
	return &dynamodb.UpdateItemOutput{}, nil
}
