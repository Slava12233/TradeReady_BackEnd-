"""Tests for the upgraded evolutionary fitness system.

Covers:
- ``compute_composite_fitness`` — 5-factor formula including OOS Sharpe
- ``_compute_fitness`` — dispatch across all four fitness_fn modes
- ``ConvergenceDetector`` — OOS-aware update and convergence logic
- ``EvolutionConfig`` — OOS split fields and derived window properties
- ``BattleRunner.get_detailed_metrics`` — metric extraction from raw API responses
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.strategies.evolutionary.config import EvolutionConfig
from agent.strategies.evolutionary.evolve import (
    ConvergenceDetector,
    _compute_fitness,
    compute_composite_fitness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metrics(
    sharpe: float | None = 1.0,
    drawdown: float | None = 0.05,
    profit_factor: float | None = 1.5,
    win_rate: float | None = 0.6,
    roi_pct: float | None = 0.10,
) -> dict[str, float | None]:
    """Return a fully-populated metrics dict."""
    return {
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": drawdown,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "roi_pct": roi_pct,
    }


# ---------------------------------------------------------------------------
# Tests: compute_composite_fitness
# ---------------------------------------------------------------------------

class TestCompositeFITNESS:
    """Unit tests for the 5-factor composite fitness function."""

    def test_all_metrics_present_positive_result(self) -> None:
        """Full set of positive metrics produces a finite positive result."""
        score = compute_composite_fitness(
            sharpe=1.5,
            profit_factor=2.0,
            max_drawdown_pct=0.10,
            win_rate=0.60,
            oos_sharpe=1.2,
        )
        assert isinstance(score, float)
        assert score > 0.0

    def test_formula_weights_sharpe_correctly(self) -> None:
        """Sharpe coefficient is 0.35 — doubling sharpe increases score by 0.35."""
        base = compute_composite_fitness(1.0, 1.0, 0.0, 0.5, 0.0)
        higher = compute_composite_fitness(2.0, 1.0, 0.0, 0.5, 0.0)
        assert abs((higher - base) - 0.35) < 1e-9

    def test_formula_weights_profit_factor_correctly(self) -> None:
        """Profit factor coefficient is 0.25."""
        base = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, 0.0)
        higher = compute_composite_fitness(0.0, 2.0, 0.0, 0.5, 0.0)
        assert abs((higher - base) - 0.25) < 1e-9

    def test_formula_penalises_drawdown(self) -> None:
        """Higher drawdown lowers the score (coefficient is -0.20)."""
        no_dd = compute_composite_fitness(1.0, 1.0, 0.0, 0.5, 0.0)
        with_dd = compute_composite_fitness(1.0, 1.0, 1.0, 0.5, 0.0)
        assert no_dd - with_dd == pytest.approx(0.20, abs=1e-9)

    def test_formula_weights_win_rate_correctly(self) -> None:
        """Win rate coefficient is 0.10."""
        base = compute_composite_fitness(0.0, 1.0, 0.0, 0.0, 0.0)
        higher = compute_composite_fitness(0.0, 1.0, 0.0, 1.0, 0.0)
        assert abs((higher - base) - 0.10) < 1e-9

    def test_formula_weights_oos_sharpe_correctly(self) -> None:
        """OOS Sharpe coefficient is 0.10."""
        base = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, 0.0)
        higher = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, 1.0)
        assert abs((higher - base) - 0.10) < 1e-9

    def test_none_sharpe_uses_fallback_zero(self) -> None:
        """Missing Sharpe treated as 0 — does not affect score via that term."""
        with_none = compute_composite_fitness(None, 1.0, 0.0, 0.5, 0.0)
        with_zero = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, 0.0)
        assert with_none == pytest.approx(with_zero, abs=1e-9)

    def test_none_profit_factor_uses_neutral_fallback(self) -> None:
        """Missing profit factor treated as 1.0 (neutral)."""
        with_none = compute_composite_fitness(0.0, None, 0.0, 0.5, 0.0)
        with_one = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, 0.0)
        assert with_none == pytest.approx(with_one, abs=1e-9)

    def test_none_drawdown_uses_fallback_zero(self) -> None:
        """Missing drawdown treated as 0 — no drawdown penalty."""
        with_none = compute_composite_fitness(0.0, 1.0, None, 0.5, 0.0)
        with_zero = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, 0.0)
        assert with_none == pytest.approx(with_zero, abs=1e-9)

    def test_none_win_rate_uses_neutral_fallback(self) -> None:
        """Missing win rate treated as 0.5 (neutral)."""
        with_none = compute_composite_fitness(0.0, 1.0, 0.0, None, 0.0)
        with_half = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, 0.0)
        assert with_none == pytest.approx(with_half, abs=1e-9)

    def test_none_oos_sharpe_uses_fallback_zero(self) -> None:
        """Missing OOS Sharpe treated as 0 — neutral OOS term."""
        with_none = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, None)
        with_zero = compute_composite_fitness(0.0, 1.0, 0.0, 0.5, 0.0)
        assert with_none == pytest.approx(with_zero, abs=1e-9)

    def test_profit_factor_clamped_at_five(self) -> None:
        """Profit factors > 5 are clamped to prevent outlier dominance."""
        at_five = compute_composite_fitness(0.0, 5.0, 0.0, 0.5, 0.0)
        at_hundred = compute_composite_fitness(0.0, 100.0, 0.0, 0.5, 0.0)
        assert at_five == pytest.approx(at_hundred, abs=1e-9)

    def test_profit_factor_clamped_at_zero(self) -> None:
        """Negative profit factors (gross loss > gross profit) are clamped to 0."""
        at_zero = compute_composite_fitness(0.0, 0.0, 0.0, 0.5, 0.0)
        at_neg = compute_composite_fitness(0.0, -5.0, 0.0, 0.5, 0.0)
        assert at_zero == pytest.approx(at_neg, abs=1e-9)

    def test_all_none_returns_neutral_score(self) -> None:
        """All-None inputs fall back to neutral values and produce a defined score."""
        score = compute_composite_fitness(None, None, None, None, None)
        # Expected: 0.35*0 + 0.25*1.0 + (-0.20)*0 + 0.10*0.5 + 0.10*0 = 0.30
        assert score == pytest.approx(0.30, abs=1e-9)

    def test_negative_sharpe_lowers_score(self) -> None:
        """Negative Sharpe reduces fitness below the all-zero baseline."""
        positive = compute_composite_fitness(1.0, 1.0, 0.0, 0.5, 0.0)
        negative = compute_composite_fitness(-1.0, 1.0, 0.0, 0.5, 0.0)
        assert negative < positive

    def test_negative_oos_sharpe_penalises_score(self) -> None:
        """Negative OOS Sharpe (overfit strategy) reduces composite fitness."""
        no_oos = compute_composite_fitness(1.0, 1.0, 0.0, 0.5, 0.0)
        bad_oos = compute_composite_fitness(1.0, 1.0, 0.0, 0.5, -2.0)
        assert bad_oos < no_oos


# ---------------------------------------------------------------------------
# Tests: _compute_fitness dispatch
# ---------------------------------------------------------------------------

class TestComputeFitnessDispatch:
    """Tests for _compute_fitness multi-mode dispatch."""

    _AGENT_IDS = ["a1", "a2"]

    def _make_is_metrics(
        self,
        sharpe: float = 1.0,
        drawdown: float = 0.05,
        pf: float = 1.5,
        wr: float = 0.6,
        roi: float = 0.10,
    ) -> dict[str, dict[str, float | None]]:
        return {
            "a1": _make_metrics(sharpe, drawdown, pf, wr, roi),
            "a2": _make_metrics(sharpe, drawdown, pf, wr, roi),
        }

    def test_composite_mode_returns_5factor_score(self) -> None:
        """'composite' mode computes the 5-factor formula."""
        is_metrics = self._make_is_metrics()
        oos_map = {"a1": 1.0, "a2": 0.5}
        scores = _compute_fitness(self._AGENT_IDS, is_metrics, oos_map, "composite")
        expected = compute_composite_fitness(1.0, 1.5, 0.05, 0.6, 1.0)
        assert scores[0] == pytest.approx(expected, abs=1e-9)

    def test_composite_mode_uses_oos_sharpe(self) -> None:
        """Composite mode: higher OOS Sharpe → higher fitness."""
        is_metrics = self._make_is_metrics()
        low_oos = {"a1": 0.0, "a2": 0.0}
        high_oos = {"a1": 2.0, "a2": 2.0}
        scores_low = _compute_fitness(self._AGENT_IDS, is_metrics, low_oos, "composite")
        scores_high = _compute_fitness(self._AGENT_IDS, is_metrics, high_oos, "composite")
        assert scores_high[0] > scores_low[0]

    def test_sharpe_minus_drawdown_mode(self) -> None:
        """'sharpe_minus_drawdown' mode: sharpe - 0.5 * drawdown."""
        is_metrics = {"a1": _make_metrics(sharpe=2.0, drawdown=0.20)}
        oos_map: dict[str, float | None] = {"a1": None}
        scores = _compute_fitness(["a1"], is_metrics, oos_map, "sharpe_minus_drawdown")
        assert scores[0] == pytest.approx(2.0 - 0.5 * 0.20, abs=1e-9)

    def test_sharpe_minus_drawdown_falls_back_to_roi(self) -> None:
        """'sharpe_minus_drawdown' uses ROI when sharpe is None."""
        is_metrics = {"a1": _make_metrics(sharpe=None, drawdown=None, roi_pct=0.15)}
        oos_map: dict[str, float | None] = {"a1": None}
        scores = _compute_fitness(["a1"], is_metrics, oos_map, "sharpe_minus_drawdown")
        assert scores[0] == pytest.approx(0.15, abs=1e-9)

    def test_sharpe_only_mode(self) -> None:
        """'sharpe_only' mode returns raw in-sample Sharpe."""
        is_metrics = {"a1": _make_metrics(sharpe=1.8)}
        oos_map: dict[str, float | None] = {"a1": 0.5}
        scores = _compute_fitness(["a1"], is_metrics, oos_map, "sharpe_only")
        assert scores[0] == pytest.approx(1.8, abs=1e-9)

    def test_roi_only_mode(self) -> None:
        """'roi_only' mode returns ROI percentage."""
        is_metrics = {"a1": _make_metrics(roi_pct=0.25)}
        oos_map: dict[str, float | None] = {"a1": None}
        scores = _compute_fitness(["a1"], is_metrics, oos_map, "roi_only")
        assert scores[0] == pytest.approx(0.25, abs=1e-9)

    def test_missing_agent_in_metrics_returns_failure_fitness(self) -> None:
        """Agent not in is_metrics receives FAILURE_FITNESS."""
        from agent.strategies.evolutionary.battle_runner import FAILURE_FITNESS

        scores = _compute_fitness(["a1"], {}, {}, "composite")
        assert scores[0] == FAILURE_FITNESS

    def test_sharpe_only_returns_failure_when_sharpe_none(self) -> None:
        """'sharpe_only' mode returns FAILURE_FITNESS when Sharpe is None."""
        from agent.strategies.evolutionary.battle_runner import FAILURE_FITNESS

        is_metrics = {"a1": _make_metrics(sharpe=None)}
        scores = _compute_fitness(["a1"], is_metrics, {"a1": None}, "sharpe_only")
        assert scores[0] == FAILURE_FITNESS

    def test_roi_only_returns_failure_when_roi_none(self) -> None:
        """'roi_only' mode returns FAILURE_FITNESS when roi_pct is None."""
        from agent.strategies.evolutionary.battle_runner import FAILURE_FITNESS

        is_metrics = {"a1": _make_metrics(roi_pct=None)}
        scores = _compute_fitness(["a1"], is_metrics, {"a1": None}, "roi_only")
        assert scores[0] == FAILURE_FITNESS

    def test_order_preserved_for_multiple_agents(self) -> None:
        """Scores list is aligned with agent_ids order."""
        is_metrics = {
            "a1": _make_metrics(sharpe=2.0),
            "a2": _make_metrics(sharpe=0.5),
        }
        scores = _compute_fitness(["a1", "a2"], is_metrics, {"a1": None, "a2": None}, "sharpe_only")
        assert scores[0] > scores[1]


# ---------------------------------------------------------------------------
# Tests: ConvergenceDetector (OOS-aware)
# ---------------------------------------------------------------------------

class TestConvergenceDetector:
    """Tests for the OOS-aware ConvergenceDetector."""

    def test_not_converged_initially(self) -> None:
        """Detector does not report convergence before any updates."""
        det = ConvergenceDetector(threshold=3)
        assert not det.converged

    def test_stale_generations_increments_on_plateau(self) -> None:
        """Stale counter increments when fitness does not improve."""
        det = ConvergenceDetector(threshold=3)
        det.update(1.0)
        det.update(1.0)
        assert det.stale_generations == 1

    def test_stale_counter_resets_on_improvement(self) -> None:
        """Stale counter resets when fitness improves by at least min_improvement."""
        det = ConvergenceDetector(threshold=3, min_improvement=0.01)
        det.update(1.0)
        det.update(1.0)  # stale = 1
        det.update(1.05)  # improvement → reset
        assert det.stale_generations == 0

    def test_converged_triggers_at_threshold(self) -> None:
        """``converged`` is True once stale count reaches threshold."""
        det = ConvergenceDetector(threshold=2)
        det.update(1.0)
        det.update(1.0)  # stale = 1
        assert not det.converged
        det.update(1.0)  # stale = 2 → converged
        assert det.converged

    def test_min_improvement_prevents_float_noise_trigger(self) -> None:
        """Tiny improvement below min_improvement does not reset stale count."""
        det = ConvergenceDetector(threshold=3, min_improvement=0.01)
        det.update(1.0)
        det.update(1.001)  # improvement < 0.01 → still stale
        assert det.stale_generations == 1

    def test_best_oos_sharpe_tracked(self) -> None:
        """OOS Sharpe of the best genome is stored per generation."""
        det = ConvergenceDetector(threshold=3)
        det.update(1.0, best_oos_sharpe=0.8)
        assert det.best_oos_sharpe == pytest.approx(0.8, abs=1e-9)

    def test_best_oos_sharpe_updated_on_improvement(self) -> None:
        """OOS Sharpe updates when a better generation is seen."""
        det = ConvergenceDetector(threshold=3)
        det.update(1.0, best_oos_sharpe=0.5)
        det.update(2.0, best_oos_sharpe=1.2)
        assert det.best_oos_sharpe == pytest.approx(1.2, abs=1e-9)

    def test_best_oos_sharpe_none_initially(self) -> None:
        """``best_oos_sharpe`` is None before any update with OOS data."""
        det = ConvergenceDetector(threshold=3)
        assert det.best_oos_sharpe is None

    def test_update_without_oos_sharpe_does_not_overwrite(self) -> None:
        """Passing ``None`` for OOS Sharpe does not overwrite a previous value."""
        det = ConvergenceDetector(threshold=3)
        det.update(1.0, best_oos_sharpe=0.9)
        det.update(2.0, best_oos_sharpe=None)
        assert det.best_oos_sharpe == pytest.approx(0.9, abs=1e-9)

    def test_converged_false_after_reset_by_improvement(self) -> None:
        """Convergence state resets when fitness improves after a plateau."""
        det = ConvergenceDetector(threshold=2)
        det.update(1.0)
        det.update(1.0)  # stale = 1
        det.update(1.0)  # stale = 2 → converged
        assert det.converged
        det.update(1.5)  # improvement → reset
        assert not det.converged


# ---------------------------------------------------------------------------
# Tests: EvolutionConfig OOS split
# ---------------------------------------------------------------------------

class TestEvolutionConfigOOSSplit:
    """Tests for OOS window split properties on EvolutionConfig."""

    def _make_config(
        self,
        start: date = date(2024, 1, 1),
        end: date = date(2024, 1, 8),
        oos_ratio: float = 0.30,
    ) -> EvolutionConfig:
        """Build an EvolutionConfig with minimal required env vars."""
        return EvolutionConfig(
            historical_start=start,
            historical_end=end,
            oos_split_ratio=oos_ratio,
            _env_file=None,  # type: ignore[call-arg]
        )

    def test_is_split_returns_three_strings(self) -> None:
        """``is_split`` returns a 3-tuple of ISO-8601 strings."""
        cfg = self._make_config()
        parts = cfg.is_split
        assert len(parts) == 3
        assert all(isinstance(p, str) for p in parts)

    def test_in_sample_window_covers_70_percent(self) -> None:
        """With 30% OOS and 7-day window, IS covers 5 days (≈70%)."""
        cfg = self._make_config(
            start=date(2024, 1, 1),
            end=date(2024, 1, 8),  # 7 days total
            oos_ratio=0.30,
        )
        is_start, split = cfg.in_sample_window
        # OOS days = round(7 * 0.30) = 2; IS days = 5; split at Jan 6
        assert "2024-01-01" in is_start
        assert "2024-01-06" in split

    def test_oos_window_covers_last_30_percent(self) -> None:
        """OOS window starts at the split point and ends at historical_end."""
        cfg = self._make_config(
            start=date(2024, 1, 1),
            end=date(2024, 1, 8),
            oos_ratio=0.30,
        )
        split, oos_end = cfg.oos_window
        assert "2024-01-06" in split
        assert "2024-01-08" in oos_end

    def test_historical_window_covers_full_range(self) -> None:
        """``historical_window`` still returns the full window (backward compat)."""
        cfg = self._make_config()
        start, end = cfg.historical_window
        assert "2024-01-01" in start
        assert "2024-01-08" in end

    def test_oos_split_ratio_validates_minimum(self) -> None:
        """oos_split_ratio below 0.10 raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make_config(oos_ratio=0.05)

    def test_oos_split_ratio_validates_maximum(self) -> None:
        """oos_split_ratio above 0.50 raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make_config(oos_ratio=0.60)

    def test_oos_split_ratio_boundary_10_pct_allowed(self) -> None:
        """oos_split_ratio = 0.10 is allowed (lower boundary)."""
        cfg = self._make_config(oos_ratio=0.10)
        assert cfg.oos_split_ratio == pytest.approx(0.10, abs=1e-9)

    def test_oos_split_ratio_boundary_50_pct_allowed(self) -> None:
        """oos_split_ratio = 0.50 is allowed (upper boundary)."""
        cfg = self._make_config(oos_ratio=0.50)
        assert cfg.oos_split_ratio == pytest.approx(0.50, abs=1e-9)

    def test_is_split_has_minimum_one_oos_day(self) -> None:
        """OOS window always has at least 1 day even with minimum ratio."""
        cfg = self._make_config(
            start=date(2024, 1, 1),
            end=date(2024, 1, 3),  # only 2 days
            oos_ratio=0.10,
        )
        _, split, oos_end = cfg.is_split
        # round(2 * 0.10) = 0 → max(1, 0) = 1 → split at Jan 2
        assert "2024-01-02" in split
        assert "2024-01-03" in oos_end

    def test_default_fitness_fn_is_composite(self) -> None:
        """The default fitness function is 'composite' (not legacy)."""
        cfg = self._make_config()
        assert cfg.fitness_fn == "composite"

    def test_composite_fitness_fn_accepted(self) -> None:
        """'composite' is a valid fitness_fn value."""
        cfg = self._make_config()
        cfg = cfg.model_copy(update={"fitness_fn": "composite"})
        assert cfg.fitness_fn == "composite"

    def test_legacy_fitness_fn_still_accepted(self) -> None:
        """'sharpe_minus_drawdown' is still accepted for backward compat."""
        cfg = self._make_config()
        cfg = cfg.model_copy(update={"fitness_fn": "sharpe_minus_drawdown"})
        assert cfg.fitness_fn == "sharpe_minus_drawdown"


# ---------------------------------------------------------------------------
# Tests: BattleRunner.get_detailed_metrics
# ---------------------------------------------------------------------------

class TestGetDetailedMetrics:
    """Tests for BattleRunner.get_detailed_metrics metric extraction."""

    def _make_runner(self, agent_ids: list[str]) -> Any:
        """Build a BattleRunner with mocked internals."""
        from agent.strategies.evolutionary.battle_runner import BattleRunner
        from agent.config import AgentConfig

        config = MagicMock(spec=AgentConfig)
        config.platform_base_url = "http://localhost:8000"
        rest_client = MagicMock()

        runner = BattleRunner.__new__(BattleRunner)
        runner._config = config
        runner._rest = rest_client
        runner._jwt_token = "test-token"
        runner._base_url = "http://localhost:8000"
        runner._agent_ids = agent_ids
        runner._strategy_ids = {}
        runner._generation = 0
        runner._jwt_client = AsyncMock()
        return runner

    async def test_returns_all_agent_ids_on_empty_results(self) -> None:
        """When battle returns no results, all agents get null metrics."""
        runner = self._make_runner(["a1", "a2"])
        runner._fetch_battle_results = AsyncMock(return_value=[])

        result = await runner.get_detailed_metrics("battle-1")

        assert set(result.keys()) == {"a1", "a2"}
        for aid, m in result.items():
            assert m["sharpe_ratio"] is None
            assert m["profit_factor"] is None

    async def test_extracts_all_five_metrics_from_nested_metrics(self) -> None:
        """Metrics nested under 'metrics' key are extracted correctly."""
        runner = self._make_runner(["a1"])
        runner._fetch_battle_results = AsyncMock(return_value=[
            {
                "agent_id": "a1",
                "metrics": {
                    "sharpe_ratio": "1.5",
                    "max_drawdown_pct": "0.08",
                    "profit_factor": "2.1",
                    "win_rate": "0.65",
                    "roi_pct": "0.12",
                },
            }
        ])

        result = await runner.get_detailed_metrics("battle-1")

        m = result["a1"]
        assert m["sharpe_ratio"] == pytest.approx(1.5, abs=1e-6)
        assert m["max_drawdown_pct"] == pytest.approx(0.08, abs=1e-6)
        assert m["profit_factor"] == pytest.approx(2.1, abs=1e-6)
        assert m["win_rate"] == pytest.approx(0.65, abs=1e-6)
        assert m["roi_pct"] == pytest.approx(0.12, abs=1e-6)

    async def test_extracts_metrics_from_flat_result(self) -> None:
        """When 'metrics' key is absent, falls back to the top-level dict."""
        runner = self._make_runner(["a1"])
        runner._fetch_battle_results = AsyncMock(return_value=[
            {
                "agent_id": "a1",
                "sharpe_ratio": 0.9,
                "max_drawdown_pct": 0.05,
                "profit_factor": 1.8,
                "win_rate": 0.55,
                "roi_pct": 0.07,
            }
        ])

        result = await runner.get_detailed_metrics("battle-1")

        m = result["a1"]
        assert m["sharpe_ratio"] == pytest.approx(0.9, abs=1e-6)
        assert m["profit_factor"] == pytest.approx(1.8, abs=1e-6)

    async def test_handles_string_none_values(self) -> None:
        """String 'None' / 'null' values in the API response parse to None."""
        runner = self._make_runner(["a1"])
        runner._fetch_battle_results = AsyncMock(return_value=[
            {
                "agent_id": "a1",
                "metrics": {
                    "sharpe_ratio": "None",
                    "max_drawdown_pct": "null",
                    "profit_factor": "",
                    "win_rate": "N/A",
                    "roi_pct": None,
                },
            }
        ])

        result = await runner.get_detailed_metrics("battle-1")
        m = result["a1"]
        assert m["sharpe_ratio"] is None
        assert m["max_drawdown_pct"] is None
        assert m["profit_factor"] is None
        assert m["win_rate"] is None
        assert m["roi_pct"] is None

    async def test_ignores_unknown_agent_ids(self) -> None:
        """Results for agent IDs not in the runner's list are ignored."""
        runner = self._make_runner(["a1"])
        runner._fetch_battle_results = AsyncMock(return_value=[
            {"agent_id": "a1", "metrics": {"sharpe_ratio": 1.0}},
            {"agent_id": "unknown-agent", "metrics": {"sharpe_ratio": 99.0}},
        ])

        result = await runner.get_detailed_metrics("battle-1")

        assert "unknown-agent" not in result
        assert "a1" in result

    async def test_handles_participants_wrapper_key(self) -> None:
        """Results wrapped under 'participants' key are unwrapped correctly."""
        runner = self._make_runner(["a1"])
        runner._fetch_battle_results = AsyncMock(return_value={
            "participants": [
                {"agent_id": "a1", "metrics": {"sharpe_ratio": 1.3}},
            ]
        })

        result = await runner.get_detailed_metrics("battle-1")

        assert result["a1"]["sharpe_ratio"] == pytest.approx(1.3, abs=1e-6)

    async def test_handles_results_wrapper_key(self) -> None:
        """Results wrapped under 'results' key are unwrapped correctly."""
        runner = self._make_runner(["a1"])
        runner._fetch_battle_results = AsyncMock(return_value={
            "results": [
                {"agent_id": "a1", "metrics": {"sharpe_ratio": 0.7}},
            ]
        })

        result = await runner.get_detailed_metrics("battle-1")

        assert result["a1"]["sharpe_ratio"] == pytest.approx(0.7, abs=1e-6)

    async def test_malformed_result_leaves_null_metrics(self) -> None:
        """A result that raises during parsing leaves the agent with null metrics."""
        runner = self._make_runner(["a1"])
        # Return a result where metrics is not a dict, triggering AttributeError.
        runner._fetch_battle_results = AsyncMock(return_value=[
            {"agent_id": "a1", "metrics": "not-a-dict"},
        ])

        result = await runner.get_detailed_metrics("battle-1")

        # Should not raise; all metrics should be None.
        assert result["a1"]["sharpe_ratio"] is None

    async def test_get_fitness_delegates_to_get_detailed_metrics(self) -> None:
        """get_fitness uses get_detailed_metrics internally (legacy formula)."""
        runner = self._make_runner(["a1"])
        runner.get_detailed_metrics = AsyncMock(return_value={
            "a1": _make_metrics(sharpe=1.5, drawdown=0.20)
        })

        fitness_map = await runner.get_fitness("battle-1")

        assert fitness_map["a1"] == pytest.approx(1.5 - 0.5 * 0.20, abs=1e-9)
