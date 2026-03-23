"""Strategy-level circuit breakers for the ensemble runner.

Tracks per-strategy performance signals and automatically pauses underperforming
strategies by setting a Redis key with an appropriate TTL.  When paused, a
strategy is excluded from the ensemble signal combination for the pause duration.

Three trigger rules (all configurable):

1. **Consecutive losses**: If a strategy produces losing signals 3 or more times
   in a row, it is paused for 24 hours.

2. **Weekly drawdown**: If a strategy's cumulative PnL contribution over the
   last 7 days exceeds a 5 % drawdown threshold, it is paused for 48 hours.

3. **Ensemble accuracy**: If the ensemble consensus is wrong on more than 60 %
   of the most recent 20 signals (tracked globally across all strategies), all
   position sizes are reduced to 25 % of their normal value.

Redis key patterns::

    strategy:circuit:{strategy_name}:{agent_id}   string   — pause sentinel; TTL = pause_seconds
    strategy:losses:{strategy_name}:{agent_id}    list     — LPUSH outcome per step; LTRIM to window
    strategy:weekly_pnl:{strategy_name}:{agent_id} string  — float; cumulative PnL contribution
    strategy:accuracy:{agent_id}                  list     — LPUSH 0/1 per signal; LTRIM to window

All Redis operations are fire-and-forget with exception logging.  A Redis
outage degrades gracefully: ``is_paused()`` returns ``False`` (allow trading)
and ``size_multiplier()`` returns ``1.0`` (normal sizing).

Example usage (inside EnsembleRunner)::

    cb = StrategyCircuitBreaker(redis_client=redis)
    agent_id = "550e8400-..."

    # After determining a signal resulted in a loss:
    await cb.record_loss("rl", agent_id)
    await cb.record_pnl_contribution("rl", agent_id, pnl_pct=-0.02)

    # Check before including in ensemble:
    if await cb.is_paused("rl", agent_id):
        # skip RL source
        ...

    # Reduce sizes if ensemble is inaccurate:
    multiplier = await cb.size_multiplier(agent_id)  # 0.25 or 1.0
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Number of consecutive losses before pausing the strategy.
CONSECUTIVE_LOSS_LIMIT: int = 3

# Pause duration (seconds) triggered by consecutive losses: 24 hours.
CONSECUTIVE_LOSS_PAUSE_SECONDS: int = 24 * 3600

# Maximum weekly drawdown percentage (e.g. 0.05 = 5 %) before pausing.
WEEKLY_DRAWDOWN_THRESHOLD: float = 0.05

# Pause duration (seconds) triggered by weekly drawdown: 48 hours.
WEEKLY_DRAWDOWN_PAUSE_SECONDS: int = 48 * 3600

# TTL for the weekly PnL accumulator key (7 days + 1 hour buffer).
WEEKLY_PNL_TTL_SECONDS: int = 7 * 24 * 3600 + 3600

# Number of recent ensemble signals to evaluate for accuracy.
ACCURACY_WINDOW: int = 20

# Fraction of wrong signals in the accuracy window that triggers size reduction.
ACCURACY_WRONG_THRESHOLD: float = 0.60

# Size multiplier applied to all positions when ensemble accuracy is poor.
LOW_ACCURACY_SIZE_MULTIPLIER: float = 0.25

# TTL for the accuracy list (7 days; signals are short-lived).
ACCURACY_LIST_TTL_SECONDS: int = 7 * 24 * 3600

# TTL for the consecutive-loss list (48 hours; kept longer than worst pause).
LOSSES_LIST_TTL_SECONDS: int = 48 * 3600 + 3600


class StrategyCircuitBreaker:
    """Per-strategy circuit breaker backed by Redis.

    Tracks consecutive losses, weekly PnL drawdown per strategy, and overall
    ensemble accuracy.  Triggers automatic pauses stored as Redis keys with TTL.

    All public methods are async and will catch ``RedisError`` internally,
    returning safe defaults to prevent a Redis outage from blocking trading.

    Args:
        redis_client: An ``redis.asyncio.Redis`` instance (or compatible).
            The client's connection pool is shared — this class never closes it.
        consecutive_loss_limit: Number of consecutive losses before pausing.
            Defaults to :data:`CONSECUTIVE_LOSS_LIMIT` (3).
        weekly_drawdown_threshold: Maximum allowable weekly PnL drawdown as a
            positive fraction (e.g. ``0.05`` = 5 %).  Defaults to
            :data:`WEEKLY_DRAWDOWN_THRESHOLD` (0.05).
        accuracy_wrong_threshold: Fraction of recent signals that must be wrong
            before triggering ensemble-wide size reduction.  Defaults to
            :data:`ACCURACY_WRONG_THRESHOLD` (0.60).
        accuracy_window: Number of recent signals to evaluate for accuracy.
            Defaults to :data:`ACCURACY_WINDOW` (20).
    """

    def __init__(
        self,
        redis_client: Any,  # noqa: ANN401
        *,
        consecutive_loss_limit: int = CONSECUTIVE_LOSS_LIMIT,
        weekly_drawdown_threshold: float = WEEKLY_DRAWDOWN_THRESHOLD,
        accuracy_wrong_threshold: float = ACCURACY_WRONG_THRESHOLD,
        accuracy_window: int = ACCURACY_WINDOW,
    ) -> None:
        self._redis = redis_client
        self._consecutive_loss_limit = consecutive_loss_limit
        self._weekly_drawdown_threshold = weekly_drawdown_threshold
        self._accuracy_wrong_threshold = accuracy_wrong_threshold
        self._accuracy_window = accuracy_window

    # ── Redis key helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _pause_key(strategy_name: str, agent_id: str) -> str:
        """Redis key for the pause sentinel.

        Args:
            strategy_name: Source name (e.g. ``"rl"``, ``"evolved"``, ``"regime"``).
            agent_id: Agent UUID string.

        Returns:
            Redis key string.
        """
        return f"strategy:circuit:{strategy_name}:{agent_id}"

    @staticmethod
    def _losses_key(strategy_name: str, agent_id: str) -> str:
        """Redis key for the consecutive-loss list.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.

        Returns:
            Redis key string.
        """
        return f"strategy:losses:{strategy_name}:{agent_id}"

    @staticmethod
    def _weekly_pnl_key(strategy_name: str, agent_id: str) -> str:
        """Redis key for the rolling weekly PnL accumulator.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.

        Returns:
            Redis key string.
        """
        return f"strategy:weekly_pnl:{strategy_name}:{agent_id}"

    @staticmethod
    def _accuracy_key(agent_id: str) -> str:
        """Redis key for the ensemble accuracy list.

        Args:
            agent_id: Agent UUID string.

        Returns:
            Redis key string.
        """
        return f"strategy:accuracy:{agent_id}"

    # ── Pause management ───────────────────────────────────────────────────────

    async def is_paused(self, strategy_name: str, agent_id: str) -> bool:
        """Check whether a strategy is currently paused.

        Args:
            strategy_name: Source name (``"rl"``, ``"evolved"``, ``"regime"``).
            agent_id: Agent UUID string.

        Returns:
            ``True`` if the strategy is paused (circuit key exists in Redis),
            ``False`` if active or on Redis error (fail-open to allow trading).
        """
        try:
            exists = await self._redis.exists(self._pause_key(strategy_name, agent_id))
            return bool(exists)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.circuit_breaker.is_paused.error",
                strategy=strategy_name,
                agent_id=agent_id,
                error=str(exc),
            )
            return False  # Fail-open: don't block trading on Redis outage.

    async def pause(
        self,
        strategy_name: str,
        agent_id: str,
        pause_seconds: int,
        reason: str,
    ) -> None:
        """Pause a strategy by setting a Redis key with TTL.

        Args:
            strategy_name: Source name to pause.
            agent_id: Agent UUID string.
            pause_seconds: TTL for the pause key in seconds.
            reason: Human-readable reason string stored as the key value.

        Returns:
            None.  Errors are logged and swallowed.
        """
        key = self._pause_key(strategy_name, agent_id)
        payload = json.dumps(
            {
                "reason": reason,
                "paused_at": time.time(),
                "pause_seconds": pause_seconds,
            }
        )
        try:
            await self._redis.set(key, payload, ex=pause_seconds)
            log.warning(
                "agent.strategy.circuit_breaker.paused",
                strategy=strategy_name,
                agent_id=agent_id,
                reason=reason,
                pause_seconds=pause_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "agent.strategy.circuit_breaker.pause_failed",
                strategy=strategy_name,
                agent_id=agent_id,
                error=str(exc),
            )

    async def resume(self, strategy_name: str, agent_id: str) -> None:
        """Manually resume a paused strategy by deleting the pause sentinel.

        Normally strategies auto-resume when the Redis TTL expires.  Use this
        only for operator-initiated manual overrides.

        Args:
            strategy_name: Source name to resume.
            agent_id: Agent UUID string.
        """
        try:
            await self._redis.delete(self._pause_key(strategy_name, agent_id))
            log.info(
                "agent.strategy.circuit_breaker.resumed",
                strategy=strategy_name,
                agent_id=agent_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "agent.strategy.circuit_breaker.resume_failed",
                strategy=strategy_name,
                agent_id=agent_id,
                error=str(exc),
            )

    async def get_pause_info(
        self, strategy_name: str, agent_id: str
    ) -> dict[str, Any] | None:
        """Return the pause payload if paused, else ``None``.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.

        Returns:
            Dict with ``reason``, ``paused_at``, ``pause_seconds`` if paused,
            or ``None`` if active or on Redis error.
        """
        try:
            raw = await self._redis.get(self._pause_key(strategy_name, agent_id))
            if raw is None:
                return None
            return json.loads(raw)  # type: ignore[no-any-return]
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.circuit_breaker.get_pause_info.error",
                strategy=strategy_name,
                error=str(exc),
            )
            return None

    # ── Loss tracking ──────────────────────────────────────────────────────────

    async def record_loss(self, strategy_name: str, agent_id: str) -> None:
        """Record a losing signal and trigger a pause if the threshold is reached.

        Appends ``"loss"`` to the strategy's loss list and keeps only the
        :attr:`_consecutive_loss_limit` most recent entries.  If all entries in
        the trimmed window are ``"loss"``, the strategy is paused for
        :data:`CONSECUTIVE_LOSS_PAUSE_SECONDS`.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.
        """
        await self._record_outcome(strategy_name, agent_id, outcome="loss")

    async def record_win(self, strategy_name: str, agent_id: str) -> None:
        """Record a winning signal and reset the consecutive-loss window.

        Appends ``"win"`` to the loss list so the streak is broken.  Any
        previously accumulated consecutive losses become irrelevant once a win
        is recorded.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.
        """
        await self._record_outcome(strategy_name, agent_id, outcome="win")

    async def _record_outcome(
        self,
        strategy_name: str,
        agent_id: str,
        outcome: str,
    ) -> None:
        """Append an outcome to the loss list and check the consecutive threshold.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.
            outcome: ``"loss"`` or ``"win"``.
        """
        key = self._losses_key(strategy_name, agent_id)
        limit = self._consecutive_loss_limit
        try:
            pipe = self._redis.pipeline()
            pipe.lpush(key, outcome)
            pipe.ltrim(key, 0, limit - 1)  # keep only the most recent `limit` entries
            pipe.expire(key, LOSSES_LIST_TTL_SECONDS)
            await pipe.execute()

            # Read back the trimmed list to check for consecutive losses.
            entries: list[bytes | str] = await self._redis.lrange(key, 0, limit - 1)
            decoded = [e.decode() if isinstance(e, bytes) else e for e in entries]

            if len(decoded) >= limit and all(e == "loss" for e in decoded):
                await self.pause(
                    strategy_name,
                    agent_id,
                    pause_seconds=CONSECUTIVE_LOSS_PAUSE_SECONDS,
                    reason=f"consecutive_losses:{limit}",
                )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.circuit_breaker.record_outcome.error",
                strategy=strategy_name,
                agent_id=agent_id,
                outcome=outcome,
                error=str(exc),
            )

    async def consecutive_loss_count(self, strategy_name: str, agent_id: str) -> int:
        """Return the current consecutive-loss streak length.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.

        Returns:
            Number of consecutive trailing losses.  Returns ``0`` on Redis error.
        """
        key = self._losses_key(strategy_name, agent_id)
        try:
            entries: list[bytes | str] = await self._redis.lrange(
                key, 0, self._consecutive_loss_limit - 1
            )
            decoded = [e.decode() if isinstance(e, bytes) else e for e in entries]
            count = 0
            for e in decoded:
                if e == "loss":
                    count += 1
                else:
                    break
            return count
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.circuit_breaker.consecutive_loss_count.error",
                strategy=strategy_name,
                error=str(exc),
            )
            return 0

    # ── Weekly PnL drawdown tracking ───────────────────────────────────────────

    async def record_pnl_contribution(
        self,
        strategy_name: str,
        agent_id: str,
        pnl_pct: float,
    ) -> None:
        """Accumulate a strategy's PnL contribution and trigger a pause on drawdown.

        PnL is stored as a float string in Redis with a 7-day TTL.  Negative
        values accumulate drawdown; once cumulative drawdown exceeds
        :attr:`_weekly_drawdown_threshold`, the strategy is paused for
        :data:`WEEKLY_DRAWDOWN_PAUSE_SECONDS` (48 hours).

        The weekly accumulator resets naturally when the key expires after 7
        days, starting a fresh measurement window.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.
            pnl_pct: PnL contribution as a fraction (e.g. ``-0.02`` = −2 %).
                Positive values are gains; negative values are losses.
        """
        key = self._weekly_pnl_key(strategy_name, agent_id)
        try:
            # Use INCRBYFLOAT to atomically accumulate. Set TTL only on creation
            # (NX flag not available for EXPIRE, so we use a pipeline with EXISTS check).
            new_val_raw = await self._redis.incrbyfloat(key, pnl_pct)
            new_val = float(new_val_raw)

            # Refresh TTL on every write to keep the 7-day rolling window.
            await self._redis.expire(key, WEEKLY_PNL_TTL_SECONDS)

            log.debug(
                "agent.strategy.circuit_breaker.pnl_contribution",
                strategy=strategy_name,
                agent_id=agent_id,
                pnl_pct=pnl_pct,
                cumulative_pnl=new_val,
            )

            # Trigger pause if cumulative drawdown exceeds threshold.
            # Only trigger on negative PnL (drawdown); positive PnL is fine.
            if new_val < -self._weekly_drawdown_threshold:
                already_paused = await self.is_paused(strategy_name, agent_id)
                if not already_paused:
                    await self.pause(
                        strategy_name,
                        agent_id,
                        pause_seconds=WEEKLY_DRAWDOWN_PAUSE_SECONDS,
                        reason=f"weekly_drawdown:{new_val:.4f}",
                    )

        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.circuit_breaker.record_pnl.error",
                strategy=strategy_name,
                agent_id=agent_id,
                pnl_pct=pnl_pct,
                error=str(exc),
            )

    async def get_weekly_pnl(self, strategy_name: str, agent_id: str) -> float:
        """Return the accumulated weekly PnL contribution for a strategy.

        Args:
            strategy_name: Source name.
            agent_id: Agent UUID string.

        Returns:
            Cumulative PnL as a float.  Returns ``0.0`` if the key is absent or
            on Redis error.
        """
        key = self._weekly_pnl_key(strategy_name, agent_id)
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return 0.0
            return float(raw)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.circuit_breaker.get_weekly_pnl.error",
                strategy=strategy_name,
                error=str(exc),
            )
            return 0.0

    # ── Ensemble accuracy tracking ─────────────────────────────────────────────

    async def record_signal_outcome(
        self,
        agent_id: str,
        correct: bool,
    ) -> None:
        """Record whether a recent ensemble signal was correct.

        Appends ``1`` (correct) or ``0`` (wrong) to the accuracy list and trims
        it to the last :attr:`_accuracy_window` entries.

        Args:
            agent_id: Agent UUID string.
            correct: ``True`` if the consensus signal led to a profitable trade,
                ``False`` if it led to a loss or was mispriced.
        """
        key = self._accuracy_key(agent_id)
        value = "1" if correct else "0"
        try:
            pipe = self._redis.pipeline()
            pipe.lpush(key, value)
            pipe.ltrim(key, 0, self._accuracy_window - 1)
            pipe.expire(key, ACCURACY_LIST_TTL_SECONDS)
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.circuit_breaker.record_signal_outcome.error",
                agent_id=agent_id,
                correct=correct,
                error=str(exc),
            )

    async def ensemble_accuracy(self, agent_id: str) -> float | None:
        """Return the ensemble accuracy over the recent window.

        Args:
            agent_id: Agent UUID string.

        Returns:
            Float in [0.0, 1.0] representing the fraction of correct signals,
            or ``None`` if the window has fewer than :attr:`_accuracy_window`
            entries yet (insufficient data).  Returns ``None`` on Redis error.
        """
        key = self._accuracy_key(agent_id)
        try:
            entries: list[bytes | str] = await self._redis.lrange(
                key, 0, self._accuracy_window - 1
            )
            if len(entries) < self._accuracy_window:
                return None  # Insufficient data.
            decoded = [e.decode() if isinstance(e, bytes) else e for e in entries]
            correct_count = sum(1 for e in decoded if e == "1")
            return correct_count / len(decoded)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.circuit_breaker.ensemble_accuracy.error",
                agent_id=agent_id,
                error=str(exc),
            )
            return None

    async def size_multiplier(self, agent_id: str) -> float:
        """Return the position-size multiplier based on ensemble accuracy.

        When accuracy drops below the threshold (too many wrong signals), returns
        :data:`LOW_ACCURACY_SIZE_MULTIPLIER` (0.25) so all position sizes are
        cut to 25 % of their normal value.

        Returns ``1.0`` when accuracy is acceptable, when there is insufficient
        data to evaluate, or when a Redis error occurs (fail-open).

        Args:
            agent_id: Agent UUID string.

        Returns:
            ``0.25`` if ensemble accuracy is poor, ``1.0`` otherwise.
        """
        accuracy = await self.ensemble_accuracy(agent_id)
        if accuracy is None:
            # Not enough data yet — use normal sizing.
            return 1.0

        wrong_fraction = 1.0 - accuracy
        if wrong_fraction > self._accuracy_wrong_threshold:
            log.warning(
                "agent.strategy.circuit_breaker.size_reduction",
                agent_id=agent_id,
                accuracy=round(accuracy, 4),
                wrong_fraction=round(wrong_fraction, 4),
                multiplier=LOW_ACCURACY_SIZE_MULTIPLIER,
            )
            return LOW_ACCURACY_SIZE_MULTIPLIER

        return 1.0

    # ── Convenience: filter and scale ─────────────────────────────────────────

    async def filter_active_sources(
        self,
        sources: list[str],
        agent_id: str,
    ) -> list[str]:
        """Return the subset of sources that are not currently paused.

        Args:
            sources: List of source names to check (e.g. ``["rl", "evolved", "regime"]``).
            agent_id: Agent UUID string.

        Returns:
            Filtered list of active (non-paused) source names.
        """
        active: list[str] = []
        for source in sources:
            if not await self.is_paused(source, agent_id):
                active.append(source)
        return active

    async def apply_size_multiplier(
        self,
        size_pct: float,
        agent_id: str,
    ) -> float:
        """Scale a base position size by the current ensemble accuracy multiplier.

        Args:
            size_pct: Base position size fraction (e.g. ``0.05`` = 5 %).
            agent_id: Agent UUID string.

        Returns:
            Adjusted size fraction clamped to [0.0, 1.0].
        """
        multiplier = await self.size_multiplier(agent_id)
        adjusted = size_pct * multiplier
        return min(max(adjusted, 0.0), 1.0)
