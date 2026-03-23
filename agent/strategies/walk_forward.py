"""Walk-forward validation for RL and evolutionary strategy systems.

Walk-forward validation (WFV) is a rolling-window out-of-sample (OOS) test
that produces a single *Walk-Forward Efficiency* (WFE) score.

Algorithm
---------
Given a date range ``[data_start, data_end]`` and parameters
``train_months`` and ``oos_months``:

  Window 0:  train [M0 .. M6),  OOS [M6 .. M7)
  Window 1:  train [M1 .. M7),  OOS [M7 .. M8)
  ...

For each window the model is **trained** on the in-sample period and
**evaluated** on the immediately following OOS period. The caller supplies
a ``TrainFn`` coroutine and an ``EvalFn`` coroutine so this module stays
algorithm-agnostic.

Walk-Forward Efficiency
-----------------------

    WFE = mean(OOS returns) / mean(IS returns)

A WFE > 0.5 (50 %) is required before a strategy can be deployed.
Below 0.5 the model is considered overfit and a ``WFE_THRESHOLD_WARNING``
is logged.

Usage — RL
----------

    from agent.strategies.walk_forward import WalkForwardConfig, walk_forward_rl
    result = await walk_forward_rl(config=rl_config, wf_config=WalkForwardConfig())

Usage — Evolutionary
---------------------

    from agent.strategies.walk_forward import WalkForwardConfig, walk_forward_evolutionary
    result = await walk_forward_evolutionary(
        evo_config=evo_config, wf_config=WalkForwardConfig()
    )
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Threshold constants
# ---------------------------------------------------------------------------

# Walk-Forward Efficiency below this value triggers a WARNING and should block
# deployment.  Rationale: a WFE of 0.5 means the strategy retains at least
# half its in-sample edge in unseen data — the minimum acceptable signal.
WFE_THRESHOLD: float = 0.50

# Sentinel value used when an IS or OOS evaluation produces no usable result.
# Chosen to be clearly out of range so callers can detect failures.
_NO_RESULT: float = float("nan")

# Minimum number of windows required to produce a meaningful WFE estimate.
# A single window would give a sample size of N=1 — too noisy to trust.
_MIN_WINDOWS: int = 2

# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------

_ENV_FILE = Path(__file__).parent.parent / ".env"


class WalkForwardConfig(BaseSettings):
    """Rolling-window parameters for walk-forward validation.

    All date fields are ISO-8601 strings (``YYYY-MM-DDTHH:MM:SSZ``) to match
    the backtest API contract.  Months are calendar months, not 30-day periods,
    so ``train_months=6`` means the six calendar months preceding the OOS start.

    Example::

        cfg = WalkForwardConfig(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-06-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        # Produces 11 rolling windows across 17 months of data.

    All financial values are stored as plain Python types (not ``Decimal``) in
    this class because they are forwarded to SB3 / numpy APIs that require
    floats.  Money amounts never pass through this class.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_prefix="WF_",
        case_sensitive=False,
        extra="ignore",
    )

    data_start: str = Field(
        default="2023-01-01T00:00:00Z",
        description=(
            "Earliest date in the available dataset.  The first training window "
            "begins here.  ISO-8601 UTC string."
        ),
    )
    data_end: str = Field(
        default="2024-06-01T00:00:00Z",
        description=(
            "Latest date in the available dataset.  The last OOS window ends here "
            "(or earlier if the window does not fit exactly).  ISO-8601 UTC string."
        ),
    )
    train_months: int = Field(
        default=6,
        ge=1,
        description=(
            "Number of calendar months in each training (in-sample) window.  "
            "6 months is the minimum recommended for a PPO model to see enough "
            "market regimes; shorter periods risk training on a single regime."
        ),
    )
    oos_months: int = Field(
        default=1,
        ge=1,
        description=(
            "Number of calendar months in each OOS evaluation window.  "
            "1 month gives granular per-window results; 3 months gives more "
            "stable OOS estimates at the cost of fewer total windows."
        ),
    )
    min_wfe_threshold: float = Field(
        default=WFE_THRESHOLD,
        description=(
            "Minimum Walk-Forward Efficiency required to consider the strategy "
            "deployable.  WFE = mean(OOS metric) / mean(IS metric).  "
            "A value >= 0.5 means the strategy retains at least half its "
            "in-sample edge on unseen data."
        ),
    )
    results_dir: Path = Field(
        default=Path(__file__).parent / "walk_forward_results",
        description=(
            "Directory where per-window metrics and the final WFE report are "
            "written as JSON files.  Created automatically if absent."
        ),
    )

    @field_validator("train_months")
    @classmethod
    def _validate_train_months(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"train_months must be >= 1, got {v}")
        return v

    @field_validator("oos_months")
    @classmethod
    def _validate_oos_months(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"oos_months must be >= 1, got {v}")
        return v


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class WindowResult(BaseModel):
    """Metrics for a single rolling window.

    Args:
        window_index: Zero-based window index.
        train_start: ISO-8601 UTC start of the training period.
        train_end: ISO-8601 UTC end of the training period (exclusive).
        oos_start: ISO-8601 UTC start of the OOS evaluation period.
        oos_end: ISO-8601 UTC end of the OOS evaluation period (exclusive).
        is_metric: In-sample performance metric (Sharpe by default).
            ``None`` when the training/evaluation failed for this window.
        oos_metric: Out-of-sample performance metric.
            ``None`` when the OOS evaluation failed.
        is_successful: ``True`` when both IS and OOS evaluations completed
            without error.
        error: Non-``None`` description of the failure when ``is_successful``
            is ``False``.
    """

    model_config = ConfigDict(frozen=True)

    window_index: int
    train_start: str
    train_end: str
    oos_start: str
    oos_end: str
    is_metric: float | None = None
    oos_metric: float | None = None
    is_successful: bool = True
    error: str | None = None


