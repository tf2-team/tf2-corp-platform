# API Schema Audit

Source: `docs/các API cần kết nối.md`

Result: all 18 fenced JSON schema blocks parse as JSON and contain `$schema`, `$id`, object `type`, and a `required` list where applicable.

Gaps fixed in code:

- Runtime config was missing from the API schema doc, so `config/runtime.json` now owns topology, signal, detector, and policy lists.
- Grafana normalized event now follows the documented event-shaped contract instead of returning only alert counts.
- Incident fingerprints now use `sha256:<digest>` to match the documented incident schema.

Still intentionally not implemented:

- Production anomaly/RCA engine. Current code keeps threshold, dependency, and no-data detectors production-shaped; anomaly/RCA needs live baseline evidence before enabling.
- Kubernetes mutation and blocked integrations. They remain policy/executor boundaries, not direct runtime adapters.
