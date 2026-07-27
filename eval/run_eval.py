"""Run a labeled dataset through the real configured LLM pipelines."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_EVAL = Path(__file__).parent
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

from adapters.copilot_adapter import run_copilot_case
from adapters.summary_adapter import run_summary_case
from graders.agency import grade_agency
from graders.deterministic import (
    grade_abstention, grade_false_block, grade_grounding_numbers,
    grade_latency, grade_multiturn_injection, grade_safety,
    grade_single_turn_injection, grade_status, record_cost, record_usage,
)
from harness.loader import load_dataset


def score_case(case: dict, output: dict) -> list[dict]:
    """Apply every deterministic check appropriate to one adapter output."""
    scores = [
        grade_status(case, output), grade_abstention(case, output),
        grade_false_block(case, output), grade_single_turn_injection(case, output),
        grade_multiturn_injection(case, output), grade_grounding_numbers(case, output),
        *grade_safety(case, output), grade_latency(output), record_usage(output), record_cost(output),
    ]
    if case["surface"] == "copilot":
        scores.append(grade_agency(case, output))
    return scores


def run_cases(cases: list[dict], copilot_runner=run_copilot_case, summary_runner=run_summary_case) -> list[dict]:
    results = []
    for case in cases:
        try:
            output = copilot_runner(case) if case["surface"] == "copilot" else summary_runner(case)
            scores = score_case(case, output)
        except Exception as exc:
            output = {"status": "FALLBACK", "answer": "", "tool_calls": []}
            scores = [{"metric": "execution", "value": False, "passed": False, "detail": type(exc).__name__}]
        results.append({"case_id": case["case_id"], "surface": case["surface"], "output": output, "scores": scores})
    return results


def write_report(results: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "per_case.jsonl").open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result) + "\n")
    scores = [score for result in results for score in result["scores"]]
    aggregate = {
        "cases": len(results),
        "checks": len(scores),
        "passed_checks": sum(score["passed"] for score in scores),
        "failed_checks": sum(not score["passed"] for score in scores),
    }
    (output_dir / "aggregate.json").write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mandate 14 eval with the configured real LLM provider.")
    parser.add_argument("--dataset", required=True, help="Gold or externally supplied JSONL dataset")
    parser.add_argument("--output", required=True, help="Directory for per_case.jsonl and aggregate.json")
    parser.add_argument("--surface", choices=["summary", "copilot"], help="Optional surface filter")
    args = parser.parse_args()
    results = run_cases(load_dataset(args.dataset, args.surface))
    write_report(results, Path(args.output))
    print(f"Evaluated {len(results)} case(s); results written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
