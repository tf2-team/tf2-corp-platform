# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure src/audit-alert-router is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import router


class TestAuditAlertRouter(unittest.TestCase):

    def setUp(self):
        router._WEBHOOK_URL_CACHE = None
        os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/test-webhook-url"

    def tearDown(self):
        router._WEBHOOK_URL_CACHE = None

    @patch("urllib.request.urlopen")
    def test_discord_2xx_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": json.dumps({"Detail": "High CPU utilization alert"}),
                }
            ]
        }
        res = router.handler(event)
        self.assertEqual(res, {"batchItemFailures": []})
        mock_urlopen.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_malformed_body_returns_item_failure(self, mock_urlopen):
        event = {
            "Records": [
                {
                    "messageId": "msg-malformed",
                    "body": "{invalid-json",
                }
            ]
        }
        res = router.handler(event)
        self.assertEqual(res, {"batchItemFailures": [{"itemIdentifier": "msg-malformed"}]})
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_discord_error_or_timeout_returns_item_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("HTTP 500 Internal Server Error")

        event = {
            "Records": [
                {
                    "messageId": "msg-500",
                    "body": json.dumps({"Message": "Database node down"}),
                }
            ]
        }
        res = router.handler(event)
        self.assertEqual(res, {"batchItemFailures": [{"itemIdentifier": "msg-500"}]})

    @patch("urllib.request.urlopen")
    def test_truncation_for_long_messages(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        long_text = "A" * 3000
        event = {
            "Records": [
                {
                    "messageId": "msg-long",
                    "body": json.dumps({"Detail": long_text}),
                }
            ]
        }
        res = router.handler(event)
        self.assertEqual(res, {"batchItemFailures": []})

        # Verify posted payload truncated to 2000 chars
        called_args, _ = mock_urlopen.call_args
        req = called_args[0]
        posted_body = json.loads(req.data.decode("utf-8"))
        self.assertLessEqual(len(posted_body["content"]), 2000)
        self.assertTrue(posted_body["content"].endswith("..."))

    @patch("urllib.request.urlopen")
    def test_mixed_batch_success_and_failure(self, mock_urlopen):
        # First record succeeds, second fails
        resp_ok = MagicMock()
        resp_ok.status = 204
        resp_ok.__enter__.return_value = resp_ok

        def side_effect(req, timeout=None):
            payload = json.loads(req.data.decode("utf-8"))
            if "fail" in payload["content"]:
                raise Exception("429 Too Many Requests")
            return resp_ok

        mock_urlopen.side_effect = side_effect

        event = {
            "Records": [
                {"messageId": "msg-success", "body": json.dumps({"Detail": "Normal event"})},
                {"messageId": "msg-fail", "body": json.dumps({"Detail": "fail event"})},
            ]
        }
        res = router.handler(event)
        self.assertEqual(res, {"batchItemFailures": [{"itemIdentifier": "msg-fail"}]})


if __name__ == "__main__":
    unittest.main()

# Change trail: @hungxqt - 2026-07-28 - Add unit tests for audit alert router (2xx, malformed, errors, truncation, mixed batch).
