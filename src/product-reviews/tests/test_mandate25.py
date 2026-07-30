#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Test Mandate #25 incidents through real services and Amazon Bedrock.

This is the only Mandate #25 test module. It separates the Shopping Copilot
and Product Review Assistant scenarios while sharing one Docker/gRPC harness.
Faults enter through container environment variables. The tests do not patch
Python objects or replace services with mocks.

Normal runtime parameters come from ``.env.override``. Editable fault
injection parameters live in ``mandate25_scenario_input.py``.

Run from the repository root:

    # List every incident configuration.
    python src/product-reviews/tests/test_mandate25.py --list-scenarios

    # Print one incident configuration.
    python src/product-reviews/tests/test_mandate25.py --show-input shopping-copilot/provider-failure

    # Run all Mandate #25 scenarios.
    python src/product-reviews/tests/test_mandate25.py

    # Inject one incident and validate its live response.
    python src/product-reviews/tests/test_mandate25.py ShoppingCopilotMandate25Tests.test_01_single_provider_failure_falls_back
    python src/product-reviews/tests/test_mandate25.py ShoppingCopilotMandate25Tests.test_02_sustained_failure_opens_breaker_then_recovers
    python src/product-reviews/tests/test_mandate25.py ShoppingCopilotMandate25Tests.test_03_malformed_tool_call_is_blocked
    python src/product-reviews/tests/test_mandate25.py ProductReviewMandate25Tests.test_01_single_provider_failure_falls_back
    python src/product-reviews/tests/test_mandate25.py ProductReviewMandate25Tests.test_02_sustained_failure_opens_breaker_then_recovers
    python src/product-reviews/tests/test_mandate25.py ProductReviewMandate25Tests.test_03_malformed_json_is_rejected_then_recovers

Pytest skips these live tests by default. Set ``RUN_MANDATE25_LIVE=1`` to run
them through pytest. Put AWS profile settings in ``.env.override`` as described
in ``docs/LOCAL_BUILD_AND_RUN.md``.

Optional settings:

* ``MANDATE25_COMPOSE_FILE`` selects a Compose file.
* ``MANDATE25_ENV_FILES`` supplies an ``os.pathsep``-separated env-file list.
* ``MANDATE25_REBUILD_IMAGE=true`` rebuilds the target service before the flow.
* ``MANDATE25_EVIDENCE_FILE`` writes each observed output as JSON.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from typing import Any

from mandate25_scenario_input import SCENARIO_CONFIGS


_TRUE_VALUES = {"1", "true", "yes", "on"}
_LIVE_REQUESTED = (
    os.environ.get("RUN_MANDATE25_LIVE", "").lower() in _TRUE_VALUES
    or __name__ == "__main__"
)

