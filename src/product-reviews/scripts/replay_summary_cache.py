#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Replay script for Summary Bot cache validation (A1.3).

Sends AI assistant requests via gRPC with x-user-id / x-session-id metadata,
records cache_status for each call, and prints a hit/miss summary table.

Usage:
    python replay_summary_cache.py [--host HOST] [--port PORT] [--output FILE]

Requires AI_CACHE_ENABLED=true on the product-reviews service and a warm
valkey-ai-cache index (ai_summary_cache_idx).

Output JSONL (one record per request)::

    {"product_id": "...", "question": "...", "user_id": "...",
     "attempt": 1, "cache_status": "miss", "cache_match": "none",
     "latency_ms": 1234.5, "response_status": "GROUNDED"}
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import grpc

from techx_ai_common.proto import demo_pb2, demo_pb2_grpc

# (product_id, question, user_id, repeat_count)
SCENARIOS = [
    # Exact-match: same question twice
    ("OLJCESPC7Z", "Is this product good?", "user_alice", 2),
    # Paraphrase: semantic similarity on same product/user/source
    ("OLJCESPC7Z", "What do customers think about this product?", "user_alice", 1),
    # Different product, same question — must miss
    ("L9ECAV7KIM", "Is this product good?", "user_alice", 1),
    # Different user — isolation must miss
    ("OLJCESPC7Z", "Is this product good?", "user_bob", 1),
    # Missing stable user boundary (anonymous) — bypass/miss, not shared
    ("OLJCESPC7Z", "How is the quality?", "anonymous", 2),
]


def run_replay(host: str, port: int, output_path: str):
    channel = grpc.insecure_channel(f"{host}:{port}")
    stub = demo_pb2_grpc.ProductReviewServiceStub(channel)
    results = []

    for product_id, question, user_id, repeat in SCENARIOS:
        for attempt in range(1, repeat + 1):
            start = time.perf_counter()
            try:
                request = demo_pb2.AskProductAIAssistantRequest(
                    product_id=product_id,
                    question=question,
                )
                # Handoff §7: x-user-id = cache boundary; x-session-id = rate limit
                metadata = (
                    ("x-user-id", user_id),
                    ("x-session-id", f"session-{user_id}"),
                )
                response = stub.AskProductAIAssistant(
                    request, metadata=metadata, timeout=30
                )
                elapsed_ms = (time.perf_counter() - start) * 1000

                try:
                    body = json.loads(response.response)
                except (json.JSONDecodeError, AttributeError):
                    body = {}

                # Prefer top-level proto fields when present
                cache_status = getattr(response, "cache_status", None) or body.get(
                    "cache_status", "unknown"
                )
                cache_match = getattr(response, "cache_match", None) or body.get(
                    "cache_match", "unknown"
                )
                cache_distance = getattr(response, "cache_distance", None)
                if cache_distance in (None, 0) and "cache_distance" in body:
                    cache_distance = body.get("cache_distance", -1)

                record = {
                    "product_id": product_id,
                    "question": question,
                    # Do not log raw secrets; user_id is a test fixture id only.
                    "user_id": user_id,
                    "attempt": attempt,
                    "cache_status": cache_status or "unknown",
                    "cache_match": cache_match or "unknown",
                    "cache_distance": cache_distance if cache_distance is not None else -1,
                    "response_status": body.get("status")
                    or getattr(response, "status", "unknown"),
                    "latency_ms": round(elapsed_ms, 2),
                    "answer_preview": (body.get("answer", ""))[:80],
                }
            except grpc.RpcError as e:
                elapsed_ms = (time.perf_counter() - start) * 1000
                record = {
                    "product_id": product_id,
                    "question": question,
                    "user_id": user_id,
                    "attempt": attempt,
                    "cache_status": "error",
                    "cache_match": "none",
                    "cache_distance": -1,
                    "response_status": "RPC_ERROR",
                    "latency_ms": round(elapsed_ms, 2),
                    "answer_preview": str(e.code()),
                }

            results.append(record)
            print(
                f"[{record['cache_status']:>5}] "
                f"product={product_id[:8]}  "
                f"user={user_id:<12}  "
                f"attempt={attempt}  "
                f"match={record['cache_match']:<8}  "
                f"latency={record['latency_ms']:>8.1f}ms  "
                f"q=\"{question[:40]}\""
            )

    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n--- Results written to {output_path} ---\n")
    _print_summary(results)
    channel.close()


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _print_summary(results: list):
    hits = [r for r in results if r["cache_status"] == "hit"]
    misses = [r for r in results if r["cache_status"] == "miss"]
    errors = [r for r in results if r["cache_status"] == "error"]
    total = len(results)
    hit_rate = len(hits) / total * 100 if total else 0

    all_lat = [r["latency_ms"] for r in results]
    hit_lat = [r["latency_ms"] for r in hits]
    miss_lat = [r["latency_ms"] for r in misses]

    print("=" * 70)
    print("  REPLAY SUMMARY  -  Summary Bot Cache (A1.3)")
    print("=" * 70)
    print(f"  Total requests:        {total}")
    print(f"  Cache hits:            {len(hits)}  ({hit_rate:.1f}%)")
    print(
        f"    - exact:             {sum(1 for r in hits if r['cache_match'] == 'exact')}"
    )
    print(
        f"    - semantic:          {sum(1 for r in hits if r['cache_match'] == 'semantic')}"
    )
    print(f"  Cache misses:          {len(misses)}")
    print(f"  Errors:                {len(errors)}")
    print(f"  Mean latency (all):    {sum(all_lat)/len(all_lat) if all_lat else 0:>8.1f} ms")
    print(f"  p95 latency (all):     {_percentile(all_lat, 95):>8.1f} ms")
    print(f"  Mean latency (hit):    {sum(hit_lat)/len(hit_lat) if hit_lat else 0:>8.1f} ms")
    print(f"  Mean latency (miss):   {sum(miss_lat)/len(miss_lat) if miss_lat else 0:>8.1f} ms")
    print()
    print("  Note: run once with AI_CACHE_ENABLED=false (baseline) and once")
    print("  with AI_CACHE_ENABLED=true (cache empty at start) on the same")
    print("  dataset. Compare model calls / tokens / cost from service metrics.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Replay Summary Bot cache scenarios")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", default="replay_summary_cache.jsonl")
    args = parser.parse_args()
    run_replay(args.host, args.port, args.output)


if __name__ == "__main__":
    main()
