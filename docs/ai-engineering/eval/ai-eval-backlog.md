# AI Evaluation Standard Backlog

> Owner: TechLead & PM. Xem [AI Eval Specification](MANDATE-14-ai-eval-standard.md), [TOOL_ACTION_POLICY](../../../eval/docs/TOOL_ACTION_POLICY.md) và [Implementation Plan](ai-eval-implementation-plan.md).

Tài liệu này định nghĩa backlog ưu tiên và lộ trình triển khai chi tiết cho hệ thống Đánh giá Chất lượng và An toàn AI (Evaluation Pipeline).

Mục tiêu cốt lõi của backlog này là giúp team **hiểu rõ thứ tự các bước cần làm**, bắt đầu từ đâu, mối quan hệ phụ thuộc giữa các công việc (dependencies), và tiêu chuẩn nghiệm thu (Acceptance Criteria) cụ thể cho từng nhiệm vụ.

---

## 1. Executive Summary

Nguyên tắc tối thượng của dự án này không phải là tạo ra một bộ dataset thật lớn ngay lập tức, mà là thiết lập một **khung đo lường đáng tin cậy và có thể tái tạo (reproducible evaluation framework)**.

Thứ tự ưu tiên triển khai được thiết kế theo 4 bước đi chiến lược:
1. **Thiết lập Contract (EV-1.1, EV-1.2)**: Định nghĩa rõ thế nào là đúng/sai và chốt schema dữ liệu.
2. **Xây dựng Gold Seed (EV-1.3)**: Con người tự tay gán nhãn một tập dữ liệu nhỏ làm mốc chuẩn (baseline).
3. **Phát triển Harness & Graders (EV-2.1, EV-2.2, EV-2.3)**: Viết code chạy thử nghiệm và chấm điểm tự động.
4. **Tích hợp & Đo lường (EV-2.4, EV-2.5)**: Chạy baseline, tối ưu hóa hệ thống và chuẩn bị bằng chứng nộp bài.

---

## 2. Current State & Gaps

### Hệ thống hiện tại (Nhánh `aie`)
- Đã có sẵn một script eval cơ bản tại `run_eval.py` và bộ ca thử nghiệm tại `eval_cases.json`.
- Bộ eval hiện tại chỉ kiểm tra được 6 cases Faithfulness và 6 cases Injection đơn giản cho Shopping Copilot.
- Chưa hỗ trợ Review Summary surface. Chưa có cơ chế nạp input từ bên ngoài một cách linh hoạt. Chưa đo lường Cost/Latency và PII Leak.

### Gaps chính cần giải quyết
1. **Chưa có Harness nhận input ngoài**: Script hiện tại đang đọc file JSON cứng, không thể nạp bộ ca ẩn từ ngoài khi chấm điểm.
2. **Chưa cover Review Summary**: Thiếu adapter để test tính năng tóm tắt review (`AskProductAIAssistant` RPC).
3. **Thiếu các bộ chấm điểm (Scorers) tự động**: Chưa có PII scanner, System prompt leak detector, và LLM judge cho faithfulness/task-success.
4. **Chưa đo lường Cost & Latency**: Quy chuẩn yêu cầu so sánh hiệu năng và chi phí trước/sau (before/after).
5. **Chưa có ADR và dữ liệu calibrating**: Thiếu tài liệu giải trình và bảng đánh giá độ khớp giữa AI Judge và Người (Agreement Table).

---

## 3. Priority and Dependency Map

