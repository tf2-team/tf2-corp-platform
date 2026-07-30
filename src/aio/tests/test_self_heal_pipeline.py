#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiops.collectors import StaticCollector
from aiops.detectors import Detector
from aiops.detectors.base import candidate_from_feature
from aiops.pipeline import AiopsPipeline
from aiops.remediation import (
    ActionCatalog,
    HistoryRetriever,
    IncidentHistoryStore,
    PolicyEngine,
    RemediationAuditLog,
    RemediationDecisionEngine,
    RemediationFeatureExtractor,
    SelfHealConfig,
    SelfHealOrchestrator,
)
from aiops.schemas import Feature, Observation, SignalQuality
from aiops.storage import SQLiteIncidentStore


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class FakeExecutorClient:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def catalog(self, request_id: str | None = None) -> list[dict]:
        return [
            {
                "action_id": "scale_product_catalog",
                "action_type": "scale_deployment",
                "target": "product-catalog",
                "target_kind": "Deployment",
                "namespace": "techx-corp-prod",
                "executor_supported": True,
                "dry_run_supported": True,
                "execute_supported": True,
                "live_execute_supported": True,
                "live_apply_enabled": True,
                "recommendation_only": False,
                "audit_only": False,
                "blocked": False,
                "protected": False,
                "rollback_supported": True,
                "rollback_action_id": "restore_deployment_replicas",
                "verification_query_id": "product-catalog.cpu_millicores",
                "verification_signal_id": "product_catalog_cpu_millicores",
                "verification_max_ratio": 0.9,
                "policy_id": "phase3-scale-policy-v1",
                "policy_approval_required": True,
            }
        ]

    def plan(self, action: dict) -> dict:
        return {
            "allowed": True,
            "executed": False,
            "status": "planned",
            "plan_hash": "sha256:plan",
            "rollback": {"defined": True, "rollback_token": "rbt:one"},
        }

    def execute(self, action: dict) -> dict:
        return {
            "allowed": True,
            "executed": True,
            "status": "running",
            "execution_id": "exec-one",
            "executed_at": self.clock().isoformat(),
            "plan_hash": action["plan_hash"],
            "before": {"replicas": 2, "resource_version": "1"},
            "after": {"replicas": 3, "resource_version": "2"},
            "verification": {
                "defined": True,
                "query_id": "product-catalog.cpu_millicores",
            },
            "rollback": {"defined": True, "rollback_token": "rbt:one"},
        }

    def record_verification(self, execution_id: str, verification: dict) -> dict:
        return {
            "execution_id": execution_id,
            "status": "succeeded" if verification["passed"] else "failed",
        }

    def rollback(self, execution_id: str, request: dict) -> dict:
        return {
            "execution_id": execution_id,
            "status": "rolled_back",
            "executed": True,
        }


class ProductCatalogCpuDetector(Detector):
    def evaluate(self, features: list[Feature]):
        feature = next(item for item in features if item.signal_id == "product_catalog_cpu_millicores")
        if feature.value is None or feature.value <= 80:
            return []
        return [
            candidate_from_feature(
                feature,
                detector_id="product-catalog-cpu",
                flow="catalog",
                service="product-catalog",
                severity="SEV2",
                threshold=80,
                reason="cpu_saturation",
                runbook_id="RB-PRODUCT-CATALOG-CPU",
                confidence=0.95,
            )
        ]


def _observation(value: float, timestamp: datetime) -> Observation:
    return Observation(
        signal_id="product_catalog_cpu_millicores",
        value=value,
        unit="mCPU",
        window="5m",
        quality=SignalQuality.VERIFIED,
        labels={"sample_timestamp": str(timestamp.timestamp())},
    )


