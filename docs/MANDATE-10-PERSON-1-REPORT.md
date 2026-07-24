# Báo cáo Mandate 10 — Người 1: CI Pipeline & Security Gates

## Thông tin thay đổi

- Repository: `tf2-team/tf2-corp-platform`
- Branch cá nhân: `hoangvu186`
- Branch tích hợp: `feat/mandate-10-secure-delivery`
- Commit triển khai: `2d13b90` (`feat(ci):mandate-10-security-gates`)
- Pull request: [#37](https://github.com/tf2-team/tf2-corp-platform/pull/37)

## Kết quả thực hiện

### 1. Cổng kiểm tra bảo mật bắt buộc

Pipeline CI/CD đã tích hợp các cổng kiểm tra trước khi image được ký và phát hành:

- Semgrep SAST.
- TruffleHog secret scan.
- Trivy image CVE scan.
- Trivy IaC misconfiguration scan.
- Trivy chặn pipeline khi phát hiện lỗi mức `HIGH` hoặc `CRITICAL`.
- Job ký và attest image phụ thuộc vào kết quả thành công của toàn bộ security gates.

Workflow liên quan:

- `.github/workflows/ci.yml`
- `.github/workflows/build-and-push.yml`

Kết quả CI của commit `2d13b90`: `success`.

**Evidence:**

- [Gắn ảnh/link PR có required checks tại đây]
- [Gắn ảnh/link PR cố tình đỏ và bị chặn merge tại đây]

### 2. Chữ ký, SBOM và provenance

Sau khi các cổng kiểm tra thành công, pipeline thực hiện:

- Ký image bằng Cosign với khóa KMS.
- Sinh SBOM định dạng CycloneDX bằng Syft.
- Ký SBOM bằng `cosign attest` với loại `cyclonedx`.
- Tạo và ký provenance chứa:
  - commit SHA;
  - số PR;
  - người duyệt PR;
  - khóa/người ký;
  - kết quả Trivy image, Trivy IaC, Semgrep và TruffleHog;
  - URL của workflow run.

**Evidence:**

- [Gắn link workflow run có job `Sign and attest` thành công tại đây]
- [Gắn ảnh các bước ký image, attest SBOM và attest provenance tại đây]

### 3. Không sử dụng dependency trôi

- GitHub Actions được pin bằng commit SHA.
- External base images trong các file `Dockerfile*` được pin bằng `@sha256:<digest>`.
- CI chạy `scripts/check_pinned_base_images.py` để chặn base image chưa pin digest.
- Tham chiếu build stage nội bộ như `FROM base AS builder` không phải external image và không yêu cầu digest.

Lệnh kiểm tra:

```powershell
python scripts/check_pinned_base_images.py
```

Kết quả:

```text
All external Dockerfile base images are pinned by sha256 digest.
```

**Evidence:**

- [Gắn ảnh kết quả checker tại đây]
- [Gắn ảnh GitHub Action pin commit SHA tại đây]

### 4. Giới hạn phạm vi build và deploy

- Pipeline xác định các service bị ảnh hưởng từ danh sách file thay đổi.
- Chỉ service thay đổi được build; service không thay đổi được bỏ qua.
- Digest chỉ được ghi vào file `values-<service>.yaml` tương ứng.
- Có xử lý riêng cho `mem0`, `load-generator` và sidecar `flagd-ui`.
- Full rebuild không phải hành vi mặc định.
- Khi chạy thủ công với `force_full_rebuild`, người chạy bắt buộc cung cấp `full_rebuild_reason`.

**Evidence:**

- [Gắn ảnh Draft PR chỉ build service thay đổi tại đây]
- [Gắn ảnh các service không thay đổi bị skip tại đây]
- [Gắn ảnh form `workflow_dispatch` có `full_rebuild_reason` tại đây]


