#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Replay Shopping Copilot requests and emit cache evidence as JSONL."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

import grpc
from techx_ai_common.proto import demo_pb2, demo_pb2_grpc


DEFAULT_REQUESTS = [
    "Find a portable telescope for observing planets under $200.",
    "Find a portable telescope for observing planets under $200.",
    "Recommend portable planet-viewing astronomy gear below $200.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--user-id", default="cache-replay-user")
    parser.add_argument("--session-id", default=str(uuid.uuid4()))
    parser.add_argument("--request", action="append", dest="requests")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requests = args.requests or DEFAULT_REQUESTS
    channel = grpc.insecure_channel(f"{args.host}:{args.port}")
    stub = demo_pb2_grpc.ShoppingCopilotServiceStub(channel)
    rows = []

    for index, user_message in enumerate(requests, start=1):
        started = time.perf_counter()
        response = stub.Search(
            demo_pb2.CopilotSearchRequest(
                user_message=user_message,
                user_id=args.user_id,
                conversation_id=args.session_id,
                turn_id=str(uuid.uuid4()),
            )
        )
        row = {
            "sequence": index,
            "request": user_message,
            "user_id": args.user_id,
            "session_id": args.session_id,
            "status": response.status,
            "cache_status": response.cache_status,
            "cache_match": response.cache_match,
            "cache_distance": response.cache_distance,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "product_ids": [product.product_id for product in response.products],
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