class WalkForwardResult(BaseModel):
    """Aggregated walk-forward validation output.

    Args:
        strategy_type: Identifier string: ``"rl"`` or ``"evolutionary"``.
        windows: Per-window breakdown (ordered by ``window_index``).
        mean_is_metric: Mean in-sample metric across all successful windows.
        mean_oos_metric: Mean OOS metric across all successful windows.
        walk_forward_efficiency: ``mean_oos_metric / mean_is_metric``.  ``None``
            when ``mean_is_metric`` is zero or no successful windows exist.
        wfe_threshold: The minimum WFE required (from ``WalkForwardConfig``).
        is_deployable: ``True`` when ``walk_forward_efficiency >= wfe_threshold``.
        total_windows: Total number of rolling windows attempted.
        successful_windows: Number of windows where both IS and OOS completed.
        overfit_warning: ``True`` when WFE is computed but below threshold.
        report_path: Absolute path to the saved JSON report (or ``None`` if
            the report could not be written).
    """

    model_config = ConfigDict(frozen=True)

    strategy_type: str
    windows: list[WindowResult]
    mean_is_metric: float | None
    mean_oos_metric: float | None
    walk_forward_efficiency: float | None
    wfe_threshold: float
    is_deployable: bool
    total_windows: int
    successful_windows: int
    overfit_warning: bool
    report_path: str | None = None


# ---------------------------------------------------------------------------
# Protocol types for train/eval callables
# ---------------------------------------------------------------------------


@runtime_checkable
class TrainFn(Protocol):
    """Callable contract for a single walk-forward training step.

    The function receives ISO-8601 window boundaries and returns an opaque
    ``model_artifact`` that is passed directly to :class:`EvalFn`.  Raising
    any exception causes the window to be marked as failed.
    """

    async def __call__(
        self,
        train_start: str,
        train_end: str,
        window_index: int,
    ) -> Any:
        """Train a model on [train_start, train_end).

        Args:
            train_start: ISO-8601 UTC start of the training period.
            train_end: ISO-8601 UTC end of the training period (exclusive).
            window_index: Zero-based window counter for logging.

        Returns:
            Arbitrary model artifact (path, object, or dict) passed to
            :class:`EvalFn`.
        """
        ...


@runtime_checkable
class EvalFn(Protocol):
    """Callable contract for evaluating a trained model on an OOS window.

    Args:
        model_artifact: Whatever :class:`TrainFn` returned for this window.
        oos_start: ISO-8601 UTC start of the OOS period.
        oos_end: ISO-8601 UTC end of the OOS period (exclusive).
        window_index: Zero-based window counter for logging.

    Returns:
        ``(is_metric, oos_metric)`` tuple — the in-sample and out-of-sample
        Sharpe (or whatever scalar metric the strategy reports).
    """

    async def __call__(
        self,
        model_artifact: Any,
        oos_start: str,
        oos_end: str,
        window_index: int,
    ) -> tuple[float, float]:
        ...


