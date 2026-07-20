from __future__ import annotations

from hashlib import sha256

from aiops.schemas import CandidateEvent


def incident_fingerprint(environment: str, candidate: CandidateEvent) -> str:
    stable_parts = [
        environment,
        candidate.detector_id,
        candidate.flow,
        candidate.service,
        candidate.likely_dependency,
    ]
    if candidate.detector_id == "rca_root_cause":
        stable_parts.append(candidate.signal_id)
    return f"sha256:{sha256('|'.join(stable_parts).encode('utf-8')).hexdigest()}"
