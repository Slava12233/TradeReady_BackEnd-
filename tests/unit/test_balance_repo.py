"""Unit tests for BalanceRepository CRUD and atomic operations.

Tests that BalanceRepository correctly delegates to the AsyncSession,
handles Decimal precision, and raises expected exceptions.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import Balance
from src.database.repositories.balance_repo import BalanceRepository
from src.utils.exceptions import DatabaseError, InsufficientBalanceError


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.rollback = AsyncMock()
    # begin_nested returns an async context manager
    nested = AsyncMock()
    nested.__aenter__ = AsyncMock()
    nested.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested)
    return session


@pytest.fixture
def repo(mock_session: AsyncMock) -> BalanceRepository:
    return BalanceRepository(mock_session)


def _make_balance(
    account_id=None,
    agent_id=None,
    asset="USDT",
    available="10000.00000000",
    locked="0.00000000",
) -> Balance:
    """Create a Balance instance for testing."""
    return Balance(
        account_id=account_id or uuid4(),
        agent_id=agent_id,
        asset=asset,
        available=Decimal(available),
        locked=Decimal(locked),
    )


class TestGet:
    async def test_get_balance_returns_balance(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """get returns balance for account+asset pair."""
        bal = _make_balance()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = bal
        mock_session.execute.return_value = mock_result

        result = await repo.get(uuid4(), "USDT")

        assert result is bal

    async def test_get_balance_not_found_returns_none(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """get returns None for missing asset."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.get(uuid4(), "BTC")

        assert result is None

    async def test_get_balance_db_error_raises(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """get raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("connection lost")

        with pytest.raises(DatabaseError):
            await repo.get(uuid4(), "USDT")


class TestGetByAgent:
    async def test_get_by_agent_returns_balance(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """get_by_agent returns balance scoped to agent_id."""
        agent_id = uuid4()
        bal = _make_balance(agent_id=agent_id, asset="BTC")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = bal
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_agent(agent_id, "BTC")

        assert result is bal
        mock_session.execute.assert_awaited_once()
        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "agent_id" in compiled

    async def test_get_by_agent_not_found_returns_none(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """get_by_agent returns None for missing agent/asset pair."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_agent(uuid4(), "ETH")

        assert result is None


class TestGetAll:
    async def test_get_all_balances_returns_list(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """get_all returns all non-zero balances for account."""
        account_id = uuid4()
        balances = [
            _make_balance(account_id=account_id, asset="USDT"),
            _make_balance(account_id=account_id, asset="BTC", available="0.50000000"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = balances
        mock_session.execute.return_value = mock_result

        result = await repo.get_all(account_id)

        assert len(result) == 2

    async def test_get_all_empty_returns_empty_list(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """get_all returns empty list when no balances exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.get_all(uuid4())

        assert result == []


class TestCreate:
    async def test_create_balance(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """create inserts balance row and flushes."""
        bal = _make_balance()

        result = await repo.create(bal)

        mock_session.add.assert_called_once_with(bal)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(bal)
        assert result is bal

    async def test_create_duplicate_raises(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """create raises DatabaseError on duplicate constraint violation."""
        bal = _make_balance()
        orig = Exception("unique violation")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.create(bal)

        mock_session.rollback.assert_awaited_once()


class TestUpdateAvailable:
    async def test_credit_increases_available(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """update_available with positive delta credits balance."""
        bal = _make_balance(available="10500.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = bal
        mock_session.execute.return_value = mock_result

        result = await repo.update_available(uuid4(), "USDT", Decimal("500"))

        assert result is bal

    async def test_debit_decreases_available(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """update_available with negative delta debits balance."""
        bal = _make_balance(available="9800.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = bal
        mock_session.execute.return_value = mock_result

        result = await repo.update_available(uuid4(), "USDT", Decimal("-200"))

        assert result is bal

    async def test_debit_insufficient_raises(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """update_available raises InsufficientBalanceError on CHECK violation."""
        orig = Exception("check constraint violated")
        mock_session.execute.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(InsufficientBalanceError):
            await repo.update_available(uuid4(), "USDT", Decimal("-99999"))

        mock_session.rollback.assert_awaited_once()

    async def test_update_available_not_found_raises(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """update_available raises DatabaseError when balance row missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(DatabaseError):
            await repo.update_available(uuid4(), "USDT", Decimal("100"))


class TestUpdateLocked:
    async def test_lock_funds_increases_locked(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """update_locked with positive delta locks funds."""
        bal = _make_balance(locked="100.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = bal
        mock_session.execute.return_value = mock_result

        result = await repo.update_locked(uuid4(), "USDT", Decimal("100"))

        assert result is bal

    async def test_unlock_funds_decreases_locked(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """update_locked with negative delta unlocks funds."""
        bal = _make_balance(locked="0.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = bal
        mock_session.execute.return_value = mock_result

        result = await repo.update_locked(uuid4(), "USDT", Decimal("-100"))

        assert result is bal

    async def test_unlock_insufficient_raises(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """update_locked raises InsufficientBalanceError on CHECK violation."""
        orig = Exception("check constraint violated")
        mock_session.execute.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(InsufficientBalanceError):
            await repo.update_locked(uuid4(), "USDT", Decimal("-99999"))


class TestAtomicLockFunds:
    async def test_atomic_lock_moves_available_to_locked(
        self, repo: BalanceRepository, mock_session: AsyncMock
    ) -> None:
        """atomic_lock_funds moves amount from available to locked."""
        bal = _make_balance(available="9500.00000000", locked="500.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = bal
        mock_session.execute.return_value = mock_result

        result = await repo.atomic_lock_funds(uuid4(), "USDT", Decimal("500"))

        assert result is bal

    async def test_atomic_lock_zero_amount_raises_value_error(self, repo: BalanceRepository) -> None:
        """atomic_lock_funds rejects zero/negative amount."""
        with pytest.raises(ValueError, match="must be positive"):
            await repo.atomic_lock_funds(uuid4(), "USDT", Decimal("0"))

    async def test_atomic_lock_insufficient_raises(self, repo: BalanceRepository, mock_session: AsyncMock) -> None:
        """atomic_lock_funds raises InsufficientBalanceError when not enough available."""
        orig = Exception("check constraint violated")
        mock_session.execute.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(InsufficientBalanceError):
            await repo.atomic_lock_funds(uuid4(), "USDT", Decimal("99999"))


class TestAtomicUnlockFunds:
    async def test_atomic_unlock_moves_locked_to_available(
        self, repo: BalanceRepository, mock_session: AsyncMock
    ) -> None:
        """atomic_unlock_funds moves amount from locked to available."""
        bal = _make_balance(available="10500.00000000", locked="0.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = bal
        mock_session.execute.return_value = mock_result

        result = await repo.atomic_unlock_funds(uuid4(), "USDT", Decimal("500"))

        assert result is bal

    async def test_atomic_unlock_zero_amount_raises_value_error(self, repo: BalanceRepository) -> None:
        """atomic_unlock_funds rejects zero/negative amount."""
        with pytest.raises(ValueError, match="must be positive"):
            await repo.atomic_unlock_funds(uuid4(), "USDT", Decimal("-1"))