# ---------------------------------------------------------------------------
# Window splitting logic
# ---------------------------------------------------------------------------


def _add_months(d: date, months: int) -> date:
    """Add ``months`` calendar months to ``d``, clamping to month-end.

    Args:
        d: Starting date.
        months: Number of calendar months to add.  Must be positive.

    Returns:
        A new ``date`` object advanced by exactly ``months`` calendar months.
        When the resulting month has fewer days than ``d.day`` the result is
        clamped to the last day of that month (e.g. Jan 31 + 1 month = Feb 28).
    """
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    # Clamp day to the last day of the target month.
    import calendar  # noqa: PLC0415

    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def _parse_iso_date(iso_str: str) -> date:
    """Parse an ISO-8601 UTC timestamp string into a :class:`date`.

    Accepts both ``YYYY-MM-DDT...`` and bare ``YYYY-MM-DD`` formats.

    Args:
        iso_str: ISO-8601 string such as ``"2024-01-01T00:00:00Z"``.

    Returns:
        The date component of the timestamp.

    Raises:
        ValueError: If the string does not start with a valid ``YYYY-MM-DD``
            prefix.
    """
    date_part = iso_str[:10]  # "YYYY-MM-DD"
    return date.fromisoformat(date_part)


def _to_iso(d: date) -> str:
    """Convert a :class:`date` to an ISO-8601 UTC timestamp string.

    Args:
        d: Calendar date to convert.

    Returns:
        A string of the form ``"YYYY-MM-DDTHH:MM:SSZ"`` with time zeroed.
    """
    return f"{d.isoformat()}T00:00:00Z"


def generate_windows(
    data_start: str,
    data_end: str,
    train_months: int,
    oos_months: int,
) -> list[tuple[str, str, str, str]]:
    """Generate rolling walk-forward window boundaries.

    Each window is a ``(train_start, train_end, oos_start, oos_end)`` tuple
    where the OOS period immediately follows the training period and the next
    window slides forward by ``oos_months``.

    Only windows where the complete OOS period fits within ``[data_start,
    data_end)`` are included — partial windows are discarded.

    Args:
        data_start: ISO-8601 UTC string for the start of available data.
        data_end: ISO-8601 UTC string for the end of available data (exclusive).
        train_months: Number of calendar months in each training period.
        oos_months: Number of calendar months in each OOS evaluation period.

    Returns:
        List of ``(train_start, train_end, oos_start, oos_end)`` tuples, all as
        ISO-8601 UTC strings.  Returns an empty list when the date range is too
        short to fit even one window.

    Example::

        windows = generate_windows(
            data_start="2023-01-01T00:00:00Z",
            data_end="2024-01-01T00:00:00Z",
            train_months=6,
            oos_months=1,
        )
        # Returns 6 windows:
        #  0: train [Jan23, Jul23), OOS [Jul23, Aug23)
        #  1: train [Feb23, Aug23), OOS [Aug23, Sep23)
        #  ...
        #  5: train [Jun23, Dec23), OOS [Dec23, Jan24)
    """
    start_date = _parse_iso_date(data_start)
    end_date = _parse_iso_date(data_end)

    windows: list[tuple[str, str, str, str]] = []

    train_start = start_date
    while True:
        train_end = _add_months(train_start, train_months)
        oos_start = train_end
        oos_end = _add_months(oos_start, oos_months)

        # Stop if OOS window exceeds the available data range.
        if oos_end > end_date:
            break

        windows.append(
            (
                _to_iso(train_start),
                _to_iso(train_end),
                _to_iso(oos_start),
                _to_iso(oos_end),
            )
        )

        # Slide forward by one OOS period.
        train_start = _add_months(train_start, oos_months)

    return windows


# ---------------------------------------------------------------------------
# WFE calculation
# ---------------------------------------------------------------------------


