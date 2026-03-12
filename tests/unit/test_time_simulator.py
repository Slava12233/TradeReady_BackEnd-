"""Unit tests for src.backtesting.time_simulator.TimeSimulator."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.time_simulator import TimeSimulator


@pytest.fixture
def sim() -> TimeSimulator:
    """A simulator covering 10 minutes with 1-minute intervals (10 steps)."""
    return TimeSimulator(
        start_time=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        interval_seconds=60,
    )


def test_step_advances_by_interval(sim: TimeSimulator) -> None:
    t = sim.step()
    assert t == datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    assert sim.current_step == 1


def test_step_does_not_exceed_end_time() -> None:
    sim = TimeSimulator(
        start_time=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC),
        interval_seconds=60,
    )
    # total_steps = 0 since 30s < 60s interval
    assert sim.total_steps == 0
    assert sim.is_complete


def test_is_complete_at_end(sim: TimeSimulator) -> None:
    for _ in range(10):
        sim.step()
    assert sim.is_complete
    assert sim.current_step == 10


def test_remaining_steps_calculation(sim: TimeSimulator) -> None:
    assert sim.remaining_steps == 10
    sim.step()
    assert sim.remaining_steps == 9
    for _ in range(9):
        sim.step()
    assert sim.remaining_steps == 0


def test_progress_pct_accurate(sim: TimeSimulator) -> None:
    assert sim.progress_pct == Decimal("0.00")
    for _ in range(5):
        sim.step()
    assert sim.progress_pct == Decimal("50.00")
    for _ in range(5):
        sim.step()
    assert sim.progress_pct == Decimal("100.00")


def test_step_batch_advances_n_intervals(sim: TimeSimulator) -> None:
    t = sim.step_batch(3)
    assert sim.current_step == 3
    assert t == datetime(2026, 1, 1, 0, 3, tzinfo=UTC)


def test_step_batch_stops_at_end(sim: TimeSimulator) -> None:
    t = sim.step_batch(20)  # Request more than available
    assert sim.is_complete
    assert sim.current_step == 10
    assert t == datetime(2026, 1, 1, 0, 10, tzinfo=UTC)


def test_step_raises_when_complete(sim: TimeSimulator) -> None:
    sim.step_batch(10)
    with pytest.raises(StopIteration):
        sim.step()


def test_step_batch_raises_when_complete(sim: TimeSimulator) -> None:
    sim.step_batch(10)
    with pytest.raises(StopIteration):
        sim.step_batch(1)


def test_step_batch_invalid_n(sim: TimeSimulator) -> None:
    with pytest.raises(ValueError, match="n >= 1"):
        sim.step_batch(0)


def test_invalid_time_range() -> None:
    with pytest.raises(ValueError, match="must be after"):
        TimeSimulator(
            start_time=datetime(2026, 1, 2, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_invalid_interval() -> None:
    with pytest.raises(ValueError, match="positive"):
        TimeSimulator(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
            interval_seconds=0,
        )


def test_elapsed_simulated(sim: TimeSimulator) -> None:
    assert sim.elapsed_simulated == timedelta(0)
    sim.step_batch(5)
    assert sim.elapsed_simulated == timedelta(minutes=5)


def test_naive_datetime_gets_utc() -> None:
    sim = TimeSimulator(
        start_time=datetime(2026, 1, 1, 0, 0),
        end_time=datetime(2026, 1, 1, 1, 0),
    )
    assert sim.start_time.tzinfo == UTC
    assert sim.end_time.tzinfo == UTC
