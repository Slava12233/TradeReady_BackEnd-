"""Circuit Breaker — Component 7.

Tracks daily realized PnL per account in Redis and halts trading when the
daily loss limit is reached.

Logic
-----
1. After every trade fills, the caller invokes :meth:`CircuitBreaker.record_trade_pnl`
   with the realized PnL for that fill.
2. The breaker accumulates the daily total in Redis and checks it against
   ``starting_balance × daily_loss_limit_pct / 100``.
3. If the loss threshold is breached the breaker marks itself *tripped* in
   Redis; all subsequent :meth:`is_tripped` calls return ``True`` until reset.
4. At 00:00 UTC a Celery beat task calls :meth:`reset_all` to delete all
   circuit-breaker keys so fresh daily totals start accumulating.

Redis schema — one hash per account
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Key    : ``circuit_breaker:{account_id}``
Fields :
  ``daily_pnl``   — running sum of realized PnL for today (Decimal string)
  ``tripped``     — ``"1"`` when breaker is tripped, absent / ``"0"`` otherwise
  ``tripped_at``  — ISO-8601 UTC timestamp of when the breaker tripped, or absent

TTL    : automatically set to the number of seconds remaining until the *next*
         midnight UTC at the time of each write.  This ensures keys self-clean
         even if the Celery reset task is delayed.

Example::

    cb = CircuitBreaker(
        redis=redis_client,
        starting_balance=Decimal("10000"),
        daily_loss_limit_pct=Decimal("20"),
    )
    await cb.record_trade_pnl(account_id, Decimal("-500"))
    if await cb.is_tripped(account_id):
        raise DailyLossLimitError(account_id=account_id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncIterator
from uuid import UUID

import redis.asyncio as aioredis

from src.utils.exceptions import CacheError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_QUANTIZE = Decimal("0.00000001")

# Redis field names inside the circuit_breaker:{account_id} hash
_FIELD_DAILY_PNL = "daily_pnl"
_FIELD_TRIPPED = "tripped"
_FIELD_TRIPPED_AT = "tripped_at"

# Key prefix — matches the pattern documented in context.md
_KEY_PREFIX = "circuit_breaker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cb_key(account_id: UUID) -> str:
    """Return the Redis key for the circuit-breaker hash of *account_id*."""
    return f"{_KEY_PREFIX}:{account_id}"


def _seconds_until_midnight_utc() -> int:
    """Return the number of whole seconds from now until the next 00:00 UTC.

    Used to set the TTL on circuit-breaker keys so they self-expire at the
    daily reset boundary even if the Celery task is delayed.

    Returns:
        Seconds until midnight UTC (always ≥ 1).
    """
    now = datetime.now(tz=timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Roll forward to the *next* midnight, not today's already-passed one.
    from datetime import timedelta  # noqa: PLC0415 — local import to keep module top clean

    next_midnight = midnight + timedelta(days=1)
    delta = next_midnight - now
    return max(1, int(delta.total_seconds()))


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Per-account daily PnL tracker that halts trading on excessive losses.

    All state is stored in Redis.  No database writes occur inside this class,
    keeping it fast and decoupled from the DB session lifecycle.

    Args:
        redis:                Async Redis client.
        starting_balance:     The account's starting balance (used to convert
                              the loss-limit *percentage* to an absolute USD
                              threshold).  Callers should pass the account's
                              ``starting_balance`` column value.
        daily_loss_limit_pct: Loss threshold as a percentage of
                              *starting_balance* (e.g. ``Decimal("20")`` means
                              a 20 % daily loss halts trading).

    Example::

        cb = CircuitBreaker(redis=r, starting_balance=Decimal("10000"),
                            daily_loss_limit_pct=Decimal("20"))
        await cb.record_trade_pnl(account_id, Decimal("-1500"))
        tripped = await cb.is_tripped(account_id)
    """

    def __init__(
        self,
        *,
        redis: aioredis.Redis,  # type: ignore[type-arg]
        starting_balance: Decimal,
        daily_loss_limit_pct: Decimal,
    ) -> None:
        self._redis = redis
        self._starting_balance = starting_balance
        self._daily_loss_limit_pct = daily_loss_limit_pct
        self._loss_threshold: Decimal = (
            starting_balance * daily_loss_limit_pct / _HUNDRED
        ).quantize(_QUANTIZE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def record_trade_pnl(
        self,
        account_id: UUID,
        pnl: Decimal,
    ) -> None:
        """Add *pnl* to the account's running daily total and trip the breaker
        if the loss threshold is exceeded.

        This method is idempotent with respect to the *tripped* flag — once
        tripped it stays tripped until :meth:`reset_all` is called.

        Args:
            account_id: The account that just executed a trade.
            pnl:        Realized PnL for this fill.  Negative values represent
                        losses; positive values represent profits.

        Raises:
            CacheError: On unexpected Redis failures.

        Example::

            await cb.record_trade_pnl(account_id, Decimal("-200.50"))
        """
        key = _cb_key(account_id)
        ttl = _seconds_until_midnight_utc()

        try:
            # Use a pipeline to keep the read-modify-write atomic enough for
            # our purposes.  Full WATCH/MULTI/EXEC is not required because the
            # worst case is a slightly stale daily_pnl value across concurrent
            # requests — the loss limit acts as a safety threshold, not an
            # exact accounting system.
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.hincrbyfloat(key, _FIELD_DAILY_PNL, float(pnl))
                pipe.expire(key, ttl)
                results = await pipe.execute()

            new_daily_pnl = Decimal(str(results[0])).quantize(_QUANTIZE)

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "circuit_breaker.record_trade_pnl.redis_error",
                extra={"account_id": str(account_id), "pnl": str(pnl), "error": str(exc)},
            )
            raise CacheError("Failed to record trade PnL in circuit breaker.") from exc

        logger.debug(
            "circuit_breaker.record_trade_pnl",
            extra={
                "account_id": str(account_id),
                "pnl": str(pnl),
                "daily_pnl": str(new_daily_pnl),
                "loss_threshold": str(self._loss_threshold),
            },
        )

        # Trip the breaker when cumulative loss exceeds the threshold
        if new_daily_pnl < _ZERO and abs(new_daily_pnl) >= self._loss_threshold:
            await self._trip(account_id, new_daily_pnl)

    async def is_tripped(self, account_id: UUID) -> bool:
        """Return ``True`` if the circuit breaker is currently tripped for
        *account_id*.

        A missing key is treated as *not tripped* — a new day or a first-ever
        trade always starts with the breaker open.

        Args:
            account_id: The account to check.

        Returns:
            ``True`` when trading should be halted; ``False`` otherwise.

        Raises:
            CacheError: On unexpected Redis failures.

        Example::

            if await cb.is_tripped(account_id):
                raise DailyLossLimitError(account_id=account_id)
        """
        key = _cb_key(account_id)
        try:
            value = await self._redis.hget(key, _FIELD_TRIPPED)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "circuit_breaker.is_tripped.redis_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise CacheError("Failed to read circuit breaker state.") from exc

        return value == b"1" or value == "1"

    async def get_daily_pnl(self, account_id: UUID) -> Decimal:
        """Return the account's accumulated realized PnL for today (UTC).

        Returns ``Decimal("0")`` if no trades have been recorded yet today
        (i.e. the Redis key does not exist or ``daily_pnl`` field is absent).

        Args:
            account_id: The account to query.

        Returns:
            Running daily PnL as a :class:`~decimal.Decimal`.  Negative means
            net loss; positive means net profit.

        Raises:
            CacheError: On unexpected Redis failures.

        Example::

            pnl = await cb.get_daily_pnl(account_id)
            print(f"Today's PnL: {pnl} USDT")
        """
        key = _cb_key(account_id)
        try:
            value = await self._redis.hget(key, _FIELD_DAILY_PNL)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "circuit_breaker.get_daily_pnl.redis_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise CacheError("Failed to read daily PnL from circuit breaker.") from exc

        if value is None:
            return _ZERO

        try:
            return Decimal(str(value)).quantize(_QUANTIZE)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "circuit_breaker.get_daily_pnl.parse_error",
                extra={"account_id": str(account_id), "raw_value": str(value)},
            )
            raise CacheError(
                f"Failed to parse daily PnL value from Redis: {value!r}"
            ) from exc

    async def reset_all(self) -> None:
        """Delete all ``circuit_breaker:*`` keys, resetting every account.

        This is called once per day by the Celery beat task at 00:00 UTC.
        Individual account keys also have a TTL set at write time so they
        self-clean even if this method is not called on schedule.

        The deletion is done in batches of 1 000 keys using ``SCAN`` to avoid
        blocking the Redis event loop on instances with many accounts.

        Raises:
            CacheError: On unexpected Redis failures.

        Example::

            await cb.reset_all()  # typically called by Celery beat at 00:00 UTC
        """
        pattern = f"{_KEY_PREFIX}:*"
        deleted = 0

        try:
            async for key in self._scan_keys(pattern):
                await self._redis.delete(key)
                deleted += 1
        except CacheError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "circuit_breaker.reset_all.redis_error",
                extra={"error": str(exc)},
            )
            raise CacheError("Failed to reset circuit breakers.") from exc

        logger.info(
            "circuit_breaker.reset_all.complete",
            extra={"keys_deleted": deleted},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _trip(self, account_id: UUID, daily_pnl: Decimal) -> None:
        """Mark the breaker as tripped in Redis.

        Args:
            account_id: The account to trip.
            daily_pnl:  The PnL value that triggered the trip.
        """
        key = _cb_key(account_id)
        tripped_at = datetime.now(tz=timezone.utc).isoformat()
        ttl = _seconds_until_midnight_utc()

        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.hset(  # type: ignore[misc]
                    key,
                    mapping={
                        _FIELD_TRIPPED: "1",
                        _FIELD_TRIPPED_AT: tripped_at,
                    },
                )
                pipe.expire(key, ttl)
                await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "circuit_breaker.trip.redis_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise CacheError("Failed to trip circuit breaker.") from exc

        logger.warning(
            "circuit_breaker.tripped",
            extra={
                "account_id": str(account_id),
                "daily_pnl": str(daily_pnl),
                "loss_threshold": str(self._loss_threshold),
                "tripped_at": tripped_at,
            },
        )

    async def _scan_keys(self, pattern: str) -> AsyncIterator[bytes]:
        """Yield Redis keys matching *pattern* using non-blocking SCAN.

        Args:
            pattern: Redis SCAN pattern (e.g. ``"circuit_breaker:*"``).

        Yields:
            Raw key bytes from Redis.
        """
        cursor: int = 0
        while True:
            try:
                cursor, keys = await self._redis.scan(
                    cursor=cursor, match=pattern, count=1000
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "circuit_breaker.scan_keys.redis_error",
                    extra={"pattern": pattern, "error": str(exc)},
                )
                raise CacheError("Failed to scan circuit breaker keys.") from exc

            for key in keys:
                yield key

            if cursor == 0:
                break
