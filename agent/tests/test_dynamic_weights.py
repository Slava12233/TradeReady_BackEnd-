"""Unit tests for MetaLearner dynamic weight adaptation (Task 23).

Covers:
- TradeOutcome dataclass construction and field defaults
- MetaLearner._rolling_sharpe() edge cases
- MetaLearner.update_weights() with no-op (empty outcomes)
- update_weights() shifts weights toward the winning source
- Rolling Sharpe window is correctly bounded (deque maxlen)
- Regime-conditional modifiers: TRENDING, MEAN_REVERTING, HIGH_VOLATILITY, LOW_VOLATILITY
- Unknown regime falls back silently (no modifier applied)
- Weights always normalise to sum 1.0 after update_weights()
- Weights always normalise to sum 1.0 after apply_attribution_weights()
- apply_attribution_weights() min_weight floor is respected
- apply_attribution_weights() raises on invalid min_weight
- EnsembleRunner.record_trade_outcome() buffers outcomes
- EnsembleRunner._drain_pending_outcomes() drains and clears
- EnsembleRunner.step() calls update_weights() when outcomes are pending
- EnsembleRunner.step() does not crash when update_weights() raises
- MetaLearner.weights property returns a copy (mutation does not propagate)
- MetaLearner.pnl_history property returns snapshots per source
- sharpe_window constructor parameter is respected
"""

from __future__ import annotations

import math
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.strategies.ensemble.meta_learner import (
    MetaLearner,
    TradeOutcome,
    _REGIME_WEIGHT_MODIFIERS,
    _SHARPE_WINDOW,
)
from agent.strategies.ensemble.signals import SignalSource, TradeAction, WeightedSignal


# ── Helpers ───────────────────────────────────────────────────────────────────


def _equal_weights() -> dict[SignalSource, float]:
    """Return equal starting weights (each 1/3)."""
    return {s: 1.0 for s in SignalSource}


def _make_outcome(
    source: SignalSource,
    pnl_pct: float,
    regime: object = None,
) -> TradeOutcome:
    return TradeOutcome(source=source, pnl_pct=pnl_pct, symbol="BTCUSDT", regime=regime)


def _make_learner(
    weights: dict[SignalSource, float] | None = None,
    sharpe_window: int = _SHARPE_WINDOW,
) -> MetaLearner:
    return MetaLearner(weights=weights, sharpe_window=sharpe_window)


# ── TradeOutcome dataclass ────────────────────────────────────────────────────


class TestTradeOutcome:
    def test_fields_stored(self) -> None:
        o = TradeOutcome(source=SignalSource.RL, pnl_pct=0.05)
        assert o.source is SignalSource.RL
        assert o.pnl_pct == pytest.approx(0.05)

    def test_symbol_default(self) -> None:
        o = TradeOutcome(source=SignalSource.EVOLVED, pnl_pct=0.0)
        assert o.symbol == "UNKNOWN"

    def test_regime_default_none(self) -> None:
        o = TradeOutcome(source=SignalSource.REGIME, pnl_pct=-0.01)
        assert o.regime is None

    def test_all_fields_explicit(self) -> None:
        o = TradeOutcome(
            source=SignalSource.EVOLVED,
            pnl_pct=-0.02,
            symbol="ETHUSDT",
            regime="trending",
        )
        assert o.source is SignalSource.EVOLVED
        assert o.pnl_pct == pytest.approx(-0.02)
        assert o.symbol == "ETHUSDT"
        assert o.regime == "trending"


# ── MetaLearner._rolling_sharpe ───────────────────────────────────────────────


