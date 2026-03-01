"""Balance manager — service-layer operations on account balances.

:class:`BalanceManager` is the single authoritative entry-point for all
balance mutations performed by the trading engine and related services.
It wraps :class:`~src.database.repositories.balance_repo.BalanceRepository`
with higher-level semantics, including fee calculation, pre-flight balance
checks, and fully atomic buy/sell settlement.

Responsibilities
----------------
1. **credit** — add funds to an account / asset (e.g. after a sell fills).
2. **debit** — remove funds from an account / asset (e.g. deducting fees).
3. **lock** — move funds from ``available`` → ``locked`` (limit order reserve).
4. **unlock** — move funds from ``locked`` → ``available`` (order cancellation).
5. **has_sufficient_balance** — non-mutating pre-flight check used by
   validators and the risk manager.
6. **execute_trade** — atomic buy or sell settlement with fee deduction;
   handles both market orders (funds from ``available``) and limit orders
   (funds from ``locked``).

Dependency direction::

    OrderEngine / RiskManager → BalanceManager → BalanceRepository → DB

All methods participate in the **caller's** transaction; this class never
calls ``session.commit()``.

Example::

    async with session_factory() as session:
        mgr = BalanceManager(session, settings)
        await mgr.credit(account_id, asset="USDT", amount=Decimal("500"))
        await session.commit()
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.database.models import Balance
from src.database.repositories.balance_repo import BalanceRepository
from src.utils.exceptions import DatabaseError, InsufficientBalanceError, InputValidationError

log = structlog.get_logger(__name__)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TradeSettlement:
    """Result returned by :meth:`BalanceManager.execute_trade`.

    Attributes:
        quote_balance: Refreshed quote-asset :class:`~src.database.models.Balance`
            after settlement (e.g. USDT balance after a BTC buy/sell).
        base_balance: Refreshed base-asset :class:`~src.database.models.Balance`
            after settlement (e.g. BTC balance after a BTC buy/sell).
        fee_charged: Fee amount deducted from the quote asset (always positive).
        quote_amount: Gross quote amount before fee deduction.
        execution_price: Effective execution price after slippage.
    """

    quote_balance: Balance
    base_balance: Balance
    fee_charged: Decimal
    quote_amount: Decimal
    execution_price: Decimal


# ---------------------------------------------------------------------------
# BalanceManager
# ---------------------------------------------------------------------------


class BalanceManager:
    """Service-layer coordinator for all balance mutations.

    All write operations delegate to
    :class:`~src.database.repositories.balance_repo.BalanceRepository` and
    participate in the **caller's** SQLAlchemy transaction — no commits are
    issued here.

    Args:
        session:  An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        settings: Application :class:`~src.config.Settings` (provides
                  ``trading_fee_pct``).

    Example::

        async with session_factory() as session:
            mgr = BalanceManager(session, get_settings())
            has_funds = await mgr.has_sufficient_balance(
                account_id, asset="USDT", amount=Decimal("1000")
            )
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._repo = BalanceRepository(session)

    # ------------------------------------------------------------------
    # Simple credit / debit
    # ------------------------------------------------------------------

    async def credit(
        self,
        account_id: UUID,
        *,
        asset: str,
        amount: Decimal,
    ) -> Balance:
        """Add ``amount`` to the *available* balance for an account / asset.

        Creates the balance row if it does not yet exist (auto-zero creation
        is handled inside :class:`~src.database.repositories.balance_repo.BalanceRepository`).

        Args:
            account_id: The owning account's UUID.
            asset:      The asset ticker to credit (e.g. ``"USDT"``).
            amount:     Positive amount to add to ``available``.

        Returns:
            The refreshed :class:`~src.database.models.Balance` instance.

        Raises:
            InputValidationError:  If ``amount`` ≤ 0.
            DatabaseError:    On any unexpected database failure.

        Example::

            bal = await mgr.credit(account_id, asset="USDT", amount=Decimal("1000"))
        """
        if amount <= _ZERO:
            raise InputValidationError(
                f"credit amount must be positive, got {amount!r}",
                field="amount",
            )

        log.debug(
            "balance_manager.credit",
            account_id=str(account_id),
            asset=asset,
            amount=str(amount),
        )
        return await self._repo.update_available(account_id, asset, amount)

    async def debit(
        self,
        account_id: UUID,
        *,
        asset: str,
        amount: Decimal,
    ) -> Balance:
        """Subtract ``amount`` from the *available* balance for an account / asset.

        The database ``CHECK`` constraint ``available >= 0`` ensures this
        operation cannot take the balance below zero; such attempts surface as
        :class:`~src.utils.exceptions.InsufficientBalanceError`.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset ticker to debit (e.g. ``"USDT"``).
            amount:     Positive amount to subtract from ``available``.

        Returns:
            The refreshed :class:`~src.database.models.Balance` instance.

        Raises:
            InputValidationError:         If ``amount`` ≤ 0.
            InsufficientBalanceError: If available balance would go negative.
            DatabaseError:            On any unexpected database failure.

        Example::

            bal = await mgr.debit(account_id, asset="BTC", amount=Decimal("0.5"))
        """
        if amount <= _ZERO:
            raise InputValidationError(
                f"debit amount must be positive, got {amount!r}",
                field="amount",
            )

        log.debug(
            "balance_manager.debit",
            account_id=str(account_id),
            asset=asset,
            amount=str(amount),
        )
        return await self._repo.update_available(account_id, asset, -amount)

    # ------------------------------------------------------------------
    # Lock / unlock for limit orders
    # ------------------------------------------------------------------

    async def lock(
        self,
        account_id: UUID,
        *,
        asset: str,
        amount: Decimal,
    ) -> Balance:
        """Move ``amount`` from ``available`` → ``locked`` for an account / asset.

        Used when a **limit order** is accepted: the required funds are
        reserved so they cannot be used by a subsequent order while the
        limit is still pending.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset to lock (e.g. ``"USDT"`` for a buy order,
                        ``"BTC"`` for a sell order).
            amount:     Positive amount to move from available to locked.

        Returns:
            The refreshed :class:`~src.database.models.Balance` instance.

        Raises:
            InputValidationError:         If ``amount`` ≤ 0.
            InsufficientBalanceError: If ``available`` would go negative.
            DatabaseError:            On any unexpected database failure.

        Example::

            # Reserve 500 USDT while waiting for a limit-buy to fill
            bal = await mgr.lock(account_id, asset="USDT", amount=Decimal("500"))
        """
        if amount <= _ZERO:
            raise InputValidationError(
                f"lock amount must be positive, got {amount!r}",
                field="amount",
            )

        log.info(
            "balance_manager.lock",
            account_id=str(account_id),
            asset=asset,
            amount=str(amount),
        )
        return await self._repo.atomic_lock_funds(account_id, asset, amount)

    async def unlock(
        self,
        account_id: UUID,
        *,
        asset: str,
        amount: Decimal,
    ) -> Balance:
        """Move ``amount`` from ``locked`` → ``available`` for an account / asset.

        Used when a **pending limit order is cancelled**: the reserved funds
        are returned to the available pool.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset to unlock.
            amount:     Positive amount to move from locked back to available.

        Returns:
            The refreshed :class:`~src.database.models.Balance` instance.

        Raises:
            InputValidationError:         If ``amount`` ≤ 0.
            InsufficientBalanceError: If ``locked`` would go negative
                (releasing more than was locked).
            DatabaseError:            On any unexpected database failure.

        Example::

            # Release 500 USDT when a limit-buy is cancelled
            bal = await mgr.unlock(account_id, asset="USDT", amount=Decimal("500"))
        """
        if amount <= _ZERO:
            raise InputValidationError(
                f"unlock amount must be positive, got {amount!r}",
                field="amount",
            )

        log.info(
            "balance_manager.unlock",
            account_id=str(account_id),
            asset=asset,
            amount=str(amount),
        )
        return await self._repo.atomic_unlock_funds(account_id, asset, amount)

    # ------------------------------------------------------------------
    # Pre-flight check
    # ------------------------------------------------------------------

    async def has_sufficient_balance(
        self,
        account_id: UUID,
        *,
        asset: str,
        amount: Decimal,
        use_locked: bool = False,
    ) -> bool:
        """Return ``True`` if the account has at least ``amount`` of ``asset``.

        This is a **non-mutating** pre-flight check.  The risk manager and
        order validators call this before attempting any write so they can
        return a clean rejection rather than relying on constraint violations.

        Args:
            account_id:  The owning account's UUID.
            asset:       The asset ticker to check (e.g. ``"USDT"``).
            amount:      The required amount (must be > 0).
            use_locked:  If ``True``, check ``locked`` instead of
                         ``available``.  Defaults to ``False``.

        Returns:
            ``True`` if the checked pool (available or locked) is ≥ ``amount``;
            ``False`` otherwise (includes the case where no balance row exists).

        Raises:
            InputValidationError: If ``amount`` ≤ 0.
            DatabaseError:   On any unexpected database failure.

        Example::

            if not await mgr.has_sufficient_balance(account_id, asset="USDT", amount=order_cost):
                raise InsufficientBalanceError(asset="USDT", required=order_cost)
        """
        if amount <= _ZERO:
            raise InputValidationError(
                f"amount must be positive, got {amount!r}",
                field="amount",
            )

        balance = await self._repo.get(account_id, asset)
        if balance is None:
            return False

        pool = Decimal(str(balance.locked if use_locked else balance.available))
        return pool >= amount

    # ------------------------------------------------------------------
    # Balance read helpers
    # ------------------------------------------------------------------

    async def get_balance(self, account_id: UUID, asset: str) -> Balance | None:
        """Return the balance row for an account / asset pair, or ``None``.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset ticker (e.g. ``"USDT"``).

        Returns:
            The :class:`~src.database.models.Balance` instance, or ``None``
            if the account has never held this asset.

        Raises:
            DatabaseError: On any unexpected database failure.

        Example::

            bal = await mgr.get_balance(account_id, "BTC")
            if bal:
                print(bal.available)
        """
        return await self._repo.get(account_id, asset)

    async def get_all_balances(self, account_id: UUID) -> Sequence[Balance]:
        """Return all balance rows owned by an account.

        Args:
            account_id: The owning account's UUID.

        Returns:
            A (possibly empty) sequence of :class:`~src.database.models.Balance`
            instances ordered by asset ticker ascending.

        Raises:
            DatabaseError: On any unexpected database failure.

        Example::

            balances = await mgr.get_all_balances(account_id)
            for b in balances:
                print(b.asset, b.available)
        """
        return await self._repo.get_all(account_id)

    # ------------------------------------------------------------------
    # Atomic trade execution
    # ------------------------------------------------------------------

    def _calculate_fee(self, gross_quote: Decimal) -> Decimal:
        """Compute the trading fee on a gross quote amount.

        Fee = gross_quote × (trading_fee_pct / 100).  The result is
        quantized to 8 decimal places to match the ``NUMERIC(20, 8)``
        column precision.

        Args:
            gross_quote: The raw quote-asset cost or proceeds before the fee.

        Returns:
            The fee amount (always ≥ 0).
        """
        return (gross_quote * self._settings.trading_fee_pct / _HUNDRED).quantize(
            Decimal("0.00000001")
        )

    async def execute_trade(
        self,
        account_id: UUID,
        *,
        symbol: str,
        side: str,
        base_asset: str,
        quote_asset: str,
        quantity: Decimal,
        execution_price: Decimal,
        from_locked: bool = False,
    ) -> TradeSettlement:
        """Atomically settle a filled order, deducting fees and updating balances.

        For a **buy** (``side="buy"``):
        - Gross quote cost = ``quantity × execution_price``
        - Fee = ``gross_cost × trading_fee_pct / 100``
        - Total quote deducted = ``gross_cost + fee``
        - Base credited = ``quantity``

        For a **sell** (``side="sell"``):
        - Gross quote proceeds = ``quantity × execution_price``
        - Fee = ``gross_proceeds × trading_fee_pct / 100``
        - Net quote credited = ``gross_proceeds − fee``
        - Base deducted = ``quantity``

        When ``from_locked=True`` (limit order), the quote (buy) or base
        (sell) asset is deducted from the ``locked`` pool rather than the
        ``available`` pool — the funds were pre-reserved when the order was
        accepted.

        All balance updates run inside the **caller's** transaction; the
        caller must commit.

        Args:
            account_id:      The owning account's UUID.
            symbol:          Trading pair symbol (e.g. ``"BTCUSDT"``), used
                             only for structured logging.
            side:            ``"buy"`` or ``"sell"``.
            base_asset:      The base asset (e.g. ``"BTC"``).
            quote_asset:     The quote asset (e.g. ``"USDT"``).
            quantity:        Filled base-asset quantity (must be > 0).
            execution_price: Effective price per base unit after slippage
                             (must be > 0).
            from_locked:     If ``True``, the pre-reserved pool is used
                             (limit orders). Defaults to ``False`` (market
                             orders).

        Returns:
            A :class:`TradeSettlement` dataclass containing the refreshed
            balance rows, the fee charged, gross quote amount, and
            execution price.

        Raises:
            InputValidationError:         If ``side`` is neither ``"buy"`` nor
                                     ``"sell"``, or if ``quantity`` / ``price``
                                     are non-positive.
            InsufficientBalanceError: If the account lacks sufficient funds
                                     (available or locked depending on
                                     ``from_locked``).
            DatabaseError:            On any unexpected database failure.

        Example::

            settlement = await mgr.execute_trade(
                account_id,
                symbol="BTCUSDT",
                side="buy",
                base_asset="BTC",
                quote_asset="USDT",
                quantity=Decimal("0.5"),
                execution_price=Decimal("50200"),
                from_locked=False,
            )
            await session.commit()
            print(settlement.fee_charged)   # e.g. Decimal("25.10")
        """
        if side not in ("buy", "sell"):
            raise InputValidationError(
                f"side must be 'buy' or 'sell', got {side!r}",
                field="side",
            )
        if quantity <= _ZERO:
            raise InputValidationError(
                f"quantity must be positive, got {quantity!r}",
                field="quantity",
            )
        if execution_price <= _ZERO:
            raise InputValidationError(
                f"execution_price must be positive, got {execution_price!r}",
                field="execution_price",
            )

        gross_quote = (quantity * execution_price).quantize(Decimal("0.00000001"))
        fee = self._calculate_fee(gross_quote)

        if side == "buy":
            quote_spent = gross_quote + fee
            base_received = quantity

            log.info(
                "balance_manager.execute_buy",
                account_id=str(account_id),
                symbol=symbol,
                quantity=str(quantity),
                execution_price=str(execution_price),
                gross_quote=str(gross_quote),
                fee=str(fee),
                quote_spent=str(quote_spent),
                from_locked=from_locked,
            )

            try:
                quote_bal, base_bal = await self._repo.atomic_execute_buy(
                    account_id,
                    quote_asset=quote_asset,
                    base_asset=base_asset,
                    quote_spent=quote_spent,
                    base_received=base_received,
                    from_locked=from_locked,
                )
            except InsufficientBalanceError:
                raise
            except SQLAlchemyError as exc:
                raise DatabaseError("Balance settlement failed.") from exc

            return TradeSettlement(
                quote_balance=quote_bal,
                base_balance=base_bal,
                fee_charged=fee,
                quote_amount=gross_quote,
                execution_price=execution_price,
            )

        # side == "sell"
        net_quote = gross_quote - fee
        if net_quote <= _ZERO:
            raise InputValidationError(
                "Fee exceeds gross proceeds; trade cannot be settled.",
                field="execution_price",
            )
        base_spent = quantity

        log.info(
            "balance_manager.execute_sell",
            account_id=str(account_id),
            symbol=symbol,
            quantity=str(quantity),
            execution_price=str(execution_price),
            gross_quote=str(gross_quote),
            fee=str(fee),
            net_quote=str(net_quote),
            from_locked=from_locked,
        )

        try:
            quote_bal, base_bal = await self._repo.atomic_execute_sell(
                account_id,
                quote_asset=quote_asset,
                base_asset=base_asset,
                quote_received=net_quote,
                base_spent=base_spent,
                from_locked=from_locked,
            )
        except InsufficientBalanceError:
            raise
        except SQLAlchemyError as exc:
            raise DatabaseError("Balance settlement failed.") from exc

        return TradeSettlement(
            quote_balance=quote_bal,
            base_balance=base_bal,
            fee_charged=fee,
            quote_amount=gross_quote,
            execution_price=execution_price,
        )
