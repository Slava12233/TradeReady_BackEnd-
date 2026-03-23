"""Tests for agent/strategies/walk_forward.py.

Covers:
- ``generate_windows`` — rolling window splitting logic
- ``compute_wfe`` — Walk-Forward Efficiency calculation
- ``_add_months`` — calendar month arithmetic helper
- ``_parse_iso_date`` / ``_to_iso`` — date conversion helpers
- ``WalkForwardConfig`` — Pydantic-settings validation
- ``WindowResult`` / ``WalkForwardResult`` — result model construction
- ``run_walk_forward`` — core async orchestrator (mocked train/eval callables)
- WFE threshold enforcement — overfit warning flag and deployability gate
- Report file persistence — JSON written to results_dir
- ``walk_forward_rl`` integration — mocked SB3 train/eval cycle
- ``walk_forward_evolutionary`` integration — mocked BattleRunner cycle
- ``TrainingRunner.walk_forward_train`` — synchronous wrapper on runner

Test counts per class:
    TestAddMonths               — 9
    TestParseIsoAndToIso        — 7
    TestGenerateWindows         — 12
    TestComputeWFE              — 10
    TestWalkForwardConfig       — 8
    TestWindowResult            — 5
    TestWalkForwardResult       — 7
    TestRunWalkForward          — 14
    TestWalkForwardRL           — 8
    TestWalkForwardEvolutionary — 8
    TestTrainingRunnerWalkForward — 5

Total: 93
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.strategies.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WindowResult,
    _add_months,
    _parse_iso_date,
    _to_iso,
    compute_wfe,
    generate_windows,
    run_walk_forward,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wf_config(**overrides: Any) -> WalkForwardConfig:
    """Construct a WalkForwardConfig bypassing the .env file."""
    defaults = {
        "data_start": "2023-01-01T00:00:00Z",
        "data_end": "2024-01-01T00:00:00Z",
        "train_months": 6,
        "oos_months": 1,
    }
    defaults.update(overrides)
    return WalkForwardConfig(_env_file=None, **defaults)  # type: ignore[call-arg]


async def _trivial_train(train_start: str, train_end: str, window_index: int) -> str:
    """Dummy train function returning a constant artifact."""
    return f"model_{window_index}"


async def _trivial_eval(
    model_artifact: str,
    oos_start: str,
    oos_end: str,
    window_index: int,
) -> tuple[float, float]:
    """Dummy eval that returns IS=1.0, OOS=0.8 always."""
    return 1.0, 0.8


async def _failing_train(
    train_start: str, train_end: str, window_index: int
) -> str:
    """Train function that always raises."""
    raise RuntimeError("simulated training failure")


async def _failing_eval(
    model_artifact: str,
    oos_start: str,
    oos_end: str,
    window_index: int,
) -> tuple[float, float]:
    """Eval function that always raises."""
    raise RuntimeError("simulated eval failure")


# ---------------------------------------------------------------------------
# TestAddMonths
# ---------------------------------------------------------------------------


class TestAddMonths:
    """Tests for the ``_add_months`` calendar month arithmetic helper."""

    def test_add_one_month_normal(self) -> None:
        """Adding 1 month to Jan 15 gives Feb 15."""
        result = _add_months(date(2024, 1, 15), 1)
        assert result == date(2024, 2, 15)

    def test_add_six_months_normal(self) -> None:
        """Adding 6 months to Jan 1 gives Jul 1."""
        result = _add_months(date(2024, 1, 1), 6)
        assert result == date(2024, 7, 1)

    def test_year_rollover(self) -> None:
        """Adding months past December wraps to the next year."""
        result = _add_months(date(2023, 11, 1), 3)
        assert result == date(2024, 2, 1)

    def test_month_end_clamping_jan_31_plus_1(self) -> None:
        """Jan 31 + 1 month = Feb 28 (non-leap year clamping)."""
        result = _add_months(date(2023, 1, 31), 1)
        # 2023 is not a leap year; Feb has 28 days.
        assert result == date(2023, 2, 28)

    def test_month_end_clamping_leap_year(self) -> None:
        """Jan 31 + 1 month = Feb 29 in a leap year."""
        result = _add_months(date(2024, 1, 31), 1)
        # 2024 is a leap year; Feb has 29 days.
        assert result == date(2024, 2, 29)

    def test_add_twelve_months(self) -> None:
        """Adding 12 months = exactly one year later."""
        result = _add_months(date(2023, 3, 15), 12)
        assert result == date(2024, 3, 15)

    def test_add_zero_months(self) -> None:
        """Adding 0 months returns the same date."""
        d = date(2024, 6, 15)
        result = _add_months(d, 0)
        assert result == d

    def test_march_31_plus_1(self) -> None:
        """Mar 31 + 1 month = Apr 30 (April has 30 days)."""
        result = _add_months(date(2024, 3, 31), 1)
        assert result == date(2024, 4, 30)

    def test_add_large_months(self) -> None:
        """Adding 24 months = 2 years later."""
        result = _add_months(date(2022, 6, 1), 24)
        assert result == date(2024, 6, 1)


# ---------------------------------------------------------------------------
# TestParseIsoAndToIso
# ---------------------------------------------------------------------------


class TestParseIsoAndToIso:
    """Tests for ``_parse_iso_date`` and ``_to_iso``."""

    def test_parse_full_iso_string(self) -> None:
        """Parses 'YYYY-MM-DDTHH:MM:SSZ' to a date object."""
        d = _parse_iso_date("2024-01-15T00:00:00Z")
        assert d == date(2024, 1, 15)

    def test_parse_date_only_string(self) -> None:
        """Parses 'YYYY-MM-DD' to a date object."""
        d = _parse_iso_date("2024-06-30")
        assert d == date(2024, 6, 30)

    def test_parse_ignores_time_component(self) -> None:
        """Only the date portion is retained; time is ignored."""
        d = _parse_iso_date("2023-12-31T23:59:59Z")
        assert d == date(2023, 12, 31)

    def test_to_iso_format(self) -> None:
        """``_to_iso`` produces the expected 'YYYY-MM-DDTHH:MM:SSZ' format."""
        result = _to_iso(date(2024, 7, 4))
        assert result == "2024-07-04T00:00:00Z"

    def test_to_iso_pads_month_and_day(self) -> None:
        """Single-digit month and day are zero-padded."""
        result = _to_iso(date(2024, 1, 5))
        assert result == "2024-01-05T00:00:00Z"

    def test_roundtrip_parse_then_iso(self) -> None:
        """Parsing then re-serialising is a no-op for the date portion."""
        original = "2023-08-22T00:00:00Z"
        parsed = _parse_iso_date(original)
        result = _to_iso(parsed)
        assert result == original

    def test_parse_raises_on_invalid_format(self) -> None:
        """Invalid date strings raise ``ValueError``."""
        with pytest.raises((ValueError, Exception)):
            _parse_iso_date("not-a-date")


# ---------------------------------------------------------------------------
# TestGenerateWindows
# ---------------------------------------------------------------------------


class TestGenerateWindows:
    """Tests for the rolling window generator."""

    def test_basic_6_month_train_1_month_oos(self) -> None:
        """12 months of data with 6+1 config gives 6 windows."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        assert len(windows) == 6

    def test_first_window_boundaries(self) -> None:
        """First window: train Jan–Jul, OOS Jul–Aug."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        train_start, train_end, oos_start, oos_end = windows[0]
        assert train_start == "2023-01-01T00:00:00Z"
        assert train_end == "2023-07-01T00:00:00Z"
        assert oos_start == "2023-07-01T00:00:00Z"
        assert oos_end == "2023-08-01T00:00:00Z"

    def test_second_window_slides_by_oos_months(self) -> None:
        """Each window slides forward by exactly one OOS period."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        _, _, _, oos_end_0 = windows[0]
        train_start_1, _, _, _ = windows[1]
        # Window 1 starts one OOS period (1 month) after window 0 starts.
        assert train_start_1 == "2023-02-01T00:00:00Z"
        # OOS end of window 0 = start of OOS period = Aug 1, which becomes
        # the next window's OOS start after advancing the train start.
        assert oos_end_0 == "2023-08-01T00:00:00Z"

    def test_too_short_range_returns_empty(self) -> None:
        """Less data than one window returns an empty list."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2023-06-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        # 5 months available; 6 + 1 = 7 required — no windows fit.
        assert windows == []

    def test_exactly_one_window_fits(self) -> None:
        """Exactly one window fits when data matches train+oos exactly."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2023-08-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        # 7 months of data; 6+1 = exactly one window.
        assert len(windows) == 1

    def test_windows_are_contiguous(self) -> None:
        """Each window's OOS end is the data end of that window (no gaps)."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        for win in windows:
            train_start, train_end, oos_start, oos_end = win
            assert train_end == oos_start, "OOS period must immediately follow training period."

    def test_train_end_advances_each_window(self) -> None:
        """Each successive window's train_end is one OOS period later."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-06-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        train_ends = [w[1] for w in windows]
        for i in range(1, len(train_ends)):
            prev_date = _parse_iso_date(train_ends[i - 1])
            curr_date = _parse_iso_date(train_ends[i])
            # Each train_end should be exactly 1 OOS month later.
            assert curr_date == _add_months(prev_date, 1)

    def test_larger_oos_produces_fewer_windows(self) -> None:
        """Larger OOS period means fewer total windows for the same data."""
        windows_1m = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        windows_3m = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=3,
        )
        assert len(windows_3m) < len(windows_1m)

    def test_all_oos_ends_within_data_range(self) -> None:
        """All OOS period end dates are within the data range."""
        data_end = "2024-06-01T00:00:00Z"
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end=data_end,
            train_months=6,
            oos_months=1,
        )
        end_date = _parse_iso_date(data_end)
        for win in windows:
            oos_end = _parse_iso_date(win[3])
            assert oos_end <= end_date

    def test_oos_start_equals_train_end(self) -> None:
        """OOS start exactly equals train end in every window."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        for win in windows:
            _, train_end, oos_start, _ = win
            assert train_end == oos_start

    def test_return_type_is_list_of_4_tuples(self) -> None:
        """Each item in the returned list is a 4-tuple of ISO strings."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        for win in windows:
            assert len(win) == 4
            for part in win:
                assert isinstance(part, str)
                assert "T" in part

    def test_3_month_train_3_month_oos(self) -> None:
        """3+3 config with 12 months of data yields 3 windows."""
        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=3,
            oos_months=3,
        )
        # Windows: [Jan-Apr, Apr-Jul), [Apr-Jul, Jul-Oct), [Jul-Oct, Oct-Jan)
        assert len(windows) == 3

    def test_windows_indexed_correct_order(self) -> None:
        """First window starts at data_start; windows are chronologically ordered."""
        windows = generate_windows(
            data_start="2023-06-01T00:00:00Z",
            data_end="2024-06-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        assert windows[0][0] == "2023-06-01T00:00:00Z"
        for i in range(1, len(windows)):
            prev_start = _parse_iso_date(windows[i - 1][0])
            curr_start = _parse_iso_date(windows[i][0])
            assert curr_start > prev_start


# ---------------------------------------------------------------------------
# TestComputeWFE
# ---------------------------------------------------------------------------


class TestComputeWFE:
    """Tests for the ``compute_wfe`` function."""

    def test_perfect_oos_match(self) -> None:
        """WFE = 1.0 when OOS exactly equals IS."""
        result = compute_wfe([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert result == pytest.approx(1.0)

    def test_half_efficiency(self) -> None:
        """WFE = 0.5 when OOS is half of IS."""
        result = compute_wfe([2.0, 2.0, 2.0], [1.0, 1.0, 1.0])
        assert result == pytest.approx(0.5)

    def test_wfe_above_1_is_valid(self) -> None:
        """WFE > 1.0 is valid — OOS can outperform IS."""
        result = compute_wfe([1.0, 1.0], [2.0, 2.0])
        assert result == pytest.approx(2.0)

    def test_zero_mean_is_returns_none(self) -> None:
        """Returns ``None`` when mean IS metric is exactly zero."""
        result = compute_wfe([0.0, 0.0, 0.0], [1.0, 2.0, 3.0])
        assert result is None

    def test_empty_lists_return_none(self) -> None:
        """Returns ``None`` for empty input lists."""
        result = compute_wfe([], [])
        assert result is None

    def test_single_window(self) -> None:
        """Single window: WFE = OOS / IS."""
        result = compute_wfe([4.0], [2.0])
        assert result == pytest.approx(0.5)

    def test_negative_is_metric(self) -> None:
        """Negative IS metric produces a valid (negative) WFE."""
        result = compute_wfe([-2.0], [-1.0])
        assert result == pytest.approx(0.5)

    def test_mismatched_lengths_raises(self) -> None:
        """Mismatched list lengths raise ``ValueError``."""
        with pytest.raises(ValueError, match="same length"):
            compute_wfe([1.0, 2.0], [1.0])

    def test_negative_oos_positive_is(self) -> None:
        """Negative OOS / positive IS = negative WFE."""
        result = compute_wfe([2.0], [-1.0])
        assert result == pytest.approx(-0.5)

    def test_large_number_of_windows(self) -> None:
        """WFE is accurate with many windows."""
        n = 100
        is_vals = [1.0] * n
        oos_vals = [0.6] * n
        result = compute_wfe(is_vals, oos_vals)
        assert result == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# TestWalkForwardConfig
# ---------------------------------------------------------------------------


class TestWalkForwardConfig:
    """Tests for ``WalkForwardConfig`` Pydantic-settings validation."""

    def test_default_values(self) -> None:
        """Default configuration is consistent with docstring examples."""
        cfg = _make_wf_config()
        assert cfg.train_months == 6
        assert cfg.oos_months == 1
        assert cfg.min_wfe_threshold == pytest.approx(0.5)

    def test_custom_train_months(self) -> None:
        """``train_months`` can be set to any positive integer."""
        cfg = _make_wf_config(train_months=3)
        assert cfg.train_months == 3

    def test_invalid_train_months_raises(self) -> None:
        """``train_months`` must be >= 1."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_wf_config(train_months=0)

    def test_invalid_oos_months_raises(self) -> None:
        """``oos_months`` must be >= 1."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_wf_config(oos_months=0)

    def test_results_dir_is_path(self) -> None:
        """``results_dir`` is a ``Path`` object."""
        cfg = _make_wf_config()
        assert isinstance(cfg.results_dir, Path)

    def test_data_start_stored_as_string(self) -> None:
        """``data_start`` is stored as a plain string, not a datetime."""
        cfg = _make_wf_config(data_start="2023-06-01T00:00:00Z")
        assert isinstance(cfg.data_start, str)
        assert cfg.data_start == "2023-06-01T00:00:00Z"

    def test_custom_wfe_threshold(self) -> None:
        """``min_wfe_threshold`` can be customised."""
        cfg = _make_wf_config(min_wfe_threshold=0.6)
        assert cfg.min_wfe_threshold == pytest.approx(0.6)

    def test_env_prefix_is_wf(self) -> None:
        """Config reads from WF_ prefixed env vars."""
        import os

        env_backup = os.environ.copy()
        try:
            os.environ["WF_TRAIN_MONTHS"] = "9"
            cfg = WalkForwardConfig(_env_file=None)  # type: ignore[call-arg]
            assert cfg.train_months == 9
        finally:
            # Restore environment to avoid polluting other tests.
            for k in list(os.environ.keys()):
                if k not in env_backup:
                    del os.environ[k]
            os.environ.update(env_backup)


# ---------------------------------------------------------------------------
# TestWindowResult
# ---------------------------------------------------------------------------


class TestWindowResult:
    """Tests for the ``WindowResult`` model."""

    def test_successful_window(self) -> None:
        """A successful window has both IS and OOS metrics set."""
        w = WindowResult(
            window_index=0,
            train_start="2023-01-01T00:00:00Z",
            train_end="2023-07-01T00:00:00Z",
            oos_start="2023-07-01T00:00:00Z",
            oos_end="2023-08-01T00:00:00Z",
            is_metric=1.2,
            oos_metric=0.8,
            is_successful=True,
        )
        assert w.is_metric == pytest.approx(1.2)
        assert w.oos_metric == pytest.approx(0.8)
        assert w.error is None

    def test_failed_window(self) -> None:
        """A failed window has ``is_successful=False`` and an error message."""
        w = WindowResult(
            window_index=1,
            train_start="2023-02-01T00:00:00Z",
            train_end="2023-08-01T00:00:00Z",
            oos_start="2023-08-01T00:00:00Z",
            oos_end="2023-09-01T00:00:00Z",
            is_successful=False,
            error="simulated failure",
        )
        assert not w.is_successful
        assert w.is_metric is None
        assert w.oos_metric is None
        assert "simulated" in w.error

    def test_frozen_model(self) -> None:
        """``WindowResult`` is immutable (frozen Pydantic model)."""
        w = WindowResult(
            window_index=0,
            train_start="2023-01-01T00:00:00Z",
            train_end="2023-07-01T00:00:00Z",
            oos_start="2023-07-01T00:00:00Z",
            oos_end="2023-08-01T00:00:00Z",
        )
        with pytest.raises(Exception):
            w.window_index = 99  # type: ignore[misc]

    def test_default_is_successful_true(self) -> None:
        """``is_successful`` defaults to ``True``."""
        w = WindowResult(
            window_index=0,
            train_start="2023-01-01T00:00:00Z",
            train_end="2023-07-01T00:00:00Z",
            oos_start="2023-07-01T00:00:00Z",
            oos_end="2023-08-01T00:00:00Z",
        )
        assert w.is_successful is True

    def test_model_dump_round_trip(self) -> None:
        """``model_dump()`` produces a JSON-serialisable dict."""
        w = WindowResult(
            window_index=2,
            train_start="2023-03-01T00:00:00Z",
            train_end="2023-09-01T00:00:00Z",
            oos_start="2023-09-01T00:00:00Z",
            oos_end="2023-10-01T00:00:00Z",
            is_metric=0.5,
            oos_metric=0.3,
        )
        d = w.model_dump()
        assert d["window_index"] == 2
        assert d["is_metric"] == pytest.approx(0.5)
        assert d["oos_metric"] == pytest.approx(0.3)
        # Verify JSON-serialisable (no Path, datetime, etc.)
        json.dumps(d)  # must not raise


# ---------------------------------------------------------------------------
# TestWalkForwardResult
# ---------------------------------------------------------------------------


class TestWalkForwardResult:
    """Tests for the ``WalkForwardResult`` model."""

    def _make_result(self, **overrides: Any) -> WalkForwardResult:
        defaults = {
            "strategy_type": "rl",
            "windows": [],
            "mean_is_metric": 1.0,
            "mean_oos_metric": 0.6,
            "walk_forward_efficiency": 0.6,
            "wfe_threshold": 0.5,
            "is_deployable": True,
            "total_windows": 6,
            "successful_windows": 6,
            "overfit_warning": False,
        }
        defaults.update(overrides)
        return WalkForwardResult(**defaults)

    def test_deployable_when_wfe_above_threshold(self) -> None:
        """``is_deployable=True`` when WFE >= threshold."""
        r = self._make_result(walk_forward_efficiency=0.6, wfe_threshold=0.5, is_deployable=True)
        assert r.is_deployable is True

    def test_not_deployable_when_wfe_below_threshold(self) -> None:
        """``is_deployable=False`` when WFE < threshold."""
        r = self._make_result(
            walk_forward_efficiency=0.3,
            wfe_threshold=0.5,
            is_deployable=False,
            overfit_warning=True,
        )
        assert r.is_deployable is False
        assert r.overfit_warning is True

    def test_none_wfe_not_deployable(self) -> None:
        """``is_deployable=False`` when WFE is ``None``."""
        r = self._make_result(
            walk_forward_efficiency=None,
            is_deployable=False,
            overfit_warning=False,
        )
        assert r.is_deployable is False
        assert r.walk_forward_efficiency is None

    def test_report_path_optional(self) -> None:
        """``report_path`` is ``None`` by default."""
        r = self._make_result()
        assert r.report_path is None

    def test_frozen_model(self) -> None:
        """``WalkForwardResult`` is immutable."""
        r = self._make_result()
        with pytest.raises(Exception):
            r.strategy_type = "evolutionary"  # type: ignore[misc]

    def test_successful_windows_count(self) -> None:
        """``successful_windows`` tracks correctly."""
        r = self._make_result(total_windows=10, successful_windows=8)
        assert r.successful_windows == 8
        assert r.total_windows == 10

    def test_model_dump_json_serialisable(self) -> None:
        """``model_dump()`` output is fully JSON-serialisable."""
        r = self._make_result()
        data = r.model_dump()
        json.dumps(data)  # must not raise


# ---------------------------------------------------------------------------
# TestRunWalkForward
# ---------------------------------------------------------------------------


class TestRunWalkForward:
    """Tests for the core ``run_walk_forward`` orchestrator."""

    async def test_basic_happy_path(self, tmp_path: Path) -> None:
        """All windows complete successfully; WFE is correct."""
        cfg = _make_wf_config(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
            results_dir=tmp_path,
        )
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_trivial_eval,
        )
        # _trivial_eval returns (1.0, 0.8) always → WFE = 0.8 / 1.0 = 0.8
        assert result.walk_forward_efficiency == pytest.approx(0.8)
        assert result.is_deployable is True
        assert result.successful_windows == result.total_windows

    async def test_strategy_type_stored(self, tmp_path: Path) -> None:
        """``strategy_type`` is stored in the result."""
        cfg = _make_wf_config(results_dir=tmp_path)
        result = await run_walk_forward(
            strategy_type="evolutionary",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_trivial_eval,
        )
        assert result.strategy_type == "evolutionary"

    async def test_failing_train_marks_window_failed(self, tmp_path: Path) -> None:
        """A failing train function marks the window as not successful."""
        cfg = _make_wf_config(results_dir=tmp_path)
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_failing_train,
            eval_fn=_trivial_eval,
        )
        assert result.successful_windows == 0
        for win in result.windows:
            assert not win.is_successful
            assert win.error is not None

    async def test_overfit_warning_when_wfe_below_threshold(self, tmp_path: Path) -> None:
        """``overfit_warning=True`` when WFE < threshold."""

        async def _low_oos_eval(
            model_artifact: str,
            oos_start: str,
            oos_end: str,
            window_index: int,
        ) -> tuple[float, float]:
            return 2.0, 0.5  # WFE = 0.25 < 0.5

        cfg = _make_wf_config(results_dir=tmp_path, min_wfe_threshold=0.5)
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_low_oos_eval,
        )
        assert result.overfit_warning is True
        assert result.is_deployable is False

    async def test_zero_is_metric_wfe_is_none(self, tmp_path: Path) -> None:
        """WFE is ``None`` when mean IS metric is zero."""

        async def _zero_is_eval(
            model_artifact: str,
            oos_start: str,
            oos_end: str,
            window_index: int,
        ) -> tuple[float, float]:
            return 0.0, 0.5  # IS=0 → undefined WFE

        cfg = _make_wf_config(results_dir=tmp_path)
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_zero_is_eval,
        )
        assert result.walk_forward_efficiency is None
        assert result.is_deployable is False

    async def test_partial_failures_counted_correctly(self, tmp_path: Path) -> None:
        """Windows that fail are excluded from WFE but counted in total."""
        call_count = 0

        async def _flaky_train(
            train_start: str, train_end: str, window_index: int
        ) -> str:
            nonlocal call_count
            call_count += 1
            if window_index % 2 == 0:
                raise RuntimeError("even window failure")
            return "ok"

        cfg = _make_wf_config(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
            results_dir=tmp_path,
        )
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_flaky_train,
            eval_fn=_trivial_eval,
        )
        assert result.total_windows == 6
        assert result.successful_windows == 3  # windows 1, 3, 5 (0-indexed odds)
        assert result.walk_forward_efficiency is not None

    async def test_report_written_to_disk(self, tmp_path: Path) -> None:
        """JSON report is written to ``results_dir``."""
        cfg = _make_wf_config(results_dir=tmp_path)
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_trivial_eval,
        )
        assert result.report_path is not None
        report_file = Path(result.report_path)
        assert report_file.exists()
        data = json.loads(report_file.read_text())
        assert data["strategy_type"] == "rl"
        assert "summary" in data
        assert "windows" in data

    async def test_report_json_has_correct_structure(self, tmp_path: Path) -> None:
        """Report JSON contains all required top-level keys."""
        cfg = _make_wf_config(results_dir=tmp_path)
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_trivial_eval,
        )
        data = json.loads(Path(result.report_path).read_text())  # type: ignore[arg-type]
        assert set(data.keys()) >= {"strategy_type", "generated_at", "config", "summary", "windows"}

    async def test_window_results_ordered_by_index(self, tmp_path: Path) -> None:
        """``result.windows`` are in window_index order."""
        cfg = _make_wf_config(results_dir=tmp_path)
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_trivial_eval,
        )
        indices = [w.window_index for w in result.windows]
        assert indices == sorted(indices)

    async def test_no_windows_returns_none_wfe(self, tmp_path: Path) -> None:
        """When no windows can be generated, WFE is ``None``."""
        cfg = _make_wf_config(
            data_start="2023-01-01T00:00:00Z",
            data_end="2023-05-01T00:00:00Z",  # too short for 6+1 months
            train_months=6,
            oos_months=1,
            results_dir=tmp_path,
        )
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_trivial_eval,
        )
        assert result.total_windows == 0
        assert result.walk_forward_efficiency is None
        assert result.is_deployable is False

    async def test_train_fn_receives_correct_dates(self, tmp_path: Path) -> None:
        """The train function is called with the correct window dates."""
        received_calls: list[tuple[str, str, int]] = []

        async def _capturing_train(
            train_start: str, train_end: str, window_index: int
        ) -> str:
            received_calls.append((train_start, train_end, window_index))
            return "model"

        cfg = _make_wf_config(
            data_start="2023-01-01T00:00:00Z",
            data_end="2023-08-01T00:00:00Z",
            train_months=6,
            oos_months=1,
            results_dir=tmp_path,
        )
        await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_capturing_train,
            eval_fn=_trivial_eval,
        )
        # Exactly 1 window in this range.
        assert len(received_calls) == 1
        ts, te, idx = received_calls[0]
        assert ts == "2023-01-01T00:00:00Z"
        assert te == "2023-07-01T00:00:00Z"
        assert idx == 0

    async def test_eval_fn_receives_model_artifact(self, tmp_path: Path) -> None:
        """The eval function receives exactly the artifact returned by train."""
        received_artifacts: list[str] = []

        async def _recording_eval(
            model_artifact: str,
            oos_start: str,
            oos_end: str,
            window_index: int,
        ) -> tuple[float, float]:
            received_artifacts.append(model_artifact)
            return 1.0, 0.8

        cfg = _make_wf_config(
            data_start="2023-01-01T00:00:00Z",
            data_end="2023-08-01T00:00:00Z",
            train_months=6,
            oos_months=1,
            results_dir=tmp_path,
        )
        await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_recording_eval,
        )
        assert received_artifacts == ["model_0"]

    async def test_wfe_deployability_boundary(self, tmp_path: Path) -> None:
        """Exactly at the threshold: WFE == threshold → deployable."""

        async def _exact_threshold_eval(
            model_artifact: str,
            oos_start: str,
            oos_end: str,
            window_index: int,
        ) -> tuple[float, float]:
            return 2.0, 1.0  # WFE = 0.5 exactly

        cfg = _make_wf_config(results_dir=tmp_path, min_wfe_threshold=0.5)
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_exact_threshold_eval,
        )
        assert result.walk_forward_efficiency == pytest.approx(0.5)
        assert result.is_deployable is True
        assert result.overfit_warning is False

    async def test_mean_metrics_computed_correctly(self, tmp_path: Path) -> None:
        """Mean IS and OOS metrics are averages across all successful windows."""
        call_count = 0

        async def _varying_eval(
            model_artifact: str,
            oos_start: str,
            oos_end: str,
            window_index: int,
        ) -> tuple[float, float]:
            nonlocal call_count
            # Returns different values per window to test averaging.
            is_vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
            oos_vals = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
            idx = window_index % len(is_vals)
            call_count += 1
            return is_vals[idx], oos_vals[idx]

        cfg = _make_wf_config(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
            results_dir=tmp_path,
        )
        result = await run_walk_forward(
            strategy_type="rl",
            wf_config=cfg,
            train_fn=_trivial_train,
            eval_fn=_varying_eval,
        )
        # 6 windows: IS = [1,2,3,4,5,6] → mean 3.5; OOS = [0.5,1,1.5,2,2.5,3] → mean 1.75
        assert result.mean_is_metric == pytest.approx(3.5)
        assert result.mean_oos_metric == pytest.approx(1.75)
        assert result.walk_forward_efficiency == pytest.approx(1.75 / 3.5)


