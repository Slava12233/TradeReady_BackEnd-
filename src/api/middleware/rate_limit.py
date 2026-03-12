"""Redis sliding-window rate limiter middleware for the API layer.

Applies per-account request rate limits using a Redis sliding window counter
keyed on ``rate_limit:{api_key}:{group}:{minute_bucket}``.

Three rate-limit tiers
----------------------
- **general**     — 600 requests / minute  (default for all routes)
- **orders**      — 100 requests / minute  (``/api/v1/trade/`` prefix)
- **market_data** — 1 200 requests / minute (``/api/v1/market/`` prefix)

On every response the middleware injects three standard headers::

    X-RateLimit-Limit:     <max requests per window>
    X-RateLimit-Remaining: <remaining requests in current window>
    X-RateLimit-Reset:     <Unix timestamp when the window resets>

When the limit is exceeded the middleware short-circuits and returns an HTTP
429 response with the standard ``{"error": {...}}`` envelope defined in
:class:`~src.utils.exceptions.RateLimitExceededError`.

Unauthenticated requests (no account on ``request.state``) and public paths
are passed through without rate-limiting so that the auth middleware can
reject them cleanly first.

Example::

    from fastapi import FastAPI
    from src.api.middleware.rate_limit import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
"""

from __future__ import annotations

import logging
import time
from typing import Final

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.utils.exceptions import RateLimitExceededError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit tier definitions
# ---------------------------------------------------------------------------

_WINDOW_SECONDS: Final[int] = 60  # all tiers share a 1-minute window

# (path_prefix, group_name, limit_per_minute)
# Entries are evaluated in order; the *first* match wins.
_TIERS: Final[tuple[tuple[str, str, int], ...]] = (
    ("/api/v1/trade/", "orders", 100),
    ("/api/v1/market/", "market_data", 1200),
    ("/api/v1/", "general", 600),
)

_DEFAULT_GROUP: Final[str] = "general"
_DEFAULT_LIMIT: Final[int] = 600

# Public paths that should bypass rate limiting entirely (no account context).
_PUBLIC_PREFIXES: Final[tuple[str, ...]] = (
    "/api/v1/auth/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_tier(path: str) -> tuple[str, int]:
    """Return ``(group_name, limit)`` for the given request path.

    Args:
        path: The raw URL path (without query string).

    Returns:
        A ``(group, limit)`` tuple for the first matching tier, or the
        default ``("general", 600)`` if no prefix matches.
    """
    for prefix, group, limit in _TIERS:
        if path.startswith(prefix):
            return group, limit
    return _DEFAULT_GROUP, _DEFAULT_LIMIT


def _is_public_path(path: str) -> bool:
    """Return ``True`` if *path* should bypass rate limiting.

    Args:
        path: The raw URL path.

    Returns:
        ``True`` when the path is in the public prefix list.
    """
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _redis_key(api_key: str, group: str, minute_bucket: int) -> str:
    """Build the Redis key for the sliding-window counter.

    Args:
        api_key:       The account's API key (acts as the client identifier).
        group:         Rate-limit tier group name.
        minute_bucket: Unix minute timestamp (``floor(unix_seconds / 60)``).

    Returns:
        A namespaced Redis key string.
    """
    return f"rate_limit:{api_key}:{group}:{minute_bucket}"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces per-account sliding-window rate limits.

    The middleware reads the account stored on ``request.state.account`` by
    :class:`~src.api.middleware.auth.AuthMiddleware` and uses its ``api_key``
    as the rate-limit identity.  If no account is present (unauthenticated or
    public path) the middleware passes through without counting.

    For each request the middleware:

    1. Resolves the rate-limit tier from the URL path.
    2. Increments an atomic Redis counter for the current 1-minute bucket.
    3. Sets a 2-minute TTL on the counter key (so keys self-clean).
    4. Computes ``remaining = max(0, limit - current_count)``.
    5. Injects ``X-RateLimit-*`` headers on *every* response (including 429s).
    6. Short-circuits with HTTP 429 if ``current_count > limit``.

    Redis errors are logged and silently swallowed — the request is allowed
    through so that a Redis outage does not take down the API.

    Example::

        from fastapi import FastAPI
        from src.api.middleware.rate_limit import RateLimitMiddleware

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Enforce rate limits before forwarding the request.

        Args:
            request:   The incoming HTTP request.
            call_next: Starlette callback for the next middleware / route.

        Returns:
            The downstream :class:`~starlette.responses.Response`, or an HTTP
            429 JSON error if the rate limit is exceeded.
        """
        path = request.url.path

        # Pass through public paths and unauthenticated requests.
        if _is_public_path(path):
            return await call_next(request)

        account = getattr(request.state, "account", None)
        if account is None:
            # Auth middleware will reject this; nothing to rate-limit.
            return await call_next(request)

        api_key: str = account.api_key
        group, limit = _resolve_tier(path)

        # Current 1-minute bucket (integer division of Unix epoch).
        now_ts = int(time.time())
        minute_bucket = now_ts // _WINDOW_SECONDS
        reset_ts = (minute_bucket + 1) * _WINDOW_SECONDS

        key = _redis_key(api_key, group, minute_bucket)
        current_count = await self._increment_counter(request, key)

        remaining = max(0, limit - current_count)
        retry_after = max(0, reset_ts - now_ts)

        rate_headers: dict[str, str] = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_ts),
        }

        if current_count > limit:
            error = RateLimitExceededError(
                limit=limit,
                window_seconds=_WINDOW_SECONDS,
                retry_after=retry_after,
            )
            logger.warning(
                "rate_limit.exceeded",
                extra={
                    "api_key_prefix": api_key[:8],
                    "group": group,
                    "limit": limit,
                    "count": current_count,
                    "path": path,
                },
            )
            response = JSONResponse(
                content=error.to_dict(),
                status_code=error.http_status,
                headers={
                    **rate_headers,
                    "Retry-After": str(retry_after),
                },
            )
            return response

        response = await call_next(request)

        # Inject rate-limit headers on successful responses.
        for header_name, header_value in rate_headers.items():
            response.headers[header_name] = header_value

        return response

    async def _increment_counter(self, request: Request, key: str) -> int:
        """Atomically increment the Redis sliding-window counter.

        Uses ``INCR`` followed by ``EXPIRE`` (set only if the key is new).
        The TTL is ``2 * _WINDOW_SECONDS`` so the key covers the current
        window plus one full window of overlap for in-flight requests near
        the boundary.

        Args:
            request: The current HTTP request (used to reach the Redis client).
            key:     The fully-qualified Redis key for this window bucket.

        Returns:
            The updated counter value after the increment.  Returns ``0`` on
            any Redis error so that the caller allows the request through.
        """
        redis = self._get_redis(request)
        if redis is None:
            # No Redis available — fail open.
            return 0

        try:
            count: int = await redis.incr(key)
            if count == 1:
                # First request in this window — set TTL.
                await redis.expire(key, _WINDOW_SECONDS * 2)
            return count
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "rate_limit.redis_error",
                extra={"key": key, "error": str(exc)},
            )
            return 0

    @staticmethod
    def _get_redis(request: Request):  # type: ignore[return]  # noqa: ANN205
        """Extract the Redis client from application state.

        The Redis client is stored on ``request.app.state.redis`` during
        application startup in ``src/main.py``.

        Args:
            request: The current Starlette / FastAPI request.

        Returns:
            A :class:`redis.asyncio.Redis` instance, or ``None`` if not
            available.
        """
        return getattr(request.app.state, "redis", None)
