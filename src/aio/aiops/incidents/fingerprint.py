#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from aiops.schemas import CandidateEvent


class TopologyLike(Protocol):
    def has_dependency_path(self, service: str, dependency: str, max_hops: int | None = None) -> bool:
        ...


def incident_fingerprint(environment: str, candidate: CandidateEvent, topology_graph: TopologyLike | None = None) -> str:
    scope = f"service:{candidate.service}"
    if (
        topology_graph is not None
        and candidate.likely_dependency != "unknown"
        and topology_graph.has_dependency_path(candidate.service, candidate.likely_dependency)
    ):
        scope = f"dependency:{candidate.likely_dependency}"
    stable_parts = [
        environment,
        candidate.detector_id,
        candidate.flow,
        scope,
        candidate.likely_dependency,
    ]
    if candidate.detector_id == "rca_root_cause":
        stable_parts.append(candidate.signal_id)
    return f"sha256:{sha256('|'.join(stable_parts).encode('utf-8')).hexdigest()}"
