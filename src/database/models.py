"""SQLAlchemy ORM models for the AI Agent Crypto Trading Platform.

Phase 1 tables:
- ``Tick``                — raw trade ticks (TimescaleDB hypertable)
- ``TradingPair``         — reference data for all active USDT pairs

Phase 2 tables:
- ``Account``             — agent accounts with API keys and risk profiles
- ``Balance``             — per-asset balances (available + locked) per account
- ``TradingSession``      — session tracking for account resets
- ``Order``               — all orders across their full lifecycle
- ``Trade``               — executed trade fills with PnL
- ``Position``            — aggregated current holdings per account/symbol
- ``PortfolioSnapshot``   — periodic equity snapshots for charting
- ``AuditLog``            — every authenticated request for security

Multi-agent tables:
- ``Agent``               — trading agents owned by accounts with own API keys

Battle tables:
- ``Battle``              — battle configuration and lifecycle
- ``BattleParticipant``   — agents participating in a battle
- ``BattleSnapshot``      — time-series equity snapshots during battle (hypertable)

Backtesting tables:
- ``BacktestSession``     — backtest run configuration and results
- ``BacktestTrade``       — simulated trade fills within a backtest
- ``BacktestSnapshot``    — periodic equity snapshots during backtest (hypertable)

All models inherit from the shared ``Base`` declarative base.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    VARCHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    All table models inherit from ``Base``.  ``Base.metadata`` is passed to
    Alembic's ``target_metadata`` so migrations stay in sync automatically.
    """


# ── Tick ──────────────────────────────────────────────────────────────────────


class Tick(Base):
    """One raw trade tick received from the Binance WebSocket stream.

    This table is converted to a **TimescaleDB hypertable** (partitioned by
    ``time`` with 1-hour chunks) in the initial Alembic migration.  Do not
    add a surrogate primary key — TimescaleDB hypertables work best without
    one on the time dimension column.

    Attributes:
        time:           UTC timestamp of the trade (partition key).
        symbol:         Trading pair symbol, e.g. ``"BTCUSDT"``.
        price:          Execution price with up to 8 decimal places.
        quantity:       Trade size in base-asset units.
        is_buyer_maker: ``True`` if the buyer was the market maker.
        trade_id:       Binance-assigned trade identifier (unique per symbol).
    """

    __tablename__ = "ticks"

    # TimescaleDB requires the time column to be part of every unique
    # constraint / index but does NOT require a traditional PK on it.
    # We declare it as a primary key here only so SQLAlchemy is happy;
    # the hypertable migration drops and recreates constraints as needed.
    time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        nullable=False,
    )
    trade_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    is_buyer_maker: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="FALSE",
    )

    __table_args__ = (
        # Primary lookup: symbol + time range scans (most common query pattern)
        Index("idx_ticks_symbol_time", "symbol", "time", postgresql_ops={"time": "DESC"}),
        # Dedup lookup when re-ingesting after reconnect
        Index("idx_ticks_trade_id", "symbol", "trade_id"),
    )

    def __repr__(self) -> str:
        return f"<Tick symbol={self.symbol!r} price={self.price} time={self.time}>"


# ── TradingPair ───────────────────────────────────────────────────────────────


class TradingPair(Base):
    """Reference data for a single Binance USDT trading pair.

    Populated (and kept fresh) by ``scripts/seed_pairs.py``.  Used by the
    order engine to validate order quantities against exchange filter rules.

    Attributes:
        symbol:         Primary key, e.g. ``"BTCUSDT"``.
        base_asset:     Base currency, e.g. ``"BTC"``.
        quote_asset:    Quote currency, always ``"USDT"`` for Phase 1.
        status:         ``"active"`` when the pair is currently tradeable.
        min_qty:        Minimum order quantity (LOT_SIZE filter).
        max_qty:        Maximum order quantity (LOT_SIZE filter).
        step_size:      Quantity increment (LOT_SIZE filter).
        min_notional:   Minimum order value in quote asset (MIN_NOTIONAL filter).
        updated_at:     Timestamp of last upsert from Binance exchange info.
    """

    __tablename__ = "trading_pairs"

    symbol: Mapped[str] = mapped_column(
        VARCHAR(20),
        primary_key=True,
        nullable=False,
    )
    base_asset: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    quote_asset: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        default="active",
        server_default="'active'",
    )
    min_qty: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    max_qty: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    step_size: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    min_notional: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<TradingPair symbol={self.symbol!r} status={self.status!r}>"


