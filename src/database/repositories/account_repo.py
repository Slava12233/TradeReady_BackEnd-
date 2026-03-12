"""Repository for Account CRUD operations.

All database access for :class:`~src.database.models.Account` rows goes
through :class:`AccountRepository`.  Service classes must never issue raw
SQLAlchemy queries for accounts directly.

Dependency direction:
    Services → AccountRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import Account
from src.utils.exceptions import (
    AccountNotFoundError,
    DatabaseError,
    DuplicateAccountError,
)

logger = structlog.get_logger(__name__)


class AccountRepository:
    """Async CRUD repository for the ``accounts`` table.

    Every method opens and closes its own unit of work within the injected
    session.  Callers are responsible for committing the session; this repo
    does *not* call ``session.commit()`` so that callers can batch multiple
    repo operations into a single atomic transaction.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    Example::

        async with session_factory() as session:
            repo = AccountRepository(session)
            account = await repo.get_by_id(some_uuid)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, account: Account) -> Account:
        """Persist a new :class:`Account` row and flush to obtain server defaults.

        The ``id``, ``created_at``, and ``updated_at`` columns are populated
        by the database on flush.  The caller must commit the session to make
        the row durable.

        Args:
            account: A fully-populated (but not yet persisted) Account instance.
                     The ``api_key`` must be unique; a duplicate raises
                     :class:`~src.utils.exceptions.DuplicateAccountError`.

        Returns:
            The same ``account`` instance with server-generated columns filled.

        Raises:
            DuplicateAccountError: If ``api_key`` or ``email`` violates a
                unique constraint.
            DatabaseError: On any other SQLAlchemy / database error.

        Example::

            account = Account(
                api_key="ak_live_...",
                api_key_hash="...",
                api_secret_hash="...",
                display_name="MyBot",
            )
            created = await repo.create(account)
            await session.commit()
        """
        try:
            self._session.add(account)
            await self._session.flush()
            await self._session.refresh(account)
            logger.info(
                "account.created",
                extra={"account_id": str(account.id), "display_name": account.display_name},
            )
            return account
        except IntegrityError as exc:
            await self._session.rollback()
            constraint = str(exc.orig) if exc.orig else ""
            if "api_key" in constraint or "email" in constraint:
                raise DuplicateAccountError("An account with the given API key or email already exists.") from exc
            raise DatabaseError(f"Integrity error while creating account: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("account.create.db_error", extra={"error": str(exc)})
            raise DatabaseError("Failed to create account.") from exc

    async def update_risk_profile(self, account_id: UUID, profile: dict[str, object]) -> None:
        """Persist an updated ``risk_profile`` JSONB value for the given account.

        Mutates the account row's ``risk_profile`` column and flushes the
        change to the database within the current session.  The caller is
        responsible for committing.

        Args:
            account_id: Primary key of the account to update.
            profile:    New risk-profile dict to store.

        Raises:
            AccountNotFoundError: If no account exists with ``account_id``.
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            await repo.update_risk_profile(account.id, {"max_open_orders": 20})
            await session.commit()
        """
        try:
            stmt = select(Account).where(Account.id == account_id)
            result = await self._session.execute(stmt)
            account = result.scalars().first()
            if account is None:
                raise AccountNotFoundError(account_id=account_id)
            account.risk_profile = profile
            await self._session.flush()
            logger.info(
                "account.risk_profile_updated",
                account_id=str(account_id),
            )
        except AccountNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "account.update_risk_profile.db_error",
                account_id=str(account_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to update account risk profile.") from exc

    async def update_status(self, account_id: UUID, status: str) -> Account:
        """Update the ``status`` column for the given account.

        Valid status values are ``"active"``, ``"suspended"``, and
        ``"archived"`` (enforced by a database CHECK constraint).

        Args:
            account_id: Primary key of the account to update.
            status: New status string.

        Returns:
            The refreshed :class:`Account` instance with the new status.

        Raises:
            AccountNotFoundError: If no account exists with ``account_id``.
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            updated = await repo.update_status(account.id, "suspended")
            await session.commit()
        """
        try:
            stmt = update(Account).where(Account.id == account_id).values(status=status).returning(Account)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AccountNotFoundError(account_id=account_id)
            logger.info(
                "account.status_updated",
                extra={"account_id": str(account_id), "new_status": status},
            )
            return row
        except AccountNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "account.update_status.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to update account status.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, account_id: UUID) -> Account:
        """Fetch a single account by its primary-key UUID.

        Args:
            account_id: The account's UUID primary key.

        Returns:
            The matching :class:`Account` instance.

        Raises:
            AccountNotFoundError: If no account with ``account_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            account = await repo.get_by_id(uuid.UUID("..."))
        """
        try:
            stmt = select(Account).where(Account.id == account_id)
            result = await self._session.execute(stmt)
            account = result.scalars().first()
            if account is None:
                raise AccountNotFoundError(account_id=account_id)
            return account
        except AccountNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception(
                "account.get_by_id.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to fetch account by ID.") from exc

    async def get_by_api_key(self, api_key: str) -> Account:
        """Fetch a single account by its plaintext API key.

        The ``api_key`` column has a unique index so this query is O(1).
        Use this method during authentication to look up the account before
        running ``bcrypt.checkpw`` against ``api_key_hash``.

        Args:
            api_key: The plaintext API key (``ak_live_`` prefix expected).

        Returns:
            The matching :class:`Account` instance.

        Raises:
            AccountNotFoundError: If no account owns ``api_key``.
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            account = await repo.get_by_api_key("ak_live_abc123...")
        """
        try:
            stmt = select(Account).where(Account.api_key == api_key)
            result = await self._session.execute(stmt)
            account = result.scalars().first()
            if account is None:
                raise AccountNotFoundError("No account found for the provided API key.")
            return account
        except AccountNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception(
                "account.get_by_api_key.db_error",
                extra={"error": str(exc)},
            )
            raise DatabaseError("Failed to fetch account by API key.") from exc

    async def get_by_email(self, email: str) -> Account:
        """Fetch a single account by its email address.

        Used during password-based authentication to look up the account before
        verifying the password hash.  The ``email`` column has a unique index so
        this query is O(1).

        Args:
            email: The account's email address (case-sensitive).

        Returns:
            The matching :class:`Account` instance.

        Raises:
            AccountNotFoundError: If no account is registered with ``email``.
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            account = await repo.get_by_email("user@example.com")
        """
        try:
            stmt = select(Account).where(Account.email == email)
            result = await self._session.execute(stmt)
            account = result.scalars().first()
            if account is None:
                raise AccountNotFoundError("No account found for the provided email address.")
            return account
        except AccountNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception(
                "account.get_by_email.db_error",
                extra={"error": str(exc)},
            )
            raise DatabaseError("Failed to fetch account by email.") from exc

    async def list_by_status(
        self,
        status: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Account]:
        """Return a paginated list of accounts filtered by ``status``.

        Results are ordered by ``created_at`` ascending (oldest first) so that
        pagination is stable across calls.

        Args:
            status: Filter value — ``"active"``, ``"suspended"``, or
                    ``"archived"``.
            limit: Maximum number of rows to return (default 100, max
                   enforced by the caller).
            offset: Number of rows to skip for pagination (default 0).

        Returns:
            A (possibly empty) sequence of :class:`Account` instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            active_accounts = await repo.list_by_status("active", limit=50)
        """
        try:
            stmt = (
                select(Account)
                .where(Account.status == status)
                .order_by(Account.created_at.asc())
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "account.list_by_status.db_error",
                extra={"status": status, "error": str(exc)},
            )
            raise DatabaseError("Failed to list accounts by status.") from exc
