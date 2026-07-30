# Self-heal CDO Phase 0 Validation

Date: 2026-07-28

Mục đích: ghi lại baseline CDO sử dụng trước khi implement self-heal P0.

## Branch Baseline

- Branch local hiện tại: `cdo/self-heal-p0`
- Upstream branch: `origin/feat/aio/v0.0.6`
- HEAD local hiện tại: `fa855e4be6a1efe93d2998764572f5fff8e026a8`
- HEAD upstream: `fa855e4be6a1efe93d2998764572f5fff8e026a8`

Branch này cố ý được tạo từ branch PR runtime AI `feat/aio/v0.0.6`, không tạo từ `main`.
Không merge PR #109 vào `main` trong phạm vi self-heal work của CDO.

## Required Runtime Files

Các file runtime AI bắt buộc sau đã tồn tại trên baseline này:

- `src/aio/config/actions.json`
- `src/aio/config/incidents_history.json`
- `src/aio/aiops/schemas/domain.py`
- `src/aio/aiops/integrations/live_executor.py`
- `src/aio/aiops/remediation/catalog.py`
- `src/aio/aiops/remediation/history.py`

## Implementation Boundary

CDO có thể tiếp tục implement trên branch này vì runtime schema, action catalog, remediation modules và live executor client đã có sẵn.

Các phase tiếp theo cần giữ các boundary sau:

- Xem PR #109 là dependency cho tới khi PR đó được merge.
- Giữ các action `restart_*` ở dry-run/page/recommendation trong P0.
- Bổ sung `scale_product_catalog` làm golden live action đầu tiên.
- Không mutate Kubernetes live target cho tới khi platform owner approve namespace dev/demo.
- Khi validation, tách rõ lỗi baseline AI runtime và lỗi do phần CDO mới thêm.