def test_detector_drives_execute_then_fresh_telemetry_closes_incident(tmp_path: Path) -> None:
    actions_path = tmp_path / "actions.json"
    history_path = tmp_path / "history.json"
    audit_path = tmp_path / "remediation.jsonl"
    actions_path.write_text(
        json.dumps(
            [
                {
                    "action_id": "scale_product_catalog",
                    "action_type": "scale_deployment",
                    "target": "product-catalog",
                    "target_kind": "Deployment",
                    "cost_min": 2,
                    "downtime_min": 0,
                    "blast_radius_services": ["frontend"],
                    "replicas": 3,
                    "verification_defined": True,
                    "verification_query_id": "product-catalog.cpu_millicores",
                    "verification_signal_id": "product_catalog_cpu_millicores",
                    "verification_max_ratio": 0.9,
                    "rollback_defined": True,
                    "rollback_action_id": "restore_deployment_replicas",
                    "rollback_supported": True,
                    "approved": True,
                    "policy_id": "phase3-scale-policy-v1",
                    "policy_approval_required": True,
                    "executor_supported": True,
                    "execute_supported": True,
                    "live_execute_supported": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    history_path.write_text(
        json.dumps(
            [
                {
                    "incident_id": "seed-product-catalog",
                    "affected_services": ["product-catalog"],
                    "log_signatures": ["cpu_saturation"],
                    "trace_signatures": [],
                    "metric_ratios": {"product_catalog_cpu_millicores": 1.5},
                    "actions_taken": [
                        {
                            "action_id": "scale_product_catalog",
                            "target": "product-catalog",
                            "outcome": "success",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    clock = Clock()
    store = SQLiteIncidentStore(tmp_path / "runtime.sqlite3", "techx-corp-prod")
    executor = FakeExecutorClient(clock)
    self_heal = SelfHealOrchestrator(
        executor,
        store,
        SelfHealConfig(
            namespace="techx-corp-prod",
            policy_id="phase3-scale-policy-v1",
            policy_expires_at="2026-08-31T23:59:59Z",
            approval_id="ADR-LIVE-001",
            protected_targets=frozenset({"payment", "postgresql"}),
            verification_deadline_seconds=180,
            min_fresh_samples=2,
            consecutive_passes=2,
            failure_samples=2,
            min_incident_occurrences=1,
        ),
        clock=clock,
    )
    collector = StaticCollector([_observation(120, clock())])
    pipeline = AiopsPipeline(
        collector=collector,
        detectors=[ProductCatalogCpuDetector()],
        store=store,
        policy=PolicyEngine(
            mode="live-approved",
            protected_targets={"payment", "postgresql"},
            stateful_kinds={"StatefulSet"},
            non_actionable_flows={"monitoring"},
            action_type="scale_deployment",
            target_kind="Deployment",
            default_replicas=3,
        ),
        remediation=(
            RemediationFeatureExtractor(),
            HistoryRetriever(
                weights={"service": 0.4, "log": 0.3, "trace": 0.0, "metric": 0.3},
                top_k=3,
                metric_similarity_epsilon=1.0e-9,
            ),
            RemediationDecisionEngine(
                ood_threshold=0.1,
                cost_page=100,
                blast_radius_limit=5,
                confidence_threshold=0.5,
                downtime_cost_multiplier=1,
                outcome_weights={"success": 1, "partial": 0.5, "failed": 0},
            ),
            ActionCatalog(actions_path),
            IncidentHistoryStore(history_path),
            RemediationAuditLog(audit_path),
        ),
        self_heal=self_heal,
    )
    try:
        first = pipeline.run_once()
        decision = first.remediation_decisions[0]
        assert decision.selected_action == "scale_product_catalog"
        assert decision.execution_status == "verifying"
        assert decision.would_execute is True
        assert first.policy_decisions[0].allowed is True
        assert first.policy_decisions[0].executed is True

        clock.advance(60)
        collector._observations = [_observation(70, clock())]
        second = pipeline.run_once()
        assert second.verification_results[0].status == "not_recovered"

        clock.advance(60)
        collector._observations = [_observation(60, clock())]
        third = pipeline.run_once()
        assert third.verification_results[0].status == "recovered"
        assert store.self_heal_workflow(first.incidents[0].incident_id)["status"] == "succeeded"
        assert store.list_incidents()[0].state == "recovered"
    finally:
        store.close()
