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
        # Default display_name when empty (field is now optional in schema)
        if not display_name:
            display_name = "Agent"

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

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------

    async def request_password_reset(
        self,
        username_or_email: str,
        redis: object,
    ) -> None:
        """Generate a password-reset token, store it in Redis, and log the link.

        Looks up the account by ``username_or_email`` (tried as email first,
        then as display_name).  When no account is found the method returns
        silently to avoid leaking account existence.

        The token is stored in Redis under ``password_reset:{token}`` with a
        1-hour TTL.  For the MVP the reset URL is logged via structlog rather
        than emailed.

        Args:
            username_or_email: The email address or display name submitted by
                               the user in the forgot-password form.
            redis:             An active ``redis.asyncio.Redis`` client.  The
                               ``Any`` type is used here because the
                               ``async_sessionmaker`` pattern does not expose
                               the generic parameter at call sites.

        Returns:
            ``None`` — always, regardless of whether an account was found.

        Example::

            await svc.request_password_reset("alice@example.com", redis_client)
        """
        import secrets  # noqa: PLC0415

        from redis.asyncio import Redis  # noqa: PLC0415
        from redis.exceptions import RedisError  # noqa: PLC0415

        # Attempt email lookup first, then fall back to display_name.
        account = None
        try:
            account = await self._account_repo.get_by_email(username_or_email)
        except AccountNotFoundError:
            # Try display_name lookup as fallback.
            try:
                from sqlalchemy import select  # noqa: PLC0415

                from src.database.models import Account as _Account  # noqa: PLC0415

                result = await self._session.execute(
                    select(_Account).where(
                        _Account.display_name == username_or_email,
                        _Account.status == "active",
                    )
                )
                account = result.scalar_one_or_none()
            except SQLAlchemyError:
                account = None

        if account is None:
            # Do not reveal whether the account exists — return silently.
            log.info(
                "account.password_reset.not_found",
                username_or_email=username_or_email,
            )
            return

        token = secrets.token_urlsafe(32)
        redis_key = f"password_reset:{token}"
        reset_url = f"https://tradeready.io/reset-password?token={token}"

        try:
            r: Redis = redis  # type: ignore[assignment]
            await r.set(redis_key, str(account.id), ex=3600)
        except RedisError as exc:
            log.error(
                "account.password_reset.redis_error",
                account_id=str(account.id),
                error=str(exc),
            )
            # Fail silently to the caller — do not reveal the error.
            return

        log.info(
            "password_reset.token_generated",
            account_id=str(account.id),
            reset_url=reset_url,
        )

    async def reset_password(
        self,
        token: str,
        new_password: str,
        redis: object,
    ) -> None:
        """Verify a password-reset token and update the account's password hash.

        Looks up ``password_reset:{token}`` in Redis.  If the key exists the
        stored ``account_id`` is used to fetch the account, the password hash is
        updated, and the Redis key is deleted.  If the key is missing or expired
        an :exc:`~src.utils.exceptions.InputValidationError` is raised.

        Args:
            token:        The reset token from the URL query parameter.
            new_password: The new plaintext password (8-72 characters).
            redis:        An active ``redis.asyncio.Redis`` client.

        Raises:
            InputValidationError: If the token is not found or has expired.
            DatabaseError:        On any unexpected database failure.

        Example::

            await svc.reset_password(token_from_url, "n3wP@ssw0rd!", redis_client)
        """
        from uuid import UUID as _UUID  # noqa: PLC0415

        from redis.asyncio import Redis  # noqa: PLC0415
        from redis.exceptions import RedisError  # noqa: PLC0415

        from src.utils.exceptions import InputValidationError  # noqa: PLC0415

        redis_key = f"password_reset:{token}"

        try:
            r: Redis = redis  # type: ignore[assignment]
            raw_account_id: str | None = await r.get(redis_key)
        except RedisError as exc:
            log.error(
                "account.password_reset.redis_error",
                error=str(exc),
            )
            raise InputValidationError("Invalid or expired reset token.") from exc

        if raw_account_id is None:
            raise InputValidationError("Invalid or expired reset token.")

        try:
            account_uuid = _UUID(raw_account_id)
        except ValueError as exc:
            raise InputValidationError("Invalid or expired reset token.") from exc

        # Hash the new password (CPU-bound — offload to thread pool).
        loop = asyncio.get_event_loop()
        new_hash: str = await loop.run_in_executor(None, hash_password, new_password)

        try:
            from sqlalchemy import update as _update  # noqa: PLC0415

            from src.database.models import Account as _Account  # noqa: PLC0415

            await self._session.execute(
                _update(_Account).where(_Account.id == account_uuid).values(password_hash=new_hash)
            )
            await self._session.flush()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            log.exception(
                "account.password_reset.db_error",
                account_id=str(account_uuid),
                error=str(exc),
            )
            raise DatabaseError("Failed to update password.") from exc

        # Delete the token so it cannot be reused.
        try:
            await r.delete(redis_key)
        except RedisError as exc:
            # Non-fatal: token TTL will expire it anyway.
            log.warning(
                "account.password_reset.token_delete_failed",
                account_id=str(account_uuid),
                error=str(exc),
            )

        log.info(
            "account.password_reset.success",
            account_id=str(account_uuid),
        )

    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------

    async def send_email_verification(
        self,
        account_id: UUID,
        email: str,
        redis: object,
    ) -> None:
        """Generate an email-verification token, store it in Redis, and log the link.

        Stores the token in Redis under ``email_verify:{token}`` with a
        24-hour TTL.  For MVP the verification URL is logged via structlog
        rather than emailed.

        Args:
            account_id: UUID of the account whose email should be verified.
            email:      The email address to include in the verification URL.
            redis:      An active ``redis.asyncio.Redis`` client.

        Returns:
            ``None`` — always, regardless of Redis availability (non-fatal).

        Example::

            await svc.send_email_verification(account.id, "user@example.com", redis_client)
        """
        import secrets  # noqa: PLC0415

        from redis.asyncio import Redis  # noqa: PLC0415
        from redis.exceptions import RedisError  # noqa: PLC0415

        token = secrets.token_urlsafe(32)
        redis_key = f"email_verify:{token}"
        verify_url = f"https://tradeready.io/verify-email?token={token}"

        try:
            r: Redis = redis  # type: ignore[assignment]
            await r.set(redis_key, str(account_id), ex=86400)
        except RedisError as exc:
            log.error(
                "account.email_verification.redis_error",
                account_id=str(account_id),
                error=str(exc),
            )
            return

        log.info(
            "account.email_verification.token_generated",
            account_id=str(account_id),
            email=email,
            verify_url=verify_url,
        )

    async def verify_email(
        self,
        token: str,
        redis: object,
    ) -> None:
        """Verify an email address using a one-time verification token.

        Looks up ``email_verify:{token}`` in Redis.  If found, sets
        ``accounts.email_verified = True`` for the associated account and
        deletes the token so it cannot be reused.  Raises
        :exc:`~src.utils.exceptions.InputValidationError` if the token is
        missing or expired.

        Args:
            token: The verification token from the URL query parameter.
            redis: An active ``redis.asyncio.Redis`` client.

        Raises:
            InputValidationError: If the token is not found or has expired.
            DatabaseError:        On any unexpected database failure.

        Example::

            await svc.verify_email(token_from_url, redis_client)
        """
        from uuid import UUID as _UUID  # noqa: PLC0415

        from redis.asyncio import Redis  # noqa: PLC0415
        from redis.exceptions import RedisError  # noqa: PLC0415

        from src.utils.exceptions import InputValidationError  # noqa: PLC0415

        redis_key = f"email_verify:{token}"

        try:
            r: Redis = redis  # type: ignore[assignment]
            raw_account_id: str | None = await r.get(redis_key)
        except RedisError as exc:
            log.error(
                "account.email_verification.redis_error",
                error=str(exc),
            )
            raise InputValidationError("Invalid or expired verification token.") from exc

        if raw_account_id is None:
            raise InputValidationError("Invalid or expired verification token.")

        try:
            account_uuid = _UUID(raw_account_id)
        except ValueError as exc:
            raise InputValidationError("Invalid or expired verification token.") from exc

        try:
            from sqlalchemy import update as _update  # noqa: PLC0415

            from src.database.models import Account as _Account  # noqa: PLC0415

            await self._session.execute(
                _update(_Account).where(_Account.id == account_uuid).values(email_verified=True)
            )
            await self._session.flush()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            log.exception(
                "account.email_verification.db_error",
                account_id=str(account_uuid),
                error=str(exc),
            )
            raise DatabaseError("Failed to verify email.") from exc

        # Delete the token so it cannot be reused.
        try:
            await r.delete(redis_key)
        except RedisError as exc:
            # Non-fatal: token TTL will expire it anyway.
            log.warning(
                "account.email_verification.token_delete_failed",
                account_id=str(account_uuid),
                error=str(exc),
            )

        log.info(
            "account.email_verification.success",
            account_id=str(account_uuid),
        )
