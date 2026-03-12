"""Virtual clock that advances through a historical time range.

The ``TimeSimulator`` steps forward by a fixed interval (default 60 s),
tracking progress and ensuring the clock never exceeds ``end_time``.
All times are UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal


class TimeSimulator:
    """Simulates the passage of time over a historical period.

    Args:
        start_time:       Period start (inclusive, UTC).
        end_time:         Period end (inclusive, UTC).
        interval_seconds: Seconds per step (default 60 = 1-minute candles).
    """

    def __init__(
        self,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int = 60,
    ) -> None:
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=UTC)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=UTC)
        if end_time <= start_time:
            msg = f"end_time ({end_time}) must be after start_time ({start_time})"
            raise ValueError(msg)
        if interval_seconds <= 0:
            msg = f"interval_seconds must be positive, got {interval_seconds}"
            raise ValueError(msg)

        self._start_time = start_time
        self._end_time = end_time
        self._interval = timedelta(seconds=interval_seconds)
        self._interval_seconds = interval_seconds
        self._current_time = start_time
        self._current_step = 0

        total_seconds = (end_time - start_time).total_seconds()
        self._total_steps = int(total_seconds // interval_seconds)

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def current_time(self) -> datetime:
        """Current virtual clock position (UTC)."""
        return self._current_time

    @property
    def start_time(self) -> datetime:
        """Period start time."""
        return self._start_time

    @property
    def end_time(self) -> datetime:
        """Period end time."""
        return self._end_time

    @property
    def interval_seconds(self) -> int:
        """Seconds per step."""
        return self._interval_seconds

    @property
    def current_step(self) -> int:
        """Number of steps completed so far."""
        return self._current_step

    @property
    def total_steps(self) -> int:
        """Total number of steps in the time range."""
        return self._total_steps

    @property
    def is_complete(self) -> bool:
        """``True`` when all steps have been consumed."""
        return self._current_step >= self._total_steps

    @property
    def progress_pct(self) -> Decimal:
        """Completion percentage (0–100) with 2-decimal precision."""
        if self._total_steps == 0:
            return Decimal("100.00")
        pct = (Decimal(self._current_step) / Decimal(self._total_steps)) * Decimal("100")
        return pct.quantize(Decimal("0.01"))

    @property
    def elapsed_simulated(self) -> timedelta:
        """Simulated time elapsed since start."""
        return self._current_time - self._start_time

    @property
    def remaining_steps(self) -> int:
        """Number of steps left until completion."""
        return max(0, self._total_steps - self._current_step)

    # ── Methods ──────────────────────────────────────────────────────────────

    def step(self) -> datetime:
        """Advance the clock by one interval.

        Returns:
            The new ``current_time`` after stepping.

        Raises:
            StopIteration: If the simulator is already complete.
        """
        if self.is_complete:
            raise StopIteration("TimeSimulator has reached end_time")

        next_time = self._current_time + self._interval
        # Clamp to end_time so we never overshoot.
        if next_time > self._end_time:
            next_time = self._end_time

        self._current_time = next_time
        self._current_step += 1
        return self._current_time

    def step_batch(self, n: int) -> datetime:
        """Advance the clock by up to *n* intervals.

        Stops early if end_time is reached before *n* steps are taken.

        Args:
            n: Number of steps to advance (must be >= 1).

        Returns:
            The new ``current_time`` after stepping.

        Raises:
            ValueError: If *n* < 1.
            StopIteration: If the simulator is already complete before stepping.
        """
        if n < 1:
            msg = f"step_batch requires n >= 1, got {n}"
            raise ValueError(msg)
        if self.is_complete:
            raise StopIteration("TimeSimulator has reached end_time")

        for _ in range(n):
            if self.is_complete:
                break
            self.step()

        return self._current_time
