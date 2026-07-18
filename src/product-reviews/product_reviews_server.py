#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


# Python
import os
import json
from concurrent import futures
import random

# Pip
import grpc
from opentelemetry import trace, metrics
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter,
)
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode

# Local
import logging
import demo_pb2
import demo_pb2_grpc
from grpc_health.v1 import health_pb2
from grpc_health.v1 import health_pb2_grpc
from database import fetch_product_reviews, fetch_product_reviews_from_db, fetch_avg_product_review_score_from_db

from openfeature import api
from openfeature.contrib.provider.flagd import FlagdProvider

from metrics import (
    init_metrics
)

# OpenAI
from openai import OpenAI

from google.protobuf.json_format import MessageToJson, MessageToDict

# AI trustworthiness pipeline (A1.2 guardrails -> A1.1 grounding -> A1.2 output scan)
from ai_contracts import GuardrailAction, ResponseStatus
import guardrails
from grounding import generate_grounded_summary, validate_grounded_summary

llm_host = None
llm_port = None
llm_mock_url = None
llm_base_url = None
llm_api_key = None
llm_model = None

# --- Define the tool for the OpenAI API ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "fetch_product_reviews",
            "description": "Executes a SQL query to retrieve reviews for a particular product.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID to fetch product reviews for.",
                    }
                },
                "required": ["product_id"],
            },
        }
    },
      {
          "type": "function",
          "function": {
              "name": "fetch_product_info",
              "description": "Retrieves information for a particular product.",
              "parameters": {
                  "type": "object",
                  "properties": {
                      "product_id": {
                          "type": "string",
                          "description": "The product ID to fetch information for.",
                      }
                  },
                  "required": ["product_id"],
              },
          }
      }
]

class ProductReviewService(demo_pb2_grpc.ProductReviewServiceServicer):
    def GetProductReviews(self, request, context):
        logger.info(f"Receive GetProductReviews for product id:{request.product_id}")
        product_reviews = get_product_reviews(request.product_id)

        return product_reviews

    def GetAverageProductReviewScore(self, request, context):
        logger.info(f"Receive GetAverageProductReviewScore for product id:{request.product_id}")
        product_reviews = get_average_product_review_score(request.product_id)

        return product_reviews

    def AskProductAIAssistant(self, request, context):
        logger.info(f"Receive AskProductAIAssistant for product id:{request.product_id}, question_length: {len(request.question)}")
        ai_assistant_response = get_ai_assistant_response(request.product_id, request.question)

        return ai_assistant_response

    def Check(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.SERVING)

    def Watch(self, request, context):
        return health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.UNIMPLEMENTED)

def get_product_reviews(request_product_id):

    with tracer.start_as_current_span("get_product_reviews") as span:

        span.set_attribute("app.product.id", request_product_id)

        product_reviews = demo_pb2.GetProductReviewsResponse()
        records = fetch_product_reviews_from_db(request_product_id)

        for row in records:
            logger.info(f"  review loaded for product_id: {request_product_id}, score: {str(row[2])}")
            product_reviews.product_reviews.add(
                    username=row[0],
                    description=row[1],
                    score=str(row[2]),
                    id=str(row[3])
            )

        span.set_attribute("app.product_reviews.count", len(product_reviews.product_reviews))

        # Collect metrics for this service
        product_review_svc_metrics["app_product_review_counter"].add(len(product_reviews.product_reviews), {'product.id': request_product_id})

        return product_reviews

def get_average_product_review_score(request_product_id):

    with tracer.start_as_current_span("get_average_product_review_score") as span:

        span.set_attribute("app.product.id", request_product_id)

        product_review_score = demo_pb2.GetAverageProductReviewScoreResponse()
        avg_score = fetch_avg_product_review_score_from_db(request_product_id)
        product_review_score.average_score = avg_score

        span.set_attribute("app.product_reviews.average_score", avg_score)

        return product_review_score


FALLBACK_MESSAGE = "AI summary is temporarily unavailable."
ABSTAIN_MESSAGE = "The current reviews do not provide enough information."


