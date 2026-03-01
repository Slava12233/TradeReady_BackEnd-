"""structlog request/response logging middleware for the API layer.

Logs every inbound HTTP request and its corresponding response with structured
fields so that log aggregators (Loki, Elasticsearch, etc.) can index and query
them efficiently.

Each log record contains:

- ``request_id``  — UUID4 correlation ID injected into ``request.state`` so
  that route handlers and downstream services can emit correlated log lines.
- ``method``      — HTTP verb.
- ``path``        — URL path (without query string).
- ``status``      — HTTP response status code.
- ``latency_ms``  — Wall-clock time from request start to response, in
  milliseconds (rounded to 2 dp).
- ``account_id``  — UUID of the authenticated account when present (omitted
  for public / unauthenticated requests).
- ``ip``          — Client IP from ``X-Forwarded-For`` (first hop) or the
  direct client address, for rate-limit debugging.

The ``/health`` endpoint is intentionally excluded from request logs to avoid
spamming log sinks with high-frequency liveness-probe noise.

Example log output (JSON renderer configured externally)::

    {
        "event": "http.request",
        "request_id": "4b3e8f1a-...",
        "method": "POST",
        "path": "/api/v1/trade/order",
        "status": 200,
        "latency_ms": 12.34,
        "account_id": "a1b2c3...",
        "ip": "203.0.113.5",
        "level": "info",
        "timestamp": "2026-02-24T10:00:00.123456Z"
    }

Example::

    from fastapi import FastAPI
    from src.api.middleware.logging import LoggingMiddleware

    app = FastAPI()
    app.add_middleware(LoggingMiddleware)
"""

from __future__ import annotations

import time
import uuid
from typing import Final

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Paths that generate excessive noise from health-check scrapers.
_SKIP_LOG_PATHS: Final[frozenset[str]] = frozenset({"/health", "/metrics"})


def _client_ip(request: Request) -> str:
    """Return the best-effort client IP address.

    Prefers the first value in ``X-Forwarded-For`` (set by reverse proxies /
    load balancers) and falls back to the direct TCP peer address.

    Args:
        request: The incoming Starlette request.

    Returns:
        A string IP address, or ``"unknown"`` if none is available.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class LoggingMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that emits a structured log line per HTTP request.

    The middleware:

    1. Generates a ``request_id`` (UUID4) and stores it on
       ``request.state.request_id`` so that downstream code can reference it.
    2. Records the start time.
    3. Calls the next middleware / route handler.
    4. On completion (or exception), logs method, path, status, latency, and
       optional account_id.
    5. Skips logging for paths in ``_SKIP_LOG_PATHS`` (``/health``,
       ``/metrics``) to reduce noise.
    6. Propagates exceptions unchanged after logging a 500-level record.

    Example::

        from fastapi import FastAPI
        from src.api.middleware.logging import LoggingMiddleware

        app = FastAPI()
        app.add_middleware(LoggingMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Log the request/response cycle and propagate to the next handler.

        Args:
            request:   The incoming HTTP request.
            call_next: Starlette callback to invoke the next middleware or
                       route handler.

        Returns:
            The downstream :class:`~starlette.responses.Response` unchanged.
        """
        path = request.url.path

        # Attach a correlation ID regardless of whether we log this path.
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        if path in _SKIP_LOG_PATHS:
            return await call_next(request)

        method = request.method
        ip = _client_ip(request)
        start = time.perf_counter()

        response: Response | None = None
        exc_info = None

        try:
            response = await call_next(request)
        except Exception as exc:
            exc_info = exc
            raise
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            status = response.status_code if response is not None else 500

            account = getattr(request.state, "account", None)
            account_id: str | None = str(account.id) if account is not None else None

            log_kwargs: dict[str, object] = {
                "request_id": request_id,
                "method": method,
                "path": path,
                "status": status,
                "latency_ms": latency_ms,
                "ip": ip,
            }
            if account_id is not None:
                log_kwargs["account_id"] = account_id

            if exc_info is not None or status >= 500:
                logger.error("http.request", **log_kwargs)
            elif status >= 400:
                logger.warning("http.request", **log_kwargs)
            else:
                logger.info("http.request", **log_kwargs)

        return response  # type: ignore[return-value]
