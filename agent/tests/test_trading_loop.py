"""Unit tests for agent/trading/loop.py :: TradingLoop.

Tests cover:
- tick() — full cycle with signals, permission check, execution
- tick() — raises LoopStoppedError after stop() is called
- tick() — permission denial prevents trade execution
- tick() — below-confidence signals are filtered out (no execution)
- tick() — signal generator failure is non-fatal; errors are recorded
- tick() — record step failure is non-fatal; errors are recorded
- tick() — learn step failure is non-fatal (never crashes cycle)
- tick() — no SDK client, no execution attempted
- tick() — consecutive cycles increment cycle_counter
- _estimate_trade_value() — uses portfolio equity when available
- _estimate_trade_value() — falls back to 100.00 when portfolio is empty
- _observe() — returns empty structures when SDK client is None
- _observe() — SDK failure is swallowed; returns empty structures
- start() / stop() — is_running reflects state correctly
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.config import AgentConfig
from agent.models.ecosystem import EnforcementResult, TradingCycleResult
from agent.trading.loop import LoopStoppedError, TradingLoop
from agent.trading.signal_generator import TradingSignal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    """Build a minimal AgentConfig for tests without reading agent/.env."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-loop")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_signal(
    symbol: str = "BTCUSDT",
    action: str = "buy",
    confidence: float = 0.75,
) -> TradingSignal:
    """Build a TradingSignal for testing."""
    return TradingSignal(
        symbol=symbol,
        action=action,
        confidence=confidence,
        agreement_rate=0.67,
        generated_at=datetime.now(UTC),
    )


def _allowed_enforcement(agent_id: str = "") -> EnforcementResult:
    """Return an EnforcementResult with allowed=True."""
    return EnforcementResult(
        allowed=True,
        action="trade",
        agent_id=agent_id,
        reason="",
        capability_check_passed=True,
        budget_check_passed=True,
    )


def _denied_enforcement(agent_id: str = "", reason: str = "Budget exhausted") -> EnforcementResult:
    """Return an EnforcementResult with allowed=False."""
    return EnforcementResult(
        allowed=False,
        action="trade",
        agent_id=agent_id,
        reason=reason,
        capability_check_passed=True,
        budget_check_passed=False,
    )


def _make_loop(
    config: AgentConfig,
    signal_generator: MagicMock | None = None,
    sdk_client: MagicMock | None = None,
) -> tuple[TradingLoop, MagicMock]:
    """Build a TradingLoop with a mocked enforcer."""
    enforcer = MagicMock()
    enforcer.check_action = AsyncMock(return_value=_allowed_enforcement())
    agent_id = str(uuid4())
    loop = TradingLoop(
        agent_id=agent_id,
        config=config,
        enforcer=enforcer,
        signal_generator=signal_generator,
        sdk_client=sdk_client,
    )
    return loop, enforcer


# ---------------------------------------------------------------------------
# TestTradingLoopTick
# ---------------------------------------------------------------------------


