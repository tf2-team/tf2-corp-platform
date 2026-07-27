import unittest

from run_eval import run_cases


class EvalRunnerTests(unittest.TestCase):
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
