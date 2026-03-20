"""Ensemble validation harness — cross-strategy comparison across historical periods.

Runs 4 strategy configurations (Ensemble, PPO-only, Evolved-only, Regime-only)
plus a buy-and-hold baseline for each requested time period, collecting Sharpe
ratio, ROI, maximum drawdown, and win rate from the platform backtest engine.
Produces a JSON-serialisable ``EnsembleValidationReport`` Pydantic model and
writes it to ``agent/reports/``.

Strategy configurations tested per period
------------------------------------------
1. Ensemble    — all three sources enabled (RL + EVOLVED + REGIME)
2. PPO-only    — RL enabled; EVOLVED and REGIME disabled
3. Evolved-only— EVOLVED enabled; RL and REGIME disabled
4. Regime-only — REGIME enabled; RL and EVOLVED disabled

Buy-and-hold baseline
---------------------
Simulated by placing a single BUY market order at the start of the period for
each symbol, then reading the final equity from the backtest results.  No
further trades are placed.

CLI usage
---------
::

    python -m agent.strategies.ensemble.validate \\
        --base-url http://localhost:8000 \\
        --periods 3 \\
        [--days 7] \\
        [--output-dir agent/reports] \\
        [--symbols BTCUSDT ETHUSDT]

Prerequisites
-------------
- Platform API running at ``--base-url`` (default ``http://localhost:8000``).
- Historical candle data available (check ``GET /api/v1/market/data-range``).
- ``PLATFORM_API_KEY`` set in ``agent/.env`` or as an environment variable.

If the platform is unavailable, all strategy runs are marked as ``error`` and
the report is still written with ``platform_available=False``.
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
from pydantic import BaseModel, ConfigDict, Field

from agent.strategies.ensemble.config import EnsembleConfig
from agent.strategies.ensemble.run import EnsembleRunner

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "http://localhost:8000"
_CANDLE_INTERVAL: int = 60        # 1-minute candles (matches EnsembleRunner default)
_STARTING_BALANCE: str = "10000"  # USDT starting balance per backtest session

# Per-symbol BUY quantities used for the buy-and-hold baseline.
_BUY_HOLD_QTY: dict[str, str] = {
    "BTCUSDT": "0.0001",
    "ETHUSDT": "0.001",
    "SOLUSDT": "0.01",
}
_DEFAULT_QTY: str = "0.001"

# Strategy configuration names (human-readable labels used throughout reports).
_STRATEGY_ENSEMBLE = "Ensemble"
_STRATEGY_PPO = "PPO-only"
_STRATEGY_EVOLVED = "Evolved-only"
_STRATEGY_REGIME = "Regime-only"
_STRATEGY_BUYHOLD = "Buy-and-Hold"

ALL_STRATEGY_NAMES = [
    _STRATEGY_ENSEMBLE,
    _STRATEGY_PPO,
    _STRATEGY_EVOLVED,
    _STRATEGY_REGIME,
    _STRATEGY_BUYHOLD,
]


# ── Pydantic output models ────────────────────────────────────────────────────


class StrategyMetrics(BaseModel):
    """Performance metrics for one strategy in one period.

    Args:
        strategy_name: Human-readable strategy label.
        session_id: Backtest session UUID, or ``"error"`` / ``"buyhold_sim"``.
        sharpe_ratio: Annualised Sharpe ratio.  ``None`` if unavailable.
        roi_pct: Return-on-investment as a percentage.  ``None`` if unavailable.
        max_drawdown_pct: Maximum drawdown as a percentage (positive = loss).
        win_rate: Fraction of profitable trades (0–1).  ``None`` if unavailable.
        total_trades: Total orders executed during the period.
        final_equity: Final portfolio equity in USDT.
        error: Non-``None`` if the backtest run failed.
        ensemble_steps: Number of ensemble decision steps executed.
        orders_placed: Number of orders successfully submitted.
    """

    model_config = ConfigDict(frozen=True)

    strategy_name: str
    session_id: str = "unknown"
    sharpe_ratio: float | None = None
    roi_pct: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    total_trades: int = 0
    final_equity: float | None = None
    error: str | None = None
    ensemble_steps: int = 0
    orders_placed: int = 0


class PeriodResult(BaseModel):
    """All strategy results for one backtest period.

    Args:
        period_index: Zero-based index of this period in the comparison run.
        start: ISO-8601 UTC start timestamp.
        end: ISO-8601 UTC end timestamp.
        strategies: Metrics for each of the five strategies (Ensemble,
            PPO-only, Evolved-only, Regime-only, Buy-and-Hold).
        winner: Name of the strategy with the highest Sharpe ratio.
            ``None`` if no valid Sharpe ratios are available.
        ensemble_vs_best_individual_sharpe: Ensemble Sharpe minus the best
            single-source Sharpe (positive = ensemble wins).
    """

    model_config = ConfigDict(frozen=True)

    period_index: int
    start: str
    end: str
    strategies: list[StrategyMetrics]
    winner: str | None = None
    ensemble_vs_best_individual_sharpe: float | None = None


class ValidationSummary(BaseModel):
    """Aggregate statistics across all periods.

    Args:
        avg_sharpe_by_strategy: Mean Sharpe ratio per strategy (NaN-safe).
        best_strategy_counts: Number of periods each strategy had the highest Sharpe.
        total_periods: Total number of periods evaluated.
        periods_with_data: Periods where at least one strategy returned metrics.
    """

    model_config = ConfigDict(frozen=True)

    avg_sharpe_by_strategy: dict[str, float]
    best_strategy_counts: dict[str, int]
    total_periods: int
    periods_with_data: int


class EnsembleValidationReport(BaseModel):
    """Full cross-strategy validation report across all periods.

    Args:
        report_id: Unique identifier for this validation run (timestamp-based).
        generated_at: ISO-8601 UTC timestamp when the report was produced.
        base_url: Platform REST API base URL used.
        symbols: Trading pairs included in each backtest.
        period_days: Length of each backtest period in calendar days.
        platform_available: Whether the platform was reachable during the run.
        per_period: Per-period breakdown of all strategy results and the winner.
        summary: Aggregate Sharpe averages and win counts across all periods.
        ensemble_wins: Number of periods where Ensemble beats every individual
            strategy (by Sharpe ratio).
        improvement_vs_baseline: Mean percentage improvement of Ensemble ROI
            over the Buy-and-Hold baseline across all periods where both have
            valid ROI values.
        errors: List of non-fatal error messages accumulated during the run.
    """

    model_config = ConfigDict(frozen=True)

    report_id: str
    generated_at: str
    base_url: str
    symbols: list[str]
    period_days: int
    platform_available: bool
    per_period: list[PeriodResult]
    summary: ValidationSummary
    ensemble_wins: int
    improvement_vs_baseline: float | None
    errors: list[str]


# ── EnsembleValidator ─────────────────────────────────────────────────────────


class EnsembleValidator:
    """Runs cross-strategy backtests and produces a validation report.

    For each requested period, five backtest sessions are created and run:
    one for each of the four strategy configurations, plus a buy-and-hold
    baseline.  Results are collected, compared, and returned as an
    ``EnsembleValidationReport``.

    Args:
        base_url: Platform REST API base URL.
        api_key: Platform API key (``ak_live_...``).
        symbols: Trading pairs to include in each backtest.
        period_days: Calendar days per backtest window.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        api_key: str = "",
        symbols: list[str] | None = None,
        period_days: int = 7,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        self._period_days = period_days
        self._errors: list[str] = []

    # ── Prerequisites check ───────────────────────────────────────────────────

    async def _check_platform(self) -> bool:
        """Return True if the platform health endpoint responds 200.

        Returns:
            True when the platform is available, False otherwise.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=10.0,
            ) as client:
                resp = await client.get("/api/v1/health")
                return resp.status_code == 200
        except (httpx.RequestError, httpx.HTTPStatusError):
            return False

    # ── Date resolution ───────────────────────────────────────────────────────

    async def _resolve_periods(
        self,
        n_periods: int,
    ) -> list[tuple[str, str]]:
        """Resolve *n_periods* non-overlapping backtest windows.

        Uses the platform ``/market/data-range`` endpoint to anchor the most
        recent period at the latest available candle data.  Each prior period
        steps back by ``period_days``.  Falls back to fixed 2024 dates if the
        endpoint is unavailable.

        Args:
            n_periods: Number of periods to produce.

        Returns:
            List of ``(start_iso, end_iso)`` tuples, most recent last.
        """
        end_dt: datetime | None = None

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"X-API-Key": self._api_key},
                timeout=10.0,
            ) as client:
                resp = await client.get("/api/v1/market/data-range")
                resp.raise_for_status()
                latest_str: str | None = resp.json().get("latest")
                if latest_str:
                    latest_str = latest_str.replace("Z", "+00:00")
                    end_dt = datetime.fromisoformat(latest_str).astimezone(UTC)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            warn = f"Could not resolve data range from platform: {exc}. Using fallback."
            log.warning("validator.date_range_failed", error=str(exc))
            self._errors.append(warn)

        if end_dt is None:
            # Fallback: use a known-good range from historical test data.
            end_dt = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)

        periods: list[tuple[str, str]] = []
        current_end = end_dt
        for _ in range(n_periods):
            current_start = current_end - timedelta(days=self._period_days)
            periods.append((
                current_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                current_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ))
            current_end = current_start

        # Return in chronological order (oldest first).
        return list(reversed(periods))

    # ── EnsembleConfig factory ────────────────────────────────────────────────

    def _make_config(
        self,
        strategy_name: str,
    ) -> EnsembleConfig:
        """Build an ``EnsembleConfig`` for the given strategy variant.

        Args:
            strategy_name: One of the four strategy name constants.

        Returns:
            Configured :class:`EnsembleConfig` instance.
        """
        base_kwargs: dict[str, Any] = {
            "mode": "backtest",
            "symbols": self._symbols,
            "platform_api_key": self._api_key,
            "platform_base_url": self._base_url,
            "enable_risk_overlay": False,  # disabled — no SDK client in validator
            "max_iterations": 30,
            "batch_size": 5,
        }

        if strategy_name == _STRATEGY_ENSEMBLE:
            return EnsembleConfig(
                **base_kwargs,
                enable_rl_signal=True,
                enable_evolved_signal=True,
                enable_regime_signal=True,
            )
        elif strategy_name == _STRATEGY_PPO:
            return EnsembleConfig(
                **base_kwargs,
                enable_rl_signal=True,
                enable_evolved_signal=False,
                enable_regime_signal=False,
            )
        elif strategy_name == _STRATEGY_EVOLVED:
            return EnsembleConfig(
                **base_kwargs,
                enable_rl_signal=False,
                enable_evolved_signal=True,
                enable_regime_signal=False,
            )
        elif strategy_name == _STRATEGY_REGIME:
            return EnsembleConfig(
                **base_kwargs,
                enable_rl_signal=False,
                enable_evolved_signal=False,
                enable_regime_signal=True,
            )
        else:
            raise ValueError(f"Unknown strategy name: {strategy_name!r}")

    # ── Single backtest run ───────────────────────────────────────────────────

    async def _run_strategy(
        self,
        strategy_name: str,
        start: str,
        end: str,
        rest_client: httpx.AsyncClient,
    ) -> StrategyMetrics:
        """Run one strategy configuration for one period.

        Creates an ``EnsembleRunner`` with the matching config, runs a full
        backtest session, then fetches results from the platform.

        Args:
            strategy_name: Strategy variant identifier.
            start: ISO-8601 UTC start of the backtest window.
            end: ISO-8601 UTC end of the backtest window.
            rest_client: Authenticated ``httpx.AsyncClient`` pointed at the platform.

        Returns:
            :class:`StrategyMetrics` with the results (or an error description
            when the backtest fails).
        """
        log.info(
            "validator.run_strategy.start",
            strategy=strategy_name,
            start=start,
            end=end,
        )

        config = self._make_config(strategy_name)
        runner = EnsembleRunner(
            config=config,
            sdk_client=None,
            rest_client=rest_client,
        )

        try:
            await runner.initialize()
        except Exception as exc:  # noqa: BLE001
            err = f"EnsembleRunner.initialize() failed for {strategy_name}: {exc}"
            log.error("validator.run_strategy.init_failed", strategy=strategy_name, error=str(exc))
            self._errors.append(err)
            return StrategyMetrics(
                strategy_name=strategy_name,
                error=err,
            )

        try:
            ensemble_report = await runner.run_backtest(start=start, end=end)
        except Exception as exc:  # noqa: BLE001
            err = f"run_backtest failed for {strategy_name}: {exc}"
            log.error("validator.run_strategy.backtest_failed", strategy=strategy_name, error=str(exc))
            self._errors.append(err)
            return StrategyMetrics(
                strategy_name=strategy_name,
                error=err,
            )

        session_id = ensemble_report.session_id
        if session_id in ("error", "unknown"):
            err = f"Backtest session failed to start for {strategy_name} (session_id={session_id!r})"
            log.warning("validator.run_strategy.bad_session", strategy=strategy_name, session_id=session_id)
            return StrategyMetrics(
                strategy_name=strategy_name,
                session_id=session_id,
                ensemble_steps=ensemble_report.total_steps,
                orders_placed=ensemble_report.total_orders_placed,
                error=err,
            )

        # Fetch detailed results from the platform.
        metrics = await self._fetch_backtest_metrics(session_id, rest_client)

        log.info(
            "validator.run_strategy.complete",
            strategy=strategy_name,
            session_id=session_id,
            sharpe=metrics.get("sharpe_ratio"),
            roi_pct=metrics.get("roi_pct"),
        )

        return StrategyMetrics(
            strategy_name=strategy_name,
            session_id=session_id,
            sharpe_ratio=metrics.get("sharpe_ratio"),
            roi_pct=metrics.get("roi_pct"),
            max_drawdown_pct=metrics.get("max_drawdown_pct"),
            win_rate=metrics.get("win_rate"),
            total_trades=int(metrics.get("total_trades") or 0),
            final_equity=metrics.get("final_equity"),
            ensemble_steps=ensemble_report.total_steps,
            orders_placed=ensemble_report.total_orders_placed,
        )

    async def _fetch_backtest_metrics(
        self,
        session_id: str,
        rest_client: httpx.AsyncClient,
    ) -> dict[str, Any]:
        """Fetch and normalise backtest result metrics from the platform.

        Args:
            session_id: Backtest session UUID.
            rest_client: Authenticated ``httpx.AsyncClient``.

        Returns:
            Dict with keys ``sharpe_ratio``, ``roi_pct``, ``max_drawdown_pct``,
            ``win_rate``, ``total_trades``, ``final_equity``.  Each key maps to
            ``None`` if the platform did not return that metric.
        """
        result: dict[str, Any] = {
            "sharpe_ratio": None,
            "roi_pct": None,
            "max_drawdown_pct": None,
            "win_rate": None,
            "total_trades": None,
            "final_equity": None,
        }

        try:
            resp = await rest_client.get(f"/api/v1/backtest/{session_id}/results")
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            warn = f"Could not fetch results for session {session_id}: {exc}"
            log.warning("validator.fetch_metrics.failed", session_id=session_id, error=str(exc))
            self._errors.append(warn)
            return result

        summary: dict[str, Any] = data.get("summary") or {}
        bt_metrics: dict[str, Any] = data.get("metrics") or {}

        def _safe_float(v: Any) -> float | None:
            if v is None:
                return None
            try:
                f = float(v)
                return None if (f != f) else f  # reject NaN
            except (ValueError, TypeError):
                return None

        result["sharpe_ratio"] = _safe_float(bt_metrics.get("sharpe_ratio"))
        result["max_drawdown_pct"] = _safe_float(bt_metrics.get("max_drawdown_pct"))
        result["win_rate"] = _safe_float(bt_metrics.get("win_rate"))
        result["roi_pct"] = _safe_float(summary.get("roi_pct"))
        result["total_trades"] = summary.get("total_trades")
        result["final_equity"] = _safe_float(summary.get("final_equity"))

        return result

    # ── Buy-and-hold baseline ─────────────────────────────────────────────────

    async def run_buyhold_baseline(
        self,
        periods: list[tuple[str, str]],
        rest_client: httpx.AsyncClient,
    ) -> list[StrategyMetrics]:
        """Run a buy-and-hold baseline for each period.

        Creates a backtest session, places a single BUY for each symbol at the
        start, advances the session to completion, then reads the final equity.
        Sharpe, win rate, and drawdown are taken from platform results; ROI is
        computed from starting and final equity when available.

        Args:
            periods: List of ``(start_iso, end_iso)`` tuples.
            rest_client: Authenticated ``httpx.AsyncClient``.

        Returns:
            One :class:`StrategyMetrics` per period.
        """
        results: list[StrategyMetrics] = []
        for start, end in periods:
            log.info("validator.buyhold.start", start=start, end=end)
            metrics = await self._run_buyhold_period(start, end, rest_client)
            results.append(metrics)
        return results

    async def _run_buyhold_period(
        self,
        start: str,
        end: str,
        rest_client: httpx.AsyncClient,
    ) -> StrategyMetrics:
        """Execute one buy-and-hold period.

        Creates a backtest session, places BUY orders for all symbols at the
        first step, then steps through to completion without further trading.

        Args:
            start: ISO-8601 UTC start of the backtest window.
            end: ISO-8601 UTC end of the backtest window.
            rest_client: Authenticated ``httpx.AsyncClient``.

        Returns:
            :class:`StrategyMetrics` for the buy-and-hold strategy.
        """
        session_id: str | None = None

        # Create session.
        try:
            create_resp = await rest_client.post(
                "/api/v1/backtest/create",
                json={
                    "start_time": start,
                    "end_time": end,
                    "pairs": self._symbols,
                    "candle_interval": _CANDLE_INTERVAL,
                    "starting_balance": _STARTING_BALANCE,
                    "strategy_label": "buyhold_baseline",
                },
            )
            create_resp.raise_for_status()
            session_id = create_resp.json().get("session_id")
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            err = f"Buy-and-hold: create session failed: {exc}"
            self._errors.append(err)
            return StrategyMetrics(strategy_name=_STRATEGY_BUYHOLD, error=err)

        if not session_id:
            err = "Buy-and-hold: no session_id returned on create"
            self._errors.append(err)
            return StrategyMetrics(strategy_name=_STRATEGY_BUYHOLD, error=err)

        # Start session.
        try:
            start_resp = await rest_client.post(f"/api/v1/backtest/{session_id}/start")
            start_resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            err = f"Buy-and-hold: start session failed: {exc}"
            self._errors.append(err)
            return StrategyMetrics(
                strategy_name=_STRATEGY_BUYHOLD,
                session_id=session_id,
                error=err,
            )

        # Place initial BUY for each symbol.
        orders_placed = 0
        for sym in self._symbols:
            qty = _BUY_HOLD_QTY.get(sym, _DEFAULT_QTY)
            try:
                order_resp = await rest_client.post(
                    f"/api/v1/backtest/{session_id}/trade/order",
                    json={
                        "symbol": sym,
                        "side": "buy",
                        "type": "market",
                        "quantity": qty,
                    },
                )
                if order_resp.status_code < 300:
                    orders_placed += 1
                    log.debug(
                        "validator.buyhold.buy_placed",
                        symbol=sym,
                        qty=qty,
                        session_id=session_id,
                    )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                warn = f"Buy-and-hold: BUY {sym} failed: {exc}"
                log.warning("validator.buyhold.order_failed", symbol=sym, error=str(exc))
                self._errors.append(warn)

        # Step through to completion without further trading.
        completed = False
        for _ in range(200):  # safety limit: 200 × 5 steps = 1000 candles max
            try:
                step_resp = await rest_client.post(
                    f"/api/v1/backtest/{session_id}/step/batch",
                    json={"steps": 5},
                )
                step_resp.raise_for_status()
                if step_resp.json().get("is_complete"):
                    completed = True
                    break
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if status_code in (404, 409, 410):
                    completed = True
                else:
                    warn = f"Buy-and-hold: step failed: {exc}"
                    self._errors.append(warn)
                break

        log.info(
            "validator.buyhold.session_done",
            session_id=session_id,
            completed=completed,
            orders_placed=orders_placed,
        )

        # Fetch results.
        bh_metrics = await self._fetch_backtest_metrics(session_id, rest_client)

        return StrategyMetrics(
            strategy_name=_STRATEGY_BUYHOLD,
            session_id=session_id,
            sharpe_ratio=bh_metrics.get("sharpe_ratio"),
            roi_pct=bh_metrics.get("roi_pct"),
            max_drawdown_pct=bh_metrics.get("max_drawdown_pct"),
            win_rate=bh_metrics.get("win_rate"),
            total_trades=int(bh_metrics.get("total_trades") or 0),
            final_equity=bh_metrics.get("final_equity"),
            orders_placed=orders_placed,
        )

    # ── Per-period comparison ─────────────────────────────────────────────────

    async def run_comparison(
        self,
        periods: list[tuple[str, str]],
    ) -> list[PeriodResult]:
        """Run all four strategy configurations for each period.

        For each period creates one ``httpx.AsyncClient`` shared across the
        five runs (four configured strategies + buy-and-hold), then assembles
        a :class:`PeriodResult`.

        Args:
            periods: List of ``(start_iso, end_iso)`` tuples (chronological).

        Returns:
            One :class:`PeriodResult` per period.
        """
        period_results: list[PeriodResult] = []

        for idx, (start, end) in enumerate(periods):
            log.info(
                "validator.comparison.period_start",
                period_index=idx,
                start=start,
                end=end,
                n_strategies=4,
            )

            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"X-API-Key": self._api_key},
                timeout=120.0,
            ) as rest_client:
                # Run the four configured strategies sequentially to avoid
                # overwhelming the platform with concurrent backtest sessions.
                strategy_metrics: list[StrategyMetrics] = []

                for strategy_name in [
                    _STRATEGY_ENSEMBLE,
                    _STRATEGY_PPO,
                    _STRATEGY_EVOLVED,
                    _STRATEGY_REGIME,
                ]:
                    metrics = await self._run_strategy(
                        strategy_name=strategy_name,
                        start=start,
                        end=end,
                        rest_client=rest_client,
                    )
                    strategy_metrics.append(metrics)

                # Buy-and-hold baseline.
                bh_metrics = await self._run_buyhold_period(start, end, rest_client)
                strategy_metrics.append(bh_metrics)

            period_result = self._build_period_result(
                period_index=idx,
                start=start,
                end=end,
                strategies=strategy_metrics,
            )
            period_results.append(period_result)
            log.info(
                "validator.comparison.period_done",
                period_index=idx,
                winner=period_result.winner,
                ensemble_vs_best=period_result.ensemble_vs_best_individual_sharpe,
            )

        return period_results

    def _build_period_result(
        self,
        period_index: int,
        start: str,
        end: str,
        strategies: list[StrategyMetrics],
    ) -> PeriodResult:
        """Assemble a PeriodResult from the collected strategy metrics.

        Args:
            period_index: Zero-based period counter.
            start: ISO-8601 period start.
            end: ISO-8601 period end.
            strategies: Metrics for all five strategies.

        Returns:
            :class:`PeriodResult` with winner and ensemble delta computed.
        """
        # Determine the winner (highest Sharpe; NaN-safe).
        best_sharpe: float | None = None
        winner: str | None = None
        for m in strategies:
            if m.sharpe_ratio is not None:
                if best_sharpe is None or m.sharpe_ratio > best_sharpe:
                    best_sharpe = m.sharpe_ratio
                    winner = m.strategy_name

        # Compute ensemble Sharpe vs. best individual source Sharpe.
        ensemble_sharpe: float | None = next(
            (m.sharpe_ratio for m in strategies if m.strategy_name == _STRATEGY_ENSEMBLE),
            None,
        )
        individual_sharpes: list[float] = [
            m.sharpe_ratio
            for m in strategies
            if m.strategy_name in (_STRATEGY_PPO, _STRATEGY_EVOLVED, _STRATEGY_REGIME)
            and m.sharpe_ratio is not None
        ]
        best_individual: float | None = max(individual_sharpes) if individual_sharpes else None

        ensemble_vs_best: float | None = None
        if ensemble_sharpe is not None and best_individual is not None:
            ensemble_vs_best = round(ensemble_sharpe - best_individual, 4)

        return PeriodResult(
            period_index=period_index,
            start=start,
            end=end,
            strategies=strategies,
            winner=winner,
            ensemble_vs_best_individual_sharpe=ensemble_vs_best,
        )

    # ── Full comparison ───────────────────────────────────────────────────────

    def compare_all(self, period_results: list[PeriodResult]) -> ValidationSummary:
        """Compute aggregate statistics from all period results.

        Args:
            period_results: Output of :meth:`run_comparison`.

        Returns:
            :class:`ValidationSummary` with per-strategy averages and
            win counts.
        """
        sharpe_sums: dict[str, list[float]] = {name: [] for name in ALL_STRATEGY_NAMES}
        win_counts: dict[str, int] = {name: 0 for name in ALL_STRATEGY_NAMES}
        periods_with_data = 0

        for pr in period_results:
            has_data = any(m.sharpe_ratio is not None for m in pr.strategies)
            if has_data:
                periods_with_data += 1

            for m in pr.strategies:
                if m.sharpe_ratio is not None:
                    sharpe_sums[m.strategy_name].append(m.sharpe_ratio)

            if pr.winner:
                win_counts[pr.winner] = win_counts.get(pr.winner, 0) + 1

        avg_sharpe: dict[str, float] = {}
        for name in ALL_STRATEGY_NAMES:
            vals = sharpe_sums[name]
            avg_sharpe[name] = round(sum(vals) / len(vals), 4) if vals else 0.0

        return ValidationSummary(
            avg_sharpe_by_strategy=avg_sharpe,
            best_strategy_counts=win_counts,
            total_periods=len(period_results),
            periods_with_data=periods_with_data,
        )

    def _count_ensemble_wins(self, period_results: list[PeriodResult]) -> int:
        """Count periods where Ensemble beats every individual strategy.

        A win requires Ensemble Sharpe to be strictly greater than PPO-only,
        Evolved-only, and Regime-only Sharpe ratios.  Periods where any
        individual strategy has no Sharpe data are excluded from the count.

        Args:
            period_results: Output of :meth:`run_comparison`.

        Returns:
            Integer count of ensemble wins.
        """
        wins = 0
        for pr in period_results:
            by_name = {m.strategy_name: m for m in pr.strategies}
            ensemble = by_name.get(_STRATEGY_ENSEMBLE)
            if ensemble is None or ensemble.sharpe_ratio is None:
                continue

            individuals = [
                by_name.get(_STRATEGY_PPO),
                by_name.get(_STRATEGY_EVOLVED),
                by_name.get(_STRATEGY_REGIME),
            ]
            # All three individuals must have valid Sharpe data for a fair comparison.
            if any(m is None or m.sharpe_ratio is None for m in individuals):
                continue

            if all(
                ensemble.sharpe_ratio > m.sharpe_ratio  # type: ignore[union-attr]
                for m in individuals
            ):
                wins += 1

        return wins

    def _compute_improvement_vs_baseline(
        self,
        period_results: list[PeriodResult],
    ) -> float | None:
        """Compute mean ROI improvement of Ensemble over Buy-and-Hold.

        For each period where both have valid ROI values, compute
        ``(ensemble_roi - buyhold_roi)``.  Return the mean across all such
        periods, or ``None`` if no valid pairs exist.

        Args:
            period_results: Output of :meth:`run_comparison`.

        Returns:
            Mean ROI delta as a float (positive = Ensemble beats baseline),
            or ``None`` if no comparison is possible.
        """
        deltas: list[float] = []
        for pr in period_results:
            by_name = {m.strategy_name: m for m in pr.strategies}
            ensemble = by_name.get(_STRATEGY_ENSEMBLE)
            buyhold = by_name.get(_STRATEGY_BUYHOLD)
            if (
                ensemble is not None
                and ensemble.roi_pct is not None
                and buyhold is not None
                and buyhold.roi_pct is not None
            ):
                deltas.append(ensemble.roi_pct - buyhold.roi_pct)

        if not deltas:
            return None
        return round(sum(deltas) / len(deltas), 4)

    # ── Report generation ─────────────────────────────────────────────────────

    async def generate_report(
        self,
        n_periods: int = 3,
    ) -> EnsembleValidationReport:
        """Run the full validation and produce a report.

        Orchestrates:
        1. Platform availability check.
        2. Period resolution (via data-range endpoint).
        3. Cross-strategy comparison across all periods.
        4. Aggregate summary computation.

        Args:
            n_periods: Number of non-overlapping backtest periods to evaluate.

        Returns:
            :class:`EnsembleValidationReport` — always returned, even if the
            platform is unavailable (``platform_available=False`` in that case).
        """
        report_id = f"ensemble-validation-{int(time.time())}"
        generated_at = datetime.now(UTC).isoformat()

        log.info(
            "validator.generate_report.start",
            report_id=report_id,
            n_periods=n_periods,
            symbols=self._symbols,
            period_days=self._period_days,
        )

        # 1. Check platform availability.
        platform_available = await self._check_platform()
        if not platform_available:
            warn = (
                f"Platform at {self._base_url} is not reachable. "
                "All backtest runs will be skipped."
            )
            log.error("validator.platform_unavailable", base_url=self._base_url)
            self._errors.append(warn)

            # Return empty report immediately.
            empty_summary = ValidationSummary(
                avg_sharpe_by_strategy={name: 0.0 for name in ALL_STRATEGY_NAMES},
                best_strategy_counts={name: 0 for name in ALL_STRATEGY_NAMES},
                total_periods=0,
                periods_with_data=0,
            )
            return EnsembleValidationReport(
                report_id=report_id,
                generated_at=generated_at,
                base_url=self._base_url,
                symbols=self._symbols,
                period_days=self._period_days,
                platform_available=False,
                per_period=[],
                summary=empty_summary,
                ensemble_wins=0,
                improvement_vs_baseline=None,
                errors=list(self._errors),
            )

        # 2. Resolve backtest periods.
        periods = await self._resolve_periods(n_periods)
        log.info(
            "validator.periods_resolved",
            n_periods=len(periods),
            first_start=periods[0][0] if periods else "none",
            last_end=periods[-1][1] if periods else "none",
        )

        # 3. Run cross-strategy comparison.
        period_results = await self.run_comparison(periods)

        # 4. Aggregate summary.
        summary = self.compare_all(period_results)
        ensemble_wins = self._count_ensemble_wins(period_results)
        improvement = self._compute_improvement_vs_baseline(period_results)

        log.info(
            "validator.generate_report.done",
            report_id=report_id,
            ensemble_wins=ensemble_wins,
            improvement_vs_baseline=improvement,
            periods_with_data=summary.periods_with_data,
        )

        return EnsembleValidationReport(
            report_id=report_id,
            generated_at=generated_at,
            base_url=self._base_url,
            symbols=self._symbols,
            period_days=self._period_days,
            platform_available=True,
            per_period=period_results,
            summary=summary,
            ensemble_wins=ensemble_wins,
            improvement_vs_baseline=improvement,
            errors=list(self._errors),
        )


# ── CLI ────────────────────────────────────────────────────────────────────────


def _print_report_summary(report: EnsembleValidationReport) -> None:
    """Print a human-readable summary of the validation report to stdout.

    Args:
        report: Completed :class:`EnsembleValidationReport`.
    """
    print()
    print("=" * 70)
    print("  ENSEMBLE VALIDATION REPORT")
    print("=" * 70)
    print(f"  Report ID        : {report.report_id}")
    print(f"  Generated        : {report.generated_at}")
    print(f"  Platform         : {report.base_url}  (available={report.platform_available})")
    print(f"  Symbols          : {', '.join(report.symbols)}")
    print(f"  Period length    : {report.period_days} days")
    print(f"  Periods tested   : {report.summary.total_periods}")
    print(f"  Periods with data: {report.summary.periods_with_data}")
    print()

    if not report.per_period:
        print("  No period results available.")
    else:
        for pr in report.per_period:
            print(f"  Period {pr.period_index}: {pr.start} → {pr.end}")
            print(f"    Winner : {pr.winner or 'none'}")
            if pr.ensemble_vs_best_individual_sharpe is not None:
                delta = pr.ensemble_vs_best_individual_sharpe
                sign = "+" if delta >= 0 else ""
                print(f"    Ensemble vs best individual Sharpe: {sign}{delta:.4f}")
            for m in pr.strategies:
                sharpe_str = f"{m.sharpe_ratio:.4f}" if m.sharpe_ratio is not None else "N/A"
                roi_str = f"{m.roi_pct:.2f}%" if m.roi_pct is not None else "N/A"
                dd_str = f"{m.max_drawdown_pct:.2f}%" if m.max_drawdown_pct is not None else "N/A"
                wr_str = f"{m.win_rate:.2%}" if m.win_rate is not None else "N/A"
                err_str = f"  [ERROR: {m.error[:60]}]" if m.error else ""
                print(
                    f"    {m.strategy_name:<15} Sharpe={sharpe_str:<8} "
                    f"ROI={roi_str:<9} DD={dd_str:<8} WinRate={wr_str}{err_str}"
                )
            print()

    print("-" * 70)
    print("  SUMMARY")
    print("-" * 70)
    print("  Average Sharpe by strategy:")
    for name, avg in sorted(
        report.summary.avg_sharpe_by_strategy.items(),
        key=lambda kv: kv[1],
        reverse=True,
    ):
        wins = report.summary.best_strategy_counts.get(name, 0)
        print(f"    {name:<15} avg_sharpe={avg:>7.4f}  period_wins={wins}")

    print()
    print(f"  Ensemble wins (beats all individuals): {report.ensemble_wins} / {report.summary.total_periods}")

    if report.improvement_vs_baseline is not None:
        sign = "+" if report.improvement_vs_baseline >= 0 else ""
        print(f"  Ensemble vs Buy-and-Hold ROI delta:   {sign}{report.improvement_vs_baseline:.4f}%")
    else:
        print("  Ensemble vs Buy-and-Hold ROI delta:   N/A")

    if report.errors:
        print()
        print(f"  Errors / warnings ({len(report.errors)}):")
        for err in report.errors:
            print(f"    - {err}")
    print("=" * 70)


async def _cli_main(
    base_url: str,
    api_key: str,
    n_periods: int,
    period_days: int,
    symbols: list[str],
    output_dir: Path,
) -> int:
    """Async CLI entry point.

    Args:
        base_url: Platform REST API base URL.
        api_key: Platform API key.
        n_periods: Number of backtest periods to evaluate.
        period_days: Length of each period in calendar days.
        symbols: Trading pairs to include.
        output_dir: Directory where the JSON report is written.

    Returns:
        Exit code (0 = success, 1 = failure or unavailable platform).
    """
    import logging  # noqa: PLC0415

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ]
    )

    print(f"\nStarting ensemble validation — {n_periods} periods × {period_days} days")
    print(f"Platform  : {base_url}")
    print(f"Symbols   : {', '.join(symbols)}")
    print(f"Strategies: {', '.join(ALL_STRATEGY_NAMES)}")

    validator = EnsembleValidator(
        base_url=base_url,
        api_key=api_key,
        symbols=symbols,
        period_days=period_days,
    )

    report = await validator.generate_report(n_periods=n_periods)

    # Print human-readable summary.
    _print_report_summary(report)

    # Save JSON report.
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"ensemble-final-validation-{ts}.json"
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nReport saved to: {output_path}")

    # Return non-zero exit code if the platform was unavailable.
    return 0 if report.platform_available else 1


def main() -> None:
    """CLI entry point.

    Usage::

        python -m agent.strategies.ensemble.validate \\
            --base-url http://localhost:8000 \\
            --periods 3 \\
            [--days 7] \\
            [--symbols BTCUSDT ETHUSDT] \\
            [--output-dir agent/reports]
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent.strategies.ensemble.validate",
        description=(
            "Ensemble validation harness — runs 4 strategy configurations "
            "(Ensemble, PPO-only, Evolved-only, Regime-only) plus a buy-and-hold "
            "baseline across N historical periods and produces a JSON report."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=_DEFAULT_BASE_URL,
        help="Platform REST API base URL.",
    )
    parser.add_argument(
        "--periods",
        type=int,
        default=3,
        metavar="N",
        help="Number of non-overlapping backtest periods to evaluate.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        metavar="N",
        help="Length of each backtest period in calendar days.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        metavar="SYMBOL",
        help="Trading pairs to include in each backtest.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent.parent / "reports",
        help="Output directory for the JSON report.",
    )

    args = parser.parse_args()

    import os  # noqa: PLC0415

    api_key = os.environ.get("ENSEMBLE_PLATFORM_API_KEY", "") or os.environ.get("PLATFORM_API_KEY", "")
    if not api_key:
        parser.error(
            "Platform API key not set. "
            "Set ENSEMBLE_PLATFORM_API_KEY or PLATFORM_API_KEY in agent/.env or as environment variable."
        )

    exit_code = asyncio.run(
        _cli_main(
            base_url=args.base_url,
            api_key=api_key,
            n_periods=args.periods,
            period_days=args.days,
            symbols=args.symbols,
            output_dir=args.output_dir,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
