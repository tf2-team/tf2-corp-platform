# Shopping Copilot cache evidence summary

Measured: 2026-07-29

| Scenario | Status | Match | Distance | Model behavior | Result |
|---|---|---|---:|---|---|
| First grounded discovery request | `miss` | `none` | `0` | Cold path | PASS |
| Exact repeat, same user/conversation/source | `hit` | `exact` | `0` | Counter unchanged in dedicated check | PASS |
| Safe paraphrase, same user/conversation/source | `hit` | `semantic` | `0.0846951` | Cache response reused | PASS |
| Repeated `NO_RESULTS` request | `miss`, `miss` | `none` | `0` | Not stored | PASS |
| Valkey entry lifetime | — | — | — | TTL `3348`–`3456` s vs configured `3600` s | PASS |
| Full local tests | — | — | — | `65 passed` | PASS |

## Important interpretation

The replay was run on a local CPU environment. End-to-end request latency
includes input guardrails and source snapshot work performed before cache
hydration, so this run does not claim a latency improvement. Cost avoidance is
shown directly by the Bedrock model-call counter remaining `16 -> 16` during a
dedicated exact-hit request.

No cache-disabled baseline, live Valkey fail-open, live user/conversation
isolation, or live source-invalidation mutation was measured in this pack.
Those cases remain reproducible from the runbook and are covered at unit level
where stated.
