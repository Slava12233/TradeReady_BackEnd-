"""Unit tests for src/accounts/service.py — account lifecycle."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.accounts.service import AccountService
from src.utils.exceptions import (
    AccountSuspendedError,
    AuthenticationError,
    DuplicateAccountError,
)


def _make_settings():
    """Return a mock Settings object with test defaults."""
    s = MagicMock()
    s.default_starting_balance = Decimal("10000")
    s.jwt_secret = "test_secret_that_is_at_least_32_characters_long"
    s.jwt_expiry_hours = 1
    return s


def _make_account(
    *,
    status="active",
    api_key="ak_live_" + "x" * 64,
    password_hash=None,
    starting_balance=Decimal("10000"),
):
    """Return a mock Account row."""
    account = MagicMock()
    account.id = uuid4()
    account.api_key = api_key
    account.api_key_hash = "$2b$12$fakehashfakehashfakehashfakehashfakehashfakehashfake"
    account.api_secret_hash = "$2b$12$fakehashfakehashfakehashfakehashfakehashfakehashfake"
    account.display_name = "TestBot"
    account.email = "test@example.com"
    account.status = status
    account.password_hash = password_hash
    account.starting_balance = starting_balance
    return account


def _make_service(session=None, settings=None):
    """Build an AccountService with mocked deps."""
    if session is None:
        session = AsyncMock()
    if settings is None:
        settings = _make_settings()
    return AccountService(session, settings)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegister:
    @patch("src.accounts.service.generate_api_credentials")
    @patch("src.accounts.service.hash_password")
    async def test_creates_account_and_balance(self, mock_hash_pw, mock_gen_creds):
        from src.accounts.auth import ApiCredentials

        mock_gen_creds.return_value = ApiCredentials(
            api_key="ak_live_" + "a" * 64,
            api_secret="sk_live_" + "b" * 64,
            api_key_hash="$2b$12$hash_key",
            api_secret_hash="$2b$12$hash_secret",
        )
        session = AsyncMock()
        svc = _make_service(session=session)

        # Mock the repo create to set an id on the account
        async def _fake_create(account):
            account.id = uuid4()
            return account

        svc._account_repo.create = AsyncMock(side_effect=_fake_create)

        result = await svc.register("TestBot", email="dev@example.com")

        assert result.api_key.startswith("ak_live_")
        assert result.api_secret.startswith("sk_live_")
        assert result.display_name == "TestBot"
        assert result.starting_balance == Decimal("10000")
        svc._account_repo.create.assert_called_once()
        # Balance and TradingSession creation is handled by AgentService.create_agent(),
        # so register() only creates the Account row via the repo.

    @patch("src.accounts.service.generate_api_credentials")
    async def test_duplicate_email_raises(self, mock_gen_creds):
        from sqlalchemy.exc import IntegrityError

        from src.accounts.auth import ApiCredentials

        mock_gen_creds.return_value = ApiCredentials(
            api_key="ak_live_" + "a" * 64,
            api_secret="sk_live_" + "b" * 64,
            api_key_hash="h1",
            api_secret_hash="h2",
        )
        session = AsyncMock()
        svc = _make_service(session=session)
        svc._account_repo.create = AsyncMock(side_effect=IntegrityError("dup", {}, Exception("email")))

        with pytest.raises(DuplicateAccountError):
            await svc.register("Bot", email="dup@example.com")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuthenticate:
    @patch("src.accounts.service.authenticate_api_key")
    async def test_valid_key_returns_account(self, mock_auth):
        account = _make_account()
        svc = _make_service()
        svc._account_repo.get_by_api_key = AsyncMock(return_value=account)

        result = await svc.authenticate(account.api_key)
        assert result.id == account.id

    @patch("src.accounts.service.authenticate_api_key")
    async def test_suspended_account_raises(self, mock_auth):
        account = _make_account(status="suspended")
        svc = _make_service()
        svc._account_repo.get_by_api_key = AsyncMock(return_value=account)

        with pytest.raises(AccountSuspendedError):
            await svc.authenticate(account.api_key)


class TestAuthenticateWithPassword:
    @patch("src.accounts.service.verify_password", return_value=True)
    async def test_valid_password(self, mock_verify):
        account = _make_account(password_hash="$2b$12$hash")
        svc = _make_service()
        svc._account_repo.get_by_email = AsyncMock(return_value=account)

        result = await svc.authenticate_with_password("test@example.com", "password")
        assert result.id == account.id

    @patch("src.accounts.service.verify_password", return_value=False)
    async def test_wrong_password_raises(self, mock_verify):
        account = _make_account(password_hash="$2b$12$hash")
        svc = _make_service()
        svc._account_repo.get_by_email = AsyncMock(return_value=account)

        with pytest.raises(AuthenticationError, match="Invalid email or password"):
            await svc.authenticate_with_password("test@example.com", "wrong")

    @patch("src.accounts.service.verify_password", return_value=True)
    async def test_suspended_raises(self, mock_verify):
        account = _make_account(status="suspended", password_hash="$2b$12$hash")
        svc = _make_service()
        svc._account_repo.get_by_email = AsyncMock(return_value=account)

        with pytest.raises(AccountSuspendedError):
            await svc.authenticate_with_password("test@example.com", "password")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestGetAccount:
    async def test_delegates_to_repo(self):
        account = _make_account()
        svc = _make_service()
        svc._account_repo.get_by_id = AsyncMock(return_value=account)

        result = await svc.get_account(account.id)
        assert result.id == account.id
        svc._account_repo.get_by_id.assert_called_once_with(account.id)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestResetAccount:
    async def test_reset_cancels_orders_and_recredits(self):
        account = _make_account()
        session = AsyncMock()
        svc = _make_service(session=session)
        svc._account_repo.get_by_id = AsyncMock(return_value=account)
        svc._balance_repo.get_all = AsyncMock(return_value=[MagicMock()])

        await svc.reset_account(account.id)

        # Session.execute called for: cancel orders, close session
        assert session.execute.call_count >= 2
        # Fresh balance was added
        assert session.add.call_count >= 1

    async def test_reset_suspended_raises(self):
        account = _make_account(status="suspended")
        svc = _make_service()
        svc._account_repo.get_by_id = AsyncMock(return_value=account)

        with pytest.raises(AccountSuspendedError):
            await svc.reset_account(account.id)


# ---------------------------------------------------------------------------
# Suspend / Unsuspend
# ---------------------------------------------------------------------------


class TestSuspendUnsuspend:
    async def test_suspend_delegates(self):
        svc = _make_service()
        aid = uuid4()
        svc._account_repo.update_status = AsyncMock()

        await svc.suspend_account(aid)
        svc._account_repo.update_status.assert_called_once_with(aid, "suspended")

    async def test_unsuspend_delegates(self):
        svc = _make_service()
        aid = uuid4()
        svc._account_repo.update_status = AsyncMock()

        await svc.unsuspend_account(aid)
        svc._account_repo.update_status.assert_called_once_with(aid, "active")
