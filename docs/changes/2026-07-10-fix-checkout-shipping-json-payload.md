# Change: Fix checkout shipping JSON payload (HTTP 500)

## Context

Requests to the checkout service were failing with HTTP 500. Frontend logs showed gRPC `INTERNAL` with:

`shipping quote failure: failed POST to shipping service: expected 200, got 400`

The shipping service’s Actix handlers reject bodies that fail Serde deserialization of `GetQuoteRequest` / `ShipOrderRequest`.

## Before

Checkout marshaled protobuf `Address` and `[]*CartItem` with Go `encoding/json` into the shipping HTTP body:

* A nil cart item slice became JSON `null` (`"items": null`), which shipping rejects (`expected a sequence`).
* Empty address strings were dropped via protobuf `omitempty` tags, so required shipping address fields were missing.

Shipping returned HTTP 400; checkout wrapped that as gRPC `INTERNAL`; the frontend middleware mapped it to HTTP 500.

## After

Checkout builds an explicit shipping DTO that matches the Rust HTTP contract:

* `items` is always a JSON array (`[]` when empty), never `null`.
* Address fields are always present under snake_case keys (`street_address`, `zip_code`, …).
* Cart items use `product_id` and `quantity` (as `uint32`).
* The same payload builder is used for `/get-quote` and `/ship-order`.
* `getUserCart` normalizes a nil item list to an empty slice.
* Empty carts fail early in order preparation (`cart is empty`) instead of calling shipping with invalid data.

## Implementation

* Added `shippingCartItem`, `shippingAddress`, `shippingRequest`, and `buildShippingRequestPayload`.
* `quoteShipping` and `shipOrder` call `buildShippingRequestPayload` instead of marshaling protobuf messages.
* Unit tests cover nil items, snake_case mapping, empty address fields, and negative quantity.

## Files Changed

* `src/checkout/main.go`

  * Shipping HTTP payload builder; quote/ship use it; empty-cart guard; nil cart items normalized.
* `src/checkout/main_test.go`

  * Tests for shipping payload marshaling.
* `docs/changes/2026-07-10-fix-checkout-shipping-json-payload.md`

  * This change document.

## Impact

* Application behavior: checkout no longer returns INTERNAL/500 solely because of a malformed shipping quote body for empty or partially empty cart/address data.
* Backward compatibility: shipping HTTP API unchanged; only checkout client payload generation is fixed.
* Reliability: fewer false 500s on the PlaceOrder path.

## Validation

```bash
cd src/checkout
go test ./...
```

## Migration or Deployment Notes

Redeploy the `checkout` service image so the fix is live in the cluster. No schema or config changes required.

## Risks and Rollback

* Risk: empty-cart PlaceOrder now fails earlier with `cart is empty` rather than failing at shipping (or succeeding with a zero-item order). That is intentional and clearer for clients.
* Rollback: redeploy the previous checkout image.
