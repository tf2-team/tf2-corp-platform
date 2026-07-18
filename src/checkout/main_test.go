// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"testing"

	pb "github.com/open-telemetry/techx-corp/src/checkout/genproto/oteldemo"
	"google.golang.org/grpc"
)

func TestIsRetryablePaymentChargeError(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{
			name: "paymentFailure inject is not retryable",
			err:  errors.New("Payment request failed. Invalid token. app.loyalty.level=gold"),
			want: false,
		},
		{
			name: "wrapped paymentFailure inject is not retryable",
			err:  errors.New("rpc error: code = Unknown desc = Payment request failed. Invalid token. app.loyalty.level=gold"),
			want: false,
		},
		{
			name: "generic unavailable",
			err:  errors.New("rpc error: code = Unavailable desc = connection refused"),
			want: true,
		},
		{
			name: "invalid card",
			err:  errors.New("Credit card info is invalid."),
			want: false,
		},
		{
			name: "unsupported card type",
			err:  errors.New("Sorry, we cannot process amex credit cards. Only VISA or MasterCard is accepted."),
			want: false,
		},
		{
			name: "expired card",
			err:  errors.New("The credit card is expired."),
			want: false,
		},
		{
			name: "nil",
			err:  nil,
			want: false,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := isRetryablePaymentChargeError(tc.err); got != tc.want {
				t.Fatalf("isRetryablePaymentChargeError(%v) = %v, want %v", tc.err, got, tc.want)
			}
		})
	}
}

