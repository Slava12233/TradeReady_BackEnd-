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
from typing import Any
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


# ---------------------------------------------------------------------------
# Decision trace & analysis schemas
# ---------------------------------------------------------------------------


class StrategySignalItem(_BaseSchema):
    """A single strategy signal captured before ensemble combination.

    Attributes:
        id:            Signal row UUID.
        trace_id:      Hex trace identifier grouping signals to one decision cycle.
        strategy_name: Name of the strategy component (e.g. ``"ppo_rl"``).
        symbol:        Trading pair this signal applies to.
        action:        Recommended action: ``"buy"``, ``"sell"``, or ``"hold"``.
        confidence:    Strategy-reported confidence score in [0, 1] (nullable).
        weight:        Ensemble weight assigned to this strategy (nullable).
        signal_data:   Strategy-specific indicator values and metadata.
        created_at:    UTC timestamp of the signal.
    """

    id: UUID
    trace_id: str
    strategy_name: str
    symbol: str
    action: str
    confidence: Decimal | None = None
    weight: Decimal | None = None
    signal_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_serializer("confidence", "weight")
    def _serialize_decimal(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


class DecisionItem(_BaseSchema):
    """A single agent decision within a trace response.

    Attributes:
        id:                  Decision UUID.
        agent_id:            Owning agent UUID.
        trace_id:            Hex trace identifier (nullable).
        decision_type:       High-level action: ``"trade"``, ``"hold"``, ``"exit"``,
                             or ``"rebalance"``.
        symbol:              Trading pair affected (nullable).
        direction:           Intended direction: ``"buy"``, ``"sell"``, or ``"hold"``.
        confidence:          Model confidence score in [0, 1] (nullable).
        reasoning:           Free-text explanation (nullable).
        market_snapshot:     JSONB snapshot of prices/indicators at decision time.
        risk_assessment:     JSONB output from the risk overlay pipeline.
        order_id:            Linked order UUID (nullable).
        outcome_pnl:         Realised PnL of the linked order (nullable).
        outcome_recorded_at: UTC timestamp when outcome was written back (nullable).
        created_at:          UTC timestamp of decision creation.
    """

    id: UUID
    agent_id: UUID
    trace_id: str | None = None
    decision_type: str
    symbol: str | None = None
    direction: str
    confidence: Decimal | None = None
    reasoning: str | None = None
    market_snapshot: dict[str, Any] | None = None
    risk_assessment: dict[str, Any] | None = None
    order_id: UUID | None = None
    outcome_pnl: Decimal | None = None
    outcome_recorded_at: datetime | None = None
    created_at: datetime

    @field_serializer("confidence", "outcome_pnl")
    def _serialize_decimal(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


class OrderSummary(_BaseSchema):
    """Compact order summary embedded in a decision trace response.

    Attributes:
        id:             Order UUID.
        symbol:         Trading pair.
        side:           ``"buy"`` or ``"sell"``.
        type:           Order type (``"market"``, ``"limit"``, etc.).
        quantity:       Requested quantity.
        executed_price: Actual fill price (nullable).
        executed_qty:   Actual filled quantity (nullable).
        fee:            Simulated fee (nullable).
        status:         Order status.
        created_at:     UTC timestamp of order submission.
        filled_at:      UTC timestamp of fill (nullable).
    """

    id: UUID
    symbol: str
    side: str
    type: str
    quantity: Decimal
    executed_price: Decimal | None = None
    executed_qty: Decimal | None = None
    fee: Decimal | None = None
    status: str
    created_at: datetime
    filled_at: datetime | None = None

    @field_serializer("quantity", "executed_price", "executed_qty", "fee")
    def _serialize_decimal(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


class TradeSummary(_BaseSchema):
    """Compact trade fill summary embedded in a decision trace response.

    Attributes:
        id:           Trade UUID.
        symbol:       Trading pair.
        side:         ``"buy"`` or ``"sell"``.
        quantity:     Filled quantity.
        price:        Execution price.
        quote_amount: ``quantity * price``.
        fee:          Simulated fee.
        realized_pnl: Realised PnL if this trade closed a position (nullable).
        created_at:   UTC timestamp of fill.
    """

    id: UUID
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    quote_amount: Decimal
    fee: Decimal
    realized_pnl: Decimal | None = None
    created_at: datetime

    @field_serializer("quantity", "price", "quote_amount", "fee", "realized_pnl")
    def _serialize_decimal(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


class ApiCallItem(_BaseSchema):
    """A single outbound API call made during a decision trace.

    Attributes:
        id:            Call UUID.
        trace_id:      Hex trace identifier.
        channel:       Transport layer: ``"sdk"``, ``"mcp"``, ``"rest"``, or ``"db"``.
        endpoint:      URL path or tool name.
        method:        HTTP verb (nullable for non-HTTP channels).
        status_code:   HTTP response code (nullable for non-HTTP channels).
        latency_ms:    Round-trip latency in milliseconds.
        request_size:  Request body size in bytes (nullable).
        response_size: Response body size in bytes (nullable).
        error:         Error message if the call failed (nullable).
        created_at:    UTC timestamp of the call.
    """

    id: UUID
    trace_id: str
    channel: str
    endpoint: str
    method: str | None = None
    status_code: int | None = None
    latency_ms: Decimal
    request_size: int | None = None
    response_size: int | None = None
    error: str | None = None
    created_at: datetime

    @field_serializer("latency_ms")
    def _serialize_latency(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class DecisionTraceResponse(_BaseSchema):
    """Full decision chain for a single trace.

    Aggregates every entity produced during one agent decision cycle
    (identified by ``trace_id``):  strategy signals from each ensemble
    component, the final fused decision, all outbound API calls, and —
    if the decision led to a trade — the order and fill details.

    Attributes:
        trace_id:  Hex trace identifier linking all rows together.
        signals:   Strategy signals from each ensemble component, ordered
                   by creation time.
        decision:  The fused agent decision (nullable if the agent decided
                   to hold without recording a decision row).
        api_calls: Outbound API/tool calls made during this cycle, ordered
                   by creation time.
        order:     The order placed by this decision (nullable).
        trade:     The trade fill for the order (nullable).
        pnl:       Realised PnL string once the order settles (nullable).
    """

    trace_id: str = Field(
        ...,
        description="Hex trace identifier linking all rows in this decision cycle.",
        examples=["a1b2c3d4e5f67890"],
    )
    signals: list[StrategySignalItem] = Field(
        default_factory=list,
        description="Strategy signals from each ensemble component.",
    )
    decision: DecisionItem | None = Field(
        default=None,
        description="The fused agent decision for this trace.",
    )
    api_calls: list[ApiCallItem] = Field(
        default_factory=list,
        description="Outbound API/tool calls made during this decision cycle.",
    )
    order: OrderSummary | None = Field(
        default=None,
        description="Order placed by this decision (null if decision_type is hold).",
    )
    trade: TradeSummary | None = Field(
        default=None,
        description="Trade fill for the order (null if order not yet filled).",
    )
    pnl: str | None = Field(
        default=None,
        description="Realised PnL once the order settles (null while pending).",
    )


class DirectionStats(_BaseSchema):
    """Win/loss breakdown for a single trade direction.

    Attributes:
        total:          Total decisions in this direction.
        wins:           Decisions with positive outcome PnL.
        losses:         Decisions with negative outcome PnL.
        win_rate:       Fraction of total that are wins, in [0, 1].
        avg_pnl:        Average outcome PnL (string-serialised Decimal, nullable).
        avg_confidence: Average model confidence (string-serialised Decimal, nullable).
    """

    total: int
    wins: int
    losses: int
    win_rate: float
    avg_pnl: str | None = None
    avg_confidence: str | None = None


class DecisionSummaryStats(_BaseSchema):
    """Aggregate statistics for a filtered set of agent decisions.

    Attributes:
        total:          Total matching decisions.
        wins:           Decisions with positive outcome PnL.
        losses:         Decisions with negative outcome PnL.
        win_rate:       Fraction of total with positive outcome.
        avg_pnl:        Average outcome PnL across all decisions (nullable).
        avg_confidence: Average model confidence (nullable).
        by_direction:   Per-direction breakdown keyed by ``"buy"`` / ``"sell"``
                        / ``"hold"``.
    """

    total: int
    wins: int
    losses: int
    win_rate: float
    avg_pnl: str | None = None
    avg_confidence: str | None = None
    by_direction: dict[str, DirectionStats] = Field(default_factory=dict)


class DecisionAnalysisResponse(_BaseSchema):
    """Analysis response for ``GET /api/v1/agents/{agent_id}/decisions/analyze``.

    Attributes:
        total:          Total decisions matching the applied filters.
        wins:           Decisions with positive outcome PnL.
        losses:         Decisions with negative outcome PnL.
        win_rate:       Fraction of total with positive outcome.
        avg_pnl:        Average outcome PnL (nullable).
        avg_confidence: Average model confidence (nullable).
        by_direction:   Per-direction stats breakdown.
        decisions:      The matched decision rows (newest first).
    """

    total: int = Field(..., description="Total decisions matching the filters.", examples=[150])
    wins: int = Field(..., description="Decisions with positive outcome PnL.", examples=[90])
    losses: int = Field(..., description="Decisions with negative outcome PnL.", examples=[60])
    win_rate: float = Field(
        ...,
        description="Fraction of total decisions that are wins (outcome_pnl > 0).",
        examples=[0.60],
    )
    avg_pnl: str | None = Field(
        default=None,
        description="Average outcome PnL across filtered decisions (null if no outcomes recorded).",
        examples=["5.23"],
    )
    avg_confidence: str | None = Field(
        default=None,
        description="Average model confidence across filtered decisions.",
        examples=["0.72"],
    )
    by_direction: dict[str, DirectionStats] = Field(
        default_factory=dict,
        description="Per-direction win/loss breakdown keyed by 'buy', 'sell', or 'hold'.",
    )
    decisions: list[DecisionItem] = Field(
        default_factory=list,
        description="Matched decision rows, newest first.",
    )


# ---------------------------------------------------------------------------
# Feedback lifecycle
# ---------------------------------------------------------------------------

#: Valid status values for the feedback lifecycle state machine.
_FEEDBACK_STATUS_VALUES: frozenset[str] = frozenset(
    {"submitted", "acknowledged", "in_progress", "resolved", "wont_fix"}
)


class UpdateFeedbackRequest(_BaseSchema):
    """Request body for ``PATCH /api/v1/agents/{agent_id}/feedback/{feedback_id}``.

    Attributes:
        status:     New lifecycle status.  Must be one of ``submitted``,
                    ``acknowledged``, ``in_progress``, ``resolved``, or
                    ``wont_fix``.
        resolution: Optional short description of how the feedback was
                    resolved or why it was closed.  Recommended when
                    ``status`` is ``resolved`` or ``wont_fix``.
    """

    status: str = Field(
        ...,
        description=(
            "New lifecycle status for the feedback item. "
            "Allowed values: submitted, acknowledged, in_progress, resolved, wont_fix."
        ),
        examples=["resolved"],
    )
    resolution: str | None = Field(
        default=None,
        description="Short description of the resolution (optional).",
        examples=["Fixed in commit abc123"],
    )

    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status against allowed lifecycle values."""
        if v not in _FEEDBACK_STATUS_VALUES:
            allowed = ", ".join(sorted(_FEEDBACK_STATUS_VALUES))
            raise ValueError(f"status must be one of: {allowed}")
        return v

    def model_post_init(self, __context: object) -> None:
        """Run cross-field validation after model initialization."""
        if self.status not in _FEEDBACK_STATUS_VALUES:
            allowed = ", ".join(sorted(_FEEDBACK_STATUS_VALUES))
            raise ValueError(f"status must be one of: {allowed}")


class FeedbackResponse(_BaseSchema):
    """Response body for feedback lifecycle update.

    Attributes:
        id:          Feedback item UUID.
        agent_id:    Owning agent UUID.
        status:      Current lifecycle status.
        resolution:  Resolution text (nullable).
        resolved_at: UTC timestamp set when status becomes ``resolved`` (nullable).
        updated:     Always ``true`` on a successful PATCH response.
    """

    id: UUID
    agent_id: UUID
    status: str = Field(description="Current lifecycle status of this feedback item.")
    resolution: str | None = Field(
        default=None,
        description="Resolution text (null if not yet resolved).",
    )
    resolved_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the item was resolved (null if still open).",
    )
    updated: bool = Field(default=True, description="Always true on a successful update.")
