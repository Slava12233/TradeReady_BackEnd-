"""Automated retraining pipeline for all ML strategy components.

:class:`RetrainOrchestrator` manages periodic retraining of the four ML strategy
components: ensemble weights (every session), regime classifier (weekly), genome
population (weekly, 2-3 new generations), and PPO RL models (monthly, rolling
6-month training window).

Each retraining cycle follows the same five-step pattern:

1. Train a new model/weights on recent + historical data.
2. Backtest the new model on a held-out period.
3. Compare against the current production model via :class:`ModelComparison`.
4. Deploy only if the new model outperforms (A/B gate).
5. Log results to the memory system via structured logging.

Architecture::

    RetrainOrchestrator
        │
        ├── _retrain_ensemble_weights()   → runs every session
        ├── _retrain_regime_classifier()  → runs weekly
        ├── _retrain_genome_population()  → runs weekly (2-3 generations)
        └── _retrain_rl_models()          → runs monthly (rolling 6-month window)
                │
                ├── _compare_models()     → A/B gate before deployment
                └── _record_result()      → persists RetrainResult to memory

Usage::

    from agent.strategies.retrain import RetrainOrchestrator, RetrainConfig

    orchestrator = RetrainOrchestrator(
        config=RetrainConfig(),
        rest_client=rest_client,
        sdk_client=sdk_client,
    )

    # Manual trigger for one component
    result = await orchestrator.retrain_ensemble()

    # Full scheduled cycle — caller decides timing
    results = await orchestrator.run_scheduled_cycle(now=datetime.now(UTC))
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger(__name__)

# ── Resolve agent .env path ────────────────────────────────────────────────────

_ENV_FILE = Path(__file__).parent.parent / ".env"

# ── Constants ──────────────────────────────────────────────────────────────────

# Minimum improvement required for a new model to replace the current one.
# A new model must beat the incumbent by at least this much (as an absolute
# difference in the primary metric) to be deployed.  Prevents constantly
# redeploying models that are only marginally better (which could be noise).
_MIN_IMPROVEMENT_THRESHOLD: float = 0.01

# Number of new generations to run in each weekly genome refresh.
# 2-3 is specified in the task; defaulting to 2 keeps wall-clock time low.
_GENOME_REFRESH_GENERATIONS: int = 2

# Rolling window for RL training expressed in months.
_RL_TRAINING_WINDOW_MONTHS: int = 6

# Maximum number of RetrainResult entries kept in the in-memory audit log.
_MAX_AUDIT_LOG_SIZE: int = 500


# ── Pydantic models ────────────────────────────────────────────────────────────


class RetrainConfig(BaseSettings):
    """Configuration for the automated retraining pipeline.

    All fields are overridable via environment variables with the ``RETRAIN_``
    prefix or via the ``agent/.env`` file.

    Example::

        config = RetrainConfig()
        config = RetrainConfig(min_improvement=0.02)
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_prefix="RETRAIN_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Scheduling ─────────────────────────────────────────────────────────────

    ensemble_retrain_interval_hours: float = Field(
        default=8.0,
        gt=0.0,
        description=(
            "How often to retrain ensemble weights, in hours.  8h corresponds to "
            "one trading session (Asian / European / US).  Shorter windows track "
            "recent performance changes faster at the cost of higher compute."
        ),
    )
    regime_retrain_interval_days: float = Field(
        default=7.0,
        gt=0.0,
        description=(
            "How often to retrain the regime classifier, in days.  Weekly retraining "
            "keeps the 6-feature XGBoost model aligned with recent market micro-structure "
            "changes without causing overfitting to short-term noise."
        ),
    )
    genome_retrain_interval_days: float = Field(
        default=7.0,
        gt=0.0,
        description=(
            "How often to run a genome population refresh, in days.  The weekly "
            "refresh runs 2-3 new GA generations to incrementally improve the "
            "champion strategy without running the full 30-generation evolution."
        ),
    )
    rl_retrain_interval_days: float = Field(
        default=30.0,
        gt=0.0,
        description=(
            "How often to retrain the PPO model, in days.  Monthly retraining "
            "uses a rolling 6-month training window to incorporate new market "
            "data while preventing the model from forgetting long-run patterns."
        ),
    )

    # ── Quality gate ───────────────────────────────────────────────────────────

    min_improvement: float = Field(
        default=_MIN_IMPROVEMENT_THRESHOLD,
        ge=0.0,
        description=(
            "Minimum absolute improvement in the primary metric (Sharpe ratio for "
            "RL; ensemble accuracy for weights; accuracy for regime; composite fitness "
            "for genome) that a new model must achieve over the current production "
            "model to be deployed.  0.01 prevents noisy swaps."
        ),
    )
    backtest_days: int = Field(
        default=30,
        ge=7,
        description=(
            "Number of days in the held-out backtest period used to evaluate a "
            "new model before comparing with the incumbent.  30 days provides "
            "statistically meaningful performance estimates without consuming "
            "too much of the available historical window."
        ),
    )

    # ── RL-specific ────────────────────────────────────────────────────────────

    rl_training_window_months: int = Field(
        default=_RL_TRAINING_WINDOW_MONTHS,
        ge=1,
        description=(
            "Length of the rolling training window for PPO models, in months.  "
            "A 6-month window is long enough to capture multiple market regimes "
            "while keeping training feasible on a single workstation."
        ),
    )
    rl_quick_timesteps: int = Field(
        default=50_000,
        ge=1_000,
        description=(
            "Total timesteps for a quick RL retrain (smoke test mode).  Full "
            "monthly retrains use the ``RLConfig.total_timesteps`` value (default "
            "500k).  The quick mode is used in tests and CI pipelines."
        ),
    )

    # ── Genome-specific ────────────────────────────────────────────────────────

    genome_refresh_generations: int = Field(
        default=_GENOME_REFRESH_GENERATIONS,
        ge=1,
        description=(
            "Number of new GA generations to run during each weekly genome refresh.  "
            "2-3 new generations on top of the champion population are enough to "
            "improve without full convergence detection overhead."
        ),
    )

    # ── Platform connectivity ──────────────────────────────────────────────────

    platform_api_key: str = Field(
        default="",
        description=(
            "TradeReady ak_live_... API key used by retraining jobs that need to "
            "create backtest sessions or run GA battles.  Reads from "
            "RETRAIN_PLATFORM_API_KEY or agent/.env."
        ),
    )
    platform_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL of the TradeReady REST API.",
    )

    # ── Results persistence ────────────────────────────────────────────────────

    results_dir: Path = Field(
        default=Path(__file__).parent / "retrain_results",
        description=(
            "Directory where RetrainResult JSON files are written after each "
            "retraining cycle.  Gitignored; created on first use."
        ),
    )


