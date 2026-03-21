"""Audit log writer middleware for the API layer.

After every response that matches a set of auditable actions, this middleware
fires a non-blocking :func:`asyncio.create_task` to persist an
:class:`~src.database.models.AuditLog` row to the database.

The task is intentionally fire-and-forget:

- The response is **never** delayed waiting for the audit write.
- A failure in the audit write is logged at ``WARNING`` level and swallowed —
  it must never crash or slow down the request path.

Auditable actions are matched by ``(method, path)`` pairs.  ``DELETE`` routes
under ``/api/v1/agents/`` are matched by prefix rather than exact path because
the agent UUID is part of the path.

Example log on audit write failure::

    {
        "event": "audit.write_failed",
        "action": "place_order",
        "path": "/api/v1/trade/order",
        "error": "...",
        "level": "warning"
    }

Example::

    from fastapi import FastAPI
    from src.api.middleware.audit import AuditMiddleware

    app = FastAPI()
    app.add_middleware(AuditMiddleware)
"""

from __future__ import annotations

import asyncio
from typing import Final
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Action mapping
# ---------------------------------------------------------------------------

# Exact-match rules: (METHOD, path) -> action code.
_EXACT_ACTIONS: Final[dict[tuple[str, str], str]] = {
    ("POST", "/api/v1/trade/order"): "place_order",
    ("POST", "/api/v1/auth/register"): "register",
    ("POST", "/api/v1/auth/login"): "login",
    ("POST", "/api/v1/backtest/create"): "create_backtest",
    ("POST", "/api/v1/strategies"): "create_strategy",
}

# Prefix-match rules: (METHOD, path_prefix) -> action code.
# Used for routes where the path contains an ID segment (e.g. DELETE /agents/{id}).
_PREFIX_ACTIONS: Final[list[tuple[str, str, str]]] = [
    ("DELETE", "/api/v1/agents/", "delete_agent"),
]


def _resolve_action(method: str, path: str) -> str | None:
    """Return the audit action code for this request, or ``None`` if not auditable.

    Checks exact matches first, then prefix matches.  Returns the first match.

    Args:
        method: HTTP method (upper-case), e.g. ``"POST"``.
        path:   URL path without query string, e.g. ``"/api/v1/trade/order"``.

    Returns:
        A short action code string such as ``"place_order"``, or ``None`` when
        the request does not correspond to an auditable action.
    """
    action = _EXACT_ACTIONS.get((method, path))
    if action is not None:
        return action
    for prefix_method, prefix_path, prefix_action in _PREFIX_ACTIONS:
        if method == prefix_method and path.startswith(prefix_path):
            return prefix_action
    return None


def _client_ip(request: Request) -> str | None:
    """Extract the best-effort client IP address.

    Prefers the first value in ``X-Forwarded-For`` (set by reverse proxies)
    and falls back to the direct TCP peer address.

    Args:
        request: The incoming Starlette request.

    Returns:
        An IP address string, or ``None`` if none is available.
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


async def _write_audit_log(
    account_id: UUID | None,
    action: str,
    details: dict[str, object],
    ip_address: str | None,
) -> None:
    """Write a single :class:`~src.database.models.AuditLog` row.

    Opens a short-lived session from the shared session factory, persists the
    row, and commits.  Any exception is caught and logged at ``WARNING`` level
    so the caller (a fire-and-forget task) never propagates errors upward.

    Args:
        account_id: UUID of the authenticated account, or ``None`` for
                    unauthenticated requests.
        action:     Short action code (max 50 chars), e.g. ``"place_order"``.
        details:    Arbitrary JSONB payload stored alongside the action.
        ip_address: Client IP address string, or ``None`` when unavailable.
    """
    # Lazy imports to avoid circular dependencies at module load time.
    from src.database.models import AuditLog  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415

    try:
        factory = get_session_factory()
        async with factory() as session:
            row = AuditLog(
                account_id=account_id,
                action=action,
                details=details,
                ip_address=ip_address,
            )
            session.add(row)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "audit.write_failed",
            action=action,
            error=str(exc),
        )


class AuditMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that asynchronously records auditable API actions.

    After the response is sent the middleware checks whether the request
    matches one of the :data:`_EXACT_ACTIONS` or :data:`_PREFIX_ACTIONS`
    entries.  When it does, an :func:`asyncio.create_task` is fired to write
    an :class:`~src.database.models.AuditLog` row without blocking the caller.

    Design invariants:

    - The middleware **never** raises an exception into the request pipeline.
    - The audit write happens **after** the response has been dispatched to
      the client, so latency impact is zero.
    - ``account_id`` is read from ``request.state.account`` which is populated
      by :class:`~src.api.middleware.auth.AuthMiddleware`.  The audit
      middleware must therefore be registered **after** auth in Starlette's
      LIFO stack (i.e. ``add_middleware(AuditMiddleware)`` **before**
      ``add_middleware(AuthMiddleware)`` in ``create_app()``).

    Example::

        from fastapi import FastAPI
        from src.api.middleware.audit import AuditMiddleware

        app = FastAPI()
        app.add_middleware(AuditMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Dispatch the request and schedule an audit write if applicable.

        Args:
            request:   The incoming HTTP request.
            call_next: Starlette callback to invoke the next middleware or
                       route handler.

        Returns:
            The downstream :class:`~starlette.responses.Response` unchanged.
        """
        response = await call_next(request)

        method = request.method
        path = request.url.path
        action = _resolve_action(method, path)

        if action is None:
            return response

        # Gather context that is only safe to read synchronously here.
        account = getattr(request.state, "account", None)
        account_id: UUID | None = account.id if account is not None else None

        request_id: str = getattr(request.state, "request_id", "")
        trace_id: str = getattr(request.state, "trace_id", "")
        ip_address = _client_ip(request)

        details: dict[str, object] = {
            "path": path,
            "status_code": response.status_code,
        }
        if request_id:
            details["request_id"] = request_id
        if trace_id:
            details["trace_id"] = trace_id

        asyncio.create_task(
            _write_audit_log(
                account_id=account_id,
                action=action,
                details=details,
                ip_address=ip_address,
            )
        )

        return response
