#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from aiops.schemas import AnomalyFinding, RuntimeConfig


class GraphTraversalRca:
    def __init__(self, config: RuntimeConfig, damping: float, pagerank_weight: float, timestamp_weight: float):
        self.config = config
        self.damping = damping
        self.pagerank_weight = pagerank_weight
        self.timestamp_weight = timestamp_weight

    def rank_services(self, findings: list[AnomalyFinding]) -> dict[str, float]:
        seed_scores: dict[str, float] = {}
        timestamps: dict[str, int] = {}
        for finding in findings:
            if finding.service == "global":
                continue
            seed_scores[finding.service] = max(seed_scores.get(finding.service, 0.0), finding.score)
            timestamps[finding.service] = max(timestamps.get(finding.service, finding.timestamp), finding.timestamp)
        if not seed_scores:
            return {}

        graph = {item.name: item.dependencies for item in self.config.topology.services}
        for service in seed_scores:
            graph.setdefault(service, [])
        pagerank = self._pagerank(graph, seed_scores)
        timestamp_scores = self._timestamp_scores(timestamps)
        max_seed = max(seed_scores.values())
        combined = {
            service: max_seed * (self.pagerank_weight * pagerank.get(service, 0.0) + self.timestamp_weight * timestamp_scores.get(service, 0.0))
            for service in graph
            if pagerank.get(service, 0.0) or timestamp_scores.get(service, 0.0)
        }
        return dict(sorted(combined.items(), key=lambda item: item[1], reverse=True))

    def _pagerank(self, graph: dict[str, list[str]], seed_scores: dict[str, float]) -> dict[str, float]:
        total_seed = sum(seed_scores.values())
        personalization = {service: seed_scores.get(service, 0.0) / total_seed for service in graph}
        rank = personalization.copy()
        for _ in range(20):
            next_rank = {service: (1 - self.damping) * personalization[service] for service in graph}
            for service, dependencies in graph.items():
                targets = [dependency for dependency in dependencies if dependency in graph] or list(graph)
                share = self.damping * rank[service] / len(targets)
                for target in targets:
                    next_rank[target] += share
            rank = next_rank
        return rank

    def _timestamp_scores(self, timestamps: dict[str, int]) -> dict[str, float]:
        newest = max(timestamps.values())
        oldest = min(timestamps.values())
        if newest == oldest:
            return {service: 1.0 for service in timestamps}
        return {service: (timestamp - oldest) / (newest - oldest) for service, timestamp in timestamps.items()}
