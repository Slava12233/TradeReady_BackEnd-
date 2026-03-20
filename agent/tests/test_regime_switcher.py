"""Targeted switcher tests for agent/strategies/regime/switcher.py.

These tests complement test_regime.py with focused behavioral tests:

- Cooldown blocks a second switch within 5 candles (counting from 0)
- Low confidence (< 0.7) always prevents switching
- Confidence exactly at threshold (0.7) is accepted
- High confidence (>= 0.7) after cooldown expires triggers a switch
- Regime history correctly tracks all switches including candle_index
- Active strategy always matches current regime
- RegimeSwitcher.reset() restores cooldown to _cooldown_candles
  (noting that reset() hard-codes MEAN_REVERTING regardless of initial_regime)
- _make_synthetic_candles generates four-segment data
- Strategy definitions module (STRATEGY_BY_REGIME, create_regime_strategies)

Nothing here duplicates the exhaustive tests already in test_regime.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from agent.strategies.regime.labeler import RegimeType
from agent.strategies.regime.switcher import (
    CONFIDENCE_THRESHOLD,
    MIN_CANDLES_REQUIRED,
    SWITCH_COOLDOWN_CANDLES,
    RegimeRecord,
    RegimeSwitcher,
    _make_synthetic_candles,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_classifier(regime: RegimeType, confidence: float) -> MagicMock:
    clf = MagicMock(spec=["predict"])
    clf.predict.return_value = (regime, confidence)
    return clf


def _default_strategy_map() -> dict[RegimeType, str]:
    return {
        RegimeType.TRENDING: "sid-trending",
        RegimeType.MEAN_REVERTING: "sid-mean-reverting",
        RegimeType.HIGH_VOLATILITY: "sid-high-vol",
        RegimeType.LOW_VOLATILITY: "sid-low-vol",
    }


def _large_candles(n: int = 200, seed: int = 0) -> list[dict]:
    """Return candles with enough history for feature extraction."""
    rng = np.random.default_rng(seed)
    candles = []
    close = 50000.0
    for _ in range(n):
        close = max(close + float(rng.normal(0, 50.0)), 1.0)
        candles.append(
            {
                "open": close,
                "high": close + abs(float(rng.normal(0, 25.0))),
                "low": close - abs(float(rng.normal(0, 25.0))),
                "close": close,
                "volume": float(rng.integers(500, 5000)),
            }
        )
    return candles


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestSwitcherConstants:
    """Verify published constant values match the acceptance criteria."""

    def test_confidence_threshold_is_0_7(self) -> None:
        assert CONFIDENCE_THRESHOLD == 0.7

    def test_cooldown_is_5_candles(self) -> None:
        assert SWITCH_COOLDOWN_CANDLES == 5

    def test_min_candles_required_is_50(self) -> None:
        assert MIN_CANDLES_REQUIRED == 50


# ---------------------------------------------------------------------------
# Cooldown guard
# ---------------------------------------------------------------------------


class TestCooldownGuard:
    """Cooldown prevents a second switch within SWITCH_COOLDOWN_CANDLES candles."""

    def test_cooldown_blocks_switch_at_zero_candles_since_switch(self) -> None:
        """Immediately after a switch (candles_since_switch == 0) no switch is allowed."""
        clf = _make_mock_classifier(RegimeType.HIGH_VOLATILITY, 0.99)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()

        # Trigger the first switch.
        _, _, switched = sw.step(candles)
        assert switched is True
        assert sw.candles_since_switch == 0

        # Change the prediction and step again — cooldown is 0 < 5, block.
        clf.predict.return_value = (RegimeType.TRENDING, 0.99)
        _, _, switched2 = sw.step(candles)
        assert switched2 is False, "Switch should be blocked immediately after a prior switch"
        assert sw.candles_since_switch == 1

    def test_cooldown_counts_candles_incrementally(self) -> None:
        """candles_since_switch increments by 1 each step while in cooldown."""
        clf = _make_mock_classifier(RegimeType.HIGH_VOLATILITY, 0.99)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=5,
        )
        candles = _large_candles()

        # First switch.
        sw.step(candles)
        assert sw.candles_since_switch == 0

        clf.predict.return_value = (RegimeType.TRENDING, 0.99)
        for expected_count in range(1, 5):
            sw.step(candles)
            assert sw.candles_since_switch == expected_count, (
                f"Expected candles_since_switch == {expected_count}, "
                f"got {sw.candles_since_switch}"
            )

    def test_cooldown_expiry_allows_switch_on_fifth_step(self) -> None:
        """After exactly cooldown_candles steps the switch is permitted."""
        clf = _make_mock_classifier(RegimeType.HIGH_VOLATILITY, 0.99)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=5,
        )
        candles = _large_candles()

        # First switch.
        sw.step(candles)

        # Change prediction — now in HIGH_VOLATILITY, want to switch to TRENDING.
        clf.predict.return_value = (RegimeType.TRENDING, 0.99)

        # Steps 2–5 are within cooldown (candles_since_switch 1–4).
        for _ in range(4):
            _, _, blocked = sw.step(candles)
            assert blocked is False

        # Step 6: candles_since_switch reaches 5 == cooldown_candles → switch allowed.
        _, _, switched = sw.step(candles)
        assert switched is True, "Switch should be allowed once cooldown_candles steps have elapsed"

    def test_initial_cooldown_counter_permits_immediate_switch(self) -> None:
        """On the very first call, candles_since_switch starts at cooldown_candles.

        This means a switch is possible on the first step without any warmup.
        """
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.99)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=5,
        )
        assert sw.candles_since_switch == 5

        candles = _large_candles()
        _, _, switched = sw.step(candles)
        assert switched is True, "First step should be able to switch immediately"


# ---------------------------------------------------------------------------
# Confidence threshold guard
# ---------------------------------------------------------------------------


class TestConfidenceThreshold:
    """Low confidence prevents switching; confidence at or above threshold allows it."""

    def test_confidence_below_threshold_blocks_switch(self) -> None:
        """Confidence strictly below 0.7 must never trigger a switch."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.69)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        _, _, switched = sw.step(candles)
        assert switched is False
        assert sw.current_regime == RegimeType.MEAN_REVERTING

    def test_confidence_exactly_at_threshold_allows_switch(self) -> None:
        """Confidence == 0.7 must be accepted (boundary condition)."""
        clf = _make_mock_classifier(RegimeType.TRENDING, CONFIDENCE_THRESHOLD)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        _, _, switched = sw.step(candles)
        assert switched is True, "Confidence exactly at threshold should permit a switch"

    def test_confidence_above_threshold_allows_switch(self) -> None:
        """Any confidence > 0.7 with cooldown satisfied triggers a switch."""
        for conf in (0.71, 0.80, 0.95, 1.0):
            clf = _make_mock_classifier(RegimeType.TRENDING, conf)
            sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
            candles = _large_candles()
            _, _, switched = sw.step(candles)
            assert switched is True, f"Switch should occur with confidence={conf}"

    def test_zero_confidence_always_blocks(self) -> None:
        """Confidence of 0.0 is always rejected."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.0)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        _, _, switched = sw.step(candles)
        assert switched is False

    def test_custom_confidence_threshold_is_respected(self) -> None:
        """A custom threshold overrides the module default."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.85)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            confidence_threshold=0.90,
        )
        candles = _large_candles()
        # 0.85 < 0.90 → blocked.
        _, _, switched = sw.step(candles)
        assert switched is False

        clf.predict.return_value = (RegimeType.TRENDING, 0.90)
        sw2 = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            confidence_threshold=0.90,
        )
        _, _, switched2 = sw2.step(candles)
        assert switched2 is True


