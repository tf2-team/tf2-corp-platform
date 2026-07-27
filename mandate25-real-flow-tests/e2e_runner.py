#!/usr/bin/env python3
"""Run MANDATE25 against the existing Docker Compose services.

This runner is an external gRPC client. It does not import application
modules, replace dependencies, or create a second Compose configuration.
Run it from the repository root with the existing docker-compose.yml loaded.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import grpc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ai-common"))
from techx_ai_common.proto import demo_pb2, demo_pb2_grpc  # noqa: E402


COMPOSE = (
    "docker",
    "compose",
    "--env-file",
    str(ROOT / ".env"),
    "--env-file",
    str(ROOT / ".env.override"),
)
FALLBACK = "FALLBACK"
SAFE_FALLBACK_REASON = (
    "Shopping assistance is temporarily unavailable. "
    "Please try again shortly."
)


def compose(*args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        (*COMPOSE, *args),
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"docker compose {' '.join(args)} failed ({result.returncode}): {detail}"
        )
    return result.stdout.strip()


def host_endpoint(service: str, port: int) -> str:
    """Resolve the host port from the existing single-port Compose mapping."""
    deadline = time.monotonic() + 60
    last = ""
    while time.monotonic() < deadline:
        try:
            last = compose("port", service, str(port))
            match = re.search(r":(\d+)\s*$", last)
            if match:
                return f"127.0.0.1:{match.group(1)}"
        except RuntimeError as exc:
            last = str(exc)
        time.sleep(1)
    raise RuntimeError(f"Cannot resolve host port for {service}:{port}: {last!r}")


def service_env(fault_mode: str) -> dict[str, str]:
    env = os.environ.copy()
    env["LLM_PROVIDER"] = "bedrock"
    env["AI_CACHE_ENABLED"] = "false"
    env["BEDROCK_FAULT_MODE"] = fault_mode
    env["BEDROCK_MAX_ATTEMPTS"] = "3"
    env["BEDROCK_SCHEMA_MAX_ATTEMPTS"] = "2"
    env["BEDROCK_BREAKER_FAILURE_THRESHOLD"] = "3"
    env["BEDROCK_BREAKER_RECOVERY_SECONDS"] = "2"
    env["BEDROCK_TOTAL_DEADLINE_SECONDS"] = "14"
    env["COPILOT_GRAPH_TIMEOUT_SECONDS"] = "15"
    env["COPILOT_PENDING_TOKEN_TTL_SECONDS"] = "2"
    env["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    return env


def ensure_services(fault_mode: str, recreate: bool = False) -> None:
    env = service_env(fault_mode)
    args = ["up", "-d"]
    if recreate:
        args.append("--force-recreate")
    args.extend(
        (
            "product-reviews",
            "shopping-copilot",
        )
    )
    compose(*args, env=env)


def container_ids() -> dict[str, str]:
    ids: dict[str, str] = {}
    for service in ("product-reviews", "shopping-copilot"):
        try:
            ids[service] = compose("ps", "-q", service)
        except RuntimeError:
            ids[service] = ""
    return ids


def service_logs(service: str, since: str = "10m") -> str:
    try:
        return compose("logs", "--since", since, service)
    except RuntimeError:
        return ""


def wait_channel(address: str) -> grpc.Channel:
    channel = grpc.insecure_channel(address)
    grpc.channel_ready_future(channel).result(timeout=60)
    return channel


class RealFlow:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.user_id = os.environ.get("MANDATE25_USER_ID", "mandate25-e2e-user")
        self.product_reviews = host_endpoint("product-reviews", 3551)
        self.shopping_copilot = host_endpoint("shopping-copilot", 3552)
        self.catalog = host_endpoint("product-catalog", 3550)
        self.cart = host_endpoint("cart", 7070)
        self.valkey_addr = host_endpoint("valkey-cart", 6379)
        self.product_id, self.product_name = self.find_product()
        self.review_source_ids = self.find_review_source_ids()
        self.catalog_product_ids = self.find_catalog_product_ids()

    def find_catalog_product_ids(self) -> set[str]:
        channel = wait_channel(self.catalog)
        try:
            stub = demo_pb2_grpc.ProductCatalogServiceStub(channel)
            return {
                product.id
                for product in stub.ListProducts(demo_pb2.Empty(), timeout=30).products
            }
        finally:
            channel.close()

    def find_review_source_ids(self) -> set[str]:
        channel = wait_channel(self.product_reviews)
        try:
            stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
            response = stub.GetProductReviews(
                demo_pb2.GetProductReviewsRequest(product_id=self.product_id),
                timeout=30,
            )
            return {review.id for review in response.product_reviews if review.id}
        finally:
            channel.close()

    def find_product(self) -> tuple[str, str]:
        channel = wait_channel(self.catalog)
        reviews_channel = wait_channel(self.product_reviews)
        catalog = demo_pb2_grpc.ProductCatalogServiceStub(channel)
        reviews = demo_pb2_grpc.ProductReviewServiceStub(reviews_channel)
        products = catalog.ListProducts(demo_pb2.Empty(), timeout=30).products
        explicit = os.environ.get("MANDATE25_PRODUCT_ID", "").strip()
        for product in products:
            if explicit and product.id != explicit:
                continue
            review_response = reviews.GetProductReviews(
                demo_pb2.GetProductReviewsRequest(product_id=product.id),
                timeout=30,
            )
            if review_response.product_reviews or explicit:
                channel.close()
                reviews_channel.close()
                return product.id, product.name
        channel.close()
        reviews_channel.close()
        if not products:
            raise RuntimeError("Product catalog returned no products")
        return products[0].id, products[0].name

    @staticmethod
    def trace_metadata() -> tuple[str, tuple[str, str]]:
        trace_id = secrets.token_hex(16)
        span_id = secrets.token_hex(8)
        return trace_id, ("traceparent", f"00-{trace_id}-{span_id}-01")

    def call_product_reviews(self, user_id: str | None = None) -> dict[str, Any]:
        channel = wait_channel(self.product_reviews)
        stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
        started = time.monotonic()
        response = stub.AskProductAIAssistant(
            demo_pb2.AskProductAIAssistantRequest(
                product_id=self.product_id,
                question="What do customers say about quality and reliability?",
            ),
            timeout=40,
            metadata=(("x-session-id", user_id or self.user_id),),
        )
        channel.close()

        # Product Reviews keeps its compatibility contract by serializing the
        # structured result into ``response.response``. The protobuf also has
        # top-level status/reason fields, but this handler does not populate
        # them, so the E2E client must decode the response envelope first.
        payload: dict[str, Any] = {}
        try:
            decoded = json.loads(response.response)
            if isinstance(decoded, dict):
                payload = decoded
        except (TypeError, json.JSONDecodeError):
            pass

        return {
            "surface": "product-reviews",
            "status": payload.get("status") or response.status,
            "reason": payload.get("reason") or response.reason,
            "claims": len(payload.get("claims", response.claims)),
            "claim_source_ids": [
                source_id
                for claim in payload.get("claims", [])
                for source_id in claim.get("source_ids", claim.get("sources", []))
            ],
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        }

    def call_copilot(self, message: str, user_id: str | None = None) -> dict[str, Any]:
        channel = wait_channel(self.shopping_copilot)
        stub = demo_pb2_grpc.ShoppingCopilotServiceStub(channel)
        started = time.monotonic()
        response = stub.Search(
            demo_pb2.CopilotSearchRequest(
                user_message=message,
                user_id=user_id or self.user_id,
            ),
            timeout=40,
        )
        channel.close()
        return {
            "surface": "shopping-copilot",
            "status": response.status,
            "reason": response.reason,
            "products": len(response.products),
            "product_ids": [product.product_id for product in response.products],
            "claims": len(response.claims),
            "claim_source_ids": [
                source_id for claim in response.claims for source_id in claim.source_ids
            ],
            "pending_action_token": response.pending_action_token,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        }

    @staticmethod
    def safe_reason(result: dict[str, Any]) -> bool:
        return not any(
            value in result.get("reason", "")
            for value in ("Traceback", "AccessDenied", "ValidationError", "Injected")
        )

    def result(
        self,
        checks: dict[str, bool],
        response: dict[str, Any],
    ) -> dict[str, Any]:
        response["checks"] = checks
        response["pass"] = all(checks.values())
        return response

    def baseline(self) -> list[dict[str, Any]]:
        pr = self.call_product_reviews()
        sc = self.call_copilot(f"Find {self.product_name}")
        return [
            self.result(
                {
                    "valid_status": pr["status"] in {"GROUNDED", "ABSTAINED"},
                    "safe_reason": self.safe_reason(pr),
                    "valid_claim_sources": (
                        pr["status"] != "GROUNDED"
                        or (
                            bool(pr["claim_source_ids"])
                            and set(pr["claim_source_ids"]) <= self.review_source_ids
                        )
                    ),
                },
                pr,
            ),
            self.result(
                {
                    "grounded": sc["status"] == "GROUNDED",
                    "has_product": sc["products"] > 0,
                    "catalog_products_only": (
                        bool(sc["product_ids"])
                        and set(sc["product_ids"]) <= self.catalog_product_ids
                    ),
                    "valid_review_sources": (
                        not sc["claim_source_ids"]
                        or set(sc["claim_source_ids"]) <= self.review_source_ids
                    ),
                    "safe_reason": self.safe_reason(sc),
                },
                sc,
            ),
        ]

    def provider_failure(self) -> list[dict[str, Any]]:
        results = []
        for call, service in (
            (self.call_product_reviews, "product-reviews"),
            (lambda: self.call_copilot(f"Find {self.product_name}"), "shopping-copilot"),
        ):
            response = call()
            results.append(
                self.result(
                    {
                        "fallback": response["status"] == FALLBACK,
                        "safe_reason": self.safe_reason(response),
                    },
                    response,
                )
            )
        return results

    def sustained_outage(self) -> list[dict[str, Any]]:
        results = []
        for surface, service in (
            ("product-reviews", "product-reviews"),
            ("shopping-copilot", "shopping-copilot"),
        ):
            def call_outage(index: int) -> dict[str, Any]:
                # Each logical request must pass the 2-second Valkey cooldown.
                # The breaker remains shared by model/region within this process.
                user_id = f"{self.user_id}-outage-{surface}-{index}"
                if surface == "product-reviews":
                    return self.call_product_reviews(user_id)
                return self.call_copilot(f"Find {self.product_name}", user_id)

            for index in range(1, 4):
                call_outage(index)
            response = call_outage(4)
            logs = service_logs(service)
            results.append(
                self.result(
                    {
                        "fallback": response["status"] == FALLBACK,
                        "breaker_rejected": "bedrock_breaker_rejected" in logs,
                        "breaker_opened": "bedrock_breaker_opened" in logs,
                    },
                    response,
                )
            )
        return results

    def recovery(self) -> list[dict[str, Any]]:
        """Run after the caller recreates Compose with BEDROCK_FAULT_MODE=none.

        Existing configuration exposes fault mode only at process startup.
        Therefore this verifies service recovery, but marks same-process
        half-open recovery as unproven instead of claiming it.
        """
        results = []
        for call in (
            self.call_product_reviews,
            lambda: self.call_copilot(f"Find {self.product_name}"),
        ):
            response = call()
            results.append(
                self.result(
                    {
                        "not_fallback": response["status"] != FALLBACK,
                        "safe_reason": self.safe_reason(response),
                        "recovery_response": response["status"] in {"GROUNDED", "ABSTAINED"},
                    },
                    response,
                )
            )
        return results

    def malformed_output(self) -> list[dict[str, Any]]:
        results = []
        for call, service in (
            (self.call_product_reviews, "product-reviews"),
            (lambda: self.call_copilot(f"Find {self.product_name}"), "shopping-copilot"),
        ):
            response = call()
            results.append(
                self.result(
                    {
                        "fallback": response["status"] == FALLBACK,
                        "safe_reason": self.safe_reason(response),
                        "no_tool_args_executed": (
                            service != "shopping-copilot"
                            or (
                                response["products"] == 0
                                and not response["pending_action_token"]
                            )
                        ),
                    },
                    response,
                )
            )
        return results

    def cart(self) -> list[dict[str, Any]]:
        before = self.cart_items(self.user_id)
        search = self.call_copilot(f"Add {self.product_name} to my cart")
        token = search["pending_action_token"]
        if not token:
            return [
                self.result(
                    {"pending_token_created": False},
                    search,
                )
            ]

        channel = wait_channel(self.shopping_copilot)
        stub = demo_pb2_grpc.ShoppingCopilotServiceStub(channel)
        confirmed = stub.ConfirmCartAction(
            demo_pb2.ConfirmCartActionRequest(
                pending_action_token=token,
                user_id=self.user_id,
            ),
            timeout=30,
        )
        replay = stub.ConfirmCartAction(
            demo_pb2.ConfirmCartActionRequest(
                pending_action_token=token,
                user_id=self.user_id,
            ),
            timeout=30,
        )
        channel.close()
        after = self.cart_items(self.user_id)
        return [
            self.result(
                {
                    "pending_token_created": True,
                    "confirm_success": confirmed.success,
                    "replay_rejected": not replay.success,
                    "cart_changed_once": (
                        sum(q for pid, q in after if pid == self.product_id)
                        == sum(q for pid, q in before if pid == self.product_id) + 1
                    ),
                },
                search,
            )
        ]

    def cart_items(self, user_id: str) -> list[tuple[str, int]]:
        address = self.cart
        channel = wait_channel(address)
        stub = demo_pb2_grpc.CartServiceStub(channel)
        response = stub.GetCart(
            demo_pb2.GetCartRequest(user_id=user_id),
            timeout=30,
        )
        channel.close()
        return [(item.product_id, item.quantity) for item in response.items]

    def run(self, scenario: str) -> dict[str, Any]:
        functions: dict[str, Callable[[], list[dict[str, Any]]]] = {
            "baseline": self.baseline,
            "provider-failure": self.provider_failure,
            "sustained-outage": self.sustained_outage,
            "recovery": self.recovery,
            "malformed-json": self.malformed_output,
            "schema-mismatch": self.malformed_output,
            "cart": self.cart,
        }
        if scenario == "deadline":
            results = self.provider_failure()
            for item in results:
                item["checks"]["deadline_observed"] = item["elapsed_ms"] <= 15000
                item["pass"] = all(item["checks"].values())
        else:
            results = functions[scenario]()
        summary = {
            "scenario": scenario,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "results": results,
            "pass": bool(results) and all(item["pass"] for item in results),
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        default="all",
        choices=(
            "all",
            "provider-failure",
            "sustained-outage",
            "recovery",
            "malformed-output",
        ),
    )
    parser.add_argument(
        "--fault-mode",
        default="none",
        choices=("none", "timeout", "throttling", "server_error", "malformed_json", "schema_mismatch", "blocking_timeout"),
    )
    args = parser.parse_args()
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = ROOT / "mandate25-real-flow-tests" / "artifacts" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = {
        "provider-failure": [
            ("provider-failure", "timeout")
        ],
        "sustained-outage": [("sustained-outage", "timeout")],
        "recovery": [("recovery", "none")],
        "malformed-output": [("malformed-json", "malformed_json")],
    }
    selected = (
        [case for group in cases.values() for case in group]
        if args.scenario == "all"
        else cases[args.scenario]
    )
    summaries: list[dict[str, Any]] = []
    infrastructure_errors: list[str] = []
    for scenario, fault_mode in selected:
        try:
            before_ids = container_ids()
            ensure_services(
                args.fault_mode if args.scenario != "all" and args.fault_mode != "none" else fault_mode,
                recreate=True,
            )
            summary = RealFlow(output_dir).run(scenario)
            summary["fault_mode"] = fault_mode
            summary["container_ids_before"] = before_ids
            summary["container_ids_after"] = container_ids()
            summary["breaker_log_evidence"] = {
                service: {
                    event: event in service_logs(service)
                    for event in (
                        "bedrock_breaker_opened",
                        "bedrock_breaker_rejected",
                        "bedrock_breaker_half_open",
                        "bedrock_breaker_recovered",
                    )
                }
                for service in ("product-reviews", "shopping-copilot")
            }
            summaries.append(summary)
            (output_dir / f"{scenario}-{fault_mode}.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:  # Preserve an auditable report on infrastructure failure.
            infrastructure_errors.append(f"{scenario}/{fault_mode}: {exc!r}")
            break

    aggregate = {
        "run_id": run_id,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pass": bool(summaries) and not infrastructure_errors and all(
            summary["pass"] for summary in summaries
        ),
        "summaries": summaries,
        "infrastructure_errors": infrastructure_errors,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    rows = []
    for summary in summaries:
        for result in summary["results"]:
            rows.append(
                "| {surface} | {scenario}/{fault} | {status} | {elapsed} | {verdict} |".format(
                    surface=result["surface"],
                    scenario=summary["scenario"],
                    fault=summary["fault_mode"],
                    status=result.get("status", ""),
                    elapsed=result.get("elapsed_ms", ""),
                    verdict="PASS" if result["pass"] else "FAIL",
                )
            )
    report = "\n".join(
        [
            "# MANDATE25 real-flow test report",
            "",
            f"- Run ID: `{run_id}`",
            f"- Overall: **{'PASS' if aggregate['pass'] else 'FAIL'}**",
            (
                f"- Product: `{summaries[0]['product_id']}` ({summaries[0]['product_name']})"
                if summaries
                else "- Product: not resolved because infrastructure startup failed"
            ),
            "",
            "## Results",
            "",
            "| Surface | Scenario | Status | Elapsed ms | Result |",
            "|---|---|---:|---:|---:|",
            *rows,
            "",
            "## Infrastructure errors",
            "",
            *(
                [f"- {error}" for error in infrastructure_errors]
                if infrastructure_errors
                else ["- None."]
            ),
            "",
            "## Evidence policy",
            "",
            "- No Prometheus, Jaeger, trace, or metric query is used.",
            "- Each result is based on a real gRPC response from the Compose service. Container IDs and scenario JSON are retained beside this report.",
            "- Recovery is verified by recreating the service with `BEDROCK_FAULT_MODE=none` and requiring a successful real request; same-process recovery requires runtime fault-control support in the service.",
            "",
            "Raw evidence is stored beside this report in `summary.json` and per-case JSON files.",
            "",
        ]
    )
    (output_dir / "summary.md").write_text(report, encoding="utf-8")
    (ROOT / "mandate25-real-flow-tests" / "MANDATE25-RESULT.md").write_text(
        report,
        encoding="utf-8",
    )
    print(f"Report: {output_dir / 'summary.md'}")
    return 0 if aggregate["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
