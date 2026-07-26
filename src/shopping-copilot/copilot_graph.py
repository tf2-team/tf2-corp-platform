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
import uuid
from typing import Optional, TypedDict

from langgraph.graph import StateGraph, START, END
import valkey as valkeylib
from techx_ai_common.contracts import GroundedResponse, GuardrailAction, ResponseStatus
from techx_ai_common.guardrails import sanitize_request, scan_output
from techx_ai_common.rate_limiter import check_rate_limit
from techx_ai_common.proto import demo_pb2_grpc
from copilot_contracts import (
    CopilotStatus,
    ShoppingIntent,
    CopilotProductResult,
    PendingCartAction,
)
import intent_parser
from catalog_tool import get_product, search_catalog
import conversation_store
from review_tool import answer_with_reviews
from cart_tool import create_pending_token


logger = logging.getLogger("copilot_graph")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class CopilotState(TypedDict):
    user_message: str
    user_id: str
    conversation_id: str
    turn_id: str
    turn_sequence: int
    state_version: int
    resolved_product_id: str
    # Sanitized version of the message (after PII redaction).
    safe_message: str
    intent: Optional[ShoppingIntent]
    # product_id values from catalog results — the only IDs allowed in review/cart tools.
    allowed_product_ids: list[str]
    catalog_results: list[CopilotProductResult]
    qa_result: Optional[GroundedResponse]
    safe_reviews: Optional[dict]
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
        """Block prompt injection, PII, and enforce rate limits in the user message."""
        allowed, limit_reason = check_rate_limit(
            valkey_client=deps.valkey_client,
            client_id=state["user_id"],
            cooldown_seconds=2,
            max_requests_per_minute=10,
        )
        if not allowed:
            logger.info("Request rate limited: %s", limit_reason)
            return {
                **state,
                "status": CopilotStatus.BLOCKED,
                "reason": limit_reason or "Rate limit exceeded. Please wait before retrying.",
                "error": "RATE_LIMITED",
            }

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

    def conversation_state_node(state: CopilotState) -> CopilotState:
        """Load isolated Valkey context and allocate this turn's sequence."""
        if not state.get("conversation_id") or not state.get("turn_id"):
            return state
        try:
            stored = conversation_store.begin_turn(
                state["conversation_id"], state["turn_id"], deps.valkey_client
            )
            message = state["safe_message"].lower()
            ids = stored.get("last_result_product_ids", [])
            resolved = ""
            if ids:
                if any(token in message for token in ("second", "thứ hai", "số 2")) and len(ids) > 1:
                    resolved = ids[1]
                elif any(token in message for token in ("third", "thứ ba", "số 3")) and len(ids) > 2:
                    resolved = ids[2]
                elif any(token in message for token in ("it", "that", "đó", "kia", "nó")):
                    resolved = stored.get("selected_product_id") or ids[0]
            return {
                **state,
                "turn_sequence": stored["last_turn_sequence"],
                "state_version": stored["state_version"],
                "resolved_product_id": resolved,
            }
        except Exception as exc:
            logger.warning("Conversation state unavailable; continuing single-turn: %s", exc)
            return state

    def intent_parse_node(state: CopilotState) -> CopilotState:
        """Parse safe_message into a ShoppingIntent."""
        try:
            intent = intent_parser.parse_intent(state["safe_message"])
            if intent.is_greeting:
                logger.info("Greeting request received: %r", state["safe_message"])
                return {
                    **state,
                    "intent": intent,
                    "status": CopilotStatus.GROUNDED,
                    "reason": "Hello! How can I help you today?",
                }
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
            results = []
            if state.get("resolved_product_id"):
                product = get_product(state["resolved_product_id"], deps.catalog_stub)
                if product:
                    results = [product]
            if not results:
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
            next_state = {
                **state,
                "catalog_results": results,
                "allowed_product_ids": [r.product_id for r in results],
            }
            if state.get("conversation_id"):
                conversation_store.update_after_catalog(
                    state["conversation_id"],
                    {
                        **conversation_store.load(state["conversation_id"], deps.valkey_client),
                        "last_intent_query": state["intent"].query if state.get("intent") else "",
                        "last_category": state["intent"].category if state.get("intent") else "",
                    },
                    [r.product_id for r in results],
                    results[0].product_id if state.get("resolved_product_id") else "",
                    deps.valkey_client,
                )
            return next_state
        except Exception as exc:
            logger.error("Catalog search failed: %s", exc)
            return {
                **state,
                "status": CopilotStatus.FALLBACK,
                "reason": "Product search is temporarily unavailable.",
                "error": str(exc),
            }

    def qa_node(state: CopilotState) -> CopilotState:
        """Ground-answer a review question for the matched catalog result."""
        if state.get("status") in (CopilotStatus.BLOCKED, CopilotStatus.FALLBACK, CopilotStatus.NO_RESULTS):
            return state
        intent = state["intent"]
        if not intent or not intent.needs_review_qa or not intent.follow_up_question:
            return state

        # Match target_product_id against catalog_results using hints or query if available.
        target_product_id = None
        search_terms = []
        if intent.cart_product_hint:
            search_terms.append(intent.cart_product_hint.lower())
        if intent.query:
            search_terms.append(intent.query.lower())

        for p in state["catalog_results"]:
            p_name_lower = p.name.lower()
            for term in search_terms:
                if term in p_name_lower or p_name_lower in term:
                    target_product_id = p.product_id
                    break
            if target_product_id:
                break

        if not target_product_id:
            target_product_id = state["catalog_results"][0].product_id

        try:
            grounded, safe_revs = answer_with_reviews(
                product_id=target_product_id,
                question=intent.follow_up_question,
                allowed_product_ids=state["allowed_product_ids"],
                product_reviews_stub=deps.reviews_stub,
            )
            return {**state, "qa_result": grounded, "safe_reviews": safe_revs}
        except Exception as exc:
            logger.error("Review Q&A failed: %s", exc)
            # Non-fatal: fall through with no qa_result rather than FALLBACK.
            return {**state, "qa_result": None, "safe_reviews": None}

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
                user_id=state["user_id"],
                product_id=target_product_id,
                quantity=1,
                valkey_client=deps.valkey_client,
            )
            return {**state, "pending_action": action}
        except Exception:
            logger.error("Pending cart action creation failed")
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

        intent = state.get("intent")
        reason_text = state.get("reason", "")
        if intent and intent.wants_description and state.get("catalog_results"):
            target_p = state["catalog_results"][0]
            desc = target_p.description or target_p.name
            reason_text = f"Product Description ({target_p.name}): {desc}"

        text_to_scan = reason_text
        if qa_result and qa_result.answer:
            text_to_scan = f"{text_to_scan}\n{qa_result.answer}".strip()

        output_guard = scan_output(text_to_scan or "")
        if output_guard.action == GuardrailAction.BLOCK:
            logger.info("Output blocked by guardrail: %s", output_guard.reason)
            return {
                **state,
                "status": CopilotStatus.BLOCKED,
                "reason": output_guard.reason or "Output blocked by guardrail",
            }
        if output_guard.action == GuardrailAction.SANITIZED and output_guard.sanitized_text:
            reason_text = output_guard.sanitized_text

        return {**state, "status": CopilotStatus.GROUNDED, "reason": reason_text}

    def fallback_node(state: CopilotState) -> CopilotState:
        """Safety net: ensure status is FALLBACK and reason is set."""
        return {
            **state,
            "status": CopilotStatus.FALLBACK,
            "reason": state.get("reason") or "An unexpected error occurred. Please try again.",
        }

    return (
        input_guardrail_node,
        conversation_state_node,
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
    """Route to 'skip' (build_response) if a terminal status is already set or if greeting."""
    if state.get("intent") and state["intent"].is_greeting:
        return "skip"
    if state.get("status") in (
        CopilotStatus.BLOCKED, CopilotStatus.FALLBACK,
        CopilotStatus.NO_RESULTS,
    ):
        return "skip"
    return "continue"


def build_graph(deps: CopilotDeps) -> StateGraph:
    (
        input_guardrail_node,
        conversation_state_node,
        intent_parse_node,
        catalog_search_node,
        qa_node,
        cart_node,
        build_response_node,
        _,  # fallback_node not used as a standalone node here
    ) = make_nodes(deps)

    builder = StateGraph(CopilotState)

    builder.add_node("input_guardrail", input_guardrail_node)
    builder.add_node("conversation_state", conversation_state_node)
    builder.add_node("intent_parse", intent_parse_node)
    builder.add_node("catalog_search", catalog_search_node)
    builder.add_node("qa", qa_node)
    builder.add_node("cart", cart_node)
    builder.add_node("build_response", build_response_node)

    builder.add_edge(START, "input_guardrail")
    builder.add_conditional_edges(
        "input_guardrail",
        _should_skip,
        {"skip": "build_response", "continue": "conversation_state"},
    )
    builder.add_edge("conversation_state", "intent_parse")
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


def _valid_uuid4(value: str) -> bool:
    """Accept only canonical UUID v4 values at the conversation boundary."""
    if not value or len(value) != 36:
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value.lower()


def run_copilot(
    user_message: str,
    deps: CopilotDeps,
    user_id: str = "anonymous",
    conversation_id: str = "",
    turn_id: str = "",
) -> CopilotState:
    """Run the Shopping Copilot graph synchronously with timeout.

    Wraps asyncio execution and applies a hard deadline. Any exception
    from the graph — including timeout — produces a FALLBACK state.
    """
    graph = build_graph(deps)
    # Invalid or missing IDs intentionally degrade to the existing single-turn
    # path. They must never become Valkey/Mem0 keys.
    safe_conversation_id = conversation_id if _valid_uuid4(conversation_id) else ""
    safe_turn_id = turn_id if _valid_uuid4(turn_id) else ""
    initial_state: CopilotState = {
        "user_message": user_message,
        "user_id": user_id or "anonymous",
        "conversation_id": safe_conversation_id,
        "turn_id": safe_turn_id,
        "turn_sequence": 0,
        "state_version": 0,
        "resolved_product_id": "",
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
