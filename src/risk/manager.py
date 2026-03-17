"""Risk Manager — Component 7.

Enforces trading limits. Called by the Order Engine before every order
execution.  All checks short-circuit on the first failure so the response
message is always specific to the *first* violated rule.

Default limits (configurable per account via the ``risk_profile`` JSONB
column on the ``accounts`` table):

+-----------------------------+-------+----------------------------------------------+
| Limit key                   | Value | Description                                  |
+=============================+=======+==============================================+
| ``max_position_size_pct``   | 25    | Single position max % of total equity        |
| ``max_open_orders``         | 50    | Max concurrent pending orders                |
| ``daily_loss_limit_pct``    | 20    | Halt if daily loss > % of starting balance   |
| ``min_order_size_usd``      | 1.0   | Minimum order value in USD                   |
| ``max_order_size_pct``      | 50    | Single order max % of available USDT balance |
| ``order_rate_limit``        | 100   | Max orders placed per minute                 |
+-----------------------------+-------+----------------------------------------------+

Validation chain (short-circuit on first failure):

1. Account is active (not suspended or archived).
2. Daily loss limit not exceeded (delegates to CircuitBreaker / trade_repo).
3. Order rate limit not exceeded (Redis INCR sliding window).
4. Order size >= minimum USD value.
5. Order size <= maximum % of available USDT balance.
6. Resulting position <= maximum % of total equity.
7. Open orders count <= maximum.
8. Sufficient available balance for the trade.

Example::

    manager = RiskManager(
        redis=redis_client,
        price_cache=price_cache,
        balance_manager=balance_manager,
        account_repo=account_repo,
        order_repo=order_repo,
        trade_repo=trade_repo,
        settings=get_settings(),
    )
    result = await manager.validate_order(account_id, order)
    if not result.approved:
        raise OrderRejectedError(result.rejection_reason, reason=result.rejection_reason)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog

from src.accounts.balance_manager import BalanceManager
from src.cache.price_cache import PriceCache
from src.config import Settings
from src.database.models import Account, Agent
from src.database.repositories.account_repo import AccountRepository
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.trade_repo import TradeRepository
from src.order_engine.validators import OrderRequest
from src.utils.exceptions import (
    CacheError,
    DatabaseError,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Default risk limits
# ---------------------------------------------------------------------------

_DEFAULT_MAX_POSITION_SIZE_PCT: Decimal = Decimal("25")
_DEFAULT_MAX_OPEN_ORDERS: int = 50
_DEFAULT_DAILY_LOSS_LIMIT_PCT: Decimal = Decimal("20")
_DEFAULT_MIN_ORDER_SIZE_USD: Decimal = Decimal("1.0")
_DEFAULT_MAX_ORDER_SIZE_PCT: Decimal = Decimal("50")
_DEFAULT_ORDER_RATE_LIMIT: int = 100

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

# Redis key template for the order rate-limit sliding window.
# Pattern: rate_limit:{account_id}:orders:{minute_bucket}
_RATE_LIMIT_KEY_TEMPLATE = "rate_limit:{account_id}:orders:{minute}"
_RATE_LIMIT_TTL_SECONDS = 120  # 2 minutes — covers the current + prior bucket


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Effective risk limits for a single account.

    These values are the *merged* result of the platform defaults and the
    per-account ``risk_profile`` JSONB overrides.  All numeric fields use
    ``Decimal`` for exact comparisons.

    Attributes:
        max_position_size_pct:  Max single-position equity percentage (0–100).
        max_open_orders:        Maximum number of simultaneously open orders.
        daily_loss_limit_pct:   Halt threshold as % of ``starting_balance``.
        min_order_size_usd:     Minimum order value in USD.
        max_order_size_pct:     Max single-order percentage of available USDT.
        order_rate_limit:       Maximum orders placed per 60-second window.
    """

    max_position_size_pct: Decimal = _DEFAULT_MAX_POSITION_SIZE_PCT
    max_open_orders: int = _DEFAULT_MAX_OPEN_ORDERS
    daily_loss_limit_pct: Decimal = _DEFAULT_DAILY_LOSS_LIMIT_PCT
    min_order_size_usd: Decimal = _DEFAULT_MIN_ORDER_SIZE_USD
    max_order_size_pct: Decimal = _DEFAULT_MAX_ORDER_SIZE_PCT
    order_rate_limit: int = _DEFAULT_ORDER_RATE_LIMIT


