"""Regime-adaptive strategy validation harness.

Runs 12 sequential monthly backtests comparing three strategies side-by-side:

1. **Regime-adaptive** — ``RegimeSwitcher`` classifies the market each iteration
   and activates the matching strategy (MACD+ADX, RSI+BB, tight-stop, or
   Bollinger-squeeze) automatically.

2. **Static MACD** — MACD-crossover strategy held constant for the full month
   regardless of regime, used as a representative "always-on" benchmark.

3. **Buy-and-hold** — Buys BTC once at the start and holds to month-end;
   represents the passive market return.

For each month a fresh backtest session is created, run on 1-minute candles, and
fully stepped to completion.  Regime switches are logged per iteration and
accumulated per month.  Final results are compiled into a ``RegimeValidationReport``
and written to ``agent/reports/regime-validation-{timestamp}.json``.

Usage:

    python -m agent.strategies.regime.validate \\
        --base-url http://localhost:8000 \\
        --months 12

    # Dry-run: validate connectivity only, no backtests
    python -m agent.strategies.regime.validate \\
        --base-url http://localhost:8000 \\
        --health-check-only

Prerequisites:

    - API running and reachable at ``--base-url``
    - At least 12 months of candle data in TimescaleDB
    - ``scikit-learn`` and either ``xgboost`` or ``scikit-learn`` available
      (``RegimeClassifier`` falls back to RandomForest automatically)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

from agent.strategies.regime.classifier import RegimeClassifier
from agent.strategies.regime.labeler import RegimeType, generate_training_data
from agent.strategies.regime.switcher import (
    CONFIDENCE_THRESHOLD,
    MIN_CANDLES_REQUIRED,
    SWITCH_COOLDOWN_CANDLES,
    RegimeSwitcher,
)

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError as _err:
    raise ImportError("pydantic >=2 is required: pip install pydantic") from _err

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Candle interval used for all backtest sessions (1-minute resolution gives the
# most granular stepping and allows the regime switcher to see intra-day moves).
_CANDLE_INTERVAL_SECONDS: int = 60

# Starting virtual USDT balance for every backtest session.
_STARTING_BALANCE: str = "10000"

# Backtest symbols — regime switcher needs enough price history per symbol.
_SYMBOLS: list[str] = ["BTCUSDT"]

# Number of candle steps to advance per trading loop iteration.  60 steps on
# 1-minute candles = 1 hour of simulated time per iteration.
_BATCH_SIZE: int = 60

# Max iterations per backtest before the loop is force-terminated.
# 1 month ≈ 43 200 minutes; 60 steps/iter → 720 iterations covers 30 days.
_MAX_ITERATIONS: int = 750

# Number of candles to request each iteration for the regime switcher.
# MIN_CANDLES_REQUIRED=50, but we fetch more so indicators have warm-up data.
_CANDLE_WINDOW: int = 120

# Static benchmark MACD-strategy label.
_STATIC_STRATEGY_LABEL: str = "static_macd_benchmark"

# Buy-and-hold strategy label.
_BUYHOLD_STRATEGY_LABEL: str = "buy_and_hold_benchmark"

# Regime-adaptive strategy label.
_REGIME_STRATEGY_LABEL: str = "regime_adaptive"

# BTC order quantity used across all strategies (small test size).
_BTC_QTY: str = "0.0001"

# Default data endpoint for checking available range.
_DATA_RANGE_PATH: str = "/api/v1/market/data-range"

# Reports directory relative to this file's package root.
_REPORTS_DIR: Path = Path(__file__).parent.parent.parent / "reports"


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------


class MonthlyResult(BaseModel):
    """Performance results for one strategy over one calendar month.

    Args:
        month_label: Human-readable label, e.g. ``"2024-01"``.
        session_id: Backtest session UUID (``None`` if session failed to start).
        strategy_label: One of ``"regime_adaptive"``, ``"static_macd_benchmark"``,
            or ``"buy_and_hold_benchmark"``.
        roi_pct: Return-on-investment percentage over the month (``None`` if
            the backtest did not complete).
        sharpe_ratio: Annualised Sharpe ratio (``None`` when insufficient trades).
        max_drawdown_pct: Maximum drawdown as a percentage (``None`` when
            insufficient trades).
        win_rate: Fraction of winning trades (0.0–1.0; ``None`` when no trades).
        total_trades: Number of trades placed during the month.
        final_equity: Final virtual USDT balance at month-end.
        regime_switches: Number of strategy switches made by the regime switcher
            (always 0 for static and buy-and-hold benchmarks).
        dominant_regime: The most-frequently active regime during the month
            (``None`` for non-regime strategies).
        error: Error message if the backtest failed; ``None`` on success.
    """

    model_config = ConfigDict(frozen=True)

    month_label: str
    session_id: str | None
    strategy_label: str
    roi_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    total_trades: int = 0
    final_equity: float | None = None
    regime_switches: int = 0
    dominant_regime: str | None = None
    error: str | None = None


class MonthlySummary(BaseModel):
    """Side-by-side comparison of all three strategies for one calendar month.

    Args:
        month_label: ISO year-month label (e.g. ``"2024-01"``).
        regime: ``MonthlyResult`` for the regime-adaptive strategy.
        static: ``MonthlyResult`` for the static MACD benchmark.
        buyhold: ``MonthlyResult`` for the buy-and-hold benchmark.
        regime_wins: ``True`` if regime ROI > static ROI for this month.
    """

    model_config = ConfigDict(frozen=True)

    month_label: str
    regime: MonthlyResult
    static: MonthlyResult
    buyhold: MonthlyResult
    regime_wins: bool = False


class ValidationSummary(BaseModel):
    """Aggregate statistics across all validated months.

    Args:
        total_months: Number of months in the validation window.
        months_completed: Number of months where all three backtests finished.
        regime_avg_roi: Average monthly ROI for the regime-adaptive strategy.
        static_avg_roi: Average monthly ROI for the static MACD benchmark.
        buyhold_avg_roi: Average monthly ROI for buy-and-hold.
        regime_avg_sharpe: Average Sharpe ratio for the regime strategy.
        static_avg_sharpe: Average Sharpe ratio for the static strategy.
        alpha_months: Months where regime ROI > static ROI.
        alpha_rate: Fraction of completed months where regime outperformed static.
        total_regime_switches: Cumulative regime switches across all months.
        avg_switches_per_month: Average switches per month.
        regime_better_than_buyhold_months: Months where regime > buy-and-hold.
    """

    model_config = ConfigDict(frozen=True)

    total_months: int
    months_completed: int
    regime_avg_roi: float | None = None
    static_avg_roi: float | None = None
    buyhold_avg_roi: float | None = None
    regime_avg_sharpe: float | None = None
    static_avg_sharpe: float | None = None
    alpha_months: int = 0
    alpha_rate: float | None = None
    total_regime_switches: int = 0
    avg_switches_per_month: float | None = None
    regime_better_than_buyhold_months: int = 0


class RegimeValidationReport(BaseModel):
    """Full regime validation report produced by ``RegimeValidator``.

    Serialises cleanly to JSON via ``model.model_dump_json(indent=2)``.

    Args:
        generated_at: ISO-8601 UTC timestamp of report generation.
        base_url: Platform API base URL used for the backtests.
        months_requested: Number of months the validator was asked to run.
        per_month: Ordered list of monthly comparisons (oldest first).
        summary: Aggregate performance statistics across all months.
        regime_switches_by_month: Dict of ``{month_label: switch_count}``
            for the regime-adaptive strategy only.
        alpha_months: Count of months where regime-adaptive outperformed static.
        errors: List of error strings accumulated across all backtests.
    """

    model_config = ConfigDict(frozen=True)

    generated_at: str
    base_url: str
    months_requested: int
    per_month: list[MonthlySummary]
    summary: ValidationSummary
    regime_switches_by_month: dict[str, int]
    alpha_months: int
    errors: list[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """Convert *value* to float, returning *default* on failure.

    Args:
        value: Any value to coerce.
        default: Returned when the coercion fails.  Defaults to ``None``.

    Returns:
        Float representation of *value* or *default*.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _extract_closes_from_candles(candles_resp: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a list of raw OHLCV dicts from a ``get_backtest_candles`` response.

    Args:
        candles_resp: Raw API response dict.

    Returns:
        List of candle dicts (oldest first).  Empty list on unexpected shape.
    """
    return candles_resp.get("candles", []) or []


def _candles_to_switcher_format(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert API candle dicts to the format expected by the ``RegimeSwitcher``.

    The platform API returns candles with keys ``bucket``, ``open``, ``high``,
    ``low``, ``close``, ``volume``.  The switcher / labeler expect the same keys
    but ``timestamp`` may also be used.  We pass through with minimal conversion.

    Args:
        candles: List of raw API candle dicts.

    Returns:
        List of normalised OHLCV dicts suitable for ``RegimeSwitcher.step()``.
    """
    result = []
    for c in candles:
        try:
            result.append(
                {
                    "open": float(c.get("open", 0) or 0),
                    "high": float(c.get("high", 0) or 0),
                    "low": float(c.get("low", 0) or 0),
                    "close": float(c.get("close", 0) or 0),
                    "volume": float(c.get("volume", 0) or 0),
                    "timestamp": c.get("bucket", c.get("timestamp", 0)),
                }
            )
        except (ValueError, TypeError):
            continue
    return result


def _compute_dominant_regime(
    regime_history: list[dict[str, Any]], total_iterations: int
) -> str | None:
    """Return the regime-value string that was active for the most iterations.

    When no switches occurred the initial regime (``mean_reverting``) dominated.

    Args:
        regime_history: List of regime-switch records from
            ``RegimeSwitcher.get_history()``.
        total_iterations: Total iteration count; used to compute time spent in
            the final (last-switched-to) regime.

    Returns:
        Dominant regime string value or ``None`` if history is empty and no
        iterations were processed.
    """
    if total_iterations == 0:
        return None
    if not regime_history:
        # No switches — initial regime dominated the whole month.
        return RegimeType.MEAN_REVERTING.value

    # Build segments: each entry covers from its candle_index until the next.
    durations: dict[str, int] = {}
    for i, record in enumerate(regime_history):
        start = record["candle_index"]
        end = regime_history[i + 1]["candle_index"] if i + 1 < len(regime_history) else total_iterations
        regime_val = record["regime"]
        durations[regime_val] = durations.get(regime_val, 0) + (end - start)

    # Add time spent in the initial regime before the first switch.
    initial_val = RegimeType.MEAN_REVERTING.value
    first_switch_candle = regime_history[0]["candle_index"] if regime_history else 0
    durations[initial_val] = durations.get(initial_val, 0) + first_switch_candle

    return max(durations, key=lambda k: durations[k])


def _build_synthetic_classifier(seed: int = 42) -> RegimeClassifier:
    """Build and return a RandomForest classifier trained on synthetic candles.

    Used as a fallback when the platform is unavailable or when insufficient
    historical candle data exists for training.  Synthetic data covers four
    distinct regimes so the classifier learns all classes.

    Args:
        seed: Random seed passed to ``RegimeClassifier`` and the candle
            generator.

    Returns:
        A fitted :class:`~agent.strategies.regime.classifier.RegimeClassifier`.
    """
    import numpy as np  # noqa: PLC0415

    rng = np.random.default_rng(seed)
    n = 600  # Enough rows for warm-up + training/test split.
    close = 50_000.0
    candles: list[dict[str, Any]] = []
    seg = n // 4

    for i in range(n):
        segment = i // seg
        if segment == 0:
            trend, noise, spread = 30.0, 10.0, 40.0
        elif segment == 1:
            trend, noise, spread = 0.0, 200.0, 400.0
        elif segment == 2:
            trend, noise, spread = 0.0, 5.0, 8.0
        else:
            trend, noise, spread = -30.0, 10.0, 40.0

        close = max(close + trend + float(rng.normal(0, noise)), 1.0)
        high = close + abs(float(rng.normal(0, spread * 0.5)))
        low = max(close - abs(float(rng.normal(0, spread * 0.5))), close * 0.001)
        candles.append(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": float(rng.integers(100, 10_000)),
                "timestamp": i,
            }
        )

    features, labels = generate_training_data(candles, window=20)
    split = int(len(features) * 0.8)
    clf = RegimeClassifier(seed=seed, use_xgboost=False)
    clf.train(features.iloc[:split].reset_index(drop=True), labels.iloc[:split].reset_index(drop=True))
    return clf


