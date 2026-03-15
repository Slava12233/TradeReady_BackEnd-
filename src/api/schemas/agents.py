"""Pydantic v2 request/response schemas for agent endpoints.

Covers:
- ``POST /api/v1/agents`` — create agent
- ``GET /api/v1/agents`` — list agents
- ``GET /api/v1/agents/{agent_id}`` — get agent
- ``PUT /api/v1/agents/{agent_id}`` — update agent
- ``POST /api/v1/agents/{agent_id}/clone`` — clone agent
- ``POST /api/v1/agents/{agent_id}/regenerate-key`` — regenerate API key
- ``GET /api/v1/agents/overview`` — agent overview
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class AgentCreate(_BaseSchema):
    """Request body for ``POST /api/v1/agents``.

    Attributes:
        display_name:     Human-readable name for the agent (required).
        starting_balance: Initial virtual USDT balance (defaults to 10000).
        llm_model:        LLM model name.
        framework:        Agent framework.
        strategy_tags:    List of strategy descriptors.
        risk_profile:     Risk limit overrides.
        color:            Hex color code for UI.
    """

    display_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable name for the agent.",
        examples=["AlphaBot"],
    )
    starting_balance: Decimal = Field(
        default=Decimal("10000.00"),
        gt=Decimal("0"),
        description="Initial virtual USDT balance (must be > 0).",
        examples=[10000.00],
    )
    llm_model: str | None = Field(
        default=None,
        max_length=100,
        description="LLM model name (e.g. 'gpt-4o', 'claude-opus-4-20250514').",
        examples=["gpt-4o"],
    )
    framework: str | None = Field(
        default=None,
        max_length=100,
        description="Agent framework (e.g. 'langchain', 'custom').",
        examples=["langchain"],
    )
    strategy_tags: list[str] = Field(
        default_factory=list,
        description="List of strategy descriptors.",
        examples=[["momentum", "mean-reversion"]],
    )
    risk_profile: dict[str, object] = Field(
        default_factory=dict,
        description="Per-agent risk limit overrides.",
    )
    color: str | None = Field(
        default=None,
        max_length=7,
        description="Hex color code for UI identification.",
        examples=["#FF5733"],
    )

    @field_serializer("starting_balance")
    def _serialize_balance(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class AgentUpdate(_BaseSchema):
    """Request body for ``PUT /api/v1/agents/{agent_id}``."""

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    llm_model: str | None = Field(default=None, max_length=100)
    framework: str | None = Field(default=None, max_length=100)
    strategy_tags: list[str] | None = Field(default=None)
    risk_profile: dict[str, object] | None = Field(default=None)
    color: str | None = Field(default=None, max_length=7)
    avatar_url: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class AgentResponse(_BaseSchema):
    """Response schema for a single agent."""

    id: UUID
    account_id: UUID
    display_name: str
    api_key_preview: str = Field(description="First 12 chars of the API key (masked).")
    starting_balance: Decimal
    llm_model: str | None = None
    framework: str | None = None
    strategy_tags: list[str] = Field(default_factory=list)
    risk_profile: dict[str, object] = Field(default_factory=dict)
    avatar_url: str | None = None
    color: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("starting_balance")
    def _serialize_balance(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class AgentListResponse(_BaseSchema):
    """Response for ``GET /api/v1/agents``."""

    agents: list[AgentResponse]
    total: int


class AgentCredentialsResponse(_BaseSchema):
    """Response for agent creation — includes plaintext API key (shown once)."""

    agent_id: UUID
    api_key: str = Field(description="Plaintext API key. Save now — shown once only.")
    display_name: str
    starting_balance: Decimal
    message: str = Field(default="Save your API key now. It will not be shown again.")

    @field_serializer("starting_balance")
    def _serialize_balance(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class AgentOverviewResponse(_BaseSchema):
    """Response for ``GET /api/v1/agents/overview``."""

    agents: list[AgentResponse]


class AgentKeyResponse(_BaseSchema):
    """Response for ``POST /api/v1/agents/{agent_id}/regenerate-key``."""

    agent_id: UUID
    api_key: str = Field(description="New plaintext API key. Save now — shown once only.")
    message: str = Field(default="API key regenerated. Save now — it will not be shown again.")
