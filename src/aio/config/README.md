# AIOps runtime configuration

This directory is the runtime-owned configuration boundary. Python provides behavior; versioned YAML selects queries, signals, detectors, topology, routes, and action policy.

The checked-in TF2 scaffold is intentionally disabled until live metric identities, endpoints, owners, routes, and evidence references are approved. Do not add sample endpoints, credentials, guessed metric names, or fixture paths here. Environment endpoints and secrets must be supplied by Kubernetes ConfigMaps and Secrets.

Run `make aiops-config-check` from the repository root after every change.