# ---------------------------------------------------------------------------
# High confidence after cooldown triggers switch
# ---------------------------------------------------------------------------


class TestHighConfidenceAfterCooldown:
    """Verify the combined condition: high confidence + cooldown expired = switch."""

    def test_high_confidence_after_cooldown_triggers_switch(self) -> None:
        """After cooldown expires, a high-confidence prediction causes a switch."""
        clf = _make_mock_classifier(RegimeType.HIGH_VOLATILITY, 0.92)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=3,
        )
        candles = _large_candles()

        # First switch: MEAN_REVERTING → HIGH_VOLATILITY.
        _, _, s1 = sw.step(candles)
        assert s1 is True

        # Cooldown steps.
        clf.predict.return_value = (RegimeType.TRENDING, 0.95)
        _, _, s2 = sw.step(candles)
        _, _, s3 = sw.step(candles)
        assert not s2 and not s3

        # Cooldown expired: HIGH_VOLATILITY → TRENDING.
        _, _, s4 = sw.step(candles)
        assert s4 is True
        assert sw.current_regime == RegimeType.TRENDING

    def test_switch_updates_current_regime_and_strategy(self) -> None:
        """After a switch, current_regime and get_active_strategy() are updated."""
        clf = _make_mock_classifier(RegimeType.HIGH_VOLATILITY, 0.95)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        sw.step(candles)

        assert sw.current_regime == RegimeType.HIGH_VOLATILITY
        assert sw.get_active_strategy() == _default_strategy_map()[RegimeType.HIGH_VOLATILITY]


