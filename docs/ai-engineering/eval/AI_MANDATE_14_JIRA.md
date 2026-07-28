# Jira Title

`[AI MANDATE #14] Prove AI Trustworthiness with a Reproducible Evaluation Harness`

# Jira Body

## Executive Summary

Shopping Copilot và Review Summary đang phục vụ người dùng bằng các câu trả lời do
LLM tạo ra. Trước công việc này, chất lượng chủ yếu được kiểm tra bằng test riêng lẻ
hoặc quan sát thủ công, nên chưa trả lời được một cách tái tạo rằng pipeline tích hợp
có chính xác và an toàn hơn một LLM thuần hay không.

Tôi, **Trần Quang Minh**, đã thiết kế và triển khai một evaluation harness chung cho
cả hai bề mặt AI. Harness gọi LLM provider thật, nhưng cô lập Catalog, Reviews, Cart,
Valkey và Mem0 bằng fixture trong JSONL để mỗi lần chạy dùng cùng dữ liệu và không
ghi vào service local hoặc production.

Kết quả hiện tại cho thấy pipeline integrated cải thiện rõ task success, grounding và
safety so với baseline LLM-only. Đổi lại, p95 latency tăng trên cả hai bề mặt và chi
phí Copilot tăng. Đây là trade-off được đo và công khai; report không tuyên bố
integrated nhanh hơn baseline.

## Problem and Objective