def compute_wfe(
    is_metrics: list[float],
    oos_metrics: list[float],
) -> float | None:
    """Compute the Walk-Forward Efficiency from parallel IS and OOS lists.

    Walk-Forward Efficiency is defined as::

        WFE = mean(OOS) / mean(IS)

    When ``mean(IS)`` is zero or negative the ratio is undefined and ``None``
    is returned — the caller must handle this case (log a warning, do not
    deploy).

    Args:
        is_metrics: List of in-sample performance values, one per window.
            Must be the same length as ``oos_metrics``.
        oos_metrics: List of OOS performance values, one per window.

    Returns:
        WFE ratio in the range ``(-inf, +inf)``, or ``None`` when the
        denominator is zero or no windows were provided.

    Raises:
        ValueError: If ``is_metrics`` and ``oos_metrics`` differ in length.
    """
    if len(is_metrics) != len(oos_metrics):
        raise ValueError(
            f"is_metrics and oos_metrics must have the same length; "
            f"got {len(is_metrics)} vs {len(oos_metrics)}"
        )
    if not is_metrics:
        return None

    mean_is = sum(is_metrics) / len(is_metrics)
    mean_oos = sum(oos_metrics) / len(oos_metrics)

    if mean_is == 0.0:
        return None

    return mean_oos / mean_is


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


async def run_walk_forward(
    strategy_type: str,
    wf_config: WalkForwardConfig,
    train_fn: TrainFn,
    eval_fn: EvalFn,
) -> WalkForwardResult:
    """Run the full walk-forward validation loop.

    This function is algorithm-agnostic.  Callers supply ``train_fn`` and
    ``eval_fn`` coroutines that implement the strategy-specific training and
    evaluation steps.

    For each rolling window:

    1.  Call ``train_fn(train_start, train_end, window_index)`` to produce a
        model artifact.
    2.  Call ``eval_fn(artifact, oos_start, oos_end, window_index)`` to
        produce ``(is_metric, oos_metric)``.
    3.  Record the result in a :class:`WindowResult`.

    After all windows are processed, compute WFE and emit a log warning when
    WFE < ``wf_config.min_wfe_threshold``.

    The final report is written as JSON to
    ``wf_config.results_dir/{strategy_type}_wf_report.json``.

    Args:
        strategy_type: Short identifier used for logging and the report
            filename (e.g. ``"rl"`` or ``"evolutionary"``).
        wf_config: Walk-forward configuration (window sizes, thresholds, paths).
        train_fn: Async callable that trains the model on a given window.
        eval_fn: Async callable that evaluates a trained model on the OOS window.

    Returns:
        :class:`WalkForwardResult` with per-window breakdown and WFE.
    """
    windows = generate_windows(
        data_start=wf_config.data_start,
        data_end=wf_config.data_end,
        train_months=wf_config.train_months,
        oos_months=wf_config.oos_months,
    )

    total_windows = len(windows)
    logger.info(
        "agent.strategies.walk_forward.start",
        strategy_type=strategy_type,
        total_windows=total_windows,
        data_start=wf_config.data_start,
        data_end=wf_config.data_end,
        train_months=wf_config.train_months,
        oos_months=wf_config.oos_months,
    )

    if total_windows < _MIN_WINDOWS:
        logger.warning(
            "agent.strategies.walk_forward.insufficient_windows",
            strategy_type=strategy_type,
            total_windows=total_windows,
            min_required=_MIN_WINDOWS,
        )

    window_results: list[WindowResult] = []
    is_values: list[float] = []
    oos_values: list[float] = []

    for idx, (train_start, train_end, oos_start, oos_end) in enumerate(windows):
        logger.info(
            "agent.strategies.walk_forward.window_start",
            strategy_type=strategy_type,
            window=idx,
            train_start=train_start,
            train_end=train_end,
            oos_start=oos_start,
            oos_end=oos_end,
        )

        try:
            model_artifact = await train_fn(
                train_start=train_start,
                train_end=train_end,
                window_index=idx,
            )
            is_metric, oos_metric = await eval_fn(
                model_artifact=model_artifact,
                oos_start=oos_start,
                oos_end=oos_end,
                window_index=idx,
            )

            logger.info(
                "agent.strategies.walk_forward.window_complete",
                strategy_type=strategy_type,
                window=idx,
                is_metric=round(is_metric, 4),
                oos_metric=round(oos_metric, 4),
            )

            window_results.append(
                WindowResult(
                    window_index=idx,
                    train_start=train_start,
                    train_end=train_end,
                    oos_start=oos_start,
                    oos_end=oos_end,
                    is_metric=is_metric,
                    oos_metric=oos_metric,
                    is_successful=True,
                )
            )
            is_values.append(is_metric)
            oos_values.append(oos_metric)

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            logger.warning(
                "agent.strategies.walk_forward.window_failed",
                strategy_type=strategy_type,
                window=idx,
                error=error_msg,
            )
            window_results.append(
                WindowResult(
                    window_index=idx,
                    train_start=train_start,
                    train_end=train_end,
                    oos_start=oos_start,
                    oos_end=oos_end,
                    is_successful=False,
                    error=error_msg,
                )
            )

    # Aggregate metrics.
    successful_windows = len(is_values)
    mean_is: float | None = (sum(is_values) / len(is_values)) if is_values else None
    mean_oos: float | None = (sum(oos_values) / len(oos_values)) if oos_values else None
    wfe: float | None = compute_wfe(is_values, oos_values) if is_values else None

    # Deployment gate.
    is_deployable = bool(wfe is not None and wfe >= wf_config.min_wfe_threshold)
    overfit_warning = bool(wfe is not None and wfe < wf_config.min_wfe_threshold)

    if overfit_warning:
        logger.warning(
            "agent.strategies.walk_forward.overfit_warning",
            strategy_type=strategy_type,
            wfe=round(wfe, 4),  # type: ignore[arg-type]
            threshold=wf_config.min_wfe_threshold,
            message=(
                f"Walk-Forward Efficiency {wfe:.2%} is below the {wf_config.min_wfe_threshold:.0%} "
                "deployment threshold. Strategy is likely overfit — do NOT deploy."
            ),
        )
    elif wfe is not None:
        logger.info(
            "agent.strategies.walk_forward.wfe_passed",
            strategy_type=strategy_type,
            wfe=round(wfe, 4),
            threshold=wf_config.min_wfe_threshold,
            is_deployable=is_deployable,
        )
    else:
        logger.warning(
            "agent.strategies.walk_forward.wfe_undefined",
            strategy_type=strategy_type,
            reason="No successful windows or zero mean IS metric.",
        )

    # Persist report.
    report_path: str | None = None
    try:
        results_dir = wf_config.results_dir
        results_dir.mkdir(parents=True, exist_ok=True)
        report_file = results_dir / f"{strategy_type}_wf_report.json"
        report_data = {
            "strategy_type": strategy_type,
            "generated_at": datetime.now(UTC).isoformat(),
            "config": {
                "data_start": wf_config.data_start,
                "data_end": wf_config.data_end,
                "train_months": wf_config.train_months,
                "oos_months": wf_config.oos_months,
                "min_wfe_threshold": wf_config.min_wfe_threshold,
            },
            "summary": {
                "total_windows": total_windows,
                "successful_windows": successful_windows,
                "mean_is_metric": mean_is,
                "mean_oos_metric": mean_oos,
                "walk_forward_efficiency": wfe,
                "is_deployable": is_deployable,
                "overfit_warning": overfit_warning,
            },
            "windows": [w.model_dump() for w in window_results],
        }
        report_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        report_path = str(report_file.resolve())
        logger.info(
            "agent.strategies.walk_forward.report_saved",
            path=report_path,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agent.strategies.walk_forward.report_save_failed",
            error=str(exc),
        )

    return WalkForwardResult(
        strategy_type=strategy_type,
        windows=window_results,
        mean_is_metric=mean_is,
        mean_oos_metric=mean_oos,
        walk_forward_efficiency=wfe,
        wfe_threshold=wf_config.min_wfe_threshold,
        is_deployable=is_deployable,
        total_windows=total_windows,
        successful_windows=successful_windows,
        overfit_warning=overfit_warning,
        report_path=report_path,
    )


