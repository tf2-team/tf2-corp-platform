#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import networkx as nx

from aiops.schemas import RuntimeConfig


class TopologyGraph:
    """Immutable service-to-dependency graph shared by correlation and RCA."""

    def __init__(self, config: RuntimeConfig):
        graph = nx.DiGraph()
        for service in config.topology.services:
            graph.add_node(
                service.name,
                namespace=service.namespace,
                kind=service.kind,
                owner=service.owner,
                flow=service.flow,
            )
        for service in config.topology.services:
            for dependency in service.dependencies:
                graph.add_edge(service.name, dependency, relationship="dependency")
        self.graph = nx.freeze(graph)

    def contains(self, service: str) -> bool:
        return service in self.graph

    def is_direct_dependency(self, service: str, dependency: str) -> bool:
        return self.graph.has_edge(service, dependency)

    def dependency_distance(self, service: str, dependency: str, max_hops: int | None = None) -> int | None:
        if service not in self.graph or dependency not in self.graph:
            return None
        try:
            distance = nx.shortest_path_length(self.graph, service, dependency)
        except nx.NetworkXNoPath:
            return None
        return distance if max_hops is None or distance <= max_hops else None

    def has_dependency_path(self, service: str, dependency: str, max_hops: int | None = None) -> bool:
        return self.dependency_distance(service, dependency, max_hops) is not None

    def blast_radius(self, root_service: str, max_hops: int = 2) -> set[str]:
        if root_service not in self.graph:
            return {root_service}
        reverse_graph = self.graph.reverse(copy=False)
        return set(nx.single_source_shortest_path_length(reverse_graph, root_service, cutoff=max_hops))

    def neighborhood(self, service: str, max_hops: int = 1) -> set[str]:
        if service not in self.graph:
            return {service}
        graph = self.graph.to_undirected(as_view=True)
        return set(nx.single_source_shortest_path_length(graph, service, cutoff=max_hops))

    def personalized_pagerank(self, seed_scores: dict[str, float], damping: float) -> dict[str, float]:
        if not seed_scores:
            return {}
        graph = nx.DiGraph(self.graph)
        graph.add_nodes_from(service for service in seed_scores if service not in graph)
        total_seed = sum(seed_scores.values())
        if total_seed <= 0:
            return {}
        personalization = {service: seed_scores.get(service, 0.0) / total_seed for service in graph}
        uniform_dangling = {service: 1.0 / len(graph) for service in graph}
        return nx.pagerank(
            graph,
            alpha=damping,
            personalization=personalization,
            dangling=uniform_dangling,
            max_iter=100,
            tol=1.0e-8,
        )
