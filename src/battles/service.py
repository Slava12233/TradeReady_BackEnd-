"""Battle service — full lifecycle management for agent battles.

Coordinates :class:`BattleRepository`, :class:`WalletManager`, and
:class:`RankingCalculator` to implement battle lifecycle operations.

State machine:
    draft → pending → active → completed
             └─ cancelled   └─ paused → active
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.battles.presets import get_preset_config
from src.battles.ranking import ParticipantMetrics, RankingCalculator
from src.battles.wallet_manager import WalletManager
from src.config import Settings
from src.database.models import Battle, BattleParticipant
from src.database.repositories.agent_repo import AgentRepository
from src.database.repositories.battle_repo import BattleRepository
from src.database.repositories.trade_repo import TradeRepository
from src.utils.exceptions import PermissionDeniedError

logger = structlog.get_logger(__name__)

# Valid state transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending", "cancelled"},
    "pending": {"active", "cancelled"},
    "active": {"paused", "completed", "cancelled"},
    "paused": {"active", "completed", "cancelled"},
}


class BattleInvalidStateError(Exception):
    """Raised when a battle operation is attempted in the wrong state."""

    def __init__(
        self,
        message: str = "Battle is not in the required state.",
        *,
        current_status: str | None = None,
        required_status: str | None = None,
    ) -> None:
        self.current_status = current_status
        self.required_status = required_status
        super().__init__(message)


class BattleService:
    """Business-logic layer for battle lifecycle management.

    Args:
        session:  An open AsyncSession. Caller is responsible for committing.
        settings: Application Settings.
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._battle_repo = BattleRepository(session)
        self._agent_repo = AgentRepository(session)
        self._trade_repo = TradeRepository(session)
        self._wallet_manager = WalletManager(session)
        self._ranking = RankingCalculator()

    def _validate_transition(self, current: str, target: str) -> None:
        """Validate a state transition is allowed."""
        valid = _VALID_TRANSITIONS.get(current, set())
        if target not in valid:
            raise BattleInvalidStateError(
                f"Cannot transition from '{current}' to '{target}'.",
                current_status=current,
                required_status=target,
            )

    # ------------------------------------------------------------------
    # Battle CRUD
    # ------------------------------------------------------------------

    async def create_battle(
        self,
        account_id: UUID,
        name: str,
        *,
        preset: str | None = None,
        config: dict[str, object] | None = None,
        ranking_metric: str = "roi_pct",
    ) -> Battle:
        """Create a new battle in draft status.

        If a preset is specified, its config is used as the base. Custom
        config values override preset defaults.
        """
        battle_config: dict[str, object] = {}
        if preset:
            battle_config = get_preset_config(preset)
        if config:
            battle_config.update(config)

        battle = Battle(
            account_id=account_id,
            name=name,
            status="draft",
            config=battle_config,
            preset=preset,
            ranking_metric=ranking_metric,
        )
        return await self._battle_repo.create_battle(battle)

    async def get_battle(self, battle_id: UUID) -> Battle:
        """Fetch a battle by ID."""
        return await self._battle_repo.get_battle(battle_id)

    async def list_battles(
        self,
        account_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Battle]:
        """List battles for an account."""
        return await self._battle_repo.list_battles(
            account_id, status=status, limit=limit, offset=offset
        )

    async def update_battle(
        self,
        battle_id: UUID,
        account_id: UUID,
        **fields: object,
    ) -> Battle:
        """Update a battle's configuration (draft only)."""
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        if battle.status != "draft":
            raise BattleInvalidStateError(
                "Can only update battles in draft status.",
                current_status=battle.status,
                required_status="draft",
            )
        return await self._battle_repo.update_battle(battle_id, **fields)

    async def delete_battle(self, battle_id: UUID, account_id: UUID) -> None:
        """Delete or cancel a battle."""
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        if battle.status in ("active", "paused"):
            # Cancel instead of delete for active battles
            await self.cancel_battle(battle_id, account_id)
        else:
            await self._battle_repo.delete_battle(battle_id)

    # ------------------------------------------------------------------
    # Participant management
    # ------------------------------------------------------------------

    async def add_participant(
        self,
        battle_id: UUID,
        agent_id: UUID,
        account_id: UUID,
    ) -> BattleParticipant:
        """Add an agent to a battle (draft or pending only)."""
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        if battle.status not in ("draft", "pending"):
            raise BattleInvalidStateError(
                "Can only add participants to draft/pending battles.",
                current_status=battle.status,
            )

        # Verify agent exists and belongs to account
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent.account_id != account_id:
            raise PermissionDeniedError("You do not own this agent.")

        participant = BattleParticipant(
            battle_id=battle_id,
            agent_id=agent_id,
            status="active",
        )
        return await self._battle_repo.add_participant(participant)

    async def remove_participant(
        self,
        battle_id: UUID,
        agent_id: UUID,
        account_id: UUID,
    ) -> None:
        """Remove an agent from a battle (draft or pending only)."""
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        if battle.status not in ("draft", "pending"):
            raise BattleInvalidStateError(
                "Can only remove participants from draft/pending battles.",
                current_status=battle.status,
            )
        await self._battle_repo.remove_participant(battle_id, agent_id)

    async def get_participants(self, battle_id: UUID) -> Sequence[BattleParticipant]:
        """Get all participants for a battle."""
        return await self._battle_repo.get_participants(battle_id)

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    async def start_battle(self, battle_id: UUID, account_id: UUID) -> Battle:
        """Start a battle — lock config, snapshot wallets, transition to active.

        Requires at least 2 participants.
        """
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")

        # Allow starting from draft or pending
        if battle.status == "draft":
            self._validate_transition("draft", "pending")
        self._validate_transition(battle.status if battle.status == "pending" else "pending", "active")

        participants = await self._battle_repo.get_participants(battle_id)
        if len(participants) < 2:
            raise BattleInvalidStateError("Need at least 2 participants to start a battle.")

        wallet_mode = battle.config.get("wallet_mode", "existing") if isinstance(battle.config, dict) else "existing"
        starting_balance_str = (
            battle.config.get("starting_balance", "10000") if isinstance(battle.config, dict) else "10000"
        )
        starting_balance = Decimal(str(starting_balance_str))

        # Snapshot and optionally provision fresh wallets
        for participant in participants:
            agent = await self._agent_repo.get_by_id(participant.agent_id)
            snapshot = await self._wallet_manager.snapshot_wallet(
                participant.agent_id, agent.account_id
            )
            await self._battle_repo.update_participant(
                battle_id, participant.agent_id, snapshot_balance=snapshot
            )

            if wallet_mode == "fresh":
                await self._wallet_manager.provision_fresh_wallet(
                    participant.agent_id, agent.account_id, starting_balance
                )

        now = datetime.now(UTC)
        return await self._battle_repo.update_status(
            battle_id, "active", started_at=now
        )

    async def pause_agent(
        self,
        battle_id: UUID,
        agent_id: UUID,
        account_id: UUID,
    ) -> BattleParticipant:
        """Pause an individual agent in an active battle."""
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        if battle.status != "active":
            raise BattleInvalidStateError(
                "Can only pause agents in active battles.",
                current_status=battle.status,
            )

        participant = await self._battle_repo.get_participant(battle_id, agent_id)
        if participant.status != "active":
            raise BattleInvalidStateError(
                f"Agent is {participant.status}, not active.",
                current_status=participant.status,
            )

        return await self._battle_repo.update_participant(
            battle_id, agent_id, status="paused"
        )

    async def resume_agent(
        self,
        battle_id: UUID,
        agent_id: UUID,
        account_id: UUID,
    ) -> BattleParticipant:
        """Resume a paused agent in an active battle."""
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        if battle.status != "active":
            raise BattleInvalidStateError(
                "Can only resume agents in active battles.",
                current_status=battle.status,
            )

        participant = await self._battle_repo.get_participant(battle_id, agent_id)
        if participant.status != "paused":
            raise BattleInvalidStateError(
                f"Agent is {participant.status}, not paused.",
                current_status=participant.status,
            )

        return await self._battle_repo.update_participant(
            battle_id, agent_id, status="active"
        )

    async def stop_battle(self, battle_id: UUID, account_id: UUID) -> Battle:
        """Stop a battle — calculate final rankings and complete.

        Force-closes all positions (conceptually) and calculates final
        rankings based on the battle's ranking metric.
        """
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        self._validate_transition(battle.status, "completed")

        participants = await self._battle_repo.get_participants(battle_id)
        wallet_mode = battle.config.get("wallet_mode", "existing") if isinstance(battle.config, dict) else "existing"

        # Calculate final metrics for each participant
        all_metrics: list[ParticipantMetrics] = []
        for participant in participants:
            agent = await self._agent_repo.get_by_id(participant.agent_id)
            final_equity = await self._wallet_manager.get_agent_equity(participant.agent_id)
            start_balance = participant.snapshot_balance or Decimal(str(agent.starting_balance))

            snapshots = await self._battle_repo.get_snapshots(
                battle_id, agent_id=participant.agent_id
            )
            trades = await self._trade_repo.list_by_agent(participant.agent_id)

            metrics = self._ranking.compute_participant_metrics(
                agent_id=participant.agent_id,
                start_balance=start_balance,
                final_equity=final_equity,
                snapshots=snapshots,
                trades=trades,
            )
            all_metrics.append(metrics)

        # Rank participants
        ranked = self._ranking.rank_participants(all_metrics, battle.ranking_metric)

        # Update participant final stats
        for rank, metrics in enumerate(ranked, 1):
            await self._battle_repo.update_participant(
                battle_id,
                metrics.agent_id,
                final_equity=metrics.final_equity,
                final_rank=rank,
                status="stopped",
            )

        # Restore wallets if fresh mode was used
        if wallet_mode == "fresh":
            for participant in participants:
                if participant.snapshot_balance is not None:
                    agent = await self._agent_repo.get_by_id(participant.agent_id)
                    await self._wallet_manager.restore_wallet(
                        participant.agent_id,
                        agent.account_id,
                        participant.snapshot_balance,
                    )

        now = datetime.now(UTC)
        return await self._battle_repo.update_status(
            battle_id, "completed", ended_at=now
        )

    async def cancel_battle(self, battle_id: UUID, account_id: UUID) -> Battle:
        """Cancel a battle — no rankings, data preserved."""
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        self._validate_transition(battle.status, "cancelled")

        # Restore wallets if fresh mode and battle was active
        if battle.status in ("active", "paused"):
            config = battle.config if isinstance(battle.config, dict) else {}
            wallet_mode = config.get("wallet_mode", "existing")
            if wallet_mode == "fresh":
                participants = await self._battle_repo.get_participants(battle_id)
                for participant in participants:
                    if participant.snapshot_balance is not None:
                        agent = await self._agent_repo.get_by_id(participant.agent_id)
                        await self._wallet_manager.restore_wallet(
                            participant.agent_id,
                            agent.account_id,
                            participant.snapshot_balance,
                        )

        now = datetime.now(UTC)
        return await self._battle_repo.update_status(
            battle_id, "cancelled", ended_at=now
        )

    # ------------------------------------------------------------------
    # Live data
    # ------------------------------------------------------------------

    async def get_live_snapshot(self, battle_id: UUID) -> list[dict[str, object]]:
        """Get live metrics for all participants in an active battle."""
        await self._battle_repo.get_battle(battle_id)  # verify exists
        participants = await self._battle_repo.get_participants(battle_id)

        results: list[dict[str, object]] = []
        for participant in participants:
            agent = await self._agent_repo.get_by_id(participant.agent_id)
            equity = await self._wallet_manager.get_agent_equity(participant.agent_id)
            start = participant.snapshot_balance or Decimal(str(agent.starting_balance))
            pnl = equity - start
            pnl_pct = (pnl / start * 100) if start > 0 else Decimal("0")

            results.append({
                "agent_id": str(participant.agent_id),
                "display_name": agent.display_name,
                "equity": str(equity),
                "pnl": str(pnl),
                "pnl_pct": str(round(pnl_pct, 2)),
                "status": participant.status,
            })

        return results

    async def get_results(self, battle_id: UUID) -> dict[str, object]:
        """Get final results for a completed battle."""
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.status != "completed":
            raise BattleInvalidStateError(
                "Battle is not completed yet.",
                current_status=battle.status,
                required_status="completed",
            )

        participants = await self._battle_repo.get_participants(battle_id)
        ranked = sorted(
            [p for p in participants if p.final_rank is not None],
            key=lambda p: p.final_rank or 999,
        )

        return {
            "battle_id": str(battle.id),
            "name": battle.name,
            "ranking_metric": battle.ranking_metric,
            "started_at": battle.started_at.isoformat() if battle.started_at else None,
            "ended_at": battle.ended_at.isoformat() if battle.ended_at else None,
            "participants": [
                {
                    "agent_id": str(p.agent_id),
                    "rank": p.final_rank,
                    "final_equity": str(p.final_equity) if p.final_equity else None,
                    "snapshot_balance": str(p.snapshot_balance) if p.snapshot_balance else None,
                    "status": p.status,
                }
                for p in ranked
            ],
        }

    async def get_replay_data(
        self,
        battle_id: UUID,
        *,
        limit: int = 10000,
        offset: int = 0,
    ) -> Sequence:
        """Get time-series snapshots for replay."""
        return await self._battle_repo.get_snapshots(
            battle_id, limit=limit, offset=offset
        )
