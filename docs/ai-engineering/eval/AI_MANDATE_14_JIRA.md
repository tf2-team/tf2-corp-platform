# Jira Title

`[AI MANDATE #14] Prove AI Trustworthiness with a Reproducible Evaluation Harness`

# Jira Body

## Executive Summary

Shopping Copilot và Review Summary đều dùng LLM để tạo câu trả lời cho người dùng. Trước khi thực hiện công việc này, team chỉ có các test rời rạc và quan sát thủ công. Cách làm đó chưa cho phép trả lời một câu hỏi quan trọng: pipeline tích hợp có thực sự chính xác và an toàn hơn một LLM thuần hay không.

Team đã xây dựng một evaluation harness chung cho cả hai bề mặt AI. Harness gọi LLM provider thật để đo hành vi của model thật, đồng thời cô lập Catalog, Reviews, Cart, Valkey và Mem0 bằng fixture JSONL. Mỗi lần chạy vì thế dùng cùng dữ liệu đầu vào, không làm thay đổi service local hoặc production, và cho phép người review tái tạo kết quả.

Kết quả hiện tại cho thấy pipeline integrated cải thiện task success, grounding và safety so với baseline LLM-only. Latency tăng trên cả hai bề mặt và chi phí Copilot cao hơn. Các số liệu quality, safety, latency và cost được trình bày trong phần Results.

## Problem and Objective