# ── Account ───────────────────────────────────────────────────────────────────


class Account(Base):
    """Agent account with API credentials and risk configuration.

    Stores the plaintext ``api_key`` for O(1) lookup and its bcrypt hash for
    verification.  The ``api_secret`` is never stored in plaintext — only its
    hash is persisted.  ``risk_profile`` holds per-account overrides for the
    default risk limits (serialized as JSONB).

    Human users authenticate via email + password; ``password_hash`` stores the
    bcrypt hash of their password (nullable so existing agent-only accounts are
    unaffected).

    Attributes:
        id:               Primary key (UUID v4, server-generated).
        api_key:          Plaintext key used as lookup token (prefixed ``ak_live_``).
        api_key_hash:     bcrypt hash of ``api_key`` for verification.
        api_secret_hash:  bcrypt hash of the secret (prefixed ``sk_live_``).
        password_hash:    bcrypt hash of the human user's password (nullable).
        display_name:     Human-readable name for the agent.
        email:            Optional contact email; unique when set (login identifier).
        starting_balance: Virtual USDT balance credited at registration.
        status:           Lifecycle state: ``active``, ``suspended``, or ``archived``.
        risk_profile:     JSON dict with optional per-account risk limit overrides.
        created_at:       UTC timestamp of account creation.
        updated_at:       UTC timestamp of last modification.
    """

    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    api_key: Mapped[str] = mapped_column(
        VARCHAR(128),
        unique=True,
        nullable=False,
    )
    api_key_hash: Mapped[str] = mapped_column(
        VARCHAR(128),
        nullable=False,
    )
    api_secret_hash: Mapped[str] = mapped_column(
        VARCHAR(128),
        nullable=False,
    )
    password_hash: Mapped[str | None] = mapped_column(
        VARCHAR(128),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(
        VARCHAR(100),
        nullable=False,
    )
    email: Mapped[str | None] = mapped_column(
        VARCHAR(255),
        nullable=True,
    )
    starting_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default="10000.00",
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        server_default="'active'",
    )
    risk_profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'{}'",
    )
    current_mode: Mapped[str] = mapped_column(
        VARCHAR(10),
        nullable=False,
        server_default="'live'",
    )
    active_strategy_label: Mapped[str | None] = mapped_column(
        VARCHAR(100),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    agents: Mapped[list[Agent]] = relationship("Agent", back_populates="account", cascade="all, delete-orphan")
    balances: Mapped[list[Balance]] = relationship("Balance", back_populates="account", cascade="all, delete-orphan")
    sessions: Mapped[list[TradingSession]] = relationship(
        "TradingSession", back_populates="account", cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship("Order", back_populates="account", cascade="all, delete-orphan")
    trades: Mapped[list[Trade]] = relationship("Trade", back_populates="account", cascade="all, delete-orphan")
    positions: Mapped[list[Position]] = relationship("Position", back_populates="account", cascade="all, delete-orphan")
    snapshots: Mapped[list[PortfolioSnapshot]] = relationship(
        "PortfolioSnapshot", back_populates="account", cascade="all, delete-orphan"
    )
    backtest_sessions: Mapped[list[BacktestSession]] = relationship(
        "BacktestSession", back_populates="account", cascade="all, delete-orphan"
    )
    battles: Mapped[list[Battle]] = relationship(
        "Battle", back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'archived')", name="ck_accounts_status"),
        CheckConstraint("current_mode IN ('live', 'backtest')", name="ck_accounts_mode"),
        Index(
            "uq_accounts_email",
            "email",
            unique=True,
            postgresql_where="email IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<Account id={self.id} display_name={self.display_name!r} status={self.status!r}>"


# ── Agent ────────────────────────────────────────────────────────────────────


class Agent(Base):
    """A trading agent owned by an account.

    Each account can have multiple agents, each with its own API key,
    starting balance, risk profile, and trading identity.  Agents are the
    primary scoping entity for all trading operations (orders, balances,
    positions, trades).

    Attributes:
        id:               Primary key (UUID v4, server-generated).
        account_id:       Foreign key → ``accounts.id`` (cascade delete).
        display_name:     Human-readable name for the agent.
        api_key:          Plaintext key used as lookup token (prefixed ``ak_live_``).
        api_key_hash:     bcrypt hash of ``api_key`` for verification.
        starting_balance: Virtual USDT balance credited at creation.
        llm_model:        LLM model name (e.g. ``"gpt-4o"``, ``"claude-opus-4-20250514"``).
        framework:        Agent framework (e.g. ``"langchain"``, ``"custom"``).
        strategy_tags:    JSONB list of strategy descriptors.
        risk_profile:     JSON dict with per-agent risk limit overrides.
        avatar_url:       URL or data-URI for the agent's avatar image.
        color:            Hex color code for UI identification (e.g. ``"#FF5733"``).
        status:           Lifecycle state: ``active``, ``paused``, ``archived``.
        created_at:       UTC timestamp of agent creation.
        updated_at:       UTC timestamp of last modification.
    """

    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(
        VARCHAR(100),
        nullable=False,
    )
    api_key: Mapped[str] = mapped_column(
        VARCHAR(128),
        unique=True,
        nullable=False,
    )
    api_key_hash: Mapped[str] = mapped_column(
        VARCHAR(128),
        nullable=False,
    )
    starting_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default="10000.00",
    )
    llm_model: Mapped[str | None] = mapped_column(
        VARCHAR(100),
        nullable=True,
    )
    framework: Mapped[str | None] = mapped_column(
        VARCHAR(100),
        nullable=True,
    )
    strategy_tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'[]'",
    )
    risk_profile: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'{}'",
    )
    avatar_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    color: Mapped[str | None] = mapped_column(
        VARCHAR(7),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        server_default="'active'",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    account: Mapped[Account] = relationship("Account", back_populates="agents")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'paused', 'archived')", name="ck_agents_status"),
        Index("idx_agents_account", "account_id"),
        Index("idx_agents_api_key", "api_key", unique=True),
        Index("idx_agents_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Agent id={self.id} display_name={self.display_name!r} status={self.status!r}>"


# ── Balance ───────────────────────────────────────────────────────────────────


class Balance(Base):
    """Per-asset virtual balance for an account.

    Both ``available`` and ``locked`` are constrained to be non-negative.
    ``locked`` funds are reserved for pending orders and cannot be traded
    until the order is filled or cancelled.

    Attributes:
        id:          Primary key (UUID v4).
        account_id:  Foreign key → ``accounts.id`` (cascade delete).
        asset:       Asset ticker, e.g. ``"USDT"``, ``"BTC"``, ``"ETH"``.
        available:   Amount free to place new orders.
        locked:      Amount reserved by pending orders.
        updated_at:  UTC timestamp of last balance change.
    """

    __tablename__ = "balances"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    available: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default="0",
    )
    locked: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default="0",
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    account: Mapped[Account] = relationship("Account", back_populates="balances")

    __table_args__ = (
        CheckConstraint("available >= 0", name="ck_balances_available_non_negative"),
        CheckConstraint("locked >= 0", name="ck_balances_locked_non_negative"),
        Index("idx_balances_account", "account_id"),
        Index("idx_balances_agent", "agent_id"),
        # Enforces one row per (agent, asset) pair.
        Index("uq_balances_agent_asset", "agent_id", "asset", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<Balance account={self.account_id} asset={self.asset!r} available={self.available} locked={self.locked}>"
        )


# ── TradingSession ────────────────────────────────────────────────────────────


class TradingSession(Base):
    """A discrete trading session for an account.

    Sessions are created on registration and each subsequent account reset.
    Closing a session records the final equity for historical comparison.

    Attributes:
        id:               Primary key (UUID v4).
        account_id:       Foreign key → ``accounts.id`` (cascade delete).
        starting_balance: USDT balance at session start.
        started_at:       UTC timestamp when the session began.
        ended_at:         UTC timestamp when the session was closed (nullable).
        ending_equity:    Total equity in USDT at session close (nullable).
        status:           ``active`` while trading, ``closed`` after reset.
    """

    __tablename__ = "trading_sessions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    starting_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    ending_equity: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        server_default="'active'",
    )

    account: Mapped[Account] = relationship("Account", back_populates="sessions")
    orders: Mapped[list[Order]] = relationship("Order", back_populates="session")
    trades: Mapped[list[Trade]] = relationship("Trade", back_populates="session")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="ck_sessions_status"),
        Index("idx_sessions_account", "account_id"),
        Index("idx_trading_sessions_agent", "agent_id"),
    )

    def __repr__(self) -> str:
        return f"<TradingSession id={self.id} account={self.account_id} status={self.status!r}>"


