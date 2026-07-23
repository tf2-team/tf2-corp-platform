#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from adapters.copilot_adapter import normalize_copilot_output


class CopilotAdapterTests(unittest.TestCase):
    def test_preserves_pending_product_id(self):
        cart_stub = MagicMock()
        output = normalize_copilot_output(
            {
                "status": SimpleNamespace(value="GROUNDED"),
                "pending_action": SimpleNamespace(token="token", product_id="RED", quantity=1),
            },
            cart_stub,
        )

        self.assertEqual(output["pending_action"]["product_id"], "RED")
        self.assertFalse(output["cart_add_item_called"])


if __name__ == "__main__":
    unittest.main()
