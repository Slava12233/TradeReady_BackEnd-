"""Redis sliding-window rate limiter middleware for the API layer.

Applies per-account request rate limits using a Redis sliding window counter
keyed on ``rate_limit:{api_key}:{group}:{minute_bucket}``.

Auth endpoints (``/api/v1/auth/``) receive separate **IP-based** rate limits
because callers are not yet authenticated:

- ``/api/v1/auth/login``      — 5 requests / minute per IP
- ``/api/v1/auth/user-login`` — 5 requests / minute per IP
- ``/api/v1/auth/register``   — 3 requests / minute per IP

All other rate-limit tiers (account-based):

- **general**     — 600 requests / minute  (default for all routes)
- **orders**      — 100 requests / minute  (``/api/v1/trade/`` prefix)
- **market_data** — 1 200 requests / minute (``/api/v1/market/`` prefix)
- **backtest**    — 6 000 requests / minute (``/api/v1/backtest/`` prefix)
- **training**    — 3 000 requests / minute (``/api/v1/training/`` prefix)

On every response the middleware injects three standard headers::

    X-RateLimit-Limit:     <max requests per window>
    X-RateLimit-Remaining: <remaining requests in current window>
    X-RateLimit-Reset:     <Unix timestamp when the window resets>

When a limit is exceeded the middleware short-circuits and returns an HTTP
429 response with ``Retry-After`` header and the standard
``{"error": {...}}`` envelope from
:class:`~src.utils.exceptions.RateLimitExceededError`.

Unauthenticated requests (no account on ``request.state``) against
non-auth paths, and truly public paths (health, docs, metrics), are
passed through without rate-limiting so that the auth middleware can
reject them cleanly first.

Example::

    from fastapi import FastAPI
    from src.api.middleware.rate_limit import RateLimitMiddleware

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
"""

from __future__ import annotations

import time
from typing import Any, Final

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
import structlog

from src.utils.exceptions import RateLimitExceededError

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit tier definitions
# ---------------------------------------------------------------------------

_WINDOW_SECONDS: Final[int] = 60  # all tiers share a 1-minute window

# (path_prefix, group_name, limit_per_minute)
# Entries are evaluated in order; the *first* match wins.
_TIERS: Final[tuple[tuple[str, str, int], ...]] = (
    ("/api/v1/trade/", "orders", 100),
    ("/api/v1/backtest/", "backtest", 6000),
    ("/api/v1/market/", "market_data", 1200),
    ("/api/v1/training/", "training", 3000),
    ("/api/v1/", "general", 600),
)

_DEFAULT_GROUP: Final[str] = "general"
_DEFAULT_LIMIT: Final[int] = 600

# ---------------------------------------------------------------------------
# Auth-endpoint IP-based rate limits
# ---------------------------------------------------------------------------

# Exact paths under /api/v1/auth/ that require tight IP-based rate limiting.
# Maps exact path → (group_name, limit_per_minute).
# Any auth path NOT listed here falls through to the standard public bypass.
_AUTH_RATE_LIMITS: Final[dict[str, tuple[str, int]]] = {
    "/api/v1/auth/login": ("auth_login", 5),
    "/api/v1/auth/user-login": ("auth_login", 5),
    "/api/v1/auth/register": ("auth_register", 3),
}

