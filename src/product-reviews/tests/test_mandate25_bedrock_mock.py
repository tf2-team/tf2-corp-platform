"""Unit tests for the Mandate #25 Bedrock reliability replica.

These tests load ``bedrock_test1.py`` explicitly so the production adapter is
not changed until the replica has been reviewed and promoted.
"""

import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path

from pydantic import BaseModel


_ADAPTER_PATH = Path(__file__).resolve().parents[2] / "ai-common" / "techx_ai_common" / "bedrock.py"
_SPEC = importlib.util.spec_from_file_location("mandate25_bedrock_mock", _ADAPTER_PATH)
assert _SPEC and _SPEC.loader
bedrock = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bedrock
_SPEC.loader.exec_module(bedrock)


class _Reply(BaseModel):
    answer: str


class _FakeClient:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def converse(self, **_kwargs):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return {"output": {"message": {"content": [{"text": outcome}]}}}


class Mandate25BedrockMockTests(unittest.TestCase):
    def setUp(self):
        self._old_env = os.environ.copy()
        os.environ.update(
            {
                "BEDROCK_MODEL_ID": "test-model",
                "AWS_REGION": "us-east-1",
                "BEDROCK_MAX_ATTEMPTS": "1",
                "BEDROCK_SCHEMA_MAX_ATTEMPTS": "2",
                "BEDROCK_BACKOFF_BASE_SECONDS": "0.01",
                "BEDROCK_BACKOFF_MAX_SECONDS": "0.01",
                "BEDROCK_BREAKER_FAILURE_THRESHOLD": "2",
                "BEDROCK_BREAKER_RECOVERY_SECONDS": "0.01",
                "BEDROCK_TOTAL_DEADLINE_SECONDS": "1",
            }
        )
        bedrock.reload_config()
        bedrock.reset_breaker_state()
        self._old_factory = bedrock._client_factory
        self._old_retryable = bedrock._is_retryable

    def tearDown(self):
        bedrock._client_factory = self._old_factory
        bedrock._is_retryable = self._old_retryable
        os.environ.clear()
        os.environ.update(self._old_env)
        bedrock.reload_config()
        bedrock.reset_breaker_state()

    def test_deadline_stops_nested_retry_before_backoff(self):
        os.environ["BEDROCK_MAX_ATTEMPTS"] = "3"
        os.environ["BEDROCK_TOTAL_DEADLINE_SECONDS"] = "0.001"
        os.environ["BEDROCK_BACKOFF_BASE_SECONDS"] = "1"
        os.environ["BEDROCK_BACKOFF_MAX_SECONDS"] = "1"
        bedrock.reload_config()
        client = _FakeClient([RuntimeError("temporary")])
        bedrock._client_factory = lambda: client
        bedrock._is_retryable = lambda _exc: True

        started = time.monotonic()
        with self.assertRaises(bedrock.BedrockDeadlineExceededError):
            bedrock.converse_text("system", "question")

        self.assertEqual(client.calls, 1)
        self.assertLess(time.monotonic() - started, 0.2)

    def test_sustained_failure_opens_breaker_and_successful_probe_recovers(self):
        failing_client = _FakeClient([RuntimeError("down"), RuntimeError("down")])
        bedrock._client_factory = lambda: failing_client
        bedrock._is_retryable = lambda _exc: False

        for _ in range(2):
            with self.assertRaises(bedrock.BedrockUnavailableError):
                bedrock.converse_text("system", "question")
        self.assertEqual(bedrock.peek_breaker_state(), "OPEN")

        with self.assertRaises(bedrock.CircuitBreakerOpenError):
            bedrock.converse_text("system", "question")
        self.assertEqual(failing_client.calls, 2)

        time.sleep(0.02)
        healthy_client = _FakeClient(['{"answer":"safe"}'])
        bedrock._client_factory = lambda: healthy_client
        self.assertEqual(bedrock.converse_text("system", "question"), '{"answer":"safe"}')
        self.assertEqual(bedrock.peek_breaker_state(), "CLOSED")

    def test_malformed_json_is_rejected_without_returning_unvalidated_output(self):
        client = _FakeClient(['{"wrong":"shape"}', 'not json'])
        bedrock._client_factory = lambda: client

        with self.assertRaises(bedrock.InvalidModelOutputError):
            bedrock.converse_json(_Reply, "system", "question")

        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
