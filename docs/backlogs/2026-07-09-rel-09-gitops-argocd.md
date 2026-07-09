# Backlog: REL-09 - Promote image tag sang GitOps (Platform / CI level)

## Bối cảnh

Repo `techx-corp-platform` build & push multi-service images lên ECR. Deploy thuộc chart + Argo CD (REL-09). Chart dùng **một** `default.image.tag` cho mọi service nested — CI phải tôn trọng contract này khi promote.

- Kế hoạch tổng: [`docs/gitops-argocd.md`](../../../docs/gitops-argocd.md)
- CICD hiện tại: [`docs/CICD.md`](../CICD.md)
- Chart runbook: `techx-corp-chart/docs/operations/gitops-argocd.md`

## Vấn đề

1. CI **không deploy** — sau bake không cập nhật chart values.
2. Nếu sau này chỉ build changed services nhưng vẫn bump global tag → service không build bị ImagePullBackOff.
3. Mở PR `values-prod.yaml` song song push image dở → Argo sync sớm fail.

## Giải pháp đề xuất (platform)

1. **Contract (bắt buộc ngay trong docs / process)**  
   - Mỗi promotion: bake **toàn bộ** catalog service với cùng `IMAGE_VERSION` / tag.  
   - Hoặc (tương lai) per-service tags trong chart — **không** v1.  

2. **Flow promote**

```text
Build ALL services → Push ECR → Verify every required tag exists
  → Smoke/security checks (nếu có)
  → Open PR on techx-corp-chart (values-dev.yaml | values-prod.yaml)
  → Review / merge
  → Argo CD sync
```

3. **Phase 6 (automation)**  
   - Job sau `build-and-push` thành công:  
     - `aws ecr describe-images` cho list service catalog  
     - Mở PR chart (bot) cập nhật `default.image.tag`  
   - Prod PR: required review; dev có thể auto-merge tùy policy  

4. **Không** gọi Helm/kubectl deploy từ platform workflow v1.

## Acceptance Criteria

- [ ] `docs/CICD.md` mô tả clear contract rebuild-all + verify-before-PR.
- [ ] (Phase 6) Workflow/job verify ECR tags trước khi tạo PR chart.
- [ ] Không path-filtered partial bake khi vẫn dùng global tag cho promotion.
- [ ] Tài liệu: không mở values PR khi push chưa xong.

## Kiểm thử / xác minh

```sh
# Sau bake tag=sha-XXXXXXX — mọi repo nested phải có tag
aws ecr describe-images --repository-name techx-corp/ad \
  --image-ids imageTag=sha-XXXXXXX --region us-east-1
# lặp cho full catalog trước khi merge chart PR
```

## Rủi ro & rollback

| Rủi ro | Giảm thiểu |
|--------|------------|
| Partial bake + global tag | Rebuild-all policy; fail job nếu thiếu tag |
| PR quá sớm | Gate verify ECR trong job |
| Sai env file (dev vs prod) | Map branch/env → values-dev vs values-prod |

**Rollback deploy:** thuộc chart/GitOps (`git revert` values), không rollback image ECR (immutable tag).

---

## English Summary

Platform-level REL-09: enforce full multi-service bake + ECR verification before any chart values PR that advances the global image tag; optional Phase 6 automation to open the chart PR after successful push.
