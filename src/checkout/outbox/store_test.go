// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package outbox

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

type fakeDynamo struct {
	putInput    *dynamodb.PutItemInput
	queryOutput *dynamodb.QueryOutput
	queryErr    error
	deleteCount int
	updateCount int
	updateInputs []*dynamodb.UpdateItemInput
}

func (f *fakeDynamo) PutItem(_ context.Context, input *dynamodb.PutItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.PutItemOutput, error) {
	f.putInput = input
	return &dynamodb.PutItemOutput{}, nil
}

func (f *fakeDynamo) Query(_ context.Context, _ *dynamodb.QueryInput, _ ...func(*dynamodb.Options)) (*dynamodb.QueryOutput, error) {
	return f.queryOutput, f.queryErr
}

func (f *fakeDynamo) DeleteItem(_ context.Context, _ *dynamodb.DeleteItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.DeleteItemOutput, error) {
	f.deleteCount++
	return &dynamodb.DeleteItemOutput{}, nil
}

func (f *fakeDynamo) UpdateItem(_ context.Context, input *dynamodb.UpdateItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.UpdateItemOutput, error) {
	f.updateCount++
	f.updateInputs = append(f.updateInputs, input)
	return &dynamodb.UpdateItemOutput{}, nil
}

func testStore(client dynamoClient) *Store {
	return &Store{
		client: client,
		table:  "checkout-outbox",
		logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
		worker: "test-worker",
	}
}

func TestEnqueueUsesOrderIDAsIdempotencyKey(t *testing.T) {
	fake := &fakeDynamo{}
	store := testStore(fake)
	if err := store.Enqueue(context.Background(), Event{ID: "order-123", Payload: []byte("payload")}); err != nil {
		t.Fatalf("Enqueue() error = %v", err)
	}
	if fake.putInput == nil || *fake.putInput.ConditionExpression != "attribute_not_exists(event_id)" {
		t.Fatal("expected conditional put for idempotency")
	}
	id := fake.putInput.Item["event_id"].(*types.AttributeValueMemberS)
	if id.Value != "order-123" {
		t.Fatalf("event_id = %q, want order-123", id.Value)
	}
}

func TestPublishBatchWaitsForPersistenceAckBeforeDelete(t *testing.T) {
	item := map[string]types.AttributeValue{
		"event_id": &types.AttributeValueMemberS{Value: "order-123"},
		"payload":  &types.AttributeValueMemberB{Value: []byte("payload")},
	}
	fake := &fakeDynamo{queryOutput: &dynamodb.QueryOutput{Items: []map[string]types.AttributeValue{item}}}
	store := testStore(fake)

	err := store.publishBatch(context.Background(), func(context.Context, Event) error {
		return errors.New("Kafka unavailable")
	})
	if err == nil {
		t.Fatal("expected publish error")
	}
	if fake.deleteCount != 0 {
		t.Fatalf("deleteCount = %d, event must remain pending", fake.deleteCount)
	}

	if err := store.publishBatch(context.Background(), func(context.Context, Event) error { return nil }); err != nil {
		t.Fatalf("publishBatch() recovery error = %v", err)
	}
	if fake.deleteCount != 0 {
		t.Fatalf("deleteCount = %d, event must remain until RDS persistence ACK", fake.deleteCount)
	}
	lastUpdate := fake.updateInputs[len(fake.updateInputs)-1]
	if lastUpdate.UpdateExpression == nil || *lastUpdate.UpdateExpression != "SET #status = :published, published_at = :published_at REMOVE lease_owner, lease_until" {
		t.Fatal("expected successful publish to mark event as published")
	}

	if err := store.Acknowledge(context.Background(), "order-123"); err != nil {
		t.Fatalf("Acknowledge() error = %v", err)
	}
	if fake.deleteCount != 1 {
		t.Fatalf("deleteCount = %d, want 1 after RDS persistence ACK", fake.deleteCount)
	}
}

func TestPreparePutsPreparedStatus(t *testing.T) {
	fake := &fakeDynamo{}
	store := testStore(fake)
	if err := store.Prepare(context.Background(), Event{ID: "order-prep", Payload: []byte("payload")}); err != nil {
		t.Fatalf("Prepare() error = %v", err)
	}
	if fake.putInput == nil {
		t.Fatal("expected PutItem call")
	}
	statusAttr := fake.putInput.Item["status"].(*types.AttributeValueMemberS)
	if statusAttr.Value != "prepared" {
		t.Fatalf("status = %q, want prepared", statusAttr.Value)
	}
}

func TestActivateUpdatesToPendingStatus(t *testing.T) {
	fake := &fakeDynamo{}
	store := testStore(fake)
	now := time.Now()
	if err := store.Activate(context.Background(), "order-prep", now, "trace-123", "tx-456"); err != nil {
		t.Fatalf("Activate() error = %v", err)
	}
	if fake.updateCount != 1 {
		t.Fatalf("updateCount = %d, want 1", fake.updateCount)
	}
	lastUpdate := fake.updateInputs[0]
	if *lastUpdate.UpdateExpression != "SET #status = :pending, charged_at = :charged_at, trace_id = :trace_id, transaction_id = :transaction_id" {
		t.Fatalf("UpdateExpression = %q", *lastUpdate.UpdateExpression)
	}
}

func TestRemovePreparedDeletesItem(t *testing.T) {
	fake := &fakeDynamo{}
	store := testStore(fake)
	if err := store.RemovePrepared(context.Background(), "order-prep"); err != nil {
		t.Fatalf("RemovePrepared() error = %v", err)
	}
	if fake.deleteCount != 1 {
		t.Fatalf("deleteCount = %d, want 1", fake.deleteCount)
	}
}

// Change trail: @hungxqt - 2026-07-28 - Add Prepare, Activate, and RemovePrepared tests for outbox store.