def _build_structured_response(status: str, answer: str = "", reason: str = "", claims: list = None) -> str:
    payload = {
        "status": status,
        "answer": answer,
        "reason": reason,
        "claims": claims or [],
    }
    return json.dumps(payload)


def _blocked_response(reason: str):
    ai_assistant_response = demo_pb2.AskProductAIAssistantResponse()
    ai_assistant_response.response = _build_structured_response(
        status="BLOCKED",
        answer="Sorry, I cannot process this request.",
        reason=reason,
    )
    logger.info(f"Request blocked by guardrails. reason={reason}")
    return ai_assistant_response


def _fallback_response(error_class: str = ""):
    """gRPC response when the LLM or a dependency fails.
    Logs the error class but never raw prompts, PII, or secrets."""
    ai_assistant_response = demo_pb2.AskProductAIAssistantResponse()
    ai_assistant_response.response = _build_structured_response(
        status="FALLBACK",
        answer=FALLBACK_MESSAGE,
        reason=f"LLM or dependency error: {error_class}" if error_class else "LLM error",
    )
    logger.warning(f"Returning fallback response. error_class={error_class}")
    return ai_assistant_response


def is_review_related(question: str) -> bool:
    if not question:
        return False
    question_lower = question.lower()
    import unicodedata
    def remove_accents(input_str):
        nfkd_form = unicodedata.normalize('NFKD', input_str)
        return "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    
    normalized_q = remove_accents(question_lower)
    keywords = [
        "review", "rating", "comment", "feedback", "opinion", 
        "danh gia", "nhan xet", "binh luan", "y kien", "phan hoi"
    ]
    for kw in keywords:
        if kw in normalized_q:
            return True
    return False


