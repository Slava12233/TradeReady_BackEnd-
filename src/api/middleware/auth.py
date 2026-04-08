"""Authentication middleware and FastAPI dependency for the API layer.

Responsibilities
----------------
1. ``AuthMiddleware`` — Starlette ``BaseHTTPMiddleware`` that runs before every
   request.  It extracts credentials from the ``X-API-Key`` header or an
   ``Authorization: Bearer <jwt>`` header, resolves the account from the
   database, and stores it on ``request.state.account``.  Public endpoints are
   passed through without authentication.

2. ``get_current_account`` — FastAPI ``Depends()`` that routes handlers use to
   obtain the already-authenticated :class:`~src.database.models.Account`
   object.  It reads ``request.state.account`` set by the middleware, or falls
   back to direct header extraction if the middleware was bypassed (e.g. in
   tests that mount the router without the middleware).

Example::

    from src.api.middleware.auth import get_current_account, AuthMiddleware
    from fastapi import Depends

    # In main.py:
    app.add_middleware(AuthMiddleware)

    # In a route:
    @router.get("/info")
    async def info(account: Annotated[Account, Depends(get_current_account)]):
        return {"account_id": str(account.id)}
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.accounts.auth import verify_jwt
from src.config import get_settings
from src.database.models import Account, Agent
from src.database.repositories.account_repo import AccountRepository
from src.database.repositories.agent_repo import AgentNotFoundError, AgentRepository
from src.utils.exceptions import (
    AccountNotFoundError,
    AccountSuspendedError,
    AuthenticationError,
    TradingPlatformError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public endpoint whitelist — no authentication required
# ---------------------------------------------------------------------------

_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/user-login",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/metrics",
        "/metrics/",  # Starlette sub-app mount redirects /metrics → /metrics/
    }
)

# Path prefixes that are publicly accessible without authentication.
# Market data endpoints are read-only and require no account to view.
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/docs",
    "/redoc",
    "/metrics",  # Prometheus scrape endpoint — must be unauthenticated
    "/api/v1/market/",
)


def _is_public(path: str) -> bool:
    """Return ``True`` if *path* does not require authentication.

    Performs an exact match against ``_PUBLIC_PATHS``, then checks
    ``_PUBLIC_PREFIXES`` for prefix matches (e.g. all ``/api/v1/market/``
    endpoints are public read-only data, Swagger UI sub-paths, etc.).

    Args:
        path: The raw request path (without query string).

    Returns:
        ``True`` when the path is publicly accessible without a token.
    """
    if path in _PUBLIC_PATHS:
        return True
    if path.startswith(_PUBLIC_PREFIXES):
        return True
    return False


# ---------------------------------------------------------------------------
# Credential extraction helpers
# ---------------------------------------------------------------------------


def _extract_api_key(request: Request) -> str | None:
    """Return the raw value of the ``X-API-Key`` header, or ``None``.

    Args:
        request: The incoming Starlette / FastAPI request.

    Returns:
        The header value stripped of leading/trailing whitespace, or ``None``
        if the header is absent or empty.
    """
    raw = request.headers.get("X-API-Key", "").strip()
    return raw or None


def _extract_bearer_token(request: Request) -> str | None:
    """Return the JWT token from an ``Authorization: Bearer <token>`` header.

    Args:
        request: The incoming Starlette / FastAPI request.

    Returns:
        The raw JWT string (without the ``Bearer `` prefix), or ``None`` if the
        header is absent, malformed, or uses a different scheme.
    """
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


# ---------------------------------------------------------------------------
# Core authentication logic (shared by middleware and dependency)
# ---------------------------------------------------------------------------


async def _resolve_account_from_api_key(
    api_key: str,
    repo: AccountRepository,
    agent_repo: AgentRepository | None = None,
) -> tuple[Account, Agent | None]:
    """Fetch and validate an account by plaintext API key.

    First tries the ``agents`` table (new multi-agent flow), then falls back
    to the ``accounts`` table (legacy single-account flow).

    Args:
        api_key:    The raw value from the ``X-API-Key`` header.
        repo:       AccountRepository bound to the current request's DB session.
        agent_repo: AgentRepository bound to the current request's DB session.

    Returns:
        A tuple of (Account, Agent | None).  When the key belongs to an agent,
        both are returned.  When the key belongs to a legacy account, the
        agent is ``None``.

    Raises:
        AuthenticationError:   If no account or agent exists with the given key.
        AccountSuspendedError: If the account's status is not ``"active"``.
    """
    # Try agents table first (new multi-agent flow)
    if agent_repo is not None:
        try:
            agent = await agent_repo.get_by_api_key(api_key)
            # Agent found — resolve its owning account
            try:
                account = await repo.get_by_id(agent.account_id)
            except AccountNotFoundError:
                raise AuthenticationError("Agent's owning account no longer exists.") from None

            if account.status != "active":
                raise AccountSuspendedError(account_id=account.id)
            if agent.status == "archived":
                raise AuthenticationError("Agent is archived.")

            return account, agent
        except AgentNotFoundError:
            pass  # Fall through to legacy account lookup

    # Legacy: try accounts table directly
    try:
        account = await repo.get_by_api_key(api_key)
    except AccountNotFoundError:
        raise AuthenticationError("Invalid API key.") from None

    if account.status != "active":
        raise AccountSuspendedError(account_id=account.id)

    return account, None


async def _resolve_account_from_jwt(
    token: str,
    repo: AccountRepository,
) -> Account:
    """Decode a JWT, then fetch and validate the embedded account.

    Args:
        token: The raw JWT string extracted from the ``Authorization`` header.
        repo:  An :class:`~src.database.repositories.account_repo.AccountRepository`
               bound to the current request's DB session.

    Returns:
        The authenticated :class:`~src.database.models.Account` instance.

    Raises:
        InvalidTokenError:    If the JWT signature is invalid, expired, or
                              otherwise malformed.
        AuthenticationError:  If the account embedded in the token does not
                              exist.
        AccountSuspendedError: If the account's status is not ``"active"``.
    """
    settings = get_settings()

    # verify_jwt raises InvalidTokenError on any problem
    payload = await asyncio.get_event_loop().run_in_executor(None, verify_jwt, token, settings.jwt_secret)

    try:
        account = await repo.get_by_id(payload.account_id)
    except AccountNotFoundError:
        raise AuthenticationError(f"Account '{payload.account_id}' referenced by token no longer exists.") from None

    if account.status != "active":
        raise AccountSuspendedError(account_id=account.id)

    return account


async def _authenticate_request(request: Request) -> tuple[Account | None, Agent | None]:
    """Attempt to authenticate *request* and return the resolved account and agent.

    Tries ``X-API-Key`` first, then ``Authorization: Bearer``.  Returns
    ``(None, None)`` when no credential header is present at all.

    Args:
        request: The incoming FastAPI / Starlette request object.

    Returns:
        A tuple of (Account | None, Agent | None).

    Raises:
        AuthenticationError:  On invalid/missing credentials when a header IS
                              present but resolves to no account.
        InvalidTokenError:    On a malformed or expired JWT.
        AccountSuspendedError: When the account is suspended.
    """
    from src.database.session import get_session_factory  # noqa: PLC0415

    api_key = _extract_api_key(request)
    bearer_token = _extract_bearer_token(request)

    if api_key is None and bearer_token is None:
        return None, None

    session_factory = get_session_factory()
    async with session_factory() as session:
        repo = AccountRepository(session)
        agent_repo = AgentRepository(session)

        if api_key is not None:
            return await _resolve_account_from_api_key(api_key, repo, agent_repo)

        # bearer_token is not None at this point
        assert bearer_token is not None  # noqa: S101  (for type narrowing)
        account = await _resolve_account_from_jwt(bearer_token, repo)
        return account, None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that authenticates every non-public request.

    On each request the middleware:

    1. Checks whether the path is in the public whitelist — if so, passes
       through immediately.
    2. Extracts credentials (API key or JWT) from the request headers.
    3. Resolves the account from the database.
    4. Stores the account on ``request.state.account``.
    5. Returns a ``401`` JSON error if no valid credential is provided, or a
       ``403`` if the account is suspended.

    Any other :class:`~src.utils.exceptions.TradingPlatformError` is also
    caught and serialised so the global exception handler does not need to
    handle middleware errors specially.

    Example::

        from fastapi import FastAPI
        from src.api.middleware.auth import AuthMiddleware

        app = FastAPI()
        app.add_middleware(AuthMiddleware)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process authentication before forwarding the request.

        Args:
            request:   The incoming HTTP request.
            call_next: Starlette callback to invoke the next middleware or
                       route handler.

        Returns:
            The downstream :class:`~starlette.responses.Response`, or a JSON
            error response if authentication fails.
        """
        # CORS preflight requests must pass through unauthenticated so that
        # CORSMiddleware can respond with the appropriate Allow headers.
        if request.method == "OPTIONS":
            return await call_next(request)

        if _is_public(request.url.path):
            return await call_next(request)

        try:
            account, agent = await _authenticate_request(request)
        except TradingPlatformError as exc:
            logger.warning(
                "auth.failed",
                extra={
                    "path": request.url.path,
                    "code": exc.code,
                    "error_message": exc.message,
                },
            )
            return JSONResponse(exc.to_dict(), status_code=exc.http_status)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "auth.unexpected_error",
                extra={"path": request.url.path, "error": str(exc)},
            )
            return JSONResponse(
                {"error": {"code": "INTERNAL_ERROR", "message": "Authentication service error."}},
                status_code=500,
            )

        if account is None:
            error = AuthenticationError("Authentication credentials are required.")
            return JSONResponse(error.to_dict(), status_code=error.http_status)

        request.state.account = account
        request.state.agent = agent  # May be None for legacy auth
        return await call_next(request)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_current_account(request: Request) -> Account:
    """FastAPI dependency that returns the currently authenticated account.

    Reads ``request.state.account`` populated by :class:`AuthMiddleware`.  If
    the attribute is absent (e.g. in tests where the middleware is not mounted),
    falls back to calling :func:`_authenticate_request` directly so that route
    tests that pass headers still work correctly.

    Args:
        request: Injected by FastAPI automatically.

    Returns:
        The authenticated :class:`~src.database.models.Account` ORM instance.

    Raises:
        AuthenticationError:  If no valid credential is present.
        AccountSuspendedError: If the account is suspended.
        InvalidTokenError:    If a Bearer JWT is invalid or expired.
    """
    account: Account | None = getattr(request.state, "account", None)

    if account is not None:
        return account

    # Fallback: middleware was bypassed (e.g. unit tests or direct router mount)
    try:
        resolved_account, _agent = await _authenticate_request(request)
    except TradingPlatformError:
        raise

    if resolved_account is None:
        raise AuthenticationError("Authentication credentials are required.")

    return resolved_account


