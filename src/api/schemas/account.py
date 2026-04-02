"""Pydantic v2 request/response schemas for account endpoints.

Covers the following REST endpoints (Section 15.4):
- ``GET  /api/v1/account/info``
- ``GET  /api/v1/account/balance``
- ``GET  /api/v1/account/positions``
- ``GET  /api/v1/account/portfolio``
- ``GET  /api/v1/account/pnl``
- ``POST /api/v1/account/reset``

All ``Decimal`` price/quantity/balance fields serialise as strings to preserve
full 8-decimal precision without floating-point rounding.

Example::

    from src.api.schemas.account import AccountInfoResponse, BalancesResponse

    info = AccountInfoResponse(
        account_id=uuid4(),
        display_name="MyBot",
        status="active",
        starting_balance=Decimal("10000.00"),
        current_session=SessionInfo(
            session_id=uuid4(),
            started_at=datetime.utcnow(),
        ),
        risk_profile=RiskProfileInfo(
            max_position_size_pct=25,
            daily_loss_limit_pct=20,
            max_open_orders=50,
        ),
        created_at=datetime.utcnow(),
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ---------------------------------------------------------------------------
# Shared config base
# ---------------------------------------------------------------------------


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Nested info models for AccountInfoResponse
# ---------------------------------------------------------------------------


class SessionInfo(_BaseSchema):
    """Nested session details embedded in ``AccountInfoResponse``.

    Attributes:
        session_id: UUID of the current trading session.
        started_at: UTC timestamp when the session began.
    """

    session_id: UUID = Field(
        ...,
        description="UUID of the current trading session.",
        examples=["770e8400-e29b-41d4-a716-446655440003"],
    )
    started_at: datetime = Field(
        ...,
        description="UTC timestamp when the session began.",
        examples=["2026-02-20T00:00:00Z"],
    )


class RiskProfileInfo(_BaseSchema):
    """Nested risk profile embedded in ``AccountInfoResponse``.

    Attributes:
        max_position_size_pct: Maximum single-position size as a percentage of
                               total equity.
        daily_loss_limit_pct:  Maximum daily loss allowed as a percentage of
                               total equity.
        max_open_orders:       Maximum number of concurrently open orders.
    """

    max_position_size_pct: int = Field(
        ...,
        ge=1,
        le=100,
        description="Maximum single-position size as a percentage of total equity.",
        examples=[25],
    )
    daily_loss_limit_pct: int = Field(
        ...,
        ge=1,
        le=100,
        description="Maximum daily loss allowed as a percentage of total equity.",
        examples=[20],
    )
    max_open_orders: int = Field(
        ...,
        ge=1,
        description="Maximum number of concurrently open orders.",
        examples=[50],
    )


# ---------------------------------------------------------------------------
# Account info — GET /account/info
# ---------------------------------------------------------------------------

AccountStatus = Literal["active", "suspended", "closed"]


class AccountInfoResponse(_BaseSchema):
    """Response body for ``GET /api/v1/account/info`` (HTTP 200).

    Attributes:
        account_id:       UUID of the account.
        display_name:     Human-readable name for the account / bot.
        status:           Lifecycle status of the account.
        starting_balance: Starting USDT balance for the current session.
        current_session:  Nested session details.
        risk_profile:     Nested risk profile configuration.
        created_at:       UTC timestamp of account creation.
    """

    account_id: UUID = Field(
        ...,
        description="UUID of the account.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    api_key: str = Field(
        ...,
        description="Account-level API key for X-API-Key header authentication.",
        examples=["ak_live_abc123..."],
    )
    display_name: str = Field(
        ...,
        description="Human-readable name for the account / bot.",
        examples=["MyTradingBot"],
    )
    status: AccountStatus = Field(
        ...,
        description="Lifecycle status of the account.",
        examples=["active"],
    )
    starting_balance: Decimal = Field(
        ...,
        description="Starting USDT balance for the current session.",
        examples=["10000.00"],
    )
    current_session: SessionInfo = Field(
        ...,
        description="Details of the current trading session.",
    )
    risk_profile: RiskProfileInfo = Field(
        ...,
        description="Risk configuration applied to this account.",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp of account creation.",
        examples=["2026-02-20T00:00:00Z"],
    )

    @field_serializer("starting_balance")
    def _serialize_starting_balance(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Balance — GET /account/balance
# ---------------------------------------------------------------------------


class BalanceItem(_BaseSchema):
    """A single asset balance row in ``BalancesResponse``.

    Attributes:
        asset:     Uppercase asset ticker (e.g. ``"USDT"``, ``"BTC"``).
        available: Amount available for trading.
        locked:    Amount reserved as collateral for open orders.
        total:     Sum of available + locked.
    """

    asset: str = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Uppercase asset ticker.",
        examples=["USDT"],
    )
    available: Decimal = Field(
        ...,
        description="Amount available for trading.",
        examples=["6741.50"],
    )
    locked: Decimal = Field(
        ...,
        description="Amount reserved as collateral for open orders.",
        examples=["1500.00"],
    )
    total: Decimal = Field(
        ...,
        description="Sum of available + locked.",
        examples=["8241.50"],
    )

    @field_serializer("available", "locked", "total")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class BalancesResponse(_BaseSchema):
    """Response body for ``GET /api/v1/account/balance`` (HTTP 200).

    Attributes:
        balances:          Per-asset balance breakdown.
        total_equity_usdt: Total portfolio equity converted to USDT.
    """

    balances: list[BalanceItem] = Field(
        default_factory=list,
        description="Per-asset balance breakdown.",
    )
    total_equity_usdt: Decimal = Field(
        ...,
        description="Total portfolio equity expressed in USDT.",
        examples=["12458.30"],
    )

    @field_serializer("total_equity_usdt")
    def _serialize_equity(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Positions — GET /account/positions
# ---------------------------------------------------------------------------


class PositionItem(_BaseSchema):
    """A single open position in ``PositionsResponse``.

    Attributes:
        symbol:              Trading pair (e.g. ``"BTCUSDT"``).
        asset:               Base asset ticker (e.g. ``"BTC"``).
        quantity:            Base-asset quantity held.
        avg_entry_price:     Volume-weighted average entry price.
        current_price:       Latest market price of the base asset in USDT.
        market_value:        Current market value in USDT (quantity × current_price).
        unrealized_pnl:      Unrealised profit/loss in USDT.
        unrealized_pnl_pct:  Unrealised P&L as a percentage of entry cost.
        opened_at:           UTC timestamp of when the position was first opened.
    """

    symbol: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Trading pair symbol.",
        examples=["BTCUSDT"],
    )
    asset: str = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Base asset ticker.",
        examples=["BTC"],
    )
    quantity: Decimal = Field(
        ...,
        description="Base-asset quantity held.",
        examples=["0.50000000"],
    )
    avg_entry_price: Decimal = Field(
        ...,
        description="Volume-weighted average entry price in USDT.",
        examples=["63200.00"],
    )
    current_price: Decimal = Field(
        ...,
        description="Latest market price of the base asset in USDT.",
        examples=["64521.30"],
    )
    market_value: Decimal = Field(
        ...,
        description="Current market value in USDT (quantity × current_price).",
        examples=["32260.65"],
    )
    unrealized_pnl: Decimal = Field(
        ...,
        description="Unrealised profit/loss in USDT.",
        examples=["660.65"],
    )
    unrealized_pnl_pct: Decimal = Field(
        ...,
        description="Unrealised P&L as a percentage of entry cost.",
        examples=["2.09"],
    )
    opened_at: datetime = Field(
        ...,
        description="UTC timestamp of when the position was first opened.",
        examples=["2026-02-21T10:15:00Z"],
    )

    @field_serializer(
        "quantity",
        "avg_entry_price",
        "current_price",
        "market_value",
        "unrealized_pnl",
        "unrealized_pnl_pct",
    )
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class PositionsResponse(_BaseSchema):
    """Response body for ``GET /api/v1/account/positions`` (HTTP 200).

    Attributes:
        positions:            List of current open positions.
        total_unrealized_pnl: Sum of unrealised P&L across all open positions.
    """

    positions: list[PositionItem] = Field(
        default_factory=list,
        description="List of current open positions.",
    )
    total_unrealized_pnl: Decimal = Field(
        ...,
        description="Sum of unrealised P&L across all open positions in USDT.",
        examples=["660.65"],
    )

    @field_serializer("total_unrealized_pnl")
    def _serialize_total_pnl(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Portfolio — GET /account/portfolio
# ---------------------------------------------------------------------------


class PortfolioResponse(_BaseSchema):
    """Response body for ``GET /api/v1/account/portfolio`` (HTTP 200).

    Full portfolio snapshot combining balances, positions, and P&L metrics.

    Attributes:
        total_equity:         Total portfolio value in USDT (cash + positions).
        available_cash:       USDT available for new orders.
        locked_cash:          USDT reserved as collateral for open orders.
        total_position_value: Current market value of all held assets in USDT.
        unrealized_pnl:       Sum of unrealised P&L across all open positions.
        realized_pnl:         Total realised P&L from closed trades this session.
        total_pnl:            unrealized_pnl + realized_pnl.
        roi_pct:              Return on investment as a percentage vs starting balance.
        starting_balance:     Session starting USDT balance.
        positions:            List of current open positions.
        timestamp:            UTC timestamp when this snapshot was computed.
    """

    total_equity: Decimal = Field(
        ...,
        description="Total portfolio value in USDT (cash + positions).",
        examples=["12458.30"],
    )
    available_cash: Decimal = Field(
        ...,
        description="USDT available for new orders.",
        examples=["6741.50"],
    )
    locked_cash: Decimal = Field(
        ...,
        description="USDT reserved as collateral for open orders.",
        examples=["1500.00"],
    )
    total_position_value: Decimal = Field(
        ...,
        description="Current market value of all held non-USDT assets in USDT.",
        examples=["4216.80"],
    )
    unrealized_pnl: Decimal = Field(
        ...,
        description="Sum of unrealised P&L across all open positions in USDT.",
        examples=["660.65"],
    )
    realized_pnl: Decimal = Field(
        ...,
        description="Total realised P&L from closed trades this session in USDT.",
        examples=["1241.30"],
    )
    total_pnl: Decimal = Field(
        ...,
        description="unrealized_pnl + realized_pnl.",
        examples=["1901.95"],
    )
    roi_pct: Decimal = Field(
        ...,
        description="Return on investment as a percentage of the starting balance.",
        examples=["19.02"],
    )
    starting_balance: Decimal = Field(
        ...,
        description="Session starting USDT balance.",
        examples=["10000.00"],
    )
    positions: list[PositionItem] = Field(
        default_factory=list,
        description="List of current open positions.",
    )
    timestamp: datetime = Field(
        ...,
        description="UTC timestamp when this portfolio snapshot was computed.",
        examples=["2026-02-23T15:30:45Z"],
    )

    @field_serializer(
        "total_equity",
        "available_cash",
        "locked_cash",
        "total_position_value",
        "unrealized_pnl",
        "realized_pnl",
        "total_pnl",
        "roi_pct",
        "starting_balance",
    )
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# PnL breakdown — GET /account/pnl
# ---------------------------------------------------------------------------

PnLPeriod = Literal["1d", "7d", "30d", "all"]


class PnLResponse(_BaseSchema):
    """Response body for ``GET /api/v1/account/pnl`` (HTTP 200).

    Attributes:
        period:         Time window covered by this P&L summary.
        realized_pnl:   Realised profit/loss from closed trades.
        unrealized_pnl: Current unrealised profit/loss from open positions.
        total_pnl:      realized_pnl + unrealized_pnl.
        fees_paid:      Total trading fees paid within the period.
        net_pnl:        total_pnl minus fees_paid.
        winning_trades: Number of profitable trades.
        losing_trades:  Number of loss-making trades.
        win_rate:       Winning trades / total trades as a percentage.
    """

    period: PnLPeriod = Field(
        ...,
        description="Time window covered by this P&L summary.",
        examples=["7d"],
    )
    realized_pnl: Decimal = Field(
        ...,
        description="Realised profit/loss from closed trades in USDT.",
        examples=["1241.30"],
    )
    unrealized_pnl: Decimal = Field(
        ...,
        description="Current unrealised profit/loss from open positions in USDT.",
        examples=["660.65"],
    )
    total_pnl: Decimal = Field(
        ...,
        description="realized_pnl + unrealized_pnl.",
        examples=["1901.95"],
    )
    fees_paid: Decimal = Field(
        ...,
        description="Total trading fees paid within the period in USDT.",
        examples=["156.20"],
    )
    net_pnl: Decimal = Field(
        ...,
        description="total_pnl minus fees_paid.",
        examples=["1745.75"],
    )
    winning_trades: int = Field(
        ...,
        ge=0,
        description="Number of profitable closed trades.",
        examples=[23],
    )
    losing_trades: int = Field(
        ...,
        ge=0,
        description="Number of loss-making closed trades.",
        examples=[12],
    )
    win_rate: Decimal = Field(
        ...,
        description="Winning trades / total trades expressed as a percentage.",
        examples=["65.71"],
    )

    @field_serializer(
        "realized_pnl",
        "unrealized_pnl",
        "total_pnl",
        "fees_paid",
        "net_pnl",
        "win_rate",
    )
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Reset — POST /account/reset
# ---------------------------------------------------------------------------


class ResetRequest(_BaseSchema):
    """Request body for ``POST /api/v1/account/reset``.

    The ``confirm`` flag must be ``True`` to prevent accidental resets.

    Attributes:
        confirm:              Must be ``True`` to authorise the reset.
        new_starting_balance: Optional new starting balance in USDT; defaults
                              to the original starting balance if omitted.
    """

    confirm: bool = Field(
        ...,
        description="Must be True to authorise the account reset.",
        examples=[True],
    )
    new_starting_balance: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        description=(
            "New starting USDT balance after reset. Defaults to the account's original starting balance if omitted."
        ),
        examples=["10000.00"],
    )

    @field_serializer("new_starting_balance")
    def _serialize_balance(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


class PreviousSessionSummary(_BaseSchema):
    """Summary of the session that was terminated by a reset.

    Attributes:
        session_id:    UUID of the concluded session.
        ending_equity: Final total equity at the time of reset.
        total_pnl:     Net P&L for the concluded session.
        duration_days: Number of calendar days the session lasted.
    """

    session_id: UUID = Field(
        ...,
        description="UUID of the concluded session.",
        examples=["770e8400-e29b-41d4-a716-446655440003"],
    )
    ending_equity: Decimal = Field(
        ...,
        description="Final total equity at the time of reset in USDT.",
        examples=["12458.30"],
    )
    total_pnl: Decimal = Field(
        ...,
        description="Net profit/loss for the concluded session in USDT.",
        examples=["2458.30"],
    )
    duration_days: int = Field(
        ...,
        ge=0,
        description="Number of calendar days the session lasted.",
        examples=[3],
    )

    @field_serializer("ending_equity", "total_pnl")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class NewSessionSummary(_BaseSchema):
    """Details of the freshly created session after a reset.

    Attributes:
        session_id:       UUID of the new session.
        starting_balance: USDT balance allocated to the new session.
        started_at:       UTC timestamp when the new session began.
    """

    session_id: UUID = Field(
        ...,
        description="UUID of the new session.",
        examples=["770e8400-e29b-41d4-a716-446655440004"],
    )
    starting_balance: Decimal = Field(
        ...,
        description="USDT balance allocated to the new session.",
        examples=["10000.00"],
    )
    started_at: datetime = Field(
        ...,
        description="UTC timestamp when the new session began.",
        examples=["2026-02-23T15:35:00Z"],
    )

    @field_serializer("starting_balance")
    def _serialize_balance(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class ResetResponse(_BaseSchema):
    """Response body for ``POST /api/v1/account/reset`` (HTTP 200).

    Attributes:
        message:          Human-readable confirmation message.
        previous_session: Summary of the session that was terminated.
        new_session:      Details of the newly created session.
    """

    message: str = Field(
        ...,
        description="Human-readable confirmation message.",
        examples=["Account reset successful"],
    )
    previous_session: PreviousSessionSummary = Field(
        ...,
        description="Summary of the session that was terminated by the reset.",
    )
    new_session: NewSessionSummary = Field(
        ...,
        description="Details of the newly created session.",
    )