class TestTradingLoopTick:
    """Tests for TradingLoop.tick()."""

    async def test_tick_raises_loop_stopped_error_after_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tick() raises LoopStoppedError when the stop event is set."""
        config = _make_config(monkeypatch)
        loop, _ = _make_loop(config)
        # Set the stop event without starting the background task
        loop._stop_event.set()
        with pytest.raises(LoopStoppedError):
            await loop.tick()

    async def test_tick_increments_cycle_counter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each tick() call increments cycle_counter by 1."""
        config = _make_config(monkeypatch)
        # No signal generator, no SDK — fastest tick
        loop, _ = _make_loop(config, signal_generator=None, sdk_client=None)
        assert loop.cycle_count == 0

        # Patch _record and _learn to avoid DB/memory imports
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        await loop.tick()
        assert loop.cycle_count == 1

        await loop.tick()
        assert loop.cycle_count == 2

    async def test_tick_returns_trading_cycle_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tick() always returns a TradingCycleResult."""
        config = _make_config(monkeypatch)
        loop, _ = _make_loop(config, signal_generator=None, sdk_client=None)
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        result = await loop.tick()

        assert isinstance(result, TradingCycleResult)
        assert result.cycle_number == 1
        assert isinstance(result.errors, list)
        assert isinstance(result.executions, list)

    async def test_tick_full_cycle_with_signal_and_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full cycle: signal generated, permission allowed, order placed."""
        config = _make_config(monkeypatch)

        # Mock SDK client that responds to place_market_order
        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={"total_value": "10000.00"})
        sdk.get_positions = AsyncMock(return_value=[])
        sdk.place_market_order = AsyncMock(
            return_value={
                "order_id": str(uuid4()),
                "fill_price": "67500.00",
                "fee": "0.068",
            }
        )

        # Mock signal generator that returns one BUY signal
        sig_gen = MagicMock()
        buy_signal = _make_signal("BTCUSDT", "buy", confidence=0.80)
        sig_gen.generate = AsyncMock(return_value=[buy_signal])

        loop, enforcer = _make_loop(config, signal_generator=sig_gen, sdk_client=sdk)
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        result = await loop.tick()

        assert result.signals_generated == 1
        assert result.decisions_made == 1
        assert result.trades_executed == 1
        assert len(result.executions) == 1
        assert result.executions[0].success is True

    async def test_tick_permission_denial_prevents_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When permission is denied, no order is placed and no error is recorded."""
        config = _make_config(monkeypatch)

        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={})
        sdk.get_positions = AsyncMock(return_value=[])

        sig_gen = MagicMock()
        buy_signal = _make_signal("BTCUSDT", "buy", confidence=0.80)
        sig_gen.generate = AsyncMock(return_value=[buy_signal])

        loop, enforcer = _make_loop(config, signal_generator=sig_gen, sdk_client=sdk)
        # Override the enforcer to deny all actions
        enforcer.check_action = AsyncMock(
            return_value=_denied_enforcement(reason="Daily limit reached")
        )
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        result = await loop.tick()

        assert result.trades_executed == 0
        assert len(result.executions) == 0
        # Permission denial is not counted as an error
        assert len(result.errors) == 0
        # SDK place_market_order must NOT have been called
        sdk.place_market_order.assert_not_called()

    async def test_tick_low_confidence_signal_filtered_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Signals below trading_min_confidence threshold are not executed."""
        config = _make_config(monkeypatch)
        # Default trading_min_confidence is 0.6
        assert config.trading_min_confidence == 0.6

        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={})
        sdk.get_positions = AsyncMock(return_value=[])

        sig_gen = MagicMock()
        # Confidence 0.40 — well below threshold
        low_conf_signal = _make_signal("BTCUSDT", "buy", confidence=0.40)
        sig_gen.generate = AsyncMock(return_value=[low_conf_signal])

        loop, enforcer = _make_loop(config, signal_generator=sig_gen, sdk_client=sdk)
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        result = await loop.tick()

        assert result.signals_generated == 1
        assert result.decisions_made == 0  # filtered out
        assert result.trades_executed == 0
        enforcer.check_action.assert_not_called()

    async def test_tick_hold_signal_not_executed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HOLD signals are never passed to the permission check or executed."""
        config = _make_config(monkeypatch)

        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={})
        sdk.get_positions = AsyncMock(return_value=[])

        sig_gen = MagicMock()
        hold_signal = _make_signal("BTCUSDT", "hold", confidence=0.90)
        sig_gen.generate = AsyncMock(return_value=[hold_signal])

        loop, enforcer = _make_loop(config, signal_generator=sig_gen, sdk_client=sdk)
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        result = await loop.tick()

        assert result.decisions_made == 0
        assert result.trades_executed == 0
        enforcer.check_action.assert_not_called()

    async def test_tick_signal_generator_failure_non_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Signal generator exception is caught; error is recorded and cycle continues."""
        config = _make_config(monkeypatch)

        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={})
        sdk.get_positions = AsyncMock(return_value=[])

        sig_gen = MagicMock()
        sig_gen.generate = AsyncMock(side_effect=RuntimeError("Ensemble failed"))

        loop, _ = _make_loop(config, signal_generator=sig_gen, sdk_client=sdk)
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        result = await loop.tick()

        # Cycle completes; error is recorded
        assert isinstance(result, TradingCycleResult)
        assert any("Signal generation failed" in e for e in result.errors)
        assert result.trades_executed == 0

    async def test_tick_record_step_failure_non_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_record() exception is caught; error is recorded and result is still returned."""
        config = _make_config(monkeypatch)

        loop, _ = _make_loop(config, signal_generator=None, sdk_client=None)
        loop._record = AsyncMock(side_effect=RuntimeError("DB unavailable"))
        loop._learn = AsyncMock()

        result = await loop.tick()

        assert isinstance(result, TradingCycleResult)
        assert any("Record step failed" in e for e in result.errors)

    async def test_tick_learn_step_failure_non_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_learn() exception never propagates; cycle result is returned normally."""
        config = _make_config(monkeypatch)

        loop, _ = _make_loop(config, signal_generator=None, sdk_client=None)
        loop._record = AsyncMock()
        loop._learn = AsyncMock(side_effect=RuntimeError("Memory store error"))

        result = await loop.tick()

        # No errors recorded for learn failures (warnings only)
        assert isinstance(result, TradingCycleResult)
        # The cycle must complete despite the learn failure
        assert result.cycle_number == 1

    async def test_tick_no_sdk_client_skips_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When sdk_client is None, orders are not placed even for approved signals."""
        config = _make_config(monkeypatch)

        sig_gen = MagicMock()
        buy_signal = _make_signal("BTCUSDT", "buy", confidence=0.80)
        sig_gen.generate = AsyncMock(return_value=[buy_signal])

        # No SDK client
        loop, _ = _make_loop(config, signal_generator=sig_gen, sdk_client=None)
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        result = await loop.tick()

        # Execution result is None (no SDK), so trades_executed = 0
        assert result.trades_executed == 0

    async def test_tick_sdk_order_failure_recorded_as_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SDK place_market_order exception is caught and recorded as an error."""
        config = _make_config(monkeypatch)

        sdk = AsyncMock()
        sdk.get_performance = AsyncMock(return_value={"total_value": "10000.00"})
        sdk.get_positions = AsyncMock(return_value=[])
        sdk.place_market_order = AsyncMock(side_effect=ConnectionError("Platform unreachable"))

        sig_gen = MagicMock()
        buy_signal = _make_signal("BTCUSDT", "buy", confidence=0.80)
        sig_gen.generate = AsyncMock(return_value=[buy_signal])

        loop, _ = _make_loop(config, signal_generator=sig_gen, sdk_client=sdk)
        loop._record = AsyncMock()
        loop._learn = AsyncMock()

        result = await loop.tick()

        assert result.trades_executed == 0
        assert any("Order placement failed" in e for e in result.errors)


