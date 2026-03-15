"""Battle wallet management — snapshot, isolate, and restore agent wallets.

Supports two wallet modes:
- **fresh**: Snapshot agent's current state, provision isolated battle wallet,
  restore on battle end.
- **existing**: No-op observation layer — agents trade with their real wallets.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import Balance
from src.database.repositories.balance_repo import BalanceRepository

logger = structlog.get_logger(__name__)


class WalletManager:
    """Manages wallet snapshots and isolation for battle participants.

    Args:
        session: An open AsyncSession. Caller is responsible for committing.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._balance_repo = BalanceRepository(session)

    async def snapshot_wallet(self, agent_id: UUID, account_id: UUID) -> Decimal:
        """Snapshot an agent's current total equity for battle reference.

        Returns the total available + locked balance across all assets
        (simplified as USDT equivalent).
        """
        balances = await self._balance_repo.get_all_by_agent(agent_id)
        total = Decimal("0")
        for bal in balances:
            total += bal.available + bal.locked
        logger.info("wallet.snapshot", agent_id=str(agent_id), total=str(total))
        return total

    async def provision_fresh_wallet(
        self,
        agent_id: UUID,
        account_id: UUID,
        starting_balance: Decimal,
    ) -> None:
        """Provision a fresh USDT wallet for a battle.

        Wipes existing balances for the agent and creates a fresh USDT balance
        with the specified starting amount.

        This is a destructive operation — call ``snapshot_wallet`` first to
        preserve the agent's pre-battle state.
        """
        # Wipe all existing balances
        balances = await self._balance_repo.get_all_by_agent(agent_id)
        for bal in balances:
            await self._session.delete(bal)
        await self._session.flush()

        # Create fresh USDT balance
        fresh = Balance(
            account_id=account_id,
            agent_id=agent_id,
            asset="USDT",
            available=starting_balance,
            locked=Decimal("0"),
        )
        self._session.add(fresh)
        await self._session.flush()

        logger.info(
            "wallet.fresh_provisioned",
            agent_id=str(agent_id),
            starting_balance=str(starting_balance),
        )

    async def restore_wallet(
        self,
        agent_id: UUID,
        account_id: UUID,
        snapshot_balance: Decimal,
    ) -> None:
        """Restore an agent's wallet to its pre-battle snapshot state.

        Wipes battle wallet and recreates a single USDT balance with the
        snapshot amount.
        """
        balances = await self._balance_repo.get_all_by_agent(agent_id)
        for bal in balances:
            await self._session.delete(bal)
        await self._session.flush()

        restored = Balance(
            account_id=account_id,
            agent_id=agent_id,
            asset="USDT",
            available=snapshot_balance,
            locked=Decimal("0"),
        )
        self._session.add(restored)
        await self._session.flush()

        logger.info(
            "wallet.restored",
            agent_id=str(agent_id),
            restored_balance=str(snapshot_balance),
        )

    async def get_agent_equity(self, agent_id: UUID) -> Decimal:
        """Get current total equity for an agent (available + locked)."""
        balances = await self._balance_repo.get_all_by_agent(agent_id)
        total = Decimal("0")
        for bal in balances:
            total += bal.available + bal.locked
        return total
