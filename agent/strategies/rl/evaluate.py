"""Evaluation and benchmark comparison for trained PPO portfolio agents.

Loads one or more trained models from disk, runs them on the held-out test
split, and compares performance against three passive benchmarks:

  (a) Equal-weight rebalancing — splits the portfolio evenly across all assets
      and rebalances at every step.
  (b) Buy-and-hold BTC — allocates 100 % to BTCUSDT at the start.
  (c) Buy-and-hold ETH — allocates 100 % to ETHUSDT at the start.

If 3 or more models are found in the model directory the evaluator also
computes an ensemble (mean portfolio weights across all models at each step)
and reports its performance alongside the individual seeds.

Usage::

    # Evaluate all models in the default models/ directory
    python -m agent.strategies.rl.evaluate

    # Specify a custom models directory
    python -m agent.strategies.rl.evaluate --model-dir agent/strategies/rl/models/

    # Point at a specific model file
    python -m agent.strategies.rl.evaluate --model-dir agent/strategies/rl/models/ --seed 42

Outputs::

    agent/reports/ppo-evaluation-{timestamp}.json   — full EvaluationReport
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger(__name__)

# ── Result models ──────────────────────────────────────────────────────────────


class StrategyMetrics(BaseModel):
    """Performance metrics for a single strategy or benchmark.

    Args:
        name: Human-readable label (e.g. ``"ppo_seed42"`` or ``"buy_hold_btc"``).
        sharpe_ratio: Annualised Sharpe ratio over the test episode.  ``None``
            when fewer than 2 non-zero returns are available.
        roi_pct: Return on investment as a percentage.  Positive means profit.
        max_drawdown_pct: Maximum peak-to-trough drawdown (in %).  Closer to
            zero is better.
        win_rate: Fraction of closed steps where equity increased (0–1).
            ``None`` if fewer than 2 steps completed.
        total_trades: Number of individual orders placed during the episode.
        final_equity: Ending portfolio value in virtual USDT (stored as string
            to avoid float precision loss).
        n_steps: Number of environment steps completed.
        episode_reward: Sum of all step rewards returned by the environment.
        is_benchmark: ``True`` when this entry represents a passive benchmark
            rather than a trained model.
        error: Non-``None`` when evaluation raised an exception.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    sharpe_ratio: float | None = None
    roi_pct: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    total_trades: int = 0
    final_equity: str = "0"
    n_steps: int = 0
    episode_reward: float = 0.0
    is_benchmark: bool = False
    error: str | None = None


