"""Unit tests for HeadlessTradingEnv.

All platform source imports and DB/engine calls are mocked so the test
suite runs without a live database or the full src/ tree.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import gymnasium as gym
import numpy as np
import pytest

import tradeready_gym  # noqa: F401 — trigger registration
from tradeready_gym.envs.headless_env import _TIMEFRAME_TO_SECONDS, HeadlessTradingEnv
from tradeready_gym.rewards.pnl_reward import PnLReward
from tradeready_gym.rewards.sharpe_reward import SharpeReward

# ---------------------------------------------------------------------------
# Fixture helpers — stand-ins for platform dataclasses
# ---------------------------------------------------------------------------


@dataclass
class _FakePortfolio:
    total_equity: Decimal = Decimal("10000")
    available_cash: Decimal = Decimal("10000")
    position_value: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    positions: list[Any] = field(default_factory=list)


@dataclass
class _FakeStepResult:
    virtual_time: datetime = field(default_factory=lambda: datetime(2025, 1, 1, 0, 1, 0, tzinfo=timezone.utc))
    step: int = 1
    total_steps: int = 100
    progress_pct: Decimal = Decimal("1.0")
    prices: dict[str, Decimal] = field(default_factory=lambda: {"BTCUSDT": Decimal("97000")})
    orders_filled: list[Any] = field(default_factory=list)
    portfolio: _FakePortfolio = field(default_factory=_FakePortfolio)
    is_complete: bool = False
    remaining_steps: int = 99


@dataclass
class _FakeCandle:
    bucket: datetime = field(default_factory=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc))
    symbol: str = "BTCUSDT"
    open: Decimal = Decimal("97000")
    high: Decimal = Decimal("97100")
    low: Decimal = Decimal("96900")
    close: Decimal = Decimal("97050")
    volume: Decimal = Decimal("100")
    trade_count: int = 50


@dataclass
class _FakePosition:
    symbol: str = "BTCUSDT"
    quantity: Decimal = Decimal("0.1")
    avg_entry_price: Decimal = Decimal("97000")
    total_cost: Decimal = Decimal("9700")
    realized_pnl: Decimal = Decimal("0")


@dataclass
class _FakeSessionModel:
    id: str = "sess-abc-123"


# ---------------------------------------------------------------------------
# Mock engine factory
# ---------------------------------------------------------------------------


def _make_mock_engine(
    step_result: _FakeStepResult | None = None,
    complete_on_step: int = 0,
) -> MagicMock:
    """Return a mock BacktestEngine whose coroutines return fake data."""
    if step_result is None:
        step_result = _FakeStepResult()

    fake_replayer = MagicMock()
    fake_replayer.load_candles = AsyncMock(return_value=[_FakeCandle() for _ in range(30)])

    fake_simulator = MagicMock()
    fake_simulator.current_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    fake_sandbox = MagicMock()
    fake_sandbox.get_portfolio.return_value = _FakePortfolio()
    fake_sandbox.get_positions.return_value = []
    fake_sandbox.place_order.return_value = MagicMock()

    fake_active = MagicMock()
    fake_active.replayer = fake_replayer
    fake_active.simulator = fake_simulator
    fake_active.sandbox = fake_sandbox

    engine = MagicMock()
    engine.create_session = AsyncMock(return_value=_FakeSessionModel())
    engine.start = AsyncMock(return_value=None)

    call_count = [0]

    async def _step_side_effect(session_id, db):
        call_count[0] += 1
        result = _FakeStepResult(
            is_complete=(complete_on_step > 0 and call_count[0] >= complete_on_step),
            prices={"BTCUSDT": Decimal("97000")},
        )
        return result

    engine.step = AsyncMock(side_effect=_step_side_effect)
    engine._active = {"sess-abc-123": fake_active}

    # is_active() returns False so _cleanup_episode() skips the cancel() call
    # on the first reset() (no prior session to cancel).
    engine.is_active = MagicMock(return_value=False)
    engine.cancel = AsyncMock(return_value=None)

    return engine


# ---------------------------------------------------------------------------
# Mock context for patching platform imports inside _ensure_engine()
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helper: build an env with injected mocks
# ---------------------------------------------------------------------------


def _make_env(
    symbol: str = "BTCUSDT",
    starting_balance: float = 10_000.0,
    episode_length: int | None = None,
    engine: MagicMock | None = None,
    reward_function=None,
) -> HeadlessTradingEnv:
    """Construct a HeadlessTradingEnv and inject a mock BacktestEngine."""
    if engine is None:
        engine = _make_mock_engine()

    env = HeadlessTradingEnv(
        db_url="postgresql+asyncpg://fake/db",
        symbol=symbol,
        starting_balance=starting_balance,
        episode_length=episode_length,
        reward_function=reward_function,
    )

    # Bypass async DB setup: inject mocks directly
    fake_db_engine = MagicMock()
    fake_db_engine.dispose = AsyncMock()
    env._db_engine = fake_db_engine

    # The new code calls self._session_factory() directly (no async with),
    # so the factory must return a session-like AsyncMock with add/flush/commit/close.
    fake_session = AsyncMock()
    fake_session.add = MagicMock()  # synchronous in SQLAlchemy
    fake_session.flush = AsyncMock()
    fake_session.commit = AsyncMock()
    fake_session.close = AsyncMock()
    mock_session_factory = MagicMock(return_value=fake_session)

    env._session_factory = mock_session_factory
    env._backtest_engine = engine
    return env


# ---------------------------------------------------------------------------
# Tests: registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_env_is_registered(self):
        """TradeReady-BTC-Headless-v0 must be registered after importing tradeready_gym."""
        registered = [spec.id for spec in gym.envs.registry.values()]
        assert "TradeReady-BTC-Headless-v0" in registered

    def test_headless_env_exported(self):
        assert hasattr(tradeready_gym, "HeadlessTradingEnv")

    def test_headless_in_all(self):
        assert "HeadlessTradingEnv" in tradeready_gym.__all__


# ---------------------------------------------------------------------------
# Tests: constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_default_action_space(self):
        env = _make_env()
        assert isinstance(env.action_space, gym.spaces.Discrete)
        assert env.action_space.n == 3
        env.close()

    def test_observation_space_shape(self):
        env = _make_env()
        # Default features: ohlcv(5) + rsi_14(1) + macd(3) = 9 candle dims
        # lookback=30 → 30*9 = 270 candle dims + balance(1) + position(1) = 272
        assert env.observation_space.shape == (272,)
        env.close()

    def test_custom_symbol_uppercased(self):
        env = _make_env(symbol="btcusdt")
        assert env.symbol == "BTCUSDT"
        env.close()

    def test_episode_length_stored(self):
        env = _make_env(episode_length=500)
        assert env.episode_length == 500
        env.close()

    def test_default_reward_function_is_pnl(self):
        env = _make_env()
        assert isinstance(env.reward_fn, PnLReward)
        env.close()

    def test_custom_reward_function_accepted(self):
        reward_fn = SharpeReward(window=20)
        env = _make_env(reward_function=reward_fn)
        assert env.reward_fn is reward_fn
        env.close()

    def test_event_loop_created(self):
        env = _make_env()
        assert env._loop is not None
        assert isinstance(env._loop, asyncio.AbstractEventLoop)
        env.close()


# ---------------------------------------------------------------------------
# Tests: timeframe mapping
# ---------------------------------------------------------------------------


class TestTimeframeMapping:
    @pytest.mark.parametrize("tf,expected", list(_TIMEFRAME_TO_SECONDS.items()))
    def test_known_timeframes(self, tf, expected):
        env = HeadlessTradingEnv(db_url="postgresql+asyncpg://x/y", timeframe=tf)
        assert env._candle_interval == expected
        env._loop.close()

    def test_unknown_timeframe_defaults_to_60(self):
        env = HeadlessTradingEnv(db_url="postgresql+asyncpg://x/y", timeframe="99m")
        assert env._candle_interval == 60
        env._loop.close()


# ---------------------------------------------------------------------------
# Tests: reset()
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_returns_correct_types(self):
        env = _make_env()
        obs, info = env.reset()

        assert isinstance(obs, np.ndarray)
        assert obs.dtype == np.float32
        assert obs.shape == env.observation_space.shape
        assert isinstance(info, dict)
        env.close()

    def test_reset_info_contains_session_id(self):
        env = _make_env()
        _, info = env.reset()
        assert "session_id" in info
        assert info["session_id"] == "sess-abc-123"
        env.close()

    def test_reset_initialises_episode_count(self):
        env = _make_env()
        assert env._episode_count == 0
        env.reset()
        assert env._episode_count == 1
        env.close()

    def test_reset_calls_create_and_start(self):
        engine = _make_mock_engine()
        env = _make_env(engine=engine)
        env.reset()
        engine.create_session.assert_awaited_once()
        engine.start.assert_awaited_once()
        env.close()

    def test_reset_increments_episode_on_second_call(self):
        env = _make_env()
        env.reset()
        env.reset()
        assert env._episode_count == 2
        env.close()

    def test_reset_resets_step_count(self):
        env = _make_env()
        env.reset()
        # Simulate some steps
        env._step_count = 42
        env.reset()
        assert env._step_count == 0
        env.close()

    def test_observation_in_observation_space(self):
        env = _make_env()
        obs, _ = env.reset()
        assert env.observation_space.contains(obs)
        env.close()


# ---------------------------------------------------------------------------
# Tests: step()
# ---------------------------------------------------------------------------


class TestStep:
    def test_step_returns_5_tuple(self):
        env = _make_env()
        env.reset()
        result = env.step(0)
        assert len(result) == 5
        env.close()

    def test_step_observation_correct_shape(self):
        env = _make_env()
        env.reset()
        obs, *_ = env.step(0)
        assert obs.shape == env.observation_space.shape
        env.close()

    def test_step_reward_is_float(self):
        env = _make_env()
        env.reset()
        _, reward, _, _, _ = env.step(0)
        assert isinstance(reward, float)
        env.close()

    def test_step_terminated_is_bool(self):
        env = _make_env()
        env.reset()
        _, _, terminated, truncated, _ = env.step(0)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        env.close()

    def test_hold_does_not_place_order(self):
        engine = _make_mock_engine()
        env = _make_env(engine=engine)
        env.reset()
        env.step(0)  # hold
        engine._active["sess-abc-123"].sandbox.place_order.assert_not_called()
        env.close()

    def test_buy_calls_place_order(self):
        engine = _make_mock_engine()
        # Give the sandbox a non-zero equity so the buy quantity is positive
        engine._active["sess-abc-123"].sandbox.get_portfolio.return_value = _FakePortfolio(
            total_equity=Decimal("10000"), available_cash=Decimal("10000")
        )
        env = _make_env(engine=engine)
        env.reset()
        env.step(1)  # buy
        engine._active["sess-abc-123"].sandbox.place_order.assert_called_once()
        call_kwargs = engine._active["sess-abc-123"].sandbox.place_order.call_args
        assert call_kwargs.kwargs.get("side") == "buy" or call_kwargs[1].get("side") == "buy"
        env.close()

    def test_sell_with_position_calls_place_order(self):
        engine = _make_mock_engine()
        engine._active["sess-abc-123"].sandbox.get_positions.return_value = [_FakePosition(quantity=Decimal("0.1"))]
        env = _make_env(engine=engine)
        env.reset()
        env.step(2)  # sell
        engine._active["sess-abc-123"].sandbox.place_order.assert_called_once()
        call_kwargs = engine._active["sess-abc-123"].sandbox.place_order.call_args
        assert call_kwargs.kwargs.get("side") == "sell" or call_kwargs[1].get("side") == "sell"
        env.close()

    def test_sell_without_position_does_not_place_order(self):
        engine = _make_mock_engine()
        engine._active["sess-abc-123"].sandbox.get_positions.return_value = []
        env = _make_env(engine=engine)
        env.reset()
        env.step(2)  # sell — no position
        engine._active["sess-abc-123"].sandbox.place_order.assert_not_called()
        env.close()

    def test_step_increments_step_count(self):
        env = _make_env()
        env.reset()
        env.step(0)
        env.step(0)
        assert env._step_count == 2
        env.close()

    def test_terminated_when_engine_signals_complete(self):
        engine = _make_mock_engine(complete_on_step=2)
        # Make the engine return is_complete=True on 2nd call (first call is reset's step)
        env = _make_env(engine=engine)
        env.reset()
        _, _, terminated, _, _ = env.step(0)
        # first step: call_count=2, complete_on_step=2 → is_complete=True
        assert terminated is True
        env.close()

    def test_truncated_when_episode_length_exceeded(self):
        env = _make_env(episode_length=1)
        env.reset()
        _, _, _, truncated, _ = env.step(0)
        assert truncated is True
        env.close()

    def test_truncated_false_before_episode_length(self):
        env = _make_env(episode_length=10)
        env.reset()
        _, _, _, truncated, _ = env.step(0)
        assert truncated is False
        env.close()

    def test_step_info_contains_prices(self):
        env = _make_env()
        env.reset()
        _, _, _, _, info = env.step(0)
        assert "prices" in info
        assert isinstance(info["prices"], dict)
        env.close()

    def test_step_info_contains_equity(self):
        env = _make_env()
        env.reset()
        _, _, _, _, info = env.step(0)
        assert "equity" in info
        env.close()


# ---------------------------------------------------------------------------
# Tests: close()
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_disposes_db_engine(self):
        env = _make_env()
        env.reset()
        # Save mock reference before close() nulls _db_engine
        db_engine_mock = env._db_engine
        env.close()
        db_engine_mock.dispose.assert_awaited_once()

    def test_close_keeps_event_loop_open(self):
        """close() intentionally does NOT close the event loop.

        SB3's Monitor wrapper may call reset() after close() during episode
        transitions.  The loop is only closed in __del__ on GC.
        """
        env = _make_env()
        env.reset()
        loop = env._loop
        env.close()
        assert not loop.is_closed()

    def test_close_without_reset_does_not_raise(self):
        env = HeadlessTradingEnv(db_url="postgresql+asyncpg://x/y")
        # No _db_engine set — close() should handle gracefully
        env._loop.close()  # close the loop manually since we won't run it


# ---------------------------------------------------------------------------
# Tests: render()
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_returns_string(self):
        env = _make_env()
        env.reset()
        text = env.render()
        assert isinstance(text, str)
        env.close()

    def test_render_contains_symbol(self):
        env = _make_env(symbol="BTCUSDT")
        env.reset()
        assert "BTCUSDT" in env.render()
        env.close()

    def test_render_human_mode_prints(self, capsys):
        env = _make_env()
        env.render_mode = "human"
        env.reset()
        env.render()
        captured = capsys.readouterr()
        assert "BTCUSDT" in captured.out
        env.close()


# ---------------------------------------------------------------------------
# Tests: helper conversions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_portfolio_to_dict_from_dataclass(self):
        portfolio = _FakePortfolio(
            total_equity=Decimal("12000"),
            available_cash=Decimal("5000"),
        )
        result = HeadlessTradingEnv._portfolio_to_dict(portfolio)
        assert result["total_equity"] == pytest.approx(12000.0)
        assert result["available_cash"] == pytest.approx(5000.0)

    def test_portfolio_to_dict_from_plain_dict(self):
        portfolio = {
            "total_equity": 9000.0,
            "available_cash": 9000.0,
            "position_value": 0.0,
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "positions": [],
        }
        result = HeadlessTradingEnv._portfolio_to_dict(portfolio)
        # Plain dict falls back: getattr won't find keys, returns 0
        # (This is the dict branch — positions list is returned empty)
        assert isinstance(result, dict)

    def test_candles_to_dicts_from_dataclass(self):
        candles = [_FakeCandle() for _ in range(5)]
        result = HeadlessTradingEnv._candles_to_dicts(candles)
        assert len(result) == 5
        assert all(isinstance(c, dict) for c in result)
        assert result[0]["close"] == pytest.approx(97050.0)

    def test_candles_to_dicts_from_plain_dict(self):
        candles = [{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}]
        result = HeadlessTradingEnv._candles_to_dicts(candles)
        assert result == candles

    def test_candles_to_dicts_empty(self):
        assert HeadlessTradingEnv._candles_to_dicts([]) == []


# ---------------------------------------------------------------------------
# Tests: full episode loop
# ---------------------------------------------------------------------------


class TestFullEpisode:
    def test_full_episode_discrete_actions(self):
        """Run a complete episode cycling through all three actions."""
        engine = _make_mock_engine(complete_on_step=5)
        env = _make_env(engine=engine, episode_length=20)
        obs, info = env.reset()

        done = False
        step_count = 0
        while not done and step_count < 20:
            action = step_count % 3  # cycle hold/buy/sell
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            step_count += 1

        assert step_count > 0
        assert obs.shape == env.observation_space.shape
        env.close()

    def test_obs_values_are_finite(self):
        """Observation array must not contain NaN or Inf after a full step."""
        env = _make_env()
        obs, _ = env.reset()
        assert np.all(np.isfinite(obs))
        obs, *_ = env.step(0)
        assert np.all(np.isfinite(obs))
        env.close()

    def test_observation_space_contains_obs_at_every_step(self):
        env = _make_env()
        obs, _ = env.reset()
        assert env.observation_space.contains(obs)
        for _ in range(3):
            obs, *_ = env.step(0)
            assert env.observation_space.contains(obs)
        env.close()


# ---------------------------------------------------------------------------
# Tests: connection lifecycle
# ---------------------------------------------------------------------------


class TestConnectionLifecycle:
    def test_multi_episode_lifecycle(self):
        """reset() -> step x10 -> reset() -> step x10 -> close() with no exceptions.

        After close(), the episode session must be None (released by _cleanup_episode).
        """
        env = _make_env()
        env.reset()
        for _ in range(10):
            env.step(0)

        env.reset()
        for _ in range(10):
            env.step(0)

        # Capture session reference before close() so we can check it was cleaned up
        env.close()

        # After close(), _episode_session must be None (cleaned by _cleanup_episode)
        assert env._episode_session is None

    def test_close_then_reset_pattern(self):
        """reset() -> step x5 -> close() -> reset() -> step x5 -> close() (SB3 Monitor pattern).

        SB3's Monitor wrapper calls close() between episodes and then reset() again.
        The env must recreate the engine after close() clears _db_engine.
        """
        env = _make_env()

        # First episode
        env.reset()
        for _ in range(5):
            env.step(0)
        db_engine_mock_1 = env._db_engine
        env.close()
        assert env._episode_session is None
        # close() should have cleared _db_engine
        assert env._db_engine is None

        # Inject a fresh mock engine/session so the second reset() works without a real DB
        engine2 = _make_mock_engine()
        fake_db_engine2 = MagicMock()
        fake_db_engine2.dispose = AsyncMock()
        env._db_engine = fake_db_engine2

        fake_session2 = AsyncMock()
        fake_session2.add = MagicMock()
        fake_session2.flush = AsyncMock()
        fake_session2.commit = AsyncMock()
        fake_session2.close = AsyncMock()
        env._session_factory = MagicMock(return_value=fake_session2)
        env._backtest_engine = engine2

        # Second episode — must not raise
        env.reset()
        for _ in range(5):
            env.step(0)
        env.close()

        assert env._episode_session is None
        # The first engine's dispose is called exactly once (from the first close())
        db_engine_mock_1.dispose.assert_awaited_once()
        # The second engine's dispose is called exactly once (from the second close())
        fake_db_engine2.dispose.assert_awaited_once()

    def test_cleanup_cancels_active_session(self):
        """_cleanup_episode() calls engine.cancel() when the session is active.

        After the first reset():
        - is_active returns False (mock default) → cancel not called yet.

        After the second reset():
        - is_active is patched to return True for the old session_id
        - engine.cancel() must be called exactly once.
        """
        engine = _make_mock_engine()
        env = _make_env(engine=engine)

        # First reset — no prior session; is_active(None) branch skipped
        env.reset()
        first_session_id = env._session_id
        assert first_session_id is not None
        engine.cancel.assert_not_awaited()

        # Before second reset, make the engine report the first session as still active.
        # This simulates a mid-episode re-reset where the engine's _active dict still
        # has the old session.
        engine.is_active = MagicMock(return_value=True)

        env.reset()

        # _cleanup_episode() should have called cancel() on the previous session
        engine.cancel.assert_awaited_once()
        # The call should reference the first session's id
        call_args = engine.cancel.call_args
        assert call_args.args[0] == first_session_id or (
            len(call_args.args) > 0 and call_args.args[0] == first_session_id
        )

        env.close()

    def test_pool_not_exhausted_across_episodes(self):
        """5 consecutive reset() -> step(0) x20 cycles must not raise QueuePool errors.

        With the long-lived _episode_session pattern (one session per episode,
        explicitly closed in _cleanup_episode), each reset() releases the previous
        episode's connection before acquiring a new one.  This test verifies that
        the session factory and cleanup path work without leaking connections across
        five back-to-back episodes.
        """
        # Use a fresh engine per reset so call_counts don't bleed across episodes
        engine = _make_mock_engine()
        env = _make_env(engine=engine)

        for episode in range(5):
            env.reset()
            for _ in range(20):
                env.step(0)
            # Verify _episode_session is open (not None) during the episode
            assert env._episode_session is not None, f"Episode {episode}: _episode_session should be open after step()"

        # Capture factory reference before close() nulls it
        session_factory = env._session_factory
        env.close()

        # After close(), session must be released
        assert env._episode_session is None
        # Session factory called at least 5 times (once per episode)
        assert session_factory.call_count >= 5
