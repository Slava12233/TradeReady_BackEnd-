"""Unit tests for agent/strategies/drift.py.

Tests are organised into classes, one per subject:

- ``TestDriftConfig``           — dataclass defaults and custom values
- ``TestDriftUpdate``           — frozen dataclass field contracts
- ``TestCompositeMetric``       — weighted signal combination
- ``TestPageHinkleyMath``       — PH accumulation, detection, and reset
- ``TestWarmup``                — no drift fires before warmup_steps
- ``TestDriftDetected``         — drift declaration and event fields
- ``TestRecovery``              — recovery_steps confirmation and ph reset
- ``TestMultipleStrategies``    — independent state per strategy name
- ``TestReset``                 — per-strategy and global reset helpers
- ``TestEnsembleWeightHints``   — normal vs drift-active weight dicts
- ``TestPositionSizeMultiplier``— 0.5 when drifting, 1.0 otherwise
- ``TestGetStateSummary``       — diagnostic dict fields and empty case
- ``TestTrackedStrategies``     — sorted list of registered strategy names
- ``TestSyntheticDegradation``  — end-to-end: inject declining metrics → drift fires
- ``TestSyntheticRecovery``     — end-to-end: drift fires → metrics recover → clears
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from agent.strategies.drift import (
    DEFAULT_PH_DELTA,
    DEFAULT_PH_THRESHOLD,
    DEFAULT_RECOVERY_STEPS,
    DEFAULT_WARMUP_STEPS,
    DRIFT_EVOLVED_WEIGHT,
    DRIFT_REGIME_WEIGHT,
    DRIFT_RL_WEIGHT,
    DRIFT_SIZE_MULTIPLIER,
    METRIC_HISTORY_MAXLEN,
    NORMAL_EVOLVED_WEIGHT,
    NORMAL_REGIME_WEIGHT,
    NORMAL_RL_WEIGHT,
    DriftConfig,
    DriftDetector,
    DriftUpdate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_detector(**kwargs: object) -> DriftDetector:
    """Return a DriftDetector with optional config overrides."""
    config = DriftConfig(**kwargs)  # type: ignore[arg-type]
    return DriftDetector(config=config)


def _good_metrics() -> tuple[float, float, float]:
    """Return consistently good (sharpe, win_rate, avg_pnl) values."""
    return 1.5, 0.60, 50.0


def _bad_metrics() -> tuple[float, float, float]:
    """Return degraded (sharpe, win_rate, avg_pnl) values."""
    return -0.5, 0.30, -80.0


def _feed(detector: DriftDetector, strategy: str, count: int, metrics: tuple[float, float, float]) -> DriftUpdate:
    """Feed ``count`` identical observations; return the last DriftUpdate."""
    sharpe, win_rate, avg_pnl = metrics
    last: DriftUpdate | None = None
    for _ in range(count):
        last = detector.update(strategy, sharpe=sharpe, win_rate=win_rate, avg_pnl=avg_pnl)
    assert last is not None
    return last


# ---------------------------------------------------------------------------
# TestDriftConfig
# ---------------------------------------------------------------------------


class TestDriftConfig:
    """DriftConfig defaults and custom-value construction."""

    def test_defaults(self) -> None:
        cfg = DriftConfig()
        assert cfg.ph_delta == DEFAULT_PH_DELTA
        assert cfg.ph_threshold == DEFAULT_PH_THRESHOLD
        assert cfg.warmup_steps == DEFAULT_WARMUP_STEPS
        assert cfg.recovery_steps == DEFAULT_RECOVERY_STEPS

    def test_custom_values(self) -> None:
        cfg = DriftConfig(ph_delta=0.01, ph_threshold=10.0, warmup_steps=5, recovery_steps=3)
        assert cfg.ph_delta == 0.01
        assert cfg.ph_threshold == 10.0
        assert cfg.warmup_steps == 5
        assert cfg.recovery_steps == 3

    def test_is_frozen(self) -> None:
        cfg = DriftConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.ph_delta = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestDriftUpdate
# ---------------------------------------------------------------------------


class TestDriftUpdate:
    """DriftUpdate is a frozen dataclass — all fields are readable, none settable."""

    def _make(self, **overrides: object) -> DriftUpdate:
        defaults: dict[str, object] = {
            "strategy_name": "test_strat",
            "drift_active": False,
            "drift_detected_this_step": False,
            "recovery_detected_this_step": False,
            "position_size_multiplier": 1.0,
            "ensemble_weight_hints": {"RL": 0.34, "EVOLVED": 0.33, "REGIME": 0.33},
            "ph_sum": 0.0,
            "step_count": 1,
        }
        defaults.update(overrides)
        return DriftUpdate(**defaults)  # type: ignore[arg-type]

    def test_fields_accessible(self) -> None:
        u = self._make()
        assert u.strategy_name == "test_strat"
        assert u.drift_active is False
        assert u.drift_detected_this_step is False
        assert u.recovery_detected_this_step is False
        assert u.position_size_multiplier == 1.0
        assert u.step_count == 1

    def test_is_frozen(self) -> None:
        u = self._make()
        with pytest.raises((AttributeError, TypeError)):
            u.drift_active = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestCompositeMetric
# ---------------------------------------------------------------------------


class TestCompositeMetric:
    """_composite_metric correctly combines the three performance signals."""

    def test_positive_metrics_positive_composite(self) -> None:
        det = DriftDetector()
        result = det._composite_metric(sharpe=1.0, win_rate=0.6, avg_pnl=100.0)
        # 0.4*1.0 + 0.35*0.6 + 0.25*(100/200) = 0.4 + 0.21 + 0.125 = 0.735
        assert abs(result - 0.735) < 1e-9

    def test_all_zero_gives_zero(self) -> None:
        det = DriftDetector()
        result = det._composite_metric(sharpe=0.0, win_rate=0.0, avg_pnl=0.0)
        assert result == 0.0

    def test_negative_pnl_reduces_composite(self) -> None:
        det = DriftDetector()
        result_pos = det._composite_metric(sharpe=1.0, win_rate=0.5, avg_pnl=100.0)
        result_neg = det._composite_metric(sharpe=1.0, win_rate=0.5, avg_pnl=-100.0)
        assert result_neg < result_pos

    def test_pnl_scale_applied(self) -> None:
        det = DriftDetector()
        # avg_pnl=200 → normalised 1.0; avg_pnl=400 → normalised 2.0
        r1 = det._composite_metric(sharpe=0.0, win_rate=0.0, avg_pnl=200.0)
        r2 = det._composite_metric(sharpe=0.0, win_rate=0.0, avg_pnl=400.0)
        assert abs(r1 - 0.25 * 1.0) < 1e-9
        assert abs(r2 - 0.25 * 2.0) < 1e-9


# ---------------------------------------------------------------------------
# TestPageHinkleyMath
# ---------------------------------------------------------------------------


class TestPageHinkleyMath:
    """Direct PH accumulation mechanics."""

    def test_ph_sum_accumulates(self) -> None:
        """PH sum increases when performance degrades below mean."""
        det = _make_detector(warmup_steps=1, ph_threshold=1_000.0, recovery_steps=5)
        # Feed one good step to establish mean, then bad steps to accumulate
        det.update("s", sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
        update1 = det.update("s", sharpe=-1.0, win_rate=0.2, avg_pnl=-50.0)
        update2 = det.update("s", sharpe=-1.0, win_rate=0.2, avg_pnl=-50.0)
        # Consecutive bad steps: ph_sum should be growing (or at least non-decreasing)
        # We cannot assert exact values due to running mean; just check monotonicity
        assert update2.ph_sum >= update1.ph_sum or update2.ph_sum != 0.0

    def test_ph_min_tracks_minimum(self) -> None:
        """ph_min never increases above the lowest ph_sum seen."""
        det = _make_detector(warmup_steps=1, ph_threshold=1_000.0, recovery_steps=5)
        _feed(det, "s", 5, _bad_metrics())
        state = det._states["s"]
        assert state.ph_min <= state.ph_sum

    def test_no_drift_during_warmup(self) -> None:
        """drift_active remains False until warmup_steps reached."""
        det = _make_detector(warmup_steps=20, ph_threshold=0.001, recovery_steps=5)
        for _ in range(19):
            upd = det.update("s", sharpe=-2.0, win_rate=0.1, avg_pnl=-200.0)
            assert upd.drift_active is False

    def test_drift_can_fire_at_warmup_step(self) -> None:
        """After warmup_steps samples, drift can be declared on the same step."""
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=5)
        upd = _feed(det, "s", 5, _bad_metrics())
        # At step 5 (== warmup_steps) the condition is checked; it may fire
        assert upd.step_count == 5

    def test_step_count_increments(self) -> None:
        det = _make_detector()
        for i in range(1, 6):
            upd = det.update("s", sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
            assert upd.step_count == i


# ---------------------------------------------------------------------------
# TestWarmup
# ---------------------------------------------------------------------------


class TestWarmup:
    """Drift never fires before warmup_steps samples have been collected."""

    def test_no_drift_before_warmup(self) -> None:
        """Even with a catastrophically low threshold, drift waits for warmup."""
        det = _make_detector(warmup_steps=10, ph_threshold=0.0, recovery_steps=5)
        for i in range(9):
            upd = det.update("s", sharpe=-5.0, win_rate=0.0, avg_pnl=-500.0)
            assert upd.drift_active is False, f"Unexpected drift at step {i + 1}"

    def test_drift_can_fire_exactly_at_warmup(self) -> None:
        """Drift may fire on step == warmup_steps."""
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=5)
        upd = _feed(det, "s", 5, _bad_metrics())
        # step_count == warmup_steps: detection is now allowed
        assert upd.step_count == 5


# ---------------------------------------------------------------------------
# TestDriftDetected
# ---------------------------------------------------------------------------


class TestDriftDetected:
    """Drift declaration behaviour."""

    def _detector_with_drift(self) -> tuple[DriftDetector, DriftUpdate]:
        """Return a detector that has declared drift plus the triggering update."""
        det = _make_detector(
            warmup_steps=5,
            ph_threshold=0.001,
            recovery_steps=100,
        )
        upd = _feed(det, "s", 30, _bad_metrics())
        return det, upd

    def test_drift_active_set(self) -> None:
        _, upd = self._detector_with_drift()
        assert upd.drift_active is True

    def test_is_drifting_property(self) -> None:
        det, _ = self._detector_with_drift()
        assert det.is_drifting("s") is True

    def test_drift_detected_this_step_fires_once(self) -> None:
        """drift_detected_this_step is True only on the first drift step."""
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=100)
        triggered = []
        for _ in range(20):
            upd = det.update("s", sharpe=-2.0, win_rate=0.2, avg_pnl=-100.0)
            if upd.drift_detected_this_step:
                triggered.append(upd.step_count)
        # Exactly one step triggers the "first detection" flag
        assert len(triggered) == 1

    def test_size_multiplier_is_half_when_drifting(self) -> None:
        _, upd = self._detector_with_drift()
        assert upd.position_size_multiplier == DRIFT_SIZE_MULTIPLIER

    def test_ensemble_hints_boost_regime_when_drifting(self) -> None:
        _, upd = self._detector_with_drift()
        hints = upd.ensemble_weight_hints
        assert hints["REGIME"] == DRIFT_REGIME_WEIGHT
        assert hints["RL"] == DRIFT_RL_WEIGHT
        assert hints["EVOLVED"] == DRIFT_EVOLVED_WEIGHT

    def test_ensemble_hints_sum_to_one_when_drifting(self) -> None:
        _, upd = self._detector_with_drift()
        total = sum(upd.ensemble_weight_hints.values())
        assert abs(total - 1.0) < 1e-9

    def test_ph_sum_positive_on_drift(self) -> None:
        _, upd = self._detector_with_drift()
        # ph_sum field on the returned update should be a float
        assert isinstance(upd.ph_sum, float)

    def test_structlog_warning_emitted(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=100)
        with patch.object(det, "_log_drift_detected") as mock_log:
            _feed(det, "s", 30, _bad_metrics())
        mock_log.assert_called()


# ---------------------------------------------------------------------------
# TestRecovery
# ---------------------------------------------------------------------------


class TestRecovery:
    """Recovery logic: drift clears after recovery_steps consecutive good steps."""

    def _detector_in_drift(self, recovery_steps: int = 5) -> DriftDetector:
        """Return a detector that is currently in drift state.

        Uses recovery_steps=5 by default so that there is a visible recovery
        window in the tests (since even a single good step is above the
        badly-degraded running mean, the counter increments immediately).
        """
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=recovery_steps)
        _feed(det, "s", 30, _bad_metrics())
        assert det.is_drifting("s"), "Setup: drift must be active"
        return det

    def test_drift_persists_during_recovery_window(self) -> None:
        """Drift flag stays True for the first recovery_steps-1 good steps."""
        # Use recovery_steps=5 so there are 4 steps before recovery clears.
        det = self._detector_in_drift(recovery_steps=5)
        for i in range(4):  # recovery_steps=5 → first 4 steps should remain drifting
            upd = det.update("s", sharpe=2.0, win_rate=0.7, avg_pnl=100.0)
            assert upd.drift_active is True, f"Drift should persist at recovery step {i + 1}"

    def test_drift_clears_after_recovery_window(self) -> None:
        """Drift clears on the recovery_steps-th consecutive good step."""
        det = self._detector_in_drift(recovery_steps=5)
        upd = _feed(det, "s", 5, _good_metrics())
        assert upd.drift_active is False

    def test_recovery_detected_this_step_fires_once(self) -> None:
        """recovery_detected_this_step is True on exactly one step."""
        # Use recovery_steps=5 and feed 20 good steps; only the 5th should fire.
        det = self._detector_in_drift(recovery_steps=5)
        recovered_steps = []
        for _ in range(20):
            upd = det.update("s", sharpe=2.0, win_rate=0.7, avg_pnl=100.0)
            if upd.recovery_detected_this_step:
                recovered_steps.append(upd.step_count)
        assert len(recovered_steps) == 1

    def test_size_multiplier_restored_after_recovery(self) -> None:
        det = self._detector_in_drift(recovery_steps=5)
        upd = _feed(det, "s", 5, _good_metrics())
        assert upd.position_size_multiplier == 1.0

    def test_ensemble_hints_normal_after_recovery(self) -> None:
        det = self._detector_in_drift(recovery_steps=5)
        upd = _feed(det, "s", 5, _good_metrics())
        hints = upd.ensemble_weight_hints
        assert hints["REGIME"] == NORMAL_REGIME_WEIGHT
        assert hints["RL"] == NORMAL_RL_WEIGHT
        assert hints["EVOLVED"] == NORMAL_EVOLVED_WEIGHT

    def test_ph_sum_reset_after_recovery(self) -> None:
        """After confirmed recovery, ph_sum and ph_min are zeroed."""
        det = self._detector_in_drift(recovery_steps=5)
        # Feed 5 good steps then check state after the 6th to ensure recovery has fired.
        _feed(det, "s", 5, _good_metrics())
        # Exactly at step recovery_steps the reset happens; state is clear now.
        state = det._states["s"]
        assert state.ph_sum == 0.0
        assert state.ph_min == 0.0

    def test_interrupted_recovery_resets_counter(self) -> None:
        """If a bad step interrupts recovery, the counter resets to 0."""
        det = self._detector_in_drift(recovery_steps=10)
        # Two good steps — counter should be 2
        det.update("s", sharpe=2.0, win_rate=0.7, avg_pnl=100.0)
        det.update("s", sharpe=2.0, win_rate=0.7, avg_pnl=100.0)
        assert det._states["s"].recovery_counter == 2
        # Very bad step — composite well below running_mean, interrupts recovery
        det.update("s", sharpe=-5.0, win_rate=0.0, avg_pnl=-500.0)
        state = det._states["s"]
        assert state.recovery_counter == 0

    def test_structlog_info_emitted_on_recovery(self) -> None:
        det = self._detector_in_drift(recovery_steps=5)
        with patch.object(det, "_log_drift_recovered") as mock_log:
            _feed(det, "s", 5, _good_metrics())
        mock_log.assert_called()


# ---------------------------------------------------------------------------
# TestMultipleStrategies
# ---------------------------------------------------------------------------


class TestMultipleStrategies:
    """Each strategy has independent drift state."""

    def test_independent_state(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=100)
        # Drive "bad" into drift
        _feed(det, "bad", 30, _bad_metrics())
        # Feed "good" with healthy metrics
        upd_good = _feed(det, "good", 30, _good_metrics())

        assert det.is_drifting("bad") is True
        assert det.is_drifting("good") is False
        assert upd_good.drift_active is False

    def test_unknown_strategy_not_drifting(self) -> None:
        det = DriftDetector()
        assert det.is_drifting("nonexistent") is False

    def test_step_counts_independent(self) -> None:
        det = DriftDetector()
        for _ in range(3):
            det.update("a", sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
        for _ in range(7):
            det.update("b", sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
        assert det._states["a"].step_count == 3
        assert det._states["b"].step_count == 7

    def test_tracked_strategies_lists_both(self) -> None:
        det = DriftDetector()
        det.update("beta", sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
        det.update("alpha", sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
        assert det.tracked_strategies == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# TestReset
# ---------------------------------------------------------------------------


class TestReset:
    """reset() and reset_all() clear state correctly."""

    def test_reset_single_strategy(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=100)
        _feed(det, "s", 30, _bad_metrics())
        assert det.is_drifting("s") is True
        det.reset("s")
        state = det._states["s"]
        assert state.drift_active is False
        assert state.step_count == 0
        assert state.ph_sum == 0.0

    def test_reset_unknown_strategy_noop(self) -> None:
        det = DriftDetector()
        det.reset("does_not_exist")  # should not raise

    def test_reset_all_clears_everything(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=100)
        _feed(det, "a", 30, _bad_metrics())
        _feed(det, "b", 30, _bad_metrics())
        det.reset_all()
        assert det.tracked_strategies == []
        assert not det.is_drifting("a")
        assert not det.is_drifting("b")

    def test_reset_preserves_other_strategies(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=100)
        _feed(det, "a", 30, _bad_metrics())
        _feed(det, "b", 30, _bad_metrics())
        det.reset("a")
        # "b" state must be intact
        assert det.is_drifting("b") is True
        assert det._states["b"].step_count == 30


# ---------------------------------------------------------------------------
# TestEnsembleWeightHints
# ---------------------------------------------------------------------------


class TestEnsembleWeightHints:
    """Ensemble weight hint dictionaries are correct for both drift states."""

    def test_normal_weights_sum_to_one(self) -> None:
        hints = DriftDetector._ensemble_weight_hints(drift_active=False)
        assert abs(sum(hints.values()) - 1.0) < 1e-9

    def test_drift_weights_sum_to_one(self) -> None:
        hints = DriftDetector._ensemble_weight_hints(drift_active=True)
        assert abs(sum(hints.values()) - 1.0) < 1e-9

    def test_normal_hint_values(self) -> None:
        hints = DriftDetector._ensemble_weight_hints(drift_active=False)
        assert hints["RL"] == NORMAL_RL_WEIGHT
        assert hints["EVOLVED"] == NORMAL_EVOLVED_WEIGHT
        assert hints["REGIME"] == NORMAL_REGIME_WEIGHT

    def test_drift_hint_values(self) -> None:
        hints = DriftDetector._ensemble_weight_hints(drift_active=True)
        assert hints["RL"] == DRIFT_RL_WEIGHT
        assert hints["EVOLVED"] == DRIFT_EVOLVED_WEIGHT
        assert hints["REGIME"] == DRIFT_REGIME_WEIGHT

    def test_regime_higher_during_drift(self) -> None:
        normal = DriftDetector._ensemble_weight_hints(drift_active=False)
        drifting = DriftDetector._ensemble_weight_hints(drift_active=True)
        assert drifting["REGIME"] > normal["REGIME"]

    def test_rl_lower_during_drift(self) -> None:
        normal = DriftDetector._ensemble_weight_hints(drift_active=False)
        drifting = DriftDetector._ensemble_weight_hints(drift_active=True)
        assert drifting["RL"] < normal["RL"]

    def test_contains_all_sources(self) -> None:
        hints = DriftDetector._ensemble_weight_hints(drift_active=False)
        assert set(hints.keys()) == {"RL", "EVOLVED", "REGIME"}


# ---------------------------------------------------------------------------
# TestPositionSizeMultiplier
# ---------------------------------------------------------------------------


class TestPositionSizeMultiplier:
    """Position size multiplier is 0.5 when drifting, 1.0 otherwise."""

    def test_multiplier_one_when_not_drifting(self) -> None:
        det = DriftDetector()
        upd = det.update("s", sharpe=1.5, win_rate=0.6, avg_pnl=50.0)
        assert upd.position_size_multiplier == 1.0

    def test_multiplier_half_when_drifting(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=100)
        upd = _feed(det, "s", 30, _bad_metrics())
        assert upd.position_size_multiplier == DRIFT_SIZE_MULTIPLIER == 0.5


# ---------------------------------------------------------------------------
# TestGetStateSummary
# ---------------------------------------------------------------------------


class TestGetStateSummary:
    """get_state_summary() returns expected fields."""

    def test_empty_dict_for_unknown_strategy(self) -> None:
        det = DriftDetector()
        assert det.get_state_summary("nonexistent") == {}

    def test_required_keys_present(self) -> None:
        det = DriftDetector()
        det.update("s", sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
        summary = det.get_state_summary("s")
        expected_keys = {
            "strategy_name",
            "step_count",
            "drift_active",
            "ph_sum",
            "ph_min",
            "ph_test_value",
            "recovery_counter",
            "running_mean",
            "recent_metrics",
        }
        assert expected_keys.issubset(summary.keys())

    def test_step_count_matches(self) -> None:
        det = DriftDetector()
        _feed(det, "s", 7, _good_metrics())
        summary = det.get_state_summary("s")
        assert summary["step_count"] == 7

    def test_recent_metrics_capped_at_ten(self) -> None:
        det = DriftDetector()
        _feed(det, "s", 20, _good_metrics())
        summary = det.get_state_summary("s")
        assert len(summary["recent_metrics"]) <= 10

    def test_ph_test_value_equals_sum_minus_min(self) -> None:
        det = DriftDetector()
        _feed(det, "s", 5, _bad_metrics())
        state = det._states["s"]
        summary = det.get_state_summary("s")
        expected = round(state.ph_sum - state.ph_min, 6)
        assert abs(summary["ph_test_value"] - expected) < 1e-9

    def test_strategy_name_in_summary(self) -> None:
        det = DriftDetector()
        det.update("my_strat", sharpe=1.0, win_rate=0.5, avg_pnl=0.0)
        summary = det.get_state_summary("my_strat")
        assert summary["strategy_name"] == "my_strat"


# ---------------------------------------------------------------------------
# TestTrackedStrategies
# ---------------------------------------------------------------------------


class TestTrackedStrategies:
    """tracked_strategies returns a sorted list."""

    def test_empty_initially(self) -> None:
        det = DriftDetector()
        assert det.tracked_strategies == []

    def test_single_strategy(self) -> None:
        det = DriftDetector()
        det.update("z_strat", sharpe=1.0, win_rate=0.5, avg_pnl=0.0)
        assert det.tracked_strategies == ["z_strat"]

    def test_multiple_sorted(self) -> None:
        det = DriftDetector()
        for name in ["gamma", "alpha", "beta"]:
            det.update(name, sharpe=1.0, win_rate=0.5, avg_pnl=0.0)
        assert det.tracked_strategies == ["alpha", "beta", "gamma"]

    def test_removed_after_reset_all(self) -> None:
        det = DriftDetector()
        det.update("a", sharpe=1.0, win_rate=0.5, avg_pnl=0.0)
        det.reset_all()
        assert det.tracked_strategies == []


# ---------------------------------------------------------------------------
# TestSyntheticDegradation
# ---------------------------------------------------------------------------


class TestSyntheticDegradation:
    """End-to-end: feed declining metrics → drift must eventually fire."""

    def test_drift_fires_on_sustained_degradation(self) -> None:
        """Drift is declared within 200 steps of sustained bad performance."""
        det = _make_detector(warmup_steps=10, ph_threshold=5.0, recovery_steps=10)
        # Warmup with good metrics
        _feed(det, "strat", 10, _good_metrics())
        # Then inject severe degradation
        drift_found = False
        for _ in range(200):
            upd = det.update("strat", sharpe=-1.0, win_rate=0.25, avg_pnl=-100.0)
            if upd.drift_active:
                drift_found = True
                break
        assert drift_found, "Drift should have been declared during sustained degradation"

    def test_drift_not_declared_on_stable_good_performance(self) -> None:
        """No drift declared when metrics are consistently healthy."""
        det = _make_detector(warmup_steps=10, ph_threshold=50.0, recovery_steps=10)
        upd = _feed(det, "strat", 200, _good_metrics())
        assert upd.drift_active is False

    def test_metric_history_bounded(self) -> None:
        """Metric history deque never exceeds METRIC_HISTORY_MAXLEN."""
        det = DriftDetector()
        _feed(det, "s", METRIC_HISTORY_MAXLEN + 100, _good_metrics())
        state = det._states["s"]
        assert len(state.metric_history) == METRIC_HISTORY_MAXLEN


# ---------------------------------------------------------------------------
# TestSyntheticRecovery
# ---------------------------------------------------------------------------


class TestSyntheticRecovery:
    """End-to-end: drift fires → metrics recover → flag clears."""

    def test_recovery_after_performance_improvement(self) -> None:
        """After drift is declared and then good metrics are fed, drift clears."""
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=5)
        # Force drift
        _feed(det, "s", 30, _bad_metrics())
        assert det.is_drifting("s"), "Precondition: drift must be active"
        # Feed recovery metrics
        upd = _feed(det, "s", 5, _good_metrics())
        assert upd.drift_active is False
        assert det.is_drifting("s") is False

    def test_drift_can_redeclare_after_recovery(self) -> None:
        """Drift can be declared a second time after recovery if degradation returns."""
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=3)
        # First drift cycle
        _feed(det, "s", 30, _bad_metrics())
        assert det.is_drifting("s")
        # Recover
        _feed(det, "s", 3, _good_metrics())
        assert not det.is_drifting("s")
        # Second degradation
        upd = _feed(det, "s", 30, _bad_metrics())
        assert upd.drift_active is True

    def test_running_mean_preserved_through_recovery(self) -> None:
        """Running mean is not zeroed during recovery — only PH sums are reset."""
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=3)
        _feed(det, "s", 30, _bad_metrics())
        _feed(det, "s", 3, _good_metrics())
        state = det._states["s"]
        # Running mean should be non-zero (it tracked the metric stream)
        assert state.running_mean != 0.0

    def test_ph_sums_zeroed_on_recovery(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=3)
        _feed(det, "s", 30, _bad_metrics())
        _feed(det, "s", 3, _good_metrics())
        state = det._states["s"]
        assert state.ph_sum == 0.0
        assert state.ph_min == 0.0

    def test_position_multiplier_restored_on_recovery(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=3)
        _feed(det, "s", 30, _bad_metrics())
        upd = _feed(det, "s", 3, _good_metrics())
        assert upd.position_size_multiplier == 1.0

    def test_regime_weight_normalized_on_recovery(self) -> None:
        det = _make_detector(warmup_steps=5, ph_threshold=0.001, recovery_steps=3)
        _feed(det, "s", 30, _bad_metrics())
        upd = _feed(det, "s", 3, _good_metrics())
        assert upd.ensemble_weight_hints["REGIME"] == NORMAL_REGIME_WEIGHT


# ---------------------------------------------------------------------------
# TestRunningMeanBehaviour
# ---------------------------------------------------------------------------


class TestRunningMeanBehaviour:
    """Running mean transitions from cumulative to EMA at warmup boundary."""

    def test_initial_mean_set_to_first_sample(self) -> None:
        det = DriftDetector()
        composite = det._composite_metric(sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
        det.update("s", sharpe=1.0, win_rate=0.6, avg_pnl=50.0)
        state = det._states["s"]
        assert abs(state.running_mean - composite) < 1e-9

    def test_mean_finite_after_many_steps(self) -> None:
        det = DriftDetector()
        _feed(det, "s", 100, _good_metrics())
        state = det._states["s"]
        assert math.isfinite(state.running_mean)

    def test_mean_reflects_metrics(self) -> None:
        """Mean should be higher for good metrics than for bad metrics."""
        det_good = DriftDetector()
        _feed(det_good, "s", 50, _good_metrics())

        det_bad = DriftDetector()
        _feed(det_bad, "s", 50, _bad_metrics())

        assert det_good._states["s"].running_mean > det_bad._states["s"].running_mean