class TestRollingSharpe:
    def test_insufficient_observations_returns_zero(self) -> None:
        # Need at least 2 observations.
        assert MetaLearner._rolling_sharpe([0.01]) == pytest.approx(0.0)
        assert MetaLearner._rolling_sharpe([]) == pytest.approx(0.0)

    def test_all_positive_returns_positive_sharpe(self) -> None:
        pnl = [0.01, 0.02, 0.03, 0.015, 0.025]
        sharpe = MetaLearner._rolling_sharpe(pnl)
        assert sharpe > 0.0

    def test_all_negative_returns_negative_sharpe(self) -> None:
        pnl = [-0.01, -0.02, -0.03]
        sharpe = MetaLearner._rolling_sharpe(pnl)
        assert sharpe < 0.0

    def test_zero_stddev_positive_mean(self) -> None:
        # All identical positive values → stddev = 0 → return 1.0
        sharpe = MetaLearner._rolling_sharpe([0.02, 0.02, 0.02])
        assert sharpe == pytest.approx(1.0)

    def test_zero_stddev_negative_mean(self) -> None:
        sharpe = MetaLearner._rolling_sharpe([-0.01, -0.01, -0.01])
        assert sharpe == pytest.approx(-1.0)

    def test_zero_stddev_zero_mean(self) -> None:
        sharpe = MetaLearner._rolling_sharpe([0.0, 0.0, 0.0])
        assert sharpe == pytest.approx(0.0)

    def test_mixed_returns(self) -> None:
        pnl = [0.05, -0.01, 0.03, -0.02, 0.04]
        sharpe = MetaLearner._rolling_sharpe(pnl)
        n = len(pnl)
        mean = sum(pnl) / n
        variance = sum((x - mean) ** 2 for x in pnl) / n
        expected = mean / math.sqrt(variance)
        assert sharpe == pytest.approx(expected)


# ── MetaLearner.update_weights ────────────────────────────────────────────────


