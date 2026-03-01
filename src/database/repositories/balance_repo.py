"""Repository for Balance CRUD and atomic trade operations.

All database access for :class:`~src.database.models.Balance` rows goes
through :class:`BalanceRepository`.  Service classes must never issue raw
SQLAlchemy queries for balances directly.

The two atomic trade helpers — :meth:`BalanceRepository.atomic_buy` and
:meth:`BalanceRepository.atomic_sell` — update multiple balance rows inside
the **caller's** transaction so the caller can commit or roll back the whole
operation together with related ``Order`` / ``Trade`` inserts.

Dependency direction:
    BalanceManager → BalanceRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

import structlog
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Balance
from src.utils.exceptions import (
    DatabaseError,
    InsufficientBalanceError,
)

logger = structlog.get_logger(__name__)

# Sentinel value used when the caller does not supply a specific amount for
# delta operations -- kept as a module-level constant for clarity.
_ZERO = Decimal("0")


class BalanceRepository:
    """Async CRUD repository for the ``balances`` table.

    Every method operates within the injected session.  Callers are
    responsible for committing; this repository never calls
    ``session.commit()`` so that multiple repo operations can participate in
    a single atomic transaction.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    Example::

        async with session_factory() as session:
            repo = BalanceRepository(session)
            bal = await repo.get(account_id=acct.id, asset="USDT")
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get(self, account_id: UUID, asset: str) -> Balance | None:
        """Fetch the balance row for a specific account / asset pair.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset ticker, e.g. ``"USDT"``, ``"BTC"``.

        Returns:
            The :class:`Balance` instance, or ``None`` if no row exists yet.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            usdt_bal = await repo.get(account_id=acct.id, asset="USDT")
            if usdt_bal is None:
                # balance not yet created for this asset
                ...
        """
        try:
            stmt = select(Balance).where(
                Balance.account_id == account_id,
                Balance.asset == asset,
            )
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception(
                "balance.get.db_error",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "error": str(exc),
                },
            )
            raise DatabaseError("Failed to fetch balance.") from exc

    async def get_all(self, account_id: UUID) -> Sequence[Balance]:
        """Return every balance row owned by an account.

        Results are ordered by ``asset`` ascending so the list is stable
        across calls.

        Args:
            account_id: The owning account's UUID.

        Returns:
            A (possibly empty) sequence of :class:`Balance` instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            balances = await repo.get_all(account_id=acct.id)
            for bal in balances:
                print(bal.asset, bal.available, bal.locked)
        """
        try:
            stmt = (
                select(Balance)
                .where(Balance.account_id == account_id)
                .order_by(Balance.asset.asc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "balance.get_all.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to fetch all balances.") from exc

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, balance: Balance) -> Balance:
        """Persist a new :class:`Balance` row and flush to obtain server defaults.

        The ``id`` and ``updated_at`` columns are populated by the database on
        flush.  The caller must commit the session to make the row durable.

        There is a unique constraint on ``(account_id, asset)``; attempting to
        insert a duplicate raises :class:`~src.utils.exceptions.DatabaseError`
        with details about the conflict.

        Args:
            balance: A fully-populated (but not yet persisted) Balance instance.
                     ``available`` and ``locked`` must be ≥ 0.

        Returns:
            The same ``balance`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On unique-constraint violations or any other
                SQLAlchemy / database error.

        Example::

            bal = Balance(account_id=acct.id, asset="USDT", available=Decimal("10000"))
            created = await repo.create(bal)
            await session.commit()
        """
        try:
            self._session.add(balance)
            await self._session.flush()
            await self._session.refresh(balance)
            logger.info(
                "balance.created",
                extra={
                    "account_id": str(balance.account_id),
                    "asset": balance.asset,
                    "available": str(balance.available),
                },
            )
            return balance
        except IntegrityError as exc:
            await self._session.rollback()
            raise DatabaseError(
                f"Balance for account={balance.account_id} asset={balance.asset!r} "
                "already exists or violates a constraint."
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "balance.create.db_error",
                extra={
                    "account_id": str(balance.account_id),
                    "asset": balance.asset,
                    "error": str(exc),
                },
            )
            raise DatabaseError("Failed to create balance.") from exc

    async def update_available(
        self,
        account_id: UUID,
        asset: str,
        delta: Decimal,
    ) -> Balance:
        """Add ``delta`` to the ``available`` column for an account / asset row.

        A positive ``delta`` credits the balance; a negative ``delta`` debits
        it.  The database CHECK constraint ``available >= 0`` will reject any
        update that would take the balance below zero — the exception is caught
        here and re-raised as :class:`~src.utils.exceptions.InsufficientBalanceError`.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset ticker, e.g. ``"USDT"``.
            delta:      Amount to add (positive) or subtract (negative).

        Returns:
            The refreshed :class:`Balance` instance.

        Raises:
            InsufficientBalanceError: If the update would make ``available``
                negative.
            DatabaseError: If the balance row does not exist or any other
                database error occurs.

        Example::

            # Credit 500 USDT
            bal = await repo.update_available(acct.id, "USDT", Decimal("500"))
            # Debit 200 USDT
            bal = await repo.update_available(acct.id, "USDT", Decimal("-200"))
        """
        try:
            stmt = (
                update(Balance)
                .where(
                    Balance.account_id == account_id,
                    Balance.asset == asset,
                )
                .values(available=Balance.available + delta)
                .returning(Balance)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise DatabaseError(
                    f"Balance row not found for account={account_id} asset={asset!r}."
                )
            logger.debug(
                "balance.available_updated",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "delta": str(delta),
                    "new_available": str(row.available),
                },
            )
            return row
        except IntegrityError as exc:
            await self._session.rollback()
            raise InsufficientBalanceError(
                asset=asset,
                required=abs(delta) if delta < _ZERO else None,
            ) from exc
        except (InsufficientBalanceError, DatabaseError):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "balance.update_available.db_error",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "delta": str(delta),
                    "error": str(exc),
                },
            )
            raise DatabaseError("Failed to update available balance.") from exc

    async def update_locked(
        self,
        account_id: UUID,
        asset: str,
        delta: Decimal,
    ) -> Balance:
        """Add ``delta`` to the ``locked`` column for an account / asset row.

        A positive ``delta`` locks additional funds; a negative ``delta``
        releases them.  The database CHECK constraint ``locked >= 0`` guards
        against releasing more than was locked.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset ticker, e.g. ``"USDT"``.
            delta:      Amount to add (positive) or subtract (negative).

        Returns:
            The refreshed :class:`Balance` instance.

        Raises:
            InsufficientBalanceError: If the update would make ``locked``
                negative (i.e. releasing more than was locked).
            DatabaseError: If the balance row does not exist or any other
                database error occurs.

        Example::

            # Lock 100 USDT for a pending limit order
            bal = await repo.update_locked(acct.id, "USDT", Decimal("100"))
            # Release 100 USDT when the limit order is cancelled
            bal = await repo.update_locked(acct.id, "USDT", Decimal("-100"))
        """
        try:
            stmt = (
                update(Balance)
                .where(
                    Balance.account_id == account_id,
                    Balance.asset == asset,
                )
                .values(locked=Balance.locked + delta)
                .returning(Balance)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise DatabaseError(
                    f"Balance row not found for account={account_id} asset={asset!r}."
                )
            logger.debug(
                "balance.locked_updated",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "delta": str(delta),
                    "new_locked": str(row.locked),
                },
            )
            return row
        except IntegrityError as exc:
            await self._session.rollback()
            raise InsufficientBalanceError(
                asset=asset,
                required=abs(delta) if delta < _ZERO else None,
            ) from exc
        except (InsufficientBalanceError, DatabaseError):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "balance.update_locked.db_error",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "delta": str(delta),
                    "error": str(exc),
                },
            )
            raise DatabaseError("Failed to update locked balance.") from exc

    # ------------------------------------------------------------------
    # Atomic trade operations
    # ------------------------------------------------------------------

    async def atomic_lock_funds(
        self,
        account_id: UUID,
        asset: str,
        amount: Decimal,
    ) -> Balance:
        """Atomically move ``amount`` from ``available`` → ``locked``.

        Used when a **limit order** is accepted: the required funds are
        reserved so they cannot be used for another order while the limit is
        pending.  Both columns are updated in a single ``UPDATE`` statement so
        the operation is safe against concurrent requests.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset to lock (e.g. ``"USDT"`` for a buy order).
            amount:     Positive amount to move from available to locked.

        Returns:
            The refreshed :class:`Balance` instance.

        Raises:
            InsufficientBalanceError: If ``available`` would drop below zero.
            DatabaseError: If the balance row does not exist or any other
                database error occurs.

        Example::

            # Lock 500 USDT for a pending BTC limit-buy
            bal = await repo.atomic_lock_funds(acct.id, "USDT", Decimal("500"))
            await session.commit()
        """
        if amount <= _ZERO:
            raise ValueError(f"amount must be positive, got {amount!r}")
        try:
            stmt = (
                update(Balance)
                .where(
                    Balance.account_id == account_id,
                    Balance.asset == asset,
                )
                .values(
                    available=Balance.available - amount,
                    locked=Balance.locked + amount,
                )
                .returning(Balance)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise DatabaseError(
                    f"Balance row not found for account={account_id} asset={asset!r}."
                )
            logger.info(
                "balance.funds_locked",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "amount": str(amount),
                    "new_available": str(row.available),
                    "new_locked": str(row.locked),
                },
            )
            return row
        except IntegrityError as exc:
            await self._session.rollback()
            raise InsufficientBalanceError(
                asset=asset,
                required=amount,
            ) from exc
        except (InsufficientBalanceError, DatabaseError):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "balance.atomic_lock_funds.db_error",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "amount": str(amount),
                    "error": str(exc),
                },
            )
            raise DatabaseError("Failed to lock funds.") from exc

    async def atomic_unlock_funds(
        self,
        account_id: UUID,
        asset: str,
        amount: Decimal,
    ) -> Balance:
        """Atomically move ``amount`` from ``locked`` → ``available``.

        Used when a **pending limit order is cancelled**: the reserved funds
        are returned to the available pool in a single ``UPDATE``.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset to unlock.
            amount:     Positive amount to move from locked back to available.

        Returns:
            The refreshed :class:`Balance` instance.

        Raises:
            InsufficientBalanceError: If ``locked`` would drop below zero.
            DatabaseError: If the balance row does not exist or any other
                database error occurs.

        Example::

            # Release 500 USDT when a limit-buy order is cancelled
            bal = await repo.atomic_unlock_funds(acct.id, "USDT", Decimal("500"))
            await session.commit()
        """
        if amount <= _ZERO:
            raise ValueError(f"amount must be positive, got {amount!r}")
        try:
            stmt = (
                update(Balance)
                .where(
                    Balance.account_id == account_id,
                    Balance.asset == asset,
                )
                .values(
                    locked=Balance.locked - amount,
                    available=Balance.available + amount,
                )
                .returning(Balance)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise DatabaseError(
                    f"Balance row not found for account={account_id} asset={asset!r}."
                )
            logger.info(
                "balance.funds_unlocked",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "amount": str(amount),
                    "new_available": str(row.available),
                    "new_locked": str(row.locked),
                },
            )
            return row
        except IntegrityError as exc:
            await self._session.rollback()
            raise InsufficientBalanceError(
                asset=asset,
                required=amount,
            ) from exc
        except (InsufficientBalanceError, DatabaseError):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "balance.atomic_unlock_funds.db_error",
                extra={
                    "account_id": str(account_id),
                    "asset": asset,
                    "amount": str(amount),
                    "error": str(exc),
                },
            )
            raise DatabaseError("Failed to unlock funds.") from exc

    async def atomic_execute_buy(
        self,
        account_id: UUID,
        *,
        quote_asset: str,
        base_asset: str,
        quote_spent: Decimal,
        base_received: Decimal,
        from_locked: bool = False,
    ) -> tuple[Balance, Balance]:
        """Atomically settle a filled **buy** order across two balance rows.

        Depending on ``from_locked``:

        - ``from_locked=True`` (limit buy, funds were pre-locked):
          deduct ``quote_spent`` from ``locked``, credit ``base_received``
          to the base-asset ``available``.
        - ``from_locked=False`` (market buy, funds still available):
          deduct ``quote_spent`` from ``available``, credit ``base_received``
          to the base-asset ``available``.

        Both updates run inside the **caller's** transaction; commit or
        rollback is the caller's responsibility.

        Args:
            account_id:    The owning account's UUID.
            quote_asset:   The quote-side asset (e.g. ``"USDT"``).
            base_asset:    The base-side asset received (e.g. ``"BTC"``).
            quote_spent:   Total quote amount deducted (including fee).
            base_received: Base quantity credited after slippage.
            from_locked:   If ``True``, deduct from ``locked``; otherwise
                           deduct from ``available``.

        Returns:
            A ``(quote_balance, base_balance)`` tuple of refreshed
            :class:`Balance` instances.

        Raises:
            InsufficientBalanceError: If the quote balance would go negative.
            DatabaseError: If a balance row is missing or any database error.

        Example::

            q_bal, b_bal = await repo.atomic_execute_buy(
                acct.id,
                quote_asset="USDT",
                base_asset="BTC",
                quote_spent=Decimal("50100"),
                base_received=Decimal("0.9988"),
                from_locked=False,
            )
            await session.commit()
        """
        if quote_spent <= _ZERO:
            raise ValueError(f"quote_spent must be positive, got {quote_spent!r}")
        if base_received <= _ZERO:
            raise ValueError(f"base_received must be positive, got {base_received!r}")

        try:
            # 1. Deduct quote (from locked or available depending on order type)
            if from_locked:
                quote_stmt = (
                    update(Balance)
                    .where(
                        Balance.account_id == account_id,
                        Balance.asset == quote_asset,
                    )
                    .values(locked=Balance.locked - quote_spent)
                    .returning(Balance)
                )
            else:
                quote_stmt = (
                    update(Balance)
                    .where(
                        Balance.account_id == account_id,
                        Balance.asset == quote_asset,
                    )
                    .values(available=Balance.available - quote_spent)
                    .returning(Balance)
                )

            quote_result = await self._session.execute(quote_stmt)
            quote_bal = quote_result.scalars().first()
            if quote_bal is None:
                raise DatabaseError(
                    f"Balance row not found for account={account_id} "
                    f"asset={quote_asset!r}."
                )

            # 2. Credit base asset — upsert-style: create if not exists
            base_bal = await self._get_or_create_zero(account_id, base_asset)
            base_stmt = (
                update(Balance)
                .where(
                    Balance.account_id == account_id,
                    Balance.asset == base_asset,
                )
                .values(available=Balance.available + base_received)
                .returning(Balance)
            )
            base_result = await self._session.execute(base_stmt)
            base_bal = base_result.scalars().first()
            if base_bal is None:
                raise DatabaseError(
                    f"Balance row not found for account={account_id} "
                    f"asset={base_asset!r}."
                )

            logger.info(
                "balance.buy_executed",
                extra={
                    "account_id": str(account_id),
                    "quote_asset": quote_asset,
                    "base_asset": base_asset,
                    "quote_spent": str(quote_spent),
                    "base_received": str(base_received),
                    "from_locked": from_locked,
                },
            )
            return quote_bal, base_bal

        except IntegrityError as exc:
            await self._session.rollback()
            raise InsufficientBalanceError(
                asset=quote_asset,
                required=quote_spent,
            ) from exc
        except (InsufficientBalanceError, DatabaseError):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "balance.atomic_execute_buy.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to execute buy balance update.") from exc

    async def atomic_execute_sell(
        self,
        account_id: UUID,
        *,
        quote_asset: str,
        base_asset: str,
        quote_received: Decimal,
        base_spent: Decimal,
        from_locked: bool = False,
    ) -> tuple[Balance, Balance]:
        """Atomically settle a filled **sell** order across two balance rows.

        Depending on ``from_locked``:

        - ``from_locked=True`` (limit sell, base asset was pre-locked):
          deduct ``base_spent`` from base ``locked``, credit ``quote_received``
          to quote ``available``.
        - ``from_locked=False`` (market sell, base asset still available):
          deduct ``base_spent`` from base ``available``, credit
          ``quote_received`` to quote ``available``.

        Both updates run inside the **caller's** transaction.

        Args:
            account_id:     The owning account's UUID.
            quote_asset:    The quote-side asset credited (e.g. ``"USDT"``).
            base_asset:     The base-side asset sold (e.g. ``"BTC"``).
            quote_received: Net quote proceeds after fee deduction.
            base_spent:     Base quantity sold.
            from_locked:    If ``True``, deduct from base ``locked``; otherwise
                            deduct from base ``available``.

        Returns:
            A ``(quote_balance, base_balance)`` tuple of refreshed
            :class:`Balance` instances.

        Raises:
            InsufficientBalanceError: If the base balance would go negative.
            DatabaseError: If a balance row is missing or any database error.

        Example::

            q_bal, b_bal = await repo.atomic_execute_sell(
                acct.id,
                quote_asset="USDT",
                base_asset="BTC",
                quote_received=Decimal("49900"),
                base_spent=Decimal("1.0"),
                from_locked=False,
            )
            await session.commit()
        """
        if quote_received <= _ZERO:
            raise ValueError(f"quote_received must be positive, got {quote_received!r}")
        if base_spent <= _ZERO:
            raise ValueError(f"base_spent must be positive, got {base_spent!r}")

        try:
            # 1. Deduct base asset
            if from_locked:
                base_stmt = (
                    update(Balance)
                    .where(
                        Balance.account_id == account_id,
                        Balance.asset == base_asset,
                    )
                    .values(locked=Balance.locked - base_spent)
                    .returning(Balance)
                )
            else:
                base_stmt = (
                    update(Balance)
                    .where(
                        Balance.account_id == account_id,
                        Balance.asset == base_asset,
                    )
                    .values(available=Balance.available - base_spent)
                    .returning(Balance)
                )

            base_result = await self._session.execute(base_stmt)
            base_bal = base_result.scalars().first()
            if base_bal is None:
                raise DatabaseError(
                    f"Balance row not found for account={account_id} "
                    f"asset={base_asset!r}."
                )

            # 2. Credit quote asset (always available; USDT almost always exists)
            await self._get_or_create_zero(account_id, quote_asset)
            quote_stmt = (
                update(Balance)
                .where(
                    Balance.account_id == account_id,
                    Balance.asset == quote_asset,
                )
                .values(available=Balance.available + quote_received)
                .returning(Balance)
            )
            quote_result = await self._session.execute(quote_stmt)
            quote_bal = quote_result.scalars().first()
            if quote_bal is None:
                raise DatabaseError(
                    f"Balance row not found for account={account_id} "
                    f"asset={quote_asset!r}."
                )

            logger.info(
                "balance.sell_executed",
                extra={
                    "account_id": str(account_id),
                    "quote_asset": quote_asset,
                    "base_asset": base_asset,
                    "quote_received": str(quote_received),
                    "base_spent": str(base_spent),
                    "from_locked": from_locked,
                },
            )
            return quote_bal, base_bal

        except IntegrityError as exc:
            await self._session.rollback()
            raise InsufficientBalanceError(
                asset=base_asset,
                required=base_spent,
            ) from exc
        except (InsufficientBalanceError, DatabaseError):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "balance.atomic_execute_sell.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to execute sell balance update.") from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_or_create_zero(self, account_id: UUID, asset: str) -> Balance:
        """Return the balance row for ``asset``, creating a zero row if absent.

        This is an internal helper used by the atomic trade methods to ensure
        a base-asset balance row exists before crediting it.  The row is
        flushed (not committed) so the caller's transaction owns it.

        Args:
            account_id: The owning account's UUID.
            asset:      The asset ticker.

        Returns:
            The existing or newly-created :class:`Balance` instance.

        Raises:
            DatabaseError: On any SQLAlchemy error.
        """
        existing = await self.get(account_id, asset)
        if existing is not None:
            return existing

        new_row = Balance(
            account_id=account_id,
            asset=asset,
            available=Decimal("0"),
            locked=Decimal("0"),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(new_row)
                await self._session.flush()
            await self._session.refresh(new_row)
            logger.info(
                "balance.auto_created",
                extra={"account_id": str(account_id), "asset": asset},
            )
            return new_row
        except IntegrityError:
            # Race condition: another concurrent request just created the row.
            # The savepoint above was rolled back; the parent transaction is intact.
            existing = await self.get(account_id, asset)
            if existing is not None:
                return existing
            raise DatabaseError(
                f"Failed to auto-create balance for account={account_id} "
                f"asset={asset!r}."
            )