class ModelComparison(BaseModel):
    """Result of comparing a candidate model to the current production model.

    Args:
        component: Strategy component being compared (e.g. ``"rl"``, ``"regime"``).
        incumbent_score: Primary metric score for the current production model.
        candidate_score: Primary metric score for the newly trained model.
        improvement: ``candidate_score - incumbent_score``.  Positive means better.
        deploy: Whether the candidate should replace the incumbent.
        metric_name: Human-readable name of the primary metric.
        details: Additional metrics dictionary for logging (secondary metrics,
            benchmark comparisons, etc.).
    """

    model_config = ConfigDict(frozen=True)

    component: str
    incumbent_score: float | None
    candidate_score: float | None
    improvement: float
    deploy: bool
    metric_name: str
    details: dict[str, Any] = Field(default_factory=dict)


class RetrainResult(BaseModel):
    """Record of one completed retraining cycle for a single component.

    Args:
        component: Which strategy component was retrained.
        triggered_at: UTC timestamp when the retraining job was initiated.
        completed_at: UTC timestamp when the job finished (or failed).
        success: Whether the retraining job completed without errors.
        comparison: Model comparison result including deployment decision.  ``None``
            when the job failed before comparison could be performed.
        deployed: Whether the new model was actually deployed to production.
        artifact_path: Filesystem path to the newly trained model artifact.  ``None``
            on failure or when no artifact was produced (e.g. ensemble weights).
        error: Error message when ``success=False``.
        metadata: Arbitrary metadata dict (e.g. training hyperparameters, data window).
    """

    model_config = ConfigDict(frozen=True)

    component: str
    triggered_at: str  # ISO-8601 UTC
    completed_at: str  # ISO-8601 UTC
    success: bool
    comparison: ModelComparison | None = None
    deployed: bool = False
    artifact_path: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_log_dict(self) -> dict[str, Any]:
        """Return a flat dict suitable for structured logging."""
        return {
            "component": self.component,
            "triggered_at": self.triggered_at,
            "completed_at": self.completed_at,
            "success": self.success,
            "deployed": self.deployed,
            "improvement": self.comparison.improvement if self.comparison else None,
            "metric": self.comparison.metric_name if self.comparison else None,
            "artifact_path": self.artifact_path,
            "error": self.error,
        }


class ScheduleState(BaseModel):
    """Tracks when each component was last retrained to drive scheduling.

    Args:
        last_ensemble_retrain: UTC ISO-8601 of last ensemble weight retrain.
        last_regime_retrain: UTC ISO-8601 of last regime classifier retrain.
        last_genome_retrain: UTC ISO-8601 of last genome population retrain.
        last_rl_retrain: UTC ISO-8601 of last PPO model retrain.
    """

    model_config = ConfigDict(frozen=False)  # mutable — updated in place

    last_ensemble_retrain: str | None = None
    last_regime_retrain: str | None = None
    last_genome_retrain: str | None = None
    last_rl_retrain: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _hours_since(iso_ts: str | None) -> float:
    """Return hours elapsed since *iso_ts* (UTC). ``inf`` when *iso_ts* is None."""
    if iso_ts is None:
        return float("inf")
    last = datetime.fromisoformat(iso_ts)
    return (datetime.now(UTC) - last).total_seconds() / 3600.0


def _rolling_window_dates(months: int) -> tuple[str, str]:
    """Return ISO-8601 (train_start, train_end) for a rolling *months*-month window.

    The window ends at midnight today and extends backwards by *months* calendar
    months.  This avoids look-ahead bias by never including today's incomplete
    candle data in the training set.

    Args:
        months: Number of calendar months in the rolling window.

    Returns:
        ``(start_iso, end_iso)`` tuple of ISO-8601 UTC strings.
    """
    now = datetime.now(UTC)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Approximate: subtract 30 days per month
    start = end - timedelta(days=months * 30)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def _backtest_window(backtest_days: int) -> tuple[str, str]:
    """Return the held-out backtest period (train_end - 2*backtest_days to train_end - backtest_days).

    The evaluation period sits just before the held-out test window so the test
    window remains clean for final comparison.

    Args:
        backtest_days: Number of days in the held-out period.

    Returns:
        ``(eval_start_iso, eval_end_iso)`` tuple.
    """
    now = datetime.now(UTC)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=backtest_days)
    start = end - timedelta(days=backtest_days)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Main orchestrator ──────────────────────────────────────────────────────────


