"""Tiny Redis-backed rate limiter for signup / recovery / other abuse-prone endpoints.

Fixed-window counter — simplest thing that solves the abuse case without
adding a dependency. Two failure modes are designed to fail-open: if Redis
is unreachable, or the key is malformed, the limiter does NOT block — we'd
rather risk a brief abuse window than take signup offline.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request
from redis.asyncio import Redis

from app.config import settings

log = logging.getLogger(__name__)

_redis: Optional[Redis] = None


def _client() -> Optional[Redis]:
    global _redis
    if _redis is None:
        try:
            _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception as e:
            log.warning("Rate-limit Redis init failed: %s", e)
            return None
    return _redis


def client_ip(request: Request) -> str:
    """Best-effort client IP. Trust the first hop from X-Forwarded-For when set
    by our edge (Vercel proxy / Railway router), else fall back to the socket."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        # left-most entry is the original client per RFC 7239
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def enforce(
    request: Request,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
    key_suffix: str = "",
) -> None:
    """Throw 429 if this IP has made more than `limit` requests in `window_seconds`.

    Args:
        bucket: short identifier of the protected route, e.g. "signup".
        limit: max requests per window.
        window_seconds: window length.
        key_suffix: optional extra discriminator (e.g. lowercased email) so the
            same IP using different emails still gets independent counters.
    """
    r = _client()
    if r is None:
        # fail-open: better to allow than 500
        return

    ip = client_ip(request)
    suffix = f":{key_suffix}" if key_suffix else ""
    key = f"rl:{bucket}:{ip}{suffix}"
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window_seconds)
        if count > limit:
            retry_after = await r.ttl(key)
            if retry_after is None or retry_after < 0:
                retry_after = window_seconds
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded for {bucket}. "
                    f"Try again in {retry_after} seconds."
                ),
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as e:
        # any other Redis hiccup → fail-open
        log.warning("Rate-limit check failed (fail-open): %s", e)
        return