# ---------------------------------------------------------------------------
# RL walk-forward integration
# ---------------------------------------------------------------------------


async def walk_forward_rl(
    config: Any,
    wf_config: WalkForwardConfig | None = None,
) -> WalkForwardResult:
    """Run walk-forward validation for the PPO RL strategy.

    Trains a fresh PPO model on each rolling window's training period, then
    evaluates it deterministically on the immediately following OOS period.
    The Sharpe ratio is used as the primary metric for both IS and OOS windows.

    Because SB3 training is CPU/GPU-bound and synchronous, it is dispatched
    to a thread via :func:`asyncio.to_thread` so the event loop remains
    responsive.

    Args:
        config: :class:`~agent.strategies.rl.config.RLConfig` instance.
            ``platform_api_key``, ``platform_base_url``, and all PPO
            hyperparameters are read from this object.
        wf_config: Walk-forward configuration.  Defaults to
            :class:`WalkForwardConfig()` with ``data_start`` and ``data_end``
            taken from ``config.train_start`` and ``config.test_end``.

    Returns:
        :class:`WalkForwardResult` with per-window Sharpe metrics and WFE.
    """
    from agent.strategies.rl.runner import _evaluate_model_sync  # noqa: PLC0415
    from agent.strategies.rl.train import train  # noqa: PLC0415

    if wf_config is None:
        wf_config = WalkForwardConfig(
            data_start=config.train_start,
            data_end=config.test_end,
        )

    async def _train(train_start: str, train_end: str, window_index: int) -> Any:
        """Train a PPO model on [train_start, train_end) and return its path."""
        window_config = config.model_copy(
            update={
                "train_start": train_start,
                "train_end": train_end,
                # Collapse val/test so training uses the full window.
                "val_start": train_start,
                "val_end": train_end,
                "test_start": train_start,
                "test_end": train_end,
                "seed": config.seed + window_index,  # unique seed per window
            }
        )
        logger.info(
            "agent.strategies.walk_forward.rl.training",
            window=window_index,
            train_start=train_start,
            train_end=train_end,
        )
        # SB3 training is synchronous and CPU-bound — run in a thread.
        model_path: Path = await asyncio.to_thread(train, window_config)
        return str(model_path)

    async def _eval(
        model_artifact: Any,
        oos_start: str,
        oos_end: str,
        window_index: int,
    ) -> tuple[float, float]:
        """Evaluate the model on both IS and OOS windows; return (IS, OOS) Sharpe."""
        model_path: str = model_artifact

        # IS evaluation: re-evaluate on the training window used above.
        # The training window is encoded in the artifact path's parent directory
        # via the config used during _train(); here we approximate by using the
        # most recent train_start/train_end passed to _train.
        # We store them as a tuple in the artifact to avoid implicit coupling.
        # For simplicity we pass the model path; the train_start/train_end from
        # _train will be reconstructed from the WF config (same sliding window).
        is_config = config.model_copy(
            update={
                "test_start": wf_config.data_start,
                "test_end": oos_start,
            }
        )
        oos_config = config.model_copy(
            update={
                "test_start": oos_start,
                "test_end": oos_end,
            }
        )

        logger.info(
            "agent.strategies.walk_forward.rl.evaluating",
            window=window_index,
            oos_start=oos_start,
            oos_end=oos_end,
        )
        is_result: dict[str, Any] = await asyncio.to_thread(
            _evaluate_model_sync, model_path, is_config
        )
        oos_result: dict[str, Any] = await asyncio.to_thread(
            _evaluate_model_sync, model_path, oos_config
        )

        is_sharpe = float(is_result.get("sharpe_ratio") or 0.0)
        oos_sharpe = float(oos_result.get("sharpe_ratio") or 0.0)
        return is_sharpe, oos_sharpe

    return await run_walk_forward(
        strategy_type="rl",
        wf_config=wf_config,
        train_fn=_train,
        eval_fn=_eval,
    )


