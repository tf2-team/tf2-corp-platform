# Change: Correct Mem0 FastEmbed S3 URI documentation

## Summary

`docs/CICD.md` previously suggested `s3://<bucket>/mem0/fastembed` for `MEM0_FASTEMBED_ARTIFACT_S3_URI`. That path is outside the IRSA-allowed prefix and chart `s3Prefix`. The docs now require the chart/IRSA-aligned prefix so CI publish and `fetch-mem0-fastembed` use the same key layout.

## Context

Production Mem0 init failed with `403 HeadObject` while the composed URI targeted `fastembed/paraphrase-multilingual-MiniLM-L12-v2/<tag>/…`. The AI models bucket had no objects under that prefix; a wrong CI base URI would keep publishing into a path the Mem0 SA cannot read.

## Before

* Example URI: `s3://<bucket>/mem0/fastembed`

## After

* Documented production-shaped URI matching chart `mem0.modelDelivery.s3Prefix` and infra `model_prefix`.
* Explained `${URI}/${VERSION}/` vs chart `${s3Prefix}/${imageTag}/${archiveName}` layout.

## Technical Design Decisions

* Docs-only in platform; IAM publish grant is in `techx-corp-infra` bootstrap (related change).

## Implementation Details

1. Updated `docs/CICD.md` FastEmbed environment variable section.

## Files Changed

* `docs/CICD.md` — Correct `MEM0_FASTEMBED_ARTIFACT_S3_URI` contract.
* `docs/changes/2026-07-19-mem0-fastembed-s3-uri-docs.md` — This change record.

## Dependencies and Cross-Repository Impact

* Related: `techx-corp-infra/docs/changes/2026-07-19-gha-mem0-fastembed-s3-publish.md`
* Chart values-prod already uses the correct `s3Prefix`.

## Impact Analysis

| Dimension | Impact |
|---|---|
| **Application behavior** | None until operators set the var and publish artifacts |
| **Documentation** | Prevents mis-wired S3 prefixes |

## Validation

* Cross-checked chart `values-prod.yaml` s3Prefix, IRSA `model_prefix`, and live empty S3 prefix.

## Migration or Deployment Notes

Set on GitHub Environment `production`:

```text
MEM0_FASTEMBED_ARTIFACT_S3_URI=s3://techx-prod-tf2-ai-models-493499579600/fastembed/paraphrase-multilingual-MiniLM-L12-v2
```

Then rebuild Mem0 (or force FastEmbed publish) so objects exist under the current image tag.

## Risks and Rollback

None operational for docs-only; revert the markdown if needed.

<!-- Change trail: @hungxqt - 2026-07-19 - Align FastEmbed S3 URI docs with IRSA prefix. -->
