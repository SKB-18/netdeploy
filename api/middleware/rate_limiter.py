"""
Sliding-window rate limiter middleware for NetDeploy.

Strategy: per-IP sliding window using Redis ZSET.
  - Each key is "rate:{ip}:{window_seconds}"
  - On each request: ZADD current timestamp, ZREMRANGEBYSCORE old entries,
    ZCARD → if > limit, return 429.

Configuration (via settings):
    RATE_LIMIT_REQUESTS  = 100   # requests per window
    RATE_LIMIT_WINDOW    = 60    # window in seconds
    RATE_LIMIT_ENABLED   = True  # set False in dev/test

Certain paths are excluded from rate limiting:
    /health, /metrics, /docs, /redoc, /openapi.json

Cursor implements:
  - _get_redis() connection pool (shared singleton)
  - _sliding_window_check() — the Redis ZSET logic
  - Per-IP exemption list from settings (e.g. monitoring IPs)
"""

import time
import logging
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("netdeploy.rate_limiter")

# Paths that bypass rate limiting entirely
EXEMPT_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",
}

# Deployment/rollback endpoints get a stricter per-minute cap
STRICT_PATHS = {
    "/api/deployments",        # POST trigger deployment
    "/api/devices",            # POST register device
}

# Default limits — overridden by settings if available
DEFAULT_LIMIT = 100
DEFAULT_WINDOW = 60
STRICT_LIMIT = 10
STRICT_WINDOW = 60


def _get_settings_limits():
    """Load limits from application settings, falling back to defaults."""
    try:
        from core.config import settings
        return {
            "limit": getattr(settings, "RATE_LIMIT_REQUESTS", DEFAULT_LIMIT),
            "window": getattr(settings, "RATE_LIMIT_WINDOW", DEFAULT_WINDOW),
            "enabled": getattr(settings, "RATE_LIMIT_ENABLED", True),
        }
    except Exception:
        return {"limit": DEFAULT_LIMIT, "window": DEFAULT_WINDOW, "enabled": True}


def _get_redis():
    """
    Return a Redis client using the configured REDIS_URL.

    [CURSOR IMPLEMENTS]: Use a module-level connection pool so we don't create
    a new connection per request. Pattern:
        import redis
        _pool = redis.ConnectionPool.from_url(settings.REDIS_URL, max_connections=50)
        _redis_client = redis.Redis(connection_pool=_pool)
    Returns None if Redis is unavailable (fail-open: requests pass through).
    """
    try:
        import redis as redis_lib
        from core.config import settings
        return redis_lib.from_url(settings.REDIS_URL, socket_connect_timeout=1)
    except Exception:
        return None


async def _sliding_window_check(
    redis_client,
    key: str,
    limit: int,
    window_seconds: int,
) -> tuple:
    """
    Sliding window rate limit check via Redis ZSET.

    Returns:
        (allowed: bool, current_count: int, reset_after_seconds: int)
    """
    now = time.time()
    cutoff = now - window_seconds
    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(key, "-inf", cutoff)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    results = pipe.execute()
    count = results[2]
    reset_after = window_seconds
    return (count <= limit, count, reset_after)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window per-IP rate limiting middleware.

    Attach in api/main.py:
        from api.middleware.rate_limiter import RateLimitMiddleware
        app.add_middleware(RateLimitMiddleware)

    On 429 the response includes:
        X-RateLimit-Limit: <limit>
        X-RateLimit-Remaining: 0
        X-RateLimit-Reset: <unix_timestamp>
        Retry-After: <seconds>
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        cfg = _get_settings_limits()

        # Fast path: middleware disabled
        if not cfg["enabled"]:
            return await call_next(request)

        path = request.url.path

        # Fast path: exempt endpoints
        if path in EXEMPT_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)

        # Determine limit tier
        is_strict = any(path.startswith(p) for p in STRICT_PATHS) and request.method == "POST"
        limit = STRICT_LIMIT if is_strict else cfg["limit"]
        window = STRICT_WINDOW if is_strict else cfg["window"]

        # Extract client IP (respect X-Forwarded-For if behind proxy)
        client_ip = _extract_ip(request)

        redis_client = _get_redis()

        if redis_client is None:
            # Fail open: Redis unavailable → allow request, log warning
            logger.warning("Rate limiter Redis unavailable — failing open for %s", client_ip)
            return await call_next(request)

        key = f"rate:{client_ip}:{path.replace('/', '_')}"

        try:
            allowed, count, reset_after = await _sliding_window_check(
                redis_client, key, limit, window
            )
        except NotImplementedError:
            # [CURSOR IMPLEMENTS] not yet filled in — fail open
            return await call_next(request)
        except Exception as e:
            logger.error("Rate limit check error: %s — failing open", e)
            return await call_next(request)

        remaining = max(0, limit - count)
        reset_ts = int(time.time()) + reset_after

        if not allowed:
            # Track in Prometheus
            try:
                from api.metrics import RATE_LIMIT_COUNTER
                RATE_LIMIT_COUNTER.labels(path=path).inc()
            except Exception:
                pass

            logger.warning("Rate limit exceeded: ip=%s path=%s count=%d", client_ip, path, count)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_ts),
                    "Retry-After": str(reset_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_ts)
        return response


def _extract_ip(request: Request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