class TestUpdateWeights:
    def test_empty_outcomes_is_noop(self) -> None:
        ml = _make_learner()
        before = dict(ml.weights)
        result = ml.update_weights([])
        assert result == before
        assert ml.weights == before

    def test_returns_dict_of_signal_sources(self) -> None:
        ml = _make_learner()
        outcomes = [_make_outcome(SignalSource.RL, 0.02)]
        result = ml.update_weights(outcomes)
        assert set(result.keys()) == set(SignalSource)

    def test_weights_always_sum_to_one(self) -> None:
        ml = _make_learner()
        outcomes = [
            _make_outcome(SignalSource.RL, 0.05),
            _make_outcome(SignalSource.EVOLVED, -0.02),
            _make_outcome(SignalSource.REGIME, 0.01),
        ]
        ml.update_weights(outcomes)
        assert sum(ml.weights.values()) == pytest.approx(1.0)

    def test_winning_source_gets_higher_weight(self) -> None:
        """RL consistently wins — its weight should increase."""
        ml = _make_learner()
        initial_rl_weight = ml.weights[SignalSource.RL]

        # Give RL many positive outcomes, others neutral.
        outcomes = [_make_outcome(SignalSource.RL, 0.04) for _ in range(20)]
        outcomes += [_make_outcome(SignalSource.EVOLVED, 0.0) for _ in range(20)]
        outcomes += [_make_outcome(SignalSource.REGIME, 0.0) for _ in range(20)]
        ml.update_weights(outcomes)

        assert ml.weights[SignalSource.RL] > initial_rl_weight

    def test_losing_source_gets_lower_weight(self) -> None:
        """EVOLVED consistently loses — its weight should decrease."""
        ml = _make_learner()
        initial_evolved_weight = ml.weights[SignalSource.EVOLVED]

        outcomes = [_make_outcome(SignalSource.EVOLVED, -0.03) for _ in range(20)]
        outcomes += [_make_outcome(SignalSource.RL, 0.01) for _ in range(20)]
        outcomes += [_make_outcome(SignalSource.REGIME, 0.01) for _ in range(20)]
        ml.update_weights(outcomes)

        assert ml.weights[SignalSource.EVOLVED] < initial_evolved_weight

    def test_pnl_history_accumulated(self) -> None:
        ml = _make_learner()
        ml.update_weights([_make_outcome(SignalSource.RL, 0.01)])
        ml.update_weights([_make_outcome(SignalSource.RL, 0.02)])

        history = ml.pnl_history[SignalSource.RL]
        assert len(history) == 2
        assert history[0] == pytest.approx(0.01)
        assert history[1] == pytest.approx(0.02)

    def test_rolling_window_bounded_by_sharpe_window(self) -> None:
        window = 5
        ml = _make_learner(sharpe_window=window)
        for i in range(10):
            ml.update_weights([_make_outcome(SignalSource.RL, float(i) * 0.01)])

        history = ml.pnl_history[SignalSource.RL]
        # deque is capped at window; only last 5 values should remain.
        assert len(history) == window
        # Last 5 entries: 5, 6, 7, 8, 9 → 0.05, 0.06, 0.07, 0.08, 0.09
        assert history[-1] == pytest.approx(0.09)
        assert history[0] == pytest.approx(0.05)

    def test_regime_derived_from_last_outcome(self) -> None:
        """When current_regime=None, regime from the last outcome is used."""
        ml = _make_learner()
        # Equal wins for all sources so weight change is only from regime modifier.
        outcomes = [
            _make_outcome(SignalSource.RL, 0.01, regime="trending"),
            _make_outcome(SignalSource.EVOLVED, 0.01, regime="trending"),
            _make_outcome(SignalSource.REGIME, 0.01, regime="trending"),
        ]
        ml.update_weights(outcomes, current_regime=None)
        # TRENDING: RL +30%, EVOLVED -10%, REGIME 0%.
        # With equal base weights (1/3 each) RL should be highest.
        assert ml.weights[SignalSource.RL] > ml.weights[SignalSource.EVOLVED]

    def test_explicit_current_regime_overrides_outcome_regime(self) -> None:
        """current_regime parameter takes priority over outcome.regime."""
        ml_trending = _make_learner()
        ml_mean_rev = _make_learner()

        # Same outcomes but different current_regime.
        base_outcomes = [
            _make_outcome(SignalSource.RL, 0.01, regime="low_volatility"),
        ]
        ml_trending.update_weights(base_outcomes, current_regime="trending")
        ml_mean_rev.update_weights(base_outcomes, current_regime="mean_reverting")

        # TRENDING boosts RL; MEAN_REVERTING boosts EVOLVED.
        assert ml_trending.weights[SignalSource.RL] > ml_mean_rev.weights[SignalSource.RL]
        assert ml_mean_rev.weights[SignalSource.EVOLVED] > ml_trending.weights[SignalSource.EVOLVED]

    def test_unknown_regime_applies_no_modifier(self) -> None:
        """An unrecognised regime string should not change weights beyond Sharpe."""
        ml_no_regime = _make_learner()
        ml_unknown = _make_learner()

        outcomes = [_make_outcome(SignalSource.RL, 0.02) for _ in range(10)]
        ml_no_regime.update_weights(outcomes, current_regime=None)
        ml_unknown.update_weights(outcomes, current_regime="UNKNOWN_REGIME_XYZ")

        # Weights should be identical since the unknown regime has no modifier.
        for source in SignalSource:
            assert ml_no_regime.weights[source] == pytest.approx(
                ml_unknown.weights[source], abs=1e-9
            )

    def test_no_regime_modifier_when_regime_is_none(self) -> None:
        """No modifier applied when both current_regime=None and outcome.regime is None."""
        ml = _make_learner()
        outcomes = [_make_outcome(SignalSource.RL, 0.02) for _ in range(10)]
        ml.update_weights(outcomes, current_regime=None)
        # Should complete without error and weights should sum to 1.
        assert sum(ml.weights.values()) == pytest.approx(1.0)

    def test_weights_property_is_copy(self) -> None:
        """Mutating the returned dict must not affect internal state."""
        ml = _make_learner()
        w = ml.weights
        original_rl = w[SignalSource.RL]
        w[SignalSource.RL] = 999.0
        assert ml.weights[SignalSource.RL] == pytest.approx(original_rl)

    def test_pnl_history_is_snapshot(self) -> None:
        """Mutating the returned pnl_history list must not affect internal deque."""
        ml = _make_learner()
        ml.update_weights([_make_outcome(SignalSource.RL, 0.01)])
        history = ml.pnl_history[SignalSource.RL]
        history.clear()
        # Internal deque should be unchanged.
        assert len(ml.pnl_history[SignalSource.RL]) == 1


# ── Regime-conditional modifiers ─────────────────────────────────────────────