@dataclass(slots=True)
class RiskCheckResult:
    """Result of the 8-step :meth:`RiskManager.validate_order` chain.

    Attributes:
        approved:         ``True`` when all checks passed; ``False`` on the
                          first failure.
        rejection_reason: Machine-readable code for the first failed check,
                          or ``None`` when ``approved`` is ``True``.
                          Possible values: ``"account_not_active"``,
                          ``"daily_loss_limit"``, ``"rate_limit_exceeded"``,
                          ``"order_too_small"``, ``"order_too_large"``,
                          ``"position_limit_exceeded"``,
                          ``"max_open_orders_exceeded"``,
                          ``"insufficient_balance"``.
        details:          Optional structured payload with numeric context
                          (e.g. current vs. max values) for logging/debugging.

    Example::

        result = RiskCheckResult(approved=False, rejection_reason="order_too_small")
        assert not result.approved
    """

    approved: bool
    rejection_reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls) -> RiskCheckResult:
        """Return an approved result with no rejection reason."""
        return cls(approved=True)

    @classmethod
    def reject(
        cls,
        reason: str,
        **details: Any,  # noqa: ANN401
    ) -> RiskCheckResult:
        """Return a rejected result with the given reason and optional details.

        Args:
            reason:  Short machine-readable rejection code.
            **details: Arbitrary key-value pairs included in the details dict
                       (e.g. ``current=26, max=25``).
        """
        return cls(approved=False, rejection_reason=reason, details=dict(details))


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------