class EvaluationReport(BaseModel):
    """Complete evaluation report comparing PPO models against benchmarks.

    Args:
        timestamp: ISO-8601 UTC timestamp when the report was generated.
        test_start: ISO-8601 start of the held-out test window.
        test_end: ISO-8601 end of the held-out test window.
        symbols: Assets used in the test environment.
        starting_balance: Virtual USDT balance at episode start.
        strategies: Per-model and per-benchmark metrics.  PPO entries appear
            first, benchmarks last.
        ensemble: Ensemble metrics when 3 or more models were evaluated.  The
            ensemble action is the element-wise mean of all model weight
            predictions at each step.  ``None`` if fewer than 3 models.
        best_strategy: ``name`` of the strategy with the highest Sharpe ratio
            among non-benchmark strategies.  ``None`` if all failed.
        total_wall_time_sec: Wall-clock seconds for the full evaluation run.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: str
    test_start: str
    test_end: str
    symbols: list[str]
    starting_balance: str
    strategies: list[StrategyMetrics]
    ensemble: StrategyMetrics | None = None
    best_strategy: str | None = None
    total_wall_time_sec: float


# ── Metric helpers ─────────────────────────────────────────────────────────────


def _compute_metrics(
    equity_curve: list[float],
    trades_placed: int,
    total_reward: float,
    starting_balance: float,
    name: str,
    is_benchmark: bool = False,
    error: str | None = None,
) -> StrategyMetrics:
    """Compute Sharpe, ROI, drawdown, and win rate from an equity curve.

    Args:
        equity_curve: Portfolio equity at each step, starting with
            ``starting_balance``.
        trades_placed: Number of orders executed during the episode.
        total_reward: Sum of all step rewards.
        starting_balance: Initial portfolio value in USDT.
        name: Label to attach to the returned :class:`StrategyMetrics`.
        is_benchmark: Forward to :class:`StrategyMetrics`.
        error: Optional error message.

    Returns:
        :class:`StrategyMetrics` with all computed fields.
    """
    import numpy as np  # noqa: PLC0415

    n = len(equity_curve)

    if error is not None or n < 2:
        return StrategyMetrics(
            name=name,
            is_benchmark=is_benchmark,
            error=error,
            n_steps=max(0, n - 1),
        )

    # Step-level returns (not log returns — simpler and less sensitive to
    # near-zero equity values which can appear in liquidation scenarios).
    returns = np.diff(equity_curve) / np.maximum(equity_curve[:-1], 1e-8)

    # Sharpe: annualised assuming hourly candles (8760 steps per year).
    # Using 8760 as the standard annualisation factor for 1h crypto data.
    annualisation = 8760.0
    std = float(np.std(returns))
    mean_r = float(np.mean(returns))
    sharpe: float | None = None
    if std > 1e-10:
        sharpe = round((mean_r / std) * (annualisation ** 0.5), 4)

    # ROI
    roi = round((equity_curve[-1] - starting_balance) / max(starting_balance, 1e-8) * 100.0, 4)

    # Max drawdown — peak-to-trough over the equity curve.
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve[1:]:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / max(peak, 1e-8) * 100.0
        if dd > max_dd:
            max_dd = dd

    # Win rate: fraction of steps where equity increased.
    wins = int(np.sum(returns > 0))
    win_rate: float | None = round(wins / max(len(returns), 1), 4) if len(returns) > 0 else None

    return StrategyMetrics(
        name=name,
        sharpe_ratio=sharpe,
        roi_pct=roi,
        max_drawdown_pct=round(max_dd, 4),
        win_rate=win_rate,
        total_trades=trades_placed,
        final_equity=str(Decimal(str(round(equity_curve[-1], 8)))),
        n_steps=n - 1,
        episode_reward=round(total_reward, 6),
        is_benchmark=is_benchmark,
        error=None,
    )


# ── Environment runner ─────────────────────────────────────────────────────────


def _run_episode(
    make_env: Any,
    action_fn: Any,
    name: str,
    starting_balance: float,
    is_benchmark: bool = False,
) -> StrategyMetrics:
    """Run one deterministic episode using the given action function.

    Args:
        make_env: No-arg callable that produces an unwrapped environment.
            Must return an environment with ``reset() -> (obs, info)`` and
            ``step(action) -> (obs, reward, terminated, truncated, info)``.
        action_fn: ``(obs) -> action`` callable.  For PPO models this is
            ``model.predict(obs, deterministic=True)[0]``.  For benchmarks
            it is a lambda returning a fixed weight vector.
        name: Label for this strategy in the report.
        starting_balance: Starting equity for ROI computation.
        is_benchmark: Whether this is a passive benchmark.

    Returns:
        :class:`StrategyMetrics` from the completed episode.
    """
    try:
        env = make_env()
        obs, info = env.reset()

        equity_curve: list[float] = [float(starting_balance)]
        trades_placed = 0
        total_reward = 0.0
        terminated = truncated = False

        while not (terminated or truncated):
            action = action_fn(obs)
            obs, reward, terminated, truncated, info = env.step(action)
            total_reward += float(reward)

            # Track equity from the info dict if available.
            equity = info.get("equity") or info.get("portfolio", {}).get("total_equity")
            if equity is not None:
                equity_curve.append(float(equity))

            # Count trades from info.
            trades_placed += int(info.get("n_trades", 0))

        env.close()

        final_info: dict[str, Any] = info

        # Fall back to info-level equity if we never received step-level values.
        if len(equity_curve) == 1:
            eq = (
                final_info.get("equity")
                or final_info.get("final_equity")
                or starting_balance
            )
            equity_curve.append(float(eq))

        # Allow info to override individual metrics if provided directly.
        result = _compute_metrics(
            equity_curve=equity_curve,
            trades_placed=trades_placed or int(final_info.get("total_trades", 0)),
            total_reward=total_reward,
            starting_balance=starting_balance,
            name=name,
            is_benchmark=is_benchmark,
        )

        # Override sharpe/roi from env if better sourced there.
        env_sharpe: float | None = final_info.get("sharpe_ratio")
        env_roi: float | None = final_info.get("roi_pct")

        if env_sharpe is not None or env_roi is not None:
            result = result.model_copy(
                update={
                    k: v
                    for k, v in {
                        "sharpe_ratio": env_sharpe if env_sharpe is not None else result.sharpe_ratio,
                        "roi_pct": env_roi if env_roi is not None else result.roi_pct,
                    }.items()
                    if v is not None
                }
            )

        log.info(
            "agent.strategy.rl.evaluate.episode.complete",
            name=name,
            sharpe=result.sharpe_ratio,
            roi_pct=result.roi_pct,
            max_dd=result.max_drawdown_pct,
            win_rate=result.win_rate,
            trades=result.total_trades,
        )
        return result

    except Exception as exc:  # noqa: BLE001
        log.exception("agent.strategy.rl.evaluate.episode.failed", name=name, error=str(exc))
        return StrategyMetrics(name=name, is_benchmark=is_benchmark, error=str(exc))


# ── Ensemble runner ────────────────────────────────────────────────────────────


def _run_ensemble_episode(
    make_env: Any,
    models: list[Any],
    name: str,
    starting_balance: float,
) -> StrategyMetrics:
    """Run one episode using the mean of all model weight predictions.

    At each step all models predict independently; the element-wise mean of
    their weight vectors is passed to the environment as the action.  This
    constitutes a simple averaging ensemble — it does not require any model
    to be the "master", and it is fast because all models run in the same
    process.

    Args:
        make_env: No-arg env factory.
        models: List of loaded SB3 ``PPO`` models.
        name: Label for the ensemble in the report.
        starting_balance: Starting equity.

    Returns:
        :class:`StrategyMetrics` for the ensemble.
    """
    import numpy as np  # noqa: PLC0415

    def _ensemble_action(obs: Any) -> Any:
        """Return element-wise mean of all model predictions."""
        preds = [model.predict(obs, deterministic=True)[0] for model in models]
        return np.mean(preds, axis=0).astype(np.float32)

    return _run_episode(
        make_env=make_env,
        action_fn=_ensemble_action,
        name=name,
        starting_balance=starting_balance,
        is_benchmark=False,
    )


# ── Main evaluator ─────────────────────────────────────────────────────────────


class ModelEvaluator:
    """Loads and evaluates PPO models against benchmarks on the test split.

    Args:
        config: :class:`~agent.strategies.rl.config.RLConfig` instance.
            ``test_start``, ``test_end``, ``env_symbols``, and
            ``starting_balance`` are used to build the test environment.
    """

    def __init__(self, config: Any) -> None:
        self._config = config

    def load_models(self, model_dir: Path) -> dict[str, Any]:
        """Scan model_dir for ``ppo_seed*.zip`` files and load them.

        Args:
            model_dir: Directory to scan.

        Returns:
            Dict mapping seed label (e.g. ``"ppo_seed42"``) to the loaded SB3
            ``PPO`` model.  Models that fail to load are skipped (logged).
        """
        try:
            from stable_baselines3 import PPO  # noqa: PLC0415
        except ImportError:
            log.error("agent.strategy.rl.evaluate.sb3_not_installed")
            return {}

        from agent.strategies.checksum import SecurityError, verify_checksum  # noqa: PLC0415

        models: dict[str, Any] = {}
        for path in sorted(model_dir.glob("ppo_seed*.zip")):
            label = path.stem  # e.g. "ppo_seed42"
            try:
                # Verify integrity before deserializing the pickle-based .zip.
                try:
                    verify_checksum(path)
                except SecurityError as exc_sec:
                    log.error(
                        "agent.strategy.rl.evaluate.model.checksum_mismatch",
                        label=label,
                        path=str(path),
                        error=str(exc_sec),
                    )
                    continue  # skip tampered model; do not load it
                except Exception as exc_cs:  # noqa: BLE001
                    log.warning(
                        "agent.strategy.rl.evaluate.model.checksum_check_failed",
                        label=label,
                        path=str(path),
                        error=str(exc_cs),
                    )
                models[label] = PPO.load(str(path))
                log.info("agent.strategy.rl.evaluate.model.loaded", label=label, path=str(path))
            except Exception as exc:  # noqa: BLE001
                log.warning("agent.strategy.rl.evaluate.model.load_failed", label=label, error=str(exc))
        return models

    def _make_test_env_factory(self) -> Any:
        """Return a no-arg factory that produces a fresh test-split environment.

        Uses the same wrapper stack as training:
        ``FeatureEngineeringWrapper(periods=[5, 10, 20])`` then
        ``NormalizationWrapper``.

        Returns:
            Callable with no arguments returning a wrapped Gymnasium env.
        """
        from agent.strategies.rl.train import _env_factory  # noqa: PLC0415

        return _env_factory(self._config, self._config.test_start, self._config.test_end)

    # ── Benchmark factories ────────────────────────────────────────────────────

    def _equal_weight_action(self) -> Any:
        """Return a fixed equal-weight action for the benchmark.

        Returns:
            Lambda that ignores the observation and returns an equal-weight
            ``float32`` array of shape ``(n_assets,)``.
        """
        import numpy as np  # noqa: PLC0415

        n = len(self._config.env_symbols)
        weight = 1.0 / n
        weights = np.full(n, weight, dtype=np.float32)

        def _action(_obs: Any) -> Any:
            return weights.copy()

        return _action

    def _btc_hold_action(self) -> Any:
        """Return a fixed action that allocates 100% to BTC.

        If BTC is not in the symbol list, allocates to index 0 instead.

        Returns:
            Lambda returning a ``float32`` array with 1.0 at the BTC position.
        """
        import numpy as np  # noqa: PLC0415

        n = len(self._config.env_symbols)
        weights = np.zeros(n, dtype=np.float32)
        symbols_upper = [s.upper() for s in self._config.env_symbols]
        btc_idx = next(
            (i for i, s in enumerate(symbols_upper) if "BTC" in s),
            0,  # fallback to first asset
        )
        weights[btc_idx] = 1.0

        def _action(_obs: Any) -> Any:
            return weights.copy()

        return _action

    def _eth_hold_action(self) -> Any:
        """Return a fixed action that allocates 100% to ETH.

        If ETH is not in the symbol list, allocates to index 1 (or 0 if
        there is only one asset) instead.

        Returns:
            Lambda returning a ``float32`` array with 1.0 at the ETH position.
        """
        import numpy as np  # noqa: PLC0415

        n = len(self._config.env_symbols)
        weights = np.zeros(n, dtype=np.float32)
        symbols_upper = [s.upper() for s in self._config.env_symbols]
        eth_idx = next(
            (i for i, s in enumerate(symbols_upper) if "ETH" in s),
            min(1, n - 1),  # fallback to second asset or last
        )
        weights[eth_idx] = 1.0

        def _action(_obs: Any) -> Any:
            return weights.copy()

        return _action

    # ── Evaluation entry point ─────────────────────────────────────────────────

    def evaluate(
        self,
        model_dir: Path,
        seed_filter: int | None = None,
    ) -> EvaluationReport:
        """Run the full evaluation pipeline and return an EvaluationReport.

        Steps:
          1. Scan ``model_dir`` for ``ppo_seed*.zip`` files.
          2. Optionally filter to a single seed.
          3. Evaluate each model on the test split.
          4. Evaluate 3 benchmarks: equal-weight, BTC hold, ETH hold.
          5. If >= 3 models loaded, compute ensemble metrics.
          6. Assemble and return :class:`EvaluationReport`.

        Args:
            model_dir: Directory containing trained ``.zip`` files.
            seed_filter: When not ``None``, only the model whose filename
                contains this seed number is evaluated.

        Returns:
            :class:`EvaluationReport` (JSON-serialisable Pydantic model).
        """
        t_start = time.monotonic()
        make_env = self._make_test_env_factory()

        # ── Load models ────────────────────────────────────────────────────────
        all_models = self.load_models(model_dir)
        if seed_filter is not None:
            key = f"ppo_seed{seed_filter}"
            if key in all_models:
                all_models = {key: all_models[key]}
            else:
                log.warning("agent.strategy.rl.evaluate.seed_not_found", seed=seed_filter, available=list(all_models))
                all_models = {}

        log.info("agent.strategy.rl.evaluate.start", n_models=len(all_models), symbols=self._config.env_symbols)

        # ── Evaluate individual PPO models ─────────────────────────────────────
        ppo_results: list[StrategyMetrics] = []
        for label, model in all_models.items():
            log.info("agent.strategy.rl.evaluate.model", label=label)
            result = _run_episode(
                make_env=make_env,
                action_fn=lambda obs, m=model: m.predict(obs, deterministic=True)[0],
                name=label,
                starting_balance=float(self._config.starting_balance),
            )
            ppo_results.append(result)

        # ── Benchmarks ────────────────────────────────────────────────────────
        benchmark_defs = [
            ("equal_weight_rebalancing", self._equal_weight_action()),
            ("buy_hold_btc", self._btc_hold_action()),
            ("buy_hold_eth", self._eth_hold_action()),
        ]
        benchmark_results: list[StrategyMetrics] = []
        for bname, baction in benchmark_defs:
            log.info("agent.strategy.rl.evaluate.benchmark", name=bname)
            result = _run_episode(
                make_env=make_env,
                action_fn=baction,
                name=bname,
                starting_balance=float(self._config.starting_balance),
                is_benchmark=True,
            )
            benchmark_results.append(result)

        # ── Ensemble (>= 3 models) ─────────────────────────────────────────────
        ensemble: StrategyMetrics | None = None
        if len(all_models) >= 3:
            log.info("agent.strategy.rl.evaluate.ensemble", n_models=len(all_models))
            ensemble = _run_ensemble_episode(
                make_env=make_env,
                models=list(all_models.values()),
                name="ensemble_mean",
                starting_balance=float(self._config.starting_balance),
            )

        # ── Best non-benchmark strategy ────────────────────────────────────────
        candidates = [r for r in ppo_results if r.error is None and r.sharpe_ratio is not None]
        if ensemble and ensemble.error is None and ensemble.sharpe_ratio is not None:
            candidates.append(ensemble)
        best_name: str | None = None
        if candidates:
            best_name = max(candidates, key=lambda r: r.sharpe_ratio or float("-inf")).name

        report = EvaluationReport(
            timestamp=datetime.now(UTC).isoformat(),
            test_start=self._config.test_start,
            test_end=self._config.test_end,
            symbols=list(self._config.env_symbols),
            starting_balance=str(Decimal(str(self._config.starting_balance))),
            strategies=ppo_results + benchmark_results,
            ensemble=ensemble,
            best_strategy=best_name,
            total_wall_time_sec=round(time.monotonic() - t_start, 2),
        )

        log.info(
            "agent.strategy.rl.evaluate.done",
            n_ppo=len(ppo_results),
            n_benchmarks=len(benchmark_results),
            ensemble=ensemble is not None,
            best_strategy=best_name,
            wall_time_sec=report.total_wall_time_sec,
        )
        return report


# ── Persistence ────────────────────────────────────────────────────────────────


def _save_report(report: EvaluationReport, output_dir: Path) -> Path:
    """Persist the evaluation report to disk as a JSON file.

    Args:
        report: Completed :class:`EvaluationReport`.
        output_dir: Directory where the file will be written.  Created if it
            does not exist.

    Returns:
        Absolute path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"ppo-evaluation-{ts}.json"
    path = output_dir / filename
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    log.info("agent.strategy.rl.evaluate.report_saved", path=str(path))
    return path