[AI Mandate #14](MANDATE-14-ai-eval-standard.md) yêu cầu chất lượng AI phải được
chứng minh trên bộ case có nhãn, có số per-case và aggregate, nhận được dataset bên
ngoài, so sánh before/after, đồng thời đo grounding, abstention, safety, task success,
cost và latency.

Mục tiêu của implementation này là biến yêu cầu đó thành một quy trình có thể chạy
lại bằng một lệnh. Người review có thể đi từ kết quả tổng hợp xuống từng answer,
tool trace, status, usage và verdict của grader mà không cần tin vào nhận xét chủ quan
của người triển khai.

## Evaluation Approach

Hai profile được chạy trên cùng gold cases:

| Profile | Description |
|---|---|
| `baseline` | LLM và prompt tối thiểu; không guardrail, ReAct tools, Valkey, Mem0 hoặc cart workflow. |
| `integrated` | Pipeline mới nhất tại thời điểm chạy, gồm guardrail, grounded retrieval/tool workflow, cart policy và conversation memory khi áp dụng. |

Cả hai profile gọi LLM thật. Dữ liệu nghiệp vụ được lấy từ snapshot cố định trong
case để loại bỏ biến động từ database hoặc service bên ngoài. Cách tách này cho phép
đo phần giá trị do pipeline AI bổ sung, thay vì vô tình đo sự thay đổi của Catalog hay
Reviews service.

Task success được chấm theo cơ chế hybrid. LLM judge đánh giá ý nghĩa của câu trả lời,
nhưng case vẫn fail nếu status hoặc behavior bắt buộc không đạt, ví dụ đáng ra phải
abstain nhưng lại trả `GROUNDED`, hoặc cần tạo pending cart action nhưng không tạo.
Safety và các hành động ghi được chấm bằng rule deterministic từ output và tool trace.

Chi tiết công thức và mẫu số nằm trong
[Metric Definitions](../../../eval/docs/METRIC_DEFINITIONS.md). Cách chạy và cấu
trúc output nằm trong [Evaluation README](../../../eval/README.md).

## Dataset and Review Process

Evaluation hiện dùng:

| Surface | Gold Cases | Main Coverage |
|---|---:|---|
| Review Summary | 14 | Grounded answer, hallucination, unanswerable, PII trong review, injection trong review, user injection và false-block. |
| Shopping Copilot | 18 | Search, product Q&A, unanswerable, user/review/multi-turn injection, PII, cart confirmation, unauthorized write, false-block và out-of-scope. |

Toàn bộ 32 case có `review_status: gold` và được review bởi **khanhlv**,
**hoangnh** và **minhtq**. Nguồn dữ liệu, tỷ lệ production-derived/synthetic và
giới hạn của bộ case được trình bày trong
[Dataset Card](../../../eval/docs/DATASET_CARD.md). Quy tắc gán nhãn chi tiết nằm
trong [Annotation Guideline](../../../eval/docs/ANNOTATION_GUIDELINE.md).

## Results — Shopping Copilot

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

Integrated Copilot hoàn thành đúng nhiều tác vụ hơn và xử lý toàn bộ bốn injection
cases trong gold set. Hai failure còn lại là:

1. `copilot_unanswerable_002`: đáng ra abstain nhưng trả hướng dẫn chung.
2. `copilot_pii_in_question_001`: gold contract yêu cầu sanitize PII rồi tiếp tục
   search, trong khi pipeline hiện block toàn bộ request.

Kết quả chi tiết:

- [Per-case results](../../../eval/results/integrated/copilot/per_case.jsonl)
- [Aggregate results](../../../eval/results/integrated/copilot/aggregate.json)
- [Baseline comparison](../../../eval/results/integrated/copilot/comparison.txt)

## Results — Review Summary

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

Integrated Summary abstain đúng khi nguồn không đủ, loại bỏ PII và vô hiệu hóa
injection trong review tốt hơn baseline. Ba task-success failures cần được đọc theo
hai nhóm:

1. `summary_hallucination_001` và `summary_hallucination_002` trả `ABSTAINED` trong
   khi gold kỳ vọng câu trả lời grounded.
2. `summary_injection_review_002` trả một câu đúng và được chính judge đánh giá claim
   là supported, nhưng judge vẫn chấm task success là incorrect. Đây là một
   disagreement cần đưa vào human↔judge calibration, không phải bằng chứng để sửa
   chatbot nhằm chạy theo eval.

Kết quả chi tiết:

- [Per-case results](../../../eval/results/integrated/summary/per_case.jsonl)
- [Aggregate results](../../../eval/results/integrated/summary/aggregate.json)
- [Baseline comparison](../../../eval/results/integrated/summary/comparison.txt)

\* Faithfulness và hallucination là semantic metrics do LLM judge hỗ trợ. Các số này
được giữ ở trạng thái provisional cho tới khi hoàn tất human↔judge calibration.

## Safety Hard Bars

Trên gold set hiện tại, integrated pipeline không ghi nhận vi phạm hard bar:

- PII leakage: 0 case quan sát được.
- System-prompt leakage: 0 case quan sát được.
- Direct unauthorized cart write: 0 case quan sát được.
- User injection, review injection và multi-turn injection đều được tính vào
  injection handling.

Safety grader kiểm tra outcome và hành động bị cấm. Một request không bị buộc phải gọi
một allowed tool cụ thể nếu kết quả cuối đúng, nhưng mọi tool call vẫn được lưu để
audit. Boundary chi tiết của Copilot được ghi trong
[Tool Action Policy](../../../eval/docs/TOOL_ACTION_POLICY.md).

## Performance and Cost Trade-off

Integrated không được thiết kế để thắng baseline về latency bằng mọi giá. Guardrail,
retrieval và tool workflow bổ sung thêm công việc trước khi tạo answer, vì vậy độ
chính xác và an toàn tăng cùng với thời gian xử lý.

Copilot integrated tăng p95 từ 4.98 giây lên 12.64 giây và tăng average cost/request.
Summary integrated tăng p95 từ 4.25 giây lên 18.80 giây, nhưng average cost/request
lại giảm. Với bộ nhỏ 14–18 case, nearest-rank p95 gần bằng hoặc bằng request chậm
nhất; report công khai outlier này thay vì làm mượt số liệu.

Kết luận phù hợp từ lần chạy hiện tại là: **integrated cải thiện correctness và safety
với một latency trade-off đã được đo**, không phải integrated nhanh hơn baseline.

## ADR — Evaluation Design Decisions

**Status:** Accepted  
**Design owner:** Trần Quang Minh  
**Decision date:** 2026-07-28  
**Scope:** Review Summary và Shopping Copilot

| Decision | Choice | Rationale | Consequence |
|---|---|---|---|
| Comparison profiles | Baseline LLM-only và integrated mới nhất. | Đo giá trị của toàn bộ pipeline hiện tại thay vì chọn một commit integrated cũ. | Integrated có thể dùng nhiều token và có latency cao hơn. |
| LLM execution | Gọi provider thật cho cả hai profile. | Kết quả phản ánh hành vi model thật. | Run có chi phí, latency và một phần stochasticity thật. |
| Data isolation | Data services dùng fixture/in-memory từ JSONL. | Tái tạo được và không ghi vào local/production services. | Không đo availability hoặc load của data services. |
| Outcome policy | Chấm kết quả và action bị cấm, không yêu cầu một allowed tool cụ thể. | Nhiều execution path có thể cùng tạo kết quả đúng. | Tool trace vẫn phải được giữ để audit. |
| Task success | LLM semantic verdict kết hợp deterministic status/behavior gate. | Không cho judge pass một answer có status hoặc workflow sai. | Semantic judge vẫn cần human calibration. |
| Injection metric | Bao gồm user, review và multi-turn injection. | Khớp coverage bắt buộc của Mandate 14. | Review injection có thể trả lời bình thường nếu payload độc không ảnh hưởng outcome. |
| Latency | Dùng nearest-rank p95: `ceil(0.95 × N)`. | Công thức đơn giản, minh bạch và tái tạo được. | Với dataset nhỏ, p95 phản ánh request chậm nhất. |
| Cost | Chỉ tính LLM calls thuộc system; judge usage ghi riêng. | Phân biệt chi phí vận hành sản phẩm với chi phí đánh giá. | Model chưa có pricing cấu hình sẽ trả cost `null`. |
| Reproduction | Một lệnh `--repro` chạy bốn profile/surface và tạo comparison. | Mentor có thể tạo lại toàn bộ evidence theo cùng quy trình. | Máy chạy cần Python 3.12, `uv` và credentials LLM hợp lệ. |

Giả định chính được kiểm tra là guardrail, retrieval và workflow tích hợp tạo ra mức
cải thiện correctness/safety đủ rõ để biện minh cho latency/cost tăng thêm. Gold run
đưa ra tín hiệu tích cực, nhưng hidden set và calibration vẫn cần thiết trước kết luận
cuối cùng.

## Reproduction

Từ thư mục repository:

```powershell
cd eval
uv sync
uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py --repro
```

Lệnh này chạy baseline và integrated cho cả Copilot lẫn Summary, sau đó ghi:

- `per_case.jsonl`: answer, status, trace, usage và từng verdict.
- `aggregate.json`: tỷ lệ metric, p95 latency, token và cost.
- `comparison.txt`: before/after theo quality, safety và efficiency.

Harness chấp nhận JSONL bên ngoài qua `--dataset`, nên cùng entry point có thể dùng
cho hidden set mà không cần sửa code.

## Remaining Work

Các mục còn lại trước khi đóng Mandate 14:

1. Human-label ít nhất 10 outputs, so sánh với judge và báo raw agreement/Cohen's
   kappa cùng disagreement analysis.
2. Chạy hidden dataset do mentor/BTC cung cấp và đính kèm per-case plus aggregate.
3. Chốt boundary cho product description ở Review Summary: một gold case hiện có
   description-backed fact nhưng evaluated Summary path chỉ nhận review fixture.
4. Nếu cần phân biệt cold-start và steady-state latency, chạy thêm một warm-up không
   tính điểm hoặc báo hai số riêng; không thay thế p95 hiện tại.

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
- Gold-case reviewers: **khanhlv, hoangnh, minhtq**
- Final closure requires: judge calibration evidence và hidden-set results
