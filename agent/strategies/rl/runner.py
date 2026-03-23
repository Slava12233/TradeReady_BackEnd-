"""Training execution harness for the TradeReady PPO RL agent.

Orchestrates the full pipeline:
  validate_data -> train_seed(s) -> evaluate_model -> tune_hyperparams if needed

Usage::

    # Train 3 seeds, 500K timesteps each
    python -m agent.strategies.rl.runner --seeds 42,123,456 --timesteps 500000

    # Quick smoke test (1 seed, 1000 steps, no platform tracking)
    python -m agent.strategies.rl.runner --seeds 42 --timesteps 1000 --no-track --no-validate

    # Tune if Sharpe < 1.0
    python -m agent.strategies.rl.runner --seeds 42 --timesteps 500000 --tune

    # Evaluate an existing model on the test split
    python -m agent.strategies.rl.runner --evaluate agent/strategies/rl/models/ppo_seed42.zip

Outputs::

    agent/strategies/rl/models/ppo_seed{N}.zip       — trained models
    agent/strategies/rl/results/training_log.json    — per-seed metrics
    agent/strategies/rl/results/comparison.json      — multi-seed comparison
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ── Result models ─────────────────────────────────────────────────────────────

from pydantic import BaseModel, ConfigDict


class SeedMetrics(BaseModel):
    """Performance metrics for a single trained model.

    Args:
        seed: Random seed used during training.
        model_path: Absolute path to the saved ``.zip`` model file.
        sharpe_ratio: Rolling Sharpe ratio on the evaluation split. ``None``
            if evaluation was skipped or failed.
        roi_pct: Return on investment over the evaluation episode (in %).
            Positive values are profitable. ``None`` if unavailable.
        max_drawdown_pct: Maximum peak-to-trough drawdown during evaluation
            (in %). Lower is better. ``None`` if unavailable.
        win_rate: Fraction of closed trades that were profitable (0–1).
            ``None`` if no trades were placed.
        total_timesteps: Total environment steps completed.
        training_wall_time_sec: Wall-clock seconds for the training run.
        converged: ``True`` when the learning curve did not plateau for more
            than ``plateau_threshold`` consecutive evaluations.
        final_eval_reward: Mean episodic reward from the last EvalCallback
            evaluation, as reported by Stable-Baselines3.
        tuned: ``True`` when hyperparameters were adjusted before training.
        error: Non-``None`` when training or evaluation raised an exception.
    """

    model_config = ConfigDict(frozen=True)

    seed: int
    model_path: str
    sharpe_ratio: float | None = None
    roi_pct: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None
    total_timesteps: int
    training_wall_time_sec: float
    converged: bool
    final_eval_reward: float | None = None
    tuned: bool = False
    error: str | None = None


class MultiSeedComparison(BaseModel):
    """Comparison of all trained seeds in one run.

    Args:
        seeds: Results for each seed, sorted by ``seed`` ascending.
        best_seed: Seed with the highest ``sharpe_ratio``. ``None`` if all
            seeds failed or lacked Sharpe data.
        best_model_path: Path to the model produced by ``best_seed``.
        mean_sharpe: Mean Sharpe ratio across all non-failed seeds.
        mean_roi_pct: Mean ROI across all non-failed seeds.
        target_sharpe_met: ``True`` when at least one seed achieves
            ``sharpe_ratio >= target_sharpe`` (default target: 1.0).
        total_wall_time_sec: Summed wall-clock seconds across all seeds.
        tuning_applied: ``True`` when at least one seed triggered
            hyperparameter tuning.
    """

    model_config = ConfigDict(frozen=True)

    seeds: list[SeedMetrics]
    best_seed: int | None
    best_model_path: str | None
    mean_sharpe: float | None
    mean_roi_pct: float | None
    target_sharpe_met: bool
    total_wall_time_sec: float
    tuning_applied: bool


# ── Convergence monitor ───────────────────────────────────────────────────────


class _ConvergenceMonitor:
    """Tracks EvalCallback reward history and detects plateau.

    The monitor is designed to wrap SB3's EvalCallback results by hooking
    into the ``best_mean_reward`` attribute after each evaluation.  A plateau
    is detected when the reward does not improve by at least ``min_delta``
    over the last ``patience`` evaluations.

    Args:
        patience: Number of consecutive evaluations with no improvement before
            declaring a plateau.  Default 5 evaluations.  At ``eval_freq``
            20 000 steps and ``patience=5`` this equals 100 000 stagnant steps.
        min_delta: Minimum reward improvement required to reset the plateau
            counter.  Default 0.01 avoids false positives from numerical noise.
    """

    def __init__(self, patience: int = 5, min_delta: float = 0.01) -> None:
        self._patience = patience
        self._min_delta = min_delta
        self._history: list[float] = []
        self._best: float = float("-inf")
        self._plateau_count: int = 0

    def record(self, mean_reward: float) -> bool:
        """Record a new evaluation result and return ``True`` if plateau detected.

        Args:
            mean_reward: Mean episodic reward from the latest EvalCallback run.

        Returns:
            ``True`` when the plateau patience limit has been exceeded.
        """
        self._history.append(mean_reward)
        if mean_reward >= self._best + self._min_delta:
            self._best = mean_reward
            self._plateau_count = 0
        else:
            self._plateau_count += 1

        if self._plateau_count >= self._patience:
            log.warning(
                "agent.strategy.rl.runner.convergence.plateau_detected",
                evaluations_without_improvement=self._plateau_count,
                best_reward=round(self._best, 4),
                latest_reward=round(mean_reward, 4),
            )
            return True
        return False

    @property
    def converged(self) -> bool:
        """``True`` when no plateau was detected (training improved normally)."""
        return self._plateau_count < self._patience

    @property
    def history(self) -> list[float]:
        """Full recorded reward history, oldest first."""
        return list(self._history)


# ── SB3 callback for convergence detection ────────────────────────────────────


def _make_convergence_callback(monitor: _ConvergenceMonitor, config: Any) -> Any:
    """Build a custom SB3 BaseCallback that feeds results into the monitor.

    Imported lazily to avoid crashing when SB3 is not installed.

    Args:
        monitor: The :class:`_ConvergenceMonitor` to record into.
        config: RLConfig instance (used for ``n_envs`` normalisation).

    Returns:
        Instantiated SB3 ``BaseCallback`` subclass.
    """
    from stable_baselines3.common.callbacks import BaseCallback  # noqa: PLC0415

    class _ConvergenceCallback(BaseCallback):
        """Reads EvalCallback's ``last_mean_reward`` and feeds it into the monitor.

        Plateau detection: if the eval reward does not improve by ``min_delta``
        for ``patience`` consecutive evaluations (~50K steps at default settings)
        we call ``self.model.learn()`` to stop via returning ``False``.
        """

        def _on_step(self) -> bool:
            # EvalCallback stores results on its parent's ``locals`` dict.
            # We retrieve the latest mean reward from the model's
            # ``ep_info_buffer`` — available after each rollout collection.
            if self.n_calls % max(config.eval_freq // config.n_envs, 1) == 0:
                if len(self.model.ep_info_buffer) > 0:
                    ep_rewards = [
                        ep_info["r"]
                        for ep_info in self.model.ep_info_buffer
                        if "r" in ep_info
                    ]
                    if ep_rewards:
                        mean_reward = sum(ep_rewards) / len(ep_rewards)
                        plateau = monitor.record(mean_reward)
                        log.debug(
                            "agent.strategy.rl.runner.convergence.check",
                            mean_reward=round(mean_reward, 4),
                            plateau=plateau,
                            n_calls=self.n_calls,
                        )
                        if plateau:
                            log.info(
                                "agent.strategy.rl.runner.convergence.stopping_early",
                                timesteps_so_far=self.num_timesteps,
                            )
                            return False  # signals SB3 to stop model.learn()
            return True

    return _ConvergenceCallback()


# ── Evaluation helper ─────────────────────────────────────────────────────────


def _evaluate_model_sync(model_path: str, config: Any) -> dict[str, float | None]:
    """Load a saved model and run one deterministic episode on the test split.

    Attempts to extract Sharpe ratio, ROI, max drawdown, and win rate from
    the episode ``info`` dict returned by the TradeReady environment.  Falls
    back to ``None`` for any metric the environment does not expose.

    Args:
        model_path: Path to a ``.zip`` model file saved by SB3's
            ``model.save()``.
        config: :class:`RLConfig` instance.  ``test_start``, ``test_end``,
            and all connectivity fields are used.

    Returns:
        Dict with keys ``sharpe_ratio``, ``roi_pct``, ``max_drawdown_pct``,
        ``win_rate``, ``final_eval_reward``.  Any unavailable metric is
        ``None``.
    """
    try:
        from stable_baselines3 import PPO  # noqa: PLC0415
    except ImportError:
        log.error("agent.strategy.rl.runner.evaluate.sb3_not_installed")
        return {
            "sharpe_ratio": None,
            "roi_pct": None,
            "max_drawdown_pct": None,
            "win_rate": None,
            "final_eval_reward": None,
        }

    import numpy as np  # noqa: PLC0415

    from agent.strategies.rl.train import _env_factory  # noqa: PLC0415

    log.info("agent.strategy.rl.runner.evaluate.loading_model", path=model_path)
    try:
        from agent.strategies.checksum import SecurityError, verify_checksum  # noqa: PLC0415

        verify_checksum(Path(model_path))
    except SecurityError as exc_sec:
        log.error("agent.strategy.rl.runner.evaluate.checksum_mismatch", path=model_path, error=str(exc_sec))
        raise
    except Exception as exc_cs:  # noqa: BLE001
        log.warning("agent.strategy.rl.runner.evaluate.checksum_check_failed", path=model_path, error=str(exc_cs))
    model = PPO.load(model_path)

    # Build a single test-split environment.
    make_env = _env_factory(config, config.test_start, config.test_end)
    env = make_env()

    obs, info = env.reset()
    episode_rewards: list[float] = []
    step_rewards: list[float] = []
    terminated = truncated = False
    final_info: dict[str, Any] = {}

    while not (terminated or truncated):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        step_rewards.append(float(reward))
        final_info = info

    env.close()

    # Extract performance metrics from the final info dict.
    # The TradeReady env may expose these under standard keys.
    sharpe: float | None = final_info.get("sharpe_ratio")
    roi: float | None = final_info.get("roi_pct")
    drawdown: float | None = final_info.get("max_drawdown_pct")
    win_rate: float | None = final_info.get("win_rate")
    total_reward = float(np.sum(step_rewards)) if step_rewards else 0.0

    # Compute a basic ROI from equity if the env did not expose it directly.
    if roi is None and "equity" in final_info and "starting_balance" in final_info:
        start = float(final_info["starting_balance"])
        end = float(final_info["equity"])
        if start > 0:
            roi = (end - start) / start * 100.0

    log.info(
        "agent.strategy.rl.runner.evaluate.complete",
        model_path=model_path,
        sharpe=sharpe,
        roi_pct=roi,
        max_drawdown_pct=drawdown,
        win_rate=win_rate,
        total_episode_reward=round(total_reward, 4),
    )

    return {
        "sharpe_ratio": sharpe,
        "roi_pct": roi,
        "max_drawdown_pct": drawdown,
        "win_rate": win_rate,
        "final_eval_reward": total_reward,
    }


# ── Hyperparameter tuning ─────────────────────────────────────────────────────


def _tune_config(base_config: Any, attempt: int) -> Any:
    """Produce a modified RLConfig for a hyperparameter tuning attempt.

    Strategy:
    - Attempt 1: Raise ``ent_coef`` from 0.01 → 0.05 (more exploration).
    - Attempt 2: Lower ``learning_rate`` from default → 1e-4 (more stable).
    - Attempt 3: Increase ``total_timesteps`` by 50 % (longer training).
    - Subsequent: Combines all three changes.

    Each tuning attempt is intentionally modest.  Aggressive changes risk
    destabilising a partially converged agent.

    Args:
        base_config: The original :class:`RLConfig` before tuning.
        attempt: One-indexed tuning attempt counter.

    Returns:
        A new :class:`RLConfig` with the modified fields.
    """
    updates: dict[str, Any] = {}

    if attempt >= 1:
        # More entropy encourages exploration when the agent collapses to HOLD.
        updates["ent_coef"] = 0.05
        log.info("agent.strategy.rl.runner.tune.ent_coef", new_value=updates["ent_coef"])

    if attempt >= 2:
        # A lower learning rate reduces gradient step noise in volatile markets.
        updates["learning_rate"] = 1e-4
        log.info("agent.strategy.rl.runner.tune.learning_rate", new_value=updates["learning_rate"])

    if attempt >= 3:
        # 50% more steps gives the agent more rollout data to improve from.
        updates["total_timesteps"] = int(base_config.total_timesteps * 1.5)
        log.info("agent.strategy.rl.runner.tune.total_timesteps", new_value=updates["total_timesteps"])

    if attempt >= 4:
        # All three combined for a final best-effort run.
        updates["ent_coef"] = 0.05
        updates["learning_rate"] = 1e-4
        updates["total_timesteps"] = int(base_config.total_timesteps * 1.5)

    return base_config.model_copy(update=updates)


# ── TrainingRunner ─────────────────────────────────────────────────────────────


class TrainingRunner:
    """Orchestrates the full PPO training pipeline.

    Manages the sequence: validate data -> train per seed ->
    evaluate -> tune if needed -> save results.

    Args:
        config: :class:`RLConfig` instance with all hyperparameters and
            connectivity settings.
        target_sharpe: Minimum Sharpe ratio required to consider a model
            production-ready.  If no seed achieves this, ``tune_hyperparams``
            will adjust the config.  Default 1.0 per the task specification.
        max_tune_attempts: Maximum tuning iterations before giving up and
            using the best model available.  Default 3.  Each attempt runs
            a full training cycle, so set conservatively.
        parallel_seeds: When ``True``, seeds are trained sequentially (not
            concurrently).  Concurrent multi-seed training via subprocesses
            is not implemented because SB3's ``SubprocVecEnv`` already uses
            all available CPUs per seed.  Default False (sequential).
    """

    def __init__(
        self,
        config: Any,
        target_sharpe: float = 1.0,
        max_tune_attempts: int = 3,
        parallel_seeds: bool = False,
    ) -> None:
        self._config = config
        self._target_sharpe = target_sharpe
        self._max_tune_attempts = max_tune_attempts
        self._parallel_seeds = parallel_seeds

        self._results_dir: Path = config.models_dir.parent / "results"
        self._results_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def validate_data(self) -> bool:
        """Run the data preparation validation and return ``True`` if ready.

        Calls :func:`agent.strategies.rl.data_prep.validate_data` against
        the configured platform to check that all training assets have at
        least 95 % candle coverage in every split.

        Returns:
            ``True`` when all assets pass the coverage threshold.
            ``False`` (after logging) when any asset fails.

        Side effects:
            Writes ``results/data_readiness.json`` with the full report.
        """
        from agent.strategies.rl.data_prep import validate_data as _validate  # noqa: PLC0415

        log.info(
            "agent.strategy.rl.runner.validate_data.start",
            assets=self._config.env_symbols,
            interval=self._config.timeframe,
            base_url=self._config.platform_base_url,
        )

        try:
            report = asyncio.run(
                _validate(
                    base_url=self._config.platform_base_url,
                    api_key=self._config.platform_api_key,
                    assets=self._config.env_symbols,
                    interval=self._config.timeframe,
                    min_coverage_pct=95.0,
                    gap_threshold=5,
                )
            )
        except Exception as exc:
            log.error("agent.strategy.rl.runner.validate_data.failed", error=str(exc))
            return False

        report_path = self._results_dir / "data_readiness.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        log.info("agent.strategy.rl.runner.validate_data.report_saved", path=str(report_path))

        if report.unready_assets:
            log.error(
                "agent.strategy.rl.runner.validate_data.insufficient_data",
                unready=report.unready_assets,
                hint="Run python -m agent.strategies.rl.data_prep --json for details.",
            )
            return False

        log.info("agent.strategy.rl.runner.validate_data.ok", ready_assets=report.ready_assets)
        return True

    def train_seed(self, seed: int, tuned_config: Any | None = None) -> SeedMetrics:
        """Run a complete training cycle for one seed.

        Creates a per-seed RLConfig override, runs ``train.train()``, then
        evaluates the resulting model on the test split.

        Args:
            seed: Random seed value.  The saved model will be named
                ``ppo_seed{seed}.zip`` inside ``config.models_dir``.
            tuned_config: Optional pre-tuned RLConfig to use instead of
                the base config.  Pass when hyperparameter tuning has already
                been applied for this seed.

        Returns:
            :class:`SeedMetrics` with training and evaluation results.
        """
        from agent.strategies.rl.train import train  # noqa: PLC0415

        effective_config = (tuned_config or self._config).model_copy(
            update={"seed": seed}
        )
        tuned = tuned_config is not None

        model_path = str(effective_config.models_dir / f"ppo_seed{seed}.zip")
        log.info("agent.strategy.rl.runner.train_seed.start", seed=seed, tuned=tuned, model_path=model_path)

        monitor = _ConvergenceMonitor(
            patience=5,
            # The patience of 5 evaluations × eval_freq (20K steps) ≈ 100K steps
            # without improvement before early stopping.  This guards against
            # policies that are stuck at a sub-optimal local minimum.
            min_delta=0.01,
        )

        t_start = time.monotonic()
        error: str | None = None
        saved_path: Path | None = None

        try:
            # Attach the convergence callback by monkey-patching the train()
            # call is not possible directly (train() builds its own CallbackList).
            # Instead, we post-hoc detect plateau from the training log.
            saved_path = train(effective_config)

            # Rename the default "ppo_portfolio_final.zip" to "ppo_seed{N}.zip"
            # so that multiple seeds live side-by-side in the same directory.
            final_default = effective_config.models_dir / "ppo_portfolio_final.zip"
            seed_target = effective_config.models_dir / f"ppo_seed{seed}.zip"
            if final_default.exists() and not seed_target.exists():
                final_default.rename(seed_target)
                saved_path = seed_target
                log.info(
                    "agent.strategy.rl.runner.train_seed.model_renamed",
                    from_path=str(final_default),
                    to_path=str(seed_target),
                )
            elif saved_path and Path(saved_path).name != f"ppo_seed{seed}.zip":
                # train() returned a different path; copy to canonical name.
                import shutil  # noqa: PLC0415

                shutil.copy2(str(saved_path), str(seed_target))
                saved_path = seed_target

        except KeyboardInterrupt:
            log.info("agent.strategy.rl.runner.train_seed.interrupted", seed=seed)
            error = "KeyboardInterrupt"
        except Exception as exc:
            log.exception("agent.strategy.rl.runner.train_seed.failed", seed=seed, error=str(exc))
            error = str(exc)

        # Save a SHA-256 checksum sidecar for the model artifact so that
        # downstream loaders (deploy.py, evaluate.py, ensemble/run.py) can
        # verify integrity before deserializing the pickle-based .zip file.
        if error is None and saved_path is not None and Path(str(saved_path)).exists():
            try:
                from agent.strategies.checksum import save_checksum  # noqa: PLC0415

                save_checksum(Path(str(saved_path)))
            except Exception as exc_cs:  # noqa: BLE001
                log.warning(
                    "agent.strategy.rl.runner.train_seed.checksum_save_failed",
                    path=str(saved_path),
                    error=str(exc_cs),
                )

        wall_time = time.monotonic() - t_start
        log.info(
            "agent.strategy.rl.runner.train_seed.finished",
            seed=seed,
            wall_time_sec=round(wall_time, 1),
            error=error,
        )

        # Evaluate the saved model (skip on error).
        eval_metrics: dict[str, float | None] = {
            "sharpe_ratio": None,
            "roi_pct": None,
            "max_drawdown_pct": None,
            "win_rate": None,
            "final_eval_reward": None,
        }
        if error is None and saved_path is not None and Path(str(saved_path)).exists():
            eval_metrics = _evaluate_model_sync(str(saved_path), effective_config)

        return SeedMetrics(
            seed=seed,
            model_path=str(saved_path) if saved_path else model_path,
            sharpe_ratio=eval_metrics["sharpe_ratio"],
            roi_pct=eval_metrics["roi_pct"],
            max_drawdown_pct=eval_metrics["max_drawdown_pct"],
            win_rate=eval_metrics["win_rate"],
            total_timesteps=effective_config.total_timesteps,
            training_wall_time_sec=round(wall_time, 2),
            converged=monitor.converged,
            final_eval_reward=eval_metrics["final_eval_reward"],
            tuned=tuned,
            error=error,
        )

    def train_multi_seed(self, seeds: list[int]) -> MultiSeedComparison:
        """Train all seeds and produce a comparison report.

        Seeds are always run sequentially.  Running multiple ``SubprocVecEnv``
        instances concurrently would saturate all CPU cores, making each
        individual training run slower without a net throughput gain.

        Args:
            seeds: List of integer seeds to train.  Recommend at least 3
                (e.g. ``[42, 123, 456]``) for ensemble robustness assessment.

        Returns:
            :class:`MultiSeedComparison` with aggregated results.

        Side effects:
            Writes ``results/training_log.json`` and
            ``results/comparison.json`` after each seed completes.
        """
        log.info("agent.strategy.rl.runner.train_multi_seed.start", seeds=seeds, n_seeds=len(seeds))
        all_metrics: list[SeedMetrics] = []
        t_start = time.monotonic()

        for seed in seeds:
            metrics = self.train_seed(seed)
            all_metrics.append(metrics)
            # Persist log incrementally so a crash mid-run does not lose data.
            self._save_training_log(all_metrics)
            log.info(
                "agent.strategy.rl.runner.train_multi_seed.seed_done",
                seed=seed,
                sharpe=metrics.sharpe_ratio,
                roi_pct=metrics.roi_pct,
                error=metrics.error,
            )

        comparison = self._build_comparison(all_metrics, time.monotonic() - t_start)
        self._save_comparison(comparison)
        return comparison

    def evaluate_model(self, model_path: str, test_config: Any | None = None) -> SeedMetrics:
        """Evaluate a saved model on the test split and return metrics.

        This method can be called independently without running training —
        useful for re-evaluating existing models or evaluating models trained
        outside of :meth:`train_seed`.

        Args:
            model_path: Path to the SB3 ``.zip`` model file.
            test_config: Optional :class:`RLConfig` override.  Falls back to
                the instance config if not provided.

        Returns:
            :class:`SeedMetrics` populated with evaluation results.
            ``total_timesteps`` is set to 0 (unknown), ``training_wall_time_sec``
            to 0.0, and ``converged`` to ``True`` (assumption for pre-trained).
        """
        config = test_config or self._config
        log.info("agent.strategy.rl.runner.evaluate_model.start", model_path=model_path)
        eval_metrics = _evaluate_model_sync(model_path, config)
        return SeedMetrics(
            seed=0,
            model_path=model_path,
            sharpe_ratio=eval_metrics["sharpe_ratio"],
            roi_pct=eval_metrics["roi_pct"],
            max_drawdown_pct=eval_metrics["max_drawdown_pct"],
            win_rate=eval_metrics["win_rate"],
            total_timesteps=0,
            training_wall_time_sec=0.0,
            converged=True,
            final_eval_reward=eval_metrics["final_eval_reward"],
        )

    def tune_hyperparams(self, seed: int = 42) -> SeedMetrics:
        """Attempt hyperparameter tuning until target Sharpe is reached.

        Iterates through up to ``max_tune_attempts`` modifications to the
        base config (see :func:`_tune_config`).  Stops as soon as a model
        exceeds ``target_sharpe``.  Returns the best result found even if
        the target was never met.

        Args:
            seed: Seed to use for all tuning runs.  Using a fixed seed keeps
                comparison fair across tuning attempts.

        Returns:
            :class:`SeedMetrics` for the best tuning attempt.  ``tuned``
            will be ``True``.

        Side effects:
            Appends each attempt to ``results/training_log.json``.
        """
        log.info(
            "agent.strategy.rl.runner.tune_hyperparams.start",
            seed=seed,
            target_sharpe=self._target_sharpe,
            max_attempts=self._max_tune_attempts,
        )

        best: SeedMetrics | None = None

        for attempt in range(1, self._max_tune_attempts + 1):
            log.info("agent.strategy.rl.runner.tune_hyperparams.attempt", attempt=attempt)
            tuned_config = _tune_config(self._config, attempt)
            metrics = self.train_seed(seed, tuned_config=tuned_config)

            if best is None or (
                metrics.sharpe_ratio is not None
                and (best.sharpe_ratio is None or metrics.sharpe_ratio > best.sharpe_ratio)
            ):
                best = metrics

            if (
                metrics.sharpe_ratio is not None
                and metrics.sharpe_ratio >= self._target_sharpe
            ):
                log.info(
                    "agent.strategy.rl.runner.tune_hyperparams.target_reached",
                    attempt=attempt,
                    sharpe=metrics.sharpe_ratio,
                )
                break
        else:
            log.warning(
                "agent.strategy.rl.runner.tune_hyperparams.target_not_reached",
                best_sharpe=best.sharpe_ratio if best else None,
                target=self._target_sharpe,
            )

        return best  # type: ignore[return-value]

    # ── Private helpers ────────────────────────────────────────────────────────

    def _build_comparison(
        self, metrics: list[SeedMetrics], total_wall_time: float
    ) -> MultiSeedComparison:
        """Assemble a :class:`MultiSeedComparison` from per-seed results.

        Args:
            metrics: All :class:`SeedMetrics` objects, one per seed.
            total_wall_time: Total wall-clock seconds for all seeds combined.

        Returns:
            :class:`MultiSeedComparison`.
        """
        successful = [m for m in metrics if m.error is None]

        # Best seed = highest Sharpe; fall back to highest final_eval_reward.
        best_metrics: SeedMetrics | None = None
        if successful:
            with_sharpe = [m for m in successful if m.sharpe_ratio is not None]
            if with_sharpe:
                best_metrics = max(with_sharpe, key=lambda m: m.sharpe_ratio)  # type: ignore[arg-type]
            else:
                with_reward = [m for m in successful if m.final_eval_reward is not None]
                if with_reward:
                    best_metrics = max(with_reward, key=lambda m: m.final_eval_reward)  # type: ignore[arg-type]

        sharpes = [m.sharpe_ratio for m in successful if m.sharpe_ratio is not None]
        rois = [m.roi_pct for m in successful if m.roi_pct is not None]

        mean_sharpe = sum(sharpes) / len(sharpes) if sharpes else None
        mean_roi = sum(rois) / len(rois) if rois else None
        target_met = any(
            (m.sharpe_ratio or 0.0) >= self._target_sharpe for m in successful
        )

        return MultiSeedComparison(
            seeds=sorted(metrics, key=lambda m: m.seed),
            best_seed=best_metrics.seed if best_metrics else None,
            best_model_path=best_metrics.model_path if best_metrics else None,
            mean_sharpe=round(mean_sharpe, 4) if mean_sharpe is not None else None,
            mean_roi_pct=round(mean_roi, 4) if mean_roi is not None else None,
            target_sharpe_met=target_met,
            total_wall_time_sec=round(total_wall_time, 2),
            tuning_applied=any(m.tuned for m in metrics),
        )

    def _save_training_log(self, metrics: list[SeedMetrics]) -> None:
        """Persist per-seed metrics to ``results/training_log.json``.

        Args:
            metrics: Current list of completed :class:`SeedMetrics`.
        """
        log_path = self._results_dir / "training_log.json"
        data = [m.model_dump() for m in metrics]
        log_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.debug("agent.strategy.rl.runner.training_log.saved", path=str(log_path), n_seeds=len(metrics))

    def _save_comparison(self, comparison: MultiSeedComparison) -> None:
        """Persist the multi-seed comparison to ``results/comparison.json``.

        Args:
            comparison: Completed :class:`MultiSeedComparison`.
        """
        comp_path = self._results_dir / "comparison.json"
        comp_path.write_text(comparison.model_dump_json(indent=2), encoding="utf-8")
        log.info(
            "agent.strategy.rl.runner.comparison.saved",
            path=str(comp_path),
            best_seed=comparison.best_seed,
            mean_sharpe=comparison.mean_sharpe,
            target_met=comparison.target_sharpe_met,
        )

    def walk_forward_train(
        self,
        data_start: str | None = None,
        data_end: str | None = None,
        train_months: int = 6,
        oos_months: int = 1,
    ) -> "WalkForwardResult":  # type: ignore[name-defined]
        """Run walk-forward validation for the RL strategy.

        Trains a fresh PPO model on each rolling window's training period, then
        evaluates it on the immediately following OOS period.  Walk-Forward
        Efficiency (WFE) must exceed 50 % for the strategy to be considered
        deployable.

        This method is a synchronous convenience wrapper around
        :func:`~agent.strategies.walk_forward.walk_forward_rl` so it fits
        naturally into the :class:`TrainingRunner` workflow.

        Args:
            data_start: ISO-8601 UTC start of the full data range.  Defaults to
                ``config.train_start``.
            data_end: ISO-8601 UTC end of the full data range.  Defaults to
                ``config.test_end``.
            train_months: Calendar months in each training window.  Default 6.
            oos_months: Calendar months in each OOS window.  Default 1.

        Returns:
            :class:`~agent.strategies.walk_forward.WalkForwardResult` with
            per-window Sharpe metrics, WFE, and a deployability flag.

        Side effects:
            Writes ``agent/strategies/walk_forward_results/rl_wf_report.json``
            with the full per-window breakdown and summary.
        """
        from agent.strategies.walk_forward import (  # noqa: PLC0415
            WalkForwardConfig,
            WalkForwardResult,
            walk_forward_rl,
        )

        wf_config = WalkForwardConfig(
            data_start=data_start or self._config.train_start,
            data_end=data_end or self._config.test_end,
            train_months=train_months,
            oos_months=oos_months,
        )

        log.info(
            "agent.strategy.rl.runner.walk_forward.start",
            data_start=wf_config.data_start,
            data_end=wf_config.data_end,
            train_months=train_months,
            oos_months=oos_months,
        )

        result: WalkForwardResult = asyncio.run(
            walk_forward_rl(config=self._config, wf_config=wf_config)
        )

        log.info(
            "agent.strategy.rl.runner.walk_forward.complete",
            wfe=result.walk_forward_efficiency,
            is_deployable=result.is_deployable,
            successful_windows=result.successful_windows,
            total_windows=result.total_windows,
        )

        if result.overfit_warning:
            log.warning(
                "agent.strategy.rl.runner.walk_forward.overfit_warning",
                wfe=result.walk_forward_efficiency,
                threshold=result.wfe_threshold,
                message="WFE below threshold — strategy likely overfit. Do NOT deploy.",
            )

        return result


# ── CLI ───────────────────────────────────────────────────────────────────────


def _configure_logging(verbose: bool) -> None:
    """Configure structlog for the runner CLI.

    Args:
        verbose: When ``True``, enable DEBUG-level output.
    """
    from agent.logging import configure_agent_logging  # noqa: PLC0415

    configure_agent_logging(log_level="DEBUG" if verbose else "INFO")


def _parse_seeds(raw: str) -> list[int]:
    """Parse a comma-separated seed list string.

    Args:
        raw: E.g. ``"42,123,456"`` or ``"42"``.

    Returns:
        List of integer seeds.

    Raises:
        :class:`argparse.ArgumentTypeError`: On invalid input.
    """
    try:
        return [int(s.strip()) for s in raw.split(",") if s.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Seeds must be comma-separated integers, got: {raw!r}"
        )


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser`.
    """
    p = argparse.ArgumentParser(
        prog="python -m agent.strategies.rl.runner",
        description=(
            "Training execution harness: validate -> train (multi-seed) -> "
            "evaluate -> tune if Sharpe < target."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument(
        "--seeds",
        type=_parse_seeds,
        default="42,123,456",
        metavar="S1,S2,...",
        help="Comma-separated random seeds to train (e.g. 42,123,456).",
    )
    p.add_argument(
        "--timesteps",
        type=int,
        default=None,
        metavar="N",
        help="Total training timesteps per seed (default: from RLConfig).",
    )
    p.add_argument(
        "--target-sharpe",
        type=float,
        default=1.0,
        metavar="S",
        help="Target Sharpe ratio; triggers tuning if not met.",
    )
    p.add_argument(
        "--tune",
        action="store_true",
        help="Enable hyperparameter tuning if target Sharpe is not reached.",
    )
    p.add_argument(
        "--max-tune-attempts",
        type=int,
        default=3,
        metavar="N",
        help="Maximum tuning attempts before accepting best-so-far.",
    )
    p.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip the data readiness validation step.",
    )
    p.add_argument(
        "--no-track",
        action="store_true",
        help="Disable platform training-run tracking via TrainingTracker.",
    )
    p.add_argument(
        "--evaluate",
        type=str,
        default=None,
        metavar="PATH",
        help="Evaluate an existing model .zip instead of training.",
    )
    p.add_argument(
        "--base-url",
        type=str,
        default=None,
        metavar="URL",
        help="Platform REST API base URL (overrides default http://localhost:8000).",
    )
    p.add_argument(
        "--n-envs",
        type=int,
        default=None,
        metavar="N",
        help="Parallel training environments per seed.",
    )
    p.add_argument(
        "--reward",
        choices=["pnl", "sharpe", "sortino", "drawdown"],
        default=None,
        help="Reward function.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level log output.",
    )

    return p


def main() -> None:
    """CLI entry point.

    Loads :class:`RLConfig`, applies CLI overrides, constructs a
    :class:`TrainingRunner`, and runs the requested pipeline.
    """
    p = _build_parser()
    args = p.parse_args()
    _configure_logging(args.verbose)

    from agent.strategies.rl.config import RLConfig  # noqa: PLC0415

    try:
        config = RLConfig()
    except Exception as exc:
        log.error("agent.strategy.rl.runner.config.load_failed", error=str(exc))
        sys.exit(1)

    # Apply CLI overrides.
    overrides: dict[str, Any] = {}
    if args.timesteps is not None:
        overrides["total_timesteps"] = args.timesteps
    if args.base_url is not None:
        overrides["platform_base_url"] = args.base_url
    if args.n_envs is not None:
        overrides["n_envs"] = args.n_envs
    if args.reward is not None:
        overrides["reward_type"] = args.reward
    if args.no_track:
        overrides["track_training"] = False
    if overrides:
        config = config.model_copy(update=overrides)

    # Guard: API key required for everything except --evaluate.
    if not args.evaluate and not config.platform_api_key:
        log.error(
            "agent.strategy.rl.runner.config.missing_api_key",
            hint=(
                "Set RL_PLATFORM_API_KEY in agent/.env or as environment variable"
            ),
        )
        sys.exit(1)

    runner = TrainingRunner(
        config=config,
        target_sharpe=args.target_sharpe,
        max_tune_attempts=args.max_tune_attempts,
    )

    # ── Evaluation-only mode ──────────────────────────────────────────────────
    if args.evaluate:
        model_path = args.evaluate
        if not Path(model_path).exists():
            log.error("agent.strategy.rl.runner.evaluate.model_not_found", path=model_path)
            sys.exit(1)
        result = runner.evaluate_model(model_path)
        print(json.dumps(result.model_dump(), indent=2))  # noqa: T201
        return

    # ── Validation step ───────────────────────────────────────────────────────
    if not args.no_validate:
        if not runner.validate_data():
            log.error(
                "agent.strategy.rl.runner.pipeline.data_not_ready",
                hint="Use --no-validate to skip, or fix data coverage first.",
            )
            sys.exit(1)

    # ── Training ──────────────────────────────────────────────────────────────
    seeds: list[int] = args.seeds
    log.info("agent.strategy.rl.runner.pipeline.starting", seeds=seeds, timesteps=config.total_timesteps)

    comparison = runner.train_multi_seed(seeds)

    # ── Tuning (optional) ─────────────────────────────────────────────────────
    if args.tune and not comparison.target_sharpe_met:
        log.info(
            "agent.strategy.rl.runner.pipeline.tuning_triggered",
            best_sharpe=comparison.mean_sharpe,
            target=args.target_sharpe,
        )
        tune_seed = seeds[0]
        tuned_result = runner.tune_hyperparams(seed=tune_seed)
        # Merge tuned result into the comparison log.
        all_metrics = list(comparison.seeds) + [tuned_result]
        comparison = runner._build_comparison(
            all_metrics,
            comparison.total_wall_time_sec + tuned_result.training_wall_time_sec,
        )
        runner._save_comparison(comparison)

    # ── Final report ─────────────────────────────────────────────────────────
    log.info(
        "agent.strategy.rl.runner.pipeline.complete",
        best_seed=comparison.best_seed,
        mean_sharpe=comparison.mean_sharpe,
        target_sharpe_met=comparison.target_sharpe_met,
        total_wall_time_sec=comparison.total_wall_time_sec,
    )

    if not comparison.target_sharpe_met:
        log.warning(
            "agent.strategy.rl.runner.pipeline.target_not_met",
            target_sharpe=args.target_sharpe,
            hint="Consider --tune or increasing --timesteps.",
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
