"""Unit tests for StrategyCircuitBreaker.

Tests cover all three trigger conditions:
  1. Consecutive losses  → 24h pause
  2. Weekly PnL drawdown → 48h pause
  3. Ensemble accuracy   → 25% size reduction

All Redis interactions are mocked via ``unittest.mock.AsyncMock`` and
``unittest.mock.MagicMock``.  No running Redis instance is required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from agent.strategies.ensemble.circuit_breaker import (
    ACCURACY_WINDOW,
    CONSECUTIVE_LOSS_PAUSE_SECONDS,
    LOW_ACCURACY_SIZE_MULTIPLIER,
    WEEKLY_DRAWDOWN_PAUSE_SECONDS,
    StrategyCircuitBreaker,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_redis() -> AsyncMock:
    """Return a fully-mocked async Redis client.

    ``pipeline()`` is a synchronous call that returns a pipeline object; only
    ``execute()`` on that pipeline is awaited.  The individual pipeline methods
    (``lpush``, ``ltrim``, ``expire``) are regular ``MagicMock`` instances that
    return the pipeline itself for chaining (though the implementation doesn't
    chain them — it just calls them sequentially).
    """
    redis = AsyncMock()
    # pipeline() is a synchronous call — use a plain MagicMock so it doesn't
    # return a coroutine.
    pipe = MagicMock()
    pipe.lpush = MagicMock(return_value=pipe)
    pipe.ltrim = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, True, True])
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


def _make_cb(redis: AsyncMock, **kwargs: object) -> StrategyCircuitBreaker:
    """Construct a StrategyCircuitBreaker with the given Redis mock."""
    return StrategyCircuitBreaker(redis_client=redis, **kwargs)  # type: ignore[arg-type]


STRATEGY = "rl"
AGENT_ID = "agent-001"


# ── Key helper tests ───────────────────────────────────────────────────────────


class TestKeyHelpers:
    def test_pause_key_format(self) -> None:
        key = StrategyCircuitBreaker._pause_key("rl", "a1")
        assert key == "strategy:circuit:rl:a1"

    def test_losses_key_format(self) -> None:
        key = StrategyCircuitBreaker._losses_key("evolved", "b2")
        assert key == "strategy:losses:evolved:b2"

    def test_weekly_pnl_key_format(self) -> None:
        key = StrategyCircuitBreaker._weekly_pnl_key("regime", "c3")
        assert key == "strategy:weekly_pnl:regime:c3"

    def test_accuracy_key_format(self) -> None:
        key = StrategyCircuitBreaker._accuracy_key("d4")
        assert key == "strategy:accuracy:d4"


# ── is_paused ─────────────────────────────────────────────────────────────────


class TestIsPaused:
    async def test_returns_false_when_key_absent(self) -> None:
        redis = _make_redis()
        redis.exists.return_value = 0
        cb = _make_cb(redis)
        assert await cb.is_paused(STRATEGY, AGENT_ID) is False

    async def test_returns_true_when_key_present(self) -> None:
        redis = _make_redis()
        redis.exists.return_value = 1
        cb = _make_cb(redis)
        assert await cb.is_paused(STRATEGY, AGENT_ID) is True

    async def test_fails_open_on_redis_error(self) -> None:
        redis = _make_redis()
        redis.exists.side_effect = Exception("connection refused")
        cb = _make_cb(redis)
        # Must return False (allow trading) even on error.
        assert await cb.is_paused(STRATEGY, AGENT_ID) is False


# ── pause / resume ────────────────────────────────────────────────────────────


class TestPauseResume:
    async def test_pause_sets_key_with_ttl(self) -> None:
        redis = _make_redis()
        cb = _make_cb(redis)
        await cb.pause(STRATEGY, AGENT_ID, pause_seconds=3600, reason="test")
        redis.set.assert_awaited_once()
        call_args = redis.set.call_args
        assert call_args.args[0] == StrategyCircuitBreaker._pause_key(STRATEGY, AGENT_ID)
        assert call_args.kwargs["ex"] == 3600
        payload = json.loads(call_args.args[1])
        assert payload["reason"] == "test"
        assert payload["pause_seconds"] == 3600

    async def test_pause_swallows_redis_error(self) -> None:
        redis = _make_redis()
        redis.set.side_effect = Exception("connection refused")
        cb = _make_cb(redis)
        # Must not raise.
        await cb.pause(STRATEGY, AGENT_ID, pause_seconds=3600, reason="test")

    async def test_resume_deletes_key(self) -> None:
        redis = _make_redis()
        cb = _make_cb(redis)
        await cb.resume(STRATEGY, AGENT_ID)
        redis.delete.assert_awaited_once_with(
            StrategyCircuitBreaker._pause_key(STRATEGY, AGENT_ID)
        )

    async def test_resume_swallows_redis_error(self) -> None:
        redis = _make_redis()
        redis.delete.side_effect = Exception("connection refused")
        cb = _make_cb(redis)
        await cb.resume(STRATEGY, AGENT_ID)  # must not raise


# ── get_pause_info ────────────────────────────────────────────────────────────


class TestGetPauseInfo:
    async def test_returns_none_when_not_paused(self) -> None:
        redis = _make_redis()
        redis.get.return_value = None
        cb = _make_cb(redis)
        result = await cb.get_pause_info(STRATEGY, AGENT_ID)
        assert result is None

    async def test_returns_dict_when_paused(self) -> None:
        redis = _make_redis()
        payload = {"reason": "consecutive_losses:3", "paused_at": 1000.0, "pause_seconds": 86400}
        redis.get.return_value = json.dumps(payload)
        cb = _make_cb(redis)
        result = await cb.get_pause_info(STRATEGY, AGENT_ID)
        assert result == payload

    async def test_returns_none_on_redis_error(self) -> None:
        redis = _make_redis()
        redis.get.side_effect = Exception("timeout")
        cb = _make_cb(redis)
        assert await cb.get_pause_info(STRATEGY, AGENT_ID) is None


# ── Trigger 1: Consecutive losses ─────────────────────────────────────────────


class TestConsecutiveLossTrigger:
    """Trigger: 3 consecutive losses → 24h pause."""

    async def test_record_loss_pushes_to_list(self) -> None:
        redis = _make_redis()
        # Return fewer than limit losses so no pause is triggered.
        redis.lrange.return_value = [b"loss", b"loss"]  # only 2
        cb = _make_cb(redis)
        await cb.record_loss(STRATEGY, AGENT_ID)
        pipe = redis.pipeline.return_value
        pipe.lpush.assert_called_once_with(
            StrategyCircuitBreaker._losses_key(STRATEGY, AGENT_ID), "loss"
        )

    async def test_three_consecutive_losses_trigger_pause(self) -> None:
        redis = _make_redis()
        # Simulate 3 losses already in the list after push.
        redis.lrange.return_value = [b"loss", b"loss", b"loss"]
        redis.exists.return_value = 0  # Not already paused.
        cb = _make_cb(redis)

        await cb.record_loss(STRATEGY, AGENT_ID)

        # pause() must have been called with 24h TTL.
        redis.set.assert_awaited_once()
        call_args = redis.set.call_args
        assert call_args.kwargs["ex"] == CONSECUTIVE_LOSS_PAUSE_SECONDS
        payload = json.loads(call_args.args[1])
        assert "consecutive_losses" in payload["reason"]

    async def test_two_losses_do_not_trigger_pause(self) -> None:
        redis = _make_redis()
        redis.lrange.return_value = [b"loss", b"loss"]  # only 2
        cb = _make_cb(redis)
        await cb.record_loss(STRATEGY, AGENT_ID)
        redis.set.assert_not_awaited()

    async def test_win_breaks_consecutive_streak(self) -> None:
        redis = _make_redis()
        # After recording a win the list has [win, loss, loss] — not all losses.
        redis.lrange.return_value = [b"win", b"loss", b"loss"]
        cb = _make_cb(redis)
        await cb.record_win(STRATEGY, AGENT_ID)
        redis.set.assert_not_awaited()

    async def test_custom_consecutive_limit(self) -> None:
        redis = _make_redis()
        redis.lrange.return_value = [b"loss", b"loss"]  # exactly 2
        cb = _make_cb(redis, consecutive_loss_limit=2)
        await cb.record_loss(STRATEGY, AGENT_ID)
        redis.set.assert_awaited_once()  # should trigger with limit=2

    async def test_record_outcome_swallows_redis_error(self) -> None:
        redis = _make_redis()
        redis.pipeline.return_value.execute.side_effect = Exception("redis error")
        cb = _make_cb(redis)
        await cb.record_loss(STRATEGY, AGENT_ID)  # must not raise

    async def test_consecutive_loss_count_all_losses(self) -> None:
        redis = _make_redis()
        redis.lrange.return_value = [b"loss", b"loss", b"loss"]
        cb = _make_cb(redis)
        count = await cb.consecutive_loss_count(STRATEGY, AGENT_ID)
        assert count == 3

    async def test_consecutive_loss_count_streak_broken(self) -> None:
        redis = _make_redis()
        redis.lrange.return_value = [b"loss", b"win", b"loss"]
        cb = _make_cb(redis)
        count = await cb.consecutive_loss_count(STRATEGY, AGENT_ID)
        assert count == 1  # streak of 1 before the win

    async def test_consecutive_loss_count_returns_zero_on_error(self) -> None:
        redis = _make_redis()
        redis.lrange.side_effect = Exception("timeout")
        cb = _make_cb(redis)
        count = await cb.consecutive_loss_count(STRATEGY, AGENT_ID)
        assert count == 0


# ── Trigger 2: Weekly drawdown ────────────────────────────────────────────────


class TestWeeklyDrawdownTrigger:
    """Trigger: cumulative weekly PnL < -5% → 48h pause."""

    async def test_record_pnl_contribution_accumulates(self) -> None:
        redis = _make_redis()
        redis.incrbyfloat.return_value = -0.03  # 3% drawdown — below threshold
        redis.exists.return_value = 0
        cb = _make_cb(redis)
        await cb.record_pnl_contribution(STRATEGY, AGENT_ID, pnl_pct=-0.03)
        redis.incrbyfloat.assert_awaited_once_with(
            StrategyCircuitBreaker._weekly_pnl_key(STRATEGY, AGENT_ID), -0.03
        )
        # Below threshold — no pause.
        redis.set.assert_not_awaited()

    async def test_exceeding_drawdown_threshold_triggers_pause(self) -> None:
        redis = _make_redis()
        # Cumulative drawdown of 6% — exceeds 5% threshold.
        redis.incrbyfloat.return_value = -0.06
        redis.exists.return_value = 0  # not already paused
        cb = _make_cb(redis)

        await cb.record_pnl_contribution(STRATEGY, AGENT_ID, pnl_pct=-0.06)

        redis.set.assert_awaited_once()
        call_args = redis.set.call_args
        assert call_args.kwargs["ex"] == WEEKLY_DRAWDOWN_PAUSE_SECONDS
        payload = json.loads(call_args.args[1])
        assert "weekly_drawdown" in payload["reason"]

    async def test_positive_pnl_does_not_trigger_pause(self) -> None:
        redis = _make_redis()
        redis.incrbyfloat.return_value = 0.10  # 10% gain
        cb = _make_cb(redis)
        await cb.record_pnl_contribution(STRATEGY, AGENT_ID, pnl_pct=0.10)
        redis.set.assert_not_awaited()

    async def test_already_paused_strategy_not_paused_again(self) -> None:
        redis = _make_redis()
        redis.incrbyfloat.return_value = -0.08
        redis.exists.return_value = 1  # already paused
        cb = _make_cb(redis)
        await cb.record_pnl_contribution(STRATEGY, AGENT_ID, pnl_pct=-0.08)
        # set() (which triggers a new pause) should not be called again.
        redis.set.assert_not_awaited()

    async def test_custom_drawdown_threshold(self) -> None:
        redis = _make_redis()
        redis.incrbyfloat.return_value = -0.03  # 3% drawdown
        redis.exists.return_value = 0
        cb = _make_cb(redis, weekly_drawdown_threshold=0.02)  # threshold = 2%
        await cb.record_pnl_contribution(STRATEGY, AGENT_ID, pnl_pct=-0.03)
        redis.set.assert_awaited_once()

    async def test_get_weekly_pnl_returns_float(self) -> None:
        redis = _make_redis()
        redis.get.return_value = b"-0.035"
        cb = _make_cb(redis)
        pnl = await cb.get_weekly_pnl(STRATEGY, AGENT_ID)
        assert abs(pnl - (-0.035)) < 1e-9

    async def test_get_weekly_pnl_returns_zero_when_absent(self) -> None:
        redis = _make_redis()
        redis.get.return_value = None
        cb = _make_cb(redis)
        pnl = await cb.get_weekly_pnl(STRATEGY, AGENT_ID)
        assert pnl == 0.0

    async def test_get_weekly_pnl_returns_zero_on_error(self) -> None:
        redis = _make_redis()
        redis.get.side_effect = Exception("timeout")
        cb = _make_cb(redis)
        pnl = await cb.get_weekly_pnl(STRATEGY, AGENT_ID)
        assert pnl == 0.0

    async def test_record_pnl_swallows_redis_error(self) -> None:
        redis = _make_redis()
        redis.incrbyfloat.side_effect = Exception("connection refused")
        cb = _make_cb(redis)
        await cb.record_pnl_contribution(STRATEGY, AGENT_ID, pnl_pct=-0.06)  # must not raise


# ── Trigger 3: Ensemble accuracy → size reduction ─────────────────────────────


class TestEnsembleAccuracyTrigger:
    """Trigger: >60% wrong in recent 20 signals → 25% size multiplier."""

    async def test_record_signal_outcome_pushes_correct(self) -> None:
        redis = _make_redis()
        cb = _make_cb(redis)
        await cb.record_signal_outcome(AGENT_ID, correct=True)
        pipe = redis.pipeline.return_value
        pipe.lpush.assert_called_once_with(
            StrategyCircuitBreaker._accuracy_key(AGENT_ID), "1"
        )

    async def test_record_signal_outcome_pushes_wrong(self) -> None:
        redis = _make_redis()
        cb = _make_cb(redis)
        await cb.record_signal_outcome(AGENT_ID, correct=False)
        pipe = redis.pipeline.return_value
        pipe.lpush.assert_called_once_with(
            StrategyCircuitBreaker._accuracy_key(AGENT_ID), "0"
        )

    async def test_record_signal_outcome_swallows_redis_error(self) -> None:
        redis = _make_redis()
        redis.pipeline.return_value.execute.side_effect = Exception("error")
        cb = _make_cb(redis)
        await cb.record_signal_outcome(AGENT_ID, correct=True)  # must not raise

    async def test_ensemble_accuracy_insufficient_data_returns_none(self) -> None:
        redis = _make_redis()
        # Only 10 entries, window requires 20.
        redis.lrange.return_value = [b"1"] * 10
        cb = _make_cb(redis)
        result = await cb.ensemble_accuracy(AGENT_ID)
        assert result is None

    async def test_ensemble_accuracy_full_window_correct(self) -> None:
        redis = _make_redis()
        redis.lrange.return_value = [b"1"] * ACCURACY_WINDOW
        cb = _make_cb(redis)
        accuracy = await cb.ensemble_accuracy(AGENT_ID)
        assert accuracy is not None
        assert abs(accuracy - 1.0) < 1e-9

    async def test_ensemble_accuracy_all_wrong(self) -> None:
        redis = _make_redis()
        redis.lrange.return_value = [b"0"] * ACCURACY_WINDOW
        cb = _make_cb(redis)
        accuracy = await cb.ensemble_accuracy(AGENT_ID)
        assert accuracy is not None
        assert abs(accuracy - 0.0) < 1e-9

    async def test_ensemble_accuracy_mixed(self) -> None:
        redis = _make_redis()
        # 8 correct, 12 wrong → accuracy = 8/20 = 0.40
        redis.lrange.return_value = [b"1"] * 8 + [b"0"] * 12
        cb = _make_cb(redis)
        accuracy = await cb.ensemble_accuracy(AGENT_ID)
        assert accuracy is not None
        assert abs(accuracy - 0.40) < 1e-9

    async def test_ensemble_accuracy_returns_none_on_redis_error(self) -> None:
        redis = _make_redis()
        redis.lrange.side_effect = Exception("timeout")
        cb = _make_cb(redis)
        result = await cb.ensemble_accuracy(AGENT_ID)
        assert result is None

    async def test_size_multiplier_returns_one_when_accuracy_good(self) -> None:
        redis = _make_redis()
        # 75% accuracy — above threshold (wrong fraction = 25% < 60%).
        redis.lrange.return_value = [b"1"] * 15 + [b"0"] * 5
        cb = _make_cb(redis)
        multiplier = await cb.size_multiplier(AGENT_ID)
        assert abs(multiplier - 1.0) < 1e-9

    async def test_size_multiplier_returns_025_when_accuracy_poor(self) -> None:
        redis = _make_redis()
        # 30% accuracy → 70% wrong (> 60% threshold).
        redis.lrange.return_value = [b"1"] * 6 + [b"0"] * 14
        cb = _make_cb(redis)
        multiplier = await cb.size_multiplier(AGENT_ID)
        assert abs(multiplier - LOW_ACCURACY_SIZE_MULTIPLIER) < 1e-9

    async def test_size_multiplier_returns_one_when_insufficient_data(self) -> None:
        redis = _make_redis()
        # Fewer entries than window — None returned by ensemble_accuracy.
        redis.lrange.return_value = [b"1"] * 5
        cb = _make_cb(redis)
        multiplier = await cb.size_multiplier(AGENT_ID)
        assert abs(multiplier - 1.0) < 1e-9

    async def test_size_multiplier_returns_one_on_redis_error(self) -> None:
        redis = _make_redis()
        redis.lrange.side_effect = Exception("timeout")
        cb = _make_cb(redis)
        multiplier = await cb.size_multiplier(AGENT_ID)
        assert abs(multiplier - 1.0) < 1e-9

    async def test_custom_accuracy_window_and_threshold(self) -> None:
        redis = _make_redis()
        # Custom: window=10, wrong_threshold=0.50
        # 4 correct, 6 wrong → wrong_fraction = 0.60 > 0.50 → reduce.
        redis.lrange.return_value = [b"1"] * 4 + [b"0"] * 6
        cb = _make_cb(redis, accuracy_window=10, accuracy_wrong_threshold=0.50)
        multiplier = await cb.size_multiplier(AGENT_ID)
        assert abs(multiplier - LOW_ACCURACY_SIZE_MULTIPLIER) < 1e-9


# ── filter_active_sources ─────────────────────────────────────────────────────


class TestFilterActiveSources:
    async def test_all_active(self) -> None:
        redis = _make_redis()
        redis.exists.return_value = 0  # none paused
        cb = _make_cb(redis)
        active = await cb.filter_active_sources(["rl", "evolved", "regime"], AGENT_ID)
        assert active == ["rl", "evolved", "regime"]

    async def test_one_paused(self) -> None:
        redis = _make_redis()
        # rl is paused, others are not.
        async def _exists(key: str) -> int:
            return 1 if "rl" in key else 0

        redis.exists.side_effect = _exists
        cb = _make_cb(redis)
        active = await cb.filter_active_sources(["rl", "evolved", "regime"], AGENT_ID)
        assert "rl" not in active
        assert "evolved" in active
        assert "regime" in active

    async def test_all_paused(self) -> None:
        redis = _make_redis()
        redis.exists.return_value = 1
        cb = _make_cb(redis)
        active = await cb.filter_active_sources(["rl", "evolved", "regime"], AGENT_ID)
        assert active == []

    async def test_empty_sources(self) -> None:
        redis = _make_redis()
        cb = _make_cb(redis)
        active = await cb.filter_active_sources([], AGENT_ID)
        assert active == []


# ── apply_size_multiplier ─────────────────────────────────────────────────────


class TestApplySizeMultiplier:
    async def test_normal_accuracy_returns_unchanged_size(self) -> None:
        redis = _make_redis()
        # Good accuracy → multiplier = 1.0.
        redis.lrange.return_value = [b"1"] * ACCURACY_WINDOW
        cb = _make_cb(redis)
        result = await cb.apply_size_multiplier(0.05, AGENT_ID)
        assert abs(result - 0.05) < 1e-9

    async def test_poor_accuracy_reduces_size(self) -> None:
        redis = _make_redis()
        # 70% wrong → multiplier = 0.25.
        redis.lrange.return_value = [b"1"] * 6 + [b"0"] * 14
        cb = _make_cb(redis)
        result = await cb.apply_size_multiplier(0.05, AGENT_ID)
        assert abs(result - 0.05 * LOW_ACCURACY_SIZE_MULTIPLIER) < 1e-9

    async def test_result_clamped_to_zero_minimum(self) -> None:
        redis = _make_redis()
        redis.lrange.return_value = [b"1"] * 6 + [b"0"] * 14
        cb = _make_cb(redis)
        result = await cb.apply_size_multiplier(0.0, AGENT_ID)
        assert result == 0.0

    async def test_result_clamped_to_one_maximum(self) -> None:
        redis = _make_redis()
        redis.lrange.return_value = [b"1"] * ACCURACY_WINDOW  # good accuracy
        cb = _make_cb(redis)
        result = await cb.apply_size_multiplier(2.0, AGENT_ID)
        assert result == 1.0


# ── EnsembleRunner integration ────────────────────────────────────────────────


class TestEnsembleRunnerCircuitBreakerIntegration:
    """Verify that EnsembleRunner respects the circuit breaker during step()."""

    async def test_runner_skips_paused_rl_source(self) -> None:
        """Paused RL source produces HOLD signals with circuit_breaker_paused reason."""
        from agent.strategies.ensemble.config import EnsembleConfig
        from agent.strategies.ensemble.run import EnsembleRunner

        redis = _make_redis()
        # RL is paused; others are not.
        async def _exists(key: str) -> int:
            return 1 if ":rl:" in key or key.endswith(":rl:" + AGENT_ID) else 0

        redis.exists.side_effect = _exists
        # Accuracy window not full → size multiplier = 1.0.
        redis.lrange.return_value = [b"1"] * 5  # fewer than window

        cb = StrategyCircuitBreaker(redis_client=redis)

        config = EnsembleConfig(
            enable_rl_signal=True,
            enable_evolved_signal=False,
            enable_regime_signal=False,
            enable_risk_overlay=False,
            symbols=["BTCUSDT"],
        )
        runner = EnsembleRunner(
            config=config,
            sdk_client=None,
            rest_client=None,
            circuit_breaker=cb,
            agent_id=AGENT_ID,
        )
        # Manually wire MetaLearner (skip full initialize()).
        from agent.strategies.ensemble.meta_learner import MetaLearner

        runner._meta_learner = MetaLearner()

        candles = [{"close": 50000.0 + i} for i in range(50)]
        result = await runner.step({"BTCUSDT": candles})

        # Find the RL contribution for BTCUSDT.
        btc_result = next(sr for sr in result.symbol_results if sr.symbol == "BTCUSDT")
        rl_contrib = next(c for c in btc_result.contributions if c.source == "rl")
        assert rl_contrib.metadata.get("reason") == "circuit_breaker_paused"

    async def test_runner_applies_size_reduction_on_poor_accuracy(self) -> None:
        """Size multiplier of 0.25 is applied when ensemble accuracy is poor."""
        from agent.strategies.ensemble.config import EnsembleConfig
        from agent.strategies.ensemble.run import EnsembleRunner

        redis = _make_redis()
        # No sources paused.
        redis.exists.return_value = 0
        # 70% wrong signals in the accuracy window → multiplier = 0.25.
        redis.lrange.return_value = [b"1"] * 6 + [b"0"] * 14

        cb = StrategyCircuitBreaker(redis_client=redis)

        config = EnsembleConfig(
            enable_rl_signal=False,
            enable_evolved_signal=False,
            enable_regime_signal=False,
            enable_risk_overlay=False,
            risk_base_size_pct=0.08,
            symbols=["BTCUSDT"],
        )
        runner = EnsembleRunner(
            config=config,
            sdk_client=None,
            rest_client=None,
            circuit_breaker=cb,
            agent_id=AGENT_ID,
        )
        from agent.strategies.ensemble.meta_learner import MetaLearner
        from agent.strategies.ensemble.signals import ConsensusSignal, TradeAction

        runner._meta_learner = MetaLearner()

        # Patch combine_all to return a BUY consensus so the size code path runs.
        buy_consensus = ConsensusSignal(
            symbol="BTCUSDT",
            action=TradeAction.BUY,
            combined_confidence=0.8,
            contributing_signals=[],
            agreement_rate=1.0,
        )

        original_combine_all = runner._meta_learner.combine_all
        runner._meta_learner.combine_all = lambda signals: [buy_consensus]  # type: ignore[method-assign]

        candles = [{"close": 50000.0 + i} for i in range(50)]
        result = await runner.step({"BTCUSDT": candles})

        runner._meta_learner.combine_all = original_combine_all

        btc_result = next(sr for sr in result.symbol_results if sr.symbol == "BTCUSDT")
        # Expected: 0.08 * 0.25 = 0.02
        expected_size = config.risk_base_size_pct * LOW_ACCURACY_SIZE_MULTIPLIER
        assert abs(btc_result.final_size_pct - expected_size) < 1e-9

    async def test_runner_without_circuit_breaker_unchanged(self) -> None:
        """EnsembleRunner without a circuit breaker works identically to before."""
        from agent.strategies.ensemble.config import EnsembleConfig
        from agent.strategies.ensemble.meta_learner import MetaLearner
        from agent.strategies.ensemble.run import EnsembleRunner

        config = EnsembleConfig(
            enable_rl_signal=False,
            enable_evolved_signal=False,
            enable_regime_signal=False,
            enable_risk_overlay=False,
            symbols=["BTCUSDT"],
        )
        runner = EnsembleRunner(
            config=config,
            sdk_client=None,
            rest_client=None,
            circuit_breaker=None,  # No CB
        )
        runner._meta_learner = MetaLearner()

        candles = [{"close": 50000.0}] * 50
        result = await runner.step({"BTCUSDT": candles})
        assert result.step_number == 0
        assert len(result.symbol_results) == 1
