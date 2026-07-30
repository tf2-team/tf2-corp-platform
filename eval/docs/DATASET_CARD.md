# Dataset Card — AI Mandate 14 Gold Evaluation Set

## Overview

Bộ dữ liệu này cung cấp các case có nhãn dùng để so sánh baseline LLM-only với
pipeline integrated của hai bề mặt AI:

- Review Summary
- Shopping Copilot

Mỗi dòng JSONL là một case độc lập, chứa input, snapshot dữ liệu nghiệp vụ cần thiết,
expected behavior/status, các nội dung được phép hoặc bị cấm, cùng metadata review.
Harness có thể chạy dataset này hoặc một JSONL bên ngoài bằng cùng entry point.

## Purpose

Dataset được thiết kế để trả lời ba câu hỏi:

1. Pipeline integrated có hoàn thành tác vụ hợp lệ chính xác hơn baseline không?
2. Câu trả lời có grounded, biết abstain và tránh hallucination không?
3. Guardrail và tool policy có ngăn injection, PII leakage và unauthorized write mà
   không block nhầm request hợp lệ không?

Bộ case không nhằm đại diện toàn bộ traffic production hoặc dùng làm benchmark model
tổng quát. Nó là một bộ nhỏ, có nhãn, có thể audit và tái tạo theo yêu cầu của
Mandate 14.

## Dataset Inventory

| Surface | File | Cases | Production-derived | Synthetic |
|---|---|---:|---:|---:|
| Review Summary | [summary_v0.jsonl](../datasets/gold/summary_v0.jsonl) | 14 | 8 | 6 |
| Shopping Copilot | [copilot_v0.jsonl](../datasets/gold/copilot_v0.jsonl) | 18 | 8 | 10 |
| **Total** |  | **32** | **16** | **16** |

`production-derived` nghĩa là case được tạo từ product/review domain data của
capstone và đóng băng thành fixture. `synthetic` được dùng cho các tình huống an
toàn cần dữ liệu kiểm soát rõ như prompt injection, PII hoặc unauthorized action.

## Coverage — Review Summary

| Case Type | Count | What It Tests |
|---|---:|---|
| `grounded` | 2 | Trả lời dựa trên review/source hợp lệ. |
| `hallucination` | 2 | Không bịa hoặc chọn sai product fact. |
| `unanswerable` | 2 | Abstain khi nguồn không đủ. |
| `pii_in_review` | 2 | Không echo email/số điện thoại từ review. |
| `injection_review` | 2 | Payload độc trong review không điều khiển answer. |
| `injection_user` | 2 | Injection trực tiếp từ question bị block. |
| `false_block_check` | 2 | Câu hợp lệ có từ nhạy cảm không bị block nhầm. |

## Coverage — Shopping Copilot

| Case Type | Count | What It Tests |
|---|---:|---|
| `search` | 2 | Tìm đúng product outcome từ yêu cầu mua sắm. |
| `product_qa` | 2 | Trả lời về sản phẩm từ dữ liệu grounded. |
| `unanswerable` | 2 | Abstain khi không có bằng chứng. |
| `injection_user` | 1 | User injection một lượt bị block. |
| `injection_multiturn` | 1 | Turn lành tính trước không làm guardrail bỏ qua injection sau. |
| `injection_review` | 2 | Review injection không ảnh hưởng answer/tool outcome. |
| `confirmed_write` | 2 | Add-to-cart hợp lệ tạo pending action đúng sản phẩm. |
| `unauthorized_write` | 2 | Write ngoài policy bị block hoặc confirmation-gated. |
| `pii_in_question` | 1 | PII trong request không bị echo hoặc chuyển thành hành động ngoài scope. |
| `pii_in_review` | 1 | PII trong review không đi vào output. |
| `false_block_check` | 1 | Request an toàn không bị block nhầm. |
| `out_of_scope` | 1 | Assistant giữ đúng phạm vi shopping. |

Coverage bao gồm các loại hidden case tối thiểu Mandate 14 công bố:
unanswerable, injection trong review, injection multi-turn, PII trong review,
unauthorized write và một tác vụ grounded hợp lệ.

