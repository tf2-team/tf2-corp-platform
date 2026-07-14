from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {"authorization", "password", "secret", "token", "webhook_url"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a bounded, redacted evidence envelope from JSON")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--environment", required=True)
    args = parser.parse_args()

    source_bytes = args.input.read_bytes()
    if len(source_bytes) > 5 * 1024 * 1024:
        raise ValueError("evidence input exceeds the 5 MiB scaffold limit")
    payload = _redact(json.loads(source_bytes))
    envelope = {
        "schema_version": "1.0",
        "environment": args.environment,
        "captured_at": datetime.now(UTC).isoformat(),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "payload": payload,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