# ── Logging setup ──────────────────────────────────────────────────────────────


def _configure_logging(verbose: bool) -> None:
    """Configure structlog for the evaluate CLI.

    Args:
        verbose: When ``True``, enable DEBUG-level output.
    """
    from agent.logging import configure_agent_logging  # noqa: PLC0415

    configure_agent_logging(log_level="DEBUG" if verbose else "INFO")


# ── CLI ────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser`.
    """
    p = argparse.ArgumentParser(
        prog="python -m agent.strategies.rl.evaluate",
        description=(
            "Evaluate trained PPO models on the held-out test split and compare "
            "against equal-weight rebalancing, buy-and-hold BTC, and buy-and-hold ETH."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Directory containing ppo_seed*.zip model files.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="Evaluate only the model for this seed (e.g. 42).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Directory to write the evaluation report JSON.",
    )
    p.add_argument(
        "--base-url",
        type=str,
        default=None,
        metavar="URL",
        help="Platform REST API base URL.",
    )
    p.add_argument(
        "--test-start",
        type=str,
        default=None,
        metavar="ISO",
        help="Override test window start (ISO-8601, e.g. 2024-12-01T00:00:00Z).",
    )
    p.add_argument(
        "--test-end",
        type=str,
        default=None,
        metavar="ISO",
        help="Override test window end (ISO-8601).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level log output.",
    )
    return p


def main() -> None:
    """CLI entry point.

    Loads :class:`RLConfig`, applies CLI overrides, runs :class:`ModelEvaluator`,
    saves the report, and prints a summary to stdout.
    """
    from agent.strategies.rl.config import RLConfig  # noqa: PLC0415

    p = _build_parser()
    args = p.parse_args()
    _configure_logging(args.verbose)

    try:
        config = RLConfig()
    except Exception as exc:
        log.error("agent.strategy.rl.evaluate.config_load_failed", error=str(exc))
        sys.exit(1)

    # Apply CLI overrides.
    overrides: dict[str, Any] = {}
    if args.base_url is not None:
        overrides["platform_base_url"] = args.base_url
    if args.test_start is not None:
        overrides["test_start"] = args.test_start
    if args.test_end is not None:
        overrides["test_end"] = args.test_end
    if overrides:
        config = config.model_copy(update=overrides)

    if not config.platform_api_key:
        log.error(
            "agent.strategy.rl.evaluate.config_missing_api_key",
            hint="Set RL_PLATFORM_API_KEY in agent/.env or as environment variable",
        )
        sys.exit(1)

    # Resolve directories.
    model_dir: Path = args.model_dir if args.model_dir is not None else config.models_dir
    output_dir: Path = (
        args.output_dir
        if args.output_dir is not None
        else Path(__file__).parent.parent.parent / "reports"
    )

    if not model_dir.exists():
        log.error("agent.strategy.rl.evaluate.model_dir_not_found", path=str(model_dir))
        sys.exit(1)

    evaluator = ModelEvaluator(config)
    report = evaluator.evaluate(model_dir=model_dir, seed_filter=args.seed)
    saved_path = _save_report(report, output_dir)

    # Log a summary.
    all_entries = list(report.strategies)
    if report.ensemble is not None:
        all_entries.insert(len([s for s in all_entries if not s.is_benchmark]), report.ensemble)

    strategy_rows = []
    for s in all_entries:
        kind = "benchmark" if s.is_benchmark else ("ensemble" if s.name == "ensemble_mean" else "strategy")
        strategy_rows.append({
            "name": s.name,
            "kind": kind,
            "sharpe": round(s.sharpe_ratio, 3) if s.sharpe_ratio is not None else None,
            "roi_pct": round(s.roi_pct, 2) if s.roi_pct is not None else None,
            "max_drawdown_pct": round(s.max_drawdown_pct, 2) if s.max_drawdown_pct is not None else None,
            "win_rate": round(s.win_rate, 3) if s.win_rate is not None else None,
            "total_trades": s.total_trades,
        })

    log.info(
        "agent.strategy.rl.evaluate.report_summary",
        test_start=str(report.test_start),
        test_end=str(report.test_end),
        assets=report.symbols,
        best_model=report.best_strategy or "N/A",
        report_file=str(saved_path),
        strategies=strategy_rows,
        wall_time_sec=round(report.total_wall_time_sec, 1),
    )


if __name__ == "__main__":
    main()
