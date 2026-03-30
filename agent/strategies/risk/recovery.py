"""Drawdown recovery state machine for the AiTradingAgent risk overlay.

After a drawdown event reduces position sizes, this module manages the
graduated return to full trading capacity.  Recovery is gated on three
independent conditions that must each be satisfied in sequence:

1. **ATR normalisation** — market volatility must return to <= 1.5× its
   median before any new positions are taken.  This prevents re-entering
   full-size positions into still-volatile market conditions.

2. **Graduated size ramp** — once ATR normalises, positions are resumed at
   25 % of their base size and scaled up by 25 percentage points per
   qualifying day (0.25 → 0.50 → 0.75 → 1.00).

3. **Equity recovery** — full size (1.0 multiplier) is only permitted after
   the portfolio has recovered at least 50 % of the peak-to-trough drawdown.
   If the equity target is not reached, the ramp pauses at 0.75× until it is.

State is persisted in Redis so that a process restart does not reset
recovery progress.  The key pattern follows the existing convention used by
:mod:`agent.memory.redis_cache`:

    ``agent:recovery:{agent_id}``  (hash, no TTL — persists until cleared)

Typical usage::

    import redis.asyncio as aioredis
    from agent.strategies.risk.recovery import RecoveryManager, RecoveryConfig

    redis_client = aioredis.from_url("redis://localhost:6379")
    manager = RecoveryManager(
        agent_id="my-agent-id",
        redis=redis_client,
    )

    # Called once when size reduction first triggers:
    await manager.start_recovery(
        drawdown_pct=0.12,
        equity_at_trigger=Decimal("88000"),
        peak_equity=Decimal("100000"),
    )

    # On every strategy tick thereafter:
    multiplier = await manager.get_size_multiplier(
        current_atr=atr,
        median_atr=median_atr,
        current_equity=Decimal("90000"),
    )

    # Advance day counter once per calendar day:
    await manager.advance_day(
        current_equity=Decimal("90000"),
        had_loss=False,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import redis.asyncio as aioredis
import structlog
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

#: Redis hash key template for storing recovery state per agent.
_RECOVERY_KEY = "agent:recovery:{agent_id}"

#: ATR normalisation multiplier — current ATR must be below this factor
#: times the median ATR before the scaling ramp can begin.
ATR_NORMALISATION_FACTOR: float = 1.5

#: Size multiplier increment applied per qualifying day during scale-up.
SCALE_STEP: float = 0.25

#: Number of days to ramp from 25 % to 100 % (0.25 → 0.50 → 0.75 → 1.00).
SCALE_DAYS: int = 4

#: Fraction of the drawdown that must be recovered before FULL state is
#: permitted.  E.g. 0.50 means 50 % recovery.
RECOVERY_THRESHOLD: float = 0.50


# ── State enum ────────────────────────────────────────────────────────────────


class RecoveryState(str, Enum):
    """Three-state recovery machine.

    Attributes:
        RECOVERING: Drawdown triggered; waiting for ATR to normalise before
            resuming any trading.
        SCALING_UP: ATR has normalised; graduated size increase is in
            progress (25 % → 50 % → 75 % per qualifying day).
        FULL: Portfolio has recovered ≥ 50 % of the drawdown and the ramp
            has reached 100 %.  Normal trading resumes.
    """

    RECOVERING = "RECOVERING"
    SCALING_UP = "SCALING_UP"
    FULL = "FULL"


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecoveryConfig:
    """Tuning parameters for :class:`RecoveryManager`.

    All attributes have production-safe defaults that match the task spec.
    Create a custom instance only when you need to deviate from defaults.

    Attributes:
        atr_normalisation_factor: Multiplier applied to ``median_atr``.
            Current ATR must fall *below* ``atr_normalisation_factor *
            median_atr`` before the scaling ramp begins.  Default ``1.5``.
        scale_step: Fractional increment applied per qualifying day during
            the SCALING_UP phase.  Default ``0.25`` (4-day ramp to 100 %).
        scale_days: Total number of qualifying days to reach 100 %.
            Default ``4``.
        recovery_threshold: Fraction of the drawdown depth that must be
            recovered before FULL state is allowed.  Default ``0.50``
            (50 % of the drawdown must be erased first).

    Example::

        cfg = RecoveryConfig(atr_normalisation_factor=2.0, scale_step=0.20)
    """

    atr_normalisation_factor: float = ATR_NORMALISATION_FACTOR
    scale_step: float = SCALE_STEP
    scale_days: int = SCALE_DAYS
    recovery_threshold: float = RECOVERY_THRESHOLD

    def __post_init__(self) -> None:
        """Validate configuration values.

        Raises:
            ValueError: If any parameter is outside its valid range.
        """
        if self.atr_normalisation_factor <= 1.0:
            raise ValueError("atr_normalisation_factor must be > 1.0")
        if not (0.0 < self.scale_step <= 1.0):
            raise ValueError("scale_step must be in (0, 1]")
        if self.scale_days < 1:
            raise ValueError("scale_days must be >= 1")
        if not (0.0 < self.recovery_threshold <= 1.0):
            raise ValueError("recovery_threshold must be in (0, 1]")


# ── Snapshot / serialisation ──────────────────────────────────────────────────


@dataclass
class RecoverySnapshot:
    """Point-in-time snapshot of the recovery machine's state.

    All financial values are stored as ``str`` to preserve ``Decimal``
    precision across Redis serialisation.

    Attributes:
        state: Current :class:`RecoveryState`.
        drawdown_pct: Drawdown fraction that triggered recovery (e.g.
            ``0.12`` for 12 %).
        equity_at_trigger: Portfolio equity at the moment recovery was
            triggered (USDT as string).
        peak_equity: Highest equity seen before the drawdown started
            (USDT as string).
        days_scaling: Number of qualifying scale-up days elapsed so far.
            Incremented by :meth:`RecoveryManager.advance_day`.
        current_multiplier: Current position-size multiplier (``0.0`` while
            RECOVERING, ``0.25``–``1.0`` while SCALING_UP or FULL).
        started_at: ISO-8601 UTC timestamp when recovery was initiated.
        last_updated: ISO-8601 UTC timestamp of the last state change.
    """

    state: RecoveryState
    drawdown_pct: float
    equity_at_trigger: str  # Decimal serialised as string
    peak_equity: str  # Decimal serialised as string
    days_scaling: int
    current_multiplier: float
    started_at: str  # ISO-8601
    last_updated: str  # ISO-8601

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def equity_at_trigger_decimal(self) -> Decimal:
        """Equity at trigger as :class:`~decimal.Decimal`."""
        return Decimal(self.equity_at_trigger)

    @property
    def peak_equity_decimal(self) -> Decimal:
        """Peak equity as :class:`~decimal.Decimal`."""
        return Decimal(self.peak_equity)

    def recovery_target(self, threshold: float = RECOVERY_THRESHOLD) -> Decimal:
        """Compute the equity level required to satisfy the recovery threshold.

        Args:
            threshold: Fraction of the drawdown depth to recover.
                Defaults to :data:`RECOVERY_THRESHOLD`.

        Returns:
            The equity level (USDT) that must be reached before FULL state
            is permitted.

        Example::

            # peak=100 000, trigger=88 000, threshold=0.50
            # drawdown = 12 000; target = 88 000 + 6 000 = 94 000
            snap.recovery_target()  # → Decimal("94000")
        """
        peak = self.peak_equity_decimal
        trigger = self.equity_at_trigger_decimal
        drawdown_amount = peak - trigger
        recovery_amount = drawdown_amount * Decimal(str(threshold))
        return trigger + recovery_amount

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialise snapshot to a plain dict suitable for Redis hash storage.

        Returns:
            A flat dict with only JSON-safe scalar values.
        """
        return {
            "state": self.state.value,
            "drawdown_pct": str(self.drawdown_pct),
            "equity_at_trigger": self.equity_at_trigger,
            "peak_equity": self.peak_equity,
            "days_scaling": str(self.days_scaling),
            "current_multiplier": str(self.current_multiplier),
            "started_at": self.started_at,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecoverySnapshot:
        """Deserialise a snapshot from a dict read from Redis.

        Args:
            data: Flat dict with string values (as returned by
                ``redis.hgetall``).

        Returns:
            A fully-populated :class:`RecoverySnapshot`.

        Raises:
            KeyError: If a required field is missing from ``data``.
            ValueError: If a field value cannot be parsed.
        """
        return cls(
            state=RecoveryState(data["state"]),
            drawdown_pct=float(data["drawdown_pct"]),
            equity_at_trigger=data["equity_at_trigger"],
            peak_equity=data["peak_equity"],
            days_scaling=int(data["days_scaling"]),
            current_multiplier=float(data["current_multiplier"]),
            started_at=data["started_at"],
            last_updated=data["last_updated"],
        )


# ── RecoveryManager ───────────────────────────────────────────────────────────


class RecoveryManager:
    """Manages the graduated return from a drawdown event to full trading size.

    The machine has three states:

    * **RECOVERING** — trading is suspended (multiplier = 0.0) while ATR
      remains elevated.  No size ramp is applied yet.
    * **SCALING_UP** — ATR has normalised; position size starts at 25 % and
      increases by 25 pp per *qualifying* day (a day with no further losses).
      Scale-up is capped at 75 % until the equity recovery target is met.
    * **FULL** — both the 4-day ramp and the equity recovery target have been
      satisfied; multiplier returns to 1.0.

    State is persisted to Redis as a hash under the key
    ``agent:recovery:{agent_id}``.  On startup, the manager loads existing
    state automatically, making it crash-safe.

    Args:
        agent_id: Unique identifier for the agent being managed.
        redis: Async Redis client handle.  The manager never creates its own
            connection; the caller is responsible for lifecycle management.
        config: Optional :class:`RecoveryConfig`.  Defaults to the
            production-tuned defaults matching the task specification.

    Example::

        manager = RecoveryManager(
            agent_id="agent-uuid",
            redis=aioredis.from_url("redis://localhost:6379"),
        )

        # Trigger recovery after a REDUCE verdict:
        await manager.start_recovery(
            drawdown_pct=0.12,
            equity_at_trigger=Decimal("88000"),
            peak_equity=Decimal("100000"),
        )

        # On every tick:
        size_mult = await manager.get_size_multiplier(
            current_atr=current_atr,
            median_atr=median_atr,
            current_equity=current_equity,
        )

        # Once per calendar day (call from the daily scheduler):
        await manager.advance_day(
            current_equity=current_equity,
            had_loss=False,
        )
    """

    def __init__(
        self,
        agent_id: str,
        redis: aioredis.Redis,  # type: ignore[type-arg]
        config: RecoveryConfig | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._redis = redis
        self._config = config or RecoveryConfig()
        self._key = _RECOVERY_KEY.format(agent_id=agent_id)

    # ── Public API ────────────────────────────────────────────────────────────

    async def start_recovery(
        self,
        drawdown_pct: float,
        equity_at_trigger: Decimal,
        peak_equity: Decimal,
    ) -> RecoverySnapshot:
        """Initiate the recovery sequence after a drawdown event.

        Transitions the machine into :attr:`RecoveryState.RECOVERING` and
        persists the initial snapshot to Redis.  If recovery is already
        active, calling this method again **does not reset** the existing
        progress; it returns the current snapshot unchanged so callers can
        safely call it idempotently on every REDUCE verdict.

        Args:
            drawdown_pct: Current drawdown fraction (e.g. ``0.12`` for 12 %).
            equity_at_trigger: Portfolio equity at the moment the drawdown
                triggered recovery (USDT).
            peak_equity: Highest equity seen before the drawdown (USDT).

        Returns:
            The newly created (or existing) :class:`RecoverySnapshot`.
        """
        # Idempotent — do not override existing recovery in progress.
        existing = await self.load()
        if existing is not None and existing.state != RecoveryState.FULL:
            logger.info(
                "recovery_already_active",
                agent_id=self._agent_id,
                state=existing.state.value,
                days_scaling=existing.days_scaling,
            )
            return existing

        now = datetime.now(UTC).isoformat()
        snapshot = RecoverySnapshot(
            state=RecoveryState.RECOVERING,
            drawdown_pct=drawdown_pct,
            equity_at_trigger=str(equity_at_trigger),
            peak_equity=str(peak_equity),
            days_scaling=0,
            current_multiplier=0.0,
            started_at=now,
            last_updated=now,
        )
        await self._save(snapshot)
        logger.info(
            "recovery_started",
            agent_id=self._agent_id,
            drawdown_pct=drawdown_pct,
            equity_at_trigger=str(equity_at_trigger),
            peak_equity=str(peak_equity),
        )
        return snapshot

    async def get_size_multiplier(
        self,
        current_atr: float,
        median_atr: float,
        current_equity: Decimal,
    ) -> float:
        """Return the current position-size multiplier for this agent.

        This is the primary method called on every strategy tick.  It reads
        persisted state, checks ATR normalisation, applies the equity
        recovery gate, and returns the appropriate multiplier without
        mutating state.  Use :meth:`advance_day` once per calendar day to
        actually progress the ramp.

        Logic by state:

        * **FULL / no recovery active** — returns ``1.0``.
        * **RECOVERING** — returns ``0.0`` until
          ``current_atr < atr_normalisation_factor * median_atr``.
          When ATR normalises, transitions to SCALING_UP (persists) and
          returns ``0.25``.
        * **SCALING_UP** — returns ``current_multiplier`` from the snapshot,
          unless the multiplier would reach ``1.0`` before the equity
          recovery target is met, in which case it is capped at ``0.75``.

        Args:
            current_atr: Most recent ATR value for the primary symbol.
            median_atr: Long-run median ATR (e.g. rolling 20-period median)
                used as the normalisation baseline.
            current_equity: Current total portfolio equity (USDT).

        Returns:
            A size multiplier in ``[0.0, 1.0]``.  ``0.0`` means no new
            trades; ``1.0`` means full position sizing.
        """
        snapshot = await self.load()
        if snapshot is None or snapshot.state == RecoveryState.FULL:
            return 1.0

        if snapshot.state == RecoveryState.RECOVERING:
            return await self._check_atr_normalisation(snapshot, current_atr, median_atr)

        # SCALING_UP — apply equity recovery gate before returning multiplier.
        return self._apply_equity_gate(snapshot, current_equity)

    async def advance_day(
        self,
        current_equity: Decimal,
        had_loss: bool,
    ) -> RecoverySnapshot | None:
        """Advance the day counter during the SCALING_UP phase.

        Should be called exactly once per calendar day by the strategy
        scheduler.  Has no effect if recovery is not active or if
        ``had_loss=True`` (a loss day does not count as a qualifying day and
        the multiplier is not increased).

        Transitions to :attr:`RecoveryState.FULL` automatically when both
        conditions are met:

        * The ramp has reached ``scale_step * scale_days`` = ``1.0``
          (four qualifying days have elapsed).
        * The equity recovery target has been satisfied (equity has recovered
          ≥ ``recovery_threshold`` of the drawdown).

        Args:
            current_equity: Current total portfolio equity (USDT).
            had_loss: If ``True``, this day is not counted as a qualifying
                scale-up day.  The multiplier is unchanged.

        Returns:
            The updated :class:`RecoverySnapshot`, or ``None`` if recovery
            was not active.
        """
        snapshot = await self.load()
        if snapshot is None or snapshot.state in (RecoveryState.RECOVERING, RecoveryState.FULL):
            return snapshot

        # Loss day — do not advance the ramp.
        if had_loss:
            logger.info(
                "recovery_day_skipped_loss",
                agent_id=self._agent_id,
                days_scaling=snapshot.days_scaling,
                current_multiplier=snapshot.current_multiplier,
            )
            return snapshot

        new_days = snapshot.days_scaling + 1
        new_multiplier = min(1.0, self._config.scale_step * new_days)

        # Check whether the equity target has been reached.
        target = snapshot.recovery_target(self._config.recovery_threshold)
        equity_recovered = current_equity >= target

        # Determine new state.
        if new_multiplier >= 1.0 and equity_recovered:
            new_state = RecoveryState.FULL
            new_multiplier = 1.0
        elif new_multiplier >= 1.0 and not equity_recovered:
            # Cap at 0.75 while waiting for equity target; do not count
            # the last step until recovery threshold is met.
            new_state = RecoveryState.SCALING_UP
            new_multiplier = 1.0 - self._config.scale_step  # 0.75 with defaults
        else:
            new_state = RecoveryState.SCALING_UP

        updated = RecoverySnapshot(
            state=new_state,
            drawdown_pct=snapshot.drawdown_pct,
            equity_at_trigger=snapshot.equity_at_trigger,
            peak_equity=snapshot.peak_equity,
            days_scaling=new_days,
            current_multiplier=new_multiplier,
            started_at=snapshot.started_at,
            last_updated=datetime.now(UTC).isoformat(),
        )
        await self._save(updated)

        logger.info(
            "recovery_day_advanced",
            agent_id=self._agent_id,
            new_state=new_state.value,
            days_scaling=new_days,
            new_multiplier=new_multiplier,
            equity_recovered=equity_recovered,
        )
        return updated

    async def complete_recovery(self) -> RecoverySnapshot | None:
        """Force-complete recovery when the equity target is met externally.

        Transitions to :attr:`RecoveryState.FULL` unconditionally and sets
        the multiplier to ``1.0``.  Intended for use when a strategy manager
        detects that the equity recovery condition is satisfied mid-day
        without waiting for :meth:`advance_day`.

        Returns:
            The updated snapshot, or ``None`` if no recovery was active.
        """
        snapshot = await self.load()
        if snapshot is None or snapshot.state == RecoveryState.FULL:
            return snapshot

        updated = RecoverySnapshot(
            state=RecoveryState.FULL,
            drawdown_pct=snapshot.drawdown_pct,
            equity_at_trigger=snapshot.equity_at_trigger,
            peak_equity=snapshot.peak_equity,
            days_scaling=snapshot.days_scaling,
            current_multiplier=1.0,
            started_at=snapshot.started_at,
            last_updated=datetime.now(UTC).isoformat(),
        )
        await self._save(updated)
        logger.info(
            "recovery_completed",
            agent_id=self._agent_id,
            days_scaling=snapshot.days_scaling,
        )
        return updated

    async def clear(self) -> None:
        """Delete the persisted recovery state for this agent.

        Should be called after a recovery cycle has finished or when the
        agent is reset.  Safe to call when no recovery is active.
        """
        try:
            await self._redis.delete(self._key)
            logger.debug("recovery_state_cleared", agent_id=self._agent_id)
        except RedisError as exc:
            logger.warning(
                "recovery_clear_failed",
                agent_id=self._agent_id,
                error=str(exc),
            )

    async def load(self) -> RecoverySnapshot | None:
        """Load the current recovery snapshot from Redis.

        Returns:
            The persisted :class:`RecoverySnapshot`, or ``None`` if no
            recovery state exists for this agent.
        """
        try:
            data: dict[bytes, bytes] = await self._redis.hgetall(self._key)
            if not data:
                return None
            # Redis returns bytes keys/values; decode to str before parsing.
            str_data = {
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in data.items()
            }
            return RecoverySnapshot.from_dict(str_data)
        except RedisError as exc:
            logger.warning(
                "recovery_load_failed",
                agent_id=self._agent_id,
                error=str(exc),
            )
            return None
        except (KeyError, ValueError) as exc:
            logger.error(
                "recovery_state_corrupt",
                agent_id=self._agent_id,
                error=str(exc),
            )
            return None

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _save(self, snapshot: RecoverySnapshot) -> None:
        """Persist a snapshot to Redis as a hash.

        Uses a pipeline to write all fields atomically.  No TTL is applied —
        recovery state persists until :meth:`clear` is called.

        Args:
            snapshot: The snapshot to persist.
        """
        try:
            pipe = self._redis.pipeline()
            pipe.hset(self._key, mapping=snapshot.to_dict())  # type: ignore[arg-type]
            await pipe.execute()
        except RedisError as exc:
            logger.error(
                "recovery_save_failed",
                agent_id=self._agent_id,
                error=str(exc),
            )

    async def _check_atr_normalisation(
        self,
        snapshot: RecoverySnapshot,
        current_atr: float,
        median_atr: float,
    ) -> float:
        """Check whether ATR has normalised and transition state if so.

        Args:
            snapshot: Current RECOVERING snapshot.
            current_atr: Latest ATR value.
            median_atr: Rolling median ATR used as baseline.

        Returns:
            ``0.0`` if still waiting for normalisation; ``0.25`` once the
            ATR condition is met (and the state is transitioned to
            SCALING_UP).
        """
        atr_threshold = self._config.atr_normalisation_factor * median_atr
        if median_atr <= 0.0 or current_atr >= atr_threshold:
            logger.debug(
                "recovery_atr_elevated",
                agent_id=self._agent_id,
                current_atr=current_atr,
                threshold=atr_threshold,
            )
            return 0.0

        # ATR normalised — transition to SCALING_UP at initial multiplier.
        initial_multiplier = self._config.scale_step  # 0.25
        updated = RecoverySnapshot(
            state=RecoveryState.SCALING_UP,
            drawdown_pct=snapshot.drawdown_pct,
            equity_at_trigger=snapshot.equity_at_trigger,
            peak_equity=snapshot.peak_equity,
            days_scaling=0,
            current_multiplier=initial_multiplier,
            started_at=snapshot.started_at,
            last_updated=datetime.now(UTC).isoformat(),
        )
        await self._save(updated)
        logger.info(
            "recovery_atr_normalised",
            agent_id=self._agent_id,
            current_atr=current_atr,
            threshold=atr_threshold,
            initial_multiplier=initial_multiplier,
        )
        return initial_multiplier

    def _apply_equity_gate(
        self,
        snapshot: RecoverySnapshot,
        current_equity: Decimal,
    ) -> float:
        """Apply the equity recovery gate to the current multiplier.

        During SCALING_UP, the multiplier is capped at ``1.0 - scale_step``
        (0.75 with defaults) until the equity recovery target is reached.
        Once the target is met, the full snapshot multiplier is returned.

        Args:
            snapshot: Current SCALING_UP snapshot.
            current_equity: Current portfolio equity (USDT).

        Returns:
            The effective position-size multiplier after applying the gate.
        """
        target = snapshot.recovery_target(self._config.recovery_threshold)
        cap = 1.0 - self._config.scale_step  # 0.75 with defaults

        if current_equity < target and snapshot.current_multiplier > cap:
            logger.debug(
                "recovery_equity_gate_active",
                agent_id=self._agent_id,
                current_equity=str(current_equity),
                target=str(target),
                capped_at=cap,
            )
            return cap

        return snapshot.current_multiplier
