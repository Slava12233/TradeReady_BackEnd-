"""Unit tests for BinanceWebSocketClient message parsing and configuration.

Tests the _parse_message static method, stream URL building,
and reconnection backoff logic.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal
import json

from src.price_ingestion.binance_ws import BinanceWebSocketClient


def _make_trade_message(
    symbol="BTCUSDT",
    price="50000.00",
    quantity="0.01",
    timestamp_ms=1710500000000,
    is_buyer_maker=False,
    trade_id=123456,
) -> str:
    """Create a raw Binance combined-stream trade message."""
    return json.dumps(
        {
            "stream": f"{symbol.lower()}@trade",
            "data": {
                "e": "trade",
                "s": symbol,
                "p": price,
                "q": quantity,
                "T": timestamp_ms,
                "m": is_buyer_maker,
                "t": trade_id,
            },
        }
    )


class TestParseMessage:
    def test_parses_trade_message(self) -> None:
        """Valid trade JSON is parsed into a Tick namedtuple."""
        raw = _make_trade_message()
        tick = BinanceWebSocketClient._parse_message(raw)

        assert tick is not None
        assert tick.symbol == "BTCUSDT"
        assert tick.trade_id == 123456

    def test_parses_price_fields_as_decimal(self) -> None:
        """Price and quantity are Decimal, not float."""
        raw = _make_trade_message(price="64521.30000000", quantity="0.00120000")
        tick = BinanceWebSocketClient._parse_message(raw)

        assert tick is not None
        assert isinstance(tick.price, Decimal)
        assert isinstance(tick.quantity, Decimal)
        assert tick.price == Decimal("64521.30000000")
        assert tick.quantity == Decimal("0.00120000")

    def test_parses_timestamp_as_utc_datetime(self) -> None:
        """Timestamp is converted from milliseconds to UTC datetime."""
        raw = _make_trade_message(timestamp_ms=1710500000000)
        tick = BinanceWebSocketClient._parse_message(raw)

        assert tick is not None
        assert tick.timestamp.tzinfo is UTC

    def test_parses_buyer_maker_flag(self) -> None:
        """is_buyer_maker boolean is correctly parsed."""
        raw = _make_trade_message(is_buyer_maker=True)
        tick = BinanceWebSocketClient._parse_message(raw)

        assert tick is not None
        assert tick.is_buyer_maker is True

    def test_ignores_non_trade_messages(self) -> None:
        """Heartbeats and other event types return None."""
        raw = json.dumps({"stream": "btcusdt@ticker", "data": {"e": "24hrTicker", "s": "BTCUSDT"}})
        tick = BinanceWebSocketClient._parse_message(raw)

        assert tick is None

    def test_ignores_malformed_json(self) -> None:
        """Malformed JSON returns None without crashing."""
        tick = BinanceWebSocketClient._parse_message("not valid json{{{")

        assert tick is None

    def test_ignores_missing_fields(self) -> None:
        """Message with missing required fields returns None."""
        raw = json.dumps({"stream": "btcusdt@trade", "data": {"e": "trade"}})
        tick = BinanceWebSocketClient._parse_message(raw)

        assert tick is None

    def test_ignores_empty_data(self) -> None:
        """Message with no data field returns None."""
        raw = json.dumps({"stream": "btcusdt@trade"})
        tick = BinanceWebSocketClient._parse_message(raw)

        assert tick is None


class TestBuildStreamUrls:
    def test_single_chunk_url(self) -> None:
        """Few symbols produce a single combined-stream URL."""
        client = BinanceWebSocketClient(max_streams=1024)
        urls = client._build_stream_urls(["BTCUSDT", "ETHUSDT"])

        assert len(urls) == 1
        assert "btcusdt@trade" in urls[0]
        assert "ethusdt@trade" in urls[0]

    def test_multiple_chunks_for_many_symbols(self) -> None:
        """More symbols than max_streams produces multiple URLs."""
        client = BinanceWebSocketClient(max_streams=2)
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "DOTUSDT"]
        urls = client._build_stream_urls(symbols)

        assert len(urls) == 3  # ceil(5/2) = 3

    def test_subscribes_to_correct_stream_names(self) -> None:
        """Stream names use lowercase symbol + @trade suffix."""
        client = BinanceWebSocketClient()
        urls = client._build_stream_urls(["BTCUSDT"])

        assert "btcusdt@trade" in urls[0]

    def test_empty_symbols_returns_empty(self) -> None:
        """No symbols produces no URLs."""
        client = BinanceWebSocketClient()
        urls = client._build_stream_urls([])

        assert urls == []


class TestGetAllPairs:
    def test_get_all_pairs_returns_copy(self) -> None:
        """get_all_pairs returns a copy of the internal list."""
        client = BinanceWebSocketClient()
        client._symbols = ["BTCUSDT", "ETHUSDT"]

        pairs = client.get_all_pairs()

        assert pairs == ["BTCUSDT", "ETHUSDT"]
        # Mutating the returned list should not affect internal state
        pairs.append("SOLUSDT")
        assert len(client._symbols) == 2
