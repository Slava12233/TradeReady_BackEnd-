"""Unit tests for agent/strategies/ensemble/optimize_weights.py.

Tests cover:
- _sma() helper: returns correct SMA, returns None on insufficient data
- _ma_signal() helper: buy/sell/hold from SMA crossover
- _extract_closes() helper: parses candle dicts, ignores bad values
- _safe_float() helper: converts values, returns default on failure
- _generate_weight_configs(): 12 configs, 4 fixed + 8 random; reproducible seed
- _normalise_weights(): sums to 1.0, handles zero-sum with equal fallback
- _build_comparison_table(): Markdown header present, one row per result
- WeightConfig: frozen, name/description/weights validation
- ConfigResult: serialisable with all fields
- OptimizationResult: frozen, comparison_table always present
- save_optimal_weights_json(): writes valid JSON; raises on bad keys/negative values
- load_optimal_weights(): round-trips with save; raises FileNotFoundError; raises ValueError
- apply_optimal_weights(): returns new EnsembleConfig with updated weights
- validate_ensemble_beats_baseline(): passes when optimal > baseline, fails when not
- WeightOptimizer.rank_results(): sorted by Sharpe desc; None Sharpe goes last
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.strategies.ensemble.config import EnsembleConfig
from agent.strategies.ensemble.optimize_weights import (
    ConfigResult,
    OptimizationResult,
    WeightConfig,
    WeightOptimizer,
    _build_comparison_table,
    _extract_closes,
    _generate_weight_configs,
    _ma_signal,
    _normalise_weights,
    _safe_float,
    _sma,
    apply_optimal_weights,
    load_optimal_weights,
    save_optimal_weights_json,
    validate_ensemble_beats_baseline,
)
from agent.strategies.ensemble.signals import SignalSource


# ── _sma() ────────────────────────────────────────────────────────────────────


class TestSma:
    """_sma() computes simple moving average over the last *window* elements."""

    def test_exact_window(self) -> None:
        closes = [10.0, 20.0, 30.0]
        assert _sma(closes, 3) == pytest.approx(20.0)

    def test_more_than_window(self) -> None:
        # Only last 2 elements are used: [30.0, 40.0] → avg 35.0
        closes = [10.0, 20.0, 30.0, 40.0]
        assert _sma(closes, 2) == pytest.approx(35.0)

    def test_insufficient_data_returns_none(self) -> None:
        assert _sma([1.0, 2.0], 5) is None

    def test_single_element_window(self) -> None:
        assert _sma([42.0, 99.0], 1) == pytest.approx(99.0)

    def test_empty_list_returns_none(self) -> None:
        assert _sma([], 3) is None


# ── _ma_signal() ──────────────────────────────────────────────────────────────


class TestMaSignal:
    """_ma_signal() returns buy/sell/hold based on fast vs slow SMA crossover."""

    def _build_closes(self, n: int = 25) -> list[float]:
        """Build a close-price list with enough values for a window-20 SMA."""
        return list(range(1, n + 1))  # monotonically increasing

    def test_buy_when_fast_above_slow(self) -> None:
        # Monotonically increasing series: fast SMA > slow SMA
        closes = self._build_closes(25)
        assert _ma_signal(closes) == "buy"

    def test_sell_when_fast_below_slow(self) -> None:
        # Monotonically decreasing series: fast SMA < slow SMA
        closes = list(range(25, 0, -1))
        assert _ma_signal(closes) == "sell"

    def test_hold_when_insufficient_data(self) -> None:
        # Only 10 elements — cannot compute slow SMA (window 20)
        assert _ma_signal(list(range(10))) == "hold"

    def test_hold_when_empty(self) -> None:
        assert _ma_signal([]) == "hold"


# ── _extract_closes() ─────────────────────────────────────────────────────────


class TestExtractCloses:
    """_extract_closes() parses close prices from candle response dicts."""

    def test_normal_response(self) -> None:
        resp = {"candles": [{"close": "100.5"}, {"close": "200.0"}]}
        assert _extract_closes(resp) == pytest.approx([100.5, 200.0])

    def test_numeric_close(self) -> None:
        resp = {"candles": [{"close": 42.0}]}
        assert _extract_closes(resp) == pytest.approx([42.0])

    def test_none_close_skipped(self) -> None:
        resp = {"candles": [{"close": None}, {"close": "10.0"}]}
        assert _extract_closes(resp) == pytest.approx([10.0])

    def test_bad_close_skipped(self) -> None:
        resp = {"candles": [{"close": "bad"}, {"close": "5.0"}]}
        assert _extract_closes(resp) == pytest.approx([5.0])

    def test_empty_candles(self) -> None:
        assert _extract_closes({"candles": []}) == []

    def test_missing_candles_key(self) -> None:
        assert _extract_closes({}) == []


# ── _safe_float() ─────────────────────────────────────────────────────────────


class TestSafeFloat:
    """_safe_float() converts values to float or returns default."""

    def test_numeric_string(self) -> None:
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_integer(self) -> None:
        assert _safe_float(42) == pytest.approx(42.0)

    def test_none_returns_default(self) -> None:
        assert _safe_float(None) == pytest.approx(0.0)

    def test_bad_string_returns_default(self) -> None:
        assert _safe_float("not-a-number", default=-1.0) == pytest.approx(-1.0)

    def test_custom_default(self) -> None:
        assert _safe_float(None, default=99.9) == pytest.approx(99.9)


# ── _generate_weight_configs() ────────────────────────────────────────────────


class TestGenerateWeightConfigs:
    """_generate_weight_configs() produces 12 configs with expected structure."""

    def test_produces_twelve_configs(self) -> None:
        configs = _generate_weight_configs(seed=42)
        assert len(configs) == 12

    def test_first_four_are_fixed(self) -> None:
        configs = _generate_weight_configs(seed=42)
        fixed_names = {c.name for c in configs[:4]}
        assert fixed_names == {"equal", "rl_heavy", "evolved_heavy", "regime_heavy"}

    def test_remaining_eight_are_random(self) -> None:
        configs = _generate_weight_configs(seed=42)
        random_names = [c.name for c in configs[4:]]
        assert all(n.startswith("random_") for n in random_names)
        assert len(random_names) == 8

    def test_all_have_three_source_weights(self) -> None:
        expected_sources = {SignalSource.RL, SignalSource.EVOLVED, SignalSource.REGIME}
        for cfg in _generate_weight_configs(seed=42):
            assert set(cfg.weights.keys()) == expected_sources

    def test_all_weights_positive(self) -> None:
        for cfg in _generate_weight_configs(seed=42):
            assert all(w >= 0 for w in cfg.weights.values())

    def test_same_seed_is_reproducible(self) -> None:
        configs_a = _generate_weight_configs(seed=123)
        configs_b = _generate_weight_configs(seed=123)
        for a, b in zip(configs_a, configs_b):
            assert a.name == b.name
            for src in SignalSource:
                assert a.weights[src] == pytest.approx(b.weights[src])

    def test_different_seeds_differ(self) -> None:
        configs_a = _generate_weight_configs(seed=1)
        configs_b = _generate_weight_configs(seed=999)
        # At least one random config must differ between seeds
        differ = any(
            a.weights[SignalSource.RL] != pytest.approx(b.weights[SignalSource.RL])
            for a, b in zip(configs_a[4:], configs_b[4:])
        )
        assert differ

    def test_equal_config_weights(self) -> None:
        configs = _generate_weight_configs(seed=42)
        equal_cfg = next(c for c in configs if c.name == "equal")
        assert equal_cfg.weights[SignalSource.RL] == pytest.approx(0.333, abs=1e-3)
        assert equal_cfg.weights[SignalSource.EVOLVED] == pytest.approx(0.333, abs=1e-3)
        assert equal_cfg.weights[SignalSource.REGIME] == pytest.approx(0.334, abs=1e-3)


# ── _normalise_weights() ──────────────────────────────────────────────────────


class TestNormaliseWeights:
    """_normalise_weights() produces string-keyed dict summing to 1.0."""

    def test_normalised_sum(self) -> None:
        weights = {SignalSource.RL: 2.0, SignalSource.EVOLVED: 3.0, SignalSource.REGIME: 5.0}
        result = _normalise_weights(weights)
        assert sum(result.values()) == pytest.approx(1.0)

    def test_string_keys(self) -> None:
        weights = {SignalSource.RL: 1.0, SignalSource.EVOLVED: 1.0, SignalSource.REGIME: 1.0}
        result = _normalise_weights(weights)
        assert "rl" in result
        assert "evolved" in result
        assert "regime" in result

    def test_zero_sum_falls_back_to_equal(self) -> None:
        weights = {SignalSource.RL: 0.0, SignalSource.EVOLVED: 0.0, SignalSource.REGIME: 0.0}
        result = _normalise_weights(weights)
        expected = pytest.approx(1.0 / 3.0, abs=1e-6)
        assert result["rl"] == expected
        assert result["evolved"] == expected
        assert result["regime"] == expected

    def test_already_normalised_unchanged(self) -> None:
        weights = {SignalSource.RL: 0.4, SignalSource.EVOLVED: 0.35, SignalSource.REGIME: 0.25}
        result = _normalise_weights(weights)
        assert result["rl"] == pytest.approx(0.4, abs=1e-5)
        assert result["evolved"] == pytest.approx(0.35, abs=1e-5)
        assert result["regime"] == pytest.approx(0.25, abs=1e-5)


# ── _build_comparison_table() ─────────────────────────────────────────────────


class TestBuildComparisonTable:
    """_build_comparison_table() produces a Markdown table."""

    def _make_result(
        self,
        name: str = "test_cfg",
        sharpe: float | None = 0.5,
        roi: float | None = 2.0,
        dd: float | None = 3.0,
        trades: int = 10,
    ) -> ConfigResult:
        return ConfigResult(
            config_name=name,
            weights={"rl": 0.33, "evolved": 0.33, "regime": 0.34},
            sharpe_ratio=sharpe,
            roi_pct=roi,
            max_drawdown_pct=dd,
            total_trades=trades,
        )

    def test_header_present(self) -> None:
        table = _build_comparison_table([self._make_result()])
        assert "| Rank |" in table
        assert "Sharpe" in table

    def test_one_row_per_result(self) -> None:
        results = [self._make_result(f"cfg_{i}") for i in range(3)]
        table = _build_comparison_table(results)
        # Each row starts with "| {rank} |"
        rows = [line for line in table.splitlines() if line.startswith("| ") and "Rank" not in line and "---" not in line]
        assert len(rows) == 3

    def test_na_for_none_values(self) -> None:
        result = self._make_result(sharpe=None, roi=None, dd=None)
        table = _build_comparison_table([result])
        assert "N/A" in table

    def test_empty_results(self) -> None:
        table = _build_comparison_table([])
        assert "| Rank |" in table


# ── WeightConfig ──────────────────────────────────────────────────────────────


class TestWeightConfig:
    """WeightConfig is a frozen Pydantic model."""

    def _valid_config(self) -> WeightConfig:
        return WeightConfig(
            name="test",
            weights={
                SignalSource.RL: 0.4,
                SignalSource.EVOLVED: 0.3,
                SignalSource.REGIME: 0.3,
            },
        )

    def test_frozen(self) -> None:
        cfg = self._valid_config()
        with pytest.raises(Exception):
            cfg.name = "mutated"  # type: ignore[misc]

    def test_name_required(self) -> None:
        with pytest.raises(Exception):
            WeightConfig(name="", weights={})  # empty name is invalid

    def test_weights_stored(self) -> None:
        cfg = self._valid_config()
        assert cfg.weights[SignalSource.RL] == pytest.approx(0.4)


# ── ConfigResult ──────────────────────────────────────────────────────────────


class TestConfigResult:
    """ConfigResult carries backtest metrics for one weight configuration."""

    def test_defaults(self) -> None:
        result = ConfigResult(
            config_name="equal",
            weights={"rl": 0.33, "evolved": 0.33, "regime": 0.34},
        )
        assert result.sharpe_ratio is None
        assert result.roi_pct is None
        assert result.total_trades == 0
        assert result.error is None

    def test_with_metrics(self) -> None:
        result = ConfigResult(
            config_name="rl_heavy",
            weights={"rl": 0.5, "evolved": 0.25, "regime": 0.25},
            sharpe_ratio=1.23,
            roi_pct=5.0,
            max_drawdown_pct=2.5,
            total_trades=15,
            session_id="abc-123",
        )
        assert result.sharpe_ratio == pytest.approx(1.23)
        assert result.session_id == "abc-123"


# ── save_optimal_weights_json() / load_optimal_weights() ─────────────────────


class TestSaveLoadOptimalWeights:
    """save_optimal_weights_json() writes and load_optimal_weights() reads the compact file."""

    def _valid_weights(self) -> dict[str, float]:
        return {"rl": 0.45, "evolved": 0.30, "regime": 0.25}

    def test_round_trip(self, tmp_path: Path) -> None:
        weights = self._valid_weights()
        path = tmp_path / "optimal_weights.json"
        save_optimal_weights_json(weights, path)
        loaded = load_optimal_weights(path)
        assert loaded["rl"] == pytest.approx(0.45)
        assert loaded["evolved"] == pytest.approx(0.30)
        assert loaded["regime"] == pytest.approx(0.25)

    def test_file_is_valid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "optimal_weights.json"
        save_optimal_weights_json(self._valid_weights(), path)
        raw = json.loads(path.read_text())
        assert isinstance(raw, dict)

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "subdir" / "optimal_weights.json"
        save_optimal_weights_json(self._valid_weights(), path)
        assert path.exists()

    def test_save_rejects_missing_keys(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="do not match"):
            save_optimal_weights_json({"rl": 0.5, "evolved": 0.5}, tmp_path / "w.json")

    def test_save_rejects_negative_weights(self, tmp_path: Path) -> None:
        weights = {"rl": -0.1, "evolved": 0.6, "regime": 0.5}
        with pytest.raises(ValueError, match="non-negative"):
            save_optimal_weights_json(weights, tmp_path / "w.json")

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_optimal_weights(tmp_path / "nonexistent.json")

    def test_load_malformed_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("[1, 2, 3]")  # a list, not a dict
        with pytest.raises(ValueError, match="Expected a JSON object"):
            load_optimal_weights(path)

    def test_load_non_numeric_value_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"rl": "bad", "evolved": 0.3, "regime": 0.2}))
        with pytest.raises(ValueError, match="Non-numeric"):
            load_optimal_weights(path)

    def test_load_missing_key_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({"rl": 0.5, "evolved": 0.5}))
        with pytest.raises(ValueError, match="missing keys"):
            load_optimal_weights(path)


# ── apply_optimal_weights() ───────────────────────────────────────────────────


class TestApplyOptimalWeights:
    """apply_optimal_weights() returns a new EnsembleConfig with updated weights."""

    def _config(self) -> EnsembleConfig:
        return EnsembleConfig(_env_file=None)  # type: ignore[call-arg]

    def _valid_weights(self) -> dict[str, float]:
        return {"rl": 0.5, "evolved": 0.3, "regime": 0.2}

    def test_returns_new_config(self) -> None:
        config = self._config()
        updated = apply_optimal_weights(config, self._valid_weights())
        assert updated is not config

    def test_weights_updated(self) -> None:
        config = self._config()
        updated = apply_optimal_weights(config, self._valid_weights())
        assert updated.weights["rl"] == pytest.approx(0.5)
        assert updated.weights["evolved"] == pytest.approx(0.3)
        assert updated.weights["regime"] == pytest.approx(0.2)

    def test_other_fields_preserved(self) -> None:
        config = self._config()
        updated = apply_optimal_weights(config, self._valid_weights())
        assert updated.confidence_threshold == config.confidence_threshold
        assert updated.symbols == config.symbols
        assert updated.mode == config.mode

    def test_original_config_unchanged(self) -> None:
        config = self._config()
        original_weights = dict(config.weights)
        apply_optimal_weights(config, self._valid_weights())
        assert config.weights == original_weights

    def test_rejects_missing_keys(self) -> None:
        config = self._config()
        with pytest.raises(ValueError, match="missing required keys"):
            apply_optimal_weights(config, {"rl": 0.5, "evolved": 0.5})

    def test_rejects_negative_weights(self) -> None:
        config = self._config()
        with pytest.raises(ValueError, match="non-negative"):
            apply_optimal_weights(config, {"rl": -0.1, "evolved": 0.6, "regime": 0.5})


# ── validate_ensemble_beats_baseline() ───────────────────────────────────────


class TestValidateEnsembleBeatsBaseline:
    """validate_ensemble_beats_baseline() checks optimal > equal-weight Sharpe."""

    def _make_result(
        self,
        name: str = "optimal",
        sharpe: float | None = 1.5,
        error: str | None = None,
    ) -> ConfigResult:
        return ConfigResult(
            config_name=name,
            weights={"rl": 0.5, "evolved": 0.3, "regime": 0.2},
            sharpe_ratio=sharpe,
            error=error,
        )

    def test_passes_when_optimal_beats_baseline(self) -> None:
        optimal = self._make_result(sharpe=1.5)
        baseline = self._make_result(name="equal", sharpe=1.0)
        passed, msg = validate_ensemble_beats_baseline(optimal, baseline)
        assert passed is True
        assert "beats" in msg

    def test_fails_when_optimal_below_baseline(self) -> None:
        optimal = self._make_result(sharpe=0.8)
        baseline = self._make_result(name="equal", sharpe=1.2)
        passed, msg = validate_ensemble_beats_baseline(optimal, baseline)
        assert passed is False
        assert "does NOT beat" in msg

    def test_fails_when_optimal_has_error(self) -> None:
        optimal = self._make_result(error="create_backtest failed")
        baseline = self._make_result(name="equal", sharpe=1.0)
        passed, msg = validate_ensemble_beats_baseline(optimal, baseline)
        assert passed is False
        assert "error" in msg.lower()

    def test_fails_when_optimal_has_no_sharpe(self) -> None:
        optimal = self._make_result(sharpe=None)
        baseline = self._make_result(name="equal", sharpe=1.0)
        passed, msg = validate_ensemble_beats_baseline(optimal, baseline)
        assert passed is False
        assert "no Sharpe" in msg

    def test_skips_when_baseline_unavailable(self) -> None:
        optimal = self._make_result(sharpe=1.5)
        passed, msg = validate_ensemble_beats_baseline(optimal, None)
        assert passed is True
        assert "unavailable" in msg

    def test_skips_when_baseline_has_error(self) -> None:
        optimal = self._make_result(sharpe=1.5)
        baseline = self._make_result(name="equal", sharpe=None, error="failed")
        passed, msg = validate_ensemble_beats_baseline(optimal, baseline)
        assert passed is True
        assert "unavailable" in msg

    def test_exact_equal_sharpe_fails(self) -> None:
        # Strictly greater than is required; equal is not a win.
        optimal = self._make_result(sharpe=1.0)
        baseline = self._make_result(name="equal", sharpe=1.0)
        passed, msg = validate_ensemble_beats_baseline(optimal, baseline)
        assert passed is False


# ── WeightOptimizer.rank_results() ───────────────────────────────────────────


class TestWeightOptimizerRankResults:
    """rank_results() sorts ConfigResults by Sharpe desc, None last."""

    def _optimizer(self) -> WeightOptimizer:
        return WeightOptimizer(base_url="http://localhost:8000", api_key="test_key", seed=42)

    def _inject_results(self, optimizer: WeightOptimizer, results: list[ConfigResult]) -> None:
        optimizer._results = results

    def test_sorted_by_sharpe_descending(self) -> None:
        optimizer = self._optimizer()
        self._inject_results(optimizer, [
            ConfigResult(config_name="low", weights={}, sharpe_ratio=0.5),
            ConfigResult(config_name="high", weights={}, sharpe_ratio=2.0),
            ConfigResult(config_name="mid", weights={}, sharpe_ratio=1.0),
        ])
        ranked = optimizer.rank_results()
        sharpes = [r.sharpe_ratio for r in ranked]
        assert sharpes == [2.0, 1.0, 0.5]

    def test_none_sharpe_goes_last(self) -> None:
        optimizer = self._optimizer()
        self._inject_results(optimizer, [
            ConfigResult(config_name="none_sharpe", weights={}, sharpe_ratio=None),
            ConfigResult(config_name="positive", weights={}, sharpe_ratio=1.5),
        ])
        ranked = optimizer.rank_results()
        assert ranked[0].config_name == "positive"
        assert ranked[-1].config_name == "none_sharpe"

    def test_empty_results(self) -> None:
        optimizer = self._optimizer()
        self._inject_results(optimizer, [])
        assert optimizer.rank_results() == []

    def test_tiebreak_by_roi(self) -> None:
        optimizer = self._optimizer()
        self._inject_results(optimizer, [
            ConfigResult(config_name="low_roi", weights={}, sharpe_ratio=1.0, roi_pct=1.0),
            ConfigResult(config_name="high_roi", weights={}, sharpe_ratio=1.0, roi_pct=5.0),
        ])
        ranked = optimizer.rank_results()
        assert ranked[0].config_name == "high_roi"

    def test_original_list_unchanged(self) -> None:
        optimizer = self._optimizer()
        original_order = [
            ConfigResult(config_name="b", weights={}, sharpe_ratio=0.5),
            ConfigResult(config_name="a", weights={}, sharpe_ratio=1.5),
        ]
        self._inject_results(optimizer, list(original_order))
        optimizer.rank_results()
        assert optimizer._results[0].config_name == "b"


# ── Integration: save_results() builds OptimizationResult ────────────────────


class TestSaveResults:
    """WeightOptimizer.save_results() assembles and persists OptimizationResult."""

    def _optimizer_with_results(self) -> WeightOptimizer:
        optimizer = WeightOptimizer(base_url="http://localhost:8000", api_key="key", seed=42)
        optimizer._results = [
            ConfigResult(
                config_name="rl_heavy",
                weights={"rl": 0.5, "evolved": 0.25, "regime": 0.25},
                sharpe_ratio=1.5,
                roi_pct=4.0,
                max_drawdown_pct=2.0,
                total_trades=12,
                session_id="session-001",
            ),
            ConfigResult(
                config_name="equal",
                weights={"rl": 0.333, "evolved": 0.333, "regime": 0.334},
                sharpe_ratio=1.0,
                roi_pct=2.0,
                max_drawdown_pct=3.0,
                total_trades=8,
                session_id="session-002",
            ),
        ]
        return optimizer

    def test_writes_json_file(self, tmp_path: Path) -> None:
        optimizer = self._optimizer_with_results()
        path = tmp_path / "result.json"
        result = optimizer.save_results(path=path)
        assert path.exists()
        assert isinstance(result, OptimizationResult)

    def test_optimal_config_name_is_highest_sharpe(self, tmp_path: Path) -> None:
        optimizer = self._optimizer_with_results()
        result = optimizer.save_results(path=tmp_path / "r.json")
        assert result.optimal_config_name == "rl_heavy"

    def test_comparison_table_non_empty(self, tmp_path: Path) -> None:
        optimizer = self._optimizer_with_results()
        result = optimizer.save_results(path=tmp_path / "r.json")
        assert "| Rank |" in result.comparison_table

    def test_optimal_weights_are_normalised(self, tmp_path: Path) -> None:
        optimizer = self._optimizer_with_results()
        result = optimizer.save_results(path=tmp_path / "r.json")
        total = sum(result.optimal_weights.values())
        assert total == pytest.approx(1.0, abs=1e-4)

    def test_json_is_deserializable(self, tmp_path: Path) -> None:
        optimizer = self._optimizer_with_results()
        path = tmp_path / "r.json"
        optimizer.save_results(path=path)
        raw = json.loads(path.read_text())
        assert "optimal_weights" in raw
        assert "results" in raw


# ── Full compact-weights round-trip ───────────────────────────────────────────


class TestCompactWeightsRoundTrip:
    """Integration: save → load → apply → verify EnsembleConfig weights."""

    def test_full_round_trip(self, tmp_path: Path) -> None:
        weights = {"rl": 0.5, "evolved": 0.3, "regime": 0.2}
        path = tmp_path / "optimal_weights.json"

        save_optimal_weights_json(weights, path)
        loaded = load_optimal_weights(path)
        config = apply_optimal_weights(EnsembleConfig(_env_file=None), loaded)  # type: ignore[call-arg]

        assert config.weights["rl"] == pytest.approx(0.5)
        assert config.weights["evolved"] == pytest.approx(0.3)
        assert config.weights["regime"] == pytest.approx(0.2)
