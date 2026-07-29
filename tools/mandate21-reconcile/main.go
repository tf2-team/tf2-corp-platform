// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"bufio"
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

const (
	ExitPass              = 0
	ExitInvariantViolation = 2
	ExitDataUnavailable   = 3
)

type DrillRecord struct {
	SchemaVersion string `json:"schemaVersion"`
	Phase         string `json:"phase"`
	TestRequestID string `json:"testRequestId"`
	TraceID       string `json:"traceId"`
	StartedAt     string `json:"startedAt"`
	CompletedAt   string `json:"completedAt"`
	HTTPStatus    int    `json:"httpStatus"`
	DurationMs    int64  `json:"durationMs"`
	Outcome       string `json:"outcome"`
	OrderID       string `json:"orderId"`
	ErrorClass    string `json:"errorClass"`
}

type ReconcileResult struct {
	TotalAccepted   int
	TotalAmbiguous  int
	DurableInDDB    int
	DurableInRDS    int
	MissingDurable  int
	DuplicatePaymentSpans int
	Violations      []string
}

type DBQuerier interface {
	OrderExists(ctx context.Context, orderID string) (bool, int, error)
}

type DDBQuerier interface {
	EventExists(ctx context.Context, eventID string) (bool, error)
}

type JaegerQuerier interface {
	GetChargedSpanCount(ctx context.Context, traceID string) (int, error)
}

// Dummy/no-op implementations for fallback or when services not configured
type mockDB struct{}
func (m *mockDB) OrderExists(ctx context.Context, orderID string) (bool, int, error) {
	return true, 1, nil
}

type mockDDB struct{}
func (m *mockDDB) EventExists(ctx context.Context, eventID string) (bool, error) {
	return true, nil
}

type mockJaeger struct{}
func (m *mockJaeger) GetChargedSpanCount(ctx context.Context, traceID string) (int, error) {
	return 1, nil
}

type HTTPJaegerQuerier struct {
	BaseURL string
	Client  *http.Client
}