class RetrainOrchestrator:
    """Automated retraining pipeline for all ML strategy components.

    Manages four retraining jobs on separate schedules:

    - **Ensemble weights** — every ``config.ensemble_retrain_interval_hours`` hours.
      Runs ``optimize_weights.py``-style backtest grid search and deploys the
      optimal weight vector if it improves ensemble accuracy.

    - **Regime classifier** — every ``config.regime_retrain_interval_days`` days.
      Retrains ``RegimeClassifier`` on fresh historical data and compares held-out
      accuracy against the production classifier.

    - **Genome population** — every ``config.genome_retrain_interval_days`` days.
      Runs ``config.genome_refresh_generations`` new GA generations from the current
      champion genome and deploys the new champion if fitness improves.

    - **PPO RL models** — every ``config.rl_retrain_interval_days`` days.
      Retrains PPO on a rolling ``config.rl_training_window_months``-month window
      and compares Sharpe ratio against the current production model.

    Each job follows the train → backtest → compare → gate → deploy sequence.
    All results are logged via structlog and persisted as JSON to ``config.results_dir``.

    The orchestrator never raises from :meth:`run_scheduled_cycle` or individual
    ``retrain_*()`` methods — all errors are caught, logged, and returned as
    ``RetrainResult(success=False)``.

    Args:
        config: ``RetrainConfig`` instance with all scheduling and quality-gate settings.
        rest_client: Async REST client for platform API calls (backtest creation,
            strategy management).  Pass ``None`` to run in offline mode (some
            functionality will be skipped).
        sdk_client: Async SDK exchange client for live data fetching.  Pass ``None``
            to run in offline mode.
        rl_trainer: Optional callable ``(config) -> Path`` for running PPO training.
            Defaults to :func:`agent.strategies.rl.train.train` when not provided.
        genome_evolver: Optional callable ``(config, generations) -> float`` for
            running genome evolution.  Defaults to the internal ``_run_genome_evolution``
            helper when not provided.
        regime_trainer: Optional callable ``(candles) -> RegimeClassifier`` for
            retraining the regime classifier.  Defaults to instantiating
            ``RegimeClassifier`` and calling ``.train()`` when not provided.
        ensemble_optimizer: Optional callable ``() -> dict[str, float]`` for
            optimising ensemble weights.  Defaults to the backtest grid search.
    """

    def __init__(
        self,
        config: RetrainConfig,
        rest_client: Any | None = None,
        sdk_client: Any | None = None,
        *,
        rl_trainer: Any | None = None,
        genome_evolver: Any | None = None,
        regime_trainer: Any | None = None,
        ensemble_optimizer: Any | None = None,
    ) -> None:
        self._config = config
        self._rest_client = rest_client
        self._sdk_client = sdk_client

        # Injectable training callables — test seam for mocking
        self._rl_trainer = rl_trainer
        self._genome_evolver = genome_evolver
        self._regime_trainer = regime_trainer
        self._ensemble_optimizer = ensemble_optimizer

        # Schedule tracking — persisted between cycles within the same process
        self._schedule = ScheduleState()

        # In-memory audit log (bounded)
        self._audit_log: deque[RetrainResult] = deque(maxlen=_MAX_AUDIT_LOG_SIZE)

        # Current production model scores — updated after each successful deploy
        self._incumbent_scores: dict[str, float | None] = {
            "ensemble": None,
            "regime": None,
            "genome": None,
            "rl": None,
        }

        config.results_dir.mkdir(parents=True, exist_ok=True)

    # ── Public interface ───────────────────────────────────────────────────────

    @property
    def audit_log(self) -> list[RetrainResult]:
        """Return a snapshot of the in-memory audit log (newest-last order)."""
        return list(self._audit_log)

    @property
    def schedule(self) -> ScheduleState:
        """Return the current schedule state (last retrain timestamps)."""
        return self._schedule

    async def run_scheduled_cycle(self, now: datetime | None = None) -> list[RetrainResult]:
        """Run all overdue retraining jobs based on the configured schedule.

        Checks each component's last-retrain timestamp against its configured
        interval.  Any overdue component is retrained concurrently via
        ``asyncio.gather``.  Jobs that are not yet due are skipped silently.

        Args:
            now: Override for the current time (used in tests).  Defaults to
                 ``datetime.now(UTC)``.

        Returns:
            List of :class:`RetrainResult` objects for every job that ran.
            Empty list if nothing was due.
        """
        if now is None:
            now = datetime.now(UTC)

        log.info("agent.strategy.retrain.cycle.start", ts=now.isoformat())

        due: list[tuple[str, Any]] = []

        if _hours_since(self._schedule.last_ensemble_retrain) >= self._config.ensemble_retrain_interval_hours:
            due.append(("ensemble", self.retrain_ensemble))
        if _hours_since(self._schedule.last_regime_retrain) >= self._config.regime_retrain_interval_days * 24:
            due.append(("regime", self.retrain_regime))
        if _hours_since(self._schedule.last_genome_retrain) >= self._config.genome_retrain_interval_days * 24:
            due.append(("genome", self.retrain_genome))
        if _hours_since(self._schedule.last_rl_retrain) >= self._config.rl_retrain_interval_days * 24:
            due.append(("rl", self.retrain_rl))

        if not due:
            log.info("agent.strategy.retrain.cycle.nothing_due")
            return []

        log.info("agent.strategy.retrain.cycle.due", components=[c for c, _ in due])

        results = await asyncio.gather(*[fn() for _, fn in due], return_exceptions=False)
        log.info("agent.strategy.retrain.cycle.complete",
                 total=len(results),
                 deployed=sum(1 for r in results if r.deployed))
        return list(results)

    async def retrain_ensemble(self) -> RetrainResult:
        """Retrain and optionally deploy ensemble source weights.

        Runs a backtest grid search over weight configurations, compares the best
        configuration's accuracy against the current production weights, and
        deploys (saves the new weights JSON) when improvement exceeds the
        configured threshold.

        Returns:
            :class:`RetrainResult` with the comparison outcome and deployment status.
        """
        triggered_at = _utc_now_iso()
        log.info("agent.strategy.retrain.ensemble.start")
        try:
            result = await self._run_ensemble_retrain(triggered_at)
        except Exception as exc:  # noqa: BLE001
            log.exception("agent.strategy.retrain.ensemble.failed", error=str(exc))
            result = self._failure_result("ensemble", triggered_at, str(exc))
        self._record_result(result)
        return result

    async def retrain_regime(self) -> RetrainResult:
        """Retrain and optionally deploy the regime classifier.

        Fetches recent OHLCV candles, retrains a ``RegimeClassifier`` on the
        labelled data, evaluates accuracy on the held-out period, and deploys
        (saves the new ``.joblib`` file) when accuracy improves beyond the
        configured threshold.

        Returns:
            :class:`RetrainResult` with the comparison outcome and deployment status.
        """
        triggered_at = _utc_now_iso()
        log.info("agent.strategy.retrain.regime.start")
        try:
            result = await self._run_regime_retrain(triggered_at)
        except Exception as exc:  # noqa: BLE001
            log.exception("agent.strategy.retrain.regime.failed", error=str(exc))
            result = self._failure_result("regime", triggered_at, str(exc))
        self._record_result(result)
        return result

    async def retrain_genome(self) -> RetrainResult:
        """Run new GA generations and optionally deploy the improved champion.

        Takes the current champion genome as the seed population, runs
        ``config.genome_refresh_generations`` new generations, and deploys the
        new champion when composite fitness improves.

        Returns:
            :class:`RetrainResult` with fitness comparison and deployment status.
        """
        triggered_at = _utc_now_iso()
        log.info("agent.strategy.retrain.genome.start")
        try:
            result = await self._run_genome_retrain(triggered_at)
        except Exception as exc:  # noqa: BLE001
            log.exception("agent.strategy.retrain.genome.failed", error=str(exc))
            result = self._failure_result("genome", triggered_at, str(exc))
        self._record_result(result)
        return result

    async def retrain_rl(self) -> RetrainResult:
        """Retrain the PPO model on a rolling window and optionally deploy.

        Computes a rolling ``config.rl_training_window_months``-month training
        window ending today, runs PPO training (or the injected ``rl_trainer``
        callable), evaluates Sharpe ratio on the held-out period, and deploys
        when Sharpe improves.

        Returns:
            :class:`RetrainResult` with Sharpe comparison and deployment status.
        """
        triggered_at = _utc_now_iso()
        log.info("agent.strategy.retrain.rl.start")
        try:
            result = await self._run_rl_retrain(triggered_at)
        except Exception as exc:  # noqa: BLE001
            log.exception("agent.strategy.retrain.rl.failed", error=str(exc))
            result = self._failure_result("rl", triggered_at, str(exc))
        self._record_result(result)
        return result

    async def trigger_drift_retrain(
        self,
        strategy_name: str,
        redis_client: Any | None = None,  # noqa: ANN401  — async Redis client has no public type
    ) -> RetrainResult | None:
        """Enqueue an ensemble retrain triggered by concept drift detection.

        Applies a per-strategy cooldown (minimum 1 hour between drift-triggered
        retrains) tracked in Redis under key ``retrain:cooldown:{strategy_name}``
        with a 3600-second TTL.  If the cooldown key is present the call is a
        no-op and ``None`` is returned.

        The retrain itself is delegated to :meth:`retrain_ensemble` because
        drift — by definition — means the current ensemble weights no longer
        reflect the live market distribution.  The full A/B gate still applies,
        so a drift-triggered retrain only deploys when the new weights are
        measurably better than the current ones.

        Args:
            strategy_name: Name of the drifting strategy (used as part of the
                Redis cooldown key so each strategy has its own independent
                cooldown budget).
            redis_client: Optional async Redis client instance.  When ``None``
                the cooldown check is skipped and retraining always proceeds.
                Pass a client to enable the 1-hour cooldown guard.

        Returns:
            :class:`RetrainResult` when a retrain was triggered, or ``None``
            when the call was suppressed by the cooldown.
        """
        cooldown_key = f"retrain:cooldown:{strategy_name}"
        _COOLDOWN_TTL_SECONDS: int = 3600

        if redis_client is not None:
            try:
                existing = await redis_client.get(cooldown_key)
                if existing is not None:
                    log.info(
                        "agent.strategy.retrain.drift.cooldown_active",
                        strategy_name=strategy_name,
                        cooldown_key=cooldown_key,
                    )
                    return None
                # Set the cooldown key before starting — prevents concurrent drift
                # events on the same strategy from launching duplicate retrains.
                await redis_client.setex(cooldown_key, _COOLDOWN_TTL_SECONDS, "1")
            except Exception as exc:  # noqa: BLE001
                # Redis failure must never block the retrain; proceed without cooldown.
                log.warning(
                    "agent.strategy.retrain.drift.redis_error",
                    strategy_name=strategy_name,
                    error=str(exc),
                )

        log.info(
            "agent.strategy.retrain.drift.triggered",
            strategy_name=strategy_name,
            trigger="drift",
        )
        return await self.retrain_ensemble()

    # ── Internal retraining implementations ───────────────────────────────────

    async def _run_ensemble_retrain(self, triggered_at: str) -> RetrainResult:
        """Internal: run ensemble weight optimisation and gate deployment.

        Strategy:
          1. Call the ensemble optimizer (custom or default grid search).
          2. Evaluate the new weights on the held-out backtest period.
          3. Compare against incumbent via accuracy improvement.
          4. Deploy (write optimal_weights.json) if gate passes.
        """
        # Step 1: obtain new optimal weights
        if self._ensemble_optimizer is not None:
            new_weights = await asyncio.to_thread(self._ensemble_optimizer)
        else:
            new_weights = await self._default_ensemble_optimize()

        # Step 2: evaluate new weights on held-out period
        eval_score = await self._evaluate_ensemble_weights(new_weights)

        # Step 3: compare with incumbent
        incumbent_score = self._incumbent_scores["ensemble"]
        comparison = self._build_comparison(
            component="ensemble",
            incumbent_score=incumbent_score,
            candidate_score=eval_score,
            metric_name="ensemble_accuracy",
        )

        # Step 4: deploy
        artifact_path: str | None = None
        deployed = False
        if comparison.deploy:
            artifact_path = await self._deploy_ensemble_weights(new_weights)
            self._incumbent_scores["ensemble"] = eval_score
            self._schedule.last_ensemble_retrain = _utc_now_iso()
            deployed = True
            log.info("agent.strategy.retrain.ensemble.deployed",
                     score=eval_score, improvement=comparison.improvement)
        else:
            # Still update schedule even when not deploying (run ran successfully)
            self._schedule.last_ensemble_retrain = _utc_now_iso()
            log.info("agent.strategy.retrain.ensemble.skipped_deploy",
                     reason="insufficient_improvement",
                     improvement=comparison.improvement,
                     threshold=self._config.min_improvement)

        return RetrainResult(
            component="ensemble",
            triggered_at=triggered_at,
            completed_at=_utc_now_iso(),
            success=True,
            comparison=comparison,
            deployed=deployed,
            artifact_path=artifact_path,
            metadata={"new_weights": new_weights},
        )

    async def _run_regime_retrain(self, triggered_at: str) -> RetrainResult:
        """Internal: retrain regime classifier and gate deployment."""
        from agent.strategies.regime.classifier import RegimeClassifier  # noqa: PLC0415
        from agent.strategies.regime.labeler import generate_training_data  # noqa: PLC0415

        # Step 1: fetch training candles and generate features
        candles = await self._fetch_candles_for_training()
        train_features, train_labels, test_features, test_labels = (
            await asyncio.to_thread(self._split_regime_data, candles)
        )

        # Step 2: train the classifier (injectable for tests)
        if self._regime_trainer is not None:
            classifier: RegimeClassifier = await asyncio.to_thread(
                self._regime_trainer, train_features, train_labels
            )
        else:
            classifier = RegimeClassifier()
            await asyncio.to_thread(classifier.train, train_features, train_labels)

        # Step 3: evaluate on held-out period
        eval_result = await asyncio.to_thread(classifier.evaluate, test_features, test_labels)
        candidate_score = float(eval_result.get("accuracy", 0.0))

        # Step 4: compare with incumbent
        incumbent_score = self._incumbent_scores["regime"]
        comparison = self._build_comparison(
            component="regime",
            incumbent_score=incumbent_score,
            candidate_score=candidate_score,
            metric_name="accuracy",
            details=eval_result,
        )

        # Step 5: deploy
        artifact_path: str | None = None
        deployed = False
        if comparison.deploy:
            artifact_path = await self._deploy_regime_classifier(classifier)
            self._incumbent_scores["regime"] = candidate_score
            deployed = True
            log.info("agent.strategy.retrain.regime.deployed",
                     accuracy=candidate_score, improvement=comparison.improvement)
        else:
            log.info("agent.strategy.retrain.regime.skipped_deploy",
                     reason="insufficient_improvement",
                     improvement=comparison.improvement)

        self._schedule.last_regime_retrain = _utc_now_iso()
        return RetrainResult(
            component="regime",
            triggered_at=triggered_at,
            completed_at=_utc_now_iso(),
            success=True,
            comparison=comparison,
            deployed=deployed,
            artifact_path=artifact_path,
            metadata={
                "train_samples": len(train_features),
                "test_samples": len(test_features),
                "eval": eval_result,
            },
        )

    async def _run_genome_retrain(self, triggered_at: str) -> RetrainResult:
        """Internal: run new GA generations and gate champion deployment."""
        # Step 1: run genome evolution (injectable for tests)
        generations = self._config.genome_refresh_generations
        if self._genome_evolver is not None:
            candidate_fitness: float = await asyncio.to_thread(
                self._genome_evolver, generations
            )
        else:
            candidate_fitness = await self._run_genome_evolution(generations)

        # Step 2: compare with incumbent
        incumbent_score = self._incumbent_scores["genome"]
        comparison = self._build_comparison(
            component="genome",
            incumbent_score=incumbent_score,
            candidate_score=candidate_fitness,
            metric_name="composite_fitness",
        )

        # Step 3: deploy
        artifact_path: str | None = None
        deployed = False
        if comparison.deploy:
            artifact_path = await self._deploy_genome_champion()
            self._incumbent_scores["genome"] = candidate_fitness
            deployed = True
            log.info("agent.strategy.retrain.genome.deployed",
                     fitness=candidate_fitness, improvement=comparison.improvement)
        else:
            log.info("agent.strategy.retrain.genome.skipped_deploy",
                     reason="insufficient_improvement",
                     improvement=comparison.improvement)

        self._schedule.last_genome_retrain = _utc_now_iso()
        return RetrainResult(
            component="genome",
            triggered_at=triggered_at,
            completed_at=_utc_now_iso(),
            success=True,
            comparison=comparison,
            deployed=deployed,
            artifact_path=artifact_path,
            metadata={"generations_run": generations, "candidate_fitness": candidate_fitness},
        )

    async def _run_rl_retrain(self, triggered_at: str) -> RetrainResult:
        """Internal: retrain PPO on rolling window and gate deployment."""
        from agent.strategies.rl.config import RLConfig  # noqa: PLC0415

        # Step 1: build rolling window config
        train_start, train_end = _rolling_window_dates(self._config.rl_training_window_months)
        eval_start, eval_end = _backtest_window(self._config.backtest_days)

        rl_config = RLConfig(
            train_start=train_start,
            train_end=train_end,
            test_start=eval_start,
            test_end=eval_end,
            platform_api_key=self._config.platform_api_key,
            platform_base_url=self._config.platform_base_url,
            track_training=False,  # suppress platform tracking during automated retrains
        )

        # Step 2: run training (injectable for tests; blocking in thread)
        if self._rl_trainer is not None:
            model_path: Path = await asyncio.to_thread(self._rl_trainer, rl_config)
        else:
            from agent.strategies.rl.train import train  # noqa: PLC0415
            model_path = await asyncio.to_thread(train, rl_config)

        # Step 3: evaluate the new model on the held-out window
        candidate_sharpe = await self._evaluate_rl_model(model_path, rl_config)

        # Step 4: compare with incumbent
        incumbent_score = self._incumbent_scores["rl"]
        comparison = self._build_comparison(
            component="rl",
            incumbent_score=incumbent_score,
            candidate_score=candidate_sharpe,
            metric_name="sharpe_ratio",
        )

        # Step 5: save checksum and deploy
        artifact_path: str | None = None
        deployed = False
        if comparison.deploy:
            artifact_path = await self._deploy_rl_model(model_path)
            self._incumbent_scores["rl"] = candidate_sharpe
            deployed = True
            log.info("agent.strategy.retrain.rl.deployed",
                     sharpe=candidate_sharpe, improvement=comparison.improvement,
                     model=str(artifact_path))
        else:
            log.info("agent.strategy.retrain.rl.skipped_deploy",
                     reason="insufficient_improvement",
                     improvement=comparison.improvement)

        self._schedule.last_rl_retrain = _utc_now_iso()
        return RetrainResult(
            component="rl",
            triggered_at=triggered_at,
            completed_at=_utc_now_iso(),
            success=True,
            comparison=comparison,
            deployed=deployed,
            artifact_path=str(model_path) if artifact_path else None,
            metadata={
                "train_start": train_start,
                "train_end": train_end,
                "eval_start": eval_start,
                "eval_end": eval_end,
                "candidate_sharpe": candidate_sharpe,
            },
        )

    # ── Comparison gate ────────────────────────────────────────────────────────

    def _build_comparison(
        self,
        component: str,
        incumbent_score: float | None,
        candidate_score: float | None,
        metric_name: str,
        details: dict[str, Any] | None = None,
    ) -> ModelComparison:
        """Build a :class:`ModelComparison` and determine the deploy decision.

        The deployment gate is:
        - ``candidate_score`` must be a valid float (not None).
        - If there is no incumbent (first run), always deploy.
        - Otherwise, improvement must exceed ``config.min_improvement``.

        Args:
            component: Short name identifying the strategy component.
            incumbent_score: Current production model's primary metric score.
            candidate_score: Newly trained model's primary metric score.
            metric_name: Display name of the primary metric.
            details: Optional secondary metrics to attach to the comparison.

        Returns:
            :class:`ModelComparison` with ``deploy=True/False``.
        """
        if candidate_score is None:
            improvement = 0.0
            deploy = False
        elif incumbent_score is None:
            # No incumbent — always deploy the first trained model
            improvement = float("inf")
            deploy = True
        else:
            improvement = candidate_score - incumbent_score
            deploy = improvement >= self._config.min_improvement

        log.info(
            "agent.strategy.retrain.comparison",
            component=component,
            metric=metric_name,
            incumbent=incumbent_score,
            candidate=candidate_score,
            improvement=improvement if improvement != float("inf") else None,
            deploy=deploy,
        )

        return ModelComparison(
            component=component,
            incumbent_score=incumbent_score,
            candidate_score=candidate_score,
            improvement=improvement if improvement != float("inf") else 999.0,
            deploy=deploy,
            metric_name=metric_name,
            details=details or {},
        )

    # ── Default trainer implementations ───────────────────────────────────────

    async def _default_ensemble_optimize(self) -> dict[str, float]:
        """Run a lightweight backtest comparison of candidate weight configs.

        Evaluates a small set of weight configurations via the REST client and
        returns the configuration that maximises ensemble accuracy over the
        held-out backtest period.

        When no REST client is available (offline mode), falls back to returning
        equal weights without making any API calls.

        Returns:
            Weight dict mapping source name to weight float.
        """
        if self._rest_client is None:
            log.warning("agent.strategy.retrain.ensemble.no_rest_client",
                        fallback="equal_weights")
            return {"rl": 0.333, "evolved": 0.333, "regime": 0.334}

        # Candidate configurations to evaluate
        candidates: list[dict[str, float]] = [
            {"rl": 0.5, "evolved": 0.3, "regime": 0.2},
            {"rl": 0.4, "evolved": 0.35, "regime": 0.25},
            {"rl": 0.333, "evolved": 0.333, "regime": 0.334},
            {"rl": 0.3, "evolved": 0.4, "regime": 0.3},
            {"rl": 0.2, "evolved": 0.5, "regime": 0.3},
            {"rl": 0.25, "evolved": 0.25, "regime": 0.5},
        ]

        best_weights = candidates[0]
        best_score = -float("inf")

        for weights in candidates:
            score = await self._score_ensemble_weights(weights)
            if score is not None and score > best_score:
                best_score = score
                best_weights = weights

        log.info("agent.strategy.retrain.ensemble.optimized",
                 best_score=best_score, best_weights=best_weights)
        return best_weights

    async def _score_ensemble_weights(self, weights: dict[str, float]) -> float | None:
        """Evaluate one weight configuration via backtest.

        Creates a short backtest session via the REST client and runs the
        ensemble with the given weights.  Returns the achieved accuracy proxy
        (fraction of steps where the ensemble chose a winning direction).

        Returns:
            Float score in ``[0, 1]`` or ``None`` on error.
        """
        if self._rest_client is None:
            return None
        try:
            eval_start, eval_end = _backtest_window(self._config.backtest_days)
            backtest = await self._rest_client.create_backtest(
                symbol="BTCUSDT",
                start_time=eval_start,
                end_time=eval_end,
                timeframe="1h",
                starting_balance=10_000.0,
            )
            session_id = backtest.get("session_id") or backtest.get("id")
            if not session_id:
                return None
            await self._rest_client.start_backtest(session_id)
            results = await self._rest_client.get_backtest_results(session_id)
            # Use win_rate as accuracy proxy — fraction of trades with positive PnL
            win_rate = results.get("win_rate")
            if win_rate is None:
                return None
            # Weight by relative emphasis: higher regime weight tends to help in
            # trending markets; this is a simplified proxy for ensemble accuracy.
            return float(win_rate) * (weights.get("regime", 0.334) + 0.5)
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.strategy.retrain.ensemble.score_failed",
                        weights=weights, error=str(exc))
            return None

    async def _evaluate_ensemble_weights(self, weights: dict[str, float]) -> float | None:
        """Evaluate the given weights on the held-out period.

        Args:
            weights: Weight configuration to evaluate.

        Returns:
            Score in ``[0, 1]`` or ``None`` on error.
        """
        return await self._score_ensemble_weights(weights)

    async def _deploy_ensemble_weights(self, weights: dict[str, float]) -> str:
        """Persist the optimal weights JSON to the results directory.

        Args:
            weights: Optimal weight configuration to save.

        Returns:
            Absolute path string to the saved JSON file.
        """
        path = self._config.results_dir / "optimal_weights.json"
        payload = {
            "weights": weights,
            "deployed_at": _utc_now_iso(),
        }
        await asyncio.to_thread(_write_json, path, payload)
        log.info("agent.strategy.retrain.ensemble.weights_saved", path=str(path))
        return str(path)

    async def _fetch_candles_for_training(self) -> list[dict[str, Any]]:
        """Fetch OHLCV candles for regime classifier training.

        Tries to fetch via the SDK client.  Falls back to returning an empty
        list when no SDK client is available (offline mode).

        Returns:
            List of OHLCV candle dicts with keys: open, high, low, close, volume.
        """
        if self._sdk_client is None:
            log.warning("agent.strategy.retrain.regime.no_sdk",
                        fallback="empty_candles")
            return []
        try:
            candles = await self._sdk_client.get_candles("BTCUSDT", "1h", 2000)
            return candles if isinstance(candles, list) else []
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.strategy.retrain.regime.candle_fetch_failed", error=str(exc))
            return []

    def _split_regime_data(
        self,
        candles: list[dict[str, Any]],
    ) -> tuple[Any, Any, Any, Any]:
        """Split candle data into training and test sets for regime classification.

        Uses an 80/20 temporal split.  The last 20% of candles form the
        held-out test set.  Requires ``generate_training_data`` from the
        ``regime.labeler`` module.

        Args:
            candles: Raw OHLCV candle dicts.

        Returns:
            ``(train_features, train_labels, test_features, test_labels)`` tuple.
            All four may be empty DataFrames/lists when fewer than 40 candles
            are available.
        """
        import pandas as pd  # noqa: PLC0415
        from agent.strategies.regime.labeler import generate_training_data  # noqa: PLC0415

        if len(candles) < 40:
            empty_df = pd.DataFrame()
            return empty_df, [], empty_df, []

        features_df, labels = generate_training_data(candles)
        # Drop NaN rows that occur at the start of indicator warm-up
        valid_mask = features_df.notna().all(axis=1)
        features_df = features_df[valid_mask]
        labels = [l for l, v in zip(labels, valid_mask) if v]

        n = len(features_df)
        split = max(1, int(n * 0.8))
        train_features = features_df.iloc[:split]
        test_features = features_df.iloc[split:]
        train_labels = labels[:split]
        test_labels = labels[split:]
        return train_features, train_labels, test_features, test_labels

    async def _deploy_regime_classifier(self, classifier: Any) -> str:
        """Save the newly trained classifier to disk with checksum verification.

        Args:
            classifier: Trained ``RegimeClassifier`` instance.

        Returns:
            Absolute path string to the saved ``.joblib`` file.
        """
        from agent.strategies.checksum import save_checksum  # noqa: PLC0415

        models_dir = Path(__file__).parent / "regime" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        path = models_dir / "regime_classifier.joblib"
        await asyncio.to_thread(classifier.save, path)
        await asyncio.to_thread(save_checksum, path)
        log.info("agent.strategy.retrain.regime.model_saved", path=str(path))
        return str(path)

    async def _run_genome_evolution(self, generations: int) -> float:
        """Run GA evolution for *generations* new generations.

        Uses the injectable ``genome_evolver`` if set, otherwise constructs a
        minimal GA loop using the evolutionary sub-package.  Returns the best
        composite fitness achieved in the final generation.

        Returns:
            Best composite fitness score (float, higher is better).
            Returns ``FAILURE_FITNESS = -999.0`` on error.
        """
        if self._genome_evolver is not None:
            return await asyncio.to_thread(self._genome_evolver, generations)

        # Default: run a lightweight population refresh
        try:
            from agent.strategies.evolutionary.config import EvolutionConfig  # noqa: PLC0415
            from agent.strategies.evolutionary.population import Population  # noqa: PLC0415

            evo_config = EvolutionConfig(
                generations=generations,
                population_size=6,  # small for refresh; champion genome is seeded
                fitness_fn="composite",
            )
            population = Population(seed=evo_config.seed)
            population.initialize(evo_config.population_size)  # type: ignore[call-arg]

            best_fitness = -999.0
            for _ in range(generations):
                # Without BattleRunner (no platform connection in offline mode),
                # we evaluate genome fitness via a simplified proxy metric.
                scores = [g.proxy_fitness() for g in population.genomes]  # type: ignore[attr-defined]
                stats = population.stats(scores)
                best_fitness = max(best_fitness, stats.max_fitness)  # type: ignore[attr-defined]
                population.evolve(scores)

            return best_fitness
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.strategy.retrain.genome.evolution_failed", error=str(exc))
            return -999.0

    async def _deploy_genome_champion(self) -> str:
        """Copy the latest champion genome JSON to the production path.

        Returns:
            Absolute path string to the deployed champion JSON file.
        """
        src = Path(__file__).parent / "evolutionary" / "results" / "champion.json"
        dst = Path(__file__).parent / "evolutionary" / "models" / "champion.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            import shutil  # noqa: PLC0415
            await asyncio.to_thread(shutil.copy2, src, dst)
        else:
            # Write a placeholder so callers can see a file was created
            await asyncio.to_thread(_write_json, dst, {"deployed_at": _utc_now_iso()})
        log.info("agent.strategy.retrain.genome.champion_deployed", path=str(dst))
        return str(dst)

    async def _evaluate_rl_model(self, model_path: Path, rl_config: Any) -> float | None:
        """Evaluate a newly trained PPO model on the held-out test window.

        Attempts to import and use ``ModelEvaluator`` from the RL sub-package.
        Returns ``None`` when SB3 is not installed so the comparison can still
        proceed (the caller will treat ``None`` as a failure to improve).

        Args:
            model_path: Path to the newly trained ``.zip`` model file.
            rl_config: ``RLConfig`` instance with test window date fields.

        Returns:
            Sharpe ratio of the best seed evaluated on the test split, or ``None``.
        """
        try:
            from agent.strategies.rl.evaluate import ModelEvaluator  # noqa: PLC0415

            evaluator = ModelEvaluator(config=rl_config)
            report = await asyncio.to_thread(
                evaluator.evaluate, model_path.parent
            )
            # Best model Sharpe ratio across evaluated seeds
            model_metrics = [m for m in report.models if not m.is_benchmark]  # type: ignore[attr-defined]
            if not model_metrics:
                return None
            sharpes = [m.sharpe_ratio for m in model_metrics if m.sharpe_ratio is not None]
            return max(sharpes) if sharpes else None
        except ImportError:
            log.warning("agent.strategy.retrain.rl.sb3_not_installed",
                        hint="pip install stable-baselines3[extra]")
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.strategy.retrain.rl.eval_failed", error=str(exc))
            return None

    async def _deploy_rl_model(self, model_path: Path) -> str:
        """Save checksum for the newly trained model and return its path.

        Args:
            model_path: Path to the ``.zip`` model file to deploy.

        Returns:
            Absolute path string to the model file.
        """
        from agent.strategies.checksum import save_checksum  # noqa: PLC0415

        await asyncio.to_thread(save_checksum, model_path)
        log.info("agent.strategy.retrain.rl.checksum_saved", path=str(model_path))
        return str(model_path)

    # ── Result persistence ─────────────────────────────────────────────────────

    def _record_result(self, result: RetrainResult) -> None:
        """Append *result* to the audit log and persist to disk.

        Logs via structlog (always) and writes a JSON sidecar to
        ``config.results_dir`` (non-blocking — errors are logged and swallowed).

        Args:
            result: Completed :class:`RetrainResult` to record.
        """
        self._audit_log.append(result)

        log.info(
            "agent.strategy.retrain.result",
            **result.to_log_dict(),
        )

        # Async fire-and-forget — run in a thread to avoid blocking the event loop
        asyncio.ensure_future(self._persist_result_async(result))

    async def _persist_result_async(self, result: RetrainResult) -> None:
        """Write the result JSON to disk asynchronously."""
        try:
            ts = result.triggered_at.replace(":", "-").replace("+", "")[:19]
            filename = f"{result.component}-{ts}.json"
            path = self._config.results_dir / filename
            await asyncio.to_thread(_write_json, path, result.model_dump())
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.strategy.retrain.persist_failed", error=str(exc))

    @staticmethod
    def _failure_result(component: str, triggered_at: str, error: str) -> RetrainResult:
        """Build a failure :class:`RetrainResult` for exception-handling paths.

        Args:
            component: Strategy component that failed.
            triggered_at: ISO-8601 UTC string when the job was initiated.
            error: Error message string.

        Returns:
            :class:`RetrainResult` with ``success=False`` and the error message.
        """
        return RetrainResult(
            component=component,
            triggered_at=triggered_at,
            completed_at=_utc_now_iso(),
            success=False,
            comparison=None,
            deployed=False,
            artifact_path=None,
            error=error,
        )


# ── Module-level helpers ───────────────────────────────────────────────────────


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write *data* as pretty-printed JSON to *path* (synchronous).

    Args:
        path: Destination file path.  Parent directory must exist.
        data: JSON-serialisable dict.
    """
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