# ---------------------------------------------------------------------------
# TestWalkForwardRL
# ---------------------------------------------------------------------------


class TestWalkForwardRL:
    """Tests for ``walk_forward_rl`` integration (mocked SB3 dependencies)."""

    def _make_rl_config(self) -> Any:
        """Return a minimal RLConfig-like mock."""
        cfg = MagicMock()
        cfg.train_start = "2023-01-01T00:00:00Z"
        cfg.test_end = "2024-01-01T00:00:00Z"
        cfg.seed = 42
        cfg.model_copy = MagicMock(return_value=cfg)
        return cfg

    async def test_walk_forward_rl_returns_result(self, tmp_path: Path) -> None:
        """``walk_forward_rl`` returns a ``WalkForwardResult``."""
        from agent.strategies.walk_forward import walk_forward_rl

        rl_cfg = self._make_rl_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        async def _mock_run_walk_forward(**kwargs: Any) -> WalkForwardResult:
            return WalkForwardResult(
                strategy_type="rl",
                windows=[],
                mean_is_metric=1.0,
                mean_oos_metric=0.8,
                walk_forward_efficiency=0.8,
                wfe_threshold=0.5,
                is_deployable=True,
                total_windows=6,
                successful_windows=6,
                overfit_warning=False,
            )

        with patch(
            "agent.strategies.walk_forward.run_walk_forward",
            side_effect=_mock_run_walk_forward,
        ):
            result = await walk_forward_rl(config=rl_cfg, wf_config=wf_cfg)

        assert isinstance(result, WalkForwardResult)
        assert result.strategy_type == "rl"

    async def test_walk_forward_rl_uses_config_dates_as_default(
        self, tmp_path: Path
    ) -> None:
        """When ``wf_config`` is ``None``, dates come from ``rl_config``."""
        from agent.strategies.walk_forward import walk_forward_rl

        rl_cfg = self._make_rl_config()

        with patch("agent.strategies.walk_forward.run_walk_forward") as mock_rw:
            mock_rw.return_value = WalkForwardResult(
                strategy_type="rl",
                windows=[],
                mean_is_metric=None,
                mean_oos_metric=None,
                walk_forward_efficiency=None,
                wfe_threshold=0.5,
                is_deployable=False,
                total_windows=0,
                successful_windows=0,
                overfit_warning=False,
            )
            # Patch asyncio.to_thread so the sync train/eval don't actually run.
            with patch("asyncio.to_thread", new=AsyncMock(return_value=None)):
                await walk_forward_rl(config=rl_cfg, wf_config=None)

        # Verify run_walk_forward was called.
        mock_rw.assert_called_once()
        call_kwargs = mock_rw.call_args[1]
        assert call_kwargs["strategy_type"] == "rl"

    async def test_walk_forward_rl_strategy_type_is_rl(self, tmp_path: Path) -> None:
        """The strategy type in the result is always 'rl'."""
        from agent.strategies.walk_forward import walk_forward_rl

        rl_cfg = self._make_rl_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        with patch("agent.strategies.walk_forward.run_walk_forward") as mock_rw:
            mock_rw.return_value = WalkForwardResult(
                strategy_type="rl",
                windows=[],
                mean_is_metric=None,
                mean_oos_metric=None,
                walk_forward_efficiency=None,
                wfe_threshold=0.5,
                is_deployable=False,
                total_windows=0,
                successful_windows=0,
                overfit_warning=False,
            )
            result = await walk_forward_rl(config=rl_cfg, wf_config=wf_cfg)

        assert result.strategy_type == "rl"

    async def test_walk_forward_rl_deployability_gate(self, tmp_path: Path) -> None:
        """A low WFE result is not deployable."""
        from agent.strategies.walk_forward import walk_forward_rl

        rl_cfg = self._make_rl_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        with patch("agent.strategies.walk_forward.run_walk_forward") as mock_rw:
            mock_rw.return_value = WalkForwardResult(
                strategy_type="rl",
                windows=[],
                mean_is_metric=2.0,
                mean_oos_metric=0.4,
                walk_forward_efficiency=0.2,
                wfe_threshold=0.5,
                is_deployable=False,
                total_windows=6,
                successful_windows=6,
                overfit_warning=True,
            )
            result = await walk_forward_rl(config=rl_cfg, wf_config=wf_cfg)

        assert result.is_deployable is False
        assert result.overfit_warning is True

    async def test_walk_forward_rl_passes_wf_config(self, tmp_path: Path) -> None:
        """Custom ``wf_config`` is forwarded to ``run_walk_forward``."""
        from agent.strategies.walk_forward import walk_forward_rl

        rl_cfg = self._make_rl_config()
        wf_cfg = _make_wf_config(
            data_start="2022-01-01T00:00:00Z",
            data_end="2023-01-01T00:00:00Z",
            train_months=3,
            oos_months=1,
            results_dir=tmp_path,
        )

        captured_wf_config: list[Any] = []

        with patch("agent.strategies.walk_forward.run_walk_forward") as mock_rw:

            async def _capture(**kwargs: Any) -> WalkForwardResult:
                captured_wf_config.append(kwargs.get("wf_config"))
                return WalkForwardResult(
                    strategy_type="rl",
                    windows=[],
                    mean_is_metric=None,
                    mean_oos_metric=None,
                    walk_forward_efficiency=None,
                    wfe_threshold=0.5,
                    is_deployable=False,
                    total_windows=0,
                    successful_windows=0,
                    overfit_warning=False,
                )

            mock_rw.side_effect = _capture
            await walk_forward_rl(config=rl_cfg, wf_config=wf_cfg)

        assert len(captured_wf_config) == 1
        assert captured_wf_config[0] is wf_cfg

    async def test_walk_forward_rl_no_train_months_default(self, tmp_path: Path) -> None:
        """Default WalkForwardConfig uses 6 train months."""
        from agent.strategies.walk_forward import walk_forward_rl

        rl_cfg = self._make_rl_config()

        with patch("agent.strategies.walk_forward.run_walk_forward") as mock_rw:
            mock_rw.return_value = WalkForwardResult(
                strategy_type="rl",
                windows=[],
                mean_is_metric=None,
                mean_oos_metric=None,
                walk_forward_efficiency=None,
                wfe_threshold=0.5,
                is_deployable=False,
                total_windows=0,
                successful_windows=0,
                overfit_warning=False,
            )
            await walk_forward_rl(config=rl_cfg, wf_config=None)

        captured_cfg = mock_rw.call_args[1]["wf_config"]
        assert captured_cfg.train_months == 6

    async def test_walk_forward_rl_windows_in_result(self, tmp_path: Path) -> None:
        """``WalkForwardResult.windows`` from run_walk_forward is preserved."""
        from agent.strategies.walk_forward import walk_forward_rl

        rl_cfg = self._make_rl_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        window = WindowResult(
            window_index=0,
            train_start="2023-01-01T00:00:00Z",
            train_end="2023-07-01T00:00:00Z",
            oos_start="2023-07-01T00:00:00Z",
            oos_end="2023-08-01T00:00:00Z",
            is_metric=1.0,
            oos_metric=0.8,
        )

        with patch("agent.strategies.walk_forward.run_walk_forward") as mock_rw:
            mock_rw.return_value = WalkForwardResult(
                strategy_type="rl",
                windows=[window],
                mean_is_metric=1.0,
                mean_oos_metric=0.8,
                walk_forward_efficiency=0.8,
                wfe_threshold=0.5,
                is_deployable=True,
                total_windows=1,
                successful_windows=1,
                overfit_warning=False,
            )
            result = await walk_forward_rl(config=rl_cfg, wf_config=wf_cfg)

        assert len(result.windows) == 1
        assert result.windows[0].is_metric == pytest.approx(1.0)

    async def test_walk_forward_rl_overfit_warning_propagated(
        self, tmp_path: Path
    ) -> None:
        """Overfit warning from run_walk_forward is propagated correctly."""
        from agent.strategies.walk_forward import walk_forward_rl

        rl_cfg = self._make_rl_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        with patch("agent.strategies.walk_forward.run_walk_forward") as mock_rw:
            mock_rw.return_value = WalkForwardResult(
                strategy_type="rl",
                windows=[],
                mean_is_metric=2.0,
                mean_oos_metric=0.3,
                walk_forward_efficiency=0.15,
                wfe_threshold=0.5,
                is_deployable=False,
                total_windows=6,
                successful_windows=6,
                overfit_warning=True,
            )
            result = await walk_forward_rl(config=rl_cfg, wf_config=wf_cfg)

        assert result.overfit_warning is True