class Mandate25LiveBase(unittest.TestCase):
    """Share live Compose, gRPC, fixture, and evidence helpers."""

    _REQUIRED_COMMON_ENV = (
        "LLM_PROVIDER",
        "AI_CACHE_ENABLED",
        "MEM0_READ_ENABLED",
        "MEM0_WRITE_ENABLED",
        "AI_GUARDRAIL_REQUIRE_MODEL",
        "BEDROCK_CONNECT_TIMEOUT_SECONDS",
        "BEDROCK_READ_TIMEOUT_SECONDS",
        "BEDROCK_MAX_ATTEMPTS",
        "BEDROCK_BACKOFF_BASE_SECONDS",
        "BEDROCK_BACKOFF_MAX_SECONDS",
        "BEDROCK_SCHEMA_MAX_ATTEMPTS",
        "BEDROCK_TOTAL_DEADLINE_SECONDS",
        "BEDROCK_BREAKER_FAILURE_THRESHOLD",
        "BEDROCK_BREAKER_RECOVERY_SECONDS",
        "MANDATE25_RPC_TIMEOUT_SECONDS",
        "MANDATE25_FALLBACK_LATENCY_LIMIT_SECONDS",
        "MANDATE25_PRODUCT_REVIEW_FALLBACK_LATENCY_LIMIT_SECONDS",
        "MANDATE25_SERVICE_START_TIMEOUT_SECONDS",
    )
    _REQUIRED_SERVICES = {
        "cart",
        "otel-collector",
        "product-catalog",
        "product-reviews",
        "valkey-cart",
    }
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[3]
        self.compose_file = self._path_from_env(
            "MANDATE25_COMPOSE_FILE", "docker-compose.yml"
        )
        self.base_env = os.environ.copy()
        self.compose_env_values = self._load_compose_env_values()
        self.rpc_timeout_seconds = self._required_float(
            "MANDATE25_RPC_TIMEOUT_SECONDS"
        )
        self.fallback_latency_limit_seconds = self._required_float(
            "MANDATE25_FALLBACK_LATENCY_LIMIT_SECONDS"
        )
        self.product_review_fallback_latency_limit_seconds = self._required_float(
            "MANDATE25_PRODUCT_REVIEW_FALLBACK_LATENCY_LIMIT_SECONDS"
        )
        self.service_start_timeout_seconds = self._required_float(
            "MANDATE25_SERVICE_START_TIMEOUT_SECONDS"
        )
        self.evidence: list[dict[str, Any]] = []
        self._service_was_recreated = False
        self._recreated_service_name: str | None = None
        self._load_grpc_contracts()
        self.compose_prefix = self._build_compose_prefix()
        self._assert_dependencies_are_running()
        self.product, self.review_count = self._real_product_fixture()
        self.build_image = (
            os.environ.get("MANDATE25_REBUILD_IMAGE", "").lower()
            in _TRUE_VALUES
        )

    def tearDown(self) -> None:
        try:
            self._write_evidence()
        finally:
            self._restore_healthy_service()

    def _path_from_env(self, name: str, default: str) -> Path:
        value = Path(os.environ.get(name, default))
        if not value.is_absolute():
            value = self.repo_root / value
        return value.resolve()

    def _load_compose_env_values(self) -> dict[str, str]:
        """Read simple key/value entries from the same env files Compose uses.

        The test passes its Bedrock settings through the Compose process
        environment. Loading these values first means developers can tune the
        baseline settings in ``.env.override`` without the harness replacing
        them with hard-coded values. Shell variables still take precedence.
        """

        raw_env_files = os.environ.get("MANDATE25_ENV_FILES", "")
        env_files = (
            [Path(item) for item in raw_env_files.split(os.pathsep) if item]
            if raw_env_files
            else [Path(".env"), Path(".env.override")]
        )
        values: dict[str, str] = {}
        for env_file in env_files:
            path = env_file if env_file.is_absolute() else self.repo_root / env_file
            if not path.is_file():
                continue
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key and key.replace("_", "").isalnum():
                    values[key] = value.strip().strip("\"'")
        return values

    def _load_grpc_contracts(self) -> None:
        common_src = self.repo_root / "src" / "ai-common"
        sys.path.insert(0, str(common_src))
        try:
            import grpc
            from grpc_health.v1 import health_pb2, health_pb2_grpc
            from techx_ai_common.proto import demo_pb2, demo_pb2_grpc
        except ImportError as exc:
            self.fail(
                "Install src/shopping-copilot/requirements.txt before running "
                f"this live flow: {exc}"
            )
        self.grpc = grpc
        self.health_pb2 = health_pb2
        self.health_pb2_grpc = health_pb2_grpc
        self.demo_pb2 = demo_pb2
        self.demo_pb2_grpc = demo_pb2_grpc

    def _required_float(self, name: str) -> float:
        value = self.base_env.get(name, self.compose_env_values.get(name))
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self.fail(
                f"Set {name} to a positive number in .env.override or the shell."
            )

    def _build_compose_prefix(self) -> list[str]:
        if shutil.which("docker") is None:
            self.fail("Docker CLI was not found on PATH.")
        if not self.compose_file.is_file():
            self.fail(f"Compose file does not exist: {self.compose_file}")

        raw_env_files = os.environ.get("MANDATE25_ENV_FILES", "")
        if raw_env_files:
            env_files = [
                Path(item) for item in raw_env_files.split(os.pathsep) if item
            ]
        else:
            env_files = [Path(".env"), Path(".env.override")]

        prefix = ["docker", "compose"]
        for env_file in env_files:
            path = (
                env_file
                if env_file.is_absolute()
                else self.repo_root / env_file
            )
            if path.is_file():
                prefix.extend(["--env-file", str(path.resolve())])
        prefix.extend(["--file", str(self.compose_file)])
        return prefix

    def _compose(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        timeout: float = 600,
    ) -> subprocess.CompletedProcess[str]:
        command = [*self.compose_prefix, *args]
        try:
            return subprocess.run(
                command,
                cwd=self.repo_root,
                env=env or self.base_env,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            self.fail(
                f"Docker Compose command failed: {' '.join(command)}\n{detail}"
            )
        except subprocess.TimeoutExpired:
            self.fail(
                f"Docker Compose command exceeded {timeout:.0f}s: "
                f"{' '.join(command)}"
            )

    def _phase_env(self, **overrides: str) -> dict[str, str]:
        env = self.base_env.copy()
        missing = []
        for name in self._REQUIRED_COMMON_ENV:
            value = self.base_env.get(name, self.compose_env_values.get(name))
            if value is None:
                missing.append(name)
            else:
                env[name] = value
        if missing:
            self.fail(
                "Set these required Mandate #25 values in .env.override or "
                "the shell environment: "
                + ", ".join(missing)
            )
        env.update(overrides)
        return env

    def _incident_env(self, scenario: str) -> dict[str, str]:
        """Build runtime environment from the public scenario input."""

        incident = SCENARIO_CONFIGS[scenario]
        return self._phase_env(
            **{str(name): str(value) for name, value in incident.items()}
        )

    def _assert_dependencies_are_running(self) -> None:
        result = self._compose("ps", "--services", "--status", "running")
        running = set(result.stdout.split())
        missing = sorted(self._REQUIRED_SERVICES - running)
        self.assertFalse(
            missing,
            "Start the real Compose stack before this test. "
            f"Missing services: {', '.join(missing)}",
        )

    def _recreate_copilot(
        self,
        env: dict[str, str],
        *,
        build: bool = False,
    ) -> str:
        args = [
            "up",
            "--detach",
            "--no-deps",
            "--force-recreate",
        ]
        if build:
            args.append("--build")
        args.append("shopping-copilot")
        self._compose(*args, env=env)
        self._service_was_recreated = True
        self._recreated_service_name = "shopping-copilot"
        address = self._published_address(
            "shopping-copilot",
            int(os.environ.get("MANDATE25_COPILOT_CONTAINER_PORT", "3552")),
            override_name="MANDATE25_COPILOT_ADDR",
        )
        self._wait_for_health(address)
        return address

    def _recreate_product_reviews(
        self,
        env: dict[str, str],
        *,
        build: bool = False,
    ) -> str:
        args = [
            "up",
            "--detach",
            "--no-deps",
            "--force-recreate",
        ]
        if build:
            args.append("--build")
        args.append("product-reviews")
        self._compose(*args, env=env)
        self._service_was_recreated = True
        self._recreated_service_name = "product-reviews"
        address = self._published_address(
            "product-reviews",
            int(os.environ.get("MANDATE25_REVIEWS_CONTAINER_PORT", "3551")),
            override_name="MANDATE25_REVIEWS_ADDR",
        )
        self._wait_for_health(address)
        return address

    def _published_address(
        self,
        service: str,
        container_port: int,
        *,
        override_name: str,
    ) -> str:
        override = os.environ.get(override_name, "").strip()
        if override:
            return override
        result = self._compose("port", service, str(container_port))
        bindings = [
            line.strip() for line in result.stdout.splitlines() if line.strip()
        ]
        self.assertTrue(
            bindings,
            f"Compose did not publish {service} port {container_port}.",
        )
        binding = next(
            (line for line in bindings if line.startswith("0.0.0.0:")),
            bindings[0],
        )
        try:
            port = int(binding.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            self.fail(f"Could not parse published address: {binding!r}")
        return f"127.0.0.1:{port}"

    def _wait_for_health(self, address: str) -> None:
        deadline = time.monotonic() + self.service_start_timeout_seconds
        last_error = "no health response"
        while time.monotonic() < deadline:
            channel = self.grpc.insecure_channel(address)
            try:
                response = self.health_pb2_grpc.HealthStub(channel).Check(
                    self.health_pb2.HealthCheckRequest(service=""),
                    timeout=2,
                )
                if (
                    response.status
                    == self.health_pb2.HealthCheckResponse.SERVING
                ):
                    return
                last_error = f"health status {response.status}"
            except self.grpc.RpcError as exc:
                last_error = f"{exc.code().name}: {exc.details()}"
            finally:
                channel.close()
            time.sleep(0.5)
        self.fail(
            f"Service at {address} did not become ready: {last_error}"
        )

    def _search(
        self,
        address: str,
        message: str,
        *,
        user_id: str,
        conversation_id: str,
    ) -> tuple[Any, float]:
        channel = self.grpc.insecure_channel(address)
        started = time.perf_counter()
        try:
            response = self.demo_pb2_grpc.ShoppingCopilotServiceStub(
                channel
            ).Search(
                self.demo_pb2.CopilotSearchRequest(
                    user_message=message,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=str(uuid.uuid4()),
                ),
                timeout=self.rpc_timeout_seconds,
            )
        except self.grpc.RpcError as exc:
            self.fail(
                "Shopping Copilot returned an RPC failure instead of a "
                f"controlled response: {exc.code().name}: {exc.details()}"
            )
        finally:
            channel.close()
        return response, time.perf_counter() - started

    def _assert_safe_fallback(
        self,
        response: Any,
        elapsed_seconds: float,
        *,
        latency_limit_seconds: float | None = None,
    ) -> None:
        self.assertEqual(response.status, "FALLBACK")
        self.assertIn("temporarily unavailable", response.reason.lower())
        self.assertEqual(list(response.products), [])
        self.assertEqual(list(response.claims), [])
        self.assertEqual(list(response.sources), [])
        self.assertEqual(response.interpreted_criteria, "")
        self.assertEqual(response.pending_action_token, "")
        self.assertLess(
            elapsed_seconds,
            latency_limit_seconds or self.fallback_latency_limit_seconds,
            "The fallback exceeded its bounded latency budget.",
        )

    def _cart_snapshot(self, address: str, user_id: str) -> list[tuple[str, int]]:
        channel = self.grpc.insecure_channel(address)
        try:
            cart = self.demo_pb2_grpc.CartServiceStub(channel).GetCart(
                self.demo_pb2.GetCartRequest(user_id=user_id),
                timeout=5,
            )
        finally:
            channel.close()
        return sorted((item.product_id, item.quantity) for item in cart.items)

    def _real_product_fixture(self) -> tuple[Any, int]:
        catalog_address = self._published_address(
            "product-catalog",
            int(os.environ.get("MANDATE25_CATALOG_CONTAINER_PORT", "3550")),
            override_name="MANDATE25_CATALOG_ADDR",
        )
        reviews_address = self._published_address(
            "product-reviews",
            int(os.environ.get("MANDATE25_REVIEWS_CONTAINER_PORT", "3551")),
            override_name="MANDATE25_REVIEWS_ADDR",
        )

        catalog_channel = self.grpc.insecure_channel(catalog_address)
        try:
            products = (
                self.demo_pb2_grpc.ProductCatalogServiceStub(catalog_channel)
                .ListProducts(self.demo_pb2.Empty(), timeout=5)
                .products
            )
            self.assertTrue(products, "The real Product Catalog returned no products.")
        finally:
            catalog_channel.close()

        reviews_channel = self.grpc.insecure_channel(reviews_address)
        try:
            reviews_stub = self.demo_pb2_grpc.ProductReviewServiceStub(
                reviews_channel
            )
            product = None
            reviews = None
            for candidate in products:
                candidate_reviews = reviews_stub.GetProductReviews(
                    self.demo_pb2.GetProductReviewsRequest(
                        product_id=candidate.id
                    ),
                    timeout=5,
                )
                if candidate_reviews.product_reviews:
                    product = candidate
                    reviews = candidate_reviews
                    break
            self.assertIsNotNone(
                product,
                "The real Product Reviews service returned no reviews for any "
                "catalog product.",
            )
            self.assertIsNotNone(reviews)
        finally:
            reviews_channel.close()
        return product, len(reviews.product_reviews)

    def _record(
        self,
        scenario: str,
        response: Any,
        elapsed_seconds: float,
        **extra: Any,
    ) -> None:
        row = {
            "scenario": scenario,
            "status": response.status,
            "latency_ms": round(elapsed_seconds * 1000, 2),
            "product_count": len(getattr(response, "products", [])),
            "claim_count": len(getattr(response, "claims", [])),
            "pending_action": bool(
                getattr(response, "pending_action_token", "")
            ),
            **extra,
        }
        self.evidence.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    def _write_evidence(self) -> None:
        destination = os.environ.get("MANDATE25_EVIDENCE_FILE", "").strip()
        if not destination:
            return
        path = Path(destination)
        if not path.is_absolute():
            path = self.repo_root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {}
        if path.is_file():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(current, dict):
                    payload.update(current)
            except (OSError, json.JSONDecodeError):
                pass
        payload[self.id()] = self.evidence
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Evidence written to {path}", flush=True)

    def _restore_healthy_service(self) -> None:
        if not self._service_was_recreated:
            return
        healthy_env = self._phase_env(
            BEDROCK_FAULT_INJECTION_ENABLED="false",
            BEDROCK_FAULT_WORKFLOW_STEP="",
            BEDROCK_FAULT_SEQUENCE="",
        )
        try:
            if self._recreated_service_name == "product-reviews":
                address = self._recreate_product_reviews(
                    healthy_env,
                    build=self.build_image,
                )
            else:
                address = self._recreate_copilot(
                    healthy_env,
                    build=self.build_image,
                )
            print(
                f"Restored {self._recreated_service_name or 'service'} "
                f"without fault injection at {address}.",
                flush=True,
            )
        except BaseException as exc:
            print(
                "WARNING: Could not restore the target service after the "
                f"live flow: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    def _shopping_request(self) -> str:
        return (
            f"Find a product like {self.product.name} for less than $200."
        )

    def _review_request(self) -> str:
        return f"What do customers say about {self.product.name}?"

    def _ask_product_review(
        self,
        address: str,
        question: str,
    ) -> tuple[Any, dict[str, Any], float]:
        channel = self.grpc.insecure_channel(address)
        started = time.perf_counter()
        try:
            response = (
                self.demo_pb2_grpc.ProductReviewServiceStub(channel)
                .AskProductAIAssistant(
                    self.demo_pb2.AskProductAIAssistantRequest(
                        product_id=self.product.id,
                        question=question,
                    ),
                    timeout=self.rpc_timeout_seconds,
                )
            )
        except self.grpc.RpcError as exc:
            self.fail(
                "Product Reviews returned an RPC failure instead of a "
                f"controlled response: {exc.code().name}: {exc.details()}"
            )
        finally:
            channel.close()
        try:
            payload = json.loads(response.response)
        except (TypeError, json.JSONDecodeError) as exc:
            self.fail(f"Product Reviews returned invalid JSON payload: {exc}")
        return response, payload, time.perf_counter() - started

    def _assert_review_fallback(
        self,
        response: Any,
        payload: dict[str, Any],
        elapsed_seconds: float,
    ) -> None:
        self.assertEqual(response.status, "FALLBACK")
        self.assertEqual(payload.get("status"), "FALLBACK")
        self.assertIn("temporarily unavailable", response.reason.lower())
        self.assertIn("temporarily unavailable", payload.get("reason", "").lower())
        self.assertEqual(list(response.claims), [])
        self.assertEqual(payload.get("claims"), [])
        self.assertLess(
            elapsed_seconds,
            self.product_review_fallback_latency_limit_seconds,
            "The Product Reviews fallback exceeded its bounded latency budget.",
        )

    def _assert_review_success(
        self,
        response: Any,
        payload: dict[str, Any],
        elapsed_seconds: float,
    ) -> None:
        self.assertIn(
            response.status,
            {"GROUNDED", "ABSTAINED"},
            "Product Reviews did not recover to a valid grounded/abstained response.",
        )
        self.assertEqual(payload.get("status"), response.status)
        self.assertLess(
            elapsed_seconds,
            self.rpc_timeout_seconds,
            "The Product Reviews request exceeded the RPC deadline.",
        )
        if response.status == "GROUNDED":
            self.assertTrue(list(response.claims), "Grounded response has no claims.")
            for claim in response.claims:
                self.assertTrue(
                    list(claim.source_ids),
                    "Every grounded review claim must cite a source.",
                )


@unittest.skipUnless(
    _LIVE_REQUESTED,
    "Set RUN_MANDATE25_LIVE=1 to run real-service Bedrock scenarios.",
)
class ShoppingCopilotMandate25Tests(Mandate25LiveBase):
    """Inject Mandate #25 incidents into the Shopping Copilot pipeline."""

    def _assert_copilot_success(
        self,
        response: Any,
        elapsed_seconds: float,
    ) -> None:
        self.assertIn(
            response.status,
            {"GROUNDED", "NO_RESULTS", "ABSTAINED"},
            "Shopping Copilot did not return a valid recovered response.",
        )
        self.assertLess(
            elapsed_seconds,
            self.rpc_timeout_seconds,
            "Shopping Copilot exceeded the RPC deadline.",
        )

    def test_01_single_provider_failure_falls_back(self) -> None:
        """One provider error returns a bounded, safe fallback."""

        provider_env = self._incident_env(
            "shopping-copilot/provider-failure"
        )
        address = self._recreate_copilot(
            provider_env,
            build=self.build_image,
        )
        user_id = f"mandate25-provider-{uuid.uuid4()}"
        incident, incident_latency = self._search(
            address,
            self._shopping_request(),
            user_id=user_id,
            conversation_id=str(uuid.uuid4()),
        )
        self._assert_safe_fallback(incident, incident_latency)
        self._record(
            "shopping_copilot_single_provider_failure",
            incident,
            incident_latency,
            surface="shopping-copilot",
            workflow_step="retrieval_hint",
            fault_sequence=provider_env["BEDROCK_FAULT_SEQUENCE"],
            configured_attempts=int(provider_env["BEDROCK_MAX_ATTEMPTS"]),
            output_valid=True,
        )

    def test_02_sustained_failure_opens_breaker_then_recovers(self) -> None:
        """A failure chain opens the breaker; a half-open probe recovers."""

        # Six timeouts exhaust three logical calls. The trailing "pass" proves
        # the next request cannot consume the plan while the breaker is OPEN.
        breaker_env = self._incident_env(
            "shopping-copilot/sustained-failure"
        )
        address = self._recreate_copilot(
            breaker_env,
            build=self.build_image,
        )

        def invoke_breaker_request() -> tuple[Any, float]:
            return self._search(
                address,
                self._shopping_request(),
                user_id=f"mandate25-breaker-{uuid.uuid4()}",
                conversation_id=str(uuid.uuid4()),
            )

        failure_threshold = int(
            breaker_env["BEDROCK_BREAKER_FAILURE_THRESHOLD"]
        )
        for index in range(1, failure_threshold + 1):
            failed, failed_latency = invoke_breaker_request()
            self._assert_safe_fallback(failed, failed_latency)
            self._record(
                f"shopping_copilot_sustained_failure_{index}",
                failed,
                failed_latency,
                surface="shopping-copilot",
                failure_threshold=failure_threshold,
                output_valid=True,
            )

        rejected, rejected_latency = invoke_breaker_request()
        self._assert_safe_fallback(rejected, rejected_latency)
        self._record(
            "shopping_copilot_open_breaker_rejection",
            rejected,
            rejected_latency,
            surface="shopping-copilot",
            next_fault_plan_outcome="pass_not_consumed",
            output_valid=True,
        )

        time.sleep(float(breaker_env["BEDROCK_BREAKER_RECOVERY_SECONDS"]) + 0.5)
        recovered, recovery_latency = invoke_breaker_request()
        self._assert_copilot_success(recovered, recovery_latency)
        self._record(
            "shopping_copilot_half_open_recovery",
            recovered,
            recovery_latency,
            surface="shopping-copilot",
            bedrock_call="real",
            output_valid=True,
        )

    def test_03_malformed_tool_call_is_blocked(self) -> None:
        """One malformed tool call cannot create or execute a cart action."""

        malformed_env = self._incident_env(
            "shopping-copilot/malformed-tool-call"
        )
        address = self._recreate_copilot(
            malformed_env,
            build=self.build_image,
        )
        cart_address = self._published_address(
            "cart",
            int(os.environ.get("MANDATE25_CART_CONTAINER_PORT", "7070")),
            override_name="MANDATE25_CART_ADDR",
        )
        cart_user = f"mandate25-garbage-{uuid.uuid4()}"
        cart_before = self._cart_snapshot(cart_address, cart_user)

        malformed, malformed_latency = self._search(
            address,
            f"Add one {self.product.name} to my cart.",
            user_id=cart_user,
            conversation_id=str(uuid.uuid4()),
        )
        self._assert_safe_fallback(
            malformed,
            malformed_latency,
        )
        cart_after = self._cart_snapshot(cart_address, cart_user)
        self.assertEqual(
            cart_after,
            cart_before,
            "Malformed model arguments changed the real cart.",
        )
        self.assertEqual(
            malformed.pending_action_token,
            "",
            "Malformed model arguments created a pending cart action.",
        )
        self._record(
            "shopping_copilot_malformed_tool_call_blocked",
            malformed,
            malformed_latency,
            surface="shopping-copilot",
            cart_unchanged=True,
            pending_action_created=False,
            real_catalog_product=self.product.name,
            real_review_count=self.review_count,
            output_valid=True,
        )

@unittest.skipUnless(
    _LIVE_REQUESTED,
    "Set RUN_MANDATE25_LIVE=1 to run real-service Bedrock scenarios.",
)
class ProductReviewMandate25Tests(Mandate25LiveBase):
    """Inject Mandate #25 incidents into the Product Review pipeline."""

    def test_01_single_provider_failure_falls_back(self) -> None:
        """One provider error returns a bounded, safe fallback."""

        provider_env = self._incident_env(
            "product-reviews/provider-failure"
        )
        address = self._recreate_product_reviews(
            provider_env,
            build=self.build_image,
        )
        question = self._review_request()
        incident, incident_payload, incident_latency = self._ask_product_review(
            address,
            question,
        )
        self._assert_review_fallback(
            incident,
            incident_payload,
            incident_latency,
        )
        self._record(
            "product_review_single_provider_failure",
            incident,
            incident_latency,
            surface="product-reviews",
            workflow_step="grounded_summary",
            fault_sequence=provider_env["BEDROCK_FAULT_SEQUENCE"],
            configured_attempts=int(provider_env["BEDROCK_MAX_ATTEMPTS"]),
            real_review_count=self.review_count,
            output_valid=True,
        )

    def test_02_sustained_failure_opens_breaker_then_recovers(self) -> None:
        """A failure chain opens the breaker; a half-open probe recovers."""

        breaker_env = self._incident_env(
            "product-reviews/sustained-failure"
        )
        address = self._recreate_product_reviews(
            breaker_env,
            build=self.build_image,
        )
        question = self._review_request()

        failure_threshold = int(
            breaker_env["BEDROCK_BREAKER_FAILURE_THRESHOLD"]
        )
        for index in range(1, failure_threshold + 1):
            failed, failed_payload, failed_latency = self._ask_product_review(
                address,
                question,
            )
            self._assert_review_fallback(
                failed,
                failed_payload,
                failed_latency,
            )
            self._record(
                f"product_review_sustained_failure_{index}",
                failed,
                failed_latency,
                surface="product-reviews",
                failure_threshold=failure_threshold,
                workflow_step="grounded_summary",
                output_valid=True,
            )

        rejected, rejected_payload, rejected_latency = self._ask_product_review(
            address,
            question,
        )
        self._assert_review_fallback(
            rejected,
            rejected_payload,
            rejected_latency,
        )
        self._record(
            "product_review_open_breaker_rejection",
            rejected,
            rejected_latency,
            surface="product-reviews",
            next_fault_plan_outcome="pass_not_consumed",
            output_valid=True,
        )

        time.sleep(float(breaker_env["BEDROCK_BREAKER_RECOVERY_SECONDS"]) + 0.5)
        recovered, recovered_payload, recovery_latency = self._ask_product_review(
            address,
            question,
        )
        self._assert_review_success(
            recovered,
            recovered_payload,
            recovery_latency,
        )
        self._record(
            "product_review_half_open_recovery",
            recovered,
            recovery_latency,
            surface="product-reviews",
            bedrock_call="real",
            workflow_step="grounded_summary",
            output_valid=True,
        )

    def test_03_malformed_json_is_rejected_then_recovers(self) -> None:
        """One malformed JSON output is rejected; schema retry recovers safely."""

        malformed_env = self._incident_env(
            "product-reviews/malformed-json"
        )
        address = self._recreate_product_reviews(
            malformed_env,
            build=self.build_image,
        )
        response, payload, latency = self._ask_product_review(
            address,
            self._review_request(),
        )
        self._assert_review_success(response, payload, latency)
        self._record(
            "product_review_malformed_json_rejected_then_recovered",
            response,
            latency,
            surface="product-reviews",
            injected_fault="malformed_json",
            workflow_step="grounded_summary",
            configured_schema_attempts=int(
                malformed_env["BEDROCK_SCHEMA_MAX_ATTEMPTS"]
            ),
            schema_recovery=True,
            bedrock_call_after_rejection="real",
            output_valid=True,
        )


def _print_scenario_inputs(selected: str | None = None) -> None:
    """Print JSON that can be copied into a manual pipeline test."""

    if selected is None:
        payload: Any = SCENARIO_CONFIGS
    else:
        try:
            payload = SCENARIO_CONFIGS[selected]
        except KeyError:
            choices = ", ".join(sorted(SCENARIO_CONFIGS))
            raise SystemExit(
                f"Unknown scenario {selected!r}. Choose one of: {choices}"
            )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] == ["--list-scenarios"]:
        _print_scenario_inputs()
    elif len(sys.argv) == 3 and sys.argv[1] == "--show-input":
        _print_scenario_inputs(sys.argv[2])
    else:
        unittest.main(verbosity=2)
