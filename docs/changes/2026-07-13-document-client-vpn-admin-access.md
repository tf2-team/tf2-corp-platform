# Change: Document Client VPN + CloudFront dual path for frontend-proxy

## Summary

Updated `frontend-proxy-guide.md` to match the current edge model: CloudFront (public HTTPS + admin 403s) and internal ALB (full paths), with **AWS Client VPN** as the supported private path for admin UIs.

## Context

The guide still described an internet-facing public ALB with ALB-level 403s. Infra/chart moved to internal ALB + CloudFront Function path blocking and optional Client VPN.

## Before

* Section 6 titled “Public ALB Ingress” assumed public ALB DNS for both storefront and path blocks.
* No Client VPN / internal ALB admin procedure.

## After

* Section 6 describes CloudFront + internal ALB + Client VPN dual path.
* Smoke curls use CloudFront for public/403 checks and internal ALB for VPN admin checks.

## Technical Design Decisions

* Documentation-only; Envoy routes unchanged.
* Point operators at `techx-corp-infra/docs/client-vpn.md` rather than duplicating full PKI steps.

## Implementation Details

1. Replaced section 6 public-ALB narrative with current edge architecture.
2. Added dual-path verification commands (CMD-friendly).

## Files Changed

* `frontend-proxy-guide.md` — Edge access model and verification.
* `docs/changes/2026-07-13-document-client-vpn-admin-access.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-infra/docs/changes/2026-07-13-introduce-client-vpn-for-internal-paths.md`
* Related: `techx-corp-chart/docs/changes/2026-07-13-document-client-vpn-admin-access.md`

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | None |
| **Infrastructure** | None |
| **Deployment** | None |
| **Backward compatibility** | Fully compatible (docs) |

## Validation

### Automated Checks

| Check | Command / Tool | Result |
|---|---|---|
| N/A (docs) | — | N/A |

### Manual Verification

* Guide matches infra `docs/client-vpn.md` and chart overlay comments.

### Remaining Verification (Post-Merge)

* None.

## Migration or Deployment Notes

None.

## Risks and Rollback

None for documentation-only change.

**Rollback procedure:** Revert `frontend-proxy-guide.md` and this change record.
