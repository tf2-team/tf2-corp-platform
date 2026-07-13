# Change: Fix cart emptying on page refresh (session identity)

## Context

After adding items, a full page refresh showed an empty cart. Cart data lives in Valkey keyed by `userId`; the browser must send the same session id on every request.

## Before

Several modules captured the session once at **import time**:

```ts
const { userId } = SessionGateway.getSession();
```

On SSR (`window` undefined), `getSession()` returned a module-level default session that is not the browser’s `localStorage` session. That throwaway id was baked into `Api.gateway` cart calls when the module was first evaluated in a context without `localStorage`, so add-to-cart and later get-cart could use different (or non-persisted) user ids. After refresh, get-cart used the real localStorage id (or a newly generated one) and found no items.

`Session.gateway` also reused a single module-level `defaultSession` object and did not validate stored JSON.

## After

* `Session.gateway` reads/writes `localStorage` with validation, creates a **new** UUID only when no valid session exists, and returns a non-durable placeholder on SSR (empty `userId`, `USD`).
* `Api.gateway` resolves `userId` via `getUserId()` **on every API call**, not at module load.
* `CartDetail`, `Footer`, and `SessionIdProcessor` resolve the session at use time (submit / mount / span start).
* `Currency.provider` defaults to `USD` and hydrates currency from the session after mount (no empty initial currency).
* `Cart.provider` enables the cart query only when a currency is set.

## Implementation

Call-time session resolution is the main fix; session storage is hardened to match the upstream OTel demo’s safer parse/validate pattern without caching identity at import time.

## Files Changed

* `src/frontend/gateways/Session.gateway.ts` — durable localStorage session; SSR-safe placeholder; validation.
* `src/frontend/gateways/Api.gateway.ts` — `getUserId()` per request.
* `src/frontend/components/Cart/CartDetail.tsx` — userId at place-order time.
* `src/frontend/components/Footer/Footer.tsx` — session id after mount.
* `src/frontend/utils/telemetry/SessionIdProcessor.ts` — session id on span start.
* `src/frontend/providers/Currency.provider.tsx` — stable currency init/hydrate.
* `src/frontend/providers/Cart.provider.tsx` — cart query `enabled` when currency is set.
* `docs/changes/2026-07-10-fix-frontend-cart-session-persistence.md` — this document.

## Impact

* Application behavior: cart items persist across full page refresh for the same browser profile (same `localStorage` session).
* Reliability: add-to-cart and get-cart use the same Valkey key.
* Notes: cart still expires after ~60 minutes of inactivity (Valkey TTL) and is cleared after a successful checkout.

## Validation

* Manual: add item → refresh → cart still contains item; footer session-id unchanged after refresh.
* Typecheck (if run): `cd src/frontend && npm run type:check` (or project equivalent).

## Migration or Deployment Notes

Redeploy the **frontend** image. Existing browsers keep a valid `localStorage.session` entry; invalid entries are recreated once.

## Risks and Rollback

* Risk: users with corrupted `localStorage` session JSON get a new session (empty cart once). Expected.
* Rollback: redeploy previous frontend image.
