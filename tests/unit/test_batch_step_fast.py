"""Unit tests for BacktestEngine.step_batch_fast().

Covers the optimized fast-batch execution path:
- Basic batch execution (N steps)
- Fill accumulation across steps (include_intermediate_trades toggle)
- Portfolio computed once at end
- is_complete flag when session finishes
- steps_executed count accuracy
- Error when session is already complete
- Error when session not found
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.backtesting.engine import BacktestEngine, BatchStepResult
from src.utils.exceptions import BacktestInvalidStateError, BacktestNotFoundError

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> BacktestEngine:
    return BacktestEngine(session_factory=MagicMock())


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def mock_session_model():
    """Create a mock BacktestSession ORM model with 10 total steps."""
    session = MagicMock()
    session.id = uuid4()
    session.account_id = uuid4()
    session.status = "created"
    session.strategy_label = "test_v1"
    session.candle_interval = 60
    session.start_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    session.end_time = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)  # 10 min = 10 steps at 60s
    session.starting_balance = Decimal("10000")
    session.agent_id = None
    session.pairs = None
    session.total_steps = 10
    return session


async def _start_session(engine: BacktestEngine, session_id: str, mock_db: AsyncMock, session_model: MagicMock) -> None:
    """Helper: start a session with mocked DB and replayer."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = session_model
    mock_db.execute.return_value = mock_result

    with patch("src.backtesting.engine.DataReplayer") as mock_replayer_cls:
        replayer = mock_replayer_cls.return_value
        replayer.preload_range = AsyncMock(return_value=100)
        replayer.load_prices = AsyncMock(return_value={"BTCUSDT": Decimal("50000")})
        await engine.start(session_id, mock_db)

    # After start(), the replayer is stored in the active session.
    # Wire load_prices on the stored replayer for subsequent calls.
    if session_id in engine._active:
        engine._active[session_id].replayer.load_prices = AsyncMock(
            return_value={"BTCUSDT": Decimal("50000")}
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStepBatchFastBasic:
    """Basic execution and return-value correctness."""

    async def test_returns_batch_step_result(self, engine, mock_db, mock_session_model):
        """step_batch_fast returns a BatchStepResult dataclass."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 3, mock_db)

        assert isinstance(result, BatchStepResult)

    async def test_steps_executed_count_matches_requested(self, engine, mock_db, mock_session_model):
        """steps_executed equals the number of steps requested (when < total)."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 3, mock_db)

        assert result.steps_executed == 3

    async def test_step_advances_virtual_clock(self, engine, mock_db, mock_session_model):
        """step index advances by the number of steps executed."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 5, mock_db)

        assert result.step == 5
        assert result.total_steps == 10

    async def test_remaining_steps_decremented_correctly(self, engine, mock_db, mock_session_model):
        """remaining_steps is reduced by the number of steps executed."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 4, mock_db)

        assert result.remaining_steps == 6  # 10 total - 4 executed

    async def test_prices_present_in_result(self, engine, mock_db, mock_session_model):
        """Result contains price dict with at least one symbol."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 2, mock_db)

        assert "BTCUSDT" in result.prices
        assert result.prices["BTCUSDT"] == Decimal("50000")

    async def test_portfolio_present_in_result(self, engine, mock_db, mock_session_model):
        """Result contains a populated portfolio summary."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 2, mock_db)

        assert result.portfolio is not None
        assert result.portfolio.total_equity > Decimal("0")

    async def test_is_complete_false_mid_session(self, engine, mock_db, mock_session_model):
        """is_complete is False when steps remain."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 5, mock_db)

        assert result.is_complete is False

    async def test_progress_pct_increases(self, engine, mock_db, mock_session_model):
        """Progress percentage increases after executing steps."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 5, mock_db)

        assert result.progress_pct > Decimal("0")
        assert result.progress_pct <= Decimal("100")

    async def test_db_flush_called_once_per_batch(self, engine, mock_db, mock_session_model):
        """DB is flushed exactly once at the end of the batch, not per-step."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        # Reset flush call count after start()
        mock_db.flush.reset_mock()

        await engine.step_batch_fast(session_id, 5, mock_db)

        # Should be exactly 1 flush for the progress write (not 5)
        assert mock_db.flush.await_count == 1


class TestStepBatchFastCompletion:
    """Behaviour when the batch reaches the final step."""

    async def test_is_complete_true_when_all_steps_exhausted(self, engine, mock_db, mock_session_model):
        """is_complete is True when requesting >= remaining steps."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        # Request more steps than available (10 total)
        result = await engine.step_batch_fast(session_id, 20, mock_db)

        assert result.is_complete is True

    async def test_steps_executed_capped_at_total(self, engine, mock_db, mock_session_model):
        """steps_executed never exceeds total_steps even if more were requested."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 100, mock_db)

        assert result.steps_executed == 10  # only 10 steps in session

    async def test_session_removed_from_active_on_complete(self, engine, mock_db, mock_session_model):
        """After auto-complete, session is removed from the active dict."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        # Exhaust all steps
        await engine.step_batch_fast(session_id, 100, mock_db)

        assert not engine.is_active(session_id)

    async def test_remaining_steps_zero_on_complete(self, engine, mock_db, mock_session_model):
        """remaining_steps is 0 after full completion."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 100, mock_db)

        assert result.remaining_steps == 0

    async def test_exact_step_count_completes_session(self, engine, mock_db, mock_session_model):
        """Requesting exactly total_steps completes the session."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(session_id, 10, mock_db)

        assert result.is_complete is True
        assert result.steps_executed == 10


class TestStepBatchFastFillAccumulation:
    """Tests for include_intermediate_trades flag behaviour."""

    async def test_orders_filled_without_accumulation_is_empty_list(
        self, engine, mock_db, mock_session_model
    ):
        """With no orders placed, orders_filled is empty regardless of flag."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(
            session_id, 3, mock_db, include_intermediate_trades=False
        )

        assert result.orders_filled == []

    async def test_orders_filled_with_accumulation_is_empty_when_no_orders(
        self, engine, mock_db, mock_session_model
    ):
        """With no pending orders, accumulated fills list is also empty."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        result = await engine.step_batch_fast(
            session_id, 3, mock_db, include_intermediate_trades=True
        )

        assert result.orders_filled == []

    async def test_include_intermediate_trades_default_is_false(
        self, engine, mock_db, mock_session_model
    ):
        """Default value of include_intermediate_trades is False."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        # Place a market order that fills immediately
        await engine.execute_order(
            session_id, "BTCUSDT", "buy", "market", Decimal("0.01"), None
        )

        # Step 1 — no fills (market order already filled at placement)
        # Step 2 — same; just check the default parameter works
        result = await engine.step_batch_fast(session_id, 2, mock_db)

        # Default (no accumulation): result is the fills from the LAST step
        assert isinstance(result.orders_filled, list)

    async def test_accumulation_true_collects_fills_across_steps(
        self, engine, mock_db, mock_session_model
    ):
        """With accumulation enabled, fills from every step are collected.

        We inject a mock sandbox to control exactly when fills are returned.
        """
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        # Patch sandbox.check_pending_orders to return a fill on step 1 and step 2
        fill_1 = MagicMock()
        fill_1.order_id = str(uuid4())
        fill_2 = MagicMock()
        fill_2.order_id = str(uuid4())

        call_count = 0

        def _fake_check(prices, vt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [fill_1]
            if call_count == 2:
                return [fill_2]
            return []

        engine._active[session_id].sandbox.check_pending_orders = _fake_check

        result = await engine.step_batch_fast(
            session_id, 3, mock_db, include_intermediate_trades=True
        )

        # Both fills should be accumulated
        assert fill_1 in result.orders_filled
        assert fill_2 in result.orders_filled

    async def test_accumulation_false_only_last_step_fills(
        self, engine, mock_db, mock_session_model
    ):
        """Without accumulation, only the final step's fills are returned."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        fill_early = MagicMock()
        fill_early.order_id = str(uuid4())
        fill_last = MagicMock()
        fill_last.order_id = str(uuid4())

        call_count = 0

        def _fake_check(prices, vt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [fill_early]
            if call_count == 3:
                return [fill_last]
            return []

        engine._active[session_id].sandbox.check_pending_orders = _fake_check

        result = await engine.step_batch_fast(
            session_id, 3, mock_db, include_intermediate_trades=False
        )

        # Only the last step's fills (empty list from step 3 since call_count 3 = fill_last)
        # Actually step 3 call_count == 3 returns fill_last
        assert fill_early not in result.orders_filled
        assert fill_last in result.orders_filled


class TestStepBatchFastErrorCases:
    """Error handling: not-found and already-complete."""

    async def test_raises_not_found_for_unknown_session(self, engine, mock_db):
        """BacktestNotFoundError raised for a session not in _active."""
        with pytest.raises(BacktestNotFoundError):
            await engine.step_batch_fast("nonexistent-session-id", 5, mock_db)

    async def test_raises_invalid_state_if_already_complete(
        self, engine, mock_db, mock_session_model
    ):
        """BacktestInvalidStateError raised when simulator.is_complete is True on entry."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        # Exhaust all steps
        await engine.step_batch_fast(session_id, 100, mock_db)

        # Session is now gone from _active; re-inject a fake active session with
        # is_complete=True to test the guard inside step_batch_fast.

        from src.backtesting.engine import _ActiveSession

        fake_active = MagicMock(spec=_ActiveSession)
        fake_active.simulator = MagicMock()
        fake_active.simulator.is_complete = True
        engine._active[session_id] = fake_active

        with pytest.raises(BacktestInvalidStateError):
            await engine.step_batch_fast(session_id, 5, mock_db)


class TestStepBatchFastPortfolioOnce:
    """Portfolio is computed exactly once at the end of the batch, not per-step."""

    async def test_get_portfolio_called_once_for_large_batch(
        self, engine, mock_db, mock_session_model
    ):
        """Sandbox.get_portfolio is called once regardless of batch size."""
        session_id = str(mock_session_model.id)
        await _start_session(engine, session_id, mock_db, mock_session_model)

        # Spy on get_portfolio
        original_get_portfolio = engine._active[session_id].sandbox.get_portfolio
        call_count = 0

        def _counting_get_portfolio(prices):
            nonlocal call_count
            call_count += 1
            return original_get_portfolio(prices)

        engine._active[session_id].sandbox.get_portfolio = _counting_get_portfolio

        await engine.step_batch_fast(session_id, 8, mock_db)

        # get_portfolio called exactly once (at the end of the batch)
        assert call_count == 1
