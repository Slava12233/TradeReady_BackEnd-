"""Frozen dataclass response models for the AgentExchange Python SDK.

Each class maps directly to a REST API response shape.  All monetary and price
fields are typed as ``Decimal`` to preserve full 8-decimal precision.  Every
model exposes a ``from_dict`` class method for convenient deserialization from
the parsed JSON dicts returned by the SDK clients.

Usage::

    from agentexchange.models import Price, Order, Portfolio

    price = Price.from_dict({"symbol": "BTCUSDT", "price": "64521.30", "timestamp": "2026-02-25T10:00:00Z"})
    print(price.symbol, price.price)  # BTCUSDT 64521.30
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decimal(value: Any) -> Decimal:
    """Coerce *value* to ``Decimal``; accepts str, int, float, and Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _decimal_opt(value: Any) -> Decimal | None:
    """Coerce *value* to ``Decimal`` or ``None`` when *value* is ``None``."""
    if value is None:
        return None
    return _decimal(value)


def _dt(value: Any) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware ``datetime``."""
    if isinstance(value, datetime):
        return value
    raw: str = str(value)
    # Replace trailing 'Z' with '+00:00' so fromisoformat works on 3.10-.
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _dt_opt(value: Any) -> datetime | None:
    """Parse an ISO-8601 string into a ``datetime`` or return ``None``."""
    if value is None:
        return None
    return _dt(value)


def _uuid(value: Any) -> UUID:
    """Coerce *value* to a ``UUID``."""
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _uuid_opt(value: Any) -> UUID | None:
    """Coerce *value* to a ``UUID`` or return ``None``."""
    if value is None:
        return None
    return _uuid(value)


# ---------------------------------------------------------------------------
# Market data models
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Price:
    """Current market price for a single trading pair.

    Returned by ``GET /api/v1/market/price/{symbol}``.

    Attributes:
        symbol:    Uppercase trading pair symbol, e.g. ``"BTCUSDT"``.
        price:     Current mid-price from the latest Binance tick.
        timestamp: UTC datetime of the latest tick.

    Example::

        price = client.get_price("BTCUSDT")
        print(price.symbol, price.price)
    """

    symbol: str
    price: Decimal
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Price":
        """Deserialize a ``GET /market/price/{symbol}`` response dict.

        Args:
            data: Parsed JSON dict from the REST response body.

        Returns:
            A populated :class:`Price` instance.
        """
        return cls(
            symbol=data["symbol"],
            price=_decimal(data["price"]),
            timestamp=_dt(data["timestamp"]),
        )


@dataclasses.dataclass(frozen=True)
class Ticker:
    """24-hour market statistics for a single trading pair.

    Returned by ``GET /api/v1/market/ticker/{symbol}``.

    Attributes:
        symbol:       Uppercase trading pair symbol.
        open:         24h opening price.
        high:         24h highest price.
        low:          24h lowest price.
        close:        Latest close price (same as current price).
        volume:       24h traded volume in base asset.
        quote_volume: 24h traded volume in quote asset (USDT).
        change:       Absolute price change over 24h.
        change_pct:   Percentage price change over 24h.
        trade_count:  Number of trades in the 24h window.
        timestamp:    UTC datetime of the statistics snapshot.

    Example::

        ticker = client.get_ticker("BTCUSDT")
        print(ticker.change_pct, ticker.volume)
    """

    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    change: Decimal
    change_pct: Decimal
    trade_count: int
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Ticker":
        """Deserialize a ``GET /market/ticker/{symbol}`` response dict.

        Args:
            data: Parsed JSON dict from the REST response body.

        Returns:
            A populated :class:`Ticker` instance.
        """
        return cls(
            symbol=data["symbol"],
            open=_decimal(data["open"]),
            high=_decimal(data["high"]),
            low=_decimal(data["low"]),
            close=_decimal(data["close"]),
            volume=_decimal(data["volume"]),
            quote_volume=_decimal(data["quote_volume"]),
            change=_decimal(data["change"]),
            change_pct=_decimal(data["change_pct"]),
            trade_count=int(data["trade_count"]),
            timestamp=_dt(data["timestamp"]),
        )


@dataclasses.dataclass(frozen=True)
class Candle:
    """A single OHLCV candle bar.

    One element of the list returned by
    ``GET /api/v1/market/candles/{symbol}``.

    Attributes:
        time:        Candle open time (UTC).
        open:        Opening price for the interval.
        high:        Highest price during the interval.
        low:         Lowest price during the interval.
        close:       Closing price for the interval.
        volume:      Traded volume in base asset during the interval.
        trade_count: Number of trades during the interval.

    Example::

        candles = client.get_candles("BTCUSDT", interval="1h", limit=24)
        for c in candles:
            print(c.time, c.open, c.close)
    """

    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Candle":
        """Deserialize a single candle dict.

        Args:
            data: A single candle object from the ``candles`` array.

        Returns:
            A populated :class:`Candle` instance.
        """
        return cls(
            time=_dt(data["time"]),
            open=_decimal(data["open"]),
            high=_decimal(data["high"]),
            low=_decimal(data["low"]),
            close=_decimal(data["close"]),
            volume=_decimal(data["volume"]),
            trade_count=int(data["trade_count"]),
        )


# ---------------------------------------------------------------------------
# Account models
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Balance:
    """A single asset balance for an account.

    One element of the list returned by ``GET /api/v1/account/balance``.

    Attributes:
        asset:     Uppercase asset ticker, e.g. ``"USDT"`` or ``"BTC"``.
        available: Amount immediately available for new orders.
        locked:    Amount reserved as collateral for open orders.
        total:     ``available + locked``.

    Example::

        balances = client.get_balance()
        usdt = next(b for b in balances if b.asset == "USDT")
        print(usdt.available)
    """

    asset: str
    available: Decimal
    locked: Decimal
    total: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Balance":
        """Deserialize a single balance item dict.

        Args:
            data: One item from the ``balances`` array.

        Returns:
            A populated :class:`Balance` instance.
        """
        return cls(
            asset=data["asset"],
            available=_decimal(data["available"]),
            locked=_decimal(data["locked"]),
            total=_decimal(data["total"]),
        )


@dataclasses.dataclass(frozen=True)
class Position:
    """A single open position held by the account.

    One element of the list returned by ``GET /api/v1/account/positions``.

    Attributes:
        symbol:             Trading pair, e.g. ``"BTCUSDT"``.
        asset:              Base asset ticker, e.g. ``"BTC"``.
        quantity:           Base-asset quantity held.
        avg_entry_price:    Volume-weighted average entry price in USDT.
        current_price:      Latest market price of the base asset in USDT.
        market_value:       Current market value (quantity × current_price) in USDT.
        unrealized_pnl:     Unrealised profit/loss in USDT.
        unrealized_pnl_pct: Unrealised P&L as a percentage of entry cost.
        opened_at:          UTC timestamp of when the position was first opened.

    Example::

        positions = client.get_positions()
        for p in positions:
            print(p.symbol, p.unrealized_pnl)
    """

    symbol: str
    asset: str
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal
    opened_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Position":
        """Deserialize a single position item dict.

        Args:
            data: One item from the ``positions`` array.

        Returns:
            A populated :class:`Position` instance.
        """
        return cls(
            symbol=data["symbol"],
            asset=data["asset"],
            quantity=_decimal(data["quantity"]),
            avg_entry_price=_decimal(data["avg_entry_price"]),
            current_price=_decimal(data["current_price"]),
            market_value=_decimal(data["market_value"]),
            unrealized_pnl=_decimal(data["unrealized_pnl"]),
            unrealized_pnl_pct=_decimal(data["unrealized_pnl_pct"]),
            opened_at=_dt(data["opened_at"]),
        )


@dataclasses.dataclass(frozen=True)
class Portfolio:
    """Full portfolio snapshot combining balances, positions, and P&L metrics.

    Returned by ``GET /api/v1/account/portfolio``.

    Attributes:
        total_equity:         Total portfolio value in USDT (cash + positions).
        available_cash:       USDT available for new orders.
        locked_cash:          USDT reserved as collateral for open orders.
        total_position_value: Current market value of all held non-USDT assets.
        unrealized_pnl:       Sum of unrealised P&L across all open positions.
        realized_pnl:         Total realised P&L from closed trades this session.
        total_pnl:            ``unrealized_pnl + realized_pnl``.
        roi_pct:              Return on investment as a percentage vs starting balance.
        starting_balance:     Session starting USDT balance.
        positions:            Tuple of current open :class:`Position` objects.
        timestamp:            UTC timestamp when this snapshot was computed.

    Example::

        pf = client.get_portfolio()
        print(pf.total_equity, pf.roi_pct)
    """

    total_equity: Decimal
    available_cash: Decimal
    locked_cash: Decimal
    total_position_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_pnl: Decimal
    roi_pct: Decimal
    starting_balance: Decimal
    positions: tuple[Position, ...]
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Portfolio":
        """Deserialize a ``GET /account/portfolio`` response dict.

        Args:
            data: Parsed JSON dict from the REST response body.

        Returns:
            A populated :class:`Portfolio` instance.
        """
        return cls(
            total_equity=_decimal(data["total_equity"]),
            available_cash=_decimal(data["available_cash"]),
            locked_cash=_decimal(data["locked_cash"]),
            total_position_value=_decimal(data["total_position_value"]),
            unrealized_pnl=_decimal(data["unrealized_pnl"]),
            realized_pnl=_decimal(data["realized_pnl"]),
            total_pnl=_decimal(data["total_pnl"]),
            roi_pct=_decimal(data["roi_pct"]),
            starting_balance=_decimal(data["starting_balance"]),
            positions=tuple(Position.from_dict(p) for p in data.get("positions", [])),
            timestamp=_dt(data["timestamp"]),
        )


@dataclasses.dataclass(frozen=True)
class PnL:
    """P&L breakdown for a given time period.

    Returned by ``GET /api/v1/account/pnl``.

    Attributes:
        period:         Time window covered, e.g. ``"7d"``, ``"30d"``, ``"all"``.
        realized_pnl:   Realised profit/loss from closed trades in USDT.
        unrealized_pnl: Current unrealised profit/loss from open positions in USDT.
        total_pnl:      ``realized_pnl + unrealized_pnl``.
        fees_paid:      Total trading fees paid within the period in USDT.
        net_pnl:        ``total_pnl`` minus ``fees_paid``.
        winning_trades: Number of profitable closed trades.
        losing_trades:  Number of loss-making closed trades.
        win_rate:       Winning trades / total trades expressed as a percentage.

    Example::

        pnl = client.get_pnl(period="7d")
        print(pnl.win_rate, pnl.net_pnl)
    """

    period: str
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    fees_paid: Decimal
    net_pnl: Decimal
    winning_trades: int
    losing_trades: int
    win_rate: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PnL":
        """Deserialize a ``GET /account/pnl`` response dict.

        Args:
            data: Parsed JSON dict from the REST response body.

        Returns:
            A populated :class:`PnL` instance.
        """
        return cls(
            period=data["period"],
            realized_pnl=_decimal(data["realized_pnl"]),
            unrealized_pnl=_decimal(data["unrealized_pnl"]),
            total_pnl=_decimal(data["total_pnl"]),
            fees_paid=_decimal(data["fees_paid"]),
            net_pnl=_decimal(data["net_pnl"]),
            winning_trades=int(data["winning_trades"]),
            losing_trades=int(data["losing_trades"]),
            win_rate=_decimal(data["win_rate"]),
        )


# ---------------------------------------------------------------------------
# Order / trade models
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Order:
    """A single order (pending, filled, cancelled, or rejected).

    Returned by ``POST /api/v1/trade/order``,
    ``GET /api/v1/trade/order/{order_id}``,
    ``GET /api/v1/trade/orders``, and ``GET /api/v1/trade/orders/open``.

    Filled market-order fields (``executed_price``, ``executed_quantity``,
    ``slippage_pct``, ``fee``, ``total_cost``, ``filled_at``) are ``None``
    for pending or cancelled orders.

    Pending-order fields (``price``, ``locked_amount``, ``created_at``) may
    be ``None`` for filled orders depending on the endpoint variant.

    Attributes:
        order_id:           UUID of the order.
        status:             Current order status string.
        symbol:             Trading pair symbol.
        side:               ``"buy"`` or ``"sell"``.
        type:               Order type: ``"market"``, ``"limit"``, etc.
        quantity:           Requested base-asset quantity.
        price:              Limit/trigger price (``None`` for market orders).
        executed_price:     Actual fill price after slippage (filled orders).
        executed_quantity:  Actual filled quantity (filled orders).
        requested_quantity: Original requested quantity (filled market orders).
        slippage_pct:       Realised slippage percentage (filled orders).
        fee:                Trading fee in quote asset (filled orders).
        total_cost:         Total quote-asset cost/proceeds including fee.
        locked_amount:      USDT reserved as collateral (pending orders).
        created_at:         UTC timestamp of order submission.
        filled_at:          UTC timestamp of fill (filled orders).

    Example::

        order = client.place_market_order("BTCUSDT", "buy", 0.5)
        print(order.order_id, order.status, order.executed_price)
    """

    order_id: UUID
    status: str
    symbol: str
    side: str
    type: str
    quantity: Decimal | None
    price: Decimal | None
    executed_price: Decimal | None
    executed_quantity: Decimal | None
    requested_quantity: Decimal | None
    slippage_pct: Decimal | None
    fee: Decimal | None
    total_cost: Decimal | None
    locked_amount: Decimal | None
    created_at: datetime | None
    filled_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Order":
        """Deserialize an order response dict (any status variant).

        Handles both the ``OrderResponse`` shape (post-placement) and the
        ``OrderDetailResponse`` shape (get-by-id / list).

        Args:
            data: Parsed JSON dict from the REST response body.

        Returns:
            A populated :class:`Order` instance.
        """
        # Support both response shapes: ``executed_qty`` (detail) and
        # ``executed_quantity`` (placement).
        executed_quantity = data.get("executed_quantity") or data.get("executed_qty")
        # ``quantity`` is used as the base quantity field across both shapes.
        quantity = data.get("quantity") or data.get("requested_quantity")

        return cls(
            order_id=_uuid(data["order_id"]),
            status=data["status"],
            symbol=data["symbol"],
            side=data["side"],
            type=data["type"],
            quantity=_decimal_opt(quantity),
            price=_decimal_opt(data.get("price")),
            executed_price=_decimal_opt(data.get("executed_price")),
            executed_quantity=_decimal_opt(executed_quantity),
            requested_quantity=_decimal_opt(data.get("requested_quantity")),
            slippage_pct=_decimal_opt(data.get("slippage_pct")),
            fee=_decimal_opt(data.get("fee")),
            total_cost=_decimal_opt(data.get("total_cost")),
            locked_amount=_decimal_opt(data.get("locked_amount")),
            created_at=_dt_opt(data.get("created_at")),
            filled_at=_dt_opt(data.get("filled_at")),
        )


@dataclasses.dataclass(frozen=True)
class Trade:
    """A single executed trade record from the account trade history.

    One element of the list returned by ``GET /api/v1/trade/history``.

    Attributes:
        trade_id:    UUID of the trade record.
        order_id:    UUID of the originating order.
        symbol:      Trading pair symbol.
        side:        ``"buy"`` or ``"sell"``.
        quantity:    Executed base-asset quantity.
        price:       Actual fill price after slippage.
        fee:         Trading fee deducted in the quote asset.
        total:       Total quote-asset cost/proceeds including the fee.
        executed_at: UTC timestamp of execution.

    Example::

        history = client.get_trade_history(symbol="BTCUSDT", limit=50)
        for t in history:
            print(t.executed_at, t.side, t.price, t.quantity)
    """

    trade_id: UUID
    order_id: UUID
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    total: Decimal
    executed_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trade":
        """Deserialize a single trade history item dict.

        Args:
            data: One item from the ``trades`` array.

        Returns:
            A populated :class:`Trade` instance.
        """
        return cls(
            trade_id=_uuid(data["trade_id"]),
            order_id=_uuid(data["order_id"]),
            symbol=data["symbol"],
            side=data["side"],
            quantity=_decimal(data["quantity"]),
            price=_decimal(data["price"]),
            fee=_decimal(data["fee"]),
            total=_decimal(data["total"]),
            executed_at=_dt(data["executed_at"]),
        )


# ---------------------------------------------------------------------------
# Analytics models
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Performance:
    """Statistical performance metrics for a given time period.

    Returned by ``GET /api/v1/analytics/performance``.

    Attributes:
        period:                     Time window used for the calculation.
        sharpe_ratio:               Annualised Sharpe ratio (risk-adjusted return).
        sortino_ratio:              Annualised Sortino ratio (downside-risk adjusted).
        max_drawdown_pct:           Maximum peak-to-trough equity decline as a %.
        max_drawdown_duration_days: Number of snapshot periods spanning the drawdown.
        win_rate:                   Percentage of closed trades that were profitable.
        profit_factor:              Gross profit divided by gross loss (> 1 is good).
        avg_win:                    Average profit per winning trade in USDT.
        avg_loss:                   Average loss per losing trade in USDT (negative).
        total_trades:               Total number of closed trades in the period.
        avg_trades_per_day:         Average closed trades per calendar day.
        best_trade:                 Largest single winning trade in USDT.
        worst_trade:                Largest single losing trade in USDT (negative).
        current_streak:             Consecutive wins (positive) or losses (negative).

    Example::

        perf = client.get_performance(period="30d")
        print(perf.sharpe_ratio, perf.win_rate, perf.max_drawdown_pct)
    """

    period: str
    sharpe_ratio: Decimal
    sortino_ratio: Decimal
    max_drawdown_pct: Decimal
    max_drawdown_duration_days: int
    win_rate: Decimal
    profit_factor: Decimal
    avg_win: Decimal
    avg_loss: Decimal
    total_trades: int
    avg_trades_per_day: Decimal
    best_trade: Decimal
    worst_trade: Decimal
    current_streak: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Performance":
        """Deserialize a ``GET /analytics/performance`` response dict.

        Args:
            data: Parsed JSON dict from the REST response body.

        Returns:
            A populated :class:`Performance` instance.
        """
        return cls(
            period=data["period"],
            sharpe_ratio=_decimal(data["sharpe_ratio"]),
            sortino_ratio=_decimal(data["sortino_ratio"]),
            max_drawdown_pct=_decimal(data["max_drawdown_pct"]),
            max_drawdown_duration_days=int(data["max_drawdown_duration_days"]),
            win_rate=_decimal(data["win_rate"]),
            profit_factor=_decimal(data["profit_factor"]),
            avg_win=_decimal(data["avg_win"]),
            avg_loss=_decimal(data["avg_loss"]),
            total_trades=int(data["total_trades"]),
            avg_trades_per_day=_decimal(data["avg_trades_per_day"]),
            best_trade=_decimal(data["best_trade"]),
            worst_trade=_decimal(data["worst_trade"]),
            current_streak=int(data["current_streak"]),
        )


@dataclasses.dataclass(frozen=True)
class Snapshot:
    """A single portfolio equity snapshot data point.

    One element of the list returned by
    ``GET /api/v1/analytics/portfolio/history``.

    Attributes:
        time:           UTC timestamp of this snapshot.
        total_equity:   Total portfolio value in USDT at this point in time.
        unrealized_pnl: Unrealised P&L from open positions at snapshot time.
        realized_pnl:   Cumulative realised P&L from closed trades at snapshot time.

    Example::

        history = client.get_portfolio_history(interval="1h")
        for snap in history:
            print(snap.time, snap.total_equity)
    """

    time: datetime
    total_equity: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        """Deserialize a single snapshot item dict.

        Args:
            data: One item from the ``snapshots`` array.

        Returns:
            A populated :class:`Snapshot` instance.
        """
        return cls(
            time=_dt(data["time"]),
            total_equity=_decimal(data["total_equity"]),
            unrealized_pnl=_decimal(data["unrealized_pnl"]),
            realized_pnl=_decimal(data["realized_pnl"]),
        )


@dataclasses.dataclass(frozen=True)
class LeaderboardEntry:
    """A single agent entry in the cross-account performance leaderboard.

    One element of the ``rankings`` list returned by
    ``GET /api/v1/analytics/leaderboard``.

    Attributes:
        rank:         Position in the leaderboard (1 = best performer).
        account_id:   UUID of the ranked account.
        display_name: Human-readable name of the agent / bot.
        roi_pct:      Return on investment as a percentage vs starting balance.
        sharpe_ratio: Annualised Sharpe ratio for the leaderboard period.
        total_trades: Total closed trades in the period.
        win_rate:     Percentage of winning trades in the period.

    Example::

        rankings = client.get_leaderboard(period="7d")
        for entry in rankings[:3]:
            print(entry.rank, entry.display_name, entry.roi_pct)
    """

    rank: int
    account_id: UUID
    display_name: str
    roi_pct: Decimal
    sharpe_ratio: Decimal
    total_trades: int
    win_rate: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LeaderboardEntry":
        """Deserialize a single leaderboard entry dict.

        Args:
            data: One item from the ``rankings`` array.

        Returns:
            A populated :class:`LeaderboardEntry` instance.
        """
        return cls(
            rank=int(data["rank"]),
            account_id=_uuid(data["account_id"]),
            display_name=data["display_name"],
            roi_pct=_decimal(data["roi_pct"]),
            sharpe_ratio=_decimal(data["sharpe_ratio"]),
            total_trades=int(data["total_trades"]),
            win_rate=_decimal(data["win_rate"]),
        )


# ---------------------------------------------------------------------------
# Account info model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AccountInfo:
    """Full account information and configuration.

    Returned by ``GET /api/v1/account/info``.

    Attributes:
        account_id:              UUID of the account.
        display_name:            Human-readable name for the account / bot.
        status:                  Account lifecycle status: ``"active"``,
                                 ``"suspended"``, or ``"closed"``.
        starting_balance:        Session starting USDT balance.
        session_id:              UUID of the current trading session.
        session_started_at:      UTC timestamp when the current session began.
        max_position_size_pct:   Maximum single-position size as a % of equity.
        daily_loss_limit_pct:    Maximum daily loss allowed as a % of equity.
        max_open_orders:         Maximum number of concurrently open orders.
        created_at:              UTC timestamp of account creation.

    Example::

        info = client.get_account_info()
        print(info.display_name, info.status, info.starting_balance)
    """

    account_id: UUID
    display_name: str
    status: str
    starting_balance: Decimal
    session_id: UUID
    session_started_at: datetime
    max_position_size_pct: int
    daily_loss_limit_pct: int
    max_open_orders: int
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AccountInfo":
        """Deserialize a ``GET /account/info`` response dict.

        Args:
            data: Parsed JSON dict from the REST response body.

        Returns:
            A populated :class:`AccountInfo` instance.
        """
        session: dict[str, Any] = data.get("current_session", {})
        risk: dict[str, Any] = data.get("risk_profile", {})
        return cls(
            account_id=_uuid(data["account_id"]),
            display_name=data["display_name"],
            status=data["status"],
            starting_balance=_decimal(data["starting_balance"]),
            session_id=_uuid(session["session_id"]),
            session_started_at=_dt(session["started_at"]),
            max_position_size_pct=int(risk["max_position_size_pct"]),
            daily_loss_limit_pct=int(risk["daily_loss_limit_pct"]),
            max_open_orders=int(risk["max_open_orders"]),
            created_at=_dt(data["created_at"]),
        )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "Price",
    "Ticker",
    "Candle",
    "Balance",
    "Position",
    "Order",
    "Trade",
    "Portfolio",
    "PnL",
    "Performance",
    "Snapshot",
    "LeaderboardEntry",
    "AccountInfo",
]
