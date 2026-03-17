"""Unit tests for AccountRepository CRUD operations.

Tests that AccountRepository correctly delegates to the AsyncSession
and raises the expected exceptions on errors.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import Account
from src.database.repositories.account_repo import AccountRepository
from src.utils.exceptions import (
    AccountNotFoundError,
    DatabaseError,
    DuplicateAccountError,
)


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session: AsyncMock) -> AccountRepository:
    return AccountRepository(mock_session)


def _make_account(**kwargs) -> Account:
    """Create an Account instance for testing."""
    defaults = {
        "api_key": "ak_live_test123",
        "api_key_hash": "hash123",
        "api_secret_hash": "secret_hash123",
        "display_name": "TestBot",
        "email": "test@example.com",
    }
    defaults.update(kwargs)
    return Account(**defaults)


class TestCreate:
    async def test_create_account(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """create inserts row, flushes, and refreshes."""
        account = _make_account()
        mock_session.refresh = AsyncMock(return_value=None)

        result = await repo.create(account)

        mock_session.add.assert_called_once_with(account)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(account)
        assert result is account

    async def test_create_duplicate_api_key_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """create raises DuplicateAccountError on api_key constraint violation."""
        account = _make_account()
        orig = Exception("UNIQUE constraint failed: api_key")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DuplicateAccountError):
            await repo.create(account)

        mock_session.rollback.assert_awaited_once()

    async def test_create_duplicate_email_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """create raises DuplicateAccountError on email constraint violation."""
        account = _make_account()
        orig = Exception("UNIQUE constraint failed: email")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DuplicateAccountError):
            await repo.create(account)

    async def test_create_db_error_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """create raises DatabaseError on generic SQLAlchemy error."""
        account = _make_account()
        mock_session.flush.side_effect = SQLAlchemyError("connection lost")

        with pytest.raises(DatabaseError):
            await repo.create(account)

        mock_session.rollback.assert_awaited_once()


class TestGetById:
    async def test_get_by_id_returns_account(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """get_by_id returns account when found."""
        account = _make_account()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = account
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(uuid4())

        assert result is account
        mock_session.execute.assert_awaited_once()

    async def test_get_by_id_not_found_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """get_by_id raises AccountNotFoundError when no row."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AccountNotFoundError):
            await repo.get_by_id(uuid4())

    async def test_get_by_id_db_error_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """get_by_id raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_by_id(uuid4())


class TestGetByApiKey:
    async def test_get_by_api_key_returns_account(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """get_by_api_key returns account when found."""
        account = _make_account()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = account
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_api_key("ak_live_test123")

        assert result is account

    async def test_get_by_api_key_not_found_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """get_by_api_key raises AccountNotFoundError for missing key."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AccountNotFoundError):
            await repo.get_by_api_key("ak_live_nonexistent")


class TestGetByEmail:
    async def test_get_by_email_returns_account(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """get_by_email returns account when found."""
        account = _make_account()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = account
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_email("test@example.com")

        assert result is account

    async def test_get_by_email_not_found_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """get_by_email raises AccountNotFoundError for missing email."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AccountNotFoundError):
            await repo.get_by_email("nobody@example.com")


class TestUpdateStatus:
    async def test_update_status_returns_updated(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """update_status returns the updated account row."""
        account = _make_account()
        account.status = "suspended"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = account
        mock_session.execute.return_value = mock_result

        result = await repo.update_status(uuid4(), "suspended")

        assert result is account
        assert result.status == "suspended"

    async def test_update_status_not_found_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """update_status raises AccountNotFoundError when row missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AccountNotFoundError):
            await repo.update_status(uuid4(), "suspended")


class TestUpdateRiskProfile:
    async def test_update_risk_profile_succeeds(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """update_risk_profile updates the risk_profile field."""
        account = _make_account()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = account
        mock_session.execute.return_value = mock_result

        profile = {"max_open_orders": 20}
        await repo.update_risk_profile(uuid4(), profile)

        assert account.risk_profile == profile
        mock_session.flush.assert_awaited_once()

    async def test_update_risk_profile_not_found_raises(
        self, repo: AccountRepository, mock_session: AsyncMock
    ) -> None:
        """update_risk_profile raises AccountNotFoundError when row missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AccountNotFoundError):
            await repo.update_risk_profile(uuid4(), {"max_open_orders": 10})


class TestListByStatus:
    async def test_list_by_status_returns_accounts(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """list_by_status returns matching accounts."""
        accounts = [_make_account(), _make_account(display_name="Bot2")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = accounts
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_status("active")

        assert len(result) == 2

    async def test_list_by_status_empty(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """list_by_status returns empty list when no matches."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_status("archived")

        assert result == []

    async def test_list_by_status_db_error_raises(self, repo: AccountRepository, mock_session: AsyncMock) -> None:
        """list_by_status raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.list_by_status("active")
