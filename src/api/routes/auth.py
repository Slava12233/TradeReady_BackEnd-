"""Authentication routes for the AI Agent Crypto Trading Platform.

Implements the following endpoints (Section 15.1 of the development plan):

- ``POST /api/v1/auth/register`` — create a new agent account, returns API
  credentials shown exactly once.
- ``POST /api/v1/auth/login`` — exchange an API key + secret for a signed JWT
  bearer token.

Both endpoints are **public** (no authentication middleware required) and are
listed in the whitelist inside :mod:`src.api.middleware.auth`.

Example::

    # Register a new bot account
    POST /api/v1/auth/register
    {"display_name": "AlphaBot", "email": "alpha@example.com", "starting_balance": "10000.00"}

    # Obtain a JWT token
    POST /api/v1/auth/login
    {"api_key": "ak_live_...", "api_secret": "sk_live_..."}
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, status

from src.accounts.auth import create_jwt, verify_api_secret
from src.api.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserLoginRequest,
)
from src.dependencies import AccountServiceDep, SettingsDep
from src.utils.exceptions import AuthenticationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# POST /api/v1/auth/register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agent account",
    description=(
        "Creates a new virtual-trading agent account.  Returns the plaintext "
        "API key and secret **once only** — store the secret immediately."
    ),
)
async def register(
    body: RegisterRequest,
    svc: AccountServiceDep,
) -> RegisterResponse:
    """Register a new account and return one-time credentials.

    The caller must create an agent explicitly via ``POST /api/v1/agents``
    before trading.

    Args:
        body: Validated registration payload (display_name, email, starting_balance).
        svc:  Injected :class:`~src.accounts.service.AccountService`.

    Returns:
        :class:`~src.api.schemas.auth.RegisterResponse` with the new
        account UUID, API key, API secret (plaintext, **shown once**),
        display name, and starting balance.

    Raises:
        :exc:`~src.utils.exceptions.DuplicateAccountError`: If the email is
            already registered (HTTP 409).
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected
            database failure (HTTP 500).

    Example::

        POST /api/v1/auth/register
        {
            "display_name": "AlphaBot",
            "email": "alpha@example.com",
            "starting_balance": "25000.00"
        }
        →  HTTP 201
        {
            "account_id": "550e8400-...",
            "api_key": "ak_live_...",
            "api_secret": "sk_live_...",
            "display_name": "AlphaBot",
            "starting_balance": "25000.00",
            "message": "Save your API secret now. It will not be shown again."
        }
    """
    creds = await svc.register(
        body.display_name,
        email=str(body.email) if body.email else None,
        starting_balance=body.starting_balance,
        password=body.password,
    )

    logger.info(
        "auth.register.success",
        extra={
            "account_id": str(creds.account_id),
            "display_name": creds.display_name,
        },
    )

    return RegisterResponse(
        account_id=creds.account_id,
        api_key=creds.api_key,
        api_secret=creds.api_secret,
        display_name=creds.display_name,
        starting_balance=creds.starting_balance,
        agent_id=creds.agent_id,
        agent_api_key=creds.agent_api_key,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain a JWT bearer token",
    description=(
        "Exchanges a valid API key + secret pair for a signed HS256 JWT token. "
        "Include the returned token in subsequent requests as "
        "``Authorization: Bearer <token>``."
    ),
)
async def login(
    body: LoginRequest,
    svc: AccountServiceDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Authenticate with an API key + secret and return a JWT token.

    Steps:
    1. Look up the account by ``api_key`` and verify the bcrypt hash
       (delegates to :meth:`~src.accounts.service.AccountService.authenticate`).
    2. Verify the ``api_secret`` against its stored bcrypt hash
       (CPU-bound — offloaded to a thread pool via ``asyncio.get_event_loop().run_in_executor``).
    3. Issue a signed JWT with ``expiry_hours`` from settings.

    Args:
        body:     Validated login payload (api_key, api_secret).
        svc:      Injected :class:`~src.accounts.service.AccountService`.
        settings: Injected :class:`~src.config.Settings` (provides
                  ``jwt_secret`` and ``jwt_expiry_hours``).

    Returns:
        :class:`~src.api.schemas.auth.TokenResponse` with the signed JWT,
        its expiry datetime, and token type ``"Bearer"``.

    Raises:
        :exc:`~src.utils.exceptions.AuthenticationError`: If the API key or
            secret is invalid (HTTP 401).
        :exc:`~src.utils.exceptions.AccountSuspendedError`: If the account is
            suspended or archived (HTTP 403).
        :exc:`~src.utils.exceptions.AccountNotFoundError`: If no account owns
            the provided API key (HTTP 404).

    Example::

        POST /api/v1/auth/login
        {"api_key": "ak_live_...", "api_secret": "sk_live_..."}
        →  HTTP 200
        {
            "token": "eyJhbGci...",
            "expires_at": "2026-02-24T13:00:00Z",
            "token_type": "Bearer"
        }
    """
    # Step 1: verify api_key via bcrypt (also checks account is active)
    account = await svc.authenticate(body.api_key)

    # Step 2: verify api_secret (bcrypt is CPU-bound — use thread pool)
    loop = asyncio.get_event_loop()
    secret_valid: bool = await loop.run_in_executor(
        None,
        verify_api_secret,
        body.api_secret,
        account.api_secret_hash,
    )
    if not secret_valid:
        logger.warning(
            "auth.login.invalid_secret",
            extra={"account_id": str(account.id)},
        )
        raise AuthenticationError("API secret is invalid.")

    # Step 3: issue JWT (also CPU-bound but fast at ~1ms; run synchronously)
    token_str = create_jwt(
        account_id=account.id,
        jwt_secret=settings.jwt_secret,
        expiry_hours=settings.jwt_expiry_hours,
    )

    # Decode expires_at from the token payload for the response
    from src.accounts.auth import verify_jwt  # noqa: PLC0415

    jwt_payload = verify_jwt(token_str, settings.jwt_secret)

    logger.info(
        "auth.login.success",
        extra={
            "account_id": str(account.id),
            "expires_at": jwt_payload.expires_at.isoformat(),
        },
    )

    return TokenResponse(
        token=token_str,
        expires_at=jwt_payload.expires_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/user-login
# ---------------------------------------------------------------------------


@router.post(
    "/user-login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate a human user with email + password",
    description=(
        "Exchanges a valid email + password pair for a signed HS256 JWT token. "
        "Intended for human users accessing the platform via a browser; AI agents "
        "should continue using ``POST /api/v1/auth/login`` with API key + secret. "
        "Include the returned token in subsequent requests as "
        "``Authorization: Bearer <token>``."
    ),
)
async def user_login(
    body: UserLoginRequest,
    svc: AccountServiceDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Authenticate a human user with email and password, returning a JWT token.

    Steps:
    1. Look up the account by ``email`` and verify the bcrypt password hash
       (delegates to :meth:`~src.accounts.service.AccountService.authenticate_with_password`).
    2. Issue a signed JWT with ``expiry_hours`` from settings.

    Args:
        body:     Validated login payload (email, password).
        svc:      Injected :class:`~src.accounts.service.AccountService`.
        settings: Injected :class:`~src.config.Settings` (provides
                  ``jwt_secret`` and ``jwt_expiry_hours``).

    Returns:
        :class:`~src.api.schemas.auth.TokenResponse` with the signed JWT,
        its expiry datetime, and token type ``"Bearer"``.

    Raises:
        :exc:`~src.utils.exceptions.AuthenticationError`: If the email is not
            registered, the account has no password set, or the password is
            incorrect (HTTP 401).
        :exc:`~src.utils.exceptions.AccountSuspendedError`: If the account is
            suspended or archived (HTTP 403).

    Example::

        POST /api/v1/auth/user-login
        {"email": "alice@example.com", "password": "s3cur3P@ssw0rd"}
        →  HTTP 200
        {
            "token": "eyJhbGci...",
            "expires_at": "2026-02-24T13:00:00Z",
            "token_type": "Bearer"
        }
    """
    account = await svc.authenticate_with_password(str(body.email), body.password)

    token_str = create_jwt(
        account_id=account.id,
        jwt_secret=settings.jwt_secret,
        expiry_hours=settings.jwt_expiry_hours,
    )

    from src.accounts.auth import verify_jwt  # noqa: PLC0415

    jwt_payload = verify_jwt(token_str, settings.jwt_secret)

    logger.info(
        "auth.user_login.success",
        extra={
            "account_id": str(account.id),
            "expires_at": jwt_payload.expires_at.isoformat(),
        },
    )

    return TokenResponse(
        token=token_str,
        expires_at=jwt_payload.expires_at,
    )