class TestRegimeModifiers:
    """Verify that each regime applies the correct directional modifier."""

    def _run_regime(self, regime_key: str) -> dict[SignalSource, float]:
        ml = _make_learner()
        # Provide equal PnL to isolate the regime effect.
        outcomes = [
            _make_outcome(SignalSource.RL, 0.01),
            _make_outcome(SignalSource.EVOLVED, 0.01),
            _make_outcome(SignalSource.REGIME, 0.01),
        ]
        ml.update_weights(outcomes, current_regime=regime_key)
        return ml.weights

    def test_trending_boosts_rl(self) -> None:
        weights = self._run_regime("trending")
        # TRENDING: RL +30%, EVOLVED -10%, REGIME ±0%
        # So RL should beat EVOLVED and REGIME.
        assert weights[SignalSource.RL] > weights[SignalSource.EVOLVED]
        assert weights[SignalSource.RL] > weights[SignalSource.REGIME]

    def test_trending_reduces_evolved(self) -> None:
        weights = self._run_regime("trending")
        assert weights[SignalSource.EVOLVED] < weights[SignalSource.RL]

    def test_mean_reverting_boosts_evolved(self) -> None:
        weights = self._run_regime("mean_reverting")
        # MEAN_REVERTING: EVOLVED +30%, RL -10%
        assert weights[SignalSource.EVOLVED] > weights[SignalSource.RL]

    def test_mean_reverting_reduces_rl(self) -> None:
        weights = self._run_regime("mean_reverting")
        assert weights[SignalSource.RL] < weights[SignalSource.EVOLVED]

    def test_high_volatility_regime_weights_sum_to_one(self) -> None:
        weights = self._run_regime("high_volatility")
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_high_volatility_reduces_rl_relative_to_low_vol(self) -> None:
        weights_hv = self._run_regime("high_volatility")
        weights_lv = self._run_regime("low_volatility")
        # HIGH_VOLATILITY applies -50% modifier to RL; LOW_VOLATILITY applies +20%.
        assert weights_hv[SignalSource.RL] < weights_lv[SignalSource.RL]

    def test_high_volatility_regime_signal_has_best_relative_position(self) -> None:
        """In HIGH_VOLATILITY, REGIME has the smallest reduction (−30%)
        vs RL and EVOLVED (each −50%), so REGIME ends up with the highest weight."""
        weights = self._run_regime("high_volatility")
        assert weights[SignalSource.REGIME] > weights[SignalSource.RL]
        assert weights[SignalSource.REGIME] > weights[SignalSource.EVOLVED]

    def test_low_volatility_boosts_rl(self) -> None:
        weights = self._run_regime("low_volatility")
        # LOW_VOLATILITY: RL +20%, others unchanged.
        assert weights[SignalSource.RL] > weights[SignalSource.EVOLVED]
        assert weights[SignalSource.RL] > weights[SignalSource.REGIME]

    def test_regime_string_value_accepted(self) -> None:
        """Plain strings like 'trending' (not enum values) are accepted."""
        ml = _make_learner()
        ml.update_weights(
            [_make_outcome(SignalSource.RL, 0.02)],
            current_regime="trending",
        )
        assert sum(ml.weights.values()) == pytest.approx(1.0)

    def test_regime_enum_value_attribute_accepted(self) -> None:
        """An object with a .value attribute (e.g. RegimeType enum) is accepted."""

        class FakeRegime:
            value = "mean_reverting"

        ml = _make_learner()
        ml.update_weights(
            [_make_outcome(SignalSource.EVOLVED, 0.02)],
            current_regime=FakeRegime(),
        )
        assert sum(ml.weights.values()) == pytest.approx(1.0)
        # MEAN_REVERTING should have boosted EVOLVED.
        assert ml.weights[SignalSource.EVOLVED] > ml.weights[SignalSource.RL]

    def test_all_regimes_present_in_modifier_table(self) -> None:
        expected = {"trending", "mean_reverting", "high_volatility", "low_volatility"}
        assert set(_REGIME_WEIGHT_MODIFIERS.keys()) == expected

    def test_all_regime_modifiers_have_all_sources(self) -> None:
        for regime_key, mod_dict in _REGIME_WEIGHT_MODIFIERS.items():
            for source in SignalSource:
                assert source in mod_dict, (
                    f"Regime '{regime_key}' missing modifier for {source}"
                )


# ── apply_attribution_weights ─────────────────────────────────────────────────