# ── Order ─────────────────────────────────────────────────────────────────────


class Order(Base):
    """A single order submitted by an agent.

    Covers the complete order lifecycle from submission through terminal states
    (``filled``, ``cancelled``, ``rejected``, ``expired``).  Market orders
    transition directly to ``filled``; limit/stop/take-profit orders pass
    through ``pending`` until matched.

    Attributes:
        id:               Primary key (UUID v4).
        account_id:       Foreign key → ``accounts.id`` (cascade delete).
        session_id:       Foreign key → ``trading_sessions.id`` (nullable).
        symbol:           Trading pair, e.g. ``"BTCUSDT"``.
        side:             ``"buy"`` or ``"sell"``.
        type:             Order type: ``"market"``, ``"limit"``, ``"stop_loss"``,
                          or ``"take_profit"``.
        quantity:         Requested base-asset quantity (must be > 0).
        price:            Target price for limit / stop / take-profit orders.
        executed_price:   Actual fill price after slippage.
        executed_qty:     Actual filled quantity.
        slippage_pct:     Realised slippage as a percentage.
        fee:              Simulated trading fee in quote asset.
        status:           Order state; one of ``pending``, ``filled``,
                          ``partially_filled``, ``cancelled``, ``rejected``,
                          ``expired``.
        rejection_reason: Short code explaining a rejection (nullable).
        created_at:       UTC timestamp of order submission.
        updated_at:       UTC timestamp of last status change.
        filled_at:        UTC timestamp of order fill (nullable).
        expires_at:       Optional expiry timestamp for limit orders.
    """

    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("trading_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    side: Mapped[str] = mapped_column(
        VARCHAR(4),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    executed_price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    executed_qty: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    slippage_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6),
        nullable=True,
    )
    fee: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        server_default="'pending'",
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        VARCHAR(100),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    filled_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    account: Mapped[Account] = relationship("Account", back_populates="orders")
    session: Mapped[TradingSession | None] = relationship("TradingSession", back_populates="orders")
    trades: Mapped[list[Trade]] = relationship("Trade", back_populates="order")

    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="ck_orders_side"),
        CheckConstraint(
            "type IN ('market', 'limit', 'stop_loss', 'take_profit')",
            name="ck_orders_type",
        ),
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint(
            "status IN ('pending', 'filled', 'partially_filled', 'cancelled', 'rejected', 'expired')",
            name="ck_orders_status",
        ),
        Index("idx_orders_account", "account_id"),
        Index("idx_orders_agent", "agent_id"),
        Index("idx_orders_account_status", "account_id", "status"),
        # Partial index: only pending orders need fast symbol-based lookup.
        Index(
            "idx_orders_symbol_status",
            "symbol",
            "status",
            postgresql_where="status = 'pending'",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id} symbol={self.symbol!r} side={self.side!r} type={self.type!r} status={self.status!r}>"
        )


