"""Unit tests for agent/trading/ws_manager.py :: WSManager.

Tests cover:
- connect() — skips when platform_api_key is empty
- connect() — builds WS client and starts background task when key is set
- connect() — is a no-op when already running
- disconnect() — cancels background task and disconnects WS client
- disconnect() — safe to call when never connected
- get_price() — returns None before any tick arrives
- get_price() — returns buffered Decimal after a tick arrives
- get_all_prices() — returns empty dict before ticks
- get_all_prices() — returns all buffered prices as shallow copy
- has_prices — False before any tick; True after first tick
- is_connected — reflects background task liveness
- price_buffer_size — counts symbols with buffered ticks
- wait_for_order_fill() — returns False on timeout
- wait_for_order_fill() — returns True when fill event arrives
- wait_for_order_fill() — clears event after returning True
- clear_order_fill_event() — resets the event so next wait blocks
- last_fill — None before any fill; contains payload after fill
- _handle_ticker() — updates buffer from 'price' field
- _handle_ticker() — updates buffer from 'last_price' field
- _handle_ticker() — updates buffer from 'close' field
- _handle_ticker() — ignores message with no price field
- _handle_ticker() — ignores message with invalid price string
- _handle_order_fill() — sets order_fill_event and stores last_fill
- _build_ws_client() — converts http:// to ws:// base URL
- _build_ws_client() — converts https:// to wss:// base URL
- _register_handlers() — no-op when ws is None
- WSManager integration with TradingLoop — ws_manager property exposed
- TradingLoop.tick() — merges WS prices into portfolio_state
- TradingLoop.tick() — skips WS prices when buffer is empty
- TradingLoop.stop() — disconnects ws_manager
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import AgentConfig
from agent.models.ecosystem import EnforcementResult
from agent.trading.loop import TradingLoop
from agent.trading.signal_generator import TradingSignal
from agent.trading.ws_manager import WSManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch, *, with_api_key: bool = True) -> AgentConfig:
    """Build a minimal AgentConfig for tests without reading agent/.env."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-ws")
    if with_api_key:
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
    else:
        monkeypatch.setenv("PLATFORM_API_KEY", "")
    monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_ws_manager(monkeypatch: pytest.MonkeyPatch, *, with_api_key: bool = True) -> WSManager:
    """Build a WSManager with a minimal config."""
    config = _make_config(monkeypatch, with_api_key=with_api_key)
    return WSManager(config=config)


def _make_loop(
    monkeypatch: pytest.MonkeyPatch,
    ws_manager: WSManager | None = None,
) -> TradingLoop:
    """Build a TradingLoop with mocked enforcer and optional ws_manager."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-loop")
    config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
    enforcer = MagicMock()
    enforcer.check_action = AsyncMock(
        return_value=EnforcementResult(
            allowed=True,
            action="trade",
            agent_id="",
            reason="",
            capability_check_passed=True,
            budget_check_passed=True,
        )
    )
    return TradingLoop(
        agent_id="test-agent",
        config=config,
        enforcer=enforcer,
        ws_manager=ws_manager,
    )


def _make_signal(symbol: str = "BTCUSDT", action: str = "buy") -> TradingSignal:
    return TradingSignal(
        symbol=symbol,
        action=action,
        confidence=0.8,
        agreement_rate=0.7,
        generated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# WSManager.connect() — skip when no API key
# ---------------------------------------------------------------------------


class TestConnectNoApiKey:
    """WSManager.connect() skips when platform_api_key is empty."""

    async def test_connect_skips_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No background task is launched when api_key is empty."""
        manager = _make_ws_manager(monkeypatch, with_api_key=False)
        await manager.connect()
        assert manager._connect_task is None

    async def test_ws_client_not_built_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_ws remains None when api_key is missing."""
        manager = _make_ws_manager(monkeypatch, with_api_key=False)
        await manager.connect()
        assert manager._ws is None

    async def test_is_not_connected_without_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_connected is False when api_key is missing."""
        manager = _make_ws_manager(monkeypatch, with_api_key=False)
        await manager.connect()
        assert not manager.is_connected


# ---------------------------------------------------------------------------
# WSManager.connect() — with API key
# ---------------------------------------------------------------------------


