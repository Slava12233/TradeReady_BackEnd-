"""Pydantic v2 request/response schemas for authentication endpoints.

Covers the following REST endpoints (Section 15.1):
- ``POST /api/v1/auth/register``
- ``POST /api/v1/auth/login``

All ``Decimal`` fields are serialised as strings in JSON responses to preserve
full 8-decimal precision without floating-point rounding.

Example::

    from src.api.schemas.auth import RegisterRequest, RegisterResponse

    req = RegisterRequest(display_name="MyBot", email="dev@example.com")
    # → starting_balance defaults to Decimal("10000.00")
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer

# ---------------------------------------------------------------------------
# Shared config mixin
# ---------------------------------------------------------------------------


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class RegisterRequest(_BaseSchema):
    """Request body for ``POST /api/v1/auth/register``.

    Attributes:
        display_name:     Human-readable name for the agent account (required).
        email:            Optional contact email; stored but not validated for
                          uniqueness at this layer.
        password:         Optional plaintext password (min 8 chars). When provided,
                          a bcrypt hash is stored and the account can authenticate
                          via ``POST /api/v1/auth/user-login``.
        starting_balance: Initial virtual USDT balance.  Defaults to 10 000 USDT.
    """

    display_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable name for the agent account.",
        examples=["MyTradingBot"],
    )
    email: EmailStr | None = Field(
        default=None,
        description="Optional contact email address.",
        examples=["dev@example.com"],
    )
    password: str | None = Field(
        default=None,
        min_length=8,
        description="Optional password (min 8 chars) for human user login.",
        examples=["s3cur3P@ssw0rd"],
    )
    starting_balance: Decimal = Field(
        default=Decimal("10000.00"),
        gt=Decimal("0"),
        description="Initial virtual USDT balance (must be > 0).",
        examples=[10000.00],
    )

    @field_serializer("starting_balance")
    def _serialize_balance(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class RegisterResponse(_BaseSchema):
    """Response body for ``POST /api/v1/auth/register`` (HTTP 201).

    The ``api_secret`` is returned **once only**.  The caller must store it
    securely; it cannot be recovered after registration.

    Attributes:
        account_id:       UUID of the newly created account.
        api_key:          Plaintext API key with ``ak_live_`` prefix.
        api_secret:       Plaintext API secret with ``sk_live_`` prefix — shown
                          once and never stored in plaintext.
        display_name:     The registered display name.
        starting_balance: Virtual USDT balance the account was seeded with.
        message:          Advisory message reminding the caller to save the secret.
    """

    account_id: UUID = Field(
        ...,
        description="UUID of the newly created account.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    api_key: str = Field(
        ...,
        description="Plaintext API key (ak_live_ prefix). Use in X-API-Key header.",
        examples=["ak_live_EXAMPLE_KEY_REPLACE_ME"],
    )
    api_secret: str = Field(
        ...,
        description="Plaintext API secret (sk_live_ prefix). Shown once only.",
        examples=["sk_EXAMPLE_SECRET_REPLACE_ME"],
    )
    display_name: str = Field(
        ...,
        description="Registered display name.",
        examples=["MyTradingBot"],
    )
    starting_balance: Decimal = Field(
        ...,
        description="Initial virtual USDT balance.",
        examples=["10000.00"],
    )
    message: str = Field(
        default="Save your API secret now. It will not be shown again.",
        description="Advisory message for the caller.",
    )

    @field_serializer("starting_balance")
    def _serialize_balance(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Login / JWT
# ---------------------------------------------------------------------------


class LoginRequest(_BaseSchema):
    """Request body for ``POST /api/v1/auth/login``.

    Attributes:
        api_key:    The plaintext ``ak_live_`` API key.
        api_secret: The plaintext ``sk_live_`` API secret.
    """

    api_key: str = Field(
        ...,
        min_length=1,
        description="Plaintext API key (ak_live_ prefix).",
        examples=["ak_live_EXAMPLE_KEY_REPLACE_ME"],
    )
    api_secret: str = Field(
        ...,
        min_length=1,
        description="Plaintext API secret (sk_live_ prefix).",
        examples=["sk_EXAMPLE_SECRET_REPLACE_ME"],
    )


class UserLoginRequest(_BaseSchema):
    """Request body for ``POST /api/v1/auth/user-login``.

    Used by human users authenticating with email + password instead of
    API key / secret.  On success the endpoint returns a ``TokenResponse``
    identical to the agent login flow.

    Attributes:
        email:    Registered email address of the human user account.
        password: Plaintext password (min 8 chars).
    """

    email: EmailStr = Field(
        ...,
        description="Registered email address.",
        examples=["alice@example.com"],
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Plaintext password (min 8 chars).",
        examples=["s3cur3P@ssw0rd"],
    )


class TokenResponse(_BaseSchema):
    """Response body for ``POST /api/v1/auth/login`` (HTTP 200).

    Attributes:
        token:      Signed HS256 JWT bearer token.
        expires_at: UTC datetime when the token expires.
        token_type: Always ``"Bearer"``; included for OAuth 2.0 compatibility.
    """

    token: str = Field(
        ...,
        description="Signed JWT token. Include as 'Authorization: Bearer <token>'.",
        examples=["eyJhbGciOiJIUzI1NiIs..."],
    )
    expires_at: datetime = Field(
        ...,
        description="UTC datetime when the token expires.",
        examples=["2026-02-24T12:00:00Z"],
    )
    token_type: str = Field(
        default="Bearer",
        description="Token type for OAuth 2.0 compatibility.",
        examples=["Bearer"],
    )
