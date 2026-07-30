#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Bounded ReAct orchestration for Shopping Copilot.

Guardrails and memory storage stay deterministic. The agent decides whether a
validated Catalog, Review, or cart-preparation tool is needed; it cannot write
a cart directly.
"""

import asyncio
import logging
import uuid
from typing import Any, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from techx_ai_common.contracts import GroundedResponse, GuardrailAction, ResponseStatus
from techx_ai_common.guardrails import sanitize_request, scan_output
from techx_ai_common.proto import demo_pb2_grpc
from techx_ai_common.rate_limiter import check_rate_limit
from techx_ai_common.semantic_cache import SemanticCache

from copilot_contracts import CopilotProductResult, CopilotStatus, PendingCartAction, RetrievalHint
import conversation_store
import mem0_client
import memory_extractor
import memory_retrieval
import shopping_cache
from react_agent import run_react_agent

logger = logging.getLogger("copilot_graph")


class CopilotState(TypedDict):
    user_message: str
    user_id: str
    conversation_id: str
    turn_id: str
    turn_sequence: int
    state_version: int
    conversation_context: str
    retrieval_hint: Optional[RetrievalHint]
    tool_access: Literal["none", "shopping"]
    memory_context: str
    safe_message: str
    allowed_product_ids: list[str]
    catalog_results: list[CopilotProductResult]
    qa_result: Optional[GroundedResponse]
    safe_reviews: Any
    pending_action: Optional[PendingCartAction]
    status: CopilotStatus
    interpreted_criteria: str
    reason: str
    error: Optional[str]
    cache_status: Literal["hit", "miss"]
    cache_match: Literal["exact", "semantic", "none"]
    cache_distance: float
    cache_eligible: bool


class CopilotDeps:
    def __init__(
        self,
        catalog_stub: demo_pb2_grpc.ProductCatalogServiceStub,
        reviews_stub: demo_pb2_grpc.ProductReviewServiceStub,
        cart_stub: demo_pb2_grpc.CartServiceStub,
        valkey_client: Any,
        semantic_cache: SemanticCache | None = None,
    ):
        self.catalog_stub = catalog_stub
        self.reviews_stub = reviews_stub
        self.cart_stub = cart_stub
        self.valkey_client = valkey_client
        self.semantic_cache = semantic_cache


def _should_stop(state: CopilotState) -> str:
    return "stop" if state.get("status") in (CopilotStatus.BLOCKED, CopilotStatus.FALLBACK) else "continue"


def _should_use_cached(state: CopilotState) -> str:
    return "cached" if state.get("cache_status") == "hit" else "continue"


def make_nodes(deps: CopilotDeps):
    def input_guardrail_node(state: CopilotState) -> CopilotState:
        allowed, limit_reason = check_rate_limit(
            valkey_client=deps.valkey_client, client_id=state["user_id"],
            cooldown_seconds=2, max_requests_per_minute=10,
        )
        if not allowed:
            return {**state, "status": CopilotStatus.BLOCKED, "reason": limit_reason or "Rate limit exceeded.", "error": "RATE_LIMITED"}
        result = sanitize_request(product_id="", question=state["user_message"])
        if result.action == GuardrailAction.BLOCK:
            return {**state, "status": CopilotStatus.BLOCKED, "reason": "Your request could not be processed.", "error": result.reason}
        safe_message = result.sanitized_text if result.action == GuardrailAction.SANITIZED and result.sanitized_text else state["user_message"]
        return {**state, "safe_message": safe_message}

    def cache_lookup_node(state: CopilotState) -> CopilotState:
        result = shopping_cache.lookup(
            deps.semantic_cache,
            state["user_id"],
            state["conversation_id"],
            state["safe_message"],
            deps,
        )
        if result is None:
            return state
        try:
            hydrated = shopping_cache.hydrate_state(state, result)
        except Exception:
            logger.warning("Invalid Shopping Copilot cache entry; continuing on miss")
            shopping_cache.record_invalid_hit(result)
            return state
        shopping_cache.record_hit(result)
        if state.get("conversation_id") and state.get("turn_id"):
            conversation_store.begin_turn(
                state["conversation_id"], state["turn_id"], deps.valkey_client
            )
        return hydrated

    def conversation_state_node(state: CopilotState) -> CopilotState:
        if not state.get("conversation_id") or not state.get("turn_id"):
            return state
        try:
            stored = conversation_store.begin_turn(state["conversation_id"], state["turn_id"], deps.valkey_client)
            ids = stored.get("last_result_product_ids", [])
            selected = stored.get("selected_product_id", "")
            allowed_ids = list(dict.fromkeys([*ids, selected])) if selected else ids
            return {
                **state,
                "turn_sequence": stored["last_turn_sequence"],
                "state_version": stored["state_version"],
                "allowed_product_ids": allowed_ids,
                "conversation_context": (
                    f"Last catalog query: {stored.get('last_intent_query', '')}\n"
                    f"Last category: {stored.get('last_category', '')}\n"
                    f"Last displayed product IDs, in order: {', '.join(ids) or 'none'}\n"
                    f"Selected product ID: {selected or 'none'}"
                ),
            }
        except Exception as exc:
            logger.warning("Conversation state unavailable; continuing single-turn: %s", type(exc).__name__)
            return state

    def turn_context_node(state: CopilotState) -> CopilotState:
        try:
            hint = memory_retrieval.parse_retrieval_hint(state["safe_message"], state.get("conversation_context", ""))
            next_state = {**state, "retrieval_hint": hint, "tool_access": hint.tool_access}
            if hint.policy_action == "block":
                return {
                    **next_state,
                    "status": CopilotStatus.BLOCKED,
                    "tool_access": "none",
                    "reason": (
                        "I can only help with safe shopping requests, product "
                        "discovery, reviews, and cart preparation."
                    ),
                    "error": "POLICY_BLOCKED",
                }
            if not mem0_client.read_enabled() or not state.get("conversation_id"):
                return next_state
            memories = mem0_client.search(hint.semantic_query or state["safe_message"], state["conversation_id"])
            values = [
                item["memory"].replace("\x00", "")[:500]
                for item in memories
                if isinstance(item.get("memory"), str) and item["memory"].strip()
            ]
            return {**next_state, "memory_context": "\n".join(values[:5])}
        except Exception as exc:
            logger.warning("Turn context unavailable; disabling tools: %s", type(exc).__name__)
            return {**state, "tool_access": "none"}

    def agent_node(state: CopilotState) -> CopilotState:
        try:
            reason = run_react_agent(state, deps)
            # The ReAct tools enrich this turn in place; return the fields explicitly
            # so LangGraph persists the structured response used by the UI.
            return {
                **state,
                "reason": reason,
                "catalog_results": state.get("catalog_results", []),
                "interpreted_criteria": state.get("interpreted_criteria", ""),
                "pending_action": state.get("pending_action"),
                "qa_result": state.get("qa_result"),
                "safe_reviews": state.get("safe_reviews"),
            }
        except Exception as exc:
            logger.error("ReAct agent failed: %s", exc)
            return {**state, "status": CopilotStatus.FALLBACK, "reason": "I could not complete that request. Please try again.", "error": str(exc)}

    def build_response_node(state: CopilotState) -> CopilotState:
        if state.get("status") in (CopilotStatus.BLOCKED, CopilotStatus.FALLBACK):
            return state
        qa_result = state.get("qa_result")
        if qa_result and qa_result.status == ResponseStatus.ABSTAINED:
            return {**state, "status": CopilotStatus.ABSTAINED, "reason": qa_result.reason or "The current reviews do not provide enough information."}
        # Keep review answers grounded instead of allowing the agent to embellish them.
        reason = qa_result.answer if qa_result and qa_result.answer else state.get("reason", "")
        output_guard = scan_output(reason)
        if output_guard.action == GuardrailAction.BLOCK:
            return {**state, "status": CopilotStatus.BLOCKED, "reason": output_guard.reason or "Output blocked."}
        if output_guard.action == GuardrailAction.SANITIZED and output_guard.sanitized_text:
            reason = output_guard.sanitized_text
        status = state.get("status", CopilotStatus.GROUNDED)
        return {**state, "status": status, "reason": reason}

    def memory_write_node(state: CopilotState) -> CopilotState:
        if (
            state.get("cache_status") == "hit"
            or not mem0_client.write_enabled() or state.get("status") != CopilotStatus.GROUNDED
            or not state.get("conversation_id") or not state.get("turn_id")
            or conversation_store.memory_turn_written(state["conversation_id"], state["turn_id"], deps.valkey_client)
        ):
            return state
        try:
            extraction = memory_extractor.extract_memories(state["safe_message"])
            wrote_all = True
            for candidate in extraction.memories:
                wrote_all = mem0_client.add(
                    content=candidate.content, conversation_id=state["conversation_id"], turn_id=state["turn_id"],
                    turn_sequence=state.get("turn_sequence", 0), memory_kind=candidate.memory_kind,
                    constraint_type=candidate.constraint_type,
                ) and wrote_all
            if extraction.memories and wrote_all:
                conversation_store.mark_memory_turn_written(state["conversation_id"], state["turn_id"], deps.valkey_client)
        except Exception as exc:
            logger.warning("Memory extraction unavailable; response remains valid: %s", type(exc).__name__)
        return state

    def cache_store_node(state: CopilotState) -> CopilotState:
        if state.get("cache_status") != "hit":
            shopping_cache.store(deps.semantic_cache, state, deps)
        return state

    return (
        input_guardrail_node,
        cache_lookup_node,
        conversation_state_node,
        turn_context_node,
        agent_node,
        build_response_node,
        memory_write_node,
        cache_store_node,
    )


def build_graph(deps: CopilotDeps) -> StateGraph:
    (
        guard,
        cache_lookup,
        conversation,
        turn_context,
        agent,
        response,
        memory_write,
        cache_store,
    ) = make_nodes(deps)
    builder = StateGraph(CopilotState)
    builder.add_node("input_guardrail", guard)
    builder.add_node("cache_lookup", cache_lookup)
    builder.add_node("conversation_state", conversation)
    builder.add_node("turn_context", turn_context)
    builder.add_node("agent", agent)
    builder.add_node("build_response", response)
    builder.add_node("memory_write", memory_write)
    builder.add_node("cache_store", cache_store)
    builder.add_edge(START, "input_guardrail")
    builder.add_conditional_edges("input_guardrail", _should_stop, {"stop": "build_response", "continue": "cache_lookup"})
    builder.add_conditional_edges(
        "cache_lookup",
        _should_use_cached,
        {"cached": "build_response", "continue": "conversation_state"},
    )
    builder.add_edge("conversation_state", "turn_context")
    builder.add_conditional_edges("turn_context", _should_stop, {"stop": "build_response", "continue": "agent"})
    builder.add_edge("agent", "build_response")
    builder.add_edge("build_response", "memory_write")
    builder.add_edge("memory_write", "cache_store")
    builder.add_edge("cache_store", END)
    return builder.compile()


GRAPH_TIMEOUT_SECONDS = 15
GRAPH_RECURSION_LIMIT = 10


def _valid_uuid4(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
        return parsed.version == 4 and str(parsed) == value.lower()
    except (ValueError, AttributeError):
        return False


def run_copilot(user_message: str, deps: CopilotDeps, user_id: str = "anonymous", conversation_id: str = "", turn_id: str = "") -> CopilotState:
    safe_conversation_id = conversation_id if _valid_uuid4(conversation_id) else ""
    safe_turn_id = turn_id if _valid_uuid4(turn_id) else ""
    initial_state: CopilotState = {
        "user_message": user_message, "user_id": user_id or "anonymous", "conversation_id": safe_conversation_id,
        "turn_id": safe_turn_id, "turn_sequence": 0, "state_version": 0,
        "conversation_context": "", "retrieval_hint": None, "tool_access": "none", "memory_context": "", "safe_message": user_message,
        "allowed_product_ids": [], "catalog_results": [], "qa_result": None, "safe_reviews": None,
        "pending_action": None, "status": CopilotStatus.GROUNDED, "interpreted_criteria": "", "reason": "", "error": None,
        "cache_status": "miss", "cache_match": "none", "cache_distance": 0.0,
        "cache_eligible": True,
    }
    graph = build_graph(deps)

    async def invoke():
        return graph.invoke(initial_state, config={"recursion_limit": GRAPH_RECURSION_LIMIT})

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(asyncio.wait_for(invoke(), timeout=GRAPH_TIMEOUT_SECONDS))
        loop.close()
        return result
    except asyncio.TimeoutError:
        return {**initial_state, "status": CopilotStatus.FALLBACK, "reason": "Request timed out. Please try again.", "error": "timeout"}
    except Exception as exc:
        error_type = type(exc).__name__
        logger.error("Copilot graph raised unexpected exception: %s", error_type)
        return {**initial_state, "status": CopilotStatus.FALLBACK, "reason": "An unexpected error occurred.", "error": error_type}