# ---------------------------------------------------------------------------
# RegimeValidator
# ---------------------------------------------------------------------------


class RegimeValidator:
    """Orchestrates regime-adaptive and benchmark backtests across multiple months.

    Each call to :meth:`run_monthly_backtests`, :meth:`run_static_benchmark`, or
    :meth:`run_buyhold_benchmark` creates and drives independent backtest sessions
    via the platform REST API.  Results are accumulated and compared in
    :meth:`compare` and :meth:`generate_report`.

    Args:
        base_url: Platform REST API base URL (e.g. ``"http://localhost:8000"``).
        api_key: ``ak_live_...`` API key for all REST calls.
        months: Number of calendar months to validate.
        seed: Random seed for the regime classifier (used when training on
            synthetic data as fallback).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        months: int = 12,
        seed: int = 42,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._months = months
        self._seed = seed

        # Results containers — populated by the three run_* methods.
        self._regime_results: list[MonthlyResult] = []
        self._static_results: list[MonthlyResult] = []
        self._buyhold_results: list[MonthlyResult] = []
        self._errors: list[str] = []

        # Month windows set by _build_month_windows()
        self._month_windows: list[tuple[datetime, datetime, str]] = []

        # Classifier — trained lazily before regime backtests start.
        self._classifier: RegimeClassifier | None = None

        self._log = logger.bind(component="RegimeValidator")

    # ------------------------------------------------------------------
    # Async HTTP helpers
    # ------------------------------------------------------------------

    def _make_client(self) -> httpx.AsyncClient:
        """Return a new authenticated ``httpx.AsyncClient``.

        Returns:
            Configured client with ``X-API-Key`` header and 60 s timeout.
        """
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-API-Key": self._api_key},
            timeout=60.0,
        )

    async def _health_check(self) -> bool:
        """Verify the platform API is reachable and responding.

        A 200 response with a ``status`` field is the ideal result.  A 401 or
        403 is also treated as success — the server is running; the key is
        just missing or wrong, which is a configuration concern rather than a
        connectivity failure.  Only network-level errors (connection refused,
        timeout, DNS failure) return ``False``.

        Returns:
            ``True`` if the platform responds to ``GET /api/v1/health`` with
            any HTTP response (even 4xx); ``False`` on network error.
        """
        try:
            async with self._make_client() as client:
                resp = await client.get("/api/v1/health")
                # 200 OK: healthy.  401/403: server is up but key needed.
                # Any HTTP response means the platform is reachable.
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", "unknown")
                    self._log.info("agent.strategy.regime.validate.health_check.ok", status=status)
                else:
                    self._log.info(
                        "agent.strategy.regime.validate.health_check.reachable_with_error",
                        status_code=resp.status_code,
                    )
                return True
        except httpx.RequestError as exc:
            self._log.error("agent.strategy.regime.validate.health_check.failed", error=str(exc))
            return False

    async def _get_data_range(self) -> tuple[datetime | None, datetime | None]:
        """Fetch the earliest and latest available candle timestamps.

        Returns:
            Tuple of ``(earliest, latest)`` as UTC-aware ``datetime`` objects.
            Either element may be ``None`` if the API call fails or the field
            is absent from the response.
        """
        try:
            async with self._make_client() as client:
                resp = await client.get(_DATA_RANGE_PATH)
                resp.raise_for_status()
                data = resp.json()

            earliest_str: str | None = data.get("earliest")
            latest_str: str | None = data.get("latest")

            earliest: datetime | None = None
            latest: datetime | None = None

            if earliest_str:
                earliest = datetime.fromisoformat(
                    earliest_str.replace("Z", "+00:00")
                ).astimezone(UTC)
            if latest_str:
                latest = datetime.fromisoformat(
                    latest_str.replace("Z", "+00:00")
                ).astimezone(UTC)

            self._log.info("agent.strategy.regime.validate.data_range.fetched", earliest=earliest_str, latest=latest_str)
            return earliest, latest

        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            self._log.warning("agent.strategy.regime.validate.data_range.fetch_failed", error=str(exc))
            return None, None

    # ------------------------------------------------------------------
    # Month window construction
    # ------------------------------------------------------------------

    def _build_month_windows(
        self,
        reference_end: datetime,
    ) -> list[tuple[datetime, datetime, str]]:
        """Compute ``self._months`` consecutive calendar-month windows ending at *reference_end*.

        Months are aligned to the 1st of each month (00:00 UTC) so that
        backtests cover clean calendar months rather than arbitrary 30-day
        chunks.

        Args:
            reference_end: The latest available data timestamp.  The validator
                works backwards from this point to build month boundaries.

        Returns:
            Ordered list (oldest first) of ``(start, end, month_label)`` tuples
            where *month_label* is ``"YYYY-MM"``.
        """
        # Clamp reference_end to the start of its month so windows align.
        # e.g. if latest = 2024-03-15, end = 2024-03-01 00:00 UTC.
        end_dt = reference_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        windows: list[tuple[datetime, datetime, str]] = []
        current_end = end_dt

        for _ in range(self._months):
            # Go back one month from current_end.
            # Use timedelta trick: first day of current_end's month minus 1 day
            # gives last day of previous month; then reset to 1st of that month.
            first_of_current = current_end
            last_of_prev = first_of_current - timedelta(days=1)
            start_dt = last_of_prev.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )

            month_label = start_dt.strftime("%Y-%m")
            windows.append((start_dt, first_of_current, month_label))
            current_end = start_dt

        # Reverse so index 0 = oldest month.
        windows.reverse()
        return windows

    # ------------------------------------------------------------------
    # Classifier bootstrap
    # ------------------------------------------------------------------

    async def _ensure_classifier(self) -> RegimeClassifier:
        """Return a fitted ``RegimeClassifier``, training on synthetic data if needed.

        First checks whether a persisted model exists at the default path.  If
        not, trains a fresh RandomForest classifier on synthetic candle data so
        that the validation can proceed even without a pre-trained model file.

        Returns:
            A ready-to-use :class:`~agent.strategies.regime.classifier.RegimeClassifier`.
        """
        if self._classifier is not None:
            return self._classifier

        model_path = Path(__file__).parent / "models" / "regime_classifier.joblib"
        if model_path.exists():
            try:
                self._classifier = RegimeClassifier.load(model_path)
                self._log.info("agent.strategy.regime.validate.classifier.loaded_from_disk", path=str(model_path))
                return self._classifier
            except Exception as exc:  # noqa: BLE001
                self._log.warning("agent.strategy.regime.validate.classifier.load_failed", path=str(model_path), error=str(exc))

        self._log.info("agent.strategy.regime.validate.classifier.training_synthetic")
        self._classifier = _build_synthetic_classifier(seed=self._seed)
        return self._classifier

    # ------------------------------------------------------------------
    # Core backtest runner
    # ------------------------------------------------------------------

    async def _run_one_backtest(
        self,
        month_label: str,
        start_dt: datetime,
        end_dt: datetime,
        strategy_label: str,
        *,
        use_regime_switcher: bool = False,
        use_buyhold: bool = False,
    ) -> MonthlyResult:
        """Run a single backtest session for *month_label* and return results.

        Internally performs the full backtest lifecycle:
        create → start → trading loop → fetch results.

        Args:
            month_label: Human-readable month identifier (``"YYYY-MM"``).
            start_dt: UTC start of the backtest window.
            end_dt: UTC end of the backtest window.
            strategy_label: Label stored with the backtest session.
            use_regime_switcher: When ``True``, classifies regime on every
                iteration and logs switches.  When ``False``, uses a fixed
                MACD-signal MA crossover (static benchmark).
            use_buyhold: When ``True``, buys once at session start and holds;
                no further orders are placed.

        Returns:
            :class:`MonthlyResult` populated with the backtest outcomes.
        """
        log = self._log.bind(month=month_label, strategy=strategy_label)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        session_id: str | None = None
        switcher: RegimeSwitcher | None = None
        strategy_map: dict[RegimeType, str] = {
            rt: rt.value for rt in RegimeType
        }

        if use_regime_switcher:
            clf = await self._ensure_classifier()
            switcher = RegimeSwitcher(
                classifier=clf,
                strategy_map=strategy_map,
                confidence_threshold=CONFIDENCE_THRESHOLD,
                cooldown_candles=SWITCH_COOLDOWN_CANDLES,
            )

        async with self._make_client() as client:
            # ── Create session ────────────────────────────────────────────────
            try:
                create_resp = await client.post(
                    "/api/v1/backtest/create",
                    json={
                        "start_time": start_iso,
                        "end_time": end_iso,
                        "pairs": _SYMBOLS,
                        "candle_interval": _CANDLE_INTERVAL_SECONDS,
                        "starting_balance": _STARTING_BALANCE,
                        "strategy_label": strategy_label,
                    },
                )
                create_resp.raise_for_status()
                create_data = create_resp.json()
                session_id = create_data.get("session_id")
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                err = f"[{month_label}/{strategy_label}] create_backtest failed: {exc}"
                log.error("agent.strategy.regime.validate.create_backtest.failed", error=err)
                self._errors.append(err)
                return MonthlyResult(
                    month_label=month_label,
                    session_id=None,
                    strategy_label=strategy_label,
                    error=err,
                )

            if not session_id:
                err = f"[{month_label}/{strategy_label}] no session_id in create response: {create_data}"
                log.error("agent.strategy.regime.validate.create_backtest.no_session_id")
                self._errors.append(err)
                return MonthlyResult(
                    month_label=month_label,
                    session_id=None,
                    strategy_label=strategy_label,
                    error=err,
                )

            log.info("agent.strategy.regime.validate.session.created", session_id=session_id)

            # ── Start session ─────────────────────────────────────────────────
            try:
                start_resp = await client.post(f"/api/v1/backtest/{session_id}/start")
                start_resp.raise_for_status()
                start_data = start_resp.json()
                session_status = start_data.get("status", "unknown")
                if session_status != "running":
                    err = (
                        f"[{month_label}/{strategy_label}] start_backtest returned "
                        f"status='{session_status}' (expected 'running')"
                    )
                    log.error("agent.strategy.regime.validate.start_backtest.unexpected_status", status=session_status)
                    self._errors.append(err)
                    return MonthlyResult(
                        month_label=month_label,
                        session_id=session_id,
                        strategy_label=strategy_label,
                        error=err,
                    )
                log.info("agent.strategy.regime.validate.session.started", status=session_status)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                err = f"[{month_label}/{strategy_label}] start_backtest failed: {exc}"
                log.error("agent.strategy.regime.validate.start_backtest.failed", error=err)
                self._errors.append(err)
                return MonthlyResult(
                    month_label=month_label,
                    session_id=session_id,
                    strategy_label=strategy_label,
                    error=err,
                )

            # ── Trading loop ──────────────────────────────────────────────────
            trades_placed: int = 0
            loop_complete: bool = False
            iterations: int = 0
            regime_switches: int = 0
            open_position: bool = False  # Track BTC position (buy-and-hold / regime)
            open_side: str | None = None  # "buy" or "sell"

            # Buy-and-hold: place a single buy at the start, then let time run.
            if use_buyhold:
                try:
                    order_resp = await client.post(
                        f"/api/v1/backtest/{session_id}/trade/order",
                        json={
                            "symbol": "BTCUSDT",
                            "side": "buy",
                            "type": "market",
                            "quantity": _BTC_QTY,
                        },
                    )
                    if order_resp.status_code < 300:
                        trades_placed += 1
                        open_position = True
                        open_side = "buy"
                        log.info("agent.strategy.regime.validate.buyhold.initial_buy.placed")
                    else:
                        log.warning(
                            "agent.strategy.regime.validate.buyhold.initial_buy.rejected",
                            status=order_resp.status_code,
                            body=order_resp.text[:200],
                        )
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning("agent.strategy.regime.validate.buyhold.initial_buy.failed", error=str(exc))

            for iteration in range(_MAX_ITERATIONS):
                iterations += 1

                if not use_buyhold:
                    # ── Fetch candles for regime detection / MA signal ────────
                    try:
                        candles_resp = await client.get(
                            f"/api/v1/backtest/{session_id}/market/candles/BTCUSDT",
                            params={
                                "interval": _CANDLE_INTERVAL_SECONDS,
                                "limit": _CANDLE_WINDOW,
                            },
                        )
                        candles_resp.raise_for_status()
                        candle_data = candles_resp.json()
                        raw_candles = _extract_closes_from_candles(candle_data)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code in (404, 409, 410):
                            loop_complete = True
                            break
                        log.warning(
                            "agent.strategy.regime.validate.loop.candles.http_error",
                            status=exc.response.status_code,
                            iteration=iteration,
                        )
                        raw_candles = []
                    except httpx.RequestError as exc:
                        log.warning("agent.strategy.regime.validate.loop.candles.request_error", error=str(exc))
                        raw_candles = []

                    # ── Determine signal ──────────────────────────────────────
                    signal: str = "hold"

                    if use_regime_switcher and switcher is not None and len(raw_candles) >= MIN_CANDLES_REQUIRED:
                        formatted = _candles_to_switcher_format(raw_candles)
                        regime, _strategy_id, switched = switcher.step(formatted)
                        if switched:
                            regime_switches += 1
                            log.info(
                                "agent.strategy.regime.validate.regime.switched",
                                new_regime=regime.value,
                                iteration=iteration,
                                month=month_label,
                            )
                        # Use regime to determine trade direction:
                        # TRENDING / LOW_VOLATILITY → look for buy entries.
                        # MEAN_REVERTING / HIGH_VOLATILITY → hold or sell.
                        closes = [c["close"] for c in formatted if c["close"] > 0]
                        if len(closes) >= 20:
                            fast_sma = sum(closes[-5:]) / 5
                            slow_sma = sum(closes[-20:]) / 20
                            if regime in (RegimeType.TRENDING, RegimeType.LOW_VOLATILITY):
                                signal = "buy" if fast_sma > slow_sma else "hold"
                            elif regime in (RegimeType.MEAN_REVERTING, RegimeType.HIGH_VOLATILITY):
                                signal = "sell" if fast_sma < slow_sma and open_side == "buy" else "hold"
                    elif not use_regime_switcher:
                        # Static MACD approximation — dual-SMA crossover
                        formatted = _candles_to_switcher_format(raw_candles)
                        closes = [c["close"] for c in formatted if c["close"] > 0]
                        if len(closes) >= 20:
                            fast_sma = sum(closes[-5:]) / 5
                            slow_sma = sum(closes[-20:]) / 20
                            signal = "buy" if fast_sma > slow_sma else "sell"

                    # ── Place order if signal is actionable ───────────────────
                    if signal in ("buy", "sell"):
                        # Skip if already in the same direction.
                        if open_side == signal:
                            pass
                        elif open_side is not None and open_side != signal:
                            # Close opposite position before reversing (simple).
                            pass
                        else:
                            try:
                                order_resp = await client.post(
                                    f"/api/v1/backtest/{session_id}/trade/order",
                                    json={
                                        "symbol": "BTCUSDT",
                                        "side": signal,
                                        "type": "market",
                                        "quantity": _BTC_QTY,
                                    },
                                )
                                if order_resp.status_code < 300:
                                    trades_placed += 1
                                    open_position = True
                                    open_side = signal
                                elif order_resp.status_code in (404, 409, 410):
                                    loop_complete = True
                                    break
                            except httpx.HTTPStatusError as exc:
                                if exc.response.status_code in (404, 409, 410):
                                    loop_complete = True
                                    break
                            except httpx.RequestError:
                                pass

                # ── Advance time ──────────────────────────────────────────────
                try:
                    step_resp = await client.post(
                        f"/api/v1/backtest/{session_id}/step/batch",
                        json={"steps": _BATCH_SIZE},
                    )
                    if step_resp.status_code in (404, 409, 410):
                        loop_complete = True
                        break
                    if step_resp.status_code >= 400:
                        log.warning(
                            "agent.strategy.regime.validate.loop.step.http_error",
                            status=step_resp.status_code,
                            iteration=iteration,
                        )
                        break
                    step_data = step_resp.json()
                    if step_data.get("is_complete", False):
                        loop_complete = True
                        break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (404, 409, 410):
                        loop_complete = True
                        break
                    log.warning("agent.strategy.regime.validate.loop.step.exception", error=str(exc))
                    break
                except httpx.RequestError as exc:
                    log.warning("agent.strategy.regime.validate.loop.step.request_error", error=str(exc))
                    break

            log.info(
                "agent.strategy.regime.validate.loop.finished",
                iterations=iterations,
                trades=trades_placed,
                regime_switches=regime_switches,
                loop_complete=loop_complete,
            )

            # ── Fetch results ─────────────────────────────────────────────────
            try:
                results_resp = await client.get(f"/api/v1/backtest/{session_id}/results")
                results_resp.raise_for_status()
                results = results_resp.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                err = f"[{month_label}/{strategy_label}] get_results failed: {exc}"
                log.error("agent.strategy.regime.validate.get_results.failed", error=err)
                self._errors.append(err)
                return MonthlyResult(
                    month_label=month_label,
                    session_id=session_id,
                    strategy_label=strategy_label,
                    regime_switches=regime_switches,
                    total_trades=trades_placed,
                    error=err,
                )

        # ── Parse results ─────────────────────────────────────────────────────
        summary = results.get("summary") or {}
        metrics = results.get("metrics") or {}

        roi_pct = _safe_float(summary.get("roi_pct"))
        final_equity = _safe_float(summary.get("final_equity"))
        total_trades_result = int(summary.get("total_trades") or 0)
        sharpe = _safe_float(metrics.get("sharpe_ratio"))
        max_dd = _safe_float(metrics.get("max_drawdown_pct"))
        win_rate = _safe_float(metrics.get("win_rate"))

        # Determine dominant regime from switcher history.
        dominant_regime: str | None = None
        if use_regime_switcher and switcher is not None:
            dominant_regime = _compute_dominant_regime(
                switcher.get_history(), iterations
            )

        log.info(
            "agent.strategy.regime.validate.result.parsed",
            roi_pct=roi_pct,
            sharpe=sharpe,
            trades=total_trades_result,
            regime_switches=regime_switches,
            dominant_regime=dominant_regime,
        )

        return MonthlyResult(
            month_label=month_label,
            session_id=session_id,
            strategy_label=strategy_label,
            roi_pct=roi_pct,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            win_rate=win_rate,
            total_trades=total_trades_result,
            final_equity=final_equity,
            regime_switches=regime_switches,
            dominant_regime=dominant_regime,
        )

    # ------------------------------------------------------------------
    # Public run methods
    # ------------------------------------------------------------------

    async def run_monthly_backtests(self, months: int | None = None) -> list[MonthlyResult]:
        """Run regime-adaptive backtests for each month in the validation window.

        Builds month windows from the latest available data, then runs one
        backtest session per month in sequence (not concurrently, to avoid
        overloading the platform).

        Args:
            months: Override the number of months.  Uses ``self._months`` when
                ``None``.

        Returns:
            Ordered list (oldest first) of :class:`MonthlyResult` objects for
            the regime-adaptive strategy.  Also stored in
            ``self._regime_results`` for later access.
        """
        n = months if months is not None else self._months
        self._log.info("agent.strategy.regime.validate.regime_backtest.starting", months=n)

        # Discover data range.
        _, latest = await self._get_data_range()
        if latest is None:
            # Fallback: use a known historical range.
            latest = datetime(2024, 3, 1, tzinfo=UTC)
            self._log.warning("agent.strategy.regime.validate.data_range.fallback", latest=latest.isoformat())

        windows = self._build_month_windows(latest)
        # Use only the last *n* windows.
        windows = windows[-n:]
        self._month_windows = windows

        results: list[MonthlyResult] = []
        for start_dt, end_dt, month_label in windows:
            logger.info(
                "agent.strategy.regime.validate.regime_backtest_starting",
                month=month_label,
                start=str(start_dt.date()),
                end=str(end_dt.date()),
            )
            result = await self._run_one_backtest(
                month_label=month_label,
                start_dt=start_dt,
                end_dt=end_dt,
                strategy_label=_REGIME_STRATEGY_LABEL,
                use_regime_switcher=True,
            )
            results.append(result)
            status = "ok" if result.error is None else "error"
            logger.info(
                "agent.strategy.regime.validate.regime_backtest_complete",
                month=month_label,
                roi_pct=str(result.roi_pct),
                regime_switches=result.regime_switches,
                status=status,
                error=result.error,
            )

        self._regime_results = results
        return results

    async def run_static_benchmark(
        self, months: int | None = None
    ) -> list[MonthlyResult]:
        """Run static MACD benchmark backtests for each month in the validation window.

        Uses the same month windows as the regime run (or builds them from the
        latest available data if ``run_monthly_backtests`` has not been called
        yet).

        Args:
            months: Override the number of months.

        Returns:
            Ordered list (oldest first) of :class:`MonthlyResult` objects for
            the static MACD benchmark.  Also stored in ``self._static_results``.
        """
        n = months if months is not None else self._months
        self._log.info("agent.strategy.regime.validate.static_backtest.starting", months=n)

        if not self._month_windows:
            _, latest = await self._get_data_range()
            if latest is None:
                latest = datetime(2024, 3, 1, tzinfo=UTC)
            self._month_windows = self._build_month_windows(latest)

        windows = self._month_windows[-n:]
        results: list[MonthlyResult] = []
        for start_dt, end_dt, month_label in windows:
            logger.info(
                "agent.strategy.regime.validate.static_backtest_starting",
                month=month_label,
                start=str(start_dt.date()),
                end=str(end_dt.date()),
            )
            result = await self._run_one_backtest(
                month_label=month_label,
                start_dt=start_dt,
                end_dt=end_dt,
                strategy_label=_STATIC_STRATEGY_LABEL,
                use_regime_switcher=False,
            )
            results.append(result)
            status = "ok" if result.error is None else "error"
            logger.info(
                "agent.strategy.regime.validate.static_backtest_complete",
                month=month_label,
                roi_pct=str(result.roi_pct),
                total_trades=result.total_trades,
                status=status,
                error=result.error,
            )

        self._static_results = results
        return results

    async def run_buyhold_benchmark(
        self, months: int | None = None
    ) -> list[MonthlyResult]:
        """Run buy-and-hold benchmark backtests for each month.

        Each session buys BTC once at the start and holds to month-end with no
        further trading.

        Args:
            months: Override the number of months.

        Returns:
            Ordered list (oldest first) of :class:`MonthlyResult` for the
            buy-and-hold benchmark.  Also stored in ``self._buyhold_results``.
        """
        n = months if months is not None else self._months
        self._log.info("agent.strategy.regime.validate.buyhold_backtest.starting", months=n)

        if not self._month_windows:
            _, latest = await self._get_data_range()
            if latest is None:
                latest = datetime(2024, 3, 1, tzinfo=UTC)
            self._month_windows = self._build_month_windows(latest)

        windows = self._month_windows[-n:]
        results: list[MonthlyResult] = []
        for start_dt, end_dt, month_label in windows:
            logger.info(
                "agent.strategy.regime.validate.buyhold_backtest_starting",
                month=month_label,
                start=str(start_dt.date()),
                end=str(end_dt.date()),
            )
            result = await self._run_one_backtest(
                month_label=month_label,
                start_dt=start_dt,
                end_dt=end_dt,
                strategy_label=_BUYHOLD_STRATEGY_LABEL,
                use_buyhold=True,
            )
            results.append(result)
            status = "ok" if result.error is None else "error"
            logger.info(
                "agent.strategy.regime.validate.buyhold_backtest_complete",
                month=month_label,
                roi_pct=str(result.roi_pct),
                status=status,
                error=result.error,
            )

        self._buyhold_results = results
        return results

    # ------------------------------------------------------------------
    # Comparison and reporting
    # ------------------------------------------------------------------

    def compare(self) -> list[MonthlySummary]:
        """Build per-month comparisons from the three sets of results.

        Must be called after :meth:`run_monthly_backtests`,
        :meth:`run_static_benchmark`, and :meth:`run_buyhold_benchmark` have
        all completed.

        Returns:
            Ordered list (oldest first) of :class:`MonthlySummary` objects.
        """
        # Build lookup dicts keyed by month_label so we can align all three lists.
        regime_map = {r.month_label: r for r in self._regime_results}
        static_map = {r.month_label: r for r in self._static_results}
        buyhold_map = {r.month_label: r for r in self._buyhold_results}

        all_labels: list[str] = []
        seen: set[str] = set()
        for r in self._regime_results + self._static_results + self._buyhold_results:
            if r.month_label not in seen:
                all_labels.append(r.month_label)
                seen.add(r.month_label)

        summaries: list[MonthlySummary] = []
        for label in all_labels:
            # Provide a placeholder result if a strategy was not run for this month.
            placeholder = MonthlyResult(
                month_label=label,
                session_id=None,
                strategy_label="missing",
                error="Not run for this month.",
            )
            r = regime_map.get(label, placeholder)
            s = static_map.get(label, placeholder)
            b = buyhold_map.get(label, placeholder)

            regime_wins = (
                r.roi_pct is not None
                and s.roi_pct is not None
                and r.roi_pct > s.roi_pct
            )

            summaries.append(
                MonthlySummary(
                    month_label=label,
                    regime=r,
                    static=s,
                    buyhold=b,
                    regime_wins=regime_wins,
                )
            )

        return summaries

    def generate_report(self) -> RegimeValidationReport:
        """Compile a :class:`RegimeValidationReport` from all collected results.

        Returns:
            Fully populated :class:`RegimeValidationReport` ready for JSON
            serialisation.
        """
        summaries = self.compare()

        # Compute aggregate statistics.
        regime_rois = [s.regime.roi_pct for s in summaries if s.regime.roi_pct is not None]
        static_rois = [s.static.roi_pct for s in summaries if s.static.roi_pct is not None]
        buyhold_rois = [s.buyhold.roi_pct for s in summaries if s.buyhold.roi_pct is not None]
        regime_sharpes = [s.regime.sharpe_ratio for s in summaries if s.regime.sharpe_ratio is not None]
        static_sharpes = [s.static.sharpe_ratio for s in summaries if s.static.sharpe_ratio is not None]

        alpha_months = sum(1 for s in summaries if s.regime_wins)
        completed = sum(
            1 for s in summaries
            if s.regime.error is None and s.static.error is None and s.buyhold.error is None
        )

        switches_by_month = {s.regime.month_label: s.regime.regime_switches for s in summaries}
        total_switches = sum(switches_by_month.values())

        regime_better_than_buyhold = sum(
            1 for s in summaries
            if s.regime.roi_pct is not None
            and s.buyhold.roi_pct is not None
            and s.regime.roi_pct > s.buyhold.roi_pct
        )

        def _avg(lst: list[float]) -> float | None:
            return round(sum(lst) / len(lst), 4) if lst else None

        summary = ValidationSummary(
            total_months=len(summaries),
            months_completed=completed,
            regime_avg_roi=_avg(regime_rois),
            static_avg_roi=_avg(static_rois),
            buyhold_avg_roi=_avg(buyhold_rois),
            regime_avg_sharpe=_avg(regime_sharpes),
            static_avg_sharpe=_avg(static_sharpes),
            alpha_months=alpha_months,
            alpha_rate=round(alpha_months / completed, 4) if completed > 0 else None,
            total_regime_switches=total_switches,
            avg_switches_per_month=round(total_switches / len(summaries), 2) if summaries else None,
            regime_better_than_buyhold_months=regime_better_than_buyhold,
        )

        return RegimeValidationReport(
            generated_at=datetime.now(tz=UTC).isoformat(),
            base_url=self._base_url,
            months_requested=self._months,
            per_month=summaries,
            summary=summary,
            regime_switches_by_month=switches_by_month,
            alpha_months=alpha_months,
            errors=self._errors,
        )


# ---------------------------------------------------------------------------
# Orchestration helper
# ---------------------------------------------------------------------------


async def run_full_validation(
    base_url: str,
    api_key: str,
    months: int = 12,
    seed: int = 42,
    health_check_only: bool = False,
) -> RegimeValidationReport | None:
    """Run the full three-strategy validation pipeline and return the report.

    Sequence:
    1. Health check — abort gracefully if platform is unreachable.
    2. Regime-adaptive backtests (``months`` sessions).
    3. Static MACD benchmark (``months`` sessions).
    4. Buy-and-hold benchmark (``months`` sessions).
    5. Compare all results.
    6. Generate and return :class:`RegimeValidationReport`.

    Args:
        base_url: Platform REST API base URL.
        api_key: ``ak_live_...`` API key.
        months: Number of calendar months to run.
        seed: Random seed for the regime classifier.
        health_check_only: When ``True``, only run the health check and exit.

    Returns:
        :class:`RegimeValidationReport` on success.  ``None`` if the health
        check fails or the platform is unavailable.
    """
    validator = RegimeValidator(base_url=base_url, api_key=api_key, months=months, seed=seed)

    logger.info(
        "agent.strategy.regime.validate.harness_starting",
        base_url=base_url,
        months=months,
        seed=seed,
    )

    # Health check.
    logger.info("agent.strategy.regime.validate.health_check_starting")
    healthy = await validator._health_check()
    if not healthy:
        logger.error("agent.strategy.regime.validate.platform_unreachable", base_url=base_url)
        return None
    logger.info("agent.strategy.regime.validate.health_check_passed")

    if health_check_only:
        logger.info("agent.strategy.regime.validate.health_check_only_exit")
        return None

    # Phase 1: Regime-adaptive.
    logger.info("agent.strategy.regime.validate.phase1_starting")
    t0 = time.monotonic()
    await validator.run_monthly_backtests(months=months)
    logger.info("agent.strategy.regime.validate.phase1_complete", elapsed_sec=round(time.monotonic() - t0, 1))

    # Phase 2: Static MACD.
    logger.info("agent.strategy.regime.validate.phase2_starting")
    t0 = time.monotonic()
    await validator.run_static_benchmark(months=months)
    logger.info("agent.strategy.regime.validate.phase2_complete", elapsed_sec=round(time.monotonic() - t0, 1))

    # Phase 3: Buy-and-hold.
    logger.info("agent.strategy.regime.validate.phase3_starting")
    t0 = time.monotonic()
    await validator.run_buyhold_benchmark(months=months)
    logger.info("agent.strategy.regime.validate.phase3_complete", elapsed_sec=round(time.monotonic() - t0, 1))

    # Phase 4: Report.
    logger.info("agent.strategy.regime.validate.phase4_generating")
    report = validator.generate_report()

    _log_summary(report)
    return report


def _log_summary(report: RegimeValidationReport) -> None:
    """Log validation summary via structlog.

    Args:
        report: The completed :class:`RegimeValidationReport`.
    """
    s = report.summary
    logger.info(
        "agent.strategy.regime.validate.results_summary",
        total_months=s.total_months,
        months_completed=s.months_completed,
        error_count=len(report.errors),
        regime_avg_roi=str(s.regime_avg_roi or "n/a"),
        regime_avg_sharpe=str(s.regime_avg_sharpe or "n/a"),
        static_avg_roi=str(s.static_avg_roi or "n/a"),
        static_avg_sharpe=str(s.static_avg_sharpe or "n/a"),
        buyhold_avg_roi=str(s.buyhold_avg_roi or "n/a"),
        alpha_months=s.alpha_months,
        alpha_rate=str(s.alpha_rate or "n/a"),
        regime_better_than_buyhold=s.regime_better_than_buyhold_months,
        total_regime_switches=s.total_regime_switches,
        avg_switches_per_month=str(s.avg_switches_per_month or "n/a"),
        per_month=[
            {
                "month": ms.month_label,
                "regime_roi": str(ms.regime.roi_pct) if ms.regime.roi_pct is not None else "n/a",
                "static_roi": str(ms.static.roi_pct) if ms.static.roi_pct is not None else "n/a",
                "bh_roi": str(ms.buyhold.roi_pct) if ms.buyhold.roi_pct is not None else "n/a",
                "switches": ms.regime.regime_switches,
                "alpha": ms.regime_wins,
            }
            for ms in (report.per_month or [])
        ],
        errors=report.errors[:10] if report.errors else [],
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _main() -> int:
    """Async CLI entry point.

    Returns:
        Exit code: 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Regime strategy validation harness.\n"
            "Runs regime-adaptive, static MACD, and buy-and-hold backtests "
            "across N consecutive calendar months and saves a JSON comparison report."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Platform REST API base URL.",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=12,
        help="Number of consecutive calendar months to validate.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for the regime classifier (used when training on synthetic data).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_REPORTS_DIR),
        help="Directory where the JSON report will be written.",
    )
    parser.add_argument(
        "--health-check-only",
        action="store_true",
        help="Only test platform connectivity — do not run any backtests.",
    )

    args = parser.parse_args()

    import os  # noqa: PLC0415

    api_key = os.environ.get("PLATFORM_API_KEY", "")

    if not api_key and not args.health_check_only:
        print(  # noqa: T201
            "ERROR: Platform API key not set. "
            "Set PLATFORM_API_KEY in agent/.env or as environment variable.\n"
            "Run with --help for usage information.",
            file=sys.stderr,
        )
        return 1

    report = await run_full_validation(
        base_url=args.base_url,
        api_key=api_key,
        months=args.months,
        seed=args.seed,
        health_check_only=args.health_check_only,
    )

    if report is None:
        # Platform unavailable or health-check-only exit.
        return 0 if args.health_check_only else 1

    # Save report to disk.
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"regime-validation-{timestamp}.json"

    try:
        output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        logger.info("agent.strategy.regime.validate.report_saved", path=str(output_path))
    except OSError as exc:
        logger.warning("agent.strategy.regime.validate.report_write_failed", error=str(exc))

    # Exit 0 if no platform errors, 1 if any backtest errored.
    return 0 if not report.errors else 1


def main() -> None:
    """Synchronous CLI entry point for ``python -m agent.strategies.regime.validate``."""
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
