# TechX Audit Alert Parser

Phase 7 parser/normalizer/rule matcher with Task 11.6 allowlist-based noise reduction, redaction, Vietnamese alert formatting, parser-side evidence/TTD records, and mandate-focused unit test coverage.

## Current Scope

- Detect and normalize EventBridge CloudTrail event shape.
- Decode CloudWatch Logs subscription payloads (`awslogs.data`) from base64+gzip.
- Normalize Kubernetes audit records from CloudWatch Logs `DATA_MESSAGE` payloads.
- Ignore CloudWatch Logs `CONTROL_MESSAGE` payloads safely.
- Match dangerous events against `config/rules.yaml`.
- Apply behavior-first IAM detection: policy attach/mutation in production alerts by
  default, while approved Terraform/CI-CD actors are handled by the 11.6 allowlist.
- Parse CloudTrail `policyDocument` directly for high-risk permissions without
  calling IAM APIs from the Lambda hot path.
- Detect EKS audit logging disablement from `UpdateClusterConfig`.
- Inspect Kubernetes `requestObject` for privileged containers, host namespace
  access, and hostPath volumes.
- Attach `rule_id`, `severity`, `title_vi`, `impact_vi`, and `first_action_vi`.
- Evaluate allowlist/noise-reduction entries from `config/allowlist.yaml`.
- Suppress only matched dangerous events with owner, ticket, reason, and review date.
- Keep suppression evidence records so allowlisted events are not dropped silently.
- Redact secret-looking keys and values before message formatting.
- Format alert-candidate messages in Vietnamese with Who/What/When/Where context.
- Convert event time from UTC to ICT for human-readable messages while keeping UTC in normalized data.
- Build structured evidence records for `alert_ready`, `suppressed`, `ignored`, and `parse_error`.
- Emit each evidence record as one JSON line to Lambda stdout so CloudWatch Logs
  can be used by Task 11.5 for parser-side TTD evidence.
- Add parser-side timestamps and latency fields for Task 11.5 TTD handoff.
- Cover the Phase 7 mandate checklist with unit tests.
- Run parser tests in GitHub Actions via `.github/workflows/audit-alert-parser-tests.yml`.
- Provide module boundaries for parser, normalizer, rule matcher, allowlist, redaction, formatter, evidence, and TTD.
- Provide JSON fixtures for the first production-oriented tests.

## Not Implemented Yet

- Routing to Discord or on-call systems.
- Final Discord/on-call `sent` evidence from the Task 11.4 router.

Those items are intentionally left for the next phases so Phase 7 stays small and reviewable.

## Local Validation

```powershell
cd "E:\Xbrain\tf_learning\phase 3\TEAM\tf2-corp-platform\src\audit-alert-parser"
python -m pytest -q -p no:cacheprovider
```

## Phase 7 Test Checklist

- CloudTrail `CreateAccessKey`.
- CloudTrail IAM admin policy.
- CloudTrail IAM policy attach requiring review.
- CloudTrail IAM policy mutation requiring review.
- CloudTrail EKS access entry creation.
- CloudTrail EKS cluster-admin access.
- CloudTrail EKS audit logging disabled.
- CloudTrail `StopLogging`.
- EKS `get secrets`.
- EKS `clusterrolebinding` to `cluster-admin`.
- EKS `pods/exec` in production namespace.
- EKS privileged/host-access workload.
- EKS production resource deletion.
- Allowlist suppress.
- Unknown actor remains an alert candidate.
- Missing fields do not crash.
- Secret/token/webhook values are redacted.
- CloudWatch Logs `CONTROL_MESSAGE` is ignored safely.
- Parse errors produce structured evidence instead of crashing.
- Mentor use-case integration tests simulate CloudTrail/EventBridge and
  Kubernetes audit/CloudWatch Logs subscription payloads end-to-end.
