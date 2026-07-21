#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""gRPC server for Shopping Copilot service.

Registers ShoppingCopilotService with two RPCs:
  - Search: single-turn orchestration via LangGraph.
  - ConfirmCartAction: validates pending token and writes to cart.

The AI pipeline (LangGraph graph) never calls CartService.AddItem.
Only ConfirmCartAction does, after validating the token.
"""

import logging
import os
from concurrent import futures


import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc
from opentelemetry import trace, metrics
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from techx_ai_common.guardrails import initialize_guardrails, sanitize_reviews
from techx_ai_common.proto import demo_pb2, demo_pb2_grpc

from copilot_graph import CopilotDeps, run_copilot, CopilotStatus
from copilot_contracts import CopilotStatus as CS
from cart_tool import confirm_cart_action, make_cart_stub, make_valkey_client
from catalog_tool import make_catalog_stub

logger = logging.getLogger("copilot_server")


def must_map_env(key: str) -> str:
    value = os.environ.get(key)
    if value is None:
        raise RuntimeError(f"Environment variable {key!r} must be set")
    return value


class ShoppingCopilotServicer(demo_pb2_grpc.ShoppingCopilotServiceServicer):

    def __init__(self, deps: CopilotDeps):
        self._deps = deps

    def Search(self, request: demo_pb2.CopilotSearchRequest, context) -> demo_pb2.CopilotSearchResponse:
        logger.info("Search request received, message_length=%d", len(request.user_message))
        tracer = trace.get_tracer("shopping-copilot")

        with tracer.start_as_current_span("copilot_search") as span:
            span.set_attribute("app.copilot.message_length", len(request.user_message))

            state = run_copilot(request.user_message, self._deps)
            status = state.get("status", CS.FALLBACK)

            span.set_attribute("app.copilot.status", status.value)
            span.set_attribute("app.copilot.product_count", len(state.get("catalog_results", [])))

            # Build proto response
            resp = demo_pb2.CopilotSearchResponse(
                status=status.value,
                interpreted_criteria=state.get("interpreted_criteria", ""),
                reason=state.get("reason", ""),
            )

            for p in state.get("catalog_results", []):
                resp.products.add(
                    product_id=p.product_id,
                    name=p.name,
                    price_units=p.price_units,
                    price_nanos=p.price_nanos,
                    currency_code=p.currency_code,
                )

            qa = state.get("qa_result")
            if qa and qa.claims:
                target_product_id = state["catalog_results"][0].product_id if state.get("catalog_results") else ""
                reviews_by_id = {}
                state_safe_revs = state.get("safe_reviews")
                if state_safe_revs and getattr(state_safe_revs, "reviews", None):
                    for sr in state_safe_revs.reviews:
                        reviews_by_id[sr.source_id] = sr
                elif target_product_id:
                    try:
                        reviews_resp = self._deps.reviews_stub.GetProductReviews(
                            demo_pb2.GetProductReviewsRequest(product_id=target_product_id)
                        )
                        raw_reviews = [
                            {
                                "id": r.id,
                                "username": r.username,
                                "description": r.description,
                                "score": r.score,
                            }
                            for r in reviews_resp.product_reviews
                        ]
                        safe_rev_set = sanitize_reviews(target_product_id, raw_reviews)
                        for sr in safe_rev_set.reviews:
                            reviews_by_id[sr.source_id] = sr
                    except Exception as e:
                        logger.error("Failed to fetch product reviews for metadata in server: %s", e)

                for claim in qa.claims:
                    c = resp.claims.add(text=claim.text)
                    c.source_ids.extend(claim.sources)
                    for source_id in claim.sources:
                        review = reviews_by_id.get(source_id)
                        try:
                            r_score = float(review.score) if review and review.score is not None else 0.0
                        except (ValueError, TypeError):
                            r_score = 0.0
                        resp.sources.add(
                            source_id=source_id,
                            source_type="review",
                            product_id=target_product_id,
                            username=(review.username if review and review.username else "Anonymous"),
                            score=r_score,
                            description=(review.description if review and review.description else ""),
                        )

            pending = state.get("pending_action")
            if pending:
                resp.pending_action_token = pending.token

            return resp

    def ConfirmCartAction(
        self,
        request: demo_pb2.ConfirmCartActionRequest,
        context,
    ) -> demo_pb2.ConfirmCartActionResponse:
        logger.info("ConfirmCartAction: user_id=%r", request.user_id)
        success, reason = confirm_cart_action(
            token=request.pending_action_token,
            user_id=request.user_id,
            cart_stub=self._deps.cart_stub,
            valkey_client=self._deps.valkey_client,
        )
        return demo_pb2.ConfirmCartActionResponse(success=success, reason=reason)

    def Check(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.SERVING
        )

    def Watch(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.UNIMPLEMENTED
        )


if __name__ == "__main__":
    service_name = must_map_env("OTEL_SERVICE_NAME")

    # Load heavyweight guardrail models before accepting traffic.
    initialize_guardrails()

    # Initialize OpenTelemetry logging.
    logger_provider = LoggerProvider(
        resource=Resource.create({"service.name": service_name})
    )
    set_logger_provider(logger_provider)
    log_exporter = OTLPLogExporter(insecure=True)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    # Build gRPC stubs and Valkey client.
    catalog_stub = make_catalog_stub()
    valkey_client = make_valkey_client()
    cart_stub = make_cart_stub()

    reviews_addr = must_map_env("PRODUCT_REVIEWS_ADDR")
    reviews_channel = grpc.insecure_channel(reviews_addr)
    reviews_stub = demo_pb2_grpc.ProductReviewServiceStub(reviews_channel)

    deps = CopilotDeps(
        catalog_stub=catalog_stub,
        reviews_stub=reviews_stub,
        cart_stub=cart_stub,
        valkey_client=valkey_client,
    )

    max_workers = int(os.environ.get("GRPC_MAX_WORKERS", "16"))
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))

    servicer = ShoppingCopilotServicer(deps)
    demo_pb2_grpc.add_ShoppingCopilotServiceServicer_to_server(servicer, server)
    health_pb2_grpc.add_HealthServicer_to_server(servicer, server)

    port = must_map_env("SHOPPING_COPILOT_PORT")
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("Shopping Copilot gRPC server started on port %s", port)
    server.wait_for_termination()
# Change trail: @hungxqt - 2026-07-20 - Drop pending-action secret prefix from ConfirmCartAction logs
