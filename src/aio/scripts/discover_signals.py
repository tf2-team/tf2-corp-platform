from __future__ import annotations

import argparse
import json
import os
from urllib.parse import urlparse

import httpx


def _production_url(value: str) -> str:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise argparse.ArgumentTypeError("Prometheus URL must be an absolute HTTP(S) URL")
    if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".example"):
        raise argparse.ArgumentTypeError("placeholder and local Prometheus URLs are not accepted")
    return value.rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover metric names from a real TF2 Prometheus endpoint")
    parser.add_argument("--base-url", type=_production_url, default=os.environ.get("AIOPS_PROMETHEUS_BASE_URL"))
    parser.add_argument("--token-env", default="AIOPS_PROMETHEUS_TOKEN")
    parser.add_argument("--contains", default="")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if not args.base_url:
        parser.error("--base-url or AIOPS_PROMETHEUS_BASE_URL is required")

    headers: dict[str, str] = {}
    token = os.environ.get(args.token_env, "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = httpx.get(f"{args.base_url}/api/v1/label/__name__/values", headers=headers, timeout=args.timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success" or not isinstance(payload.get("data"), list):
        raise RuntimeError("Prometheus returned an unexpected metric-name response")
    names = sorted(name for name in payload["data"] if isinstance(name, str) and args.contains.lower() in name.lower())
    print(json.dumps({"source": args.base_url, "count": len(names), "metric_names": names}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