| Rank | Item | Priority | Depends on | Rationale (Lý do ưu tiên) |
|---|---|---|---|---|
| 1 | **EV-1.1** Metric Definitions & Annotation Guidelines | **P0** | None | Phải định nghĩa rõ tiêu chí chấm điểm trước khi tạo dữ liệu. Tránh việc team gán nhãn cảm tính hoặc không đồng nhất. |
| 2 | **EV-1.2** Dataset Schema & Validator | **P0** | None | Thiết lập cấu trúc dữ liệu chuẩn để cả AI Generator, Loader và Runner đều nói chung một ngôn ngữ. |
| 3 | **EV-1.3** Gold Seed Datasets for Both Surfaces | **P0** | EV-1.1, EV-1.2 | Tạo tập test mẫu chuẩn do con người gán nhãn. Bộ dữ liệu này dùng để test harness và làm mốc calibrate LLM Judge. |
| 4 | **EV-2.1** Surface-specific Mock Adapters | **P0** | EV-1.2 | Xây dựng cổng kết nối (Adapter) đến code thật của Summary và Copilot để chạy test offline nhanh, cô lập. |
| 5 | **EV-2.2** Deterministic Graders | **P0** | EV-1.1, EV-2.1 | Cài đặt các bộ chấm điểm bằng code (Regex, Presidio, keyword check) cho các hard bar (PII, System Prompt, Unauthorized Write). |
| 6 | **EV-2.3** Semantic LLM Judges | **P1** | EV-1.1, EV-2.1 | Triển khai LLM Judge kèm prompt rubric để chấm các chỉ số cần hiểu ngữ nghĩa như faithfulness và task success. |
| 7 | **EV-2.4** Eval Runner, Reporter & Baseline Run | **P0** | EV-1.2, EV-2.1, EV-2.2, EV-2.3 | Tích hợp toàn bộ hệ thống thành một lệnh chạy duy nhất, xuất báo cáo per-case + aggregate và so sánh before/after. |
| 8 | **EV-2.5** Compliance ADR & Delivery | **P0** | EV-1.3, EV-2.4 | Hoàn thiện tài liệu kiến trúc (ADR) và đóng gói bằng chứng đầy đủ đúng thời hạn. |

---

## 4. Backlog Details

### EV-1.1 - Metric Definitions & Annotation Guidelines

- **Why**: Cần một nguồn tài liệu thống nhất định nghĩa rõ thế nào là đúng/sai cho 12 chỉ số. Mentor chấm cả *cách team chấm*, do đó quy luật gán nhãn phải tường minh và phản biện được.
- **What**: Soạn thảo `METRIC_DEFINITIONS.md` và `ANNOTATION_GUIDELINE.md`.
- **Acceptance Criteria**:
  - METRIC_DEFINITIONS.md phủ đủ 5 nhóm chỉ số của quy chuẩn. Định nghĩa rõ pass/fail condition và loại scorer cho từng metric.
  - ANNOTATION_GUIDELINE.md có checklist 10 điểm duyệt case, hướng dẫn phân tích disagreement và ví dụ pass/fail rõ ràng.
- **Dependencies**: None.
- **Reuse / Open-source**: Tham khảo các benchmark tiêu chuẩn như RAGAS, OWASP LLM Top 10, và hướng dẫn đánh giá của Anthropic.

---

### EV-1.2 - Dataset Schema & Validator

- **Why**: Tránh việc dữ liệu bị lỗi format làm hỏng luồng chạy thử nghiệm. Runner phải tự động từ chối các file JSONL bị sai cấu trúc trước khi thực thi.
- **What**: Định nghĩa JSON Schema `eval-case.schema.json` và code module `loader.py`.
- **Acceptance Criteria**:
  - Schema validate thành công bằng thư viện `jsonschema`.
  - Hỗ trợ phân biệt trường bắt buộc cho Summary (`product_id`, `question`) và Copilot (`user_message`).
  - Loader đọc file JSONL từ ngoài, validate schema và báo lỗi chi tiết dòng + lý do nếu không hợp lệ.
- **Dependencies**: None.
- **Reuse / Open-source**: Sử dụng thư viện `jsonschema` của Python.

---

### EV-1.3 - Gold Seed Datasets for Both Surfaces

