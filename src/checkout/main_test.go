// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package main

import (
	"testing"
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
