"""Unit tests for TrainingRunService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.training.tracker import TrainingRunService


def _make_service(repo=None):
    if repo is None:
        repo = AsyncMock()
    return TrainingRunService(repo)


def _make_run(run_id=None, status="running", episodes=0):
    r = MagicMock()
    r.id = run_id or uuid4()
    r.status = status
    r.episodes_completed = episodes
    r.episodes_total = None
    r.config = {}
    r.started_at = MagicMock()
    r.completed_at = None
    r.aggregate_stats = None
    r.learning_curve = None
    return r


def _make_episode(ep_num=1, roi=5.0, sharpe=1.0, reward=100.0):
    e = MagicMock()
    e.episode_number = ep_num
    e.metrics = {"roi_pct": roi, "sharpe_ratio": sharpe, "reward_sum": reward}
    e.created_at = MagicMock()
    return e


async def test_register_run():
    """register_run delegates to repo.create_run."""
    repo = AsyncMock()
    run = _make_run()
    repo.create_run.return_value = run
    service = _make_service(repo)

    result = await service.register_run(uuid4(), uuid4(), {"lr": 0.001})
    assert result == run
    repo.create_run.assert_called_once()


async def test_record_episode():
    """record_episode delegates to repo.add_episode."""
    repo = AsyncMock()
    ep = _make_episode()
    repo.add_episode.return_value = ep
    service = _make_service(repo)

    result = await service.record_episode(uuid4(), 1, metrics={"roi_pct": 5.0})
    assert result == ep


async def test_complete_run_with_episodes():
    """complete_run computes aggregate stats from episodes."""
    repo = AsyncMock()
    episodes = [_make_episode(i, roi=i * 2.0) for i in range(1, 6)]
    repo.get_episodes.return_value = episodes
    completed = _make_run(status="completed")
    repo.complete_run.return_value = completed
    service = _make_service(repo)

    result = await service.complete_run(uuid4())
    assert result.status == "completed"
    # Verify aggregate_stats was computed and passed
    call_args = repo.complete_run.call_args
    assert call_args.args[1] is not None  # aggregate_stats
    assert call_args.args[2] is not None  # learning_curve


async def test_complete_run_no_episodes():
    """complete_run with no episodes still completes."""
    repo = AsyncMock()
    repo.get_episodes.return_value = []
    completed = _make_run(status="completed")
    repo.complete_run.return_value = completed
    service = _make_service(repo)

    result = await service.complete_run(uuid4())
    assert result.status == "completed"


async def test_list_runs():
    """list_runs delegates to repo."""
    repo = AsyncMock()
    runs = [_make_run() for _ in range(3)]
    repo.list_runs.return_value = runs
    service = _make_service(repo)

    result = await service.list_runs(uuid4(), status="running")
    assert len(result) == 3


async def test_get_learning_curve():
    """get_learning_curve computes raw + smoothed values."""
    repo = AsyncMock()
    episodes = [_make_episode(i, roi=float(i * 10)) for i in range(1, 11)]
    repo.get_episodes.return_value = episodes
    service = _make_service(repo)

    curve = await service.get_learning_curve(uuid4(), metric="roi_pct", window=3)
    assert len(curve["raw_values"]) == 10
    assert len(curve["smoothed_values"]) == 10
    assert curve["metric"] == "roi_pct"
    assert curve["window"] == 3
    # Smoothed values should differ from raw (rolling mean)
    assert curve["smoothed_values"][0] == curve["raw_values"][0]  # First value same


async def test_compare_runs():
    """compare_runs returns comparison data."""
    repo = AsyncMock()
    runs = [_make_run() for _ in range(2)]
    for r in runs:
        r.aggregate_stats = {"avg_roi_pct": 5.0}
        r.started_at.isoformat.return_value = "2026-03-18T00:00:00"
        r.completed_at = None
    repo.get_runs_by_ids.return_value = runs
    service = _make_service(repo)

    result = await service.compare_runs([uuid4(), uuid4()])
    assert len(result) == 2


def test_rolling_mean():
    """Rolling mean computation is correct."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = TrainingRunService._rolling_mean(values, 3)
    assert result[0] == 10.0  # only 1 value
    assert result[1] == 15.0  # avg(10, 20)
    assert result[2] == 20.0  # avg(10, 20, 30)
    assert result[3] == 30.0  # avg(20, 30, 40)
    assert result[4] == 40.0  # avg(30, 40, 50)


def test_rolling_mean_empty():
    """Rolling mean of empty list returns empty."""
    assert TrainingRunService._rolling_mean([], 5) == []


def test_aggregate_stats():
    """Aggregate stats computation is correct."""
    metrics = [
        {"roi_pct": 10, "sharpe_ratio": 1.5, "max_drawdown_pct": 5, "reward_sum": 100},
        {"roi_pct": -2, "sharpe_ratio": 0.3, "max_drawdown_pct": 8, "reward_sum": 50},
        {"roi_pct": 6, "sharpe_ratio": 1.0, "max_drawdown_pct": 3, "reward_sum": 80},
    ]
    stats = TrainingRunService._compute_aggregate_stats(metrics)
    assert stats["total_episodes"] == 3
    assert abs(stats["avg_roi_pct"] - (10 - 2 + 6) / 3) < 0.01
    assert stats["best_roi_pct"] == 10.0
    assert stats["worst_roi_pct"] == -2.0