def get_ai_assistant_response(request_product_id, question):

    with tracer.start_as_current_span("get_ai_assistant_response") as span:

        ai_assistant_response = demo_pb2.AskProductAIAssistantResponse()

        span.set_attribute("app.product.id", request_product_id)
        span.set_attribute("app.product.question_length", len(question))

        # --- A1.2, step 1: is the incoming request itself safe? ---------
        # Runs before anything else — before even the rate-limit mock path
        # below, since an unsafe question should never reach any model,
        # mock or real.
        request_guard = guardrails.sanitize_request(request_product_id, question)
        span.set_attribute("app.guardrail.request_action", request_guard.action.value)
        if request_guard.action == GuardrailAction.BLOCK:
            return _blocked_response(request_guard.reason)

        if request_guard.action == GuardrailAction.SANITIZED and request_guard.sanitized_text:
            question = request_guard.sanitized_text

        span.set_attribute("app.guardrail.sanitized_question", question)
        logger.info(f"Sanitized AI Assistant question: {question}")

        # Instruct the model to call fetch_product_reviews in English for review questions
        system_prompt = (
            "You are a helpful assistant that answers related to a specific product. "
            "Use tools as needed to fetch the product reviews and product information. "
            "For questions about customer reviews, you must call the fetch_product_reviews tool using the exact product_id of the request. "
            "Keep the response brief with no more than 1-2 sentences. "
            "If you don't know the answer, just say you don't know. "
            "All responses must be written in English."
        )

        llm_rate_limit_error = check_feature_flag("llmRateLimitError")
        logger.info(f"llmRateLimitError feature flag: {llm_rate_limit_error}")
        if llm_rate_limit_error:
            random_number = random.random()
            logger.info(f"Generated a random number: {str(random_number)}")
            # return a rate limit error 50% of the time
            if random_number < 0.5:

                # ensure the mock LLM is always used, since we want to generate a 429 error
                client = OpenAI(
                    base_url=f"{llm_mock_url}",
                    # The OpenAI API requires an api_key to be present, but
                    # our LLM doesn't use it
                    api_key=f"{llm_api_key}"
                )

                user_prompt = f"Answer the following question about product ID:{request_product_id}: {question}"
                messages = [
                   {"role": "system", "content": system_prompt},
                   {"role": "user", "content": user_prompt}
                ]
                logger.info(f"Invoking mock LLM with model: techx-llm-rate-limit")

                try:
                    initial_response = client.chat.completions.create(
                        model="techx-llm-rate-limit",
                        messages=messages,
                        tools=tools,
                        tool_choice="auto"
                    )
                except Exception as e:
                    logger.error(f"Caught Exception: {e}")
                    # Record the exception
                    span.record_exception(e)
                    # Set the span status to ERROR
                    span.set_status(Status(StatusCode.ERROR, description=str(e)))
                    ai_assistant_response.response = "The system is unable to process your response. Please try again later."
                    return ai_assistant_response

        # otherwise, continue processing the request as normal
        client = OpenAI(
            base_url=f"{llm_base_url}",
            # The OpenAI API requires an api_key to be present, but
            # our LLM doesn't use it
            api_key=f"{llm_api_key}"
        )

        user_prompt = f"Answer the following question about product ID:{request_product_id}: {question}"
        messages = [
           {"role": "system", "content": system_prompt},
           {"role": "user", "content": user_prompt}
        ]

        # use the LLM to decide which tool(s) it needs
        try:
            initial_response = client.chat.completions.create(
                model=llm_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                timeout=20.0,
            )
            response_message = initial_response.choices[0].message
            tool_calls = response_message.tool_calls
            logger.info("Received initial AI assistant response")
        except Exception as e:
            # Includes APITimeoutError / connection failures — never let them
            # surface as an unhandled 500 or hang until the gateway 504s.
            logger.error(f"LLM tool-selection call failed: {type(e).__name__}")
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, description=type(e).__name__))
            return _fallback_response(type(e).__name__)

        # safe_reviews is only populated if the model calls
        # fetch_product_reviews. It feeds the grounding step below.
        safe_reviews = None

        # Check if the model wants to call a tool
        if tool_calls:
            logger.info(f"Model wants to call {len(tool_calls)} tool(s)")

            # Append the assistant's message with tool calls
            messages.append(response_message)

            # Process all tool calls
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                logger.info(f"Processing tool call: '{function_name}' with arguments: {function_args}")

                # --- A1.2, step 2: is this specific tool call allowed? --
                # Blocks unknown tool names, and blocks the model trying
                # to read a different product_id than the request's own.
                tool_check = guardrails.validate_tool_call(
                    request_product_id, function_name, function_args
                )
                if not tool_check.allowed:
                    span.set_attribute("app.guardrail.tool_call_blocked", True)
                    return _blocked_response(tool_check.reason)

                if function_name == "fetch_product_reviews":
                    raw_reviews = fetch_product_reviews(
                        product_id=function_args.get("product_id")
                    )
                    # A1.2 cleans reviews (PII, injection) before anything
                    # downstream — including before they go back into the
                    # conversation as a tool response — ever sees them.
                    safe_reviews = guardrails.sanitize_reviews(
                        function_args.get("product_id"), raw_reviews
                    )
                    span.set_attribute("app.safe_reviews.count", len(safe_reviews.reviews))
                    function_response = json.dumps(
                        [{"source_id": r.source_id, "text": r.text, "score": str(r.score)} for r in safe_reviews.reviews]
                    )
                    logger.info(f"Function response for fetch_product_reviews loaded for product_id: {function_args.get('product_id')}")

                elif function_name == "fetch_product_info":
                    function_response = fetch_product_info(
                        product_id=function_args.get("product_id")
                    )
                    logger.info(f"Function response for fetch_product_info loaded for product_id: {function_args.get('product_id')}")

                else:
                    raise Exception(f'Received unexpected tool call request: {function_name}')

                # Append the tool response
                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": function_response,
                    }
                )

        # Automatically fetch reviews from DB if model didn't call fetch_product_reviews for a review-related query
        if is_review_related(question) and safe_reviews is None:
            logger.info("Model did not call fetch_product_reviews for review-related question. Fetching reviews directly.")
            raw_reviews = fetch_product_reviews(product_id=request_product_id)
            safe_reviews = guardrails.sanitize_reviews(request_product_id, raw_reviews)
            span.set_attribute("app.safe_reviews.count", len(safe_reviews.reviews))

        llm_inaccurate_response = check_feature_flag("llmInaccurateResponse")
        logger.info(f"llmInaccurateResponse feature flag: {llm_inaccurate_response}")

        # structured_response holds the full JSON payload; candidate_text
        # is kept as a plain-text fallback for the output guardrail scan.
        structured_response = None
        candidate_text = ""

        # Enforce grounding pipeline for all review-related queries
        if is_review_related(question):
            if safe_reviews is not None and safe_reviews.reviews:
                if llm_inaccurate_response and request_product_id == "L9ECAV7KIM":
                    span.set_attribute("app.flagd.llm_inaccurate_response", True)
                    logger.info(f"llmInaccurateResponse is on for product_id: {request_product_id}; grounding must still filter any fabricated claim")

                try:
                    draft = generate_grounded_summary(safe_reviews, question=question)
                    grounded = validate_grounded_summary(draft, safe_reviews)
                except Exception as e:
                    logger.error(f"Grounding pipeline failed: {type(e).__name__}")
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, description=type(e).__name__))
                    return _fallback_response(type(e).__name__)

                span.set_attribute("app.grounding.status", grounded.status.value)

                if grounded.status == ResponseStatus.GROUNDED:
                    span.set_attribute("app.grounding.claim_count", len(grounded.claims))
                    candidate_text = grounded.answer
                    structured_response = _build_structured_response(
                        status="GROUNDED",
                        answer=grounded.answer,
                        claims=[{"text": c.text, "source_ids": c.sources} for c in grounded.claims],
                    )
                else:
                    candidate_text = grounded.reason
                    structured_response = _build_structured_response(
                        status="ABSTAINED",
                        answer=grounded.reason or ABSTAIN_MESSAGE,
                        reason=grounded.reason or ABSTAIN_MESSAGE,
                    )
            else:
                # No reviews or all blocked
                candidate_text = ABSTAIN_MESSAGE
                structured_response = _build_structured_response(
                    status="ABSTAINED",
                    answer=ABSTAIN_MESSAGE,
                    reason=ABSTAIN_MESSAGE,
                )
                span.set_attribute("app.grounding.status", "ABSTAINED")
        else:
            # Non-review queries
            if tool_calls:
                if llm_inaccurate_response and request_product_id == "L9ECAV7KIM":
                    logger.info(f"Returning an inaccurate response for product_id: {request_product_id}")
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Based on the tool results, answer the original question about product ID, but make the answer inaccurate:{request_product_id}. Keep the response brief with no more than 1-2 sentences. Reply in English."
                        }
                    )
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Based on the tool results, answer the original question about product ID:{request_product_id}. Keep the response brief with no more than 1-2 sentences. Reply in English."
                        }
                    )

                logger.info(f"Invoking the LLM with {len(messages)} messages")

                try:
                    final_response = client.chat.completions.create(
                        model=llm_model,
                        messages=messages,
                        timeout=20.0,
                    )
                    candidate_text = final_response.choices[0].message.content
                except Exception as e:
                    logger.error(f"LLM final-answer call failed: {type(e).__name__}")
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, description=type(e).__name__))
                    return _fallback_response(type(e).__name__)
            else:
                # Model answered without tools; still surface empty content as fallback
                # rather than a blank or hanging client response.
                candidate_text = response_message.content or ""
                if not candidate_text.strip():
                    return _fallback_response("EmptyLLMResponse")

        # --- A1.2, step 3: scan whatever text we're about to return -
        output_guard = guardrails.scan_output(candidate_text)
        span.set_attribute("app.guardrail.output_action", output_guard.action.value)
        if output_guard.action == GuardrailAction.BLOCK:
            return _blocked_response(output_guard.reason)
        if output_guard.action == GuardrailAction.SANITIZED and output_guard.sanitized_text:
            candidate_text = output_guard.sanitized_text

        # Use structured JSON if grounding produced one; otherwise wrap
        # the plain candidate_text as a GROUNDED response without claims.
        if structured_response:
            ai_assistant_response.response = structured_response
        else:
            ai_assistant_response.response = _build_structured_response(
                status="GROUNDED",
                answer=candidate_text or "",
            )
        logger.info(f"Returning an AI assistant response with length: {len(candidate_text or '')}")

        # Collect metrics for this service
        product_review_svc_metrics["app_ai_assistant_counter"].add(1, {'product.id': request_product_id})

        return ai_assistant_response

