# Change: Fix checkout nil Kafka producer panic on PlaceOrder

## Summary

Checkout pods panicked with a nil pointer dereference in `sendToPostProcessor` during `PlaceOrder` when `KAFKA_ADDR` was set but the Sarama async producer failed to initialize. The service now guards all producer uses, skips post-processing safely when the producer is unavailable, and no longer races on the producer `Errors()` channel.

## Context

Production/dev checkout logs showed:

* `panic: runtime error: invalid memory address or nil pointer dereference`
* Stack: `PlaceOrder` → `sendToPostProcessor` at `main.go:813` (`KafkaProducerClient.Input()`)
* Secondary noise from OpenTelemetry `recordingSpan.End` re-raising the original panic

`KAFKA_ADDR` is always injected by Helm/Compose. Producer creation is soft-fail (log only). `PlaceOrder` previously treated a non-empty broker address as “producer ready,” which is false when broker metadata/connect fails at startup (Kafka not ready, DNS, network).

## Before

* Startup: if `CreateKafkaProducer` failed, error was logged and `KafkaProducerClient` stayed `nil`.
* `PlaceOrder` called `sendToPostProcessor` whenever `kafkaBrokerSvcAddr != ""`.
* `sendToPostProcessor` unconditionally called `cs.KafkaProducerClient.Input()` → SIGSEGV.
* `kafka.CreateKafkaProducer` started a background goroutine draining `producer.Errors()`, racing with `sendToPostProcessor`’s own `Errors()` select (hang until context cancel on produce failure).
* `ApprovedOrderConsumer` could also nil-deref when publishing `orders-shipped`.

## After

* Startup still soft-fails producer creation (service stays up for checkout), but logs that post-processing is disabled and keeps `KafkaProducerClient == nil`.
* `PlaceOrder` only posts when **both** broker address and non-nil producer are present; otherwise warns and completes the order without Kafka.
* `sendToPostProcessor` defensive nil checks on producer and order result.
* Consumer path skips `orders-shipped` publish when producer is nil (logs error, marks message).
* Producer factory no longer steals `Errors()` from callers.

## Technical Design Decisions

* **Soft-fail over crash-loop on producer init:** preserves PlaceOrder availability when Kafka is temporarily unavailable at pod start. Trade-off: accounting/fraud async pipeline is skipped until the pod is restarted with a working producer. Fail-fast was rejected because it couples checkout readiness hard to Kafka readiness without a retry loop.
* **Nil guards at call sites + inside `sendToPostProcessor`:** defense in depth for any future caller.
* **Remove background `Errors()` drain:** callers that `select` on success/error need exclusive ownership of those channels; background drain was a latent hang, not the reported SIGSEGV.

## Implementation Details

1. Producer init failure path: explicit `KafkaProducerClient = nil` and clearer error log.
2. `PlaceOrder` condition: `kafkaBrokerSvcAddr != "" && KafkaProducerClient != nil`.
3. `sendToPostProcessor`: early return on nil producer or nil result.
4. `ApprovedOrderConsumer`: nil producer check before `Input()` for `orders-shipped`.
5. `kafka/producer.go`: remove background `Errors()` consumer.
6. Unit tests: nil producer and nil result must not panic.

## Files Changed

**Application:**
* `src/checkout/main.go` — Nil-safe PlaceOrder / sendToPostProcessor / consumer publish path.
* `src/checkout/kafka/producer.go` — Stop draining `Errors()` in factory.
* `src/checkout/main_test.go` — Regression tests for nil producer/result.

**Documentation:**
* `docs/changes/2026-07-14-fix-checkout-nil-kafka-producer-panic.md` — This change record.

## Dependencies and Cross-Repository Impact

None for code deploy of the fix itself.

Operational note: if post-processing remains skipped, verify Kafka readiness and restart checkout after the broker is healthy so a producer can be created. Chart/infra changes not required for the panic fix.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | PlaceOrder no longer crashes when Kafka producer is missing; orders still charge/email; Kafka order event may be skipped until producer is available |
| **Infrastructure** | No change |
| **Deployment** | Redeploy checkout image with this fix |
| **Performance** | No material change |
| **Security** | No change |
| **Reliability** | Removes pod-killing panic on checkout path; soft degradation instead of crash |
| **Cost** | None |
| **Backward compatibility** | Fully backward-compatible API |
| **Observability** | New warn/error logs when producer is unavailable or send is skipped |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| Unit tests | `go test ./... -count=1` (from `src/checkout`) | ✅ Pass |

### Manual Verification

* Stack trace matched `main.go:813` → `KafkaProducerClient.Input()` with nil client when `KAFKA_ADDR` set.
* Local regression tests cover nil producer/result paths.

### Remaining Verification (Post-Merge)

* Redeploy checkout to the affected cluster/namespace.
* Confirm no checkout panics on PlaceOrder under load.
* If orders do not appear in accounting/fraud consumers: check checkout logs for “Kafka producer is not available” / “failed to create Kafka producer”, ensure Kafka is Ready, then restart checkout.

## Migration or Deployment Notes

1. Build and push a new checkout image (platform CI or local bake for the checkout service).
2. Promote chart image tag (dev auto / prod PR per existing pipeline).
3. After deploy, if Kafka was the original root cause of producer init failure, ensure Kafka is healthy **before** or **and** restart checkout so producer initializes.

```cmd
cd /d techx-corp-platform\src\checkout
go test ./... -count=1
```

## Risks and Rollback

| Risk | Likelihood | Severity | Mitigation / Rollback |
|---|---|---|---|
| Orders complete without Kafka post-processing while producer is down | Medium | Medium | Monitor checkout logs; fix Kafka; restart checkout |
| Produce failures now surface only to the PlaceOrder wait path (no factory drain) | Low | Low | Intended; errors logged in `sendToPostProcessor` |

**Rollback procedure:**

Revert this commit in `techx-corp-platform` and redeploy the previous checkout image tag via chart values. Note: rollback reintroduces the panic when producer init fails.

<!-- Change trail: @hungxqt - 2026-07-14 - Document nil Kafka producer PlaceOrder panic fix. -->
