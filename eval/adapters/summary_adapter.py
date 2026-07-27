"""Run the real Product Reviews pipeline with deterministic review data."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


_ROOT = Path(__file__).resolve().parents[2]
for _path in (_ROOT / "src" / "ai-common", _ROOT / "src" / "product-reviews"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def run_summary_case(case: dict) -> dict:
    """Call the configured real LLM pipeline while replacing only source data."""
    import product_reviews_server as service

    case_input = case["input"]
    reviews = [
        {"id": str(index), "username": "eval", "description": item if isinstance(item, str) else item["text"], "score": "4"}
        for index, item in enumerate(case_input["mock_reviews"], 1)
    ]
    service.tracer = MagicMock()
    service.tracer.start_as_current_span.return_value.__enter__.return_value = MagicMock()
    service.product_review_svc_metrics = {"app_ai_assistant_counter": MagicMock()}
    service.valkey_client = None
    calls = []

    def traced_reviews(product_id):
        calls.append({"name": "fetch_product_reviews", "args": {"product_id": product_id}})
        return reviews

    started = time.perf_counter()
    with patch.object(service, "fetch_product_reviews", side_effect=traced_reviews):
        response = service.get_ai_assistant_response(
            case_input["product_id"], case_input["question"], user_id="eval-user"
        )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    try:
        payload = json.loads(response.response)
    except json.JSONDecodeError:
        payload = {"status": "FALLBACK", "answer": response.response, "claims": []}
    return {
        "status": payload.get("status", "FALLBACK"), "answer": payload.get("answer", ""),
        "claims": payload.get("claims", []), "tool_calls": calls,
        "latency_ms": latency_ms, "usage": {},
    }
