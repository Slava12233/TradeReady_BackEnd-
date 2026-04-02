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
from src.database.repositories.agent_repo import AgentRepository
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
        agent_id:         UUID of the default agent auto-created during
                          registration.  ``None`` only if agent creation fails
                          (non-fatal — the account is still valid).
        agent_api_key:    Plaintext API key for the default agent.  Shown once;
                          callers should use this key for trading.  ``None``
                          when ``agent_id`` is ``None``.
    """

    account_id: UUID
    api_key: str
    api_secret: str
    display_name: str
    starting_balance: Decimal
    agent_id: UUID | None = None
    agent_api_key: str | None = None


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
        self._agent_repo = AgentRepository(session)
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

        # Auto-create a default agent so the account can trade immediately.
        # The agent holds the Balance row (agent_id NOT NULL), so without this
        # step the account has no usable balance.
        # Lazy import to avoid circular dependency: accounts → agents → accounts.
        from src.agents.service import AgentService  # noqa: PLC0415

        agent_svc = AgentService(self._session, self._settings)
        try:
            agent_creds = await agent_svc.create_agent(
                account_id=account.id,
                display_name=f"{display_name}'s Agent",
                starting_balance=balance_amount,
            )
            agent_id: UUID | None = agent_creds.agent_id
            agent_api_key: str | None = agent_creds.api_key
        except Exception as exc:  # noqa: BLE001
            # Agent creation failure is non-fatal for account creation itself.
            # Log and continue — the caller can create an agent manually.
            log.error(
                "account.register.default_agent_failed",
                account_id=str(account.id),
                error=str(exc),
            )
            agent_id = None
            agent_api_key = None

        log.info(
            "account.registered",
            account_id=str(account.id),
            display_name=display_name,
            starting_balance=str(balance_amount),
            default_agent_id=str(agent_id) if agent_id else None,
        )

        return AccountCredentials(
            account_id=account.id,
            api_key=creds.api_key,
            api_secret=creds.api_secret,
            display_name=display_name,
            starting_balance=balance_amount,
            agent_id=agent_id,
            agent_api_key=agent_api_key,
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
        """Reset an account to a clean state, restoring each agent to its starting balance.

        Steps performed inside **one transaction**:

        1. Verify the account exists and is ``active``.
        2. Cancel all pending / partially-filled orders for the account so the
           Celery ``LimitOrderMonitor`` cannot execute stale orders against the
           freshly-credited balances.
        3. Close all active :class:`~src.database.models.TradingSession` rows
           for the account.
        4. For each non-archived agent that belongs to the account:
           a. Wipe all :class:`~src.database.models.Balance` rows for that agent.
           b. Re-credit a fresh USDT balance scoped to that agent.
           c. Open a new :class:`~src.database.models.TradingSession` with the
              correct ``agent_id`` (satisfies the ``NOT NULL`` constraint).
        5. Flush and return the first new session (used by the route layer for
           the response summary).

        Args:
            account_id: UUID of the account to reset.

        Returns:
            The newly-created :class:`~src.database.models.TradingSession` for
            the first agent (or the only agent for single-agent accounts).

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

        # Fetch all non-archived agents before entering the write path so that
        # a subsequent flush cannot invalidate these ORM instances.
        agents = await self._agent_repo.list_by_account(account_id, include_archived=False)

        try:
            # 1. Cancel all pending / partially-filled orders for the account.
            #    Without this the Celery LimitOrderMonitor could execute stale
            #    orders against the freshly-credited balances after the reset.
            await self._session.execute(
                update(Order)
                .where(
                    Order.account_id == account_id,
                    Order.status.in_(["pending", "partially_filled"]),
                )
                .values(status="cancelled")
            )

            # 2. Close all active trading sessions for the account.
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

            # 3. Per-agent reset: wipe balances, re-credit starting USDT,
            #    open a new session with the required agent_id.
            first_new_session: TradingSession | None = None

            for agent in agents:
                agent_starting = Decimal(str(agent.starting_balance))

                # 3a. Wipe all balance rows for this agent.
                agent_balances: Sequence[Balance] = await self._balance_repo.get_all_by_agent(agent.id)
                for bal in agent_balances:
                    await self._session.delete(bal)
                await self._session.flush()

                # 3b. Re-credit the agent's starting USDT balance.
                fresh_balance = Balance(
                    account_id=account_id,
                    agent_id=agent.id,
                    asset=_STARTING_ASSET,
                    available=agent_starting,
                    locked=Decimal("0"),
                )
                self._session.add(fresh_balance)
                await self._session.flush()

                # 3c. Open a new trading session scoped to this agent.
                new_session = TradingSession(
                    account_id=account_id,
                    agent_id=agent.id,
                    starting_balance=agent_starting,
                    status="active",
                )
                self._session.add(new_session)
                await self._session.flush()
                await self._session.refresh(new_session)

                if first_new_session is None:
                    first_new_session = new_session

                log.info(
                    "account.reset.agent",
                    account_id=str(account_id),
                    agent_id=str(agent.id),
                    new_session_id=str(new_session.id),
                    starting_balance=str(agent_starting),
                )

            # Edge case: account has no agents yet (should not happen in
            # normal operation since registration always creates a default
            # agent, but handled defensively).
            if first_new_session is None:
                log.warning("account.reset.no_agents", account_id=str(account_id))
                # Return a sentinel session without agent_id is not possible
                # (NOT NULL constraint).  Raise a clear error so the caller
                # knows why the reset did not produce a session.
                raise DatabaseError(
                    "Cannot reset account: no agents found. Create at least one agent before resetting."
                )

            log.info(
                "account.reset",
                account_id=str(account_id),
                agent_count=len(agents),
            )
            return first_new_session

        except (AccountNotFoundError, AccountSuspendedError, DatabaseError):
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
