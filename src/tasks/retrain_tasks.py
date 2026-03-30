"""Celery tasks for automated ML strategy retraining via :class:`RetrainOrchestrator`.

Five tasks are registered here and available for manual trigger or Celery beat
scheduling.  Each task bridges the sync Celery boundary to the async
``RetrainOrchestrator`` via ``asyncio.run()``.

Tasks
-----

* :func:`run_retraining_cycle` — master task; runs all overdue retraining jobs
  concurrently via ``RetrainOrchestrator.run_scheduled_cycle()``.

* :func:`retrain_ensemble` — ensemble weights only; calls
  ``RetrainOrchestrator.retrain_ensemble()``.

* :func:`retrain_regime` — regime classifier only; calls
  ``RetrainOrchestrator.retrain_regime()``.

* :func:`retrain_genome` — genome population only; calls
  ``RetrainOrchestrator.retrain_genome()``.

* :func:`retrain_rl` — PPO RL model only; calls
  ``RetrainOrchestrator.retrain_rl()``.

All tasks use the ``ml_training`` queue (separate from the default queue) so
long-running ML jobs do not block platform-critical tasks like the limit order
monitor or portfolio snapshots.  The worker processing ``ml_training`` can be
scaled independently:

    celery -A src.tasks.celery_app worker --loglevel=info -Q ml_training

Design notes
------------
* ``soft_time_limit=3600`` (1 hour), ``time_limit=3900`` (1 hour + 5 min hard).
  Full PPO retraining can take 30-60 minutes on a CPU worker.  The soft limit
  triggers ``SoftTimeLimitExceeded`` so the task can log the timeout and return
  a partial result dict.  The hard limit ensures the worker process is reclaimed.
* All imports inside async bodies (``# noqa: PLC0415``) to avoid circular imports
  at worker startup.
* ``max_retries=0`` — no automatic retry.  ML jobs are expensive; manual
  re-trigger is preferred over silent auto-retry.
* ``RetrainOrchestrator`` is constructed fresh per invocation so tasks are
  stateless and safe across worker restarts.  The orchestrator's in-memory
  ``ScheduleState`` is discarded after each run; the Celery beat schedule drives
  the actual cadence.

Example (manual trigger)::

    from src.tasks.retrain_tasks import run_retraining_cycle
    result = run_retraining_cycle.delay()
    print(result.get(timeout=3900))

    from src.tasks.retrain_tasks import retrain_ensemble
    result = retrain_ensemble.delay()
    print(result.get(timeout=3900))
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from src.tasks.celery_app import app

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metric helpers
# ---------------------------------------------------------------------------

# Trigger labels: "scheduled" (beat schedule), "drift" (drift detection),
# "manual" (direct task invocation).  All beat-scheduled tasks use "scheduled".
_TRIGGER_SCHEDULED: str = "scheduled"


def _emit_retrain_metrics(
    strategy: str,
    trigger: str,
    duration_seconds: float,
    deployed: bool,
) -> None:
    """Emit Prometheus metrics for a completed retraining job.

    Best-effort — a failure in metric emission must never fail the Celery task.

    Args:
        strategy: Strategy component name (e.g. ``"ensemble"``, ``"regime"``).
        trigger: How the retrain was triggered — ``"scheduled"``, ``"drift"``,
            or ``"manual"``.
        duration_seconds: Wall-clock duration of the retraining job in seconds.
        deployed: Whether the new model passed the A/B gate and was deployed.
    """
    try:
        from agent.metrics import (  # noqa: PLC0415
            agent_retrain_deployed_total,
            agent_retrain_duration_seconds,
            agent_retrain_runs_total,
        )

        agent_retrain_runs_total.labels(strategy=strategy, trigger=trigger).inc()
        agent_retrain_duration_seconds.labels(strategy=strategy).observe(duration_seconds)
        if deployed:
            agent_retrain_deployed_total.labels(strategy=strategy).inc()
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent.task.retrain.metrics_emit_failed", error=str(exc))

# ---------------------------------------------------------------------------
# Task 1: run_retraining_cycle  (master — all overdue components)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.retrain_tasks.run_retraining_cycle",
    bind=False,
    max_retries=0,
    ignore_result=False,
    queue="ml_training",
    soft_time_limit=3600,
    time_limit=3900,
)
def run_retraining_cycle() -> dict[str, Any]:
    """Run all overdue ML retraining jobs via RetrainOrchestrator.

    Delegates to ``RetrainOrchestrator.run_scheduled_cycle()`` which checks
    each component's last-retrain timestamp against its configured interval and
    runs only the overdue components concurrently.

    Returns:
        Summary dict with keys:

        * ``components_run`` — list of component names that were retrained.
        * ``components_deployed`` — list of component names where the new model
          was deployed.
        * ``components_failed`` — list of component names where retraining failed.
        * ``total_run`` — number of components that ran.
        * ``total_deployed`` — number of new models deployed.
        * ``duration_ms`` — wall-clock milliseconds for the full cycle.
    """
    start = time.monotonic()
    logger.info("agent.task.retrain.cycle.start")
    result = asyncio.run(_run_retraining_cycle_async())
    result["duration_ms"] = int((time.monotonic() - start) * 1000)
    logger.info(
        "agent.task.retrain.cycle.complete",
        total_run=result["total_run"],
        total_deployed=result["total_deployed"],
        duration_ms=result["duration_ms"],
    )
    return result


async def _run_retraining_cycle_async() -> dict[str, Any]:
    """Async implementation of the master retraining cycle."""
    from agent.strategies.retrain import RetrainConfig, RetrainOrchestrator  # noqa: PLC0415

    config = RetrainConfig()
    orchestrator = RetrainOrchestrator(config=config)

    retrain_results = await orchestrator.run_scheduled_cycle()

    components_run: list[str] = [r.component for r in retrain_results]
    components_deployed: list[str] = [r.component for r in retrain_results if r.deployed]
    components_failed: list[str] = [r.component for r in retrain_results if not r.success]

    return {
        "components_run": components_run,
        "components_deployed": components_deployed,
        "components_failed": components_failed,
        "total_run": len(components_run),
        "total_deployed": len(components_deployed),
        "results": [r.to_log_dict() for r in retrain_results],
    }


# ---------------------------------------------------------------------------
# Task 2: retrain_ensemble  (ensemble weights only)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.retrain_tasks.retrain_ensemble",
    bind=False,
    max_retries=0,
    ignore_result=False,
    queue="ml_training",
    soft_time_limit=3600,
    time_limit=3900,
)
def retrain_ensemble() -> dict[str, Any]:
    """Retrain and optionally deploy ensemble source weights.

    Runs a backtest grid search over weight configurations and deploys the
    optimal weight vector when it improves ensemble accuracy beyond the
    configured threshold.

    Returns:
        RetrainResult log dict with keys: ``component``, ``triggered_at``,
        ``completed_at``, ``success``, ``deployed``, ``improvement``,
        ``metric``, ``artifact_path``, ``error``, plus ``duration_ms``.
    """
    start = time.monotonic()
    logger.info("agent.task.retrain.ensemble.start")
    result = asyncio.run(_retrain_ensemble_async())
    duration_s = time.monotonic() - start
    result["duration_ms"] = int(duration_s * 1000)
    logger.info(
        "agent.task.retrain.ensemble.complete",
        success=result.get("success"),
        deployed=result.get("deployed"),
        duration_ms=result["duration_ms"],
    )
    _emit_retrain_metrics(
        strategy="ensemble",
        trigger=_TRIGGER_SCHEDULED,
        duration_seconds=duration_s,
        deployed=bool(result.get("deployed")),
    )
    return result


async def _retrain_ensemble_async() -> dict[str, Any]:
    """Async implementation of ensemble weight retraining."""
    from agent.strategies.retrain import RetrainConfig, RetrainOrchestrator  # noqa: PLC0415

    config = RetrainConfig()
    orchestrator = RetrainOrchestrator(config=config)
    retrain_result = await orchestrator.retrain_ensemble()
    return retrain_result.to_log_dict()


# ---------------------------------------------------------------------------
# Task 3: retrain_regime  (regime classifier only)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.retrain_tasks.retrain_regime",
    bind=False,
    max_retries=0,
    ignore_result=False,
    queue="ml_training",
    soft_time_limit=3600,
    time_limit=3900,
)
def retrain_regime() -> dict[str, Any]:
    """Retrain and optionally deploy the regime classifier.

    Fetches recent OHLCV candles, retrains the 6-feature XGBoost/RandomForest
    regime classifier, evaluates held-out accuracy, and deploys the new
    ``.joblib`` model when accuracy improves.

    Returns:
        RetrainResult log dict with keys: ``component``, ``triggered_at``,
        ``completed_at``, ``success``, ``deployed``, ``improvement``,
        ``metric``, ``artifact_path``, ``error``, plus ``duration_ms``.
    """
    start = time.monotonic()
    logger.info("agent.task.retrain.regime.start")
    result = asyncio.run(_retrain_regime_async())
    duration_s = time.monotonic() - start
    result["duration_ms"] = int(duration_s * 1000)
    logger.info(
        "agent.task.retrain.regime.complete",
        success=result.get("success"),
        deployed=result.get("deployed"),
        duration_ms=result["duration_ms"],
    )
    _emit_retrain_metrics(
        strategy="regime",
        trigger=_TRIGGER_SCHEDULED,
        duration_seconds=duration_s,
        deployed=bool(result.get("deployed")),
    )
    return result


async def _retrain_regime_async() -> dict[str, Any]:
    """Async implementation of regime classifier retraining."""
    from agent.strategies.retrain import RetrainConfig, RetrainOrchestrator  # noqa: PLC0415

    config = RetrainConfig()
    orchestrator = RetrainOrchestrator(config=config)
    retrain_result = await orchestrator.retrain_regime()
    return retrain_result.to_log_dict()


# ---------------------------------------------------------------------------
# Task 4: retrain_genome  (genome population only)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.retrain_tasks.retrain_genome",
    bind=False,
    max_retries=0,
    ignore_result=False,
    queue="ml_training",
    soft_time_limit=3600,
    time_limit=3900,
)
def retrain_genome() -> dict[str, Any]:
    """Run new GA generations and optionally deploy the improved champion genome.

    Takes the current champion genome as the seed population, runs
    ``config.genome_refresh_generations`` new GA generations, and deploys the
    new champion when composite fitness improves beyond the configured threshold.

    Returns:
        RetrainResult log dict with keys: ``component``, ``triggered_at``,
        ``completed_at``, ``success``, ``deployed``, ``improvement``,
        ``metric``, ``artifact_path``, ``error``, plus ``duration_ms``.
    """
    start = time.monotonic()
    logger.info("agent.task.retrain.genome.start")
    result = asyncio.run(_retrain_genome_async())
    duration_s = time.monotonic() - start
    result["duration_ms"] = int(duration_s * 1000)
    logger.info(
        "agent.task.retrain.genome.complete",
        success=result.get("success"),
        deployed=result.get("deployed"),
        duration_ms=result["duration_ms"],
    )
    _emit_retrain_metrics(
        strategy="genome",
        trigger=_TRIGGER_SCHEDULED,
        duration_seconds=duration_s,
        deployed=bool(result.get("deployed")),
    )
    return result


async def _retrain_genome_async() -> dict[str, Any]:
    """Async implementation of genome population retraining."""
    from agent.strategies.retrain import RetrainConfig, RetrainOrchestrator  # noqa: PLC0415

    config = RetrainConfig()
    orchestrator = RetrainOrchestrator(config=config)
    retrain_result = await orchestrator.retrain_genome()
    return retrain_result.to_log_dict()


# ---------------------------------------------------------------------------
# Task 5: retrain_rl  (PPO RL model only)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.retrain_tasks.retrain_rl",
    bind=False,
    max_retries=0,
    ignore_result=False,
    queue="ml_training",
    soft_time_limit=3600,
    time_limit=3900,
)
def retrain_rl() -> dict[str, Any]:
    """Retrain the PPO model on a rolling training window and optionally deploy.

    Computes a rolling ``config.rl_training_window_months``-month window ending
    today, runs PPO training, evaluates Sharpe ratio on the held-out period, and
    deploys the new ``.zip`` model when Sharpe improves.

    Returns:
        RetrainResult log dict with keys: ``component``, ``triggered_at``,
        ``completed_at``, ``success``, ``deployed``, ``improvement``,
        ``metric``, ``artifact_path``, ``error``, plus ``duration_ms``.
    """
    start = time.monotonic()
    logger.info("agent.task.retrain.rl.start")
    result = asyncio.run(_retrain_rl_async())
    duration_s = time.monotonic() - start
    result["duration_ms"] = int(duration_s * 1000)
    logger.info(
        "agent.task.retrain.rl.complete",
        success=result.get("success"),
        deployed=result.get("deployed"),
        duration_ms=result["duration_ms"],
    )
    _emit_retrain_metrics(
        strategy="rl",
        trigger=_TRIGGER_SCHEDULED,
        duration_seconds=duration_s,
        deployed=bool(result.get("deployed")),
    )
    return result


async def _retrain_rl_async() -> dict[str, Any]:
    """Async implementation of PPO RL model retraining."""
    from agent.strategies.retrain import RetrainConfig, RetrainOrchestrator  # noqa: PLC0415

    config = RetrainConfig()
    orchestrator = RetrainOrchestrator(config=config)
    retrain_result = await orchestrator.retrain_rl()
    return retrain_result.to_log_dict()
