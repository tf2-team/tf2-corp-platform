# Change: Support an externally delivered AI guardrail model cache

## Summary

`product-reviews` can now run with a pinned Hugging Face cache supplied by the
deployment environment instead of baking model weights into its Docker image.
Local development remains compatible with the normal user cache.

## Implementation

- Cached the LLM Guard prompt-injection scanner so model initialization occurs
  once per process rather than once per review or request.
- Added `AI_GUARDRAIL_REQUIRE_MODEL=true` strict mode. In cloud deployments the
  service fails before opening gRPC when the model cannot load; local/test mode
  retains the documented keyword fallback.
- Added `build_model_artifact.py` to download the reviewed ProtectAI revision,
  pin offline `main` resolution to that commit, validate the runtime loader and
  generate `model.tar.gz`, SHA-256 and manifest files.
- Ignored generated model archives and increased the local Compose memory limit
  for the scanner runtime.

## Cross-Repository Contract

- `tf2-corp-infra` owns private S3, gateway endpoint and read-only IRSA.
- `tf2-corp-chart` owns artifact download, checksum validation, cache mount and
  offline environment variables.
- Artifact publication and infrastructure apply require CloudOps approval; no
  AWS credential, API key or model binary is committed to Git.

## Validation

- Product-review suite: 34 tests passed on Python 3.12.
- Python compilation passed for the server, guardrails and artifact builder.
- Live S3 download and EKS rollout remain post-apply operator checks.

## Rollback

Roll back the chart first to remove strict external-cache startup requirements,
then roll back this platform change. Do not remove the S3 artifact until the
previous pods are healthy.
