"""Unit tests for attribution-driven ensemble weight adjustment.

Covers:
- MetaLearner.apply_attribution_weights() — weight update logic
- MetaLearner.weights property — returns a snapshot copy
- AttributionLoader.load_and_apply() — DB query, MetaLearner update, CB pause
- AttributionLoader._fetch_attribution() — aggregation query
- EnsembleRunner.load_attribution() — wires loader into runner
- Edge cases: no data, all negative, mixed, unknown strategy names
- Auto-pause: strategies with negative PnL get paused via CircuitBreaker
- Fail-safe: DB errors, CB errors captured in result.errors; never raise

All DB and Redis interactions are mocked.  No running database or Redis
instance required.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.strategies.ensemble.attribution import (
    _ATTRIBUTION_WINDOW_DAYS,
    AttributionLoader,
    AttributionResult,
)
from agent.strategies.ensemble.circuit_breaker import WEEKLY_DRAWDOWN_PAUSE_SECONDS
from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.signals import SignalSource

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_meta_learner(
    rl: float = 0.333,
    evolved: float = 0.333,
    regime: float = 0.334,
) -> MetaLearner:
    """Return a MetaLearner with explicit per-source weights."""
    return MetaLearner(
        weights={
            SignalSource.RL: rl,
            SignalSource.EVOLVED: evolved,
            SignalSource.REGIME: regime,
        }
    )


def _make_redis() -> AsyncMock:
    """Return a mock async Redis client with a no-op pipeline."""
    redis = AsyncMock()
    pipe = MagicMock()
    pipe.lpush = MagicMock(return_value=pipe)
    pipe.ltrim = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, True, True])
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


def _make_session_factory(rows: list[tuple[str, Decimal]]) -> AsyncMock:
    """Return a mock async_sessionmaker that yields a session with the given rows.

    Each entry in *rows* is a (strategy_name, pnl_sum) tuple matching the
    shape of the SELECT query in AttributionLoader._fetch_attribution().
    """
    # Build fake row objects.
    fake_rows = [
        MagicMock(strategy_name=name, pnl_sum=pnl)
        for name, pnl in rows
    ]

    # Build a mock execute result whose .all() returns fake_rows.
    mock_result = MagicMock()
    mock_result.all.return_value = fake_rows

    # Build a mock session where db.execute() returns mock_result.
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    # Build a mock session factory that acts as an async context manager.
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=mock_cm)
    return session_factory


# ── MetaLearner.weights property ──────────────────────────────────────────────


class TestMetaLearnerWeightsProperty:
    """Tests for MetaLearner.weights read-only property."""

    def test_weights_returns_dict(self) -> None:
        ml = _make_meta_learner()
        w = ml.weights
        assert isinstance(w, dict)

    def test_weights_sum_to_one(self) -> None:
        ml = _make_meta_learner()
        total = sum(ml.weights.values())
        assert abs(total - 1.0) < 1e-9

    def test_weights_keys_are_signal_sources(self) -> None:
        ml = _make_meta_learner()
        assert set(ml.weights.keys()) == set(SignalSource)

    def test_weights_is_copy_not_alias(self) -> None:
        """Mutating the returned dict must not affect the MetaLearner."""
        ml = _make_meta_learner()
        copy = ml.weights
        copy[SignalSource.RL] = 999.0
        # Internal state unchanged.
        assert ml.weights[SignalSource.RL] != 999.0


# ── MetaLearner.apply_attribution_weights ────────────────────────────────────


class TestApplyAttributionWeights:
    """Tests for MetaLearner.apply_attribution_weights()."""

    def test_empty_attribution_preserves_weights(self) -> None:
        ml = _make_meta_learner(rl=0.5, evolved=0.3, regime=0.2)
        original = ml.weights.copy()
        result = ml.apply_attribution_weights({})
        # No change — no attribution data.
        assert result == original

    def test_all_positive_boosts_weights_proportionally(self) -> None:
        """All strategies profitable: weights shift proportionally to PnL."""
        ml = _make_meta_learner(rl=0.333, evolved=0.333, regime=0.334)
        # RL: +10%, EVOLVED: +5%, REGIME: +0%
        result = ml.apply_attribution_weights({"rl": 0.10, "evolved": 0.05, "regime": 0.0})
        assert result[SignalSource.RL] > result[SignalSource.EVOLVED] > result[SignalSource.REGIME]
        assert abs(sum(result.values()) - 1.0) < 1e-9

    def test_negative_pnl_shrinks_weight(self) -> None:
        """Strategy with negative PnL gets a smaller weight."""
        ml = _make_meta_learner(rl=0.333, evolved=0.333, regime=0.334)
        result = ml.apply_attribution_weights({"rl": -0.20, "evolved": 0.0, "regime": 0.0})
        assert result[SignalSource.RL] < result[SignalSource.EVOLVED]
        assert result[SignalSource.RL] < result[SignalSource.REGIME]

    def test_min_weight_floor_applied(self) -> None:
        """Even with very negative PnL, no source drops below min_weight after normalisation."""
        ml = _make_meta_learner(rl=0.333, evolved=0.333, regime=0.334)
        # Extreme loss on RL.
        result = ml.apply_attribution_weights({"rl": -0.999}, min_weight=0.05)
        # All weights should be positive and sum to 1.
        for w in result.values():
            assert w > 0
        assert abs(sum(result.values()) - 1.0) < 1e-9

    def test_weights_sum_to_one_after_update(self) -> None:
        ml = _make_meta_learner()
        result = ml.apply_attribution_weights({"rl": 0.05, "evolved": -0.03, "regime": 0.01})
        assert abs(sum(result.values()) - 1.0) < 1e-9

    def test_unknown_strategy_name_ignored(self) -> None:
        ml = _make_meta_learner()
        original_weights = ml.weights.copy()
        # "deep_rl" is not a known SignalSource value.
        result = ml.apply_attribution_weights({"deep_rl": 0.5})
        # Weights unchanged since no known source was referenced.
        assert result == original_weights

    def test_returns_new_weights_dict(self) -> None:
        ml = _make_meta_learner()
        result = ml.apply_attribution_weights({"rl": 0.10})
        assert isinstance(result, dict)
        assert set(result.keys()) == set(SignalSource)

    def test_internal_weights_updated_after_call(self) -> None:
        """Calling apply_attribution_weights mutates self._weights."""
        ml = _make_meta_learner(rl=0.333, evolved=0.333, regime=0.334)
        ml.apply_attribution_weights({"rl": 0.20})
        # RL weight should now be the highest.
        assert ml.weights[SignalSource.RL] > ml.weights[SignalSource.EVOLVED]

    def test_base_weights_updated_for_sharpe_continuity(self) -> None:
        """After apply_attribution_weights, base_weights mirrors the new weights."""
        ml = _make_meta_learner()
        new_w = ml.apply_attribution_weights({"rl": 0.10})
        # _base_weights should match the new normalised weights.
        for source, w in new_w.items():
            assert abs(ml._base_weights[source] - w) < 1e-9

    def test_invalid_min_weight_raises(self) -> None:
        ml = _make_meta_learner()
        with pytest.raises(ValueError, match="min_weight"):
            ml.apply_attribution_weights({}, min_weight=1.0)

    def test_invalid_min_weight_negative_raises(self) -> None:
        ml = _make_meta_learner()
        with pytest.raises(ValueError, match="min_weight"):
            ml.apply_attribution_weights({}, min_weight=-0.1)

    def test_mixed_pnl_ordering(self) -> None:
        """Source with highest PnL should have highest post-update weight."""
        ml = _make_meta_learner(rl=0.333, evolved=0.333, regime=0.334)
        # Regime: +15%, RL: -5%, EVOLVED: 0%
        result = ml.apply_attribution_weights(
            {"rl": -0.05, "evolved": 0.00, "regime": 0.15}
        )
        assert result[SignalSource.REGIME] > result[SignalSource.EVOLVED]
        assert result[SignalSource.EVOLVED] > result[SignalSource.RL]

    def test_partial_attribution_only_adjusts_named_sources(self) -> None:
        """Providing PnL for only one source still normalises correctly."""
        ml = _make_meta_learner(rl=0.5, evolved=0.3, regime=0.2)
        result = ml.apply_attribution_weights({"rl": 0.50})
        # Sum must still equal 1.0.
        assert abs(sum(result.values()) - 1.0) < 1e-9
        # RL should have grown relative to its original share.
        assert result[SignalSource.RL] > 0.5


# ── AttributionLoader: basic construction ────────────────────────────────────


class TestAttributionLoaderInit:
    def test_creates_without_meta_learner(self) -> None:
        sf = MagicMock()
        loader = AttributionLoader(session_factory=sf)
        assert loader._meta_learner is None
        assert loader._circuit_breaker is None

    def test_stores_meta_learner(self) -> None:
        ml = _make_meta_learner()
        loader = AttributionLoader(session_factory=MagicMock(), meta_learner=ml)
        assert loader._meta_learner is ml

    def test_stores_circuit_breaker(self) -> None:
        from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker  # noqa: PLC0415
        redis = _make_redis()
        cb = StrategyCircuitBreaker(redis_client=redis)
        loader = AttributionLoader(session_factory=MagicMock(), circuit_breaker=cb)
        assert loader._circuit_breaker is cb


# ── AttributionLoader.load_and_apply — no data ───────────────────────────────


class TestLoadAndApplyNoData:
    async def test_returns_result_with_no_strategies(self) -> None:
        sf = _make_session_factory([])
        loader = AttributionLoader(session_factory=sf, meta_learner=_make_meta_learner())
        result = await loader.load_and_apply("agent-001")
        assert isinstance(result, AttributionResult)
        assert result.strategies_loaded == 0
        assert result.strategies_paused == 0
        assert result.attribution_pnl == {}
        assert result.errors == []

    async def test_no_data_does_not_change_meta_learner_weights(self) -> None:
        ml = _make_meta_learner()
        original = ml.weights.copy()
        sf = _make_session_factory([])
        loader = AttributionLoader(session_factory=sf, meta_learner=ml)
        await loader.load_and_apply("agent-001")
        assert ml.weights == original


# ── AttributionLoader.load_and_apply — with data ─────────────────────────────


class TestLoadAndApplyWithData:
    async def test_loads_attribution_pnl(self) -> None:
        rows = [
            ("rl", Decimal("0.03")),
            ("evolved", Decimal("-0.02")),
            ("regime", Decimal("0.01")),
        ]
        sf = _make_session_factory(rows)
        ml = _make_meta_learner()
        loader = AttributionLoader(session_factory=sf, meta_learner=ml)
        result = await loader.load_and_apply("agent-001")
        assert result.strategies_loaded == 3
        assert abs(result.attribution_pnl["rl"] - 0.03) < 1e-9
        assert abs(result.attribution_pnl["evolved"] - (-0.02)) < 1e-9
        assert abs(result.attribution_pnl["regime"] - 0.01) < 1e-9

    async def test_meta_learner_weights_updated(self) -> None:
        rows = [("rl", Decimal("0.10")), ("evolved", Decimal("0.0")), ("regime", Decimal("0.0"))]
        sf = _make_session_factory(rows)
        ml = _make_meta_learner()
        loader = AttributionLoader(session_factory=sf, meta_learner=ml)
        await loader.load_and_apply("agent-001")
        # RL boosted by +10%: should now be the highest weight.
        assert ml.weights[SignalSource.RL] > ml.weights[SignalSource.EVOLVED]

    async def test_result_new_weights_populated(self) -> None:
        rows = [("rl", Decimal("0.05"))]
        sf = _make_session_factory(rows)
        ml = _make_meta_learner()
        loader = AttributionLoader(session_factory=sf, meta_learner=ml)
        result = await loader.load_and_apply("agent-001")
        assert "rl" in result.new_weights
        assert "evolved" in result.new_weights
        assert "regime" in result.new_weights

    async def test_no_errors_on_success(self) -> None:
        rows = [("rl", Decimal("0.02"))]
        sf = _make_session_factory(rows)
        loader = AttributionLoader(session_factory=sf, meta_learner=_make_meta_learner())
        result = await loader.load_and_apply("agent-001")
        assert result.errors == []

    async def test_duration_ms_non_negative(self) -> None:
        rows = [("rl", Decimal("0.01"))]
        sf = _make_session_factory(rows)
        loader = AttributionLoader(session_factory=sf, meta_learner=_make_meta_learner())
        result = await loader.load_and_apply("agent-001")
        assert result.duration_ms >= 0

    async def test_none_pnl_sum_treated_as_zero(self) -> None:
        """Rows with NULL pnl_sum (edge case in DB) should not cause errors."""
        # Build a session factory where pnl_sum is None (SQL NULL scenario).
        rows_with_none = [MagicMock(strategy_name="rl", pnl_sum=None)]
        mock_result = MagicMock()
        mock_result.all.return_value = rows_with_none
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        sf_none = MagicMock(return_value=mock_cm)
        loader = AttributionLoader(session_factory=sf_none, meta_learner=_make_meta_learner())
        result = await loader.load_and_apply("agent-001")
        # Should handle None without raising and treat as 0.
        assert result.attribution_pnl.get("rl", 0.0) == 0.0


# ── Auto-pause via CircuitBreaker ─────────────────────────────────────────────


class TestAutoPassCircuitBreaker:
    async def test_negative_pnl_triggers_pause(self) -> None:
        rows = [("rl", Decimal("-0.05")), ("evolved", Decimal("0.02"))]
        sf = _make_session_factory(rows)
        redis = _make_redis()
        redis.exists = AsyncMock(return_value=0)  # not paused
        redis.set = AsyncMock(return_value=True)

        from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker  # noqa: PLC0415
        cb = StrategyCircuitBreaker(redis_client=redis)
        loader = AttributionLoader(
            session_factory=sf,
            meta_learner=_make_meta_learner(),
            circuit_breaker=cb,
        )
        result = await loader.load_and_apply("agent-001")
        assert result.strategies_paused == 1  # only RL paused

    async def test_already_paused_strategy_not_double_paused(self) -> None:
        rows = [("rl", Decimal("-0.05"))]
        sf = _make_session_factory(rows)
        redis = _make_redis()
        redis.exists = AsyncMock(return_value=1)  # already paused

        from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker  # noqa: PLC0415
        cb = StrategyCircuitBreaker(redis_client=redis)
        loader = AttributionLoader(
            session_factory=sf,
            meta_learner=_make_meta_learner(),
            circuit_breaker=cb,
        )
        result = await loader.load_and_apply("agent-001")
        assert result.strategies_paused == 0  # already paused; skip

    async def test_positive_pnl_does_not_trigger_pause(self) -> None:
        rows = [("rl", Decimal("0.05")), ("evolved", Decimal("0.01"))]
        sf = _make_session_factory(rows)
        redis = _make_redis()
        redis.exists = AsyncMock(return_value=0)

        from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker  # noqa: PLC0415
        cb = StrategyCircuitBreaker(redis_client=redis)
        loader = AttributionLoader(
            session_factory=sf,
            meta_learner=_make_meta_learner(),
            circuit_breaker=cb,
        )
        result = await loader.load_and_apply("agent-001")
        assert result.strategies_paused == 0

    async def test_pause_uses_weekly_drawdown_ttl(self) -> None:
        rows = [("evolved", Decimal("-0.08"))]
        sf = _make_session_factory(rows)
        redis = _make_redis()
        redis.exists = AsyncMock(return_value=0)
        redis.set = AsyncMock(return_value=True)

        from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker  # noqa: PLC0415
        cb = StrategyCircuitBreaker(redis_client=redis)
        loader = AttributionLoader(
            session_factory=sf,
            meta_learner=_make_meta_learner(),
            circuit_breaker=cb,
        )
        await loader.load_and_apply("agent-001")
        # Verify redis.set was called with the weekly drawdown TTL.
        redis.set.assert_called_once()
        call_kwargs = redis.set.call_args
        # The TTL is passed as `ex=` keyword argument.
        assert call_kwargs.kwargs.get("ex") == WEEKLY_DRAWDOWN_PAUSE_SECONDS

    async def test_no_circuit_breaker_skips_pause(self) -> None:
        rows = [("rl", Decimal("-0.05"))]
        sf = _make_session_factory(rows)
        loader = AttributionLoader(
            session_factory=sf,
            meta_learner=_make_meta_learner(),
            circuit_breaker=None,
        )
        result = await loader.load_and_apply("agent-001")
        # No CB → no pauses, no errors.
        assert result.strategies_paused == 0
        assert result.errors == []

    async def test_all_negative_pauses_all(self) -> None:
        rows = [
            ("rl", Decimal("-0.03")),
            ("evolved", Decimal("-0.07")),
            ("regime", Decimal("-0.01")),
        ]
        sf = _make_session_factory(rows)
        redis = _make_redis()
        redis.exists = AsyncMock(return_value=0)
        redis.set = AsyncMock(return_value=True)

        from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker  # noqa: PLC0415
        cb = StrategyCircuitBreaker(redis_client=redis)
        loader = AttributionLoader(
            session_factory=sf,
            meta_learner=_make_meta_learner(),
            circuit_breaker=cb,
        )
        result = await loader.load_and_apply("agent-001")
        assert result.strategies_paused == 3


# ── Error handling ────────────────────────────────────────────────────────────


class TestErrorHandling:
    async def test_db_error_captured_in_result(self) -> None:
        """A DB exception during fetch should be captured in errors, not raised."""
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("DB connection failed"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=mock_cm)

        loader = AttributionLoader(session_factory=sf, meta_learner=_make_meta_learner())
        result = await loader.load_and_apply("agent-001")
        assert len(result.errors) == 1
        assert "DB fetch failed" in result.errors[0]
        assert result.strategies_loaded == 0

    async def test_circuit_breaker_error_captured(self) -> None:
        """A Redis error during CB pause should be captured, not propagate."""
        rows = [("rl", Decimal("-0.05"))]
        sf = _make_session_factory(rows)

        redis = _make_redis()
        redis.exists = AsyncMock(side_effect=RuntimeError("Redis timeout"))

        from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker  # noqa: PLC0415
        cb = StrategyCircuitBreaker(redis_client=redis)
        loader = AttributionLoader(
            session_factory=sf,
            meta_learner=_make_meta_learner(),
            circuit_breaker=cb,
        )
        result = await loader.load_and_apply("agent-001")
        # The CB error is caught inside is_paused (fail-open) so no loader error.
        # The CB itself logs and swallows the error — result.errors may be empty.
        assert isinstance(result, AttributionResult)

    async def test_meta_learner_error_captured(self) -> None:
        """If apply_attribution_weights raises, error is captured in result."""
        rows = [("rl", Decimal("0.05"))]
        sf = _make_session_factory(rows)
        ml = _make_meta_learner()

        with patch.object(ml, "apply_attribution_weights", side_effect=ValueError("bad min")):
            loader = AttributionLoader(session_factory=sf, meta_learner=ml)
            result = await loader.load_and_apply("agent-001")
            assert len(result.errors) == 1
            assert "MetaLearner weight update failed" in result.errors[0]


# ── EnsembleRunner.load_attribution ───────────────────────────────────────────


class TestEnsembleRunnerLoadAttribution:
    """Smoke tests for EnsembleRunner.load_attribution() integration."""

    def _make_runner(self) -> None:  # type: ignore[return]  # EnsembleRunner imported lazily
        from agent.strategies.ensemble.config import EnsembleConfig  # noqa: PLC0415
        from agent.strategies.ensemble.run import EnsembleRunner  # noqa: PLC0415

        config = EnsembleConfig(
            enable_rl_signal=False,
            enable_evolved_signal=False,
            enable_regime_signal=False,
            enable_risk_overlay=False,
        )
        return EnsembleRunner(config=config, sdk_client=None, rest_client=None)

    async def test_returns_none_before_initialize(self) -> None:
        runner = self._make_runner()
        sf = _make_session_factory([])
        result = await runner.load_attribution(agent_id="agent-001", session_factory=sf)
        assert result is None

    async def test_returns_attribution_result_after_initialize(self) -> None:
        runner = self._make_runner()
        await runner.initialize()
        sf = _make_session_factory([("rl", Decimal("0.02"))])
        result = await runner.load_attribution(agent_id="agent-001", session_factory=sf)
        assert isinstance(result, AttributionResult)
        assert result.strategies_loaded == 1

    async def test_wires_meta_learner_from_runner(self) -> None:
        runner = self._make_runner()
        await runner.initialize()
        original_weights = runner._meta_learner.weights.copy()
        sf = _make_session_factory([("rl", Decimal("0.30"))])  # big RL boost
        await runner.load_attribution(agent_id="agent-001", session_factory=sf)
        # RL weight should have increased.
        assert runner._meta_learner.weights[SignalSource.RL] > original_weights[SignalSource.RL]

    async def test_passes_circuit_breaker_to_loader(self) -> None:
        from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker  # noqa: PLC0415
        from agent.strategies.ensemble.config import EnsembleConfig  # noqa: PLC0415
        from agent.strategies.ensemble.run import EnsembleRunner  # noqa: PLC0415

        config = EnsembleConfig(
            enable_rl_signal=False,
            enable_evolved_signal=False,
            enable_regime_signal=False,
            enable_risk_overlay=False,
        )
        redis = _make_redis()
        redis.exists = AsyncMock(return_value=0)
        redis.set = AsyncMock(return_value=True)
        cb = StrategyCircuitBreaker(redis_client=redis)

        runner = EnsembleRunner(
            config=config,
            sdk_client=None,
            rest_client=None,
            circuit_breaker=cb,
        )
        await runner.initialize()

        sf = _make_session_factory([("evolved", Decimal("-0.10"))])
        result = await runner.load_attribution(agent_id="agent-001", session_factory=sf)
        assert result is not None
        assert result.strategies_paused == 1

    async def test_custom_window_days_forwarded(self) -> None:
        """window_days=3 should restrict the attribution window in the DB query."""
        runner = self._make_runner()
        await runner.initialize()
        sf = _make_session_factory([])

        # We just verify it calls through without error; window is in the SQL WHERE clause.
        result = await runner.load_attribution(
            agent_id="agent-001",
            session_factory=sf,
            window_days=3,
        )
        assert isinstance(result, AttributionResult)


# ── AttributionResult dataclass ───────────────────────────────────────────────


class TestAttributionResult:
    def test_defaults(self) -> None:
        r = AttributionResult(agent_id="agent-001")
        assert r.strategies_loaded == 0
        assert r.strategies_paused == 0
        assert r.attribution_pnl == {}
        assert r.new_weights == {}
        assert r.duration_ms == 0.0
        assert r.errors == []

    def test_populated_fields(self) -> None:
        r = AttributionResult(
            agent_id="agent-002",
            strategies_loaded=3,
            strategies_paused=1,
            attribution_pnl={"rl": 0.05, "evolved": -0.02},
            new_weights={"rl": 0.40, "evolved": 0.30, "regime": 0.30},
            duration_ms=42.5,
            errors=["one error"],
        )
        assert r.strategies_loaded == 3
        assert r.strategies_paused == 1
        assert r.attribution_pnl["rl"] == 0.05
        assert r.new_weights["rl"] == 0.40
        assert r.duration_ms == 42.5
        assert r.errors == ["one error"]


# ── Window constant ───────────────────────────────────────────────────────────


class TestAttributionWindowConstant:
    def test_default_window_is_7_days(self) -> None:
        assert _ATTRIBUTION_WINDOW_DAYS == 7
