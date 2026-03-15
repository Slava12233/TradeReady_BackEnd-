"""Unit tests for WalletManager — snapshot/restore, isolation."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.battles.wallet_manager import WalletManager


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def manager(mock_session):
    mgr = WalletManager(mock_session)
    mgr._balance_repo = AsyncMock()
    return mgr


class TestSnapshotWallet:
    async def test_snapshot_sums_all_balances(self, manager):
        bal1 = MagicMock()
        bal1.available = Decimal("5000")
        bal1.locked = Decimal("1000")

        bal2 = MagicMock()
        bal2.available = Decimal("3000")
        bal2.locked = Decimal("500")

        manager._balance_repo.get_all_by_agent.return_value = [bal1, bal2]

        total = await manager.snapshot_wallet(uuid4(), uuid4())
        assert total == Decimal("9500")

    async def test_snapshot_empty_wallet(self, manager):
        manager._balance_repo.get_all_by_agent.return_value = []
        total = await manager.snapshot_wallet(uuid4(), uuid4())
        assert total == Decimal("0")


class TestProvisionFreshWallet:
    async def test_wipes_and_creates_fresh(self, manager, mock_session):
        old_bal = MagicMock()
        manager._balance_repo.get_all_by_agent.return_value = [old_bal]

        await manager.provision_fresh_wallet(uuid4(), uuid4(), Decimal("10000"))

        # Should delete old balance
        mock_session.delete.assert_called_once_with(old_bal)
        # Should add new USDT balance
        mock_session.add.assert_called_once()
        new_bal = mock_session.add.call_args[0][0]
        assert new_bal.asset == "USDT"
        assert new_bal.available == Decimal("10000")
        assert new_bal.locked == Decimal("0")


class TestRestoreWallet:
    async def test_restores_snapshot_balance(self, manager, mock_session):
        battle_bal = MagicMock()
        manager._balance_repo.get_all_by_agent.return_value = [battle_bal]

        await manager.restore_wallet(uuid4(), uuid4(), Decimal("8500"))

        mock_session.delete.assert_called_once_with(battle_bal)
        mock_session.add.assert_called_once()
        restored_bal = mock_session.add.call_args[0][0]
        assert restored_bal.available == Decimal("8500")


class TestGetAgentEquity:
    async def test_sums_balances(self, manager):
        bal = MagicMock()
        bal.available = Decimal("7000")
        bal.locked = Decimal("2000")
        manager._balance_repo.get_all_by_agent.return_value = [bal]

        equity = await manager.get_agent_equity(uuid4())
        assert equity == Decimal("9000")
