#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from aiops.schemas import AnomalyFinding, RuntimeConfig
from aiops.topology import TopologyGraph


class GraphTraversalRca:
    def __init__(
        self,
        config: RuntimeConfig,
        damping: float,
        pagerank_weight: float,
        timestamp_weight: float,
        topology_graph: TopologyGraph | None = None,
    ):
        self.topology_graph = topology_graph or TopologyGraph(config)
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

        pagerank = self.topology_graph.personalized_pagerank(seed_scores, self.damping)
        timestamp_scores = self._timestamp_scores(timestamps)
        max_seed = max(seed_scores.values())
        combined = {
            service: max_seed * (self.pagerank_weight * pagerank.get(service, 0.0) + self.timestamp_weight * timestamp_scores.get(service, 0.0))
            for service in pagerank.keys() | timestamp_scores.keys()
            if pagerank.get(service, 0.0) or timestamp_scores.get(service, 0.0)
        }
        return dict(sorted(combined.items(), key=lambda item: item[1], reverse=True))

    def _timestamp_scores(self, timestamps: dict[str, int]) -> dict[str, float]:
        newest = max(timestamps.values())
        oldest = min(timestamps.values())
        if newest == oldest:
            return {service: 1.0 for service in timestamps}
        return {service: (timestamp - oldest) / (newest - oldest) for service, timestamp in timestamps.items()}