func TestParseOrderCancelledBytes(t *testing.T) {
	orderID := "order-123"
	reason := "suspicious velocity"

	var data []byte
	// Field 1: OrderId (tag 1, wire type 2)
	data = append(data, 0x0a)
	data = append(data, byte(len(orderID)))
	data = append(data, []byte(orderID)...)

	// Field 2: Reason (tag 2, wire type 2)
	data = append(data, 0x12)
	data = append(data, byte(len(reason)))
	data = append(data, []byte(reason)...)

	gotID, gotReason, err := parseOrderCancelledBytes(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if gotID != orderID {
		t.Errorf("got OrderId = %q, want %q", gotID, orderID)
	}

	if gotReason != reason {
		t.Errorf("got Reason = %q, want %q", gotReason, reason)
	}
}

func TestBuildShippingRequestPayload_NilItemsBecomesEmptyArray(t *testing.T) {
	payload, err := buildShippingRequestPayload(&pb.Address{
		StreetAddress: "1600 Amphitheatre Parkway",
		City:          "Mountain View",
		State:         "CA",
		Country:       "United States",
		ZipCode:       "94043",
	}, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(payload, &raw); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if string(raw["items"]) != "[]" {
		t.Fatalf("items = %s, want [] (not null)", raw["items"])
	}
}

func TestBuildShippingRequestPayload_SnakeCaseAndQuantity(t *testing.T) {
	payload, err := buildShippingRequestPayload(&pb.Address{
		StreetAddress: "1600 Amphitheatre Parkway",
		City:          "Mountain View",
		State:         "CA",
		Country:       "United States",
		ZipCode:       "94043",
	}, []*pb.CartItem{
		{ProductId: "OLJCESPC7Z", Quantity: 2},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var req shippingRequest
	if err := json.Unmarshal(payload, &req); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if req.Address == nil {
		t.Fatal("expected address")
	}
	if req.Address.StreetAddress != "1600 Amphitheatre Parkway" || req.Address.ZipCode != "94043" {
		t.Fatalf("unexpected address: %+v", req.Address)
	}
	if len(req.Items) != 1 || req.Items[0].ProductID != "OLJCESPC7Z" || req.Items[0].Quantity != 2 {
		t.Fatalf("unexpected items: %+v", req.Items)
	}
}

func TestBuildShippingRequestPayload_EmptyAddressStringsStillPresent(t *testing.T) {
	// protobuf encoding/json omitempty would drop empty strings; shipping requires fields.
	payload, err := buildShippingRequestPayload(&pb.Address{}, []*pb.CartItem{
		{ProductId: "X", Quantity: 1},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(payload, &raw); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	var addr map[string]string
	if err := json.Unmarshal(raw["address"], &addr); err != nil {
		t.Fatalf("unmarshal address: %v", err)
	}
	for _, key := range []string{"street_address", "city", "state", "country", "zip_code"} {
		if _, ok := addr[key]; !ok {
			t.Fatalf("address missing required key %q in %s", key, raw["address"])
		}
	}
}

func TestBuildShippingRequestPayload_NegativeQuantity(t *testing.T) {
	_, err := buildShippingRequestPayload(nil, []*pb.CartItem{
		{ProductId: "X", Quantity: -1},
	})
	if err == nil {
		t.Fatal("expected error for negative quantity")
	}
}

func TestSendToPostProcessor_NilProducerDoesNotPanic(t *testing.T) {
	// Regression: PlaceOrder used to call KafkaProducerClient.Input() when
	// KAFKA_ADDR was set but producer creation had failed (nil client).
	prev := logger
	logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	t.Cleanup(func() { logger = prev })

	cs := &checkout{
		kafkaBrokerSvcAddr:  "kafka:9092",
		KafkaProducerClient: nil,
	}
	cs.sendToPostProcessor(context.Background(), &pb.OrderResult{OrderId: "order-nil-producer"})
}

func TestSendToPostProcessor_NilResultDoesNotPanic(t *testing.T) {
	prev := logger
	logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	t.Cleanup(func() { logger = prev })

	cs := &checkout{KafkaProducerClient: nil}
	cs.sendToPostProcessor(context.Background(), nil)
}

func TestEmptyUserCart_RetriesAndSucceeds(t *testing.T) {
	prev := logger
	logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	t.Cleanup(func() { logger = prev })

	cartClient := &stubCartServiceClient{
		emptyCartErrors: []error{
			errors.New("rpc error: code = Unknown desc = cartFailure"),
			errors.New("rpc error: code = Unknown desc = cartFailure"),
			nil,
		},
	}
	cs := &checkout{cartSvcClient: cartClient}

	if err := cs.emptyUserCart(context.Background(), "user-123"); err != nil {
		t.Fatalf("emptyUserCart returned error: %v", err)
	}
	if cartClient.emptyCartCalls != 3 {
		t.Fatalf("EmptyCart calls = %d, want 3", cartClient.emptyCartCalls)
	}
}

func TestEmptyUserCart_FailsAfterRetries(t *testing.T) {
	prev := logger
	logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	t.Cleanup(func() { logger = prev })

	cartClient := &stubCartServiceClient{
		emptyCartErrors: []error{
			errors.New("rpc error: code = Unknown desc = cartFailure"),
			errors.New("rpc error: code = Unknown desc = cartFailure"),
			errors.New("rpc error: code = Unknown desc = cartFailure"),
		},
	}
	cs := &checkout{cartSvcClient: cartClient}

	err := cs.emptyUserCart(context.Background(), "user-123")
	if err == nil {
		t.Fatal("expected emptyUserCart to return an error after retries")
	}
	if cartClient.emptyCartCalls != emptyCartMaxAttempts {
		t.Fatalf("EmptyCart calls = %d, want %d", cartClient.emptyCartCalls, emptyCartMaxAttempts)
	}
}

type stubCartServiceClient struct {
	pb.CartServiceClient
	emptyCartErrors []error
	emptyCartCalls  int
}

func (s *stubCartServiceClient) EmptyCart(ctx context.Context, in *pb.EmptyCartRequest, opts ...grpc.CallOption) (*pb.Empty, error) {
	s.emptyCartCalls++
	idx := s.emptyCartCalls - 1
	if idx < len(s.emptyCartErrors) && s.emptyCartErrors[idx] != nil {
		return nil, s.emptyCartErrors[idx]
	}
	return &pb.Empty{}, nil
}

// Change trail: @hungxqt - 2026-07-17 - paymentFailure not retryable; cart cleanup fails after retries.