# ── Trade ─────────────────────────────────────────────────────────────────────


class Trade(Base):
    """A single executed trade fill.

    Created when an order transitions to ``filled``.  ``realized_pnl`` is
    populated when the trade closes an existing position.

    Attributes:
        id:            Primary key (UUID v4).
        account_id:    Foreign key → ``accounts.id`` (cascade delete).
        order_id:      Foreign key → ``orders.id``.
        session_id:    Foreign key → ``trading_sessions.id`` (nullable).
        symbol:        Trading pair, e.g. ``"BTCUSDT"``.
        side:          ``"buy"`` or ``"sell"``.
        quantity:      Filled base-asset quantity.
        price:         Execution price in quote asset.
        quote_amount:  ``quantity * price`` (total quote cost/proceeds).
        fee:           Simulated fee deducted from quote asset.
        realized_pnl:  PnL realised if this trade closes a position (nullable).
        created_at:    UTC timestamp of fill.
    """

    __tablename__ = "trades"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("trading_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    side: Mapped[str] = mapped_column(
        VARCHAR(4),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    quote_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    realized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    account: Mapped[Account] = relationship("Account", back_populates="trades")
    order: Mapped[Order] = relationship("Order", back_populates="trades")
    session: Mapped[TradingSession | None] = relationship("TradingSession", back_populates="trades")

    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="ck_trades_side"),
        Index("idx_trades_account", "account_id"),
        Index("idx_trades_agent", "agent_id"),
        Index("idx_trades_account_time", "account_id", "created_at"),
        Index("idx_trades_symbol", "symbol", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Trade id={self.id} symbol={self.symbol!r} side={self.side!r} price={self.price} qty={self.quantity}>"


# ── Position ──────────────────────────────────────────────────────────────────


class Position(Base):
    """Aggregated current holding for an account/symbol pair.

    Maintained by the order engine after each fill.  A position is opened on
    the first buy and reduced on sells; it is deleted (or zeroed) when fully
    closed.  ``avg_entry_price`` uses a weighted-average calculation across all
    partial fills.

    Attributes:
        id:               Primary key (UUID v4).
        account_id:       Foreign key → ``accounts.id`` (cascade delete).
        symbol:           Trading pair, e.g. ``"BTCUSDT"``.
        side:             Always ``"long"`` for Phase 2 (no shorting).
        quantity:         Current held base-asset quantity.
        avg_entry_price:  Weighted-average entry price in quote asset.
        total_cost:       ``quantity * avg_entry_price``.
        realized_pnl:     Cumulative realised PnL from partial closes.
        opened_at:        UTC timestamp of position creation.
        updated_at:       UTC timestamp of last modification.
    """

    __tablename__ = "positions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    side: Mapped[str] = mapped_column(
        VARCHAR(4),
        nullable=False,
        server_default="'long'",
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default="0",
    )
    avg_entry_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default="0",
    )
    opened_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    account: Mapped[Account] = relationship("Account", back_populates="positions")

    __table_args__ = (
        Index("idx_positions_account", "account_id"),
        Index("idx_positions_agent", "agent_id"),
        Index("uq_positions_agent_symbol", "agent_id", "symbol", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<Position account={self.account_id} symbol={self.symbol!r} "
            f"qty={self.quantity} avg_entry={self.avg_entry_price}>"
        )


# ── PortfolioSnapshot ─────────────────────────────────────────────────────────


class PortfolioSnapshot(Base):
    """Periodic snapshot of an account's portfolio state.

    Captured by a Celery beat task at three granularities:
    ``minute`` (quick equity), ``hourly`` (full breakdown), ``daily``
    (comprehensive report including performance metrics).

    This table is converted to a **TimescaleDB hypertable** (partitioned by
    ``created_at`` with 1-day chunks) in the Phase 2 Alembic migration.

    Attributes:
        id:              Primary key (UUID v4).
        account_id:      Foreign key → ``accounts.id`` (cascade delete).
        snapshot_type:   Granularity: ``"minute"``, ``"hourly"``, or ``"daily"``.
        total_equity:    Total portfolio value in USDT at snapshot time.
        available_cash:  Free USDT balance.
        position_value:  Market value of all non-USDT holdings.
        unrealized_pnl:  Open PnL across all positions.
        realized_pnl:    Cumulative realised PnL for the current session.
        positions:       Serialised position data (JSONB).
        metrics:         Serialised performance metrics (JSONB, hourly/daily only).
        created_at:      UTC timestamp of snapshot capture (hypertable partition key).
    """

    __tablename__ = "portfolio_snapshots"

    # TimescaleDB requires the partition column to be part of the PK.
    # Composite PK (id, created_at) satisfies that constraint.
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        nullable=False,
        server_default=func.now(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_type: Mapped[str] = mapped_column(
        VARCHAR(10),
        nullable=False,
    )
    total_equity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    available_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    position_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    positions: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    account: Mapped[Account] = relationship("Account", back_populates="snapshots")

    __table_args__ = (
        CheckConstraint(
            "snapshot_type IN ('minute', 'hourly', 'daily')",
            name="ck_snapshots_type",
        ),
        Index(
            "idx_snapshots_account_type",
            "account_id",
            "snapshot_type",
            "created_at",
        ),
        Index("idx_portfolio_snapshots_agent", "agent_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PortfolioSnapshot account={self.account_id} "
            f"type={self.snapshot_type!r} equity={self.total_equity} at={self.created_at}>"
        )


# ── AuditLog ──────────────────────────────────────────────────────────────────


class AuditLog(Base):
    """Immutable audit trail of every authenticated API request.

    Uses a ``BIGSERIAL`` surrogate key rather than a UUID so that insertion
    order is preserved for forensic analysis without relying on timestamps
    (which can collide at millisecond resolution under load).

    Attributes:
        id:          Auto-incrementing surrogate primary key (BIGSERIAL).
        account_id:  Foreign key → ``accounts.id`` (nullable; NULL for
                     unauthenticated requests that still reach the log).
        action:      Short action code, e.g. ``"place_order"``, ``"login"``.
        details:     Arbitrary JSONB payload with request/response metadata.
        ip_address:  Client IP address (PostgreSQL INET type).
        created_at:  UTC timestamp of the event.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    account_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        VARCHAR(50),
        nullable=False,
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    ip_address: Mapped[str | None] = mapped_column(
        INET,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (Index("idx_audit_account", "account_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} account={self.account_id} action={self.action!r} at={self.created_at}>"


# ── WaitlistEntry ─────────────────────────────────────────────────────────


class WaitlistEntry(Base):
    """An email collected from the landing page waitlist form.

    Attributes:
        id:         Primary key (UUID v4, server-generated).
        email:      Email address (unique, case-sensitive).
        source:     Which form submitted the entry (e.g. ``"hero"``, ``"cta"``).
        created_at: UTC timestamp of submission.
    """

    __tablename__ = "waitlist_entries"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(
        VARCHAR(255),
        unique=True,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        VARCHAR(50),
        nullable=False,
        server_default="'landing'",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (Index("idx_waitlist_created", "created_at"),)

    def __repr__(self) -> str:
        return f"<WaitlistEntry email={self.email!r} source={self.source!r}>"


# ── BacktestSession ──────────────────────────────────────────────────────────


class BacktestSession(Base):
    """A single backtest run with configuration, progress, and results.

    Created by the agent via API with a time range, starting balance, and
    strategy label.  The engine advances through historical candles step by
    step, recording trades and snapshots.  Final metrics are persisted on
    completion.

    Attributes:
        id:                 Primary key (UUID v4).
        account_id:         Foreign key → ``accounts.id`` (cascade delete).
        strategy_label:     Agent-assigned label for the strategy being tested.
        status:             Lifecycle state: created → running → completed/failed/cancelled.
        candle_interval:    Candle interval in seconds (default 60 = 1m candles).
        start_time:         Backtest period start (UTC).
        end_time:           Backtest period end (UTC).
        starting_balance:   Virtual USDT balance at backtest start.
        pairs:              List of trading pairs to include (JSONB, null = all).
        virtual_clock:      Current simulated time position.
        current_step:       Number of candles processed so far.
        total_steps:        Total candles in the time range.
        progress_pct:       Completion percentage (0–100).
        final_equity:       Portfolio equity at backtest end (null until complete).
        total_pnl:          Net PnL at backtest end (null until complete).
        roi_pct:            Return on investment percentage (null until complete).
        total_trades:       Number of trades executed.
        total_fees:         Cumulative fees paid.
        metrics:            Full performance metrics JSONB (sharpe, drawdown, etc.).
        started_at:         Wall-clock time when engine started processing.
        completed_at:       Wall-clock time when engine finished.
        duration_real_sec:  Actual seconds the backtest took to run.
        created_at:         UTC timestamp of session creation.
        updated_at:         UTC timestamp of last modification.
    """

    __tablename__ = "backtest_sessions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
    )
    strategy_label: Mapped[str] = mapped_column(
        VARCHAR(100),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        server_default="'created'",
    )
    candle_interval: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="60",
    )
    start_time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    end_time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    starting_balance: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    pairs: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    virtual_clock: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    current_step: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    total_steps: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    progress_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default="0",
    )
    final_equity: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    total_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    roi_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
    total_trades: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    total_fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default="0",
    )
    metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    duration_real_sec: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    account: Mapped[Account] = relationship("Account", back_populates="backtest_sessions")
    agent: Mapped[Agent | None] = relationship("Agent")
    backtest_trades: Mapped[list[BacktestTrade]] = relationship(
        "BacktestTrade", back_populates="session", cascade="all, delete-orphan"
    )
    backtest_snapshots: Mapped[list[BacktestSnapshot]] = relationship(
        "BacktestSnapshot", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'running', 'paused', 'completed', 'failed', 'cancelled')",
            name="ck_bt_sessions_status",
        ),
        Index("idx_bt_sessions_account", "account_id"),
        Index("idx_bt_sessions_account_status", "account_id", "status"),
        Index("idx_bt_sessions_account_strategy", "account_id", "strategy_label"),
        Index(
            "idx_bt_sessions_account_roi",
            "account_id",
            "roi_pct",
            postgresql_ops={"roi_pct": "DESC NULLS LAST"},
        ),
        Index("idx_bt_sessions_agent", "agent_id"),
        Index("idx_bt_sessions_agent_status", "agent_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<BacktestSession id={self.id} strategy={self.strategy_label!r} "
            f"status={self.status!r} progress={self.progress_pct}%>"
        )


# ── BacktestTrade ────────────────────────────────────────────────────────────


class BacktestTrade(Base):
    """A single simulated trade fill within a backtest session.

    Mirrors the structure of ``Trade`` but belongs to a backtest session
    rather than the live trading system.  Uses ``simulated_at`` (virtual
    clock time) instead of ``created_at`` (wall-clock).

    Attributes:
        id:            Primary key (UUID v4).
        session_id:    Foreign key → ``backtest_sessions.id`` (cascade delete).
        symbol:        Trading pair, e.g. ``"BTCUSDT"``.
        side:          ``"buy"`` or ``"sell"``.
        type:          Order type that generated this trade.
        quantity:      Filled base-asset quantity.
        price:         Execution price in quote asset.
        quote_amount:  ``quantity * price``.
        fee:           Simulated trading fee.
        slippage_pct:  Realised slippage percentage.
        realized_pnl:  PnL if this trade closed a position (nullable).
        simulated_at:  Virtual clock timestamp when the trade occurred.
    """

    __tablename__ = "backtest_trades"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("backtest_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    side: Mapped[str] = mapped_column(
        VARCHAR(4),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    quote_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    slippage_pct: Mapped[Decimal] = mapped_column(
        Numeric(10, 6),
        nullable=False,
        server_default="0",
    )
    realized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    simulated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    session: Mapped[BacktestSession] = relationship("BacktestSession", back_populates="backtest_trades")

    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="ck_bt_trades_side"),
        CheckConstraint(
            "type IN ('market', 'limit', 'stop_loss', 'take_profit')",
            name="ck_bt_trades_type",
        ),
        Index("idx_bt_trades_session", "session_id"),
        Index("idx_bt_trades_session_time", "session_id", "simulated_at"),
    )

    def __repr__(self) -> str:
        return f"<BacktestTrade id={self.id} symbol={self.symbol!r} side={self.side!r} price={self.price}>"


# ── BacktestSnapshot ─────────────────────────────────────────────────────────


class BacktestSnapshot(Base):
    """Periodic equity snapshot during a backtest run.

    Captured at each step (or at a configured interval) to build the equity
    curve.  This table is converted to a **TimescaleDB hypertable** partitioned
    by ``simulated_at`` with 1-day chunks.

    Attributes:
        id:              Primary key (UUID v4).
        session_id:      Foreign key → ``backtest_sessions.id`` (cascade delete).
        simulated_at:    Virtual clock timestamp of the snapshot (hypertable partition key).
        total_equity:    Total portfolio value in USDT.
        available_cash:  Free USDT balance.
        position_value:  Market value of all non-USDT holdings.
        unrealized_pnl:  Open PnL across all positions.
        realized_pnl:    Cumulative realised PnL up to this point.
        positions:       Serialised position data (JSONB).
    """

    __tablename__ = "backtest_snapshots"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    simulated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("backtest_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_equity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    available_cash: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    position_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    positions: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    session: Mapped[BacktestSession] = relationship("BacktestSession", back_populates="backtest_snapshots")

    __table_args__ = (Index("idx_bt_snapshots_session_time", "session_id", "simulated_at"),)

    def __repr__(self) -> str:
        return f"<BacktestSnapshot session={self.session_id} equity={self.total_equity} at={self.simulated_at}>"


# ── Battle ──────────────────────────────────────────────────────────────────


class Battle(Base):
    """A competitive battle between multiple trading agents.

    Battles progress through a state machine:
    ``draft`` → ``pending`` → ``active`` → ``completed``
    with optional ``paused`` and ``cancelled`` states.

    Attributes:
        id:              Primary key (UUID v4, server-generated).
        account_id:      Foreign key → ``accounts.id`` (cascade delete).
        name:            Human-readable battle name.
        status:          Lifecycle state.
        config:          JSONB battle configuration (duration, pairs, wallet mode, etc.).
        preset:          Optional preset name (e.g. ``"quick_1h"``).
        ranking_metric:  Metric used to rank participants.
        started_at:      UTC timestamp when battle became active.
        ended_at:        UTC timestamp when battle completed.
        created_at:      UTC timestamp of battle creation.
    """

    __tablename__ = "battles"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        VARCHAR(200),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        server_default="'draft'",
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="'{}'",
    )
    battle_mode: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        server_default="'live'",
    )
    backtest_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    preset: Mapped[str | None] = mapped_column(
        VARCHAR(50),
        nullable=True,
    )
    ranking_metric: Mapped[str] = mapped_column(
        VARCHAR(30),
        nullable=False,
        server_default="'roi_pct'",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    account: Mapped[Account] = relationship("Account", back_populates="battles")
    participants: Mapped[list[BattleParticipant]] = relationship(
        "BattleParticipant", back_populates="battle", cascade="all, delete-orphan"
    )
    battle_snapshots: Mapped[list[BattleSnapshot]] = relationship(
        "BattleSnapshot", back_populates="battle", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending', 'active', 'paused', 'completed', 'cancelled')",
            name="ck_battles_status",
        ),
        CheckConstraint(
            "ranking_metric IN ('roi_pct', 'total_pnl', 'sharpe_ratio', 'win_rate', 'profit_factor')",
            name="ck_battles_ranking_metric",
        ),
        CheckConstraint(
            "battle_mode IN ('live', 'historical')",
            name="ck_battles_mode",
        ),
        Index("idx_battles_account", "account_id"),
        Index("idx_battles_status", "account_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Battle id={self.id} name={self.name!r} status={self.status!r}>"


# ── BattleParticipant ──────────────────────────────────────────────────────


class BattleParticipant(Base):
    """An agent participating in a battle.

    Tracks the agent's starting snapshot balance, final equity, rank, and
    per-participant status (active, paused, stopped, blown_up).

    Attributes:
        id:                Primary key (UUID v4).
        battle_id:         Foreign key → ``battles.id`` (cascade delete).
        agent_id:          Foreign key → ``agents.id``.
        snapshot_balance:  Starting balance snapshot when battle begins.
        final_equity:      Final equity when battle ends.
        final_rank:        Rank based on the battle's ranking metric.
        status:            Per-participant status.
        joined_at:         UTC timestamp when the agent joined the battle.
    """

    __tablename__ = "battle_participants"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    battle_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("battles.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    backtest_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("backtest_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    snapshot_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    final_equity: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    final_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        VARCHAR(20),
        nullable=False,
        server_default="'active'",
    )
    joined_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    battle: Mapped[Battle] = relationship("Battle", back_populates="participants")
    agent: Mapped[Agent] = relationship("Agent")

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'stopped', 'blown_up')",
            name="ck_bp_status",
        ),
        Index("idx_bp_battle", "battle_id"),
        Index("idx_bp_agent", "agent_id"),
        Index("uq_bp_battle_agent", "battle_id", "agent_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<BattleParticipant battle={self.battle_id} agent={self.agent_id} status={self.status!r}>"


# ── BattleSnapshot ─────────────────────────────────────────────────────────


class BattleSnapshot(Base):
    """Time-series equity snapshot for a battle participant.

    Captured every ~5 seconds during an active battle by the snapshot engine.
    This table is converted to a **TimescaleDB hypertable** partitioned by
    ``timestamp``.

    Attributes:
        id:              Auto-incrementing primary key (BIGSERIAL).
        battle_id:       Foreign key → ``battles.id`` (cascade delete).
        agent_id:        Foreign key → ``agents.id``.
        timestamp:       UTC timestamp of the snapshot (hypertable partition key).
        equity:          Total portfolio equity in USDT.
        unrealized_pnl:  Unrealised PnL across all open positions.
        realized_pnl:    Cumulative realised PnL.
        trade_count:     Total trades executed so far.
        open_positions:  Number of currently open positions.
    """

    __tablename__ = "battle_snapshots"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        nullable=False,
    )
    battle_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("battles.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    equity: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
    )
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    realized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
    )
    trade_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    open_positions: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    battle: Mapped[Battle] = relationship("Battle", back_populates="battle_snapshots")
    agent: Mapped[Agent] = relationship("Agent")

    __table_args__ = (
        Index("idx_battle_snap", "battle_id", "agent_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<BattleSnapshot battle={self.battle_id} agent={self.agent_id} equity={self.equity}>"
