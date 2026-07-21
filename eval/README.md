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
