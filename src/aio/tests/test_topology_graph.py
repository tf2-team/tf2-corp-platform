#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path

import networkx as nx

from aiops.config import load_runtime_config
from aiops.topology import TopologyGraph


class TopologyGraphTest(unittest.TestCase):
    def setUp(self):
        self.config = load_runtime_config(Path("config/runtime.json"))
        self.topology = TopologyGraph(self.config)

    def test_builds_directed_networkx_graph_with_service_metadata(self):
        self.assertIsInstance(self.topology.graph, nx.DiGraph)
        self.assertTrue(self.topology.is_direct_dependency("checkout", "payment"))
        self.assertFalse(self.topology.is_direct_dependency("payment", "checkout"))
        self.assertEqual(self.topology.graph.nodes["otel-collector"]["kind"], "DaemonSet")
        self.assertEqual(self.topology.graph.nodes["kafka"]["kind"], "ManagedService")

    def test_current_production_services_and_dependencies_are_present(self):
        expected_dependencies = {
            "accounting": {"kafka", "postgresql"},
            "fraud-detection": {"flagd", "kafka", "valkey-cart"},
            "product-reviews": {"product-catalog", "postgresql", "flagd", "llm", "external-llm"},
            "shopping-copilot": {"product-catalog", "product-reviews", "cart", "valkey-cart", "aws-bedrock"},
        }
        for service, dependencies in expected_dependencies.items():
            self.assertIn(service, self.topology.graph)
            self.assertEqual(set(self.topology.graph.successors(service)), dependencies)

    def test_dependency_distance_supports_direct_and_transitive_paths(self):
        self.assertEqual(self.topology.dependency_distance("frontend", "shipping"), 1)
        self.assertEqual(self.topology.dependency_distance("frontend", "quote"), 2)
        self.assertIsNone(self.topology.dependency_distance("frontend", "quote", max_hops=1))
        self.assertIsNone(self.topology.dependency_distance("quote", "frontend"))

    def test_blast_radius_walks_callers_without_unrelated_sibling_dependencies(self):
        self.assertEqual(self.topology.blast_radius("payment", max_hops=1), {"payment", "checkout"})
        self.assertEqual(self.topology.blast_radius("payment", max_hops=2), {"payment", "checkout", "frontend"})
        self.assertNotIn("cart", self.topology.blast_radius("payment", max_hops=2))

    def test_neighborhood_walks_dependencies_and_callers(self):
        neighborhood = self.topology.neighborhood("checkout", max_hops=1)

        self.assertIn("payment", neighborhood)
        self.assertIn("frontend", neighborhood)

    def test_pagerank_handles_cycles_and_unknown_observed_services(self):
        graph = nx.DiGraph(self.topology.graph)
        graph.add_edge("payment", "checkout")
        nx.freeze(graph)
        self.topology.graph = graph

        scores = self.topology.personalized_pagerank({"checkout": 1.0, "unmapped-service": 0.5}, damping=0.85)

        self.assertIn("unmapped-service", scores)
        self.assertAlmostEqual(sum(scores.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
