#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Intent parser for Shopping Copilot (A2.1).

Converts a raw user message into a structured ShoppingIntent using
Instructor + Pydantic. The LLM fills the structured fields; backend
code then validates and applies them as hard filters — the model
output is never used directly as a SQL query or free-form search string.

Public API:
    parse_intent(user_message: str) -> ShoppingIntent
"""

import logging
import os

import instructor
from openai import OpenAI

from copilot_contracts import ShoppingIntent

logger = logging.getLogger("intent_parser")

_SYSTEM_PROMPT = """\
You are a shopping assistant that extracts structured search intent from a user message.
Fill in the fields below based strictly on what the user said. Leave optional fields as null if the user did not mention them.

Rules:
- is_greeting: set to true if the message is a simple greeting or conversation start (e.g. "hi", "hello", "hey", "good morning", "chào").
- is_shopping_related: set to true for any product query, review question, cart request, or greeting. Set to false ONLY if the user asked something completely unrelated to shopping (e.g. math problems, coding tasks, general trivia, weather).
- All output fields (query, category, features, follow_up_question, cart_product_hint) MUST be written in English.
- query: a concise keyword string suitable for a product name/description search in English. IMPORTANT: If the user asked generically for "products", "items", "anything", "stuff" without naming a specific product (e.g. "show me products under $50"), set query to "" (empty string). Do NOT use generic words like "products" as a search query. If the user specified a specific product name or descriptor (e.g. "Lens Cleaning Kit"), extract that specific name.
- category: ONLY set if the user mentioned a category matching one of these exact allowed values: telescopes, accessories, travel, binoculars, flashlights, assembly, books. Leave as null if the category is not in this list.
- max_price: only set if the user mentioned a price limit. Extract the numeric value in USD.
- features: list any product characteristics the user mentioned (e.g. "waterproof", "noise cancelling") in English. Keep each item short.
- wants_description: set to true if the user explicitly asked for a description, details, or overview of a product.
- needs_review_qa: set to true if the user asked a question about reviews, quality, pros/cons, ratings, 5-star reviews, or user experiences.
- follow_up_question: only set if needs_review_qa is true. Translate or write the user's review-related or pros/cons question in English.
- wants_add_to_cart: true only if the user explicitly said they want to add something to their cart.
- cart_product_hint: only set if wants_add_to_cart is true. The product name or description the user mentioned in English.

Return JSON only. Do not add any commentary.
"""


def _get_instructor_client() -> tuple[instructor.Instructor, str]:
    """Build Instructor-wrapped OpenAI client from env vars.
    Same env vars as product-reviews for consistency.
    """
    raw_client = OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
    )
    model = os.environ["LLM_MODEL"]
    return instructor.from_openai(raw_client, mode=instructor.Mode.JSON), model


def parse_intent(user_message: str) -> ShoppingIntent:
    """Parse a raw user message into a structured ShoppingIntent.

    Uses Instructor to enforce the ShoppingIntent schema on the model
    output and retries automatically on schema mismatch.

    Raises:
        Exception: propagated to the LangGraph node which must catch it
                   and route to the fallback node.
    """
    client, model = _get_instructor_client()
    intent = client.chat.completions.create(
        model=model,
        response_model=ShoppingIntent,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_retries=2,
    )
    logger.info(
        "Intent parsed: query=%r category=%r max_price=%s "
        "needs_review_qa=%s wants_add_to_cart=%s",
        intent.query, intent.category, intent.max_price,
        intent.needs_review_qa, intent.wants_add_to_cart,
    )
    return intent
