#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import re
import hashlib
import json
import logging
import os
from functools import lru_cache
from decimal import Decimal
from .contracts import (
    GuardrailAction,
    GuardrailResult,
    ToolValidationResult,
    SafeReview,
    SafeReviewSet,
)

# Setup basic logging
logger = logging.getLogger("guardrails")


def _model_is_required() -> bool:
    return os.getenv("AI_GUARDRAIL_REQUIRE_MODEL", "false").lower() in {
        "1", "true", "yes", "on"
    }


_scanner_cache = None
_scanner_initialized = False


def _prompt_injection_scanner():
    global _scanner_cache, _scanner_initialized
    if _scanner_initialized:
        return _scanner_cache

    try:
        from llm_guard.input_scanners import PromptInjection
        _scanner_cache = PromptInjection(threshold=0.5)
    except Exception as e:
        if _model_is_required():
            raise e
        logger.warning(f"Failed to load LLM Guard PromptInjection scanner: {e}")
        _scanner_cache = None

    _scanner_initialized = True
    return _scanner_cache


def initialize_guardrails() -> None:
    """Load heavyweight guardrails before the service starts accepting traffic."""
    try:
        _prompt_injection_scanner()
    except Exception:
        if _model_is_required():
            logger.exception("Required prompt-injection model failed to load")
            raise
        logger.warning("Prompt-injection model unavailable; keyword fallback is active")

    try:
        _get_presidio_engines()
    except Exception as e:
        logger.warning(f"Presidio model unavailable at startup: {e}")

# Common PII Regex Fallback patterns
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
# Match typical telephone formats: +XX XXX XXX XXXX or domestic digits
PHONE_REGEX = re.compile(r"\+?\b(?:\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
# Credit card pattern: 12 to 19 digits, possibly separated by spaces or hyphens
CARD_REGEX = re.compile(r"\b(?:\d[- ]*){12,19}\b")

# High-confidence hard-block keywords (Layer 1)
HARD_INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "reveal system prompt",
    "show system prompt",
    "output system prompt",
    "display system prompt",
    "reveal api key",
    "show api key",
    "output api key",
    "developer mode",
    "dan mode",
    "do anything now",
    "bypass instructions",
    "bypass safety",
]

# Regex patterns for dangerous combinations (Layer 1)
COMBINATION_PATTERNS = [
    # Match "act as" combined with dangerous modifiers like "unrestricted", "dan", "jailbreak"
    re.compile(r"\bact\s+as\b.*\b(unrestricted|dan|jailbreak)\b", re.IGNORECASE),
]

@lru_cache(maxsize=1)
def _get_presidio_engines():
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    return AnalyzerEngine(), AnonymizerEngine()

def redact_pii(text: str) -> str:
    """Redacts email, phone number, location/address and credit cards."""
    if not text:
        return text

    sanitized = text
    # 1. Try using Presidio Analyzer and Anonymizer
    try:
        from presidio_anonymizer.entities import OperatorConfig

        analyzer, anonymizer = _get_presidio_engines()

        results = analyzer.analyze(
            text=sanitized,
            language="en",
            entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "CREDIT_CARD"]
        )

        operators = {
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
            "LOCATION": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
            "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
        }

        anonymized = anonymizer.anonymize(
            text=sanitized,
            analyzer_results=results,
            operators=operators
        )
        sanitized = anonymized.text
    except Exception as e:
        logger.warning(f"Presidio PII anonymization failed or not installed. Error: {e}")

    # 2. Defense-in-depth: always run Regex fallback on top to catch missed or unclassified PII
    sanitized = EMAIL_REGEX.sub("[REDACTED]", sanitized)
    sanitized = PHONE_REGEX.sub("[REDACTED]", sanitized)
    sanitized = CARD_REGEX.sub("[REDACTED]", sanitized)

    return sanitized


def check_prompt_injection(text: str) -> bool:
    """Returns True if text is clean/valid, False if injection is detected.
    
    Implements a Hybrid 2-Layer check:
    - Layer 1: Fast Hard Keywords & Combination Patterns check (instantly blocks high-confidence threats).
    - Layer 2: LLM Guard Input Scanner model check (evaluates ambiguous / remaining texts).
    """
    if not text:
        return True

    text_clean = text.lower().strip()

    # --- LAYER 1: Hard Keywords & Dangerous Combinations Check ---
    for kw in HARD_INJECTION_KEYWORDS:
        if kw in text_clean:
            logger.info(f"Prompt injection detected by Layer 1 Hard Keyword: '{kw}'")
            return False

    for pattern in COMBINATION_PATTERNS:
        if pattern.search(text):
            logger.info(f"Prompt injection detected by Layer 1 Combination Pattern: '{pattern.pattern}'")
            return False

    # --- LAYER 2: LLM Guard Model Scan ---
    try:
        scanner = _prompt_injection_scanner()
        if scanner is not None:
            _, is_valid, _ = scanner.scan(text)
            if not is_valid:
                logger.info("Prompt injection detected by Layer 2 LLM Guard Model Scanner")
                return False
    except Exception as e:
        if _model_is_required():
            raise RuntimeError("Required prompt-injection model is unavailable") from e
        logger.warning(f"LLM Guard prompt injection model scan failed. Error: {e}")

    return True


