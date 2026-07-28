#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_eval
from run_eval import _percentile, _usage_totals, compare_reports, run_cases, score_case, write_report


class EvalRunnerTests(unittest.TestCase):
    def test_prices_nova_2_lite_usage(self):
        usage = _usage_totals([{
            "provider": "bedrock",
            "model": "us.amazon.nova-2-lite-v1:0",
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "total_tokens": 2_000_000,
        }])
        self.assertAlmostEqual(usage["cost_usd"], 3.08)

    def test_runs_and_scores_without_calling_real_llm(self):
        case = {
            "case_id": "copilot_search_001", "surface": "copilot",
            "input": {"user_message": "Find a telescope"},
            "labels": {"case_type": "search", "expected_behavior": "search_results", "expected_status": "GROUNDED"},
        }
        output = {"status": "GROUNDED", "answer": "", "tool_calls": [], "cart_add_item_called": False, "latency_ms": 1, "usage": {}}
        result = run_cases([case], copilot_runner=lambda _: output)

        self.assertEqual(result[0]["case_id"], "copilot_search_001")
        self.assertTrue(result[0]["scores"][0]["passed"])

    def test_task_success_fails_when_required_status_fails(self):
        case = {
            "surface": "summary", "input": {},
            "labels": {"case_type": "grounded", "expected_status": "GROUNDED"},
        }
        scores = score_case(case, {"status": "ABSTAINED", "answer": "", "tool_calls": []}, {"claims": [], "task_success": "correct"})
        task_success = next(score for score in scores if score["metric"] == "task_success")
        self.assertFalse(task_success["passed"])

    def test_judge_error_preserves_system_output(self):
        case = {
            "case_id": "summary", "surface": "summary", "input": {"question": "Q"},
            "labels": {"case_type": "grounded", "expected_status": "GROUNDED"},
        }
        output = {"status": "GROUNDED", "answer": "A", "tool_calls": [], "latency_ms": 1}
        results = run_cases([case], summary_runner=lambda _: output, judge=lambda *_: (_ for _ in ()).throw(RuntimeError("judge down")))
        self.assertEqual(results[0]["output"]["status"], "GROUNDED")
        self.assertEqual(results[0]["output"]["judge_error"], "RuntimeError: judge down")
        self.assertFalse(any(score["metric"] == "execution" for score in results[0]["scores"]))

    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(_percentile(list(range(1, 15)), 0.95), 14)

    def test_repro_allows_baseline_hard_bar_but_not_integrated(self):
        with patch.object(run_eval.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, patch.object(run_eval, "compare_reports"):
            self.assertEqual(run_eval.reproduce_all(), 0)
        baseline_calls = [call.args[0] for call in run.call_args_list if "--profile" in call.args[0] and call.args[0][call.args[0].index("--profile") + 1] == "baseline"]
        self.assertTrue(all("--allow-hard-bar-fail" in command for command in baseline_calls))

    def test_report_keeps_only_per_case_and_aggregate(self):
        results = [{
            "case_id": "case", "surface": "copilot", "output": {"latency_ms": 12, "system_usage": None},
            "scores": [{"metric": "status", "value": True, "passed": True, "detail": "ok"}], "judgement": None,
        }]
        with tempfile.TemporaryDirectory() as directory:
            aggregate = write_report(results, Path(directory), "integrated")
            self.assertEqual(aggregate["profile"], "integrated")
            self.assertEqual(set(path.name for path in Path(directory).iterdir()), {"per_case.jsonl", "aggregate.json"})
            self.assertEqual(json.loads((Path(directory) / "aggregate.json").read_text())["cases"], 1)

    def test_compare_includes_quality_safety_and_efficiency(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("baseline", "integrated")]
            for path, task_success, injection in zip(paths, (0.5, 1.0), (0.0, 1.0)):
                path.mkdir()
                (path / "aggregate.json").write_text(json.dumps({
                    "profile": path.name,
                    "metrics": {
                        "task_success": {"pass_rate": task_success},
                        "injection_handling": {"pass_rate": injection},
                    },
                    "p95_latency_ms": 10,
                    "system_tokens": 20,
                    "system_cost_usd": 0.01,
                }))
            output = io.StringIO()
            with redirect_stdout(output):
                compare_reports([str(path) for path in paths])
            self.assertIn("Quality", output.getvalue())
            self.assertIn("Safety", output.getvalue())
            self.assertIn("Efficiency", output.getvalue())
            comparison = paths[1] / "comparison.txt"
            self.assertTrue(comparison.exists())
            self.assertIn("task_success", comparison.read_text())
