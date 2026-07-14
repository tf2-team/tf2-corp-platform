// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package outbox

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

const pendingStatus = "pending"

type dynamoClient interface {
	PutItem(context.Context, *dynamodb.PutItemInput, ...func(*dynamodb.Options)) (*dynamodb.PutItemOutput, error)
	Query(context.Context, *dynamodb.QueryInput, ...func(*dynamodb.Options)) (*dynamodb.QueryOutput, error)
	DeleteItem(context.Context, *dynamodb.DeleteItemInput, ...func(*dynamodb.Options)) (*dynamodb.DeleteItemOutput, error)
	UpdateItem(context.Context, *dynamodb.UpdateItemInput, ...func(*dynamodb.Options)) (*dynamodb.UpdateItemOutput, error)
}

// Store is a durable DynamoDB queue between the customer checkout response and
// Kafka. Pending records survive pod restarts and Kafka outages.
type Store struct {
	client dynamoClient
	table  string
	logger *slog.Logger
	worker string
}

type Event struct {
	ID      string
	Payload []byte
}

func New(ctx context.Context, table string, logger *slog.Logger) (*Store, error) {
	if table == "" {
		return nil, fmt.Errorf("outbox table is required")
	}
	awsConfig, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		return nil, fmt.Errorf("load AWS configuration: %w", err)
	}
	return &Store{
		client: dynamodb.NewFromConfig(awsConfig),
		table:  table,
		logger: logger,
		worker: fmt.Sprintf("worker-%d", time.Now().UnixNano()),
	}, nil
}

func (s *Store) Enqueue(ctx context.Context, event Event) error {
	if event.ID == "" || len(event.Payload) == 0 {
		return fmt.Errorf("event id and payload are required")
	}
	_, err := s.client.PutItem(ctx, &dynamodb.PutItemInput{
		TableName: &s.table,
		Item: map[string]types.AttributeValue{
			"event_id":   &types.AttributeValueMemberS{Value: event.ID},
			"status":     &types.AttributeValueMemberS{Value: pendingStatus},
			"created_at": &types.AttributeValueMemberN{Value: strconv.FormatInt(time.Now().UnixMilli(), 10)},
			"payload":    &types.AttributeValueMemberB{Value: event.Payload},
		},
		// The order ID is the idempotency key. A retry must not create a second event.
		ConditionExpression: strPtr("attribute_not_exists(event_id)"),
	})
	if err != nil {
		return fmt.Errorf("put outbox event: %w", err)
	}
	return nil
}

// Run publishes pending events outside the checkout request path. Records are
// deleted only after the publisher confirms Kafka success.
func (s *Store) Run(ctx context.Context, publish func(context.Context, Event) error) {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()

	for {
		if err := s.publishBatch(ctx, publish); err != nil && ctx.Err() == nil {
			s.logger.Error("checkout outbox publish batch failed", "error", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func (s *Store) publishBatch(ctx context.Context, publish func(context.Context, Event) error) error {
	statusName := "status"
	pending := pendingStatus
	result, err := s.client.Query(ctx, &dynamodb.QueryInput{
		TableName:              &s.table,
		IndexName:              strPtr("status-created-index"),
		KeyConditionExpression: strPtr("#status = :pending"),
		ExpressionAttributeNames: map[string]string{
			"#status": statusName,
		},
		ExpressionAttributeValues: map[string]types.AttributeValue{
			":pending": &types.AttributeValueMemberS{Value: pending},
		},
		Limit: int32Ptr(25),
	})
	if err != nil {
		return fmt.Errorf("query pending events: %w", err)
	}

	for _, item := range result.Items {
		id, idOK := item["event_id"].(*types.AttributeValueMemberS)
		payload, payloadOK := item["payload"].(*types.AttributeValueMemberB)
		if !idOK || !payloadOK {
			s.logger.Error("invalid checkout outbox record", "item", item)
			continue
		}
		event := Event{ID: id.Value, Payload: payload.Value}
		claimed, err := s.claim(ctx, event.ID)
		if err != nil {
			return err
		}
		if !claimed {
			continue
		}
		publishCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		err = publish(publishCtx, event)
		cancel()
		if err != nil {
			s.release(ctx, event.ID)
			// Preserve ordering and avoid hammering Kafka while it is unavailable.
			return fmt.Errorf("publish event %s: %w", event.ID, err)
		}
		_, err = s.client.DeleteItem(ctx, &dynamodb.DeleteItemInput{
			TableName: &s.table,
			Key: map[string]types.AttributeValue{
				"event_id": &types.AttributeValueMemberS{Value: event.ID},
			},
			ConditionExpression: strPtr("lease_owner = :worker"),
			ExpressionAttributeValues: map[string]types.AttributeValue{
				":worker": &types.AttributeValueMemberS{Value: s.worker},
			},
		})
		if err != nil {
			return fmt.Errorf("delete published event %s: %w", event.ID, err)
		}
	}
	return nil
}

// claim prevents two checkout replicas from publishing the same pending event.
// The lease expires automatically so another healthy pod can recover work after
// a worker crash without a coordinator or singleton leader.
func (s *Store) claim(ctx context.Context, eventID string) (bool, error) {
	now := time.Now().Unix()
	_, err := s.client.UpdateItem(ctx, &dynamodb.UpdateItemInput{
		TableName: &s.table,
		Key: map[string]types.AttributeValue{
			"event_id": &types.AttributeValueMemberS{Value: eventID},
		},
		UpdateExpression:    strPtr("SET lease_owner = :worker, lease_until = :lease_until"),
		ConditionExpression: strPtr("attribute_not_exists(lease_until) OR lease_until < :now"),
		ExpressionAttributeValues: map[string]types.AttributeValue{
			":worker":      &types.AttributeValueMemberS{Value: s.worker},
			":lease_until": &types.AttributeValueMemberN{Value: strconv.FormatInt(now+30, 10)},
			":now":         &types.AttributeValueMemberN{Value: strconv.FormatInt(now, 10)},
		},
	})
	if err == nil {
		return true, nil
	}
	var conditional *types.ConditionalCheckFailedException
	if errors.As(err, &conditional) {
		return false, nil
	}
	return false, fmt.Errorf("claim outbox event %s: %w", eventID, err)
}

func (s *Store) release(ctx context.Context, eventID string) {
	_, err := s.client.UpdateItem(ctx, &dynamodb.UpdateItemInput{
		TableName: &s.table,
		Key: map[string]types.AttributeValue{
			"event_id": &types.AttributeValueMemberS{Value: eventID},
		},
		UpdateExpression:    strPtr("REMOVE lease_owner, lease_until"),
		ConditionExpression: strPtr("lease_owner = :worker"),
		ExpressionAttributeValues: map[string]types.AttributeValue{
			":worker": &types.AttributeValueMemberS{Value: s.worker},
		},
	})
	if err != nil {
		s.logger.Error("failed to release checkout outbox lease", "event_id", eventID, "error", err)
	}
}

func strPtr(value string) *string { return &value }
func int32Ptr(value int32) *int32 { return &value }