# Public paths that should bypass rate limiting entirely (no account context).
# Note: /api/v1/auth/ is intentionally excluded here — auth paths are handled
# by the IP-based auth limiter above, not bypassed wholesale.
_PUBLIC_PREFIXES: Final[tuple[str, ...]] = (
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
    """Return ``True`` if *path* should bypass rate limiting entirely.

    Auth paths (``/api/v1/auth/``) are **not** in this list — they go
    through the separate IP-based auth limiter instead.

    Args:
        path: The raw URL path.

    Returns:
        ``True`` when the path matches a non-auth public prefix.
    """
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _resolve_auth_tier(path: str) -> tuple[str, int] | None:
    """Return ``(group_name, limit)`` for auth paths that need IP-based limiting.

    Args:
        path: The raw URL path.

    Returns:
        A ``(group, limit)`` tuple when the path is an auth endpoint subject
        to IP-based limiting, or ``None`` if the path is an auth path with no
        specific limit configured (passes through freely).
    """
    return _AUTH_RATE_LIMITS.get(path)


def _get_client_ip(request: Request) -> str:
    """Extract the client IP address from the request.

    Reads the first hop from ``X-Forwarded-For`` when present (reverse-proxy
    deployments); falls back to the direct peer address from
    ``request.client``.

    Args:
        request: The incoming Starlette request.

    Returns:
        The client IP as a string.  Returns ``"unknown"`` when no address can
        be determined (e.g. test environments without a transport).
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        # Take only the first (leftmost) hop — closest to the real client.
        return forwarded_for.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def _redis_key(api_key: str, group: str, minute_bucket: int) -> str:
    """Build the Redis key for an account-based sliding-window counter.

    Args:
        api_key:       The account's API key (acts as the client identifier).
        group:         Rate-limit tier group name.
        minute_bucket: Unix minute timestamp (``floor(unix_seconds / 60)``).

    Returns:
        A namespaced Redis key string.
    """
    return f"rate_limit:{api_key}:{group}:{minute_bucket}"


def _auth_redis_key(ip: str, group: str, minute_bucket: int) -> str:
    """Build the Redis key for an IP-based auth sliding-window counter.

    Args:
        ip:            The client IP address.
        group:         Auth rate-limit group name (e.g. ``"auth_login"``).
        minute_bucket: Unix minute timestamp (``floor(unix_seconds / 60)``).

    Returns:
        A namespaced Redis key string distinct from account-based keys.
    """
    return f"auth_rate_limit:{ip}:{group}:{minute_bucket}"


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

        # Pass through public paths (health, docs, metrics).
        if _is_public_path(path):
            return await call_next(request)

        # ── Auth-endpoint IP-based rate limiting ──────────────────────
        auth_tier = _resolve_auth_tier(path)
        if auth_tier is not None:
            return await self._enforce_auth_rate_limit(
                request,
                call_next,
                path,
                auth_tier,
            )

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
                api_key_prefix=api_key[:8],
                group=group,
                limit=limit,
                count=current_count,
                path=path,
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

        response = await call_next(request)  # type: ignore[assignment]

        # Inject rate-limit headers on successful responses.
        for header_name, header_value in rate_headers.items():
            response.headers[header_name] = header_value

        return response

    async def _enforce_auth_rate_limit(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
        path: str,
        auth_tier: tuple[str, int],
    ) -> Response:
        """Enforce IP-based rate limits on authentication endpoints.

        Auth endpoints are rate-limited by client IP (not account) because
        the caller is not yet authenticated.  This prevents brute-force
        password attacks and CPU DoS via bcrypt hashing.

        Args:
            request:    The incoming HTTP request.
            call_next:  Starlette callback for the next middleware / route.
            path:       The request URL path.
            auth_tier:  ``(group_name, limit_per_minute)`` for this auth path.

        Returns:
            The downstream response, or HTTP 429 if the limit is exceeded.
        """
        group, limit = auth_tier
        client_ip = _get_client_ip(request)

        now_ts = int(time.time())
        minute_bucket = now_ts // _WINDOW_SECONDS
        reset_ts = (minute_bucket + 1) * _WINDOW_SECONDS

        key = _auth_redis_key(client_ip, group, minute_bucket)
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
                "rate_limit.auth_exceeded",
                client_ip=client_ip,
                group=group,
                limit=limit,
                count=current_count,
                path=path,
            )
            return JSONResponse(
                content=error.to_dict(),
                status_code=error.http_status,
                headers={
                    **rate_headers,
                    "Retry-After": str(retry_after),
                },
            )

        response = await call_next(request)  # type: ignore[assignment]
        for header_name, header_value in rate_headers.items():
            response.headers[header_name] = header_value
        return response

    async def _increment_counter(self, request: Request, key: str) -> int:
        """Atomically increment the Redis sliding-window counter using a pipeline.

        Batches ``INCR`` and ``EXPIRE`` in a single pipeline round-trip to
        halve Redis latency per rate-limit check.  The TTL is always set (not
        just on the first request) to handle any key-renewal edge cases.  The
        TTL is ``2 * _WINDOW_SECONDS`` so the key covers the current window
        plus one full window of overlap for in-flight requests near the
        boundary.

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
            pipe = redis.pipeline(transaction=False)
            pipe.incr(key)
            pipe.expire(key, _WINDOW_SECONDS * 2)
            results = await pipe.execute()
            count: int = results[0]
            return count
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "rate_limit.redis_error",
                key=key,
                error=str(exc),
            )
            return 0

    @staticmethod
    def _get_redis(request: Request) -> Any:  # noqa: ANN401
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