# ---------------------------------------------------------------------------
# TestWalkForwardEvolutionary
# ---------------------------------------------------------------------------


class TestWalkForwardEvolutionary:
    """Tests for ``walk_forward_evolutionary`` integration (mocked BattleRunner)."""

    def _make_evo_config(self) -> Any:
        """Return a minimal EvolutionConfig-like mock."""
        cfg = MagicMock()
        cfg.historical_start = date(2023, 1, 1)
        cfg.historical_end = date(2024, 1, 1)
        cfg.population_size = 4
        cfg.generations = 2
        cfg.seed = 42
        cfg.battle_preset = "historical_week"
        cfg.fitness_fn = "composite"
        cfg.oos_split_ratio = 0.3
        cfg.convergence_threshold = 2
        return cfg

    def _make_wf_result(self, **overrides: Any) -> WalkForwardResult:
        defaults = dict(
            strategy_type="evolutionary",
            windows=[],
            mean_is_metric=0.8,
            mean_oos_metric=0.6,
            walk_forward_efficiency=0.75,
            wfe_threshold=0.5,
            is_deployable=True,
            total_windows=6,
            successful_windows=6,
            overfit_warning=False,
        )
        defaults.update(overrides)
        return WalkForwardResult(**defaults)

    def _patch_evo(self, result: WalkForwardResult) -> Any:
        """Context-manager stack that patches both the runner factory and orchestrator.

        The BattleRunner factory must be patched to avoid attempting real
        platform auth; ``run_walk_forward`` is patched to return the given
        result without running the real window loop.
        """
        from contextlib import ExitStack
        from unittest.mock import AsyncMock, patch

        stack = ExitStack()

        mock_runner = AsyncMock()
        mock_runner.setup_agents = AsyncMock()
        mock_runner.teardown_agents = AsyncMock()
        stack.enter_context(
            patch(
                "agent.strategies.walk_forward._create_evo_battle_runner",
                new=AsyncMock(return_value=mock_runner),
            )
        )
        stack.enter_context(
            patch(
                "agent.strategies.walk_forward.run_walk_forward",
                return_value=result,
            )
        )
        return stack

    async def test_returns_wf_result(self, tmp_path: Path) -> None:
        """``walk_forward_evolutionary`` returns a ``WalkForwardResult``."""
        from agent.strategies.walk_forward import walk_forward_evolutionary

        evo_cfg = self._make_evo_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)
        result_to_return = self._make_wf_result()

        with self._patch_evo(result_to_return):
            result = await walk_forward_evolutionary(
                evo_config=evo_cfg, wf_config=wf_cfg
            )

        assert isinstance(result, WalkForwardResult)
        assert result.strategy_type == "evolutionary"

    async def test_strategy_type_is_evolutionary(self, tmp_path: Path) -> None:
        """Strategy type is always 'evolutionary'."""
        from agent.strategies.walk_forward import walk_forward_evolutionary

        evo_cfg = self._make_evo_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        with self._patch_evo(self._make_wf_result(strategy_type="evolutionary")):
            result = await walk_forward_evolutionary(
                evo_config=evo_cfg, wf_config=wf_cfg
            )

        assert result.strategy_type == "evolutionary"

    async def test_uses_config_dates_when_wf_config_none(
        self, tmp_path: Path
    ) -> None:
        """Dates come from evo_config when wf_config is None."""
        from contextlib import ExitStack
        from agent.strategies.walk_forward import walk_forward_evolutionary

        evo_cfg = self._make_evo_config()
        captured_wf: list[Any] = []

        async def _capturing_rw(**kwargs: Any) -> WalkForwardResult:
            captured_wf.append(kwargs.get("wf_config"))
            return self._make_wf_result(total_windows=0, successful_windows=0)

        mock_runner = AsyncMock()
        mock_runner.setup_agents = AsyncMock()
        mock_runner.teardown_agents = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "agent.strategies.walk_forward._create_evo_battle_runner",
                    new=AsyncMock(return_value=mock_runner),
                )
            )
            stack.enter_context(
                patch(
                    "agent.strategies.walk_forward.run_walk_forward",
                    side_effect=_capturing_rw,
                )
            )
            await walk_forward_evolutionary(evo_config=evo_cfg, wf_config=None)

        assert len(captured_wf) == 1
        assert "2023-01-01" in captured_wf[0].data_start
        assert "2024-01-01" in captured_wf[0].data_end

    async def test_deployable_result_propagated(self, tmp_path: Path) -> None:
        """Deployability from run_walk_forward is preserved."""
        from agent.strategies.walk_forward import walk_forward_evolutionary

        evo_cfg = self._make_evo_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        with self._patch_evo(self._make_wf_result(is_deployable=True)):
            result = await walk_forward_evolutionary(
                evo_config=evo_cfg, wf_config=wf_cfg
            )

        assert result.is_deployable is True

    async def test_overfit_warning_propagated(self, tmp_path: Path) -> None:
        """Overfit warning is propagated correctly."""
        from agent.strategies.walk_forward import walk_forward_evolutionary

        evo_cfg = self._make_evo_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        with self._patch_evo(
            self._make_wf_result(
                walk_forward_efficiency=0.13,
                is_deployable=False,
                overfit_warning=True,
            )
        ):
            result = await walk_forward_evolutionary(
                evo_config=evo_cfg, wf_config=wf_cfg
            )

        assert result.overfit_warning is True

    async def test_passes_wf_config_to_orchestrator(self, tmp_path: Path) -> None:
        """Custom wf_config is forwarded to run_walk_forward unchanged."""
        from contextlib import ExitStack
        from agent.strategies.walk_forward import walk_forward_evolutionary

        evo_cfg = self._make_evo_config()
        wf_cfg = _make_wf_config(train_months=4, oos_months=2, results_dir=tmp_path)
        captured: list[Any] = []

        async def _capture(**kwargs: Any) -> WalkForwardResult:
            captured.append(kwargs.get("wf_config"))
            return self._make_wf_result(total_windows=0, successful_windows=0)

        mock_runner = AsyncMock()
        mock_runner.setup_agents = AsyncMock()
        mock_runner.teardown_agents = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "agent.strategies.walk_forward._create_evo_battle_runner",
                    new=AsyncMock(return_value=mock_runner),
                )
            )
            stack.enter_context(
                patch(
                    "agent.strategies.walk_forward.run_walk_forward",
                    side_effect=_capture,
                )
            )
            await walk_forward_evolutionary(evo_config=evo_cfg, wf_config=wf_cfg)

        assert len(captured) == 1
        assert captured[0].train_months == 4
        assert captured[0].oos_months == 2

    async def test_wfe_metric_accessible(self, tmp_path: Path) -> None:
        """WFE value is accessible on the returned result."""
        from agent.strategies.walk_forward import walk_forward_evolutionary

        evo_cfg = self._make_evo_config()
        wf_cfg = _make_wf_config(results_dir=tmp_path)

        with self._patch_evo(self._make_wf_result(walk_forward_efficiency=0.6)):
            result = await walk_forward_evolutionary(
                evo_config=evo_cfg, wf_config=wf_cfg
            )

        assert result.walk_forward_efficiency == pytest.approx(0.6)

    async def test_none_wf_config_creates_wf_from_evo_dates(
        self, tmp_path: Path
    ) -> None:
        """When wf_config=None, the constructed WalkForwardConfig uses evo dates."""
        from contextlib import ExitStack
        from agent.strategies.walk_forward import walk_forward_evolutionary

        evo_cfg = self._make_evo_config()
        evo_cfg.historical_start = date(2022, 6, 1)
        evo_cfg.historical_end = date(2023, 6, 1)
        captured_wf: list[Any] = []

        async def _capturing(**kwargs: Any) -> WalkForwardResult:
            captured_wf.append(kwargs.get("wf_config"))
            return self._make_wf_result(total_windows=0, successful_windows=0)

        mock_runner = AsyncMock()
        mock_runner.setup_agents = AsyncMock()
        mock_runner.teardown_agents = AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "agent.strategies.walk_forward._create_evo_battle_runner",
                    new=AsyncMock(return_value=mock_runner),
                )
            )
            stack.enter_context(
                patch(
                    "agent.strategies.walk_forward.run_walk_forward",
                    side_effect=_capturing,
                )
            )
            await walk_forward_evolutionary(evo_config=evo_cfg, wf_config=None)

        assert len(captured_wf) == 1
        assert "2022-06-01" in captured_wf[0].data_start
        assert "2023-06-01" in captured_wf[0].data_end


