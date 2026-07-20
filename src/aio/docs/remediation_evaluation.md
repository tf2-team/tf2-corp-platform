# Remediation Evaluation

## Scope

Review the AIOps remediation configuration, topology safety assumptions, and action catalog so remediation recommendations can be evaluated consistently.

## Kubernetes Evidence

Checked the live `techx-corp-prod` namespace against `config/runtime.json`.

- The main application services in topology exist as Kubernetes Deployments: `checkout`, `payment`, `frontend`, `frontend-proxy`, `product-catalog`, `product-reviews`, `recommendation`, `cart`, `ad`, `currency`, `shipping`, `email`, `quote`, `flagd`, `fraud-detection`, `load-generator`, and `jaeger`.
- `product-catalog` uses PostgreSQL through `DB_CONNECTION_STRING` from secret `techx-corp-postgresql-app`; PostgreSQL is an external managed database dependency, not a namespace Deployment.
- `cart` uses managed Valkey through `VALKEY_ADDR=valkey-cart.techx.internal:6379` and `VALKEY_TLS_HOST=master.techx-prod-tf2-cart...cache.amazonaws.com`; Valkey is an external managed cache dependency, not a namespace Deployment.
- `opensearch` exists as a Kubernetes StatefulSet and should be treated as a stateful observability dependency.

## Runtime Changes

Updated `config/runtime.json` to better represent remediation safety boundaries.

- `postgresql` changed from `Deployment` in `techx-corp-prod` to external `Database`.
- `valkey-cart` changed from `Deployment` in `techx-corp-prod` to external `Database`.
- `opensearch` added to topology as `StatefulSet` in `techx-corp-prod` with `flow=observability`.
- `product-reviews` runtime dependency updated to include `product-catalog`, matching the broader topology evidence graph.
- `valkey-cart` and `opensearch` added to `policy.protected_targets`.

These changes keep real dependencies visible to RCA while preventing remediation from treating external/stateful systems as ordinary restartable Deployments.

## Action Catalog Review

Reviewed `config/actions.json` against the updated topology and policy.

- No restart action targets a protected target.
- No restart action targets a `Database` or `StatefulSet`.
- Restart action targets exist in topology and match `Deployment` kind.
- `restart_payment`, `restart_cart`, `restart_frontend`, and `restart_checkout` are consistent with the current topology and expected impact.
- `restart_frontend_proxy` has a wide `blast_radius_services` list. This is acceptable if `blast_radius_services` is interpreted as business impact rather than direct dependency graph only.
- `restart_product_catalog` includes `product-reviews` in `blast_radius_services`; this is consistent with the topology edge `product-reviews -> product-catalog`, now mirrored in runtime config.

## Evaluation Method

Use the following checks when reviewing future remediation changes.

1. Verify action targets exist in topology unless the action is an OnCall/page action.
2. Verify restart actions do not target `protected_targets`.
3. Verify restart actions do not target stateful kinds such as `Database` or `StatefulSet`.
4. Verify `blast_radius_services` contains known topology services.
5. Treat `blast_radius_services` as impacted services/business impact, not necessarily direct reverse dependencies.
6. Confirm remediation remains dry-run or fallback unless live approval and execution boundaries are explicitly implemented.

## Safety Tests

Executed remediation and policy tests with the project virtual environment.

```powershell
cd C:\Users\AdminPC\Downloads\projectx-brain\Aio_v2\tf2-corp-platform\src\aio
.\.venv\Scripts\python.exe -m pytest tests/test_core_pipeline.py -k "policy or remediation"
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_pipeline.py -k remediation
.\.venv\Scripts\python.exe -m pytest tests/test_e2e_pipeline_regression.py -k remediation
```

Observed result:

- `tests/test_core_pipeline.py -k "policy or remediation"`: 7 passed.
- `tests/test_runtime_pipeline.py -k remediation`: 1 passed.
- `tests/test_e2e_pipeline_regression.py -k remediation`: 1 passed.

Added policy coverage to verify `postgresql`, `valkey-cart`, and `opensearch` are blocked as protected/stateful remediation targets.

## Remaining Follow-up

No remediation safety blocker remains from this review. Future topology refreshes should continue validating `product-reviews -> product-catalog` with live trace or source evidence.
