# AI Eval Pipeline — Mandate 14

Harness này đánh giá hai AI surface của platform bằng LLM provider thật:

- **Review Summary**
- **Shopping Copilot**

Catalog, reviews, cart, Valkey và Mem0 trong mỗi case là dữ liệu/double xác định
từ JSONL. Vì vậy eval không cần Docker, nhưng vẫn gọi LLM thật theo cấu hình local.

## Hai profile

Mỗi dataset được chạy với cùng model, cùng input và cùng source data ở hai profile:

| Profile | Có gì |
|---|---|
| `baseline` | Chỉ LLM và prompt; không guardrail, ReAct tools, Valkey, Mem0 hoặc cart workflow. |
| `integrated` | Pipeline mới nhất của platform, gồm guardrail, ReAct/tool policy và conversation memory. |

Mỗi lần chạy chỉ ghi hai file vào thư mục output:

```text
per_case.jsonl   # answer, trace, verdict claim-level và usage từng case
aggregate.json   # metric rates, p95 latency, token và cost nếu có pricing
```

`--compare` đọc hai `aggregate.json`, in chênh lệch ra terminal và ghi
`comparison.txt` vào thư mục integrated được truyền ở đối số thứ hai.

## Chuẩn bị

Chạy mọi lệnh bên dưới từ thư mục `eval`.

```powershell
cd eval
uv sync
```

Eval đọc cấu hình từ `../.env` và `../.env.override`. Không commit `.env.override`,
AWS credentials hay API key.

Ví dụ tối thiểu cho Bedrock trong `.env.override`:

```env
LLM_PROVIDER=bedrock
AWS_PROFILE=bedrock-dev
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0
BEDROCK_MAX_TOKENS=1024
```

Kiểm tra profile trước khi chạy:

```powershell
aws sts get-caller-identity --profile bedrock-dev
```

## Chạy eval

Chạy toàn bộ baseline/integrated cho cả Copilot và Summary, rồi tạo hai file
comparison bằng một lệnh:

```powershell
uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py --repro
```

Kết quả được tách theo profile và surface:

```text
results/
├── baseline/
│   ├── copilot/
│   └── summary/
└── integrated/
    ├── copilot/
    └── summary/
```

Chạy Shopping Copilot:

```powershell
uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py `
  --profile baseline `
  --dataset datasets/gold/copilot_v0.jsonl `
  --output results/baseline/copilot

uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py `
  --profile integrated `
  --dataset datasets/gold/copilot_v0.jsonl `
  --output results/integrated/copilot
```

Chạy Review Summary:

```powershell
uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py `
  --profile baseline `
  --dataset datasets/gold/summary_v0.jsonl `
  --output results/baseline/summary

uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py `
  --profile integrated `
  --dataset datasets/gold/summary_v0.jsonl `
  --output results/integrated/summary
```

Runner hiển thị progress bar theo số case và status của case vừa hoàn tất.

So sánh từng surface:

```powershell
uv run -- python run_eval.py --compare results/baseline/copilot results/integrated/copilot
uv run -- python run_eval.py --compare results/baseline/summary results/integrated/summary
```

`--compare` in cùng lúc:

- **Quality**: task success, faithfulness, hallucination, abstention, grounded
  numbers và status match.
- **Safety**: injection, false block, PII, system prompt, unauthorized write,
  pending action và forbidden output.
- **Efficiency**: p95 latency, token/cost trung bình mỗi request và tổng token/cost.

Quality/safety dùng delta theo điểm phần trăm; Mandate không đặt ngưỡng cứng nên
runner chỉ trình bày trade-off, không tự tuyên bố profile nào thắng chung cuộc.

Khi mentor cung cấp JSONL hidden, truyền đường dẫn đó vào `--dataset` và chọn một
output directory riêng.

LLM judge chạy mặc định để chấm faithfulness, hallucination và task success theo
claim. Chỉ dùng `--no-judge` khi debug harness không muốn phát sinh judge call:

```powershell
uv run --env-file ../.env --env-file ../.env.override -- python run_eval.py `
  --profile integrated `
  --dataset datasets/examples/copilot_multiturn_injection.jsonl `
  --output results/debug `
  --no-judge
```

## Đọc kết quả

- `per_case.jsonl` có output của pipeline, tool trace, `system_usage` và
  `judge_usage`. `judge_usage` không được cộng vào latency/cost của hệ thống.
- `aggregate.json` tổng hợp tỷ lệ metric, p95 latency và tổng token.
- Với `us.amazon.nova-2-lite-v1:0` tại `us-east-1`, runner tính cost theo AWS Price
  List được kiểm tra ngày 2026-07-28: `$0.33/1M` input tokens và `$2.75/1M` output
  tokens. Report ghi kèm model, region, ngày và nguồn pricing.
- Model khác vẫn trả cost `null` để tránh ước tính sai.
- Exit code chỉ là `1` khi hard bar bị vi phạm: PII leak, system-prompt leak hoặc
  unauthorized write.

## Chạy unit tests

Unit tests không gọi LLM thật:

```powershell
uv run -- python -m unittest discover -s . -p "test_*.py"
```

## Tài liệu liên quan

1. [Tool Action Policy](docs/TOOL_ACTION_POLICY.md)
2. [Metric Definitions](docs/METRIC_DEFINITIONS.md)
3. [Annotation Guideline](docs/ANNOTATION_GUIDELINE.md)
4. [Dataset Card](docs/DATASET_CARD.md)
5. [Eval case schema](schemas/eval-case.schema.json)
6. [Mandate 14](../docs/ai-engineering/eval/MANDATE-14-ai-eval-standard.md)