# ---------------------------------------------------------------------------
# Regime history tracking
# ---------------------------------------------------------------------------


class TestRegimeHistoryTracking:
    """Regime history accurately records all switches."""

    def test_no_switch_produces_no_history(self) -> None:
        # Classifier returns same regime as initial → no switch → empty history.
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.99)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        sw.step(candles)
        assert len(sw.regime_history) == 0

    def test_single_switch_produces_one_history_entry(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.88)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        sw.step(candles)
        assert len(sw.regime_history) == 1

    def test_history_entry_fields_are_correct(self) -> None:
        """Each history entry has regime, confidence, strategy_id, and candle_index."""
        clf = _make_mock_classifier(RegimeType.HIGH_VOLATILITY, 0.91)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        sw.step(candles)

        record = sw.regime_history[0]
        assert isinstance(record, RegimeRecord)
        assert record.regime == RegimeType.HIGH_VOLATILITY
        assert record.confidence == 0.91
        assert record.strategy_id == _default_strategy_map()[RegimeType.HIGH_VOLATILITY]
        assert record.candle_index == 1  # first step increments to 1

    def test_history_candle_index_increments_correctly(self) -> None:
        """candle_index in history entries reflects the step count at time of switch."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.95)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=1,
        )
        candles = _large_candles()

        sw.step(candles)  # step 1 → switch
        assert sw.regime_history[0].candle_index == 1

        clf.predict.return_value = (RegimeType.HIGH_VOLATILITY, 0.95)
        sw.step(candles)  # step 2 → switch (cooldown=1 → candles_since_switch becomes 1 ≥ 1)
        assert sw.regime_history[1].candle_index == 2

    def test_history_accumulates_across_multiple_switches(self) -> None:
        """Each qualifying switch appends exactly one entry."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.88)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=1,
        )
        candles = _large_candles()

        regimes_sequence = [
            RegimeType.TRENDING,
            RegimeType.HIGH_VOLATILITY,
            RegimeType.LOW_VOLATILITY,
        ]
        for i, regime in enumerate(regimes_sequence):
            clf.predict.return_value = (regime, 0.90)
            sw.step(candles)
            assert len(sw.regime_history) == i + 1

    def test_history_timestamp_is_utc_aware(self) -> None:
        """Timestamps in history entries are timezone-aware UTC datetimes."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.88)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        sw.step(candles)
        record = sw.regime_history[0]
        assert record.timestamp.tzinfo is not None

    def test_history_regime_record_is_frozen(self) -> None:
        """RegimeRecord instances in history cannot be mutated."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.88)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        sw.step(candles)
        record = sw.regime_history[0]
        with pytest.raises((AttributeError, TypeError)):
            record.regime = RegimeType.MEAN_REVERTING  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Active strategy matches current regime
# ---------------------------------------------------------------------------