class RiskManager:
    """8-step order validation chain for the trading engine.

    All checks are read-only: no balance mutations or order writes occur
    inside this class.  The manager reads account state, balances, open-order
    counts, daily PnL, and current prices to decide whether an order may
    proceed.

    Args:
        redis:           Async Redis client used for the rate-limit window.
        price_cache:     :class:`~src.cache.price_cache.PriceCache` for
                         current prices.
        balance_manager: :class:`~src.accounts.balance_manager.BalanceManager`
                         for balance reads.
        account_repo:    :class:`~src.database.repositories.account_repo.AccountRepository`
                         to fetch account status and risk_profile.
        order_repo:      :class:`~src.database.repositories.order_repo.OrderRepository`
                         to count open orders.
        trade_repo:      :class:`~src.database.repositories.trade_repo.TradeRepository`
                         to sum today's realized PnL.
        settings:        Application :class:`~src.config.Settings`.

    Example::

        result = await manager.validate_order(account_id, order_request)
        if not result.approved:
            raise OrderRejectedError(reason=result.rejection_reason)
    """

    def __init__(
        self,
        *,
        redis: aioredis.Redis,  # type: ignore[type-arg]
        price_cache: PriceCache,
        balance_manager: BalanceManager,
        account_repo: AccountRepository,
        order_repo: OrderRepository,
        trade_repo: TradeRepository,
        settings: Settings,
    ) -> None:
        self._redis = redis
        self._price_cache = price_cache
        self._balance_manager = balance_manager
        self._account_repo = account_repo
        self._order_repo = order_repo
        self._trade_repo = trade_repo
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate_order(
        self,
        account_id: UUID,
        order: OrderRequest,
        *,
        agent: Agent | None = None,
    ) -> RiskCheckResult:
        """Run the 8-step risk validation chain against *order*.

        The chain short-circuits on the first failure and returns a
        :class:`RiskCheckResult` with ``approved=False`` and a specific
        ``rejection_reason``.  If all checks pass, ``approved=True`` is
        returned.

        Validation steps (in order):

        1. **account_active** — account must have ``status="active"``.
        2. **daily_loss** — today's realized PnL must not breach the daily
           loss threshold.
        3. **rate_limit** — orders placed in the last 60 seconds must be
           below ``order_rate_limit``.
        4. **min_size** — estimated order value (qty × current price) must be
           ≥ ``min_order_size_usd``.
        5. **max_size** — estimated order value must be ≤
           ``max_order_size_pct`` % of available USDT balance.
        6. **position_limit** — the resulting position value must be ≤
           ``max_position_size_pct`` % of total equity.
        7. **open_orders** — open order count must be < ``max_open_orders``.
        8. **balance** — account must have sufficient funds for the trade.

        Args:
            account_id: The account placing the order.
            order:      The validated :class:`~src.order_engine.validators.OrderRequest`.
            agent:      Optional :class:`~src.database.models.Agent` whose
                        ``risk_profile`` and ``starting_balance`` override
                        account-level defaults.

        Returns:
            :class:`RiskCheckResult` with ``approved=True`` or details of
            the first failed check.

        Raises:
            AccountNotFoundError: If the account does not exist.
            DatabaseError:        On unexpected database failures.
            CacheError:           On unexpected Redis failures.

        Example::

            result = await manager.validate_order(account_id, order_req, agent=my_agent)
            if not result.approved:
                logger.warning("order.rejected", extra={"reason": result.rejection_reason})
        """
        account = await self._account_repo.get_by_id(account_id)
        limits = self._build_risk_limits(account, agent=agent)
        agent_id = agent.id if agent is not None else None

        # Determine starting balance for daily loss check
        starting_balance_override: Decimal | None = None
        if agent is not None and agent.starting_balance is not None:
            starting_balance_override = Decimal(str(agent.starting_balance))

        # ── Step 1: Account active ────────────────────────────────────────
        result = self._check_account_active(account)
        if not result.approved:
            return result

        # ── Step 2: Daily loss limit ──────────────────────────────────────
        result = await self._check_daily_loss(
            account, limits, agent_id=agent_id, starting_balance_override=starting_balance_override
        )
        if not result.approved:
            return result

        # ── Step 3: Order rate limit (read-only) ─────────────────────────
        # The counter is incremented AFTER all checks pass (see end of chain)
        # so that rejected orders do not consume a rate-limit token.
        result, rate_limit_key = await self._check_rate_limit(account_id, limits, agent_id=agent_id)
        if not result.approved:
            return result

        # ── Fetch current price once — reused by steps 4, 5, 6, 8 ───────
        current_price = await self._price_cache.get_price(order.symbol)
        if current_price is None:
            # If price is unavailable we cannot validate order size or
            # position limits — reject conservatively.
            logger.warning(
                "risk.price_unavailable",
                account_id=str(account_id),
                symbol=order.symbol,
            )
            return RiskCheckResult.reject(
                "price_unavailable",
                symbol=order.symbol,
            )

        estimated_value = (order.quantity * current_price).quantize(Decimal("0.00000001"))

        # Compute real total portfolio equity once — reused by steps 5 and 6
        # to avoid extra DB/cache round-trips and to use correct denominator.
        total_equity = await self._compute_total_equity(account_id, order.symbol, current_price, agent_id=agent_id)

        # ── Step 4: Minimum order size ────────────────────────────────────
        result = self._check_min_order_size(estimated_value, limits)
        if not result.approved:
            return result

        # ── Step 5: Maximum order size % ─────────────────────────────────
        result = await self._check_max_order_size(account_id, estimated_value, order, limits, total_equity)
        if not result.approved:
            return result

        # ── Step 6: Maximum position % ───────────────────────────────────
        result = await self._check_position_limit(
            account_id, order, estimated_value, limits, total_equity, current_price, agent_id=agent_id
        )
        if not result.approved:
            return result

        # ── Step 7: Maximum open orders ───────────────────────────────────
        result = await self._check_open_orders(account_id, limits, agent_id=agent_id)
        if not result.approved:
            return result

        # ── Step 8: Sufficient balance ────────────────────────────────────
        result = await self._check_sufficient_balance(account_id, order, estimated_value, agent_id=agent_id)
        if not result.approved:
            return result

        # ── All checks passed — consume the rate-limit token now ─────────
        await self._consume_rate_limit_token(rate_limit_key)

        logger.debug(
            "risk.validate_order.approved",
            account_id=str(account_id),
            symbol=order.symbol,
            side=order.side,
            quantity=str(order.quantity),
            estimated_value_usd=str(estimated_value),
        )
        return RiskCheckResult.ok()

    async def check_daily_loss(
        self,
        account_id: UUID,
        *,
        agent: Agent | None = None,
    ) -> bool:
        """Return ``True`` if the account/agent is within its daily loss limit.

        Args:
            account_id: The account to check.
            agent:      Optional agent whose ``starting_balance`` and
                        ``risk_profile`` override account-level defaults.

        Returns:
            ``True`` when the account has not yet hit its loss threshold;
            ``False`` when trading should be halted.

        Raises:
            AccountNotFoundError: If the account does not exist.
            DatabaseError:        On unexpected database failures.

        Example::

            if not await manager.check_daily_loss(account_id, agent=my_agent):
                raise DailyLossLimitError(account_id=account_id)
        """
        account = await self._account_repo.get_by_id(account_id)
        limits = self._build_risk_limits(account, agent=agent)
        agent_id = agent.id if agent is not None else None
        starting_balance_override: Decimal | None = None
        if agent is not None and agent.starting_balance is not None:
            starting_balance_override = Decimal(str(agent.starting_balance))
        result = await self._check_daily_loss(
            account, limits, agent_id=agent_id, starting_balance_override=starting_balance_override
        )
        return result.approved

    async def get_risk_limits(
        self,
        account_id: UUID,
        *,
        agent: Agent | None = None,
    ) -> RiskLimits:
        """Return the effective :class:`RiskLimits` for *account_id*.

        Merges platform defaults with per-account overrides stored in the
        ``risk_profile`` JSONB column.  When an *agent* is provided, its
        ``risk_profile`` takes precedence over the account's.

        Args:
            account_id: The account whose limits to retrieve.
            agent:      Optional agent whose ``risk_profile`` overrides
                        account-level settings.

        Returns:
            A :class:`RiskLimits` instance with all fields populated.

        Raises:
            AccountNotFoundError: If the account does not exist.
            DatabaseError:        On unexpected database failures.

        Example::

            limits = await manager.get_risk_limits(account_id, agent=my_agent)
            print(limits.max_open_orders)  # 50 (default) or per-agent value
        """
        account = await self._account_repo.get_by_id(account_id)
        return self._build_risk_limits(account, agent=agent)

    async def update_risk_limits(
        self,
        account_id: UUID,
        limits: RiskLimits,
    ) -> None:
        """Persist updated risk limits into the account's ``risk_profile`` JSON.

        Only fields that differ from the defaults are stored; this keeps the
        JSONB lean and allows future default changes to propagate to accounts
        that have not explicitly overridden a value.

        Args:
            account_id: The account to update.
            limits:     New :class:`RiskLimits` (caller must validate inputs
                        before passing here).

        Raises:
            AccountNotFoundError: If the account does not exist.
            DatabaseError:        On unexpected database failures.

        Example::

            new_limits = RiskLimits(max_open_orders=20, daily_loss_limit_pct=Decimal("10"))
            await manager.update_risk_limits(account_id, new_limits)
        """
        account = await self._account_repo.get_by_id(account_id)

        profile: dict[str, Any] = dict(account.risk_profile or {})
        profile["max_position_size_pct"] = str(limits.max_position_size_pct)
        profile["max_open_orders"] = limits.max_open_orders
        profile["daily_loss_limit_pct"] = str(limits.daily_loss_limit_pct)
        profile["min_order_size_usd"] = str(limits.min_order_size_usd)
        profile["max_order_size_pct"] = str(limits.max_order_size_pct)
        profile["order_rate_limit"] = limits.order_rate_limit

        await self._account_repo.update_risk_profile(account_id, profile)
        logger.info(
            "risk.limits_updated",
            account_id=str(account_id),
            profile=profile,
        )

    # ------------------------------------------------------------------
    # Private helpers — one method per validation step
    # ------------------------------------------------------------------

    def _build_risk_limits(self, account: Account, *, agent: Agent | None = None) -> RiskLimits:
        """Merge platform defaults with risk profile overrides.

        When *agent* is provided and has a non-empty ``risk_profile``, the
        agent's profile takes precedence over the account's.  This ensures
        each agent can have independent risk configuration.

        Args:
            account: Loaded :class:`~src.database.models.Account` instance.
            agent:   Optional :class:`~src.database.models.Agent` whose
                     ``risk_profile`` overrides account-level settings.

        Returns:
            :class:`RiskLimits` with per-agent/account overrides applied.
        """
        # Agent risk_profile takes precedence when present
        if agent is not None and agent.risk_profile:
            profile: dict[str, Any] = dict(agent.risk_profile)
        else:
            profile = account.risk_profile or {}

        def _dec(key: str, default: Decimal) -> Decimal:
            raw = profile.get(key)
            if raw is None:
                return default
            try:
                return Decimal(str(raw))
            except Exception:  # noqa: BLE001
                logger.warning(
                    "risk.invalid_profile_value",
                    account_id=str(account.id),
                    key=key,
                    value=raw,
                )
                return default

        def _int(key: str, default: int) -> int:
            raw = profile.get(key)
            if raw is None:
                return default
            try:
                return int(raw)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "risk.invalid_profile_value",
                    account_id=str(account.id),
                    key=key,
                    value=raw,
                )
                return default

        return RiskLimits(
            max_position_size_pct=_dec("max_position_size_pct", _DEFAULT_MAX_POSITION_SIZE_PCT),
            max_open_orders=_int("max_open_orders", _DEFAULT_MAX_OPEN_ORDERS),
            daily_loss_limit_pct=_dec("daily_loss_limit_pct", _DEFAULT_DAILY_LOSS_LIMIT_PCT),
            min_order_size_usd=_dec("min_order_size_usd", _DEFAULT_MIN_ORDER_SIZE_USD),
            max_order_size_pct=_dec("max_order_size_pct", _DEFAULT_MAX_ORDER_SIZE_PCT),
            order_rate_limit=_int("order_rate_limit", _DEFAULT_ORDER_RATE_LIMIT),
        )

    # ── Step 1 ─────────────────────────────────────────────────────────────────

    def _check_account_active(self, account: Account) -> RiskCheckResult:
        """Step 1: Verify the account has ``status="active"``."""
        if account.status != "active":
            logger.info(
                "risk.check.account_not_active",
                account_id=str(account.id),
                status=account.status,
            )
            return RiskCheckResult.reject(
                "account_not_active",
                status=account.status,
            )
        return RiskCheckResult.ok()

    # ── Step 2 ─────────────────────────────────────────────────────────────────

    async def _check_daily_loss(
        self,
        account: Account,
        limits: RiskLimits,
        *,
        agent_id: UUID | None = None,
        starting_balance_override: Decimal | None = None,
    ) -> RiskCheckResult:
        """Step 2: Verify the account/agent's daily realized PnL is within limits."""
        try:
            daily_pnl = Decimal(str(await self._trade_repo.sum_daily_realized_pnl(account.id, agent_id=agent_id)))
        except DatabaseError:
            raise
        except Exception as exc:
            logger.exception(
                "risk.check_daily_loss.unexpected_error",
                account_id=str(account.id),
                error=str(exc),
            )
            raise DatabaseError("Failed to check daily loss limit.") from exc

        starting_balance = starting_balance_override or Decimal(str(account.starting_balance))
        loss_limit = (starting_balance * limits.daily_loss_limit_pct / _HUNDRED).quantize(Decimal("0.00000001"))

        # daily_pnl is negative when in loss; breach when loss > limit
        if daily_pnl < _ZERO and abs(daily_pnl) >= loss_limit:
            logger.warning(
                "risk.check.daily_loss_limit",
                account_id=str(account.id),
                daily_pnl=str(daily_pnl),
                loss_limit=str(loss_limit),
                starting_balance=str(starting_balance),
            )
            return RiskCheckResult.reject(
                "daily_loss_limit",
                daily_pnl=str(daily_pnl),
                loss_limit=str(loss_limit),
                loss_limit_pct=str(limits.daily_loss_limit_pct),
            )
        return RiskCheckResult.ok()

    # ── Step 3 ─────────────────────────────────────────────────────────────────

    async def _check_rate_limit(
        self,
        account_id: UUID,
        limits: RiskLimits,
        *,
        agent_id: UUID | None = None,
    ) -> tuple[RiskCheckResult, str]:
        """Step 3: Read-only check of the per-minute order rate limit.

        Returns the current count and the Redis key so the caller can
        increment the counter *after* all other checks pass — rejected
        orders therefore do not consume a rate-limit token.

        When *agent_id* is provided, the rate limit is scoped to the agent
        rather than the account, so each agent gets its own rate limit bucket.

        Uses a minute-bucket key so the window resets naturally at each new
        UTC minute.  TTL is set to 120 s to cover both the current and the
        immediately preceding bucket while avoiding unbounded key growth.

        Returns:
            A tuple of (RiskCheckResult, rate_limit_key).
        """
        now_utc = datetime.now(tz=UTC)
        minute_bucket = now_utc.strftime("%Y%m%d%H%M")
        # Scope rate limit to agent when available, otherwise to account
        scope_id = str(agent_id) if agent_id is not None else str(account_id)
        key = _RATE_LIMIT_KEY_TEMPLATE.format(
            account_id=scope_id,
            minute=minute_bucket,
        )

        try:
            raw = await self._redis.get(key)
            current_count: int = int(raw) if raw is not None else 0
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "risk.rate_limit.redis_error",
                account_id=str(account_id),
                error=str(exc),
            )
            raise CacheError("Failed to check order rate limit.") from exc

        if current_count >= limits.order_rate_limit:
            logger.warning(
                "risk.check.rate_limit_exceeded",
                account_id=str(account_id),
                current_count=current_count,
                limit=limits.order_rate_limit,
                minute_bucket=minute_bucket,
            )
            return RiskCheckResult.reject(
                "rate_limit_exceeded",
                current_count=current_count,
                limit=limits.order_rate_limit,
            ), key
        return RiskCheckResult.ok(), key

    async def _consume_rate_limit_token(self, key: str) -> None:
        """Increment the rate-limit counter for a successfully validated order.

        Called only after all 8 validation steps pass so that rejected orders
        do not consume a token.

        Args:
            key: The rate-limit Redis key returned by :meth:`_check_rate_limit`.

        Raises:
            CacheError: On unexpected Redis failures.
        """
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.incr(key)
                pipe.expire(key, _RATE_LIMIT_TTL_SECONDS)
                await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "risk.rate_limit.consume_error",
                key=key,
                error=str(exc),
            )
            raise CacheError("Failed to increment order rate limit counter.") from exc

    # ── Step 4 ─────────────────────────────────────────────────────────────────

    def _check_min_order_size(
        self,
        estimated_value: Decimal,
        limits: RiskLimits,
    ) -> RiskCheckResult:
        """Step 4: Ensure the order value meets the minimum USD threshold."""
        if estimated_value < limits.min_order_size_usd:
            logger.info(
                "risk.check.order_too_small",
                estimated_value=str(estimated_value),
                min_order_size_usd=str(limits.min_order_size_usd),
            )
            return RiskCheckResult.reject(
                "order_too_small",
                estimated_value=str(estimated_value),
                min_order_size_usd=str(limits.min_order_size_usd),
            )
        return RiskCheckResult.ok()

    # ── Step 5 ─────────────────────────────────────────────────────────────────

    async def _check_max_order_size(
        self,
        account_id: UUID,
        estimated_value: Decimal,
        order: OrderRequest,
        limits: RiskLimits,
        total_equity: Decimal,
    ) -> RiskCheckResult:
        """Step 5: Ensure the order value does not exceed max % of total portfolio equity.

        Uses the full portfolio value (USDT + all held assets at live prices) as
        the denominator so the limit reflects true account size, not just remaining
        USDT.  This prevents false rejections after buying multiple coins when the
        USDT balance is lower but total portfolio value is unchanged.
        """
        if total_equity <= _ZERO:
            # No equity at all; step 8 (sufficient balance) will catch this.
            return RiskCheckResult.ok()

        max_allowed_usd = (total_equity * limits.max_order_size_pct / _HUNDRED).quantize(Decimal("0.00000001"))

        if estimated_value > max_allowed_usd:
            logger.info(
                "risk.check.order_too_large",
                account_id=str(account_id),
                estimated_value=str(estimated_value),
                max_allowed_usd=str(max_allowed_usd),
                max_order_size_pct=str(limits.max_order_size_pct),
                total_equity=str(total_equity),
            )
            return RiskCheckResult.reject(
                "order_too_large",
                estimated_value=str(estimated_value),
                max_allowed_usd=str(max_allowed_usd),
                max_order_size_pct=str(limits.max_order_size_pct),
            )
        return RiskCheckResult.ok()

    # ── Step 6 ─────────────────────────────────────────────────────────────────

    async def _check_position_limit(
        self,
        account_id: UUID,
        order: OrderRequest,
        estimated_value: Decimal,
        limits: RiskLimits,
        total_equity: Decimal,
        current_price: Decimal,
        *,
        agent_id: UUID | None = None,
    ) -> RiskCheckResult:
        """Step 6: Ensure the resulting position won't exceed max % of total equity.

        Uses the full portfolio value pre-computed by :meth:`_compute_total_equity`
        so the percentage is relative to real account size across all holdings,
        not just remaining USDT.

        For a **sell** order the position shrinks, so no limit is breached.
        """
        if order.side == "sell":
            return RiskCheckResult.ok()

        if total_equity <= _ZERO:
            # Cannot compute percentage; step 8 will catch it.
            return RiskCheckResult.ok()

        symbol = order.symbol
        base_asset = symbol.removesuffix("USDT")
        base_balance = await self._balance_manager.get_balance(account_id, base_asset, agent_id=agent_id)
        existing_base = Decimal(str(base_balance.available)) if base_balance else _ZERO
        existing_position_value = (existing_base * current_price).quantize(Decimal("0.00000001"))

        new_position_value = existing_position_value + estimated_value
        new_position_pct = (new_position_value / total_equity * _HUNDRED).quantize(Decimal("0.01"))

        if new_position_pct > limits.max_position_size_pct:
            logger.info(
                "risk.check.position_limit_exceeded",
                account_id=str(account_id),
                symbol=symbol,
                new_position_pct=str(new_position_pct),
                max_position_size_pct=str(limits.max_position_size_pct),
                new_position_value=str(new_position_value),
                total_equity=str(total_equity),
            )
            return RiskCheckResult.reject(
                "position_limit_exceeded",
                new_position_pct=str(new_position_pct),
                max_position_size_pct=str(limits.max_position_size_pct),
                symbol=symbol,
            )
        return RiskCheckResult.ok()

    # ── Equity helper ──────────────────────────────────────────────────────────

    async def _compute_total_equity(
        self,
        account_id: UUID,
        current_symbol: str,
        current_price: Decimal,
        *,
        agent_id: UUID | None = None,
    ) -> Decimal:
        """Return total portfolio value in USDT by pricing all held assets.

        Fetches all balance rows in a single DB call, then prices each non-USDT
        asset via :attr:`_price_cache`.  The price of ``current_symbol`` is
        supplied directly to avoid a redundant cache lookup.

        Assets whose price cannot be resolved are excluded (conservative: lower
        equity → stricter limits, never looser).

        Args:
            account_id:     The account to evaluate.
            current_symbol: The symbol being ordered (e.g. ``"BTCUSDT"``).
            current_price:  Live price for ``current_symbol``.

        Returns:
            Total portfolio value in USDT, or ``Decimal("0")`` when no
            balance rows exist.
        """
        all_balances = await self._balance_manager.get_all_balances(account_id, agent_id=agent_id)
        total = _ZERO
        for balance in all_balances:
            total_qty = Decimal(str(balance.available)) + Decimal(str(balance.locked))
            if total_qty <= _ZERO:
                continue
            if balance.asset == "USDT":
                total += total_qty
            elif f"{balance.asset}USDT" == current_symbol:
                total += (total_qty * current_price).quantize(Decimal("0.00000001"))
            else:
                price = await self._price_cache.get_price(f"{balance.asset}USDT")
                if price is not None:
                    total += (total_qty * price).quantize(Decimal("0.00000001"))
        return total

    # ── Step 7 ─────────────────────────────────────────────────────────────────

    async def _check_open_orders(
        self,
        account_id: UUID,
        limits: RiskLimits,
        *,
        agent_id: UUID | None = None,
    ) -> RiskCheckResult:
        """Step 7: Ensure the account/agent has not hit the open-order cap."""
        if agent_id is not None:
            open_count = await self._order_repo.count_open_by_agent(agent_id)
        else:
            open_count = await self._order_repo.count_open_by_account(account_id)

        if open_count >= limits.max_open_orders:
            logger.info(
                "risk.check.max_open_orders_exceeded",
                account_id=str(account_id),
                open_count=open_count,
                max_open_orders=limits.max_open_orders,
            )
            return RiskCheckResult.reject(
                "max_open_orders_exceeded",
                open_count=open_count,
                max_open_orders=limits.max_open_orders,
            )
        return RiskCheckResult.ok()

    # ── Step 8 ─────────────────────────────────────────────────────────────────

    async def _check_sufficient_balance(
        self,
        account_id: UUID,
        order: OrderRequest,
        estimated_value: Decimal,
        *,
        agent_id: UUID | None = None,
    ) -> RiskCheckResult:
        """Step 8: Verify the account/agent can fund the trade.

        For **buy** orders: checks available USDT ≥ estimated cost (including
        fee buffer of ``trading_fee_pct``).
        For **sell** orders: checks available base-asset quantity ≥ order quantity.
        """
        fee_multiplier = Decimal("1") + (self._settings.trading_fee_pct / _HUNDRED)

        if order.side == "buy":
            required_usdt = (estimated_value * fee_multiplier).quantize(Decimal("0.00000001"))
            has_funds = await self._balance_manager.has_sufficient_balance(
                account_id,
                asset="USDT",
                amount=required_usdt,
                agent_id=agent_id,
            )
            if not has_funds:
                usdt_balance = await self._balance_manager.get_balance(account_id, "USDT", agent_id=agent_id)
                available = Decimal(str(usdt_balance.available)) if usdt_balance else _ZERO
                logger.info(
                    "risk.check.insufficient_balance",
                    account_id=str(account_id),
                    asset="USDT",
                    required=str(required_usdt),
                    available=str(available),
                )
                return RiskCheckResult.reject(
                    "insufficient_balance",
                    asset="USDT",
                    required=str(required_usdt),
                    available=str(available),
                )

        else:  # sell
            base_asset = order.symbol.removesuffix("USDT")
            has_funds = await self._balance_manager.has_sufficient_balance(
                account_id,
                asset=base_asset,
                amount=order.quantity,
                agent_id=agent_id,
            )
            if not has_funds:
                base_balance = await self._balance_manager.get_balance(account_id, base_asset, agent_id=agent_id)
                available = Decimal(str(base_balance.available)) if base_balance else _ZERO
                logger.info(
                    "risk.check.insufficient_balance",
                    account_id=str(account_id),
                    asset=base_asset,
                    required=str(order.quantity),
                    available=str(available),
                )
                return RiskCheckResult.reject(
                    "insufficient_balance",
                    asset=base_asset,
                    required=str(order.quantity),
                    available=str(available),
                )

        return RiskCheckResult.ok()
