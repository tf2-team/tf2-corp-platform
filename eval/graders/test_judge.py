#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest

import json

from graders.judge import JudgeOutput, _prompt, grade_judgement


class JudgeGraderTests(unittest.TestCase):
    def test_claim_metrics_distinguish_contradiction_and_missing_evidence(self):
        scores = grade_judgement({
            "claims": [
                {"text": "Supported", "claim_type": "product_fact", "verdict": "SUPPORTED"},
                {"text": "Wrong", "claim_type": "product_fact", "verdict": "CONTRADICTED"},
                {"text": "Unknown", "claim_type": "opinion", "verdict": "NOT_ENOUGH_INFORMATION"},
            ],
            "task_success": "partial",
        })
        self.assertEqual(scores[0]["value"], 1 / 3)
        self.assertEqual(scores[1]["value"], 2 / 3)
        self.assertFalse(scores[2]["passed"])

    def test_accepts_provider_variant_field_names(self):
        scores = grade_judgement(JudgeOutput.model_validate({
            "extracted_claims": [],
            "task_fulfilment": "correct",
        }).model_dump())
        self.assertEqual(scores[-1]["value"], "correct")

    def test_task_success_requires_deterministic_behavior(self):
        scores = grade_judgement({"claims": [], "task_success": "correct"}, deterministic_behavior_ok=False)
        self.assertFalse(scores[-1]["passed"])

    def test_prompt_includes_runtime_evidence(self):
        case = {
            "input": {"user_message": "Find binoculars", "mock_catalog_products": [{"name": "Roof Binoculars"}]},
            "labels": {"expected_behavior": "search_results", "expected_status": "GROUNDED"},
        }
        payload = json.loads(_prompt(case, {
            "answer": "Found one.", "status": "GROUNDED",
            "products": [{"name": "Roof Binoculars"}],
            "tool_calls": [{"name": "search_catalog"}], "pending_action": None,
        }))
        self.assertEqual(payload["CATALOG_PRODUCTS"][0]["name"], "Roof Binoculars")
        self.assertEqual(payload["RETURNED_PRODUCTS"][0]["name"], "Roof Binoculars")
        self.assertEqual(payload["TOOL_CALLS"][0]["name"], "search_catalog")
