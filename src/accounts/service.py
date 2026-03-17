"""Account service — registration, authentication, and lifecycle management.

Responsibilities
----------------
1. **Register** a new agent account: generate API credentials, persist the
   ``Account`` row, credit the initial USDT balance, and open a ``TradingSession``
   — all inside a single atomic database transaction.
2. **Authenticate** an inbound API key: look up by key, verify the bcrypt hash,
   and return the account (or raise on mismatch / suspended / archived).
3. **Get** an account by UUID.
4. **Reset** an account: close the active session, wipe all balances, re-credit
   the original starting balance, and open a fresh session.
5. **Suspend** / **unsuspend** an account.
6. **List** accounts filtered by status.

All bcrypt operations are CPU-bound and must be called from a thread pool when
invoked from async FastAPI handlers
(``await asyncio.get_event_loop().run_in_executor(None, sync_fn)``).
:class:`AccountService` itself is async — the blocking helpers are handled by
:mod:`src.accounts.auth` which callers should wrap appropriately.

Example::

    async with session_factory() as session:
        svc = AccountService(session, settings)
        creds = await svc.register("MyBot", email="dev@example.com")
        print(creds.api_key)   # ak_live_<64 chars>
        print(creds.api_secret)  # sk_live_<64 chars>  ← shown once
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.accounts.auth import (
    authenticate_api_key,
    generate_api_credentials,
    hash_password,
    verify_password,
)
from src.config import Settings
from src.database.models import Account, Balance, Order, TradingSession
from src.database.repositories.account_repo import AccountRepository
from src.database.repositories.balance_repo import BalanceRepository
from src.utils.exceptions import (
    AccountNotFoundError,
    AccountSuspendedError,
    AuthenticationError,
    DatabaseError,
    DuplicateAccountError,
)

log = structlog.get_logger(__name__)

# Asset credited on every new account and account reset.
_STARTING_ASSET = "USDT"


# ---------------------------------------------------------------------------
# Return value for register()
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccountCredentials:
    """Credentials returned exactly once on successful registration.

    The ``api_secret`` is **never** stored in the database; it must be saved
    by the caller immediately.  Only ``api_key`` and the two bcrypt hashes are
    persisted.

    Attributes:
        account_id:       The newly-created account's UUID.
        api_key:          Plaintext API key (``ak_live_`` prefix).  Stored in
                          ``accounts.api_key`` for O(1) lookup.
        api_secret:       Plaintext API secret (``sk_live_`` prefix). **Show
                          once, never store.**
        display_name:     The account's display name.
        starting_balance: USDT balance credited at registration.
    """

    account_id: UUID
    api_key: str
    api_secret: str
    display_name: str
    starting_balance: Decimal


# ---------------------------------------------------------------------------
# AccountService
# ---------------------------------------------------------------------------


class AccountService:
    """Business-logic layer for account management.

    Coordinates :class:`~src.database.repositories.account_repo.AccountRepository`
    and :class:`~src.database.repositories.balance_repo.BalanceRepository` to
    implement account lifecycle operations as single atomic transactions.

    Args:
        session:  An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
                  The caller is responsible for committing or rolling back.
        settings: Application :class:`~src.config.Settings` (provides
                  ``default_starting_balance``, ``jwt_secret``, etc.).

    Example::

        async with session_factory() as session:
            svc = AccountService(session, get_settings())
            account = await svc.get_account(some_uuid)
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._account_repo = AccountRepository(session)
        self._balance_repo = BalanceRepository(session)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(
        self,
        display_name: str,
        email: str | None = None,
        starting_balance: Decimal | None = None,
        password: str | None = None,
    ) -> AccountCredentials:
        """Register a new agent account with an initial USDT balance.

        Steps performed inside **one transaction**:

        1. Generate a fresh API key/secret pair (bcrypt-hashed).
        2. Persist the :class:`~src.database.models.Account` row.
        3. Create the initial USDT :class:`~src.database.models.Balance` row.
        4. Open a :class:`~src.database.models.TradingSession` row.
        5. Commit.

        Args:
            display_name:     Human-readable name for the agent (max 100 chars).
            email:            Optional contact email.  Must be unique if provided.
            starting_balance: USDT balance to credit.  Defaults to
                              ``Settings.default_starting_balance`` (10 000 USDT).
            password:         Optional plaintext password for human users.  When
                              provided it is bcrypt-hashed and stored in
                              ``accounts.password_hash``.  Human users can then
                              authenticate via :meth:`authenticate_with_password`.

        Returns:
            :class:`AccountCredentials` containing the plaintext API key and
            secret (shown exactly once) plus the new account's UUID.

        Raises:
            DuplicateAccountError: If ``email`` is already registered.
            DatabaseError:         On any unexpected database failure.

        Example::

            creds = await svc.register("AlphaBot", email="alpha@example.com")
            # → AccountCredentials(account_id=UUID(...), api_key="ak_live_...", ...)
        """
        balance_amount = starting_balance if starting_balance is not None else self._settings.default_starting_balance

        loop = asyncio.get_event_loop()
        # generate_api_credentials() and hash_password() are CPU-bound — offload to thread pool
        creds = await loop.run_in_executor(None, generate_api_credentials)
        password_hash: str | None = None
        if password is not None:
            password_hash = await loop.run_in_executor(None, hash_password, password)

        try:
            account = Account(
                api_key=creds.api_key,
                api_key_hash=creds.api_key_hash,
                api_secret_hash=creds.api_secret_hash,
                display_name=display_name,
                email=email,
                password_hash=password_hash,
                starting_balance=balance_amount,
                status="active",
                risk_profile={},
            )

            account = await self._account_repo.create(account)

            # NOTE: Balance creation is handled by AgentService.create_agent(),
            # which creates an agent-scoped balance (Balance.agent_id is NOT NULL).

            session_row = TradingSession(
                account_id=account.id,
                starting_balance=balance_amount,
                status="active",
            )
            self._session.add(session_row)
            await self._session.flush()
            await self._session.refresh(session_row)

        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateAccountError(email=email) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            log.exception(
                "account.register.db_error",
                display_name=display_name,
                error=str(exc),
            )
            raise DatabaseError("Failed to register account.") from exc

        log.info(
            "account.registered",
            account_id=str(account.id),
            display_name=display_name,
            starting_balance=str(balance_amount),
            session_id=str(session_row.id),
        )

        return AccountCredentials(
            account_id=account.id,
            api_key=creds.api_key,
            api_secret=creds.api_secret,
            display_name=display_name,
            starting_balance=balance_amount,
        )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self, api_key: str) -> Account:
        """Authenticate an API key and return the associated account.

        Performs an O(1) lookup by plaintext ``api_key`` then verifies the
        bcrypt hash.  Also checks that the account is ``active`` — suspended
        or archived accounts are rejected even with a valid key.

        Args:
            api_key: The raw ``ak_live_`` prefixed key from the request header.

        Returns:
            The matching :class:`~src.database.models.Account` instance.

        Raises:
            AuthenticationError:    If the key does not match its stored hash.
            AccountSuspendedError:  If the account is ``suspended`` or
                                    ``archived``.
            AccountNotFoundError:   If no account owns ``api_key``.
            DatabaseError:          On any unexpected database failure.

        Example::

            account = await svc.authenticate(request.headers["X-API-Key"])
            # account.status is always "active" here
        """
        account = await self._account_repo.get_by_api_key(api_key)

        # authenticate_api_key() calls bcrypt (CPU-bound) — offload to thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, authenticate_api_key, api_key, account.api_key_hash)

        if account.status != "active":
            log.warning(
                "account.auth.rejected_non_active",
                account_id=str(account.id),
                status=account.status,
            )
            raise AccountSuspendedError(account_id=account.id)

        log.debug("account.authenticated", account_id=str(account.id))
        return account

    async def authenticate_with_password(self, email: str, password: str) -> Account:
        """Authenticate a human user by email and password.

        Looks up the account by ``email``, verifies the plaintext ``password``
        against the stored bcrypt hash, and checks the account is ``active``.

        Args:
            email:    The user's registered email address.
            password: The plaintext password submitted at login.

        Returns:
            The matching :class:`~src.database.models.Account` instance.

        Raises:
            AuthenticationError:   If the email is not registered, the account
                                   has no password set, or the password does not
                                   match the stored hash.
            AccountSuspendedError: If the account is ``suspended`` or
                                   ``archived``.
            DatabaseError:         On any unexpected database failure.

        Example::

            account = await svc.authenticate_with_password("user@example.com", "s3cr3t!")
            # account.status is always "active" here
        """
        try:
            account = await self._account_repo.get_by_email(email)
        except AccountNotFoundError:
            raise AuthenticationError("Invalid email or password.") from None

        if not account.password_hash:
            raise AuthenticationError("Invalid email or password.")

        loop = asyncio.get_event_loop()
        password_matches: bool = await loop.run_in_executor(None, verify_password, password, account.password_hash)
        if not password_matches:
            log.warning("account.password_auth.invalid", email=email)
            raise AuthenticationError("Invalid email or password.")

        if account.status != "active":
            log.warning(
                "account.password_auth.rejected_non_active",
                account_id=str(account.id),
                status=account.status,
            )
            raise AccountSuspendedError(account_id=account.id)

        log.debug("account.password_authenticated", account_id=str(account.id))
        return account

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_account(self, account_id: UUID) -> Account:
        """Fetch an account by its primary-key UUID.

        Args:
            account_id: The account's UUID.

        Returns:
            The matching :class:`~src.database.models.Account` instance.

        Raises:
            AccountNotFoundError: If no account exists with ``account_id``.
            DatabaseError:        On any unexpected database failure.

        Example::

            account = await svc.get_account(uuid.UUID("..."))
        """
        return await self._account_repo.get_by_id(account_id)

    async def list_accounts(
        self,
        status: str = "active",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Account]:
        """Return a paginated list of accounts filtered by status.

        Args:
            status: One of ``"active"``, ``"suspended"``, or ``"archived"``.
            limit:  Maximum rows to return (default 100).
            offset: Rows to skip for pagination (default 0).

        Returns:
            A (possibly empty) sequence of :class:`~src.database.models.Account`
            instances ordered by ``created_at`` ascending.

        Raises:
            DatabaseError: On any unexpected database failure.

        Example::

            active = await svc.list_accounts("active", limit=50)
        """
        return await self._account_repo.list_by_status(status, limit=limit, offset=offset)

    # ------------------------------------------------------------------
    # Account lifecycle
    # ------------------------------------------------------------------

    async def reset_account(self, account_id: UUID) -> TradingSession:
        """Reset an account to a clean state with its original starting balance.

        Steps performed inside **one transaction**:

        1. Verify the account exists and is ``active``.
        2. Close the current active :class:`~src.database.models.TradingSession`
           (sets ``ended_at = now()``, ``status = "closed"``).
        3. Delete all :class:`~src.database.models.Balance` rows for the account.
        4. Re-credit the original ``starting_balance`` as a fresh USDT balance.
        5. Open a new ``TradingSession``.
        6. Commit.

        Args:
            account_id: UUID of the account to reset.

        Returns:
            The newly-created :class:`~src.database.models.TradingSession`.

        Raises:
            AccountNotFoundError:  If no account exists with ``account_id``.
            AccountSuspendedError: If the account is not ``active``.
            DatabaseError:         On any unexpected database failure.

        Example::

            new_session = await svc.reset_account(account.id)
            print(new_session.status)  # "active"
        """
        account = await self._account_repo.get_by_id(account_id)

        if account.status != "active":
            raise AccountSuspendedError(account_id=account_id)

        try:
            # 1. Cancel all pending / partially-filled orders before wiping balances.
            #    Without this, the Celery LimitOrderMonitor could execute stale orders
            #    against the freshly-credited USDT balance after the reset.
            await self._session.execute(
                update(Order)
                .where(
                    Order.account_id == account_id,
                    Order.status.in_(["pending", "partially_filled"]),
                )
                .values(status="cancelled")
            )

            # 2. Close the current active session (if one exists)
            await self._session.execute(
                update(TradingSession)
                .where(
                    TradingSession.account_id == account_id,
                    TradingSession.status == "active",
                )
                .values(
                    status="closed",
                    ended_at=datetime.now(tz=UTC),
                )
            )

            # 3. Wipe all balance rows for the account
            balances: Sequence[Balance] = await self._balance_repo.get_all(account_id)
            for bal in balances:
                await self._session.delete(bal)
            await self._session.flush()

            # 4. Re-credit starting USDT balance
            starting = Decimal(str(account.starting_balance))
            fresh_balance = Balance(
                account_id=account_id,
                asset=_STARTING_ASSET,
                available=starting,
                locked=Decimal("0"),
            )
            self._session.add(fresh_balance)
            await self._session.flush()

            # 5. Open a new trading session
            new_session = TradingSession(
                account_id=account_id,
                starting_balance=starting,
                status="active",
            )
            self._session.add(new_session)
            await self._session.flush()
            await self._session.refresh(new_session)

            log.info(
                "account.reset",
                account_id=str(account_id),
                new_session_id=str(new_session.id),
                starting_balance=str(starting),
            )
            return new_session

        except (AccountNotFoundError, AccountSuspendedError):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            log.exception(
                "account.reset.db_error",
                account_id=str(account_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to reset account.") from exc

    async def suspend_account(self, account_id: UUID) -> None:
        """Suspend an account, preventing further trading.

        Sets ``accounts.status = "suspended"``.  The account can be reactivated
        by calling :meth:`unsuspend_account`.  Authentication for suspended
        accounts raises :exc:`~src.utils.exceptions.AccountSuspendedError`.

        Args:
            account_id: UUID of the account to suspend.

        Raises:
            AccountNotFoundError: If no account exists with ``account_id``.
            DatabaseError:        On any unexpected database failure.

        Example::

            await svc.suspend_account(account.id)
        """
        try:
            await self._account_repo.update_status(account_id, "suspended")
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DatabaseError("Failed to suspend account.") from exc
        log.info("account.suspended", account_id=str(account_id))

    async def unsuspend_account(self, account_id: UUID) -> None:
        """Reactivate a previously suspended account.

        Sets ``accounts.status = "active"``.

        Args:
            account_id: UUID of the account to reactivate.

        Raises:
            AccountNotFoundError: If no account exists with ``account_id``.
            DatabaseError:        On any unexpected database failure.

        Example::

            await svc.unsuspend_account(account.id)
        """
        try:
            await self._account_repo.update_status(account_id, "active")
        except SQLAlchemyError as exc:
            await self._session.rollback()
            raise DatabaseError("Failed to unsuspend account.") from exc
        log.info("account.unsuspended", account_id=str(account_id))