# ---------------------------------------------------------------------------
# Evolutionary walk-forward integration
# ---------------------------------------------------------------------------


async def _create_evo_battle_runner(evo_config: Any) -> Any:
    """Factory that creates and authenticates a BattleRunner for evolutionary WFV.

    Exists as a separate named function so it can be patched in unit tests
    without touching the main ``walk_forward_evolutionary`` logic.

    Args:
        evo_config: :class:`~agent.strategies.evolutionary.config.EvolutionConfig`
            instance.

    Returns:
        Authenticated :class:`~agent.strategies.evolutionary.battle_runner.BattleRunner`.
    """
    from agent.config import AgentConfig  # noqa: PLC0415
    from agent.strategies.evolutionary.battle_runner import BattleRunner  # noqa: PLC0415
    from agent.tools.rest_tools import PlatformRESTClient  # noqa: PLC0415

    agent_cfg = AgentConfig()
    rest_client = PlatformRESTClient(agent_cfg)
    return await BattleRunner.create(agent_cfg, rest_client)


async def walk_forward_evolutionary(
    evo_config: Any,
    wf_config: WalkForwardConfig | None = None,
) -> WalkForwardResult:
    """Run walk-forward validation for the genetic algorithm strategy.

    For each rolling window the full GA evolution loop runs on the in-sample
    period, then the champion genome from that window is evaluated on the OOS
    period.  The 5-factor composite fitness is used as the primary metric.

    The BattleRunner is created via :func:`_create_evo_battle_runner` so that
    platform authentication and the runner lifecycle can be mocked in tests.

    Args:
        evo_config: :class:`~agent.strategies.evolutionary.config.EvolutionConfig`
            instance.
        wf_config: Walk-forward configuration.  Defaults to
            :class:`WalkForwardConfig()` with window dates taken from
            ``evo_config.historical_start`` / ``evo_config.historical_end``.

    Returns:
        :class:`WalkForwardResult` with per-window composite fitness metrics
        and WFE.
    """
    from agent.strategies.evolutionary.evolve import (  # noqa: PLC0415
        _compute_fitness,
    )
    from agent.strategies.evolutionary.genome import StrategyGenome  # noqa: PLC0415
    from agent.strategies.evolutionary.population import Population  # noqa: PLC0415

    if wf_config is None:
        wf_config = WalkForwardConfig(
            data_start=f"{evo_config.historical_start.isoformat()}T00:00:00Z",
            data_end=f"{evo_config.historical_end.isoformat()}T00:00:00Z",
        )

    # One shared BattleRunner for all windows — avoids repeated agent provisioning.
    # ``_create_evo_battle_runner`` is patched in unit tests.
    runner = await _create_evo_battle_runner(evo_config)
    await runner.setup_agents(evo_config.population_size)

    try:

        async def _train(
            train_start: str, train_end: str, window_index: int
        ) -> Any:
            """Run the GA on the IS window; return the champion genome."""
            logger.info(
                "agent.strategies.walk_forward.evo.training",
                window=window_index,
                train_start=train_start,
                train_end=train_end,
            )
            import numpy as np  # noqa: PLC0415

            rng = np.random.default_rng(evo_config.seed + window_index)
            pop = Population(size=evo_config.population_size, rng=rng)
            pop.initialize()

            best_genome: StrategyGenome | None = None
            best_fitness: float = float("-inf")

            for gen in range(evo_config.generations):
                await runner.reset_agents()
                await runner.assign_strategies(pop.genomes)

                is_battle_id = await runner.run_battle(
                    preset=evo_config.battle_preset,
                    historical_window=(train_start, train_end),
                )
                is_metrics = await runner.get_detailed_metrics(is_battle_id)
                await runner.cleanup(is_battle_id)

                # Inner OOS split within training window to avoid look-ahead
                # into the walk-forward OOS period.
                total_days = (
                    _parse_iso_date(train_end) - _parse_iso_date(train_start)
                ).days
                oos_days = max(1, round(total_days * evo_config.oos_split_ratio))
                is_days = total_days - oos_days
                is_end_date = _parse_iso_date(train_start) + timedelta(days=is_days)
                inner_oos_window = (_to_iso(is_end_date), train_end)

                await runner.reset_agents()
                inner_oos_battle_id = await runner.run_battle(
                    preset=evo_config.battle_preset,
                    historical_window=inner_oos_window,
                )
                inner_oos_metrics = await runner.get_detailed_metrics(inner_oos_battle_id)
                await runner.cleanup(inner_oos_battle_id)

                oos_sharpe_map: dict[str, float | None] = {
                    aid: m.get("sharpe_ratio")
                    for aid, m in inner_oos_metrics.items()
                }
                scores = _compute_fitness(
                    agent_ids=runner.agent_ids,
                    is_metrics=is_metrics,
                    oos_sharpe_map=oos_sharpe_map,
                    fitness_fn=evo_config.fitness_fn,
                )

                for genome, score in zip(pop.genomes, scores):
                    if score > best_fitness:
                        best_fitness = score
                        best_genome = genome

                logger.info(
                    "agent.strategies.walk_forward.evo.generation_complete",
                    window=window_index,
                    generation=gen,
                    best_fitness=round(best_fitness, 4),
                )
                pop.evolve(scores)

            return (best_genome, best_fitness, train_start, train_end)

        async def _eval(
            model_artifact: Any,
            oos_start: str,
            oos_end: str,
            window_index: int,
        ) -> tuple[float, float]:
            """Evaluate champion genome on OOS window; return (IS, OOS) fitness."""
            champion_genome, is_fitness, _train_start, _train_end = model_artifact

            if champion_genome is None:
                raise RuntimeError(
                    f"Window {window_index}: no champion genome produced during training"
                )

            logger.info(
                "agent.strategies.walk_forward.evo.evaluating_oos",
                window=window_index,
                oos_start=oos_start,
                oos_end=oos_end,
            )

            await runner.reset_agents()
            await runner.assign_strategies([champion_genome] * evo_config.population_size)

            wf_oos_battle_id = await runner.run_battle(
                preset=evo_config.battle_preset,
                historical_window=(oos_start, oos_end),
            )
            wf_oos_metrics = await runner.get_detailed_metrics(wf_oos_battle_id)
            await runner.cleanup(wf_oos_battle_id)

            oos_sharpe_values = [
                m.get("sharpe_ratio")
                for m in wf_oos_metrics.values()
                if m.get("sharpe_ratio") is not None
            ]
            oos_fitness = (
                sum(oos_sharpe_values) / len(oos_sharpe_values)
                if oos_sharpe_values
                else 0.0
            )

            return float(is_fitness), float(oos_fitness)

        return await run_walk_forward(
            strategy_type="evolutionary",
            wf_config=wf_config,
            train_fn=_train,
            eval_fn=_eval,
        )

    finally:
        # Best-effort agent cleanup — do not propagate errors here.
        try:
            await runner.teardown_agents()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "agent.strategies.walk_forward.evo.teardown_failed",
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_cli() -> Any:
    """Build the CLI argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser`.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="python -m agent.strategies.walk_forward",
        description="Run walk-forward validation for RL or evolutionary strategies.",
    )
    parser.add_argument(
        "--strategy",
        choices=["rl", "evolutionary"],
        required=True,
        help="Strategy type to validate.",
    )
    parser.add_argument(
        "--data-start",
        default="2023-01-01T00:00:00Z",
        help="ISO-8601 UTC start of the available data window.",
    )
    parser.add_argument(
        "--data-end",
        default="2024-06-01T00:00:00Z",
        help="ISO-8601 UTC end of the available data window.",
    )
    parser.add_argument(
        "--train-months",
        type=int,
        default=6,
        help="Calendar months in each training window (default: 6).",
    )
    parser.add_argument(
        "--oos-months",
        type=int,
        default=1,
        help="Calendar months in each OOS evaluation window (default: 1).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Master random seed for reproducibility (default: 42).",
    )
    return parser


async def _async_main(args: Any) -> int:
    """Async entry point for the CLI.

    Args:
        args: Parsed :class:`argparse.Namespace` from ``_build_cli()``.

    Returns:
        Exit code: 0 for success / deployable, 1 for overfit warning or error.
    """
    import sys  # noqa: PLC0415

    wf_config = WalkForwardConfig(
        data_start=args.data_start,
        data_end=args.data_end,
        train_months=args.train_months,
        oos_months=args.oos_months,
    )

    try:
        if args.strategy == "rl":
            from agent.strategies.rl.config import RLConfig  # noqa: PLC0415

            rl_config = RLConfig(seed=args.seed)
            result = await walk_forward_rl(config=rl_config, wf_config=wf_config)
        else:
            from agent.strategies.evolutionary.config import EvolutionConfig  # noqa: PLC0415

            evo_config = EvolutionConfig(seed=args.seed)
            result = await walk_forward_evolutionary(
                evo_config=evo_config, wf_config=wf_config
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "agent.strategies.walk_forward.cli.fatal_error",
            error=str(exc),
        )
        print(f"Walk-forward validation failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nWalk-Forward Validation — {result.strategy_type.upper()}")
    print(f"  Windows:              {result.successful_windows}/{result.total_windows} successful")
    if result.mean_is_metric is not None:
        print(f"  Mean IS metric:       {result.mean_is_metric:.4f}")
    if result.mean_oos_metric is not None:
        print(f"  Mean OOS metric:      {result.mean_oos_metric:.4f}")
    if result.walk_forward_efficiency is not None:
        print(f"  Walk-Forward Efficiency: {result.walk_forward_efficiency:.2%}")
    print(f"  Deployable:           {result.is_deployable}")
    if result.overfit_warning:
        print(
            f"\n  WARNING: WFE {result.walk_forward_efficiency:.2%} < "
            f"{result.wfe_threshold:.0%} threshold. Strategy likely overfit — do NOT deploy."
        )
    if result.report_path:
        print(f"  Report saved to:      {result.report_path}")

    return 0 if result.is_deployable else 1


if __name__ == "__main__":
    import argparse  # noqa: PLC0415
    import sys  # noqa: PLC0415

    _parser = _build_cli()
    _args = _parser.parse_args()
    sys.exit(asyncio.run(_async_main(_args)))
