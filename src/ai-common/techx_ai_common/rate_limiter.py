#!/usr/bin/python
# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger("rate_limiter")


def check_rate_limit(
    valkey_client,
    client_id: str,
    cooldown_seconds: int = 2,
    max_requests_per_minute: int = 10,
) -> Tuple[bool, Optional[str]]:
    """Checks if client exceeds cooldown or per-minute rate limit.

    Returns:
        (is_allowed: bool, reason: Optional[str])
    """
    if not valkey_client or not client_id:
        return True, None

    now = time.time()
    cooldown_key = f"rate_limit:cooldown:{client_id}"
    window_key = f"rate_limit:window:{client_id}"

    try:
        # 1. Cooldown check (2 seconds between requests)
        last_req_time = valkey_client.get(cooldown_key)
        if last_req_time:
            elapsed = now - float(last_req_time)
            if elapsed < cooldown_seconds:
                remaining = cooldown_seconds - elapsed
                return False, f"Please wait {remaining:.1f}s before sending another message."

        # 2. Sliding window rate limit check (10 requests per 60 seconds)
        pipe = valkey_client.pipeline()
        pipe.zremrangebyscore(window_key, 0, now - 60)
        pipe.zadd(window_key, {str(now): now})
        pipe.zcard(window_key)
        pipe.expire(window_key, 60)
        results = pipe.execute()

        request_count = results[2]
        if request_count > max_requests_per_minute:
            return False, f"Rate limit exceeded (maximum {max_requests_per_minute} messages per minute). Please try again later."

        # Update cooldown timestamp
        valkey_client.setex(cooldown_key, cooldown_seconds, str(now))
        return True, None

    except Exception as e:
        logger.warning("Valkey rate limit check error: %s", e)
        # Fallback to allow on cache error
        return True, None