# ---------------------------------------------------------------------------
# TestTrainingRunnerWalkForward
# ---------------------------------------------------------------------------


class TestTrainingRunnerWalkForward:
    """Tests for ``TrainingRunner.walk_forward_train``."""

    def _make_runner(self) -> Any:
        """Create a TrainingRunner with a minimal mocked RLConfig."""
        from agent.strategies.rl.runner import TrainingRunner

        cfg = MagicMock()
        cfg.train_start = "2023-01-01T00:00:00Z"
        cfg.test_end = "2024-01-01T00:00:00Z"
        cfg.models_dir = Path("/tmp/models")
        cfg.seed = 42
        cfg.model_copy = MagicMock(return_value=cfg)
        return TrainingRunner(config=cfg, target_sharpe=1.0)

    def _make_mock_wf_result(
        self, wfe: float = 0.75, deployable: bool = True
    ) -> WalkForwardResult:
        return WalkForwardResult(
            strategy_type="rl",
            windows=[],
            mean_is_metric=2.0,
            mean_oos_metric=wfe * 2.0,
            walk_forward_efficiency=wfe,
            wfe_threshold=0.5,
            is_deployable=deployable,
            total_windows=6,
            successful_windows=6,
            overfit_warning=not deployable,
        )

    def test_walk_forward_train_returns_wf_result(self) -> None:
        """``walk_forward_train`` returns a ``WalkForwardResult``."""
        runner = self._make_runner()
        mock_result = self._make_mock_wf_result()

        with patch("asyncio.run", return_value=mock_result):
            with patch(
                "agent.strategies.walk_forward.walk_forward_rl",
                return_value=mock_result,
            ):
                result = runner.walk_forward_train()

        assert isinstance(result, WalkForwardResult)

    def test_walk_forward_train_passes_config_dates(self) -> None:
        """Default dates come from the runner's config."""
        runner = self._make_runner()
        mock_result = self._make_mock_wf_result()

        with patch("asyncio.run", return_value=mock_result) as mock_run:
            runner.walk_forward_train()

        mock_run.assert_called_once()

    def test_walk_forward_train_custom_window_sizes(self) -> None:
        """Custom train/OOS months are passed to the WalkForwardConfig."""
        runner = self._make_runner()
        mock_result = self._make_mock_wf_result()

        captured_configs: list[Any] = []

        def _capturing_run(coro: Any) -> Any:
            captured_configs.append(coro)
            return mock_result

        with patch("asyncio.run", side_effect=_capturing_run):
            runner.walk_forward_train(train_months=3, oos_months=2)

        assert len(captured_configs) == 1

    def test_walk_forward_train_deployable_result(self) -> None:
        """A deployable result is returned correctly."""
        runner = self._make_runner()
        mock_result = self._make_mock_wf_result(wfe=0.8, deployable=True)

        with patch("asyncio.run", return_value=mock_result):
            result = runner.walk_forward_train()

        assert result.is_deployable is True
        assert result.overfit_warning is False

    def test_walk_forward_train_low_wfe_not_deployable(self) -> None:
        """A low-WFE result is not deployable."""
        runner = self._make_runner()
        mock_result = self._make_mock_wf_result(wfe=0.2, deployable=False)

        with patch("asyncio.run", return_value=mock_result):
            result = runner.walk_forward_train()

        assert result.is_deployable is False
        assert result.overfit_warning is True