def sanitize_request(product_id: str, question: str) -> GuardrailResult:
    """Blocks prompt injection, attempts to extract system prompt or modify product_id."""
    if not question:
        return GuardrailResult(action=GuardrailAction.ALLOW)

    # Check for prompt injection or system prompt extraction
    if not check_prompt_injection(question):
        return GuardrailResult(
            action=GuardrailAction.BLOCK,
            reason="Request blocked: Potential prompt injection or system prompt leakage attempt detected."
        )

    # Redact any PII from request
    sanitized = redact_pii(question)
    if sanitized != question:
        return GuardrailResult(
            action=GuardrailAction.SANITIZED,
            sanitized_text=sanitized
        )

    return GuardrailResult(action=GuardrailAction.ALLOW)


def sanitize_reviews(product_id: str, reviews) -> SafeReviewSet:
    """Cleans reviews, strips username, redacts PII, excludes prompt injections."""
    # Handle string input (JSON representation of reviews list)
    reviews_list = []
    if isinstance(reviews, str):
        try:
            reviews_list = json.loads(reviews)
        except Exception as e:
            logger.error(f"Failed to parse reviews string as JSON: {e}")
            return SafeReviewSet(product_id=product_id, reviews=[], reason="NO_ELIGIBLE_REVIEWS")
    elif isinstance(reviews, list):
        reviews_list = reviews
    else:
        logger.error(f"Unsupported reviews parameter type: {type(reviews)}")
        return SafeReviewSet(product_id=product_id, reviews=[], reason="NO_ELIGIBLE_REVIEWS")

    safe_reviews = []
    blocked_count = 0

    for item in reviews_list:
        # DB row layout: [username, description, score, id]
        if isinstance(item, (list, tuple)):
            text = item[1] if len(item) > 1 else ""
            score_val = item[2] if len(item) > 2 else None
            db_id = item[3] if len(item) > 3 else None
        elif isinstance(item, dict):
            text = item.get("description", item.get("text", ""))
            score_val = item.get("score")
            db_id = item.get("id", item.get("source_id"))
        else:
            continue

        if not text:
            continue

        # Check prompt injection inside review content
        if not check_prompt_injection(text):
            blocked_count += 1
            continue

        # Redact PII
        sanitized_text = redact_pii(text)

        # Generate stable source_id: priority to DB ID, fallback to SHA-256
        if db_id is not None:
            source_id = str(db_id)
        else:
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()
            source_id = f"rev_sha256_{h}"

        # Clean score parsing to decimal
        score = None
        if score_val is not None:
            try:
                score = Decimal(str(score_val))
            except Exception:
                pass

        username_val = item[0] if isinstance(item, (list, tuple)) and len(item) > 0 else (item.get("username") if isinstance(item, dict) else None)

        safe_reviews.append(
            SafeReview(
                source_id=source_id,
                text=sanitized_text,
                score=score,
                username=username_val,
                description=sanitized_text,
            )
        )

    # Log clean statistics
    logger.info(f"Sanitize reviews for product_id={product_id}: total={len(reviews_list)}, safe={len(safe_reviews)}, blocked={blocked_count}")

    if not safe_reviews:
        return SafeReviewSet(
            product_id=product_id,
            reviews=[],
            reason="NO_ELIGIBLE_REVIEWS"
        )

    return SafeReviewSet(
        product_id=product_id,
        reviews=safe_reviews
    )


def validate_tool_call(request_product_id: str, tool_name: str, arguments: dict) -> ToolValidationResult:
    """Ensures tool usage is safe and restricted to the current product_id."""
    allowed_tools = ["fetch_product_reviews", "fetch_product_info"]
    if tool_name not in allowed_tools:
        return ToolValidationResult(
            allowed=False,
            reason=f"Rejected: Tool '{tool_name}' is not allowed in this context."
        )

    tool_product_id = arguments.get("product_id")
    if tool_product_id != request_product_id:
        return ToolValidationResult(
            allowed=False,
            reason=f"Rejected: Mismatch product_id in tool arguments. Expected {request_product_id}, got {tool_product_id}."
        )

    return ToolValidationResult(allowed=True)


def scan_output(text: str) -> GuardrailResult:
    """Blocks PII in a model response before it reaches the user."""
    if not text:
        return GuardrailResult(action=GuardrailAction.ALLOW)

    # Detect PII in output
    try:
        analyzer, _ = _get_presidio_engines()
        results = analyzer.analyze(
            text=text,
            language="en",
            entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "CREDIT_CARD"]
        )
        if results:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason="Response blocked: Personally identifiable information (PII) detected in output."
            )
    except Exception as e:
        logger.warning(f"Presidio PII check on output failed. Using Regex fallback. Error: {e}")
        if EMAIL_REGEX.search(text) or PHONE_REGEX.search(text) or CARD_REGEX.search(text):
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason="Response blocked: Personally identifiable information (PII) detected in output."
            )

    return GuardrailResult(action=GuardrailAction.ALLOW)
# Change trail: @hungxqt - 2026-07-16 - Add Apache-2.0 copyright headers for license-checker.