async def get_current_agent(request: Request) -> Agent | None:
    """FastAPI dependency that returns the currently authenticated agent.

    Reads ``request.state.agent`` populated by :class:`AuthMiddleware`.
    For JWT auth, resolves agent from the ``X-Agent-Id`` header.

    Returns ``None`` when no agent context exists (e.g. legacy account-only auth
    or JWT auth without an agent header).

    Args:
        request: Injected by FastAPI automatically.

    Returns:
        The authenticated Agent ORM instance, or None.
    """
    agent: Agent | None = getattr(request.state, "agent", None)
    if agent is not None:
        return agent

    # For JWT auth, resolve agent from X-Agent-Id header
    agent_id_raw = request.headers.get("X-Agent-Id", "").strip()
    if agent_id_raw:
        from uuid import UUID as _UUID  # noqa: PLC0415

        from src.database.session import get_session_factory  # noqa: PLC0415

        try:
            agent_uuid = _UUID(agent_id_raw)
        except ValueError:
            return None

        session_factory = get_session_factory()
        async with session_factory() as session:
            agent_repo = AgentRepository(session)
            try:
                return await agent_repo.get_by_id(agent_uuid)
            except AgentNotFoundError:
                return None

    return None


# Convenience type aliases for use in route signatures.
CurrentAccountDep = Annotated[Account, Depends(get_current_account)]
CurrentAgentDep = Annotated[Agent | None, Depends(get_current_agent)]
