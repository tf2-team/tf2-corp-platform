from __future__ import annotations

from collections import deque

from aiops.schemas import AnomalyFinding, RuntimeConfig


class GraphTraversalRca:
    def __init__(self, config: RuntimeConfig):
        self.config = config

    def rank_services(self, findings: list[AnomalyFinding]) -> dict[str, float]:
        seed_scores: dict[str, float] = {}
        for finding in findings:
            if finding.service == "global":
                continue
            seed_scores[finding.service] = max(seed_scores.get(finding.service, 0.0), finding.score)

        ranked: dict[str, float] = dict(seed_scores)
        for service, score in seed_scores.items():
            for dependency, distance in self._dependencies(service).items():
                ranked[dependency] = max(ranked.get(dependency, 0.0), score / (distance + 1))
        return dict(sorted(ranked.items(), key=lambda item: item[1], reverse=True))

    def _dependencies(self, service: str) -> dict[str, int]:
        graph = {item.name: item.dependencies for item in self.config.topology.services}
        distances: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque((dependency, 1) for dependency in graph.get(service, []))
        while queue:
            node, distance = queue.popleft()
            if node in distances:
                continue
            distances[node] = distance
            queue.extend((dependency, distance + 1) for dependency in graph.get(node, []))
        return distances