class TestApplyAttributionWeights:
    def test_positive_pnl_boosts_weight(self) -> None:
        ml = _make_learner()
        initial = ml.weights[SignalSource.RL]
        ml.apply_attribution_weights({"rl": 0.10})
        assert ml.weights[SignalSource.RL] > initial

    def test_negative_pnl_reduces_weight(self) -> None:
        ml = _make_learner()
        initial = ml.weights[SignalSource.EVOLVED]
        ml.apply_attribution_weights({"evolved": -0.30})
        assert ml.weights[SignalSource.EVOLVED] < initial

    def test_weights_sum_to_one_after_attribution(self) -> None:
        ml = _make_learner()
        ml.apply_attribution_weights({"rl": 0.05, "evolved": -0.10, "regime": 0.02})
        assert sum(ml.weights.values()) == pytest.approx(1.0)

    def test_min_weight_floor_applied(self) -> None:
        ml = _make_learner()
        # A very large negative attribution should be floored.
        ml.apply_attribution_weights({"evolved": -0.999}, min_weight=0.10)
        assert ml.weights[SignalSource.EVOLVED] >= 0.10

    def test_invalid_min_weight_raises(self) -> None:
        ml = _make_learner()
        with pytest.raises(ValueError):
            ml.apply_attribution_weights({}, min_weight=1.0)
        with pytest.raises(ValueError):
            ml.apply_attribution_weights({}, min_weight=-0.1)

    def test_unknown_source_key_ignored(self) -> None:
        ml = _make_learner()
        before = dict(ml.weights)
        # "unknown_source" is not a valid SignalSource value — should be ignored.
        ml.apply_attribution_weights({"unknown_source": 0.50})
        assert sum(ml.weights.values()) == pytest.approx(1.0)
        # Weights should be unchanged since no known source was specified.
        for source in SignalSource:
            assert ml.weights[source] == pytest.approx(before[source], abs=1e-9)

    def test_returns_updated_weights(self) -> None:
        ml = _make_learner()
        result = ml.apply_attribution_weights({"rl": 0.05})
        assert set(result.keys()) == set(SignalSource)
        assert sum(result.values()) == pytest.approx(1.0)

    def test_base_weights_updated_for_subsequent_sharpe_updates(self) -> None:
        """After attribution, base_weights reflect the new baseline."""
        ml = _make_learner()
        ml.apply_attribution_weights({"rl": 0.50})  # boost RL significantly
        rl_weight_after_attribution = ml.weights[SignalSource.RL]

        # Now feed neutral outcomes — Sharpe is 0 so weights should stay at
        # the attribution-adjusted baseline.
        outcomes = [_make_outcome(SignalSource.RL, 0.0) for _ in range(5)]
        ml.update_weights(outcomes)

        # RL weight should still be elevated because _base_weights was updated.
        assert ml.weights[SignalSource.RL] > 1.0 / len(SignalSource)
        # And the magnitude should be close to the attribution-adjusted level.
        assert ml.weights[SignalSource.RL] == pytest.approx(
            rl_weight_after_attribution, abs=0.05
        )


# ── sharpe_window constructor parameter ──────────────────────────────────────


class TestSharpeWindowParam:
    def test_custom_window_respected(self) -> None:
        window = 10
        ml = MetaLearner(sharpe_window=window)
        # Fill beyond the window.
        for _ in range(20):
            ml.update_weights([_make_outcome(SignalSource.RL, 0.01)])
        history = ml.pnl_history[SignalSource.RL]
        assert len(history) == window

    def test_default_window_is_50(self) -> None:
        ml = MetaLearner()
        assert ml._sharpe_window == 50


# ── EnsembleRunner integration ────────────────────────────────────────────────


