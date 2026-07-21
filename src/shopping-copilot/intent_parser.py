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
  "is_greeting": boolean,
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

Examples:

User: hi
JSON: {"is_greeting":true,"is_shopping_related":true,"query":"","category":null,"max_price":null,"features":[],"needs_review_qa":false,"follow_up_question":null,"wants_add_to_cart":false,"cart_product_hint":null}

User: Show me lens cleaning kits under $30
JSON: {"is_greeting":false,"is_shopping_related":true,"query":"lens cleaning kit","category":null,"max_price":30,"features":[],"needs_review_qa":false,"follow_up_question":null,"wants_add_to_cart":false,"cart_product_hint":null}

User: Is the Red Flashlight good for night observation?
JSON: {"is_greeting":false,"is_shopping_related":true,"query":"red flashlight","category":"flashlight","max_price":null,"features":[],"needs_review_qa":true,"follow_up_question":"Is the Red Flashlight good for night observation?","wants_add_to_cart":false,"cart_product_hint":null}

User: Add the Lens Cleaning Kit to my cart
JSON: {"is_greeting":false,"is_shopping_related":true,"query":"lens cleaning kit","category":null,"max_price":null,"features":[],"needs_review_qa":false,"follow_up_question":null,"wants_add_to_cart":true,"cart_product_hint":"Lens Cleaning Kit"}

User: Write a Python quicksort program
JSON: {"is_greeting":false,"is_shopping_related":false,"query":"","category":null,"max_price":null,"features":[],"needs_review_qa":false,"follow_up_question":null,"wants_add_to_cart":false,"cart_product_hint":null}
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
