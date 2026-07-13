// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package main

import (
	"encoding/json"
	"testing"

	pb "github.com/open-telemetry/techx-corp/src/checkout/genproto/oteldemo"
)

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
