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

from bedrock_runtime import converse_json, is_bedrock_provider
from copilot_contracts import ShoppingIntent

logger = logging.getLogger("intent_parser")

_SYSTEM_PROMPT = """\
You extract shopping intent into exactly one JSON object.

Return JSON only. Do not use Markdown or add commentary.
Always include every key below, even when its value is null, false, or []:

{
  "is_shopping_related": boolean,
  "query": string,
  "category": string | null,
  "max_price": number | null,
  "features": string[],
  "needs_review_qa": boolean,
  "follow_up_question": string | null,
  "wants_add_to_cart": boolean,
  "cart_product_hint": string | null
}

Rules:
- Translate search terms into concise English keywords.
- Put a numeric USD budget only in max_price. Never include price, currency symbols,
  "under", "below", or "less than" in query.
- "$30", "under 30 dollars", and "below $30" all become max_price: 30.
- Set category only for a clear catalog category such as headphones, laptop, or clothing.
- Set is_shopping_related=false only for requests unrelated to products, shopping, reviews, or carts.
- Set needs_review_qa=true only for questions about reviews, quality, or user experience.
- Set wants_add_to_cart=true only when the user explicitly asks to add an item to a cart.

Examples:

User: Show me lens cleaning kits under $30
JSON: {"is_shopping_related":true,"query":"lens cleaning kit","category":null,"max_price":30,"features":[],"needs_review_qa":false,"follow_up_question":null,"wants_add_to_cart":false,"cart_product_hint":null}

User: Is the Red Flashlight good for night observation?
JSON: {"is_shopping_related":true,"query":"red flashlight","category":"flashlight","max_price":null,"features":[],"needs_review_qa":true,"follow_up_question":"Is the Red Flashlight good for night observation?","wants_add_to_cart":false,"cart_product_hint":null}

User: Add the Lens Cleaning Kit to my cart
JSON: {"is_shopping_related":true,"query":"lens cleaning kit","category":null,"max_price":null,"features":[],"needs_review_qa":false,"follow_up_question":null,"wants_add_to_cart":true,"cart_product_hint":"Lens Cleaning Kit"}

User: Write a Python quicksort program
JSON: {"is_shopping_related":false,"query":"","category":null,"max_price":null,"features":[],"needs_review_qa":false,"follow_up_question":null,"wants_add_to_cart":false,"cart_product_hint":null}
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
    if is_bedrock_provider():
        return converse_json(ShoppingIntent, _SYSTEM_PROMPT, user_message)

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
