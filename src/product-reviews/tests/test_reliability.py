#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import sys
import os
import json
import pytest

sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

os.environ.setdefault("DB_CONNECTION_STRING", "postgresql://test:test@127.0.0.1:1/product_reviews")

from product_reviews_server import get_ai_assistant_response
from openai import APITimeoutError, APIConnectionError

@pytest.fixture(autouse=True)
def mock_dependencies(mocker):
    # Mock feature flags and rate limit
    mocker.patch("product_reviews_server.check_feature_flag", return_value=False)
    mocker.patch("product_reviews_server.random.random", return_value=1.0)
    
    import product_reviews_server
    import logging
    mock_tracer = mocker.MagicMock()
    mock_span_obj = mock_tracer.start_as_current_span.return_value.__enter__.return_value
    product_reviews_server.tracer = mock_tracer
    product_reviews_server.logger = logging.getLogger("test")
    product_reviews_server.product_review_svc_metrics = {"app_ai_assistant_counter": mocker.MagicMock()}
    
    yield mock_span_obj
    
    del product_reviews_server.tracer
    del product_reviews_server.logger
    del product_reviews_server.product_review_svc_metrics

def test_llm_timeout_fallback(mocker):
    """Test that an APITimeoutError from OpenAI returns a FALLBACK response."""
    mocker.patch("product_reviews_server.fetch_product_reviews_from_db", return_value=[("user1", "Great product", 5.0, "1")])
    
    mock_client = mocker.MagicMock()
    mock_client.chat.completions.create.side_effect = APITimeoutError(request=mocker.MagicMock())
    mocker.patch("product_reviews_server.OpenAI", return_value=mock_client)

    response = get_ai_assistant_response("TEST_ID", "What are the reviews saying?")
    
    assert response.response is not None
    data = json.loads(response.response)
    assert data["status"] == "FALLBACK"
    assert "timeout" in data["reason"].lower() or "apitimeouterror" in data["reason"].lower()

def test_llm_connection_error_fallback(mocker):
    """Test that an APIConnectionError from OpenAI returns a FALLBACK response."""
    mock_client = mocker.MagicMock()
    mock_client.chat.completions.create.side_effect = APIConnectionError(request=mocker.MagicMock(), message="Connection failed")
    mocker.patch("product_reviews_server.OpenAI", return_value=mock_client)

    response = get_ai_assistant_response("TEST_ID", "Tell me about this product.")
    
    data = json.loads(response.response)
    assert data["status"] == "FALLBACK"
    assert "apiconnectionerror" in data["reason"].lower()

def test_grounding_pipeline_error_fallback(mocker):
    """Test that if the grounding pipeline fails, we fallback gracefully."""
    # Force LLM tool selection to succeed but grounding pipeline to fail
    class MockChoice:
        def __init__(self, message):
            self.message = message
    class MockMessage:
        def __init__(self, content=None, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls
            
    mock_msg = MockMessage(tool_calls=[])
    mock_response = mocker.MagicMock()
    mock_response.choices = [MockChoice(mock_msg)]
    
    mock_client = mocker.MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    mocker.patch("product_reviews_server.OpenAI", return_value=mock_client)
    
    mocker.patch("product_reviews_server.fetch_product_reviews", return_value=json.dumps([["user1", "Great product", 5.0, "1"]]))
    
    # Mock grounding pipeline to raise an exception
    mocker.patch("product_reviews_server.generate_grounded_summary", side_effect=Exception("Grounding crashed"))

    response = get_ai_assistant_response("TEST_ID", "What are the reviews saying?")
    
    data = json.loads(response.response)
    assert data["status"] == "FALLBACK"

def test_final_llm_call_error_fallback(mocker):
    """Test that if the final LLM call (non-review query) fails, we fallback gracefully."""
    class MockChoice:
        def __init__(self, message):
            self.message = message
    class MockMessage:
        def __init__(self, content=None, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls
    class MockToolCall:
        def __init__(self):
            self.id = "1"
            self.function = mocker.MagicMock()
            self.function.name = "fetch_product_info"
            self.function.arguments = '{"product_id": "TEST_ID"}'

    mock_msg = MockMessage(tool_calls=[MockToolCall()])
    mock_response = mocker.MagicMock()
    mock_response.choices = [MockChoice(mock_msg)]
    
    mock_client = mocker.MagicMock()
    # First call succeeds (tool selection), second call fails
    mock_client.chat.completions.create.side_effect = [mock_response, APITimeoutError(request=mocker.MagicMock())]
    mocker.patch("product_reviews_server.OpenAI", return_value=mock_client)
    mocker.patch("product_reviews_server.fetch_product_info", return_value="Some info")
    
    response = get_ai_assistant_response("TEST_ID", "What is the weight?")
    
    data = json.loads(response.response)
    assert data["status"] == "FALLBACK"
    assert "timeout" in data["reason"].lower() or "apitimeouterror" in data["reason"].lower()