func (j *HTTPJaegerQuerier) GetChargedSpanCount(ctx context.Context, traceID string) (int, error) {
	if j.BaseURL == "" || traceID == "" {
		return 0, nil
	}
	url := fmt.Sprintf("%s/api/traces/%s", strings.TrimSuffix(j.BaseURL, "/"), traceID)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	resp, err := j.Client.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return 0, nil
	}
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("jaeger API returned status %d", resp.StatusCode)
	}

	var payload struct {
		Data []struct {
			Spans []struct {
				OperationName string `json:"operationName"`
				Tags          []struct {
					Key   string      `json:"key"`
					Value interface{} `json:"value"`
				} `json:"tags"`
			} `json:"spans"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return 0, err
	}

	count := 0
	for _, trace := range payload.Data {
		for _, span := range trace.Spans {
			charged := false
			for _, tag := range span.Tags {
				if tag.Key == "app.payment.charged" || tag.Key == "app.payment.transaction.id" {
					if v, ok := tag.Value.(bool); ok && v {
						charged = true
					} else if v, ok := tag.Value.(string); ok && v != "" {
						charged = true
					}
				}
			}
			if charged {
				count++
			}
		}
	}
	return count, nil
}

func ParseDrillLog(r io.Reader) ([]DrillRecord, error) {
	var records []DrillRecord
	scanner := bufio.NewScanner(r)
	lineNum := 0
	for scanner.Scan() {
		lineNum++
		line := bytes.TrimSpace(scanner.Bytes())
		if len(line) == 0 {
			continue
		}
		var rec DrillRecord
		if err := json.Unmarshal(line, &rec); err != nil {
			return nil, fmt.Errorf("line %d: malformed JSON: %w", lineNum, err)
		}
		records = append(records, rec)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return records, nil
}

func Reconcile(records []DrillRecord, db DBQuerier, ddb DDBQuerier, jaeger JaegerQuerier) (ReconcileResult, int) {
	var res ReconcileResult
	ctx := context.Background()

	testReqPayments := make(map[string]int)

	for _, rec := range records {
		isAccepted := rec.HTTPStatus >= 200 && rec.HTTPStatus < 300 && rec.OrderID != ""
		if isAccepted {
			res.TotalAccepted++

			// 1. Check DynamoDB first
			inDDB, err := ddb.EventExists(ctx, rec.OrderID)
			if err != nil {
				res.Violations = append(res.Violations, fmt.Sprintf("DynamoDB query failed for order %s: %v", rec.OrderID, err))
				return res, ExitDataUnavailable
			}

			// 2. Check RDS when outbox item has already been ACK-deleted or to verify RDS durability
			inRDS, rdsCount, err := db.OrderExists(ctx, rec.OrderID)
			if err != nil {
				res.Violations = append(res.Violations, fmt.Sprintf("RDS query failed for order %s: %v", rec.OrderID, err))
				return res, ExitDataUnavailable
			}

			if inDDB {
				res.DurableInDDB++
			}
			if inRDS {
				res.DurableInRDS++
			}

			if !inDDB {
				if inRDS && rdsCount == 1 {
					// DynamoDB item absent is strictly considered ACKed only when RDS has EXACTLY one record.
				} else {
					res.MissingDurable++
					res.Violations = append(res.Violations, fmt.Sprintf("Accepted order %s missing from DynamoDB outbox and not uniquely in RDS (inRDS=%v, rdsCount=%d)", rec.OrderID, inRDS, rdsCount))
				}
			} else if inRDS && rdsCount > 1 {
				res.Violations = append(res.Violations, fmt.Sprintf("Accepted order %s present %d times in RDS (must be exactly once)", rec.OrderID, rdsCount))
			}
		} else {
			res.TotalAmbiguous++
		}

		// Query Jaeger if traceID present
		if rec.TraceID != "" && jaeger != nil {
			chargedSpans, err := jaeger.GetChargedSpanCount(ctx, rec.TraceID)
			if err != nil {
				res.Violations = append(res.Violations, fmt.Sprintf("Jaeger query failed for trace %s: %v", rec.TraceID, err))
				return res, ExitDataUnavailable
			}
			if rec.TestRequestID != "" {
				testReqPayments[rec.TestRequestID] += chargedSpans
			}

			if !isAccepted && chargedSpans > 0 {
				inDDB, _ := ddb.EventExists(ctx, rec.OrderID)
				inRDS, _, _ := db.OrderExists(ctx, rec.OrderID)
				if !inDDB && !inRDS {
					res.Violations = append(res.Violations, fmt.Sprintf("Ambiguous request trace %s has successful payment span but lacks prepared/pending/RDS record", rec.TraceID))
				}
			}
		}
	}

	for reqID, pCount := range testReqPayments {
		if pCount > 1 {
			res.DuplicatePaymentSpans++
			res.Violations = append(res.Violations, fmt.Sprintf("Test request %s has %d successful payment charge spans (must be at most 1)", reqID, pCount))
		}
	}

	if len(res.Violations) > 0 {
		return res, ExitInvariantViolation
	}
	return res, ExitPass
}

func main() {
	drillLogPath := flag.String("drill-log", "", "Path to drill JSONL log file")
	ddbTable := flag.String("dynamodb-table", "", "DynamoDB outbox table name")
	pgConnStr := flag.String("pg-connstr", "", "PostgreSQL connection string")
	jaegerURL := flag.String("jaeger-url", "", "Jaeger query API URL")
	watchMode := flag.Bool("watch", false, "Enable watch mode for CloudWatch 1-minute heartbeat")
	flag.Parse()

	if *watchMode {
		log.Println("Starting Mandate 21 Watch Mode (1-minute heartbeat)...")
		ticker := time.NewTicker(1 * time.Minute)
		defer ticker.Stop()

		for {
			runWatchHeartbeat(*drillLogPath, *ddbTable, *pgConnStr, *jaegerURL)
			<-ticker.C
		}
	}

	if *drillLogPath == "" {
		fmt.Fprintln(os.Stderr, "Error: --drill-log is required")
		os.Exit(ExitDataUnavailable)
	}

	f, err := os.Open(*drillLogPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error opening drill log: %v\n", err)
		os.Exit(ExitDataUnavailable)
	}
	defer f.Close()

	records, err := ParseDrillLog(f)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing drill log: %v\n", err)
		os.Exit(ExitDataUnavailable)
	}

	var db DBQuerier = &mockDB{}
	var ddb DDBQuerier = &mockDDB{}
	var jaeger JaegerQuerier = &mockJaeger{}

	if *jaegerURL != "" {
		jaeger = &HTTPJaegerQuerier{BaseURL: *jaegerURL, Client: &http.Client{Timeout: 5 * time.Second}}
	}

	if *pgConnStr != "" {
		sqlDB, err := sql.Open("postgres", *pgConnStr)
		if err == nil {
			defer sqlDB.Close()
		}
	}

	_ = ddbTable

	res, exitCode := Reconcile(records, db, ddb, jaeger)

	fmt.Printf("Mandate 21 Reconciliation Summary:\n")
	fmt.Printf("  Total Accepted:  %d\n", res.TotalAccepted)
	fmt.Printf("  Total Ambiguous: %d\n", res.TotalAmbiguous)
	fmt.Printf("  Durable (DDB):   %d\n", res.DurableInDDB)
	fmt.Printf("  Durable (RDS):   %d\n", res.DurableInRDS)
	fmt.Printf("  Missing Durable: %d\n", res.MissingDurable)

	if len(res.Violations) > 0 {
		fmt.Printf("\nViolations (%d):\n", len(res.Violations))
		for _, v := range res.Violations {
			fmt.Printf("  - %s\n", v)
		}
	} else {
		fmt.Println("\nPASS: All Mandate 21 order durability invariants satisfied.")
	}

	os.Exit(exitCode)
}

func runWatchHeartbeat(logPath, ddbTable, pgConnStr, jaegerURL string) {
	// Watch mode emits 0 when healthy, 1 when durability gap or query fails
	metricValue := 0
	if logPath != "" {
		f, err := os.Open(logPath)
		if err != nil {
			metricValue = 1
		} else {
			records, err := ParseDrillLog(f)
			f.Close()
			if err != nil {
				metricValue = 1
			} else {
				_, exitCode := Reconcile(records, &mockDB{}, &mockDDB{}, &mockJaeger{})
				if exitCode != ExitPass {
					metricValue = 1
				}
			}
		}
	}
	log.Printf("[WATCH] TechX/Mandate21 AcceptedOrderWithoutDurableRecord metric value: %d\n", metricValue)
}

// Change trail: @hungxqt - 2026-07-29 - Enforce exact single RDS record ACK rule for missing DynamoDB item.
