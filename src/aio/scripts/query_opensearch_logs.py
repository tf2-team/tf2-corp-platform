#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0
"""Inspect the real OpenSearch logs used by AIOps enrichment.

The script uses the production Settings and OpenSearchClient classes. It never
prints credentials. Log fields that commonly contain secrets are redacted
before output.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ENGINE_SERVICE_FIELDS = ["service.name", "k8s.deployment.name"]
ENGINE_TEXT_FIELDS = ["message", "body", "log"]
FAILURE_QUERY = "exception | timeout | failed | failure | connection refused | oom | retry exhausted"
SENSITIVE_KEY = re.compile(r"(?i)(authorization|cookie|password|passwd|token|secret|api[_-]?key)")
INLINE_SECRET = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key)=\S+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def parse_window(value: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([smhd])", value.strip())
    if not match:
        raise argparse.ArgumentTypeError("window must look like 30s, 5m, 1h, or 1d")
    amount = int(match.group(1))
    unit = match.group(2)
    return timedelta(seconds=amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit])


def parse_end(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("end must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def engine_evidence_query(service: str, start: datetime, end: datetime) -> dict[str, Any]:
    """Build the query used by Enricher._opensearch_evidence."""
    return {
        "bool": {
            "must": [
                {
                    "multi_match": {
                        "query": service,
                        "fields": ENGINE_SERVICE_FIELDS + ["message", "body"],
                    }
                },
                {"range": {"@timestamp": {"gte": iso_utc(start), "lte": iso_utc(end)}}},
            ]
        }
    }


def engine_corroboration_query(service: str, start: datetime, end: datetime) -> dict[str, Any]:
    """Build the log query used by Enricher._corroborate_service."""
    return {
        "bool": {
            "must": [
                {"multi_match": {"query": service, "fields": ENGINE_SERVICE_FIELDS}},
                {"simple_query_string": {"query": FAILURE_QUERY, "fields": ENGINE_TEXT_FIELDS}},
            ],
            "filter": [
                {"range": {"@timestamp": {"gte": iso_utc(start), "lte": iso_utc(end)}}}
            ],
        }
    }


def exact_service_query(service: str, start: datetime, end: datetime) -> dict[str, Any]:
    """Match the service field present in the current otel-logs mapping."""
    return {
        "bool": {
            "filter": [
                {"term": {"resource.service.name.keyword": service}},
                {"range": {"@timestamp": {"gte": iso_utc(start), "lte": iso_utc(end)}}},
            ]
        }
    }


def redact(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {item_key: redact(item_value, item_key) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = INLINE_SECRET.sub(r"\1=[REDACTED]", value)
        return EMAIL.sub("[REDACTED_EMAIL]", value)
    return value


def response_output(mode: str, query: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    hits = response.get("hits", {})
    total = hits.get("total", 0)
    if isinstance(total, dict):
        total_value = total.get("value", 0)
        total_relation = total.get("relation", "eq")
    else:
        total_value = total
        total_relation = "eq"
    return {
        "mode": mode,
        "query": query,
        "response": {
            "took_ms": response.get("took"),
            "timed_out": response.get("timed_out"),
            "shards": response.get("_shards"),
            "total_hits": total_value,
            "total_relation": total_relation,
            "returned_hits": len(hits.get("hits", [])),
        },
        "hits": [
            {
                "_index": hit.get("_index"),
                "_id": hit.get("_id"),
                "_score": hit.get("_score"),
                "_source": redact(hit.get("_source", {})),
            }
            for hit in hits.get("hits", [])
        ],
    }


def run_query(client: Any, index: str, mode: str, query: dict[str, Any], size: int) -> dict[str, Any]:
    response = client.search(
        index,
        {
            "size": size,
            "track_total_hits": True,
            "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
            "query": query,
        },
    )
    return response_output(mode, query, response)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query and safely print the real OpenSearch logs used by AIOps enrichment."
    )
    parser.add_argument("service", help="Service or dependency name used by the enrichment query")
    parser.add_argument(
        "--mode",
        choices=("engine-evidence", "engine-corroboration", "exact-service", "compare"),
        default="engine-evidence",
        help="Query to execute; compare runs engine-evidence and exact-service (default: engine-evidence)",
    )
    parser.add_argument("--window", type=parse_window, default=parse_window("5m"))
    parser.add_argument("--end", type=parse_end, default=None, help="ISO-8601 end time; default is now")
    parser.add_argument("--size", type=int, default=3, help="Maximum returned documents (default: 3)")
    parser.add_argument("--index", default="otel-logs-*", help="OpenSearch index pattern")
    args = parser.parse_args()

    if not 1 <= args.size <= 100:
        parser.error("--size must be between 1 and 100")

    from aiops.config import Settings
    from aiops.integrations import OpenSearchClient

    end = args.end or datetime.now(UTC)
    start = end - args.window
    builders = {
        "engine-evidence": engine_evidence_query,
        "engine-corroboration": engine_corroboration_query,
        "exact-service": exact_service_query,
    }
    modes = ("engine-evidence", "exact-service") if args.mode == "compare" else (args.mode,)
    client = OpenSearchClient(Settings())
    results = [
        run_query(
            client,
            args.index,
            mode,
            builders[mode](args.service, start, end),
            args.size,
        )
        for mode in modes
    ]
    output = {
        "service": args.service,
        "index": args.index,
        "window": {
            "start": iso_utc(start),
            "end": iso_utc(end),
        },
        "results": results,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
