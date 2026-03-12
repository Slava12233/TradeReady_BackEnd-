"""WebSocket channel definitions.

Each channel class knows:

* its **name pattern** (used as the subscription key stored in
  ``Connection.subscriptions``),
* how to **build the channel name** from runtime parameters,
* how to **serialize** a raw payload dict into the wire-format envelope that
  is delivered to subscribed clients.

Channel name conventions
------------------------
* ``ticker:{symbol}``    — per-symbol real-time price updates
* ``ticker:all``         — price updates for every symbol on a single channel
* ``candles:{symbol}:{interval}``  — OHLCV candle updates (1m / 5m / 1h / 1d)
* ``orders``             — per-account order status updates (private)
* ``portfolio``          — per-account portfolio equity snapshots (private, ~5 s)

Wire-format envelopes
---------------------
Every message delivered to clients is a flat JSON object that includes at
least a ``"channel"`` key identifying which channel the data belongs to.
The ``"data"`` sub-object carries the channel-specific payload.

Example — ticker channel::

    {
        "channel": "ticker",
        "symbol": "BTCUSDT",
        "data": {
            "price": "64521.30",
            "quantity": "0.012",
            "timestamp": "2026-02-23T15:30:45.123Z",
            "is_buyer_maker": false
        }
    }

Example — orders channel::

    {
        "channel": "orders",
        "data": {
            "order_id": "660e8400-...",
            "status": "filled",
            "symbol": "BTCUSDT",
            "side": "buy",
            "executed_price": "64521.30",
            "executed_quantity": "0.50",
            "fee": "32.26",
            "filled_at": "2026-02-23T15:30:45.456Z"
        }
    }

Usage::

    from src.api.websocket.channels import TickerChannel, OrderChannel

    # Build the subscription key that clients use when subscribing
    channel_name = TickerChannel.channel_name("BTCUSDT")  # "ticker:BTCUSDT"

    # Serialise a broadcaster payload into the wire envelope
    envelope = TickerChannel.serialize("BTCUSDT", raw_payload)

    # Push the envelope to all subscribers
    await manager.broadcast_to_channel(channel_name, envelope)
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _str_decimal(value: Any) -> str:  # noqa: ANN401
    """Convert *value* to a string, normalising ``Decimal`` and ``float``.

    Args:
        value: Any value — typically a ``Decimal``, ``float``, or ``str``.

    Returns:
        String representation; Decimal values use fixed-point notation.
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _iso_timestamp(value: Any) -> str:  # noqa: ANN401
    """Convert *value* to an ISO-8601 UTC timestamp string.

    Accepts:
    * A ``datetime.datetime`` object (timezone-aware or naive UTC).
    * An integer or float millisecond epoch.
    * A string (returned as-is).

    Args:
        value: The timestamp to format.

    Returns:
        ISO-8601 string ending in ``"Z"``.
    """
    if isinstance(value, datetime.datetime):
        # Ensure the datetime is expressed in UTC
        if value.tzinfo is not None:
            dt = value.astimezone(datetime.UTC)
        else:
            dt = value.replace(tzinfo=datetime.UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, int | float):
        dt = datetime.datetime.fromtimestamp(value / 1000.0, tz=datetime.UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(value)


# ---------------------------------------------------------------------------
# TickerChannel
# ---------------------------------------------------------------------------


class TickerChannel:
    """Real-time price-update channel.

    Two subscription variants exist:

    * ``ticker:{symbol}`` — updates for a single trading pair.
    * ``ticker:all``      — updates for every pair (higher throughput).

    The Redis broadcaster publishes raw tick data on the ``price_updates``
    Redis pub/sub channel (see :mod:`src.price_ingestion.broadcaster`).
    The WebSocket handler fans those messages out to all connections
    subscribed to the matching ``ticker:{symbol}`` or ``ticker:all`` channel.

    Wire format::

        {
            "channel": "ticker",
            "symbol": "BTCUSDT",
            "data": {
                "price": "64521.30",
                "quantity": "0.012",
                "timestamp": "2026-02-23T15:30:45.123Z",
                "is_buyer_maker": false
            }
        }
    """

    #: Channel prefix used in subscription keys.
    PREFIX: str = "ticker"

    #: Wildcard channel name — clients subscribe to this to receive all pairs.
    ALL: str = "ticker:all"

    @classmethod
    def channel_name(cls, symbol: str) -> str:
        """Return the per-symbol subscription key.

        Args:
            symbol: Trading pair symbol, e.g. ``"BTCUSDT"``.

        Returns:
            Subscription key string, e.g. ``"ticker:BTCUSDT"``.
        """
        return f"{cls.PREFIX}:{symbol.upper()}"

    @classmethod
    def serialize(cls, symbol: str, raw: dict[str, Any]) -> dict[str, Any]:
        """Build the wire-format envelope from a raw broadcaster payload.

        The *raw* dict is the JSON object published by
        :class:`~src.price_ingestion.broadcaster.PriceBroadcaster` to the
        ``price_updates`` Redis channel.  Keys expected:

        * ``"price"``          — trade price (str / Decimal / float)
        * ``"quantity"``       — trade quantity (str / Decimal / float)
        * ``"timestamp"``      — millisecond epoch (int) or datetime
        * ``"is_buyer_maker"`` — bool

        Args:
            symbol: Trading pair symbol.
            raw:    Raw payload dict from the broadcaster.

        Returns:
            Envelope dict ready to pass to :meth:`ConnectionManager.broadcast_to_channel`.
        """
        data: dict[str, Any] = {
            "price": _str_decimal(raw.get("price", "0")),
            "quantity": _str_decimal(raw.get("quantity", "0")),
            "timestamp": _iso_timestamp(raw.get("timestamp", 0)),
            "is_buyer_maker": bool(raw.get("is_buyer_maker", False)),
        }
        return {
            "channel": cls.PREFIX,
            "symbol": symbol.upper(),
            "data": data,
        }

    @classmethod
    def channel_names_for_symbol(cls, symbol: str) -> tuple[str, str]:
        """Return both the per-symbol and the ``ticker:all`` channel names.

        The WebSocket handler broadcasts to both channels on every tick so
        clients subscribed to either variant receive the update.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Tuple of ``(ticker:{symbol}, ticker:all)``.
        """
        return cls.channel_name(symbol), cls.ALL


# ---------------------------------------------------------------------------
# CandleChannel
# ---------------------------------------------------------------------------


class CandleChannel:
    """Live OHLCV candle-update channel.

    Subscription key format: ``candles:{symbol}:{interval}``.

    Valid intervals: ``"1m"``, ``"5m"``, ``"1h"``, ``"1d"``.

    Wire format::

        {
            "channel": "candles",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "data": {
                "time": "2026-02-23T15:30:00Z",
                "open": "64500.00",
                "high": "64550.00",
                "low": "64490.00",
                "close": "64521.30",
                "volume": "12.345",
                "is_closed": false
            }
        }
    """

    #: Channel prefix used in subscription keys.
    PREFIX: str = "candles"

    #: Supported candle intervals.
    VALID_INTERVALS: frozenset[str] = frozenset({"1m", "5m", "1h", "1d"})

    @classmethod
    def channel_name(cls, symbol: str, interval: str) -> str:
        """Return the subscription key for a specific symbol and interval.

        Args:
            symbol:   Trading pair symbol, e.g. ``"BTCUSDT"``.
            interval: Candle interval, e.g. ``"1m"``.

        Returns:
            Subscription key, e.g. ``"candles:BTCUSDT:1m"``.

        Raises:
            ValueError: If *interval* is not in :attr:`VALID_INTERVALS`.
        """
        if interval not in cls.VALID_INTERVALS:
            raise ValueError(f"Invalid candle interval {interval!r}. Must be one of: {sorted(cls.VALID_INTERVALS)}")
        return f"{cls.PREFIX}:{symbol.upper()}:{interval}"

    @classmethod
    def serialize(
        cls,
        symbol: str,
        interval: str,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the wire-format envelope from a raw candle payload.

        Expected keys in *raw*:

        * ``"time"``      — candle open time (datetime or ms epoch)
        * ``"open"``      — open price
        * ``"high"``      — high price
        * ``"low"``       — low price
        * ``"close"``     — close price (last trade price so far)
        * ``"volume"``    — base-asset volume
        * ``"is_closed"`` — bool, ``True`` when the candle period has ended

        Args:
            symbol:   Trading pair symbol.
            interval: Candle interval string.
            raw:      Raw candle payload dict.

        Returns:
            Envelope dict ready for broadcast.
        """
        data: dict[str, Any] = {
            "time": _iso_timestamp(raw.get("time", 0)),
            "open": _str_decimal(raw.get("open", "0")),
            "high": _str_decimal(raw.get("high", "0")),
            "low": _str_decimal(raw.get("low", "0")),
            "close": _str_decimal(raw.get("close", "0")),
            "volume": _str_decimal(raw.get("volume", "0")),
            "is_closed": bool(raw.get("is_closed", False)),
        }
        return {
            "channel": cls.PREFIX,
            "symbol": symbol.upper(),
            "interval": interval,
            "data": data,
        }


# ---------------------------------------------------------------------------
# OrderChannel
# ---------------------------------------------------------------------------


class OrderChannel:
    """Per-account order-status update channel (private).

    This channel is **per-account** — messages are pushed via
    :meth:`~src.api.websocket.manager.ConnectionManager.broadcast_to_account`
    rather than :meth:`~src.api.websocket.manager.ConnectionManager.broadcast_to_channel`.

    Clients subscribe by sending ``{"action": "subscribe", "channel": "orders"}``.
    No ``symbol`` is required.

    Wire format::

        {
            "channel": "orders",
            "data": {
                "order_id": "660e8400-...",
                "status": "filled",
                "symbol": "BTCUSDT",
                "side": "buy",
                "type": "market",
                "quantity": "0.50",
                "executed_price": "64521.30",
                "executed_quantity": "0.50",
                "fee": "32.26",
                "filled_at": "2026-02-23T15:30:45.456Z"
            }
        }
    """

    #: Channel name — also used as the subscription key.
    NAME: str = "orders"

    @classmethod
    def channel_name(cls) -> str:
        """Return the fixed channel subscription key.

        Returns:
            ``"orders"``
        """
        return cls.NAME

    @classmethod
    def serialize(cls, raw: dict[str, Any]) -> dict[str, Any]:
        """Build the wire-format envelope for an order-status event.

        Expected keys in *raw*:

        * ``"order_id"``           — UUID string
        * ``"status"``             — ``"filled"``, ``"cancelled"``, ``"rejected"``, etc.
        * ``"symbol"``             — trading pair, e.g. ``"BTCUSDT"``
        * ``"side"``               — ``"buy"`` or ``"sell"``
        * ``"type"``               — order type (``"market"``, ``"limit"``, …)
        * ``"quantity"``           — original order quantity
        * ``"executed_price"``     — execution price (optional, for fills)
        * ``"executed_quantity"``  — filled quantity (optional, for fills)
        * ``"fee"``                — fee charged (optional, for fills)
        * ``"filled_at"``          — ISO timestamp or ms epoch (optional, for fills)
        * ``"cancelled_at"``       — ISO timestamp or ms epoch (optional, for cancels)
        * ``"rejected_reason"``    — rejection reason string (optional)

        Args:
            raw: Raw order event dict from the order engine or route handler.

        Returns:
            Envelope dict ready for :meth:`ConnectionManager.broadcast_to_account`.
        """
        data: dict[str, Any] = {
            "order_id": str(raw.get("order_id", "")),
            "status": str(raw.get("status", "")),
            "symbol": str(raw.get("symbol", "")),
            "side": str(raw.get("side", "")),
            "type": str(raw.get("type", "")),
            "quantity": _str_decimal(raw.get("quantity", "0")),
        }

        # Optional fields — only include if present in the raw payload
        if "executed_price" in raw and raw["executed_price"] is not None:
            data["executed_price"] = _str_decimal(raw["executed_price"])
        if "executed_quantity" in raw and raw["executed_quantity"] is not None:
            data["executed_quantity"] = _str_decimal(raw["executed_quantity"])
        if "fee" in raw and raw["fee"] is not None:
            data["fee"] = _str_decimal(raw["fee"])
        if "filled_at" in raw and raw["filled_at"] is not None:
            data["filled_at"] = _iso_timestamp(raw["filled_at"])
        if "cancelled_at" in raw and raw["cancelled_at"] is not None:
            data["cancelled_at"] = _iso_timestamp(raw["cancelled_at"])
        if "rejected_reason" in raw and raw["rejected_reason"] is not None:
            data["rejected_reason"] = str(raw["rejected_reason"])
        if "price" in raw and raw["price"] is not None:
            data["price"] = _str_decimal(raw["price"])

        return {"channel": cls.NAME, "data": data}


# ---------------------------------------------------------------------------
# PortfolioChannel
# ---------------------------------------------------------------------------


class PortfolioChannel:
    """Per-account portfolio-equity snapshot channel (private).

    Like :class:`OrderChannel`, this is a **per-account** channel.  The
    server pushes updates approximately every 5 seconds (driven by a Celery
    beat task or an asyncio loop in the handler).

    Clients subscribe by sending
    ``{"action": "subscribe", "channel": "portfolio"}``.

    Wire format::

        {
            "channel": "portfolio",
            "data": {
                "total_equity": "12458.30",
                "unrealized_pnl": "660.65",
                "realized_pnl": "1241.30",
                "available_cash": "5000.00",
                "timestamp": "2026-02-23T15:30:45Z"
            }
        }
    """

    #: Channel name — also used as the subscription key.
    NAME: str = "portfolio"

    @classmethod
    def channel_name(cls) -> str:
        """Return the fixed channel subscription key.

        Returns:
            ``"portfolio"``
        """
        return cls.NAME

    @classmethod
    def serialize(cls, raw: dict[str, Any]) -> dict[str, Any]:
        """Build the wire-format envelope for a portfolio-snapshot event.

        Expected keys in *raw*:

        * ``"total_equity"``    — total account equity in USDT
        * ``"unrealized_pnl"``  — unrealised profit/loss
        * ``"realized_pnl"``    — realised profit/loss for the session
        * ``"available_cash"``  — free USDT balance (optional)
        * ``"timestamp"``       — snapshot time (datetime or ms epoch);
          defaults to the current UTC time if omitted

        Args:
            raw: Raw portfolio snapshot dict from
                 :class:`~src.portfolio.tracker.PortfolioTracker` or a
                 Celery snapshot task.

        Returns:
            Envelope dict ready for :meth:`ConnectionManager.broadcast_to_account`.
        """
        timestamp = raw.get("timestamp") or datetime.datetime.now(datetime.UTC)

        data: dict[str, Any] = {
            "total_equity": _str_decimal(raw.get("total_equity", "0")),
            "unrealized_pnl": _str_decimal(raw.get("unrealized_pnl", "0")),
            "realized_pnl": _str_decimal(raw.get("realized_pnl", "0")),
            "timestamp": _iso_timestamp(timestamp),
        }

        if "available_cash" in raw and raw["available_cash"] is not None:
            data["available_cash"] = _str_decimal(raw["available_cash"])

        return {"channel": cls.NAME, "data": data}


# ---------------------------------------------------------------------------
# Channel registry helpers
# ---------------------------------------------------------------------------

#: All private per-account channel names (not routed via broadcast_to_channel).
PRIVATE_CHANNELS: frozenset[str] = frozenset({OrderChannel.NAME, PortfolioChannel.NAME})

#: All public channel prefixes (routed via broadcast_to_channel).
PUBLIC_CHANNEL_PREFIXES: frozenset[str] = frozenset({TickerChannel.PREFIX, CandleChannel.PREFIX})


def resolve_channel_name(action_payload: dict[str, Any]) -> str | None:
    """Derive the subscription key from a client ``subscribe`` / ``unsubscribe`` message.

    Accepts payloads of the form::

        {"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"}
        {"action": "subscribe", "channel": "candles", "symbol": "BTCUSDT", "interval": "1m"}
        {"action": "subscribe", "channel": "orders"}
        {"action": "subscribe", "channel": "portfolio"}

    Args:
        action_payload: The parsed JSON dict sent by the client.

    Returns:
        The resolved subscription key string, or ``None`` if the payload is
        malformed or the channel is unknown.
    """
    channel = action_payload.get("channel", "")

    if channel == TickerChannel.PREFIX:
        symbol = action_payload.get("symbol", "").strip().upper()
        if not symbol:
            return None
        return TickerChannel.channel_name(symbol)

    if channel == "ticker_all":
        return TickerChannel.ALL

    if channel == CandleChannel.PREFIX:
        symbol = action_payload.get("symbol", "").strip().upper()
        interval = action_payload.get("interval", "").strip()
        if not symbol or not interval:
            return None
        if interval not in CandleChannel.VALID_INTERVALS:
            return None
        return CandleChannel.channel_name(symbol, interval)

    if channel == OrderChannel.NAME:
        return OrderChannel.channel_name()

    if channel == PortfolioChannel.NAME:
        return PortfolioChannel.channel_name()

    return None