- **Why**: Quy chuẩn yêu cầu phải có một bộ ca kiểm thử có nhãn commit trong repo, bao gồm cả các ca bẫy (adversarial cases) như PII, Injection và Unanswerable.
- **What**: Soạn thảo tập dữ liệu Gold Seed cho Review Summary (10-12 cases) và Shopping Copilot (14-18 cases).
- **Acceptance Criteria**:
  - File dữ liệu được lưu dưới dạng JSONL và đặt tại `eval/datasets/gold/`.
  - Tận dụng và chuẩn hóa 12 cases hiện có trong `eval_cases.json` làm seed ban đầu.
  - Phủ đủ 6 loại hidden case đặc trưng (1 unanswerable, 2 injection, 1 review chứa PII, 1 write trái phép, 1 RAG hợp lệ).
  - Có đầy đủ các cặp đối chứng (VD: injection case ↔ request tương tự nhưng an toàn) để đo `false_block_rate`.
- **Dependencies**: EV-1.1, EV-1.2.
- **Reuse / Open-source**: Dùng dữ liệu sản phẩm và review mẫu từ database thực tế của platform để làm mock content.

---

### EV-2.1 - Surface-specific Mock Adapters

- **Why**: Chạy thử nghiệm trên hệ thống thật kết nối mạng sẽ bị chậm (do API latency) và không ổn định (do rate limit). Cần cơ chế mock dữ liệu đầu vào (reviews, catalog) ở tầng code Python để chạy nhanh và độc lập.
- **What**: Phát triển `summary_adapter.py` và `copilot_adapter.py`.
- **Acceptance Criteria**:
  - Summary adapter mock thành công `fetch_product_reviews` và `fetch_product_info` để trả về dữ liệu mock từ JSONL.
  - Copilot adapter mock thành công catalog stub, reviews stub và Valkey client.
  - Reset trạng thái (cart, memory) sau mỗi case để đảm bảo tính cô lập độc lập giữa các test cases.
  - Trả về output chuẩn hóa chứa: `answer`, `status`, `claims`, `tool_calls`, `latency_ms`, và `usage` (token count).
- **Dependencies**: EV-1.2.
- **Reuse / Open-source**: Tái sử dụng và nâng cấp các pattern mock gRPC stub có sẵn tại `src/shopping-copilot/evals/run_eval.py`.

---

### EV-2.2 - Deterministic Graders

- **Why**: Các chỉ số an toàn nghiêm ngặt (PII leak, System prompt leak, Unauthorized write) phải được kiểm tra bằng code-based rules để đảm bảo độ chính xác tuyệt đối, tốc độ cực nhanh và chi phí bằng 0.
- **What**: Phát triển các module graders tại thư mục `eval/graders/` (cho PII, System Prompt, Abstention, Agency/Write, Cost/Latency).
- **Acceptance Criteria**:
  - `pii.py` sử dụng regex kết hợp Presidio scan trên output text.
  - `system_prompt.py` phát hiện rò rỉ qua keyword canary list.
  - `agency.py` kiểm tra trace tool call để phát hiện nếu `AddItem` gRPC được gọi trái phép (không qua pending token).
  - `cost_latency.py` tính toán đúng p95 latency và chi phí dựa trên token pricing.
  - Mỗi grader có unit test riêng với ít nhất 1 ca pass và 1 ca fail.
- **Dependencies**: EV-1.1, EV-2.1.
- **Reuse / Open-source**: Tận dụng regex patterns và Presidio integration sẵn có trong `guardrails.py`.

---

### EV-2.3 - Semantic LLM Judges

- **Why**: Đánh giá sự trung thực của câu tóm tắt (faithfulness) và độ hoàn thành nhiệm vụ (task success) cần khả năng hiểu ngữ nghĩa, không thể dùng rule hoặc keyword trùng lặp đơn giản.
- **What**: Viết prompt rubric chi tiết và code kết nối LLM Judge (`faithfulness_judge.py`, `task_success_judge.py`).
- **Acceptance Criteria**:
  - Mỗi chỉ số có một prompt rubric riêng biệt, lưu trữ tường minh và có version.
  - Faithfulness judge đánh giá ở claim-level (tách câu trả lời thành từng claim nhỏ và check đối chứng).
  - Trả về output có cấu trúc rõ ràng chứa điểm số và giải thích lý do (reasoning).