[AI Mandate #14](MANDATE-14-ai-eval-standard.md) yêu cầu chất lượng AI phải được chứng minh trên bộ case có nhãn, có kết quả cho từng case và có số liệu tổng hợp. Hệ thống cần nhận dataset JSONL bên ngoài, so sánh before và after, đồng thời đo grounding, abstention, safety, task success, cost và latency.

Mục tiêu của implementation là biến yêu cầu này thành một quy trình có thể chạy lại bằng một lệnh. Người review có thể đi từ kết quả tổng hợp xuống từng answer, status, tool trace, usage và verdict của grader.

## Evaluation Design

Để trả lời pipeline bổ sung mang lại giá trị gì, team chạy hai profile trên cùng một gold set.

| Profile | Description |
|---|---|
| `baseline` | LLM và prompt tối thiểu, không guardrail, ReAct tools, Valkey, Mem0 hoặc cart workflow. |
| `integrated` | Pipeline mới nhất tại thời điểm chạy, gồm guardrail, grounded retrieval và tool workflow, cart policy và conversation memory khi áp dụng. |

Cả hai profile đều gọi LLM thật và nhận cùng câu hỏi cùng dữ liệu nghiệp vụ từ snapshot cố định trong từng case. Vì vậy, khi kết quả khác nhau, nguyên nhân là pipeline integrated chứ không phải Catalog hoặc Reviews trả dữ liệu khác.

Task success được chấm theo cơ chế hybrid. LLM judge đánh giá ý nghĩa của câu trả lời, nhưng case vẫn fail nếu status hoặc behavior bắt buộc không đạt. Ví dụ, một câu trả lời cần abstain nhưng có status `GROUNDED` vẫn fail. Tương tự, một thao tác cần tạo pending cart action nhưng không tạo cũng fail. Safety và các hành động ghi được chấm bằng rule deterministic từ output và tool trace.

Chi tiết công thức và mẫu số nằm trong [Metric Definitions](../../../eval/docs/METRIC_DEFINITIONS.md). Cách chạy và cấu trúc output nằm trong [Evaluation README](../../../eval/README.md).

## Dataset and Review Process

Gold set hiện có 32 case, được phân bổ cho hai bề mặt AI để bao phủ cả correctness, safety và workflow.

| Surface | Gold Cases | Main Coverage |
|---|---:|---|
| Review Summary | 14 | Grounded answer, hallucination, unanswerable, PII trong review, injection trong review, user injection và false-block. |
| Shopping Copilot | 18 | Search, product Q&A, unanswerable, user, review và multi-turn injection, PII, cart confirmation, unauthorized write, false-block và out-of-scope. |

Toàn bộ 32 case có `review_status: gold` và đã được review bởi **Lê Văn Khánh**, **Nguyễn Hoàng Huy** và **Trần Quang Minh**. Nguồn dữ liệu, tỷ lệ production-derived và synthetic, cùng giới hạn của bộ case được mô tả trong [Dataset Card](../../../eval/docs/DATASET_CARD.md). Quy tắc gán nhãn chi tiết nằm trong [Annotation Guideline](../../../eval/docs/ANNOTATION_GUIDELINE.md).

## Results

Các bảng dưới đây so sánh baseline và integrated trên cùng gold cases. Nhận xét được đặt ngay sau từng bảng để diễn giải ý nghĩa của số liệu.

### Shopping Copilot

| Metric | Baseline | Integrated | Change |
|---|---:|---:|---:|
| Task success | 50.0% | **88.9%** | +38.9 pp |
| Faithfulness* | 92.9% | **100.0%** | +7.1 pp |
| Hallucination rate* | 7.1% | **0.0%** | -7.1 pp |
| Abstention accuracy | 0.0% | **50.0%** | +50.0 pp |
| Injection handling | 50.0% | **100.0%** | +50.0 pp |
| Valid request not blocked | 100.0% | 100.0% | Không đổi |
| PII safe | 0.0% | **100.0%** | +100.0 pp |
| System-prompt safe | 100.0% | 100.0% | Không đổi |
| Unauthorized-write safe | 100.0% | 100.0% | Không đổi |
| Pending-action accuracy | 0.0% | **100.0%** | +100.0 pp |
| p95 latency | 4.98 s | 12.64 s | +7.66 s |
| Average tokens/request | 415.56 | 2,844.50 | +2,428.94 |
| Average cost/request | $0.000640 | $0.001208 | +$0.000568 |

Shopping Copilot cho thấy mức cải thiện rõ nhất. Task success tăng từ 50.0% lên 88.9%, tương đương 38.9 điểm phần trăm. Faithfulness tăng từ 92.9% lên 100.0%, trong khi hallucination giảm từ 7.1% xuống 0.0%. Các guardrail cũng tạo khác biệt trực tiếp: injection handling tăng từ 50.0% lên 100.0%, PII safe tăng từ 0.0% lên 100.0% và pending-action accuracy tăng từ 0.0% lên 100.0%.

Hai failure còn lại đều có nguyên nhân xác định. Ở yêu cầu không đủ thông tin để trả lời, Copilot trả hướng dẫn chung thay vì abstain. Ở yêu cầu có PII nhưng vẫn hợp lệ cho shopping, pipeline block toàn bộ request thay vì loại bỏ PII rồi tiếp tục search. Về chi phí vận hành, integrated Copilot có p95 latency 12.64 giây so với 4.98 giây ở baseline, dùng trung bình 2,844.50 token mỗi request so với 415.56 token và có average cost/request $0.001208 so với $0.000640.

Kết quả chi tiết: [per-case results](../../../eval/results/integrated/copilot/per_case.jsonl), [aggregate results](../../../eval/results/integrated/copilot/aggregate.json) và [baseline comparison](../../../eval/results/integrated/copilot/comparison.txt).

### Review Summary

| Metric | Baseline | Integrated | Change |
|---|---:|---:|---:|
| Task success | 71.4% | **78.6%** | +7.1 pp |
| Faithfulness* | 93.9% | **100.0%** | +6.1 pp |
| Hallucination rate* | 6.1% | **0.0%** | -6.1 pp |
| Abstention accuracy | 0.0% | **100.0%** | +100.0 pp |
| Injection handling | 50.0% | **100.0%** | +50.0 pp |
| Valid request not blocked | 100.0% | 100.0% | Không đổi |
| PII safe | 50.0% | **100.0%** | +50.0 pp |
| System-prompt safe | 100.0% | 100.0% | Không đổi |
| p95 latency | 4.25 s | 18.80 s | +14.55 s |
| Average tokens/request | 355.93 | 471.36 | +115.43 |
| Average cost/request | $0.000570 | **$0.000288** | -$0.000282 |

Review Summary cải thiện theo hướng an toàn và tiết kiệm chi phí hơn. Task success tăng từ 71.4% lên 78.6%. Faithfulness tăng từ 93.9% lên 100.0%, hallucination giảm từ 6.1% xuống 0.0%, abstention accuracy tăng từ 0.0% lên 100.0%, injection handling tăng từ 50.0% lên 100.0% và PII safe tăng từ 50.0% lên 100.0%. Average cost/request giảm từ $0.000570 xuống $0.000288, dù số token trung bình tăng từ 355.93 lên 471.36.

Ba task-success failures có hai nguyên nhân. Hai câu hỏi có đủ evidence để tạo summary grounded nhưng pipeline lại abstain. Một câu trả lời khác có claim được judge đánh giá là supported, nhưng verdict task success tổng thể vẫn là incorrect. Disagreement này là đầu vào trực tiếp cho human to judge calibration. Integrated Summary có p95 latency 18.80 giây, cao hơn baseline 4.25 giây. Với 14 case, chỉ số này phản ánh request chậm nhất trong lần chạy.

Kết quả chi tiết: [per-case results](../../../eval/results/integrated/summary/per_case.jsonl), [aggregate results](../../../eval/results/integrated/summary/aggregate.json) và [baseline comparison](../../../eval/results/integrated/summary/comparison.txt).

### Interpretation

Hai bề mặt AI đều cải thiện correctness và safety sau khi tích hợp guardrail, retrieval và workflow. Copilot đạt mức tăng task success lớn hơn, nhưng dùng nhiều token và chi phí cao hơn. Summary tăng task success ít hơn, đổi lại giảm được average cost/request. Cả hai đều có latency cao hơn baseline.

Nearest-rank p95 được tính theo `ceil(0.95 × N)`. Với bộ nhỏ từ 14 đến 18 case, p95 phản ánh request chậm nhất.

### Human-label and Judge Calibration

Faithfulness, hallucination và phần semantic của task success được LLM judge hỗ trợ chấm. Team kiểm tra độ tin cậy của judge bằng một calibration set gồm ít nhất 10 output, được chọn từ cả Shopping Copilot và Review Summary. Mẫu calibration bao gồm câu trả lời grounded, abstention, PII, injection và các case có kết quả sát ranh giới.

Reviewer đối chiếu output với evidence của case và gán nhãn theo [Annotation Guideline](../../../eval/docs/ANNOTATION_GUIDELINE.md). Harness so sánh nhãn người với verdict của judge, sau đó báo raw agreement, Cohen's kappa và từng disagreement. Quy trình này giúp tách lỗi của hệ thống khỏi sai lệch của judge trước khi dùng semantic metrics để kết luận chất lượng.

## Safety Hard Bars

Trên gold set hiện tại, integrated pipeline không ghi nhận vi phạm hard bar: PII leakage là 0 case, system-prompt leakage là 0 case và direct unauthorized cart write là 0 case. User injection, review injection và multi-turn injection đều được tính vào injection handling.

Safety grader kiểm tra outcome và hành động bị cấm. Một request không bắt buộc phải gọi một allowed tool cụ thể nếu kết quả cuối đúng, nhưng mọi tool call đều được lưu để audit. Boundary chi tiết của Copilot nằm trong [Tool Action Policy](../../../eval/docs/TOOL_ACTION_POLICY.md).

## ADR: Evaluation Design Decisions

- **Status:** Accepted
- **Design owner:** Trần Quang Minh
- **Decision date:** 2026-07-28
- **Scope:** Review Summary và Shopping Copilot

Các quyết định dưới đây làm rõ cách harness đo và cách diễn giải kết quả.

| Decision | Choice | Rationale | Consequence |
|---|---|---|---|
| Comparison profiles | Baseline LLM-only và integrated mới nhất. | Đo giá trị của toàn bộ pipeline hiện tại thay vì chọn một commit integrated cũ. | Integrated có thể dùng nhiều token và có latency cao hơn. |
| LLM execution | Gọi provider thật cho cả hai profile. | Kết quả phản ánh hành vi model thật. | Run có chi phí, latency và một phần stochasticity thật. |
| Data isolation | Data services dùng fixture in-memory từ JSONL. | Có thể tái tạo và không ghi vào local hoặc production services. | Không đo availability hoặc load của data services. |
| Outcome policy | Chấm kết quả và action bị cấm, không yêu cầu một allowed tool cụ thể. | Nhiều execution path có thể cùng tạo kết quả đúng. | Tool trace vẫn phải được giữ để audit. |
| Task success | LLM semantic verdict kết hợp deterministic status và behavior gate. | Không cho judge pass một answer có status hoặc workflow sai. | Semantic judge vẫn cần human calibration. |
| Injection metric | Bao gồm user, review và multi-turn injection. | Khớp coverage bắt buộc của Mandate 14. | Review injection có thể trả lời bình thường nếu payload độc không ảnh hưởng outcome. |
| Latency | Dùng nearest-rank p95: `ceil(0.95 × N)`. | Công thức đơn giản, minh bạch và tái tạo được. | Với dataset nhỏ, p95 phản ánh request chậm nhất. |
| Cost | Chỉ tính LLM calls thuộc system. Judge usage được ghi riêng. | Phân biệt chi phí vận hành sản phẩm với chi phí đánh giá. | Report hiển thị riêng system usage và judge usage. |
| Reproduction | Một lệnh `--repro` chạy bốn profile và surface, sau đó tạo comparison. | Mentor có thể tạo lại toàn bộ evidence theo cùng quy trình. | Máy chạy cần Python 3.12, `uv` và credentials LLM hợp lệ. |

## Reproduction and Evidence

Từ thư mục repository, chạy:

```powershell
cd eval
uv sync
uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py --repro
```

Lệnh này chạy baseline và integrated cho cả Copilot lẫn Summary, sau đó ghi ba artifact cho mỗi surface. `per_case.jsonl` chứa answer, status, trace, usage và verdict từng case. `aggregate.json` chứa tỷ lệ metric, p95 latency, token và cost. `comparison.txt` ghi before và after theo quality, safety và efficiency.

Harness nhận JSONL bên ngoài qua `--dataset`, vì vậy cùng entry point có thể dùng cho hidden set mà không cần sửa code.

## Evidence Links

- [Evaluation Standard](MANDATE-14-ai-eval-standard.md)
- [Evaluation README](../../../eval/README.md)
- [Metric Definitions](../../../eval/docs/METRIC_DEFINITIONS.md)
- [Dataset Card](../../../eval/docs/DATASET_CARD.md)
- [Annotation Guideline](../../../eval/docs/ANNOTATION_GUIDELINE.md)
- [Tool Action Policy](../../../eval/docs/TOOL_ACTION_POLICY.md)
- [Summary Gold Dataset](../../../eval/datasets/gold/summary_v0.jsonl)
- [Copilot Gold Dataset](../../../eval/datasets/gold/copilot_v0.jsonl)

## Ownership

- Evaluation design and implementation: **Trần Quang Minh**
- Gold-case reviewers: **Lê Văn Khánh**, **Nguyễn Hoàng Huy**, **Trần Quang Minh**
