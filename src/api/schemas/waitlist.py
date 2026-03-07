"""Pydantic v2 request/response schemas for the waitlist endpoint.

Covers ``POST /api/v1/waitlist/subscribe``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class WaitlistRequest(_BaseSchema):
    """Request body for ``POST /api/v1/waitlist/subscribe``.

    Attributes:
        email:  Email address to add to the waitlist.
        source: Which landing-page form submitted the entry.
    """

    email: EmailStr = Field(
        ...,
        description="Email address to add to the waitlist.",
        examples=["dev@example.com"],
    )
    source: str = Field(
        default="landing",
        max_length=50,
        description="Which form submitted the entry (e.g. 'hero', 'cta').",
        examples=["hero"],
    )


class WaitlistResponse(_BaseSchema):
    """Response body for ``POST /api/v1/waitlist/subscribe`` (HTTP 201).

    Attributes:
        message: Confirmation message.
    """

    message: str = Field(
        default="You're on the list!",
        description="Confirmation message.",
    )