class TestActiveStrategyMatchesRegime:
    """get_active_strategy() always reflects the current regime."""

    def test_active_strategy_matches_initial_regime(self) -> None:
        for regime in RegimeType:
            clf = _make_mock_classifier(regime, 0.0)  # low conf → no switch
            sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=regime)
            assert sw.get_active_strategy() == _default_strategy_map()[regime]

    def test_active_strategy_updates_after_switch(self) -> None:
        clf = _make_mock_classifier(RegimeType.HIGH_VOLATILITY, 0.95)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        sw.step(candles)
        assert sw.get_active_strategy() == _default_strategy_map()[RegimeType.HIGH_VOLATILITY]

    def test_active_strategy_correct_after_multiple_switches(self) -> None:
        """After several switches the active strategy always matches current_regime."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.90)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=1,
        )
        candles = _large_candles()

        for regime in [RegimeType.TRENDING, RegimeType.HIGH_VOLATILITY, RegimeType.LOW_VOLATILITY]:
            clf.predict.return_value = (regime, 0.90)
            sw.step(candles)
            assert sw.get_active_strategy() == _default_strategy_map()[sw.current_regime]

    def test_get_active_strategy_raises_on_missing_key(self) -> None:
        """KeyError if current_regime is not in strategy_map."""
        clf = _make_mock_classifier(RegimeType.LOW_VOLATILITY, 0.99)
        # Map is missing LOW_VOLATILITY.
        incomplete_map = {
            RegimeType.TRENDING: "sid-t",
            RegimeType.MEAN_REVERTING: "sid-mr",
            RegimeType.HIGH_VOLATILITY: "sid-hv",
        }
        sw = RegimeSwitcher(clf, incomplete_map, initial_regime=RegimeType.LOW_VOLATILITY)
        with pytest.raises(KeyError):
            sw.get_active_strategy()


# ---------------------------------------------------------------------------
# reset() behaviour
# ---------------------------------------------------------------------------


class TestReset:
    """reset() restores runtime state but preserves classifier and strategy_map."""

    def test_reset_restores_cooldown_to_cooldown_candles(self) -> None:
        """candles_since_switch is restored to _cooldown_candles after reset."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.90)
        sw = RegimeSwitcher(clf, _default_strategy_map(), cooldown_candles=7)
        candles = _large_candles()
        sw.step(candles)  # switch → candles_since_switch = 0
        sw.reset()
        assert sw.candles_since_switch == 7

    def test_reset_clears_history(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.90)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()
        sw.step(candles)
        assert len(sw.regime_history) == 1
        sw.reset()
        assert len(sw.regime_history) == 0

    def test_reset_sets_regime_to_mean_reverting(self) -> None:
        """reset() always restores current_regime to MEAN_REVERTING (hardcoded).

        Note: even if initial_regime was set to something else,
        reset() restores MEAN_REVERTING (current implementation behaviour).
        """
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.90)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.HIGH_VOLATILITY,
        )
        candles = _large_candles()
        sw.step(candles)
        sw.reset()
        assert sw.current_regime == RegimeType.MEAN_REVERTING

    def test_reset_clears_total_candles_processed(self) -> None:
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.5)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        short = [{"close": float(i + 1)} for i in range(5)]  # below MIN_CANDLES_REQUIRED
        for _ in range(3):
            sw.step(short)
        assert sw._total_candles_processed == 3
        sw.reset()
        assert sw._total_candles_processed == 0

    def test_reset_allows_immediate_switch_again(self) -> None:
        """After reset, the first step can trigger a switch (cooldown satisfied)."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.90)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles()

        sw.step(candles)   # switch 1
        sw.reset()         # back to MEAN_REVERTING

        clf.predict.return_value = (RegimeType.HIGH_VOLATILITY, 0.95)
        _, _, switched = sw.step(candles)
        assert switched is True, "After reset, first step should be able to switch"


# ---------------------------------------------------------------------------
# _make_synthetic_candles (CLI demo helper)
# ---------------------------------------------------------------------------


class TestMakeSyntheticCandles:
    """Tests for the CLI demo helper in switcher.py."""

    def test_returns_correct_number_of_candles(self) -> None:
        candles = _make_synthetic_candles(n=200, seed=1)
        assert len(candles) == 200

    def test_each_candle_has_required_ohlcv_keys(self) -> None:
        candles = _make_synthetic_candles(n=50, seed=2)
        for c in candles:
            for key in ("open", "high", "low", "close", "volume"):
                assert key in c, f"Missing key '{key}' in candle {c}"

    def test_high_is_at_least_close(self) -> None:
        """High should always be >= close (synthetic candles guarantee this)."""
        candles = _make_synthetic_candles(n=100, seed=3)
        for c in candles:
            assert c["high"] >= c["close"], f"high < close in candle {c}"

    def test_low_is_at_most_close(self) -> None:
        """Low should always be <= close."""
        candles = _make_synthetic_candles(n=100, seed=4)
        for c in candles:
            assert c["low"] <= c["close"], f"low > close in candle {c}"

    def test_different_seeds_produce_different_candles(self) -> None:
        c1 = _make_synthetic_candles(n=50, seed=10)
        c2 = _make_synthetic_candles(n=50, seed=99)
        closes1 = [c["close"] for c in c1]
        closes2 = [c["close"] for c in c2]
        assert closes1 != closes2, "Different seeds should produce different candles"

    def test_same_seed_is_deterministic(self) -> None:
        c1 = _make_synthetic_candles(n=50, seed=42)
        c2 = _make_synthetic_candles(n=50, seed=42)
        assert [c["close"] for c in c1] == [c["close"] for c in c2]


# ---------------------------------------------------------------------------
# strategy_definitions module
# ---------------------------------------------------------------------------


class TestStrategyDefinitions:
    """Tests for agent/strategies/regime/strategy_definitions.py."""

    def test_strategy_by_regime_covers_all_four_types(self) -> None:
        from agent.strategies.regime.strategy_definitions import STRATEGY_BY_REGIME

        assert set(STRATEGY_BY_REGIME.keys()) == set(RegimeType)

    def test_each_strategy_has_required_keys(self) -> None:
        from agent.strategies.regime.strategy_definitions import STRATEGY_BY_REGIME

        required_keys = {"pairs", "timeframe", "entry_conditions", "exit_conditions",
                         "position_size_pct", "max_positions", "model_type"}
        for regime, defn in STRATEGY_BY_REGIME.items():
            missing = required_keys - set(defn.keys())
            assert not missing, (
                f"Strategy for {regime.value} is missing keys: {missing}"
            )

    def test_all_strategies_use_1h_timeframe(self) -> None:
        from agent.strategies.regime.strategy_definitions import STRATEGY_BY_REGIME

        for regime, defn in STRATEGY_BY_REGIME.items():
            assert defn["timeframe"] == "1h", (
                f"Strategy for {regime.value} should use 1h timeframe"
            )

    def test_high_volatility_strategy_has_tightest_stop_loss(self) -> None:
        """HIGH_VOLATILITY strategy must have the smallest stop_loss_pct (capital preservation)."""
        from agent.strategies.regime.strategy_definitions import STRATEGY_BY_REGIME

        hv_stop = STRATEGY_BY_REGIME[RegimeType.HIGH_VOLATILITY]["exit_conditions"]["stop_loss_pct"]
        for regime, defn in STRATEGY_BY_REGIME.items():
            if regime == RegimeType.HIGH_VOLATILITY:
                continue
            other_stop = defn["exit_conditions"]["stop_loss_pct"]
            assert hv_stop <= other_stop, (
                f"HIGH_VOLATILITY stop_loss_pct ({hv_stop}) should be <= "
                f"{regime.value} ({other_stop})"
            )

    def test_low_volatility_strategy_has_largest_position_size(self) -> None:
        """LOW_VOLATILITY strategy should have the largest position_size_pct."""
        from agent.strategies.regime.strategy_definitions import STRATEGY_BY_REGIME

        lv_size = STRATEGY_BY_REGIME[RegimeType.LOW_VOLATILITY]["position_size_pct"]
        for regime, defn in STRATEGY_BY_REGIME.items():
            if regime == RegimeType.LOW_VOLATILITY:
                continue
            assert lv_size >= defn["position_size_pct"], (
                f"LOW_VOLATILITY position_size_pct ({lv_size}) should be >= "
                f"{regime.value} ({defn['position_size_pct']})"
            )

    def test_create_regime_strategies_returns_all_four_ids(self) -> None:
        """create_regime_strategies calls create_strategy once per regime and
        returns all four strategy IDs."""
        from agent.strategies.regime.strategy_definitions import create_regime_strategies

        mock_client = AsyncMock()
        call_count = 0

        async def mock_create(name: str, description: str, definition: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return {"strategy_id": f"sid-{call_count}"}

        mock_client.create_strategy.side_effect = mock_create

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            create_regime_strategies(mock_client, agent_id="agent-123")
        )

        assert len(result) == 4
        assert set(result.keys()) == set(RegimeType)
        assert all(isinstance(v, str) for v in result.values())
        assert mock_client.create_strategy.call_count == 4

    def test_create_regime_strategies_raises_on_api_error(self) -> None:
        """create_regime_strategies raises RuntimeError if response contains 'error'."""
        from agent.strategies.regime.strategy_definitions import create_regime_strategies

        mock_client = AsyncMock()
        mock_client.create_strategy.return_value = {"error": "unauthorized"}

        import asyncio
        with pytest.raises(RuntimeError, match="rejected"):
            asyncio.get_event_loop().run_until_complete(
                create_regime_strategies(mock_client, agent_id="agent-456")
            )

    def test_create_regime_strategies_raises_on_missing_strategy_id(self) -> None:
        """create_regime_strategies raises RuntimeError if strategy_id is absent."""
        from agent.strategies.regime.strategy_definitions import create_regime_strategies

        mock_client = AsyncMock()
        mock_client.create_strategy.return_value = {"name": "some_strategy"}  # no strategy_id

        import asyncio
        with pytest.raises(RuntimeError, match="strategy_id"):
            asyncio.get_event_loop().run_until_complete(
                create_regime_strategies(mock_client, agent_id="agent-789")
            )

    def test_create_regime_strategies_raises_on_exception(self) -> None:
        """create_regime_strategies wraps underlying exceptions as RuntimeError."""
        from agent.strategies.regime.strategy_definitions import create_regime_strategies

        mock_client = AsyncMock()
        mock_client.create_strategy.side_effect = ConnectionError("network failure")

        import asyncio
        with pytest.raises(RuntimeError, match="Failed to create strategy"):
            asyncio.get_event_loop().run_until_complete(
                create_regime_strategies(mock_client, agent_id="agent-000")
            )