def fetch_product_info(product_id):
    try:
        product = product_catalog_stub.GetProduct(demo_pb2.GetProductRequest(id=product_id))
        logger.info(f"product_catalog_stub.GetProduct returned product_id: '{product_id}'")
        json_str = MessageToJson(product)
        return json_str
    except Exception as e:
        return json.dumps({"error": str(e)})

def must_map_env(key: str):
    value = os.environ.get(key)
    if value is None:
        raise Exception(f'{key} environment variable must be set')
    return value

def check_feature_flag(flag_name: str):
    # BTC original || team local- twin (either source can inject).
    client = api.get_client()
    return (
        client.get_boolean_value(flag_name, False)
        or client.get_boolean_value(f"local-{flag_name}", False)
    )

if __name__ == "__main__":
    service_name = must_map_env('OTEL_SERVICE_NAME')

    # In EKS this is strict: do not become Ready with a missing/corrupt model.
    guardrails.initialize_guardrails()

    api.set_provider(FlagdProvider(host=os.environ.get('FLAGD_HOST', 'flagd'), port=os.environ.get('FLAGD_PORT', 8013)))

    # Initialize Traces and Metrics
    tracer = trace.get_tracer_provider().get_tracer(service_name)
    meter = metrics.get_meter_provider().get_meter(service_name)

    product_review_svc_metrics = init_metrics(meter)

    # Initialize Logs
    logger_provider = LoggerProvider(
        resource=Resource.create(
            {
                'service.name': service_name,
            }
        ),
    )
    set_logger_provider(logger_provider)
    log_exporter = OTLPLogExporter(insecure=True)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)

    # Attach OTLP handler to logger
    logger = logging.getLogger('main')
    logger.addHandler(handler)

    # gRPC worker pool is shared by business RPCs and Health/Check. AskProductAIAssistant
    # holds a worker for the full LLM round-trip; a too-small pool makes health probes time
    # out under load (kubelet: "health rpc did not complete within 5s") and, when liveness
    # also uses gRPC, restarts the pod. Default 32 leaves headroom for health + short RPCs
    # while several AI calls are in flight. Override with GRPC_MAX_WORKERS.
    max_workers = int(os.environ.get('GRPC_MAX_WORKERS', '32'))
    if max_workers < 4:
        max_workers = 4
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))

    # Add class to gRPC server
    service = ProductReviewService()
    demo_pb2_grpc.add_ProductReviewServiceServicer_to_server(service, server)
    health_pb2_grpc.add_HealthServicer_to_server(service, server)

    llm_host = must_map_env('LLM_HOST')
    llm_port = must_map_env('LLM_PORT')
    llm_mock_url = f"http://{llm_host}:{llm_port}/v1"
    llm_base_url = must_map_env('LLM_BASE_URL')
    llm_api_key = must_map_env('OPENAI_API_KEY')
    llm_model = must_map_env('LLM_MODEL')

    catalog_addr = must_map_env('PRODUCT_CATALOG_ADDR')
    pc_channel = grpc.insecure_channel(catalog_addr)
    product_catalog_stub = demo_pb2_grpc.ProductCatalogServiceStub(pc_channel)

    # Start server
    port = must_map_env('PRODUCT_REVIEWS_PORT')
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    logger.info(
        f'Product reviews service started, listening on port {port}, '
        f'grpc_max_workers={max_workers}'
    )
    server.wait_for_termination()
# Change trail: @hungxqt - 2026-07-16 - Configurable gRPC max_workers to avoid health probe starvation.