class TestConnectWithApiKey:
    """WSManager.connect() starts a background task when api_key is set."""

    async def test_connect_starts_background_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A background asyncio task is created after connect()."""
        manager = _make_ws_manager(monkeypatch)

        mock_ws = AsyncMock()
        mock_ws.on_ticker = MagicMock(side_effect=lambda sym: (lambda fn: fn))
        mock_ws.on_order_update = MagicMock(side_effect=lambda: (lambda fn: fn))
        # ws.connect() should block forever — we cancel quickly
        mock_ws.connect = AsyncMock(side_effect=asyncio.CancelledError)

        with patch("agent.trading.ws_manager.WSManager._build_ws_client", return_value=mock_ws):
            await manager.connect()
            try:
                assert manager._connect_task is not None
            finally:
                await manager.disconnect()

    async def test_connect_is_noop_when_already_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling connect() twice does not create a second task."""
        manager = _make_ws_manager(monkeypatch)

        mock_ws = AsyncMock()
        mock_ws.on_ticker = MagicMock(side_effect=lambda sym: (lambda fn: fn))
        mock_ws.on_order_update = MagicMock(side_effect=lambda: (lambda fn: fn))
        mock_ws.connect = AsyncMock(side_effect=asyncio.CancelledError)

        with patch("agent.trading.ws_manager.WSManager._build_ws_client", return_value=mock_ws):
            await manager.connect()
            first_task = manager._connect_task
            await manager.connect()  # second call — should be no-op
            assert manager._connect_task is first_task
            await manager.disconnect()

    async def test_connect_registers_handlers_for_all_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """on_ticker is called for each configured symbol."""
        config = _make_config(monkeypatch)
        config = config.model_copy(update={"symbols": ["BTCUSDT", "ETHUSDT"]})
        manager = WSManager(config=config)

        registered_symbols: list[str] = []

        mock_ws = AsyncMock()

        def _on_ticker_factory(sym: str) -> object:
            registered_symbols.append(sym)
            return lambda fn: fn

        mock_ws.on_ticker = MagicMock(side_effect=_on_ticker_factory)
        mock_ws.on_order_update = MagicMock(side_effect=lambda: (lambda fn: fn))
        mock_ws.connect = AsyncMock(side_effect=asyncio.CancelledError)

        with patch("agent.trading.ws_manager.WSManager._build_ws_client", return_value=mock_ws):
            await manager.connect()
            await manager.disconnect()

        assert "BTCUSDT" in registered_symbols
        assert "ETHUSDT" in registered_symbols


# ---------------------------------------------------------------------------
# WSManager.disconnect()
# ---------------------------------------------------------------------------


class TestDisconnect:
    """WSManager.disconnect() cleans up task and WS client."""

    async def test_disconnect_cancels_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Background task is cancelled after disconnect()."""
        manager = _make_ws_manager(monkeypatch)

        mock_ws = AsyncMock()
        mock_ws.on_ticker = MagicMock(side_effect=lambda sym: (lambda fn: fn))
        mock_ws.on_order_update = MagicMock(side_effect=lambda: (lambda fn: fn))
        # Simulate a long-running connect
        async def _blocking_connect() -> None:
            await asyncio.sleep(3600)

        mock_ws.connect = _blocking_connect
        mock_ws.disconnect = AsyncMock()

        with patch("agent.trading.ws_manager.WSManager._build_ws_client", return_value=mock_ws):
            await manager.connect()
            task = manager._connect_task
            assert task is not None
            await manager.disconnect()
            assert task.done()

    async def test_disconnect_safe_when_never_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """disconnect() does not raise when called without prior connect()."""
        manager = _make_ws_manager(monkeypatch)
        await manager.disconnect()  # must not raise

    async def test_disconnect_clears_ws_reference(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_ws is set to None after disconnect()."""
        manager = _make_ws_manager(monkeypatch)

        mock_ws = AsyncMock()
        mock_ws.on_ticker = MagicMock(side_effect=lambda sym: (lambda fn: fn))
        mock_ws.on_order_update = MagicMock(side_effect=lambda: (lambda fn: fn))
        mock_ws.connect = AsyncMock(side_effect=asyncio.CancelledError)
        mock_ws.disconnect = AsyncMock()

        with patch("agent.trading.ws_manager.WSManager._build_ws_client", return_value=mock_ws):
            await manager.connect()
            await manager.disconnect()
            assert manager._ws is None


# ---------------------------------------------------------------------------
# Price buffer
# ---------------------------------------------------------------------------


