"""Budget enforcement for agent trading activity.

Enforces four financial limits for each agent:

1. **Daily trade count** — ``max_trades_per_day`` (from ``agent_budgets`` table or
   :class:`~agent.config.AgentConfig` defaults).
2. **Exposure cap** — ``max_exposure_pct`` of starting balance as a USDT ceiling.
3. **Daily loss limit** — ``max_daily_loss_pct`` of starting balance; trips when
   cumulative realised loss exceeds the threshold.
4. **Position size** — ``max_position_size_pct`` of starting balance; a single trade
   cannot exceed this USDT value.

Redis key patterns managed by this module::

    agent:budget:{agent_id}:trades_today     string  — integer trade count, expires at midnight UTC
    agent:budget:{agent_id}:exposure_today   string  — Decimal USDT exposure, expires at midnight UTC
    agent:budget:{agent_id}:loss_today       string  — Decimal USDT loss, expires at midnight UTC
    agent:budget:{agent_id}:limits           string  — JSON-encoded limit config, TTL = _LIMITS_CACHE_TTL
    agent:budget:{agent_id}:last_persist     string  — epoch of last DB persist, no TTL

All counter reads happen exclusively from Redis (sub-millisecond).  Counters are
persisted to the Postgres ``agent_budgets`` table periodically (every
:data:`_PERSIST_INTERVAL_SECONDS`, default 300 s) to reduce DB load.

All Redis operations catch :class:`~redis.exceptions.RedisError` and degrade
gracefully — on failure the system falls back to a Postgres read and, if that
also fails, applies conservative defaults (treat budget as exhausted).

Example::

    from agent.permissions.budget import BudgetManager
    from agent.config import AgentConfig
    from decimal import Decimal

    config = AgentConfig()
    manager = BudgetManager(config=config)

    result = await manager.check_budget("agent-uuid", Decimal("500.00"))
    if not result.allowed:
        print(f"Trade denied: {result.reason}")
    else:
        await manager.record_trade("agent-uuid", Decimal("500.00"))
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis
import structlog
from redis.exceptions import RedisError

from agent.config import AgentConfig
from agent.models.ecosystem import BudgetCheckResult, BudgetStatus

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Redis key patterns
# ---------------------------------------------------------------------------

_BUDGET_TRADES_KEY = "agent:budget:{agent_id}:trades_today"
_BUDGET_EXPOSURE_KEY = "agent:budget:{agent_id}:exposure_today"
_BUDGET_LOSS_KEY = "agent:budget:{agent_id}:loss_today"
_BUDGET_LIMITS_KEY = "agent:budget:{agent_id}:limits"
_BUDGET_LAST_PERSIST_KEY = "agent:budget:{agent_id}:last_persist"

# How long the resolved limit config stays cached in Redis (5 minutes).
_LIMITS_CACHE_TTL: int = 300

# How often (in seconds) we flush Redis counters back to Postgres.
_PERSIST_INTERVAL_SECONDS: int = 300

# Decimal precision constant for USDT comparisons.
_ZERO = Decimal("0")


def _trades_key(agent_id: str) -> str:
    return _BUDGET_TRADES_KEY.format(agent_id=agent_id)


def _exposure_key(agent_id: str) -> str:
    return _BUDGET_EXPOSURE_KEY.format(agent_id=agent_id)


def _loss_key(agent_id: str) -> str:
    return _BUDGET_LOSS_KEY.format(agent_id=agent_id)


def _limits_key(agent_id: str) -> str:
    return _BUDGET_LIMITS_KEY.format(agent_id=agent_id)


def _last_persist_key(agent_id: str) -> str:
    return _BUDGET_LAST_PERSIST_KEY.format(agent_id=agent_id)


def _seconds_until_midnight_utc() -> int:
    """Return the number of seconds from now until the next UTC midnight.

    Used to set the TTL on daily counter keys so they auto-expire at reset time.

    Returns:
        Integer seconds until next UTC midnight (minimum 1).
    """
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    delta = int((tomorrow - now).total_seconds())
    return max(delta, 1)


# ---------------------------------------------------------------------------
# BudgetLimits (internal NamedTuple-like dataclass)
# ---------------------------------------------------------------------------


class _BudgetLimits:
    """Resolved budget limits for a single agent.

    All monetary limits are in USDT absolute values derived from the
    percentage limits and an assumed starting balance (default 10,000 USDT
    when not stored in the budget record).

    Args:
        max_trades_per_day: Maximum trades allowed per day.
        max_exposure_usdt: Maximum cumulative exposure (open positions) in USDT.
        max_daily_loss_usdt: Maximum realised loss in USDT before circuit breaker fires.
        max_position_size_usdt: Maximum single-trade value in USDT.
    """

    __slots__ = (
        "max_trades_per_day",
        "max_exposure_usdt",
        "max_daily_loss_usdt",
        "max_position_size_usdt",
    )

    def __init__(
        self,
        max_trades_per_day: int,
        max_exposure_usdt: Decimal,
        max_daily_loss_usdt: Decimal,
        max_position_size_usdt: Decimal,
    ) -> None:
        self.max_trades_per_day = max_trades_per_day
        self.max_exposure_usdt = max_exposure_usdt
        self.max_daily_loss_usdt = max_daily_loss_usdt
        self.max_position_size_usdt = max_position_size_usdt

    def to_json(self) -> str:
        """Serialise to JSON for Redis caching.

        Returns:
            JSON string with all four limit fields.
        """
        return json.dumps(
            {
                "max_trades_per_day": self.max_trades_per_day,
                "max_exposure_usdt": str(self.max_exposure_usdt),
                "max_daily_loss_usdt": str(self.max_daily_loss_usdt),
                "max_position_size_usdt": str(self.max_position_size_usdt),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> _BudgetLimits:
        """Deserialise from a JSON string cached in Redis.

        Args:
            raw: JSON string produced by :meth:`to_json`.

        Returns:
            A :class:`_BudgetLimits` instance.

        Raises:
            (json.JSONDecodeError, KeyError, InvalidOperation): On any parse error.
        """
        data: dict[str, Any] = json.loads(raw)
        return cls(
            max_trades_per_day=int(data["max_trades_per_day"]),
            max_exposure_usdt=Decimal(data["max_exposure_usdt"]),
            max_daily_loss_usdt=Decimal(data["max_daily_loss_usdt"]),
            max_position_size_usdt=Decimal(data["max_position_size_usdt"]),
        )


# ---------------------------------------------------------------------------
# BudgetManager
# ---------------------------------------------------------------------------


class BudgetManager:
    """Enforces financial limits on agent trading activity.

    Acts as a fast pre-trade gate that runs in under 5 ms by reading all
    counter state from Redis.  Counter durability is maintained by flushing
    to Postgres every :data:`_PERSIST_INTERVAL_SECONDS` (300 s).

    Four limits are enforced on every :meth:`check_budget` call:

    1. **Daily trade count** — ``trades_today < max_trades_per_day``
    2. **Exposure cap** — ``exposure_today + trade_value <= max_exposure_usdt``
    3. **Daily loss limit** — ``loss_today < max_daily_loss_usdt``
    4. **Position size** — ``trade_value <= max_position_size_usdt``

    All limits are resolved from the Postgres ``agent_budgets`` table on first
    use and cached in Redis for :data:`_LIMITS_CACHE_TTL` seconds.

    Redis counter keys carry a TTL set to the number of seconds until the next
    UTC midnight, so daily counters reset automatically even if the Celery beat
    task that calls :meth:`reset_daily` misses its scheduled window.

    Args:
        config: :class:`~agent.config.AgentConfig` instance — used for default
            limit values and to obtain the Redis connection.
        redis: Optional pre-built ``redis.asyncio.Redis`` instance.  Pass an
            explicit instance in tests to inject a mock.

    Example::

        config = AgentConfig()
        manager = BudgetManager(config=config)

        result = await manager.check_budget("agent-uuid", Decimal("500.00"))
        if result.allowed:
            await manager.record_trade("agent-uuid", Decimal("500.00"))
    """

    def __init__(
        self,
        config: AgentConfig,
        redis: aioredis.Redis | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._config = config
        self._redis: aioredis.Redis | None = redis  # type: ignore[type-arg]
        # In-process lock to serialise check+record sequences per agent_id.
        # This prevents a TOCTOU race when multiple async tasks call check_budget
        # and record_trade for the same agent concurrently.
        self._locks: dict[str, asyncio.Lock] = {}
        # Tracked fire-and-forget persist tasks so we can await them on shutdown
        # and ensure no counter snapshots are lost when the process exits cleanly.
        self._pending_persists: set[asyncio.Task] = set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_lock(self, agent_id: str) -> asyncio.Lock:
        """Return the per-agent asyncio lock, creating it on first use.

        Uses ``setdefault`` for atomic dict insertion so that two concurrent
        callers racing on the same ``agent_id`` both receive the same lock
        object (Python's dict.setdefault is thread-safe under the GIL).

        Args:
            agent_id: UUID string of the agent.

        Returns:
            An :class:`asyncio.Lock` scoped to *agent_id*.
        """
        return self._locks.setdefault(agent_id, asyncio.Lock())

    async def _get_redis(self) -> aioredis.Redis:  # type: ignore[type-arg]
        """Return the Redis client, initialising the singleton on first call.

        Returns:
            A connected ``redis.asyncio.Redis`` instance.
        """
        if self._redis is None:
            from src.cache.redis_client import get_redis_client  # noqa: PLC0415

            self._redis = await get_redis_client()
        return self._redis

    async def _get_db_session(self) -> AsyncSession:
        """Return a new async DB session from the shared session factory.

        Returns:
            An :class:`~sqlalchemy.ext.asyncio.AsyncSession` context manager.
        """
        from src.database.session import get_session_factory  # noqa: PLC0415

        factory = get_session_factory()
        return factory()

    async def _resolve_limits(self, agent_id: str) -> _BudgetLimits:
        """Resolve budget limits for *agent_id*.

        Resolution order:

        1. Redis cache hit (``agent:budget:{agent_id}:limits``) → deserialise.
        2. Postgres ``agent_budgets`` row → convert percentages to USDT absolutes
           using a default 10,000 USDT starting balance.
        3. Both fail → apply :class:`~agent.config.AgentConfig` defaults.

        Resolved limits are written to Redis with :data:`_LIMITS_CACHE_TTL`.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            A :class:`_BudgetLimits` instance with all four limits populated.
        """
        # --- 1. Redis cache hit ---
        try:
            redis = await self._get_redis()
            raw: str | None = await redis.get(_limits_key(agent_id))
            if raw is not None:
                try:
                    return _BudgetLimits.from_json(raw)
                except (json.JSONDecodeError, KeyError, InvalidOperation) as exc:
                    logger.warning(
                        "agent.budget.limits_deserialise_error",
                        agent_id=agent_id,
                        error=str(exc),
                    )
        except RedisError as exc:
            logger.warning(
                "agent.budget.limits_redis_read_error",
                agent_id=agent_id,
                error=str(exc),
            )

        # --- 2. Postgres lookup ---
        limits = await self._load_limits_from_db(agent_id)

        # --- 3. Cache the resolved limits ---
        await self._cache_limits(agent_id, limits)
        return limits

    async def _load_limits_from_db(self, agent_id: str) -> _BudgetLimits:
        """Load budget limits from the Postgres ``agent_budgets`` table.

        Falls back to :class:`~agent.config.AgentConfig` defaults if the
        record does not exist or on any DB error.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Resolved :class:`_BudgetLimits`.
        """
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
            AgentBudgetRepository,
        )

        # Assumed starting balance for converting percentages to USDT.
        _STARTING_BALANCE = Decimal("10000")

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError) as exc:
            logger.warning(
                "agent.budget.invalid_agent_id",
                agent_id=agent_id,
                error=str(exc),
            )
            return self._default_limits()

        session = await self._get_db_session()
        try:
            async with session as s:
                repo = AgentBudgetRepository(s)
                try:
                    budget = await repo.get_by_agent(agent_uuid)
                except AgentBudgetNotFoundError:
                    logger.debug(
                        "agent.budget.no_budget_record",
                        agent_id=agent_id,
                    )
                    return self._default_limits()

                # Convert percentage limits to USDT absolutes.
                max_trades = (
                    budget.max_trades_per_day
                    if budget.max_trades_per_day is not None
                    else self._config.default_max_trades_per_day
                )

                exposure_pct = (
                    budget.max_exposure_pct
                    if budget.max_exposure_pct is not None
                    else Decimal(str(self._config.default_max_exposure_pct))
                )
                max_exposure = (_STARTING_BALANCE * exposure_pct / Decimal("100")).quantize(
                    Decimal("0.00000001")
                )

                loss_pct = (
                    budget.max_daily_loss_pct
                    if budget.max_daily_loss_pct is not None
                    else Decimal(str(self._config.default_max_daily_loss_pct))
                )
                max_loss = (_STARTING_BALANCE * loss_pct / Decimal("100")).quantize(
                    Decimal("0.00000001")
                )

                position_pct = (
                    budget.max_position_size_pct
                    if budget.max_position_size_pct is not None
                    else Decimal("10")  # 10% default position size
                )
                max_position = (_STARTING_BALANCE * position_pct / Decimal("100")).quantize(
                    Decimal("0.00000001")
                )

                return _BudgetLimits(
                    max_trades_per_day=max_trades,
                    max_exposure_usdt=max_exposure,
                    max_daily_loss_usdt=max_loss,
                    max_position_size_usdt=max_position,
                )

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "agent.budget.db_load_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return self._default_limits()

    def _default_limits(self) -> _BudgetLimits:
        """Build limits from :class:`~agent.config.AgentConfig` defaults.

        Uses a fixed 10,000 USDT starting balance to convert percentage
        defaults into USDT absolute values.

        Returns:
            A :class:`_BudgetLimits` instance with config-derived defaults.
        """
        _STARTING_BALANCE = Decimal("10000")
        exposure_pct = Decimal(str(self._config.default_max_exposure_pct))
        loss_pct = Decimal(str(self._config.default_max_daily_loss_pct))
        # Default position size is 10% of starting balance.
        position_pct = Decimal("10")

        return _BudgetLimits(
            max_trades_per_day=self._config.default_max_trades_per_day,
            max_exposure_usdt=(_STARTING_BALANCE * exposure_pct / Decimal("100")).quantize(
                Decimal("0.00000001")
            ),
            max_daily_loss_usdt=(_STARTING_BALANCE * loss_pct / Decimal("100")).quantize(
                Decimal("0.00000001")
            ),
            max_position_size_usdt=(_STARTING_BALANCE * position_pct / Decimal("100")).quantize(
                Decimal("0.00000001")
            ),
        )

    async def _cache_limits(self, agent_id: str, limits: _BudgetLimits) -> None:
        """Write resolved limits to Redis with :data:`_LIMITS_CACHE_TTL`.

        Swallows Redis errors silently — a write failure here is non-critical
        because the next call will simply re-resolve from Postgres.

        Args:
            agent_id: UUID string of the agent.
            limits: Resolved :class:`_BudgetLimits` to store.
        """
        try:
            redis = await self._get_redis()
            await redis.set(
                _limits_key(agent_id),
                limits.to_json(),
                ex=_LIMITS_CACHE_TTL,
            )
        except (RedisError, TypeError, ValueError) as exc:
            logger.debug(
                "agent.budget.limits_cache_write_error",
                agent_id=agent_id,
                error=str(exc),
            )

    async def _invalidate_limits_cache(self, agent_id: str) -> None:
        """Delete the cached limits entry for *agent_id*.

        Called after a budget record is updated so the next :meth:`check_budget`
        call re-resolves from Postgres.

        Args:
            agent_id: UUID string of the agent.
        """
        try:
            redis = await self._get_redis()
            await redis.delete(_limits_key(agent_id))
        except RedisError as exc:
            logger.debug(
                "agent.budget.limits_cache_invalidate_error",
                agent_id=agent_id,
                error=str(exc),
            )

    async def _read_counters(
        self, agent_id: str
    ) -> tuple[int, Decimal, Decimal]:
        """Read (trades_today, exposure_today, loss_today) from Redis.

        Falls back to Postgres on Redis failure.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Tuple of ``(trades_today, exposure_today, loss_today)``.
        """
        try:
            redis = await self._get_redis()
            trades_raw, exposure_raw, loss_raw = await redis.mget(
                _trades_key(agent_id),
                _exposure_key(agent_id),
                _loss_key(agent_id),
            )
            trades_today = int(trades_raw) if trades_raw is not None else 0
            exposure_today = Decimal(exposure_raw) if exposure_raw is not None else _ZERO
            loss_today = Decimal(loss_raw) if loss_raw is not None else _ZERO
            return trades_today, exposure_today, loss_today
        except RedisError as exc:
            logger.warning(
                "agent.budget.counter_read_redis_error",
                agent_id=agent_id,
                error=str(exc),
            )
        except (InvalidOperation, ValueError) as exc:
            logger.warning(
                "agent.budget.counter_parse_error",
                agent_id=agent_id,
                error=str(exc),
            )

        # Redis unavailable — fall back to Postgres.
        return await self._read_counters_from_db(agent_id)

    async def _read_counters_from_db(
        self, agent_id: str
    ) -> tuple[int, Decimal, Decimal]:
        """Read counters from the Postgres ``agent_budgets`` table.

        Returns fail-closed sentinel values on any error so that when both
        Redis and Postgres are unavailable, all budget checks are denied
        rather than permitted.  A missing budget record (agent has never
        traded) legitimately returns zeros.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Tuple of ``(trades_today, exposure_today, loss_today)``.
        """
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
            AgentBudgetRepository,
        )

        try:
            agent_uuid = UUID(agent_id)
            session = await self._get_db_session()
            async with session as s:
                repo = AgentBudgetRepository(s)
                try:
                    budget = await repo.get_by_agent(agent_uuid)
                    return (
                        budget.trades_today,
                        budget.exposure_today,
                        budget.loss_today,
                    )
                except AgentBudgetNotFoundError:
                    # No record yet — agent has not traded; genuine zeros.
                    return 0, _ZERO, _ZERO
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "agent.budget.counter_db_read_error",
                agent_id=agent_id,
                error=str(exc),
            )
            # Fail closed: when both Redis and DB are unavailable, return
            # sentinel values that cause all four budget limit checks to
            # fail rather than pass.  Using sys.maxsize / very large Decimal
            # ensures no limit threshold can be satisfied.
            import sys  # noqa: PLC0415
            _FAIL_CLOSED_USDT = Decimal("999999999999")
            return sys.maxsize, _FAIL_CLOSED_USDT, _FAIL_CLOSED_USDT

    async def _maybe_persist(self, agent_id: str) -> None:
        """Flush Redis counters to Postgres if the persist interval has elapsed.

        Writes to the ``agent_budgets`` table at most once every
        :data:`_PERSIST_INTERVAL_SECONDS` seconds per agent.  The timestamp
        of the last persist is stored in Redis as an epoch float under
        ``agent:budget:{agent_id}:last_persist``.

        Silently swallows all errors — persistence failure must never block
        a trade.

        Args:
            agent_id: UUID string of the agent.
        """
        try:
            redis = await self._get_redis()
            now = time.time()

            # Check when we last persisted.
            last_raw: str | None = await redis.get(_last_persist_key(agent_id))
            if last_raw is not None:
                last_persist = float(last_raw)
                if now - last_persist < _PERSIST_INTERVAL_SECONDS:
                    return  # Not yet time.

            # Read current counter values.
            trades, exposure, loss = await self._read_counters(agent_id)

            # Write to Postgres.
            await self._persist_counters_to_db(agent_id, trades, exposure, loss)

            # Record persist timestamp.
            await redis.set(_last_persist_key(agent_id), str(now))

        except RedisError as exc:
            logger.warning(
                "agent.budget.persist_redis_error",
                agent_id=agent_id,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "agent.budget.persist_error",
                agent_id=agent_id,
                error=str(exc),
            )

    async def _persist_counters_to_db(
        self,
        agent_id: str,
        trades_today: int,
        exposure_today: Decimal,
        loss_today: Decimal,
    ) -> None:
        """Write current counter values to the ``agent_budgets`` table.

        Uses the atomic increment methods on :class:`AgentBudgetRepository`
        to avoid clobbering concurrent updates.  The strategy is to compute
        the delta from the DB's current value.

        Args:
            agent_id: UUID string of the agent.
            trades_today: Current Redis trade count.
            exposure_today: Current Redis exposure in USDT.
            loss_today: Current Redis loss in USDT.
        """
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
            AgentBudgetRepository,
        )

        try:
            agent_uuid = UUID(agent_id)
            session = await self._get_db_session()
            async with session.begin():
                repo = AgentBudgetRepository(session)
                try:
                    budget = await repo.get_by_agent(agent_uuid)
                except AgentBudgetNotFoundError:
                    # No budget record — nothing to persist.
                    logger.debug(
                        "agent.budget.persist_no_record",
                        agent_id=agent_id,
                    )
                    return

                # Compute deltas so we do not overwrite concurrent changes.
                trade_delta = trades_today - budget.trades_today
                exposure_delta = exposure_today - budget.exposure_today
                loss_delta = loss_today - budget.loss_today

                if trade_delta != 0:
                    await repo.increment_trades_today(agent_uuid, delta=trade_delta)
                if exposure_delta != _ZERO:
                    await repo.increment_exposure_today(agent_uuid, delta=exposure_delta)
                if loss_delta != _ZERO:
                    await repo.increment_loss_today(agent_uuid, delta=loss_delta)

            logger.debug(
                "agent.budget.persisted",
                agent_id=agent_id,
                trades_today=trades_today,
                exposure_today=str(exposure_today),
                loss_today=str(loss_today),
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "agent.budget.persist_db_error",
                agent_id=agent_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_budget(
        self, agent_id: str, trade_value: Decimal
    ) -> BudgetCheckResult:
        """Check whether a proposed trade is within all budget limits.

        Evaluates four limits in order:

        1. Position size — ``trade_value <= max_position_size_usdt``.
        2. Daily trade count — ``trades_today < max_trades_per_day``.
        3. Exposure cap — ``exposure_today + trade_value <= max_exposure_usdt``.
        4. Daily loss limit — ``loss_today < max_daily_loss_usdt``.

        All counter reads are from Redis (< 5 ms).  If Redis is unavailable the
        method falls back to Postgres, which may be slightly slower.

        Args:
            agent_id: UUID string of the agent placing the trade.
            trade_value: Proposed trade value in USDT.

        Returns:
            A :class:`~agent.models.ecosystem.BudgetCheckResult` with
            ``allowed=True`` and remaining headroom, or ``allowed=False``
            with a human-readable ``reason``.
        """
        limits = await self._resolve_limits(agent_id)
        trades_today, exposure_today, loss_today = await self._read_counters(agent_id)

        # Emit budget usage ratio metrics (best-effort)
        try:
            from agent.metrics import agent_budget_usage  # noqa: PLC0415

            if limits.max_trades_per_day > 0:
                agent_budget_usage.labels(
                    agent_id=agent_id, limit_type="daily_trades"
                ).set(trades_today / limits.max_trades_per_day)
            if limits.max_exposure_usdt > _ZERO:
                agent_budget_usage.labels(
                    agent_id=agent_id, limit_type="exposure"
                ).set(float(exposure_today / limits.max_exposure_usdt))
            if limits.max_daily_loss_usdt > _ZERO:
                agent_budget_usage.labels(
                    agent_id=agent_id, limit_type="daily_loss"
                ).set(float(loss_today / limits.max_daily_loss_usdt))
        except Exception:  # noqa: BLE001
            pass

        # Derive remaining headroom for the result.
        remaining_trades = max(0, limits.max_trades_per_day - trades_today)
        remaining_exposure = max(_ZERO, limits.max_exposure_usdt - exposure_today)
        remaining_loss = max(_ZERO, limits.max_daily_loss_usdt - loss_today)

        # --- Check 1: Single position size limit ---
        if trade_value > limits.max_position_size_usdt:
            reason = (
                f"Trade value {trade_value} USDT exceeds maximum position size "
                f"{limits.max_position_size_usdt} USDT."
            )
            logger.info(
                "agent.budget.check.denied.position_size",
                agent_id=agent_id,
                trade_value=str(trade_value),
                limit=str(limits.max_position_size_usdt),
            )
            return BudgetCheckResult(
                allowed=False,
                reason=reason,
                remaining_trades=remaining_trades,
                remaining_exposure=remaining_exposure,
                remaining_loss_budget=remaining_loss,
            )

        # --- Check 2: Daily trade count limit ---
        if trades_today >= limits.max_trades_per_day:
            reason = (
                f"Daily trade limit of {limits.max_trades_per_day} reached "
                f"(trades_today={trades_today})."
            )
            logger.info(
                "agent.budget.check.denied.trade_count",
                agent_id=agent_id,
                trades_today=trades_today,
                limit=limits.max_trades_per_day,
            )
            return BudgetCheckResult(
                allowed=False,
                reason=reason,
                remaining_trades=0,
                remaining_exposure=remaining_exposure,
                remaining_loss_budget=remaining_loss,
            )

        # --- Check 3: Exposure cap ---
        projected_exposure = exposure_today + trade_value
        if projected_exposure > limits.max_exposure_usdt:
            reason = (
                f"Trade would bring total exposure to {projected_exposure} USDT, "
                f"exceeding cap of {limits.max_exposure_usdt} USDT "
                f"(current exposure={exposure_today} USDT)."
            )
            logger.info(
                "agent.budget.check.denied.exposure",
                agent_id=agent_id,
                projected_exposure=str(projected_exposure),
                limit=str(limits.max_exposure_usdt),
            )
            return BudgetCheckResult(
                allowed=False,
                reason=reason,
                remaining_trades=remaining_trades,
                remaining_exposure=remaining_exposure,
                remaining_loss_budget=remaining_loss,
            )

        # --- Check 4: Daily loss limit ---
        if loss_today >= limits.max_daily_loss_usdt:
            reason = (
                f"Daily loss limit of {limits.max_daily_loss_usdt} USDT reached "
                f"(loss_today={loss_today} USDT)."
            )
            logger.info(
                "agent.budget.check.denied.loss_limit",
                agent_id=agent_id,
                loss_today=str(loss_today),
                limit=str(limits.max_daily_loss_usdt),
            )
            return BudgetCheckResult(
                allowed=False,
                reason=reason,
                remaining_trades=remaining_trades,
                remaining_exposure=remaining_exposure,
                remaining_loss_budget=_ZERO,
            )

        logger.debug(
            "agent.budget.check.allowed",
            agent_id=agent_id,
            trade_value=str(trade_value),
            trades_today=trades_today,
            exposure_today=str(exposure_today),
            loss_today=str(loss_today),
        )
        return BudgetCheckResult(
            allowed=True,
            reason="",
            remaining_trades=remaining_trades - 1,  # subtract the prospective trade
            remaining_exposure=remaining_exposure - trade_value,
            remaining_loss_budget=remaining_loss,
        )

    async def record_trade(
        self, agent_id: str, trade_value: Decimal
    ) -> None:
        """Record that a trade has been executed, updating Redis counters atomically.

        Increments ``trades_today`` by 1 and ``exposure_today`` by
        *trade_value*.  Both increments happen in a single Redis pipeline
        (no race window between them).

        After updating counters, triggers :meth:`_maybe_persist` to flush to
        Postgres if the persist interval has elapsed.  Persist failures never
        block this method.

        Args:
            agent_id: UUID string of the agent.
            trade_value: Value of the executed trade in USDT.
        """
        ttl = _seconds_until_midnight_utc()
        # Format Decimal as a fixed-point string to avoid float precision loss.
        # Redis INCRBYFLOAT accepts arbitrary-precision decimal strings.
        trade_value_str = format(trade_value, "f")
        try:
            redis = await self._get_redis()
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incr(_trades_key(agent_id))
                pipe.expire(_trades_key(agent_id), ttl)
                pipe.incrbyfloat(_exposure_key(agent_id), trade_value_str)
                pipe.expire(_exposure_key(agent_id), ttl)
                await pipe.execute()

            logger.info(
                "agent.budget.trade_recorded",
                agent_id=agent_id,
                trade_value=str(trade_value),
            )
        except RedisError as exc:
            logger.error(
                "agent.budget.record_trade_redis_error",
                agent_id=agent_id,
                trade_value=str(trade_value),
                error=str(exc),
            )

        # Best-effort persist — never raises.  Task is tracked so _shutdown
        # can await all pending persists before the process exits.
        task = asyncio.create_task(self._maybe_persist(agent_id))
        self._pending_persists.add(task)
        task.add_done_callback(self._pending_persists.discard)

    async def check_and_record(
        self, agent_id: str, trade_value: Decimal
    ) -> BudgetCheckResult:
        """Atomically check budget and record the trade if allowed.

        This is the **preferred entry point** for the enforcement layer.
        It acquires the per-agent asyncio lock to serialise concurrent calls
        from different async tasks within the same process, eliminating the
        TOCTOU race between separate ``check_budget`` + ``record_trade`` calls.

        If the budget check passes, the counters are incremented before the
        lock is released, so a second concurrent call for the same agent sees
        the updated counters and will correctly deny if limits are exhausted.

        .. note::
            The per-agent lock prevents races within a single process.
            Multi-process deployments (e.g., multiple Uvicorn workers) still
            rely on Redis atomic operations (INCR / INCRBYFLOAT) for
            inter-process safety.  The Redis pipeline with ``transaction=True``
            ensures the counter update is atomic at the Redis level.

        Args:
            agent_id: UUID string of the agent placing the trade.
            trade_value: Proposed trade value in USDT.

        Returns:
            A :class:`~agent.models.ecosystem.BudgetCheckResult` with
            ``allowed=True`` if the trade was within limits and counters were
            incremented, or ``allowed=False`` with a human-readable ``reason``
            (counters unchanged).
        """
        async with self._get_lock(agent_id):
            result = await self.check_budget(agent_id, trade_value)
            if result.allowed:
                await self.record_trade(agent_id, trade_value)
            return result

    async def record_loss(
        self, agent_id: str, loss_amount: Decimal
    ) -> None:
        """Record a realised loss against the daily loss budget.

        Atomically increments ``loss_today`` by *loss_amount* in Redis.
        *loss_amount* must be a positive value representing the magnitude of
        the loss (e.g., ``Decimal("45.00")`` for a $45 loss).

        Args:
            agent_id: UUID string of the agent.
            loss_amount: Magnitude of the realised loss in USDT (positive value).
        """
        if loss_amount <= _ZERO:
            logger.debug(
                "agent.budget.record_loss_skipped_non_positive",
                agent_id=agent_id,
                loss_amount=str(loss_amount),
            )
            return

        ttl = _seconds_until_midnight_utc()
        # Format Decimal as a fixed-point string to avoid float precision loss.
        loss_amount_str = format(loss_amount, "f")
        try:
            redis = await self._get_redis()
            async with redis.pipeline(transaction=True) as pipe:
                pipe.incrbyfloat(_loss_key(agent_id), loss_amount_str)
                pipe.expire(_loss_key(agent_id), ttl)
                await pipe.execute()

            logger.info(
                "agent.budget.loss_recorded",
                agent_id=agent_id,
                loss_amount=str(loss_amount),
            )
        except RedisError as exc:
            logger.error(
                "agent.budget.record_loss_redis_error",
                agent_id=agent_id,
                loss_amount=str(loss_amount),
                error=str(exc),
            )

        # Best-effort persist — never raises.  Task is tracked so _shutdown
        # can await all pending persists before the process exits.
        task = asyncio.create_task(self._maybe_persist(agent_id))
        self._pending_persists.add(task)
        task.add_done_callback(self._pending_persists.discard)

    async def get_budget_status(self, agent_id: str) -> BudgetStatus:
        """Return the current budget utilisation for *agent_id*.

        Reads counters from Redis and limits from the limits cache to build a
        :class:`~agent.models.ecosystem.BudgetStatus` with utilisation
        percentages rounded to 4 decimal places.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            A :class:`~agent.models.ecosystem.BudgetStatus` instance
            with all current counters and computed utilisation fractions.
        """
        limits = await self._resolve_limits(agent_id)
        trades_today, exposure_today, loss_today = await self._read_counters(agent_id)

        def _safe_pct(numerator: Decimal | int, denominator: Decimal | int) -> float:
            """Compute numerator / denominator clamped to [0.0, 1.0].

            Args:
                numerator: Current value.
                denominator: Limit value.

            Returns:
                Utilisation fraction in [0.0, 1.0].
            """
            if denominator == 0:
                return 1.0 if numerator > 0 else 0.0
            ratio = float(Decimal(str(numerator)) / Decimal(str(denominator)))
            return min(1.0, max(0.0, ratio))

        # Compute next UTC midnight reset time.
        now = datetime.now(UTC)
        reset_at = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        return BudgetStatus(
            agent_id=agent_id,
            trades_today=trades_today,
            trades_limit=limits.max_trades_per_day,
            trades_utilization_pct=_safe_pct(trades_today, limits.max_trades_per_day),
            exposure_used=exposure_today,
            exposure_limit=limits.max_exposure_usdt,
            exposure_utilization_pct=_safe_pct(exposure_today, limits.max_exposure_usdt),
            loss_today=loss_today,
            loss_limit=limits.max_daily_loss_usdt,
            loss_utilization_pct=_safe_pct(loss_today, limits.max_daily_loss_usdt),
            reset_at=reset_at,
        )

    async def reset_daily(self, agent_id: str) -> None:
        """Reset all daily counters to zero for *agent_id*.

        Deletes the Redis counter keys and updates the Postgres
        ``agent_budgets`` row via ``AgentBudgetRepository.reset_daily()``.
        Also invalidates the limits cache so the next :meth:`check_budget`
        re-resolves fresh limits.

        Intended to be called by the Celery beat task at midnight UTC, but
        can also be called manually (e.g., in tests or for manual overrides).

        Args:
            agent_id: UUID string of the agent.
        """
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
            AgentBudgetRepository,
        )

        # --- Reset Redis counters ---
        try:
            redis = await self._get_redis()
            async with redis.pipeline(transaction=True) as pipe:
                pipe.delete(_trades_key(agent_id))
                pipe.delete(_exposure_key(agent_id))
                pipe.delete(_loss_key(agent_id))
                pipe.delete(_last_persist_key(agent_id))
                await pipe.execute()

            logger.info(
                "agent.budget.daily_reset_redis",
                agent_id=agent_id,
            )
        except RedisError as exc:
            logger.error(
                "agent.budget.daily_reset_redis_error",
                agent_id=agent_id,
                error=str(exc),
            )

        # --- Reset Postgres counters ---
        try:
            agent_uuid = UUID(agent_id)
            session = await self._get_db_session()
            async with session.begin():
                repo = AgentBudgetRepository(session)
                try:
                    await repo.reset_daily(agent_uuid)
                    logger.info(
                        "agent.budget.daily_reset_db",
                        agent_id=agent_id,
                    )
                except AgentBudgetNotFoundError:
                    logger.debug(
                        "agent.budget.daily_reset_no_record",
                        agent_id=agent_id,
                    )
        except (ValueError, AttributeError) as exc:
            logger.warning(
                "agent.budget.invalid_agent_id",
                agent_id=agent_id,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "agent.budget.daily_reset_db_error",
                agent_id=agent_id,
                error=str(exc),
            )

        # Invalidate limits cache so any limit changes take effect immediately.
        await self._invalidate_limits_cache(agent_id)

    async def close(self) -> None:
        """Await all pending background persist tasks before shutdown.

        Called during graceful shutdown to ensure that the last counter
        snapshot for every agent is flushed to Postgres before the process
        exits.  Without this, any persist tasks fired after the most recent
        :data:`_PERSIST_INTERVAL_SECONDS` checkpoint would be silently
        dropped when the event loop is torn down.

        Uses ``asyncio.gather(..., return_exceptions=True)`` so that a
        failure in one task does not prevent the others from completing.
        All exceptions are logged at WARNING level.

        Safe to call even if ``_pending_persists`` is empty — it is a no-op
        in that case.
        """
        pending = list(self._pending_persists)
        if not pending:
            return

        logger.info(
            "agent.budget.close_awaiting_persists",
            count=len(pending),
        )
        results = await asyncio.gather(*pending, return_exceptions=True)
        for exc in results:
            if isinstance(exc, BaseException):
                logger.warning(
                    "agent.budget.close_persist_task_failed",
                    error=str(exc),
                )
        logger.info("agent.budget.close_complete")
