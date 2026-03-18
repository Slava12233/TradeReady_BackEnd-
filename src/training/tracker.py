"""Training run service — business logic for RL/Gym training observation.

Provides registration, episode tracking, learning curve computation,
and cross-run comparison for training runs reported by the Gym wrapper.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import structlog

from src.database.models import TrainingEpisode, TrainingRun
from src.database.repositories.training_repo import TrainingRunRepository

logger = structlog.get_logger(__name__)


class TrainingRunService:
    """Business logic for training run observation.

    Args:
        repo: A :class:`TrainingRunRepository` wired to the current session.
    """

    def __init__(self, repo: TrainingRunRepository) -> None:
        self._repo = repo

    async def register_run(
        self,
        account_id: UUID,
        run_id: UUID,
        config: dict[str, Any] | None = None,
        strategy_id: UUID | None = None,
    ) -> TrainingRun:
        """Register a new training run (called by Gym wrapper on first episode).

        Args:
            account_id: Owner account.
            run_id: Client-provided run UUID.
            config: Training configuration dict.
            strategy_id: Optional linked strategy.

        Returns:
            The created TrainingRun.
        """
        return await self._repo.create_run(run_id, account_id, config, strategy_id)

    async def record_episode(
        self,
        run_id: UUID,
        episode_number: int,
        session_id: UUID | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> TrainingEpisode:
        """Record a completed training episode.

        Args:
            run_id: Training run UUID.
            episode_number: Sequential episode number.
            session_id: Optional backtest session ID.
            metrics: Episode metrics (roi_pct, sharpe, etc.).

        Returns:
            The created TrainingEpisode.
        """
        return await self._repo.add_episode(run_id, episode_number, session_id, metrics)

    async def complete_run(self, run_id: UUID) -> TrainingRun | None:
        """Complete a training run and compute aggregate stats.

        Fetches all episodes, computes aggregate statistics and learning
        curve data, then marks the run as completed.

        Args:
            run_id: Training run UUID.

        Returns:
            The completed TrainingRun, or None if not found.
        """
        episodes = await self._repo.get_episodes(run_id)
        if not episodes:
            return await self._repo.complete_run(run_id)

        episode_metrics = [ep.metrics for ep in episodes if ep.metrics]

        # Compute aggregate stats
        aggregate_stats = self._compute_aggregate_stats(episode_metrics)

        # Compute learning curve
        learning_curve = self._compute_learning_curve(episode_metrics)

        return await self._repo.complete_run(run_id, aggregate_stats, learning_curve)

    async def get_run(self, run_id: UUID) -> TrainingRun | None:
        """Get a training run by ID."""
        return await self._repo.get_run(run_id)

    async def get_episodes(
        self,
        run_id: UUID,
        *,
        limit: int = 1000,
        offset: int = 0,
    ) -> Sequence[TrainingEpisode]:
        """Get episodes for a training run."""
        return await self._repo.get_episodes(run_id, limit=limit, offset=offset)

    async def list_runs(
        self,
        account_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[TrainingRun]:
        """List training runs for an account."""
        return await self._repo.list_runs(account_id, status=status, limit=limit, offset=offset)

    async def get_learning_curve(
        self,
        run_id: UUID,
        metric: str = "roi_pct",
        window: int = 10,
    ) -> dict[str, Any]:
        """Get learning curve data for a training run.

        Args:
            run_id: Training run UUID.
            metric: Metric to plot (e.g. roi_pct, sharpe_ratio, reward_sum).
            window: Rolling mean window size for smoothing.

        Returns:
            Dict with episode_numbers, raw_values, smoothed_values, metric, window.
        """
        episodes = await self._repo.get_episodes(run_id)
        episode_numbers: list[int] = []
        raw_values: list[float] = []

        for ep in episodes:
            if ep.metrics and metric in ep.metrics:
                episode_numbers.append(ep.episode_number)
                raw_values.append(float(ep.metrics[metric]))

        smoothed = self._rolling_mean(raw_values, window) if raw_values else []

        return {
            "episode_numbers": episode_numbers,
            "raw_values": raw_values,
            "smoothed_values": smoothed,
            "metric": metric,
            "window": window,
        }

    async def compare_runs(self, run_ids: list[UUID]) -> list[dict[str, Any]]:
        """Compare multiple training runs by their aggregate stats.

        Args:
            run_ids: List of run UUIDs to compare.

        Returns:
            List of run comparison dicts.
        """
        runs = await self._repo.get_runs_by_ids(run_ids)
        return [
            {
                "run_id": str(run.id),
                "status": run.status,
                "episodes_completed": run.episodes_completed,
                "aggregate_stats": run.aggregate_stats,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
            for run in runs
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_aggregate_stats(episode_metrics: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate statistics from episode metrics."""
        if not episode_metrics:
            return {}

        rois = [float(m.get("roi_pct", 0)) for m in episode_metrics]
        sharpes = [float(m.get("sharpe_ratio", 0)) for m in episode_metrics if m.get("sharpe_ratio") is not None]
        drawdowns = [float(m.get("max_drawdown_pct", 0)) for m in episode_metrics]
        rewards = [float(m.get("reward_sum", 0)) for m in episode_metrics if m.get("reward_sum") is not None]

        stats: dict[str, Any] = {
            "total_episodes": len(episode_metrics),
            "avg_roi_pct": round(sum(rois) / len(rois), 4) if rois else 0,
            "best_roi_pct": round(max(rois), 4) if rois else 0,
            "worst_roi_pct": round(min(rois), 4) if rois else 0,
            "avg_sharpe": round(sum(sharpes) / len(sharpes), 4) if sharpes else None,
            "avg_max_drawdown_pct": round(sum(drawdowns) / len(drawdowns), 4) if drawdowns else 0,
        }
        if rewards:
            stats["avg_reward_sum"] = round(sum(rewards) / len(rewards), 4)
            stats["best_reward_sum"] = round(max(rewards), 4)

        return stats

    @staticmethod
    def _compute_learning_curve(episode_metrics: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute learning curve data from episode metrics."""
        roi_curve = [float(m.get("roi_pct", 0)) for m in episode_metrics]
        reward_curve = [float(m.get("reward_sum", 0)) for m in episode_metrics if m.get("reward_sum") is not None]

        return {
            "roi_pct": roi_curve,
            "reward_sum": reward_curve if reward_curve else None,
        }

    @staticmethod
    def _rolling_mean(values: list[float], window: int) -> list[float]:
        """Compute rolling mean with the given window size."""
        if not values or window <= 0:
            return []
        result: list[float] = []
        for i in range(len(values)):
            start = max(0, i - window + 1)
            window_vals = values[start : i + 1]
            result.append(round(sum(window_vals) / len(window_vals), 4))
        return result