class TestEnsembleRunnerWeightIntegration:
    """Tests for record_trade_outcome / _drain_pending_outcomes / step wiring."""

    def _make_runner(self) -> "EnsembleRunner":  # type: ignore[name-defined]
        from agent.strategies.ensemble.run import EnsembleRunner  # noqa: PLC0415
        from agent.strategies.ensemble.config import EnsembleConfig  # noqa: PLC0415

        config = EnsembleConfig(
            enable_rl_signal=False,
            enable_evolved_signal=False,
            enable_regime_signal=False,
            enable_risk_overlay=False,
            symbols=["BTCUSDT"],
        )
        return EnsembleRunner(config=config, sdk_client=None, rest_client=None)

    def test_record_trade_outcome_appends_to_pending(self) -> None:
        runner = self._make_runner()
        assert len(runner._pending_outcomes) == 0
        runner.record_trade_outcome(source=SignalSource.RL, pnl_pct=0.02)
        assert len(runner._pending_outcomes) == 1
        assert runner._pending_outcomes[0].pnl_pct == pytest.approx(0.02)

    def test_record_trade_outcome_uses_last_regime(self) -> None:
        runner = self._make_runner()
        runner._last_regime = "trending"
        runner.record_trade_outcome(source=SignalSource.RL, pnl_pct=0.01)
        assert runner._pending_outcomes[0].regime == "trending"

    def test_record_trade_outcome_explicit_regime_overrides(self) -> None:
        runner = self._make_runner()
        runner._last_regime = "trending"
        runner.record_trade_outcome(
            source=SignalSource.EVOLVED, pnl_pct=-0.01, regime="mean_reverting"
        )
        assert runner._pending_outcomes[0].regime == "mean_reverting"

    def test_drain_clears_pending_outcomes(self) -> None:
        runner = self._make_runner()
        runner.record_trade_outcome(source=SignalSource.RL, pnl_pct=0.01)
        runner.record_trade_outcome(source=SignalSource.EVOLVED, pnl_pct=-0.01)
        drained = runner._drain_pending_outcomes()
        assert len(drained) == 2
        assert len(runner._pending_outcomes) == 0

    def test_drain_returns_empty_when_no_outcomes(self) -> None:
        runner = self._make_runner()
        result = runner._drain_pending_outcomes()
        assert result == []

    async def test_step_calls_update_weights_with_pending_outcomes(self) -> None:
        """step() should drain pending outcomes and pass them to MetaLearner."""
        runner = self._make_runner()

        # Wire a real MetaLearner so we can inspect it.
        ml = _make_learner()
        runner._meta_learner = ml

        # Record a pending outcome before calling step().
        runner.record_trade_outcome(source=SignalSource.RL, pnl_pct=0.05)

        # step() needs candles_by_symbol — provide empty dict (all sources disabled).
        await runner.step(candles_by_symbol={"BTCUSDT": []})

        # The outcome should have been consumed (drained).
        assert len(runner._pending_outcomes) == 0

        # MetaLearner should have the RL PnL in its history.
        history = ml.pnl_history[SignalSource.RL]
        assert len(history) == 1
        assert history[0] == pytest.approx(0.05)

    async def test_step_does_not_crash_when_update_weights_raises(self) -> None:
        """step() must be non-crashing even if update_weights() fails."""
        runner = self._make_runner()

        ml = MagicMock(spec=MetaLearner)
        ml.combine_all.return_value = []
        ml.update_weights.side_effect = RuntimeError("unexpected failure")
        runner._meta_learner = ml

        runner.record_trade_outcome(source=SignalSource.RL, pnl_pct=0.01)

        # Should not raise.
        result = await runner.step(candles_by_symbol={"BTCUSDT": []})
        assert result is not None

    async def test_step_skips_update_when_no_pending_outcomes(self) -> None:
        """When no outcomes are pending, update_weights must not be called."""
        runner = self._make_runner()

        ml = MagicMock(spec=MetaLearner)
        ml.combine_all.return_value = []
        runner._meta_learner = ml

        await runner.step(candles_by_symbol={"BTCUSDT": []})

        ml.update_weights.assert_not_called()

    async def test_step_updates_last_regime_from_detected_regime(self) -> None:
        """_last_regime is updated when the regime switcher returns a regime."""
        runner = self._make_runner()
        runner._config.enable_regime_signal = True  # type: ignore[attr-defined]

        # Use a real RegimeType enum so regime_to_signals() can call .value on it.
        from agent.strategies.regime.labeler import RegimeType  # noqa: PLC0415

        mock_switcher = MagicMock()
        mock_switcher.detect_regime.return_value = (RegimeType.TRENDING, 0.9)
        runner._regime_switcher = mock_switcher

        # Wire a real MetaLearner so combine_all works.
        ml = _make_learner()
        runner._meta_learner = ml

        candles = [{"close": 50000.0 + i} for i in range(100)]
        await runner.step(candles_by_symbol={"BTCUSDT": candles})

        assert runner._last_regime is RegimeType.TRENDING