- **Dependencies**: EV-1.1, EV-2.1.
- **Reuse / Open-source**: Sử dụng **Instructor + Pydantic** để kiểm soát format đầu ra của LLM Judge.

---

### EV-2.4 - Eval Runner, Reporter & Baseline Run

- **Why**: Quy chuẩn yêu cầu phải có một script duy nhất (`repro` một lệnh) có thể chạy qua bộ ca ẩn, tính toán số liệu per-case, xuất báo cáo tổng hợp và so sánh before/after.
- **What**: Phát triển CLI tool `run_eval.py`, module `reporter.py` và cấu hình Makefile.
- **Acceptance Criteria**:
  - Lệnh `make eval DATASET=path.jsonl` chạy thành công toàn bộ luồng.
  - Báo cáo per-case được ghi ra file JSONL; báo cáo aggregate được định dạng bảng markdown.
  - Chế độ so sánh `--compare` xuất ra bảng so sánh chi tiết biến động (delta) của từng metric trước và sau khi thay đổi hệ thống.
  - Trả exit code = 1 nếu phát hiện bất kỳ vi phạm hard bar nào (PII leak, prompt leak, unauthorized write).
- **Dependencies**: EV-1.2, EV-2.1, EV-2.2, EV-2.3.
- **Reuse / Open-source**: Dùng Python standard libraries cho runner và reporter.

---

### EV-2.5 - Compliance ADR & Delivery

- **Why**: Người chấm điểm sẽ audit cách thức đánh giá của team. Cần một tài liệu giải trình kiến trúc (ADR) có chữ ký đồng thuận và đóng gói bằng chứng đầy đủ để được công nhận hoàn thành.
- **What**: Soạn thảo `ADR-ai-evaluation-standard.md` và chuẩn bị Jira evidence bundle.
- **Acceptance Criteria**:
  - ADR định nghĩa rõ 12 chỉ số, cách hiệu chỉnh judge và giới hạn của kiến trúc không lưu hội thoại. Harness vẫn phải chạy kịch bản nhiều lượt theo chuỗi request để kiểm tra guardrail ở lượt có injection.
  - Bằng chứng chứa đầy đủ: PR/commit link, lệnh repro, gold datasets, bảng agreement judge-người, và so sánh chi phí/độ trễ before/after.
- **Dependencies**: EV-1.3, EV-2.4.
- **Reuse / Open-source**: Tổng hợp số liệu từ kết quả chạy baseline.

---

## 5. Lộ trình triển khai & Phân vai (5 ngày)

```
        │ Ngày 1 (21/07) │ Ngày 2 (22/07) │ Ngày 3 (23/07) │ Ngày 4 (24/07) │ Ngày 5 (25/07) │
────────┼────────────────┼────────────────┼────────────────┼────────────────┼────────────────┤
TL/PM   │ Review EV-1.1  │ Review Gold Set│ Review Graders │ Ký duyệt ADR   │ Review Jira và │
(Bạn)   │ Review EV-1.2  │ (EV-1.3)       │ Review Harness │ Chốt Baseline  │ đóng gói nộp   │
────────┼────────────────┼────────────────┼────────────────┼────────────────┼────────────────┤
Mem A   │ Soạn EV-1.1    │ Soạn Gold Set  │ Viết EV-2.2    │ Viết EV-2.3    │ Tối ưu, chạy   │
        │ (Metrics/Guide)│ (EV-1.3)       │ (Det. Graders) │ (LLM Judge)    │ thử nghiệm và  │
        │                │                │                │ Calibrate      │ fix bug cuối   │
────────┼────────────────┼────────────────┼────────────────┼────────────────┼────────────────┤
Mem B   │ Code EV-1.2    │ Code EV-2.1    │ Code EV-2.1    │ Code EV-2.4    │ Tối ưu, chạy   │
        │ (Schema/Loader)│ (Sum Adapter)  │ (Cop. Adapter) │ (Runner/Rep)   │ thử nghiệm và  │
        │                │                │                │                │ fix bug cuối   │
```
