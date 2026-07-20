"""Time-to-detect helper functions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def seconds_between(start_utc: str, end_utc: str) -> int:
    return int((parse_utc_timestamp(end_utc) - parse_utc_timestamp(start_utc)).total_seconds())


def safe_seconds_between(start_utc: Any, end_utc: Any) -> int | None:
    """Return a positive/negative second delta, or None for unknown timestamps."""

    if not isinstance(start_utc, str) or not isinstance(end_utc, str):
        return None

    try:
        return seconds_between(start_utc, end_utc)
    except (TypeError, ValueError):
        return None
