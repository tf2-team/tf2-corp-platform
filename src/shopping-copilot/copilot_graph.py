#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""LangGraph single-turn orchestration graph for Shopping Copilot.

Flow:
    START
      → input_guardrail_node     ← block injection/PII in user message
      → intent_parse_node        ← extract ShoppingIntent
      → catalog_search_node      ← call ProductCatalogService.SearchProducts
      → [conditional] qa_node    ← if needs_review_qa AND catalog_results non-empty
      → [conditional] cart_node  ← if wants_add_to_cart AND catalog_results non-empty
      → build_response_node      ← assemble final CopilotState.response
    END

Each node is wrapped in try/except; any unhandled exception routes to
fallback_node which sets status=FALLBACK and stops the graph.

Bounds (enforced by LangGraph config):
    recursion_limit = 5
    timeout        = 15 seconds (asyncio.wait_for in copilot_server.py)
"""

import asyncio
import logging
import os
import sys
from typing import Optional, TypedDict

_PRODUCT_REVIEWS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../product-reviews")
)
if _PRODUCT_REVIEWS_DIR not in sys.path:
    sys.path.insert(0, _PRODUCT_REVIEWS_DIR)


from langgraph.graph import StateGraph, START, END

import demo_pb2_grpc
import valkey as valkeylib

from ai_contracts import GroundedResponse, ResponseStatus
from copilot_contracts import (
    CopilotStatus,
    ShoppingIntent,
    CopilotProductResult,
    PendingCartAction,
)
from guardrails import sanitize_request
from ai_contracts import GuardrailAction
import intent_parser
from catalog_tool import search_catalog
from review_tool import answer_with_reviews
from cart_tool import create_pending_token


logger = logging.getLogger("copilot_graph")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class CopilotState(TypedDict):
    user_message: str
    # Sanitized version of the message (after PII redaction).
    safe_message: str
    intent: Optional[ShoppingIntent]
    # product_id values from catalog results — the only IDs allowed in review/cart tools.
    allowed_product_ids: list[str]
    catalog_results: list[CopilotProductResult]
    qa_result: Optional[GroundedResponse]
    pending_action: Optional[PendingCartAction]
    status: CopilotStatus
    interpreted_criteria: str
    reason: str
    # Populated by build_response_node; everything else is intermediate.
    error: Optional[str]


# ---------------------------------------------------------------------------
# Dependency container (populated in copilot_server.py at startup)
# ---------------------------------------------------------------------------

class CopilotDeps:
    """Holds gRPC stubs and Valkey client shared across all graph invocations."""
    def __init__(
        self,
        catalog_stub: demo_pb2_grpc.ProductCatalogServiceStub,
        reviews_stub: demo_pb2_grpc.ProductReviewServiceStub,
        cart_stub: demo_pb2_grpc.CartServiceStub,
        valkey_client: valkeylib.Valkey,
    ):
        self.catalog_stub = catalog_stub
        self.reviews_stub = reviews_stub
        self.cart_stub = cart_stub
        self.valkey_client = valkey_client


# ---------------------------------------------------------------------------
# Node factories (accept deps via closure)
# ---------------------------------------------------------------------------

def make_nodes(deps: CopilotDeps):

    def input_guardrail_node(state: CopilotState) -> CopilotState:
        """Block prompt injection and PII in the user message."""
        result = sanitize_request(product_id="", question=state["user_message"])
        if result.action == GuardrailAction.BLOCK:
            logger.info("Input blocked by guardrail: %s", result.reason)
            return {
                **state,
                "status": CopilotStatus.BLOCKED,
                "reason": "Your request could not be processed.",
                "error": result.reason,
            }
        safe_msg = (
            result.sanitized_text
            if result.action == GuardrailAction.SANITIZED and result.sanitized_text
            else state["user_message"]
        )
        return {**state, "safe_message": safe_msg}

    def intent_parse_node(state: CopilotState) -> CopilotState:
        """Parse safe_message into a ShoppingIntent."""
        try:
            intent = intent_parser.parse_intent(state["safe_message"])
            if not intent.is_shopping_related:
                logger.info("Out-of-scope request blocked: %r", state["safe_message"])
                return {
                    **state,
                    "intent": intent,
                    "status": CopilotStatus.BLOCKED,
                    "reason": "I am a shopping assistant and can only help with product discovery, user reviews, and shopping cart operations. Please ask a shopping-related question.",
                }
            criteria_parts = [f'query="{intent.query}"']
            if intent.category:
                criteria_parts.append(f"category={intent.category}")
            if intent.max_price is not None:
                criteria_parts.append(f"max_price=${intent.max_price:.2f}")
            if intent.features:
                criteria_parts.append(f"features={', '.join(intent.features)}")
            return {
                **state,
                "intent": intent,
                "interpreted_criteria": ", ".join(criteria_parts),
            }
        except Exception as exc:
            logger.error("Intent parse failed: %s", exc)
            return {
                **state,
                "status": CopilotStatus.FALLBACK,
                "reason": "Could not understand your request. Please try again.",
                "error": str(exc),
            }

    def catalog_search_node(state: CopilotState) -> CopilotState:
        """Call ProductCatalogService.SearchProducts."""
        if state.get("status") in (CopilotStatus.BLOCKED, CopilotStatus.FALLBACK):
            return state
        try:
            results = search_catalog(state["intent"], deps.catalog_stub)
            if not results:
                q_text = state["intent"].query or state["intent"].cart_product_hint or state["user_message"]
                return {
                    **state,
                    "catalog_results": [],
                    "allowed_product_ids": [],
                    "status": CopilotStatus.NO_RESULTS,
                    "reason": f"No products matching '{q_text}' were found in our store catalog. Available categories include telescopes, accessories, binoculars, flashlights, travel, and books.",
                }
            return {
                **state,
                "catalog_results": results,
                "allowed_product_ids": [r.product_id for r in results],
            }
        except Exception as exc:
            logger.error("Catalog search failed: %s", exc)
            return {
                **state,
                "status": CopilotStatus.FALLBACK,
                "reason": "Product search is temporarily unavailable.",
                "error": str(exc),
            }

    def qa_node(state: CopilotState) -> CopilotState:
        """Ground-answer a review question for the first catalog result."""
        if state.get("status") in (CopilotStatus.BLOCKED, CopilotStatus.FALLBACK, CopilotStatus.NO_RESULTS):
            return state
        intent = state["intent"]
        if not intent or not intent.needs_review_qa or not intent.follow_up_question:
            return state
        # Default to the first/highest-ranked catalog result for Q&A.
        target_product_id = state["catalog_results"][0].product_id
        try:
            grounded = answer_with_reviews(
                product_id=target_product_id,
                question=intent.follow_up_question,
                allowed_product_ids=state["allowed_product_ids"],
                product_reviews_stub=deps.reviews_stub,
            )
            return {**state, "qa_result": grounded}
        except Exception as exc:
            logger.error("Review Q&A failed: %s", exc)
            # Non-fatal: fall through with no qa_result rather than FALLBACK.
            return {**state, "qa_result": None}

    def cart_node(state: CopilotState) -> CopilotState:
        """Prepare a pending add-to-cart token (does NOT write to cart)."""
        if state.get("status") in (CopilotStatus.BLOCKED, CopilotStatus.FALLBACK, CopilotStatus.NO_RESULTS):
            return state
        intent = state["intent"]
        if not intent or not intent.wants_add_to_cart:
            return state
        # Resolve cart_product_hint to a product_id among allowed results.
        target_product_id = None
        if intent.cart_product_hint:
            hint_lower = intent.cart_product_hint.lower()
            for p in state["catalog_results"]:
                if hint_lower in p.name.lower():
                    target_product_id = p.product_id
                    break
        if target_product_id is None:
            # Default to first result.
            target_product_id = state["catalog_results"][0].product_id
        try:
            action = create_pending_token(
                user_id="anonymous",  # replaced by real user_id from frontend in ConfirmCartAction
                product_id=target_product_id,
                quantity=1,
                valkey_client=deps.valkey_client,
            )
            return {**state, "pending_action": action}
        except Exception as exc:
            logger.error("Cart token creation failed: %s", exc)
            # Non-fatal.
            return {**state, "pending_action": None}

    def build_response_node(state: CopilotState) -> CopilotState:
        """Determine final status if not already set by an earlier node."""
        if state.get("status") in (
            CopilotStatus.BLOCKED, CopilotStatus.FALLBACK,
            CopilotStatus.NO_RESULTS, CopilotStatus.ABSTAINED,
        ):
            return state

        qa_result = state.get("qa_result")
        if qa_result and qa_result.status == ResponseStatus.ABSTAINED:
            return {**state, "status": CopilotStatus.ABSTAINED, "reason": qa_result.reason or ""}

        return {**state, "status": CopilotStatus.GROUNDED}

    def fallback_node(state: CopilotState) -> CopilotState:
        """Safety net: ensure status is FALLBACK and reason is set."""
        return {
            **state,
            "status": CopilotStatus.FALLBACK,
            "reason": state.get("reason") or "An unexpected error occurred. Please try again.",
        }

    return (
        input_guardrail_node,
        intent_parse_node,
        catalog_search_node,
        qa_node,
        cart_node,
        build_response_node,
        fallback_node,
    )


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _should_skip(state: CopilotState) -> str:
    """Route to 'skip' (build_response) if a terminal status is already set."""
    if state.get("status") in (
        CopilotStatus.BLOCKED, CopilotStatus.FALLBACK,
        CopilotStatus.NO_RESULTS,
    ):
        return "skip"
    return "continue"


def build_graph(deps: CopilotDeps) -> StateGraph:
    (
        input_guardrail_node,
        intent_parse_node,
        catalog_search_node,
        qa_node,
        cart_node,
        build_response_node,
        _,  # fallback_node not used as a standalone node here
    ) = make_nodes(deps)

    builder = StateGraph(CopilotState)

    builder.add_node("input_guardrail", input_guardrail_node)
    builder.add_node("intent_parse", intent_parse_node)
    builder.add_node("catalog_search", catalog_search_node)
    builder.add_node("qa", qa_node)
    builder.add_node("cart", cart_node)
    builder.add_node("build_response", build_response_node)

    builder.add_edge(START, "input_guardrail")
    builder.add_conditional_edges(
        "input_guardrail",
        _should_skip,
        {"skip": "build_response", "continue": "intent_parse"},
    )
    builder.add_conditional_edges(
        "intent_parse",
        _should_skip,
        {"skip": "build_response", "continue": "catalog_search"},
    )
    builder.add_conditional_edges(
        "catalog_search",
        _should_skip,
        {"skip": "build_response", "continue": "qa"},
    )
    builder.add_edge("qa", "cart")
    builder.add_edge("cart", "build_response")
    builder.add_edge("build_response", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# Entry point used by copilot_server.py
# ---------------------------------------------------------------------------

GRAPH_TIMEOUT_SECONDS = 15
GRAPH_RECURSION_LIMIT = 10



def run_copilot(user_message: str, deps: CopilotDeps) -> CopilotState:
    """Run the Shopping Copilot graph synchronously with timeout.

    Wraps asyncio execution and applies a hard deadline. Any exception
    from the graph — including timeout — produces a FALLBACK state.
    """
    graph = build_graph(deps)
    initial_state: CopilotState = {
        "user_message": user_message,
        "safe_message": user_message,
        "intent": None,
        "allowed_product_ids": [],
        "catalog_results": [],
        "qa_result": None,
        "pending_action": None,
        "status": CopilotStatus.GROUNDED,  # overridden by each node
        "interpreted_criteria": "",
        "reason": "",
        "error": None,
    }
    config = {"recursion_limit": GRAPH_RECURSION_LIMIT}

    async def _async_invoke():
        return graph.invoke(initial_state, config=config)

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            asyncio.wait_for(
                _async_invoke(),
                timeout=GRAPH_TIMEOUT_SECONDS,
            )
        )
        loop.close()
        return result

    except asyncio.TimeoutError:
        logger.error("Copilot graph timed out after %ds", GRAPH_TIMEOUT_SECONDS)
        return {
            **initial_state,
            "status": CopilotStatus.FALLBACK,
            "reason": "Request timed out. Please try again.",
            "error": "timeout",
        }
    except Exception as exc:
        logger.error("Copilot graph raised unexpected exception: %s", exc)
        return {
            **initial_state,
            "status": CopilotStatus.FALLBACK,
            "reason": "An unexpected error occurred.",
            "error": str(exc),
        }
