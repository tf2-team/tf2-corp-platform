# AI Eval Pipeline — Mandate #14

Reproducible evaluation pipeline for the AI tier's quality and safety across both surfaces:
**Review Summary** and **Shopping Copilot**.

## Quick Start

```bash
# Validate a gold dataset (copilot)
make eval DATASET=eval/datasets/gold/copilot_v0.jsonl

# Validate a gold dataset (summary)
make eval DATASET=eval/datasets/gold/summary_v0.jsonl

# Validate an external dataset (BTC hidden set)
make eval DATASET=/path/to/hidden.jsonl

# Install the loader dependency and run its integration tests
python -m pip install -r eval/requirements.txt
cd eval && python -m unittest harness.test_loader

# Full evaluation and before/after comparison will be available after EV-2.4
python -m eval.run_eval --dataset eval/datasets/gold/copilot_v0.jsonl --output results/candidate --compare results/baseline results/candidate
```

## Bắt đầu từ đâu?

Trước khi viết hoặc chạy một gold case, đọc các tài liệu theo thứ tự sau. Mỗi file trả lời một câu hỏi khác nhau, nên không nên bỏ qua bước nào.

1. [Tool Action Policy](docs/TOOL_ACTION_POLICY.md): bot được phép gọi công cụ nào và hành động nào phải bị chặn hoặc yêu cầu xác nhận.
2. [Metric Definitions](docs/METRIC_DEFINITIONS.md): case sẽ được chấm theo những chỉ số nào và thế nào là đạt hoặc không đạt.
3. [Annotation Guideline](docs/ANNOTATION_GUIDELINE.md): cách viết case, gán nhãn và review chéo.
4. [Available Source Data](docs/AVAILABLE_SOURCE_DATA.md): chọn product information và review có sẵn trong capstone làm source cho case grounded, unanswerable hoặc hallucination.
5. [Eval case schema](schemas/eval-case.schema.json): format bắt buộc của từng dòng JSONL. Schema giúp ngăn dataset thiếu field hoặc dùng sai enum.
6. [Dataset loader](harness/loader.py): đọc JSONL và báo lỗi theo dòng. Chạy loader trước khi gửi case sang review để reviewer chỉ cần tập trung vào chất lượng nhãn.

Catalog dữ liệu nguồn chỉ dùng để tham khảo. Gold dataset phải chứa snapshot nhỏ được chọn lọc, có labels và metadata riêng.

## Structure

```
eval/
├── docs/           # Evaluation contract, metric definitions, guidelines
├── schemas/        # JSON Schema for eval cases
├── datasets/       # Gold, silver, calibration datasets
├── adapters/       # Surface-specific adapters (summary, copilot)
├── graders/        # Deterministic + LLM-based scorers
├── harness/        # Loader, runner, reporter
└── results/        # Baseline and comparison reports
```

## Mandate Reference

See [MANDATE-14-ai-eval-standard.md](../docs/ai-engineering/eval/MANDATE-14-ai-eval-standard.md)
