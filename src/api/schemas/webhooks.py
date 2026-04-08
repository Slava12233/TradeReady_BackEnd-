"""Pydantic v2 request/response schemas for webhook subscription endpoints.

Covers create, list, detail, update, delete, and test endpoints under
``/api/v1/webhooks``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.webhooks.dispatcher import validate_webhook_url

# ---------------------------------------------------------------------------
# Supported events
# ---------------------------------------------------------------------------

SUPPORTED_EVENTS: frozenset[str] = frozenset(
    {
        "backtest.completed",
        "strategy.test.completed",
        "strategy.deployed",
        "battle.completed",
    }
)


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class WebhookCreateRequest(_BaseSchema):
    """Request body for ``POST /api/v1/webhooks``."""

    url: str = Field(
        ...,
        max_length=2048,
        description="HTTPS endpoint that will receive webhook payloads.",
        examples=["https://example.com/webhooks"],
    )
    events: list[str] = Field(
        ...,
        min_length=1,
        description=(f"List of event names to subscribe to. Supported: {sorted(SUPPORTED_EVENTS)}"),
        examples=[["backtest.completed", "strategy.deployed"]],
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="Optional human-readable label for this subscription.",
        examples=["My production webhook"],
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Reject URLs that could be used for SSRF attacks.

        Calls :func:`~src.webhooks.dispatcher.validate_webhook_url` which
        enforces ``https``-only scheme, rejects bare IP literals, and resolves
        the hostname to ensure none of the returned addresses fall within
        loopback, link-local, RFC-1918 private, Docker bridge, or cloud
        metadata IP ranges.

        Args:
            value: Raw URL string from the request body.

        Returns:
            The validated URL string.

        Raises:
            ValueError: If the URL fails any SSRF safety check.
        """
        return validate_webhook_url(value)

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str]) -> list[str]:
        """Reject any event name that is not in the supported set.

        Args:
            value: Raw list of event name strings from the request body.

        Returns:
            The validated list of event names.

        Raises:
            ValueError: If any event name is not supported.
        """
        unknown = sorted(set(value) - SUPPORTED_EVENTS)
        if unknown:
            raise ValueError(f"Unsupported event(s): {unknown}. Supported events: {sorted(SUPPORTED_EVENTS)}")
        return value


class WebhookUpdateRequest(_BaseSchema):
    """Request body for ``PUT /api/v1/webhooks/{webhook_id}``."""

    url: str | None = Field(
        default=None,
        max_length=2048,
        description="New HTTPS endpoint URL.",
        examples=["https://example.com/webhooks/v2"],
    )
    events: list[str] | None = Field(
        default=None,
        min_length=1,
        description="Replacement event list.",
        examples=[["backtest.completed"]],
    )
    active: bool | None = Field(
        default=None,
        description="Enable or disable the subscription.",
        examples=[True],
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="New description label.",
        examples=["Updated webhook"],
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        """Reject URLs that could be used for SSRF attacks when provided.

        Calls :func:`~src.webhooks.dispatcher.validate_webhook_url` which
        enforces ``https``-only scheme, rejects bare IP literals, and resolves
        the hostname to ensure none of the returned addresses fall within
        loopback, link-local, RFC-1918 private, Docker bridge, or cloud
        metadata IP ranges.

        Args:
            value: Optional raw URL string from the request body.

        Returns:
            The validated URL string, or ``None`` if not provided.

        Raises:
            ValueError: If the URL fails any SSRF safety check.
        """
        if value is None:
            return None
        return validate_webhook_url(value)

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str] | None) -> list[str] | None:
        """Reject unsupported event names when provided.

        Args:
            value: Optional list of event name strings.

        Returns:
            The validated list, or ``None`` if not provided.

        Raises:
            ValueError: If any event name is not supported.
        """
        if value is None:
            return None
        unknown = sorted(set(value) - SUPPORTED_EVENTS)
        if unknown:
            raise ValueError(f"Unsupported event(s): {unknown}. Supported events: {sorted(SUPPORTED_EVENTS)}")
        return value


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class WebhookCreateResponse(_BaseSchema):
    """Response body for ``POST /api/v1/webhooks``.

    Includes the HMAC-SHA256 ``secret`` — shown **only once** at creation.
    The caller must store it immediately; it cannot be retrieved again.
    """

    id: UUID = Field(..., description="Webhook subscription UUID.")
    url: str = Field(..., description="Target HTTPS endpoint URL.")
    events: list[str] = Field(..., description="Subscribed event names.")
    description: str | None = Field(default=None, description="Optional label.")
    active: bool = Field(..., description="Whether the subscription is active.")
    secret: str = Field(
        ...,
        description=(
            "HMAC-SHA256 signing secret — shown ONLY at creation. Use this to verify incoming webhook payloads."
        ),
    )
    created_at: datetime = Field(..., description="UTC timestamp of creation.")


class WebhookResponse(_BaseSchema):
    """Response body for list, detail, and update endpoints.

    The ``secret`` is intentionally omitted from this schema.
    """

    id: UUID = Field(..., description="Webhook subscription UUID.")
    url: str = Field(..., description="Target HTTPS endpoint URL.")
    events: list[str] = Field(..., description="Subscribed event names.")
    description: str | None = Field(default=None, description="Optional label.")
    active: bool = Field(..., description="Whether the subscription is active.")
    failure_count: int = Field(
        ...,
        description="Consecutive delivery failure count. Reset on success.",
    )
    created_at: datetime = Field(..., description="UTC timestamp of creation.")
    updated_at: datetime = Field(..., description="UTC timestamp of last update.")
    last_triggered_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the most recent delivery attempt.",
    )


class WebhookListResponse(_BaseSchema):
    """Response body for ``GET /api/v1/webhooks``."""

    webhooks: list[WebhookResponse] = Field(
        default_factory=list,
        description="List of webhook subscriptions.",
    )
    total: int = Field(..., description="Total number of subscriptions for the account.")