## Case Structure

Mỗi case gồm bốn phần:

| Section | Meaning |
|---|---|
| `case_id` và `surface` | Định danh ổn định và adapter cần chạy. |
| `input` | User request cùng Catalog/Review/Product fixture cần thiết. |
| `labels` | Expected behavior/status và các claim/action được phép hoặc bị cấm. |
| `metadata` | Nguồn case, review status và reviewer. |

Schema chính thức nằm tại
[eval-case.schema.json](../schemas/eval-case.schema.json). Quy tắc gán nhãn và xử lý
disagreement nằm trong [Annotation Guideline](ANNOTATION_GUIDELINE.md).

## Gold Review Process

Toàn bộ 32 case hiện có:

```text
review_status = gold
reviewers = [khanhlv, hoangnh, minhtq]
```

Reviewer kiểm tra:

1. Input có đủ source để xác định expected behavior không.
2. Expected status có khớp contract của surface không.
3. Supported/forbidden claims có kiểm tra đúng outcome cần đo không.
4. Safety case có payload và forbidden outcome đủ rõ không.
5. Case không vô tình yêu cầu một allowed tool cụ thể khi nhiều execution path đều
   có thể tạo kết quả đúng.

`gold` xác nhận label đã được human review; nó không đồng nghĩa LLM judge đã được
calibrate. Judge calibration là artifact riêng, cần ít nhất 10 human-labeled outputs
và agreement analysis.

## Data and Runtime Boundaries

LLM được gọi thật trong cả baseline và integrated profile. Các dependency dữ liệu
được cô lập như sau:

| Dependency | Evaluation Behavior |
|---|---|
| Catalog | Trả product fixture trong case. |
| Reviews | Trả review fixture trong case. |
| Cart | Fake/in-memory; theo dõi direct write và pending action. |
| Valkey | In-memory conversation state dùng chung giữa các turn trong cùng case. |
| Mem0 | In-memory semantic memory theo `conversation_id`. |

Boundary này nhằm đo hành vi AI một cách tái tạo. Dataset không đo availability,
latency hoặc consistency của các data services thật.

## Source and Privacy

Synthetic PII trong dataset chỉ dùng để kiểm tra leakage, ví dụ email và số điện
thoại giả. Dataset không nên chứa credentials, API key thật hoặc PII của khách hàng.

Source snapshot được chọn từ [Available Source Data](AVAILABLE_SOURCE_DATA.md).
Snapshot nằm trực tiếp trong JSONL để hidden runner không cần truy cập database.

## Known Limitations

1. Bộ 32 case nhỏ nên tỷ lệ có thể thay đổi mạnh khi một case đổi verdict.
2. Nearest-rank p95 trên 14–18 case gần bằng hoặc bằng request chậm nhất.
3. Synthetic safety cases dễ audit nhưng không bao phủ toàn bộ cách diễn đạt của
   attacker thực tế.
4. Một số Summary cases có `mock_product_description` để phản ánh yêu cầu Mandate
   rằng product fact phải dựa trên description. Evaluated Summary path hiện chủ yếu
   nhận review fixture; boundary này cần được chốt trước final closure.
5. Gold labels không thay thế human↔judge calibration cho semantic metrics.
6. Kết quả gold không bảo đảm hidden-set pass; hidden set phải chạy qua cùng harness.

## External and Hidden Datasets

Dataset bên ngoài phải tuân theo cùng JSON Schema nhưng không cần sửa runner. Ví dụ:

```powershell
uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py `
  --profile integrated `
  --dataset <path-to-hidden.jsonl> `
  --output results/hidden/integrated
```

Khi nhận hidden set, team cần giữ nguyên case input/labels, chạy harness và đính kèm
`per_case.jsonl` cùng `aggregate.json` vào Jira. Không chỉnh prompt, labels hoặc
grader theo output của hidden case.

## Ownership

- Dataset design: **Trần Quang Minh**
- Gold-case reviewers: **khanhlv, hoangnh, minhtq**
- Evaluation standard: [AI Mandate #14](../../docs/ai-engineering/eval/MANDATE-14-ai-eval-standard.md)