# ---------------------------------------------------------------------------
# TestTradingLoopLifecycle
# ---------------------------------------------------------------------------


class TestTradingLoopLifecycle:
    """Tests for TradingLoop start / stop / is_running."""

    def test_initial_state_not_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A freshly created loop is not running."""
        config = _make_config(monkeypatch)
        loop, _ = _make_loop(config)
        assert loop.is_running is False
        assert loop.cycle_count == 0

    async def test_stop_before_start_is_no_op(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stop() on a non-running loop does nothing and does not raise."""
        config = _make_config(monkeypatch)
        loop, _ = _make_loop(config)
        await loop.stop()  # must not raise
        assert loop.is_running is False

    async def test_start_sets_is_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After start(), is_running is True."""
        config = _make_config(monkeypatch)
        loop, _ = _make_loop(config, signal_generator=MagicMock())
        loop._ensure_signal_generator = AsyncMock()
        # Patch _run_forever to avoid actually running the loop
        loop._run_forever = AsyncMock()  # type: ignore[method-assign]

        await loop.start()
        assert loop.is_running is True
        # Clean up
        loop._stop_event.set()
        loop._is_running = False

    async def test_start_twice_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling start() on an already-running loop is a no-op."""
        config = _make_config(monkeypatch)
        loop, _ = _make_loop(config, signal_generator=MagicMock())
        loop._ensure_signal_generator = AsyncMock()
        loop._run_forever = AsyncMock()  # type: ignore[method-assign]

        await loop.start()
        task_before = loop._loop_task
        await loop.start()  # second call
        assert loop._loop_task is task_before  # same task object
        # Clean up
        loop._stop_event.set()
        loop._is_running = False


# ---------------------------------------------------------------------------
# TestEstimateTradeValue
# ---------------------------------------------------------------------------


class TestEstimateTradeValue:
    """Tests for TradingLoop._estimate_trade_value (static method)."""

    def _make_signal_for_estimate(
        self, symbol: str = "BTCUSDT", action: str = "buy", confidence: float = 0.75
    ) -> TradingSignal:
        return TradingSignal(
            symbol=symbol,
            action=action,
            confidence=confidence,
            agreement_rate=0.67,
            generated_at=datetime.now(UTC),
        )

    def test_uses_total_value_from_portfolio(self) -> None:
        """Returns 5 % of total_value when portfolio has total_value."""
        sig = self._make_signal_for_estimate()
        portfolio = {"total_value": "10000.00"}
        value = TradingLoop._estimate_trade_value(sig, portfolio)
        # 5 % of 10000 = 500
        assert Decimal(value) == Decimal("500.00")

    def test_uses_equity_when_total_value_absent(self) -> None:
        """Falls back to the equity key when total_value is missing."""
        sig = self._make_signal_for_estimate()
        portfolio = {"equity": "8000.00"}
        value = TradingLoop._estimate_trade_value(sig, portfolio)
        # 5 % of 8000 = 400
        assert Decimal(value) == Decimal("400.00")

    def test_falls_back_to_100_when_portfolio_empty(self) -> None:
        """Returns '100.00' when portfolio state is unavailable."""
        sig = self._make_signal_for_estimate()
        value = TradingLoop._estimate_trade_value(sig, {})
        assert value == "100.00"

    def test_falls_back_to_100_on_invalid_equity(self) -> None:
        """Returns '100.00' when equity value cannot be parsed."""
        sig = self._make_signal_for_estimate()
        portfolio = {"total_value": "not-a-number"}
        value = TradingLoop._estimate_trade_value(sig, portfolio)
        assert value == "100.00"
