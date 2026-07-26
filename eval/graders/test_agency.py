#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest

from graders.agency import grade_agency


class AgencyGraderTests(unittest.TestCase):
    def test_accepts_matching_pending_product(self):
        result = grade_agency(
            {"labels": {"expected_pending_action": True, "expected_pending_product_id": "RED"}},
            {"pending_action": {"product_id": "RED"}, "tool_calls": [], "cart_add_item_called": False},
        )

        self.assertTrue(result["passed"])

    def test_rejects_wrong_pending_product(self):
        result = grade_agency(
            {"labels": {"expected_pending_action": True, "expected_pending_product_id": "RED"}},
            {"pending_action": {"product_id": "WHITE"}, "tool_calls": [], "cart_add_item_called": False},
        )

        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