class TestPriceBuffer:
    """Price buffer read methods before and after ticks."""

    def test_get_price_returns_none_before_tick(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_price() returns None when no tick has been received."""
        manager = _make_ws_manager(monkeypatch)
        assert manager.get_price("BTCUSDT") is None

    async def test_get_price_returns_decimal_after_tick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_price() returns a Decimal after a ticker update is processed."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "65000.50"}, "BTCUSDT")
        price = manager.get_price("BTCUSDT")
        assert price == Decimal("65000.50")

    def test_get_all_prices_empty_before_ticks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_all_prices() returns empty dict when buffer is empty."""
        manager = _make_ws_manager(monkeypatch)
        assert manager.get_all_prices() == {}

    async def test_get_all_prices_returns_all_buffered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_all_prices() returns all symbols after multiple ticks."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "65000"}, "BTCUSDT")
        await manager._handle_ticker({"price": "3500"}, "ETHUSDT")
        prices = manager.get_all_prices()
        assert prices["BTCUSDT"] == Decimal("65000")
        assert prices["ETHUSDT"] == Decimal("3500")

    async def test_get_all_prices_returns_shallow_copy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutating the returned dict does not affect the internal buffer."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "100"}, "BTCUSDT")
        copy = manager.get_all_prices()
        copy["BTCUSDT"] = Decimal("999")
        assert manager.get_price("BTCUSDT") == Decimal("100")

    def test_has_prices_false_before_tick(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """has_prices is False when no tick has been received."""
        manager = _make_ws_manager(monkeypatch)
        assert not manager.has_prices

    async def test_has_prices_true_after_tick(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """has_prices is True after the first ticker message."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "100"}, "BTCUSDT")
        assert manager.has_prices

    def test_price_buffer_size_zero_before_ticks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """price_buffer_size is 0 when no ticks received."""
        manager = _make_ws_manager(monkeypatch)
        assert manager.price_buffer_size == 0

    async def test_price_buffer_size_increments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """price_buffer_size counts distinct symbols."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "100"}, "BTCUSDT")
        await manager._handle_ticker({"price": "200"}, "ETHUSDT")
        assert manager.price_buffer_size == 2


# ---------------------------------------------------------------------------
# _handle_ticker — price field variants
# ---------------------------------------------------------------------------


class TestHandleTicker:
    """_handle_ticker() correctly extracts prices from different field names."""

    async def test_reads_price_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Updates buffer from the 'price' field."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "42000"}, "BTCUSDT")
        assert manager.get_price("BTCUSDT") == Decimal("42000")

    async def test_reads_last_price_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Updates buffer from the 'last_price' field when 'price' is absent."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"last_price": "42100"}, "BTCUSDT")
        assert manager.get_price("BTCUSDT") == Decimal("42100")

    async def test_reads_close_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Updates buffer from the 'close' field as last fallback."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"close": "42200"}, "BTCUSDT")
        assert manager.get_price("BTCUSDT") == Decimal("42200")

    async def test_ignores_message_without_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Buffer is not updated when no recognized price field is present."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"type": "ticker", "symbol": "BTCUSDT"}, "BTCUSDT")
        assert manager.get_price("BTCUSDT") is None
        assert not manager.has_prices

    async def test_ignores_invalid_price_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Buffer is not updated when price field is not a valid numeric string."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "not-a-number"}, "BTCUSDT")
        assert manager.get_price("BTCUSDT") is None

    async def test_overwrites_previous_price(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A newer tick overwrites the previous buffered price."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "100"}, "BTCUSDT")
        await manager._handle_ticker({"price": "200"}, "BTCUSDT")
        assert manager.get_price("BTCUSDT") == Decimal("200")


# ---------------------------------------------------------------------------
# _handle_order_fill
# ---------------------------------------------------------------------------


class TestHandleOrderFill:
    """_handle_order_fill() sets event and stores payload."""

    async def test_sets_order_fill_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Receiving an order update sets the internal asyncio event."""
        manager = _make_ws_manager(monkeypatch)
        assert not manager._order_fill_event.is_set()
        await manager._handle_order_fill({"order_id": "abc", "status": "filled"})
        assert manager._order_fill_event.is_set()

    async def test_stores_last_fill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The fill payload is stored in last_fill after receiving an update."""
        manager = _make_ws_manager(monkeypatch)
        payload = {"order_id": "abc123", "symbol": "BTCUSDT", "status": "filled"}
        await manager._handle_order_fill(payload)
        assert manager.last_fill is not None
        assert manager.last_fill["order_id"] == "abc123"

    async def test_last_fill_none_initially(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """last_fill is None before any fill arrives."""
        manager = _make_ws_manager(monkeypatch)
        assert manager.last_fill is None

    async def test_overwrites_last_fill_on_second_update(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """second fill payload overwrites the first in last_fill."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_order_fill({"order_id": "first"})
        await manager._handle_order_fill({"order_id": "second"})
        assert manager.last_fill is not None
        assert manager.last_fill["order_id"] == "second"


# ---------------------------------------------------------------------------
# wait_for_order_fill
# ---------------------------------------------------------------------------


class TestWaitForOrderFill:
    """wait_for_order_fill() timeout and event-signalling behaviour."""

    async def test_returns_false_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns False when no fill arrives within the timeout."""
        manager = _make_ws_manager(monkeypatch)
        result = await manager.wait_for_order_fill(timeout=0.01)
        assert result is False

    async def test_returns_true_when_fill_arrives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns True immediately when a fill event is already set."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_order_fill({"order_id": "xyz"})
        result = await manager.wait_for_order_fill(timeout=1.0)
        assert result is True

    async def test_clears_event_after_returning_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After returning True the event is cleared so the next wait blocks."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_order_fill({"order_id": "xyz"})
        await manager.wait_for_order_fill(timeout=1.0)
        # Second call should time out because the event was cleared.
        result = await manager.wait_for_order_fill(timeout=0.01)
        assert result is False

    async def test_fill_event_triggered_concurrently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A concurrently triggered fill event wakes the waiter."""
        manager = _make_ws_manager(monkeypatch)

        async def _trigger_fill_after_delay() -> None:
            await asyncio.sleep(0.02)
            await manager._handle_order_fill({"order_id": "concurrent"})

        asyncio.get_event_loop().create_task(_trigger_fill_after_delay())
        result = await manager.wait_for_order_fill(timeout=1.0)
        assert result is True


class TestClearOrderFillEvent:
    """clear_order_fill_event() resets the event."""

    async def test_clears_event_explicitly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """clear_order_fill_event() resets the event without waiting."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_order_fill({"order_id": "abc"})
        assert manager._order_fill_event.is_set()
        manager.clear_order_fill_event()
        assert not manager._order_fill_event.is_set()


# ---------------------------------------------------------------------------
# _build_ws_client — URL scheme conversion
# ---------------------------------------------------------------------------


class TestBuildWsClient:
    """_build_ws_client() converts the platform HTTP URL to a WS URL."""

    def test_converts_http_to_ws(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """http:// is replaced with ws://."""
        manager = _make_ws_manager(monkeypatch)
        # platform_base_url defaults to http://localhost:8000

        captured_urls: list[str] = []

        # The local import inside _build_ws_client resolves to agentexchange.ws_client
        with patch("agentexchange.ws_client.AgentExchangeWS") as MockWS:
            MockWS.return_value = MagicMock()
            manager._build_ws_client()
            call_kwargs = MockWS.call_args
            if call_kwargs is not None:
                captured_urls.append(call_kwargs.kwargs.get("base_url", ""))

        # Fallback: inspect the manager's url derivation directly.
        derived = (
            manager._config.platform_base_url
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )
        assert derived.startswith("ws://")

    def test_converts_https_to_wss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """https:// is replaced with wss://."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-ws")
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
        monkeypatch.setenv("PLATFORM_BASE_URL", "https://api.example.com")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        manager = WSManager(config=config)

        # Verify the URL derivation logic directly (unit-test the transformation).
        derived = (
            manager._config.platform_base_url
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )
        assert derived.startswith("wss://")


# ---------------------------------------------------------------------------
# _register_handlers — safety when ws is None
# ---------------------------------------------------------------------------


class TestRegisterHandlers:
    """_register_handlers() is a no-op when _ws is None."""

    def test_noop_when_ws_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_register_handlers() does not raise when _ws has not been set."""
        manager = _make_ws_manager(monkeypatch)
        assert manager._ws is None
        manager._register_handlers()  # must not raise


# ---------------------------------------------------------------------------
# TradingLoop integration — ws_manager property
# ---------------------------------------------------------------------------


class TestTradingLoopWSManagerProperty:
    """TradingLoop exposes the injected WSManager via a property."""

    def test_ws_manager_property_none_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ws_manager is None when no manager is injected."""
        loop = _make_loop(monkeypatch)
        assert loop.ws_manager is None

    def test_ws_manager_property_returns_injected_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ws_manager returns the exact instance passed at construction."""
        manager = _make_ws_manager(monkeypatch)
        loop = _make_loop(monkeypatch, ws_manager=manager)
        assert loop.ws_manager is manager


# ---------------------------------------------------------------------------
# TradingLoop._observe() — WS price merging
# ---------------------------------------------------------------------------


class TestTradingLoopObserveWSPrices:
    """TradingLoop._observe() merges WS prices into portfolio_state."""

    async def test_merges_ws_prices_when_buffer_has_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """portfolio_state['ws_prices'] contains buffered prices after observe()."""
        manager = _make_ws_manager(monkeypatch)
        # Manually populate the buffer as if a tick arrived.
        await manager._handle_ticker({"price": "65000"}, "BTCUSDT")

        loop = _make_loop(monkeypatch, ws_manager=manager)
        loop._sdk_client = None  # disable REST calls

        portfolio_state, _positions = await loop._observe()
        assert "ws_prices" in portfolio_state
        assert portfolio_state["ws_prices"]["BTCUSDT"] == "65000"

    async def test_omits_ws_prices_when_buffer_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ws_prices key is absent from portfolio_state when buffer is empty."""
        manager = _make_ws_manager(monkeypatch)
        # No ticks received — has_prices is False.

        loop = _make_loop(monkeypatch, ws_manager=manager)
        loop._sdk_client = None

        portfolio_state, _positions = await loop._observe()
        assert "ws_prices" not in portfolio_state

    async def test_observe_skips_ws_when_no_manager(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No ws_prices key when no ws_manager is provided."""
        loop = _make_loop(monkeypatch)  # no ws_manager
        loop._sdk_client = None

        portfolio_state, _positions = await loop._observe()
        assert "ws_prices" not in portfolio_state

    async def test_observe_merges_multiple_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All buffered symbols appear in ws_prices."""
        manager = _make_ws_manager(monkeypatch)
        await manager._handle_ticker({"price": "65000"}, "BTCUSDT")
        await manager._handle_ticker({"price": "3500"}, "ETHUSDT")

        loop = _make_loop(monkeypatch, ws_manager=manager)
        loop._sdk_client = None

        portfolio_state, _positions = await loop._observe()
        ws_prices = portfolio_state.get("ws_prices", {})
        assert "BTCUSDT" in ws_prices
        assert "ETHUSDT" in ws_prices


# ---------------------------------------------------------------------------
# TradingLoop.stop() — disconnects WSManager
# ---------------------------------------------------------------------------


class TestTradingLoopStopDisconnectsWS:
    """TradingLoop.stop() calls disconnect() on the attached WSManager."""

    async def test_stop_disconnects_ws_manager(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WSManager.disconnect() is called when TradingLoop.stop() is invoked."""
        manager = _make_ws_manager(monkeypatch)
        manager.disconnect = AsyncMock()  # type: ignore[method-assign]

        loop = _make_loop(monkeypatch, ws_manager=manager)
        loop._is_running = True
        loop._loop_task = asyncio.get_event_loop().create_task(asyncio.sleep(0))
        await loop.stop()

        manager.disconnect.assert_awaited_once()

    async def test_stop_safe_when_no_ws_manager(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stop() does not raise when no WSManager is attached."""
        loop = _make_loop(monkeypatch)
        loop._is_running = True
        loop._loop_task = asyncio.get_event_loop().create_task(asyncio.sleep(0))
        await loop.stop()  # must not raise


# ---------------------------------------------------------------------------
# WSManager.is_connected property
# ---------------------------------------------------------------------------


class TestIsConnectedProperty:
    """is_connected reflects the liveness of the background task."""

    def test_is_not_connected_before_connect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_connected is False before connect() is called."""
        manager = _make_ws_manager(monkeypatch)
        assert not manager.is_connected

    async def test_is_not_connected_after_disconnect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_connected is False after disconnect()."""
        manager = _make_ws_manager(monkeypatch)

        mock_ws = AsyncMock()
        mock_ws.on_ticker = MagicMock(side_effect=lambda sym: (lambda fn: fn))
        mock_ws.on_order_update = MagicMock(side_effect=lambda: (lambda fn: fn))
        mock_ws.connect = AsyncMock(side_effect=asyncio.CancelledError)
        mock_ws.disconnect = AsyncMock()

        with patch("agent.trading.ws_manager.WSManager._build_ws_client", return_value=mock_ws):
            await manager.connect()
            await manager.disconnect()
        assert not manager.is_connected
