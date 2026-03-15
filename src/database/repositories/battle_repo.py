"""Repository for Battle CRUD operations.

All database access for :class:`~src.database.models.Battle`,
:class:`~src.database.models.BattleParticipant`, and
:class:`~src.database.models.BattleSnapshot` goes through
:class:`BattleRepository`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import Battle, BattleParticipant, BattleSnapshot
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class BattleNotFoundError(Exception):
    """Raised when a battle cannot be found."""

    def __init__(self, message: str = "Battle not found.", *, battle_id: UUID | None = None) -> None:
        self.battle_id = battle_id
        super().__init__(message)


class BattleRepository:
    """Async CRUD repository for battle tables.

    Callers are responsible for committing the session.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Battle CRUD
    # ------------------------------------------------------------------

    async def create_battle(self, battle: Battle) -> Battle:
        """Persist a new Battle row."""
        try:
            self._session.add(battle)
            await self._session.flush()
            await self._session.refresh(battle)
            logger.info("battle.created", battle_id=str(battle.id))
            return battle
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create battle.") from exc

    async def get_battle(self, battle_id: UUID) -> Battle:
        """Fetch a battle by ID."""
        try:
            stmt = select(Battle).where(Battle.id == battle_id)
            result = await self._session.execute(stmt)
            battle = result.scalars().first()
            if battle is None:
                raise BattleNotFoundError(battle_id=battle_id)
            return battle
        except BattleNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("battle.get.db_error", battle_id=str(battle_id), error=str(exc))
            raise DatabaseError("Failed to fetch battle.") from exc

    async def list_battles(
        self,
        account_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Battle]:
        """List battles for an account with optional status filter."""
        try:
            stmt = select(Battle).where(Battle.account_id == account_id)
            if status is not None:
                stmt = stmt.where(Battle.status == status)
            stmt = stmt.order_by(Battle.created_at.desc()).limit(limit).offset(offset)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("battle.list.db_error", account_id=str(account_id), error=str(exc))
            raise DatabaseError("Failed to list battles.") from exc

    async def update_status(self, battle_id: UUID, status: str, **extra_fields: object) -> Battle:
        """Update a battle's status and optional extra fields."""
        try:
            battle = await self.get_battle(battle_id)
            battle.status = status  # type: ignore[assignment]
            for key, value in extra_fields.items():
                setattr(battle, key, value)
            await self._session.flush()
            await self._session.refresh(battle)
            logger.info("battle.status_updated", battle_id=str(battle_id), status=status)
            return battle
        except BattleNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.update_status.db_error", battle_id=str(battle_id), error=str(exc))
            raise DatabaseError("Failed to update battle status.") from exc

    async def update_battle(self, battle_id: UUID, **fields: object) -> Battle:
        """Update specific fields on a battle."""
        try:
            battle = await self.get_battle(battle_id)
            for key, value in fields.items():
                setattr(battle, key, value)
            await self._session.flush()
            await self._session.refresh(battle)
            logger.info("battle.updated", battle_id=str(battle_id), fields=list(fields.keys()))
            return battle
        except BattleNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.update.db_error", battle_id=str(battle_id), error=str(exc))
            raise DatabaseError("Failed to update battle.") from exc

    async def delete_battle(self, battle_id: UUID) -> None:
        """Permanently delete a battle and all associated data (cascade)."""
        try:
            battle = await self.get_battle(battle_id)
            await self._session.delete(battle)
            await self._session.flush()
            logger.info("battle.deleted", battle_id=str(battle_id))
        except BattleNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.delete.db_error", battle_id=str(battle_id), error=str(exc))
            raise DatabaseError("Failed to delete battle.") from exc

    # ------------------------------------------------------------------
    # Participant operations
    # ------------------------------------------------------------------

    async def add_participant(self, participant: BattleParticipant) -> BattleParticipant:
        """Add a participant to a battle."""
        try:
            self._session.add(participant)
            await self._session.flush()
            await self._session.refresh(participant)
            logger.info(
                "battle.participant_added",
                battle_id=str(participant.battle_id),
                agent_id=str(participant.agent_id),
            )
            return participant
        except IntegrityError as exc:
            await self._session.rollback()
            constraint = str(exc.orig) if exc.orig else ""
            if "uq_bp_battle_agent" in constraint:
                raise DatabaseError("Agent is already a participant in this battle.") from exc
            raise DatabaseError(f"Integrity error adding participant: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.add_participant.db_error", error=str(exc))
            raise DatabaseError("Failed to add participant.") from exc

    async def remove_participant(self, battle_id: UUID, agent_id: UUID) -> None:
        """Remove a participant from a battle."""
        try:
            stmt = select(BattleParticipant).where(
                BattleParticipant.battle_id == battle_id,
                BattleParticipant.agent_id == agent_id,
            )
            result = await self._session.execute(stmt)
            participant = result.scalars().first()
            if participant is None:
                raise BattleNotFoundError("Participant not found in this battle.")
            await self._session.delete(participant)
            await self._session.flush()
            logger.info("battle.participant_removed", battle_id=str(battle_id), agent_id=str(agent_id))
        except BattleNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.remove_participant.db_error", error=str(exc))
            raise DatabaseError("Failed to remove participant.") from exc

    async def get_participants(self, battle_id: UUID) -> Sequence[BattleParticipant]:
        """Get all participants for a battle."""
        try:
            stmt = (
                select(BattleParticipant)
                .where(BattleParticipant.battle_id == battle_id)
                .order_by(BattleParticipant.joined_at.asc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("battle.get_participants.db_error", battle_id=str(battle_id), error=str(exc))
            raise DatabaseError("Failed to get participants.") from exc

    async def get_participant(self, battle_id: UUID, agent_id: UUID) -> BattleParticipant:
        """Get a specific participant."""
        try:
            stmt = select(BattleParticipant).where(
                BattleParticipant.battle_id == battle_id,
                BattleParticipant.agent_id == agent_id,
            )
            result = await self._session.execute(stmt)
            participant = result.scalars().first()
            if participant is None:
                raise BattleNotFoundError("Participant not found in this battle.")
            return participant
        except BattleNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("battle.get_participant.db_error", error=str(exc))
            raise DatabaseError("Failed to get participant.") from exc

    async def update_participant(
        self, battle_id: UUID, agent_id: UUID, **fields: object
    ) -> BattleParticipant:
        """Update fields on a participant."""
        try:
            participant = await self.get_participant(battle_id, agent_id)
            for key, value in fields.items():
                setattr(participant, key, value)
            await self._session.flush()
            await self._session.refresh(participant)
            return participant
        except BattleNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.update_participant.db_error", error=str(exc))
            raise DatabaseError("Failed to update participant.") from exc

    # ------------------------------------------------------------------
    # Snapshot operations
    # ------------------------------------------------------------------

    async def insert_snapshot(self, snapshot: BattleSnapshot) -> BattleSnapshot:
        """Insert a single battle snapshot."""
        try:
            self._session.add(snapshot)
            await self._session.flush()
            return snapshot
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.insert_snapshot.db_error", error=str(exc))
            raise DatabaseError("Failed to insert battle snapshot.") from exc

    async def insert_snapshots_bulk(self, snapshots: list[BattleSnapshot]) -> None:
        """Insert multiple battle snapshots in bulk."""
        try:
            self._session.add_all(snapshots)
            await self._session.flush()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("battle.insert_snapshots_bulk.db_error", error=str(exc))
            raise DatabaseError("Failed to insert battle snapshots.") from exc

    async def get_snapshots(
        self,
        battle_id: UUID,
        *,
        agent_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 10000,
        offset: int = 0,
    ) -> Sequence[BattleSnapshot]:
        """Get time-series snapshots for a battle with optional filters."""
        try:
            stmt = select(BattleSnapshot).where(BattleSnapshot.battle_id == battle_id)
            if agent_id is not None:
                stmt = stmt.where(BattleSnapshot.agent_id == agent_id)
            if since is not None:
                stmt = stmt.where(BattleSnapshot.timestamp >= since)
            if until is not None:
                stmt = stmt.where(BattleSnapshot.timestamp <= until)
            stmt = stmt.order_by(BattleSnapshot.timestamp.asc()).limit(limit).offset(offset)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("battle.get_snapshots.db_error", battle_id=str(battle_id), error=str(exc))
            raise DatabaseError("Failed to get battle snapshots.") from exc

    async def count_snapshots(self, battle_id: UUID) -> int:
        """Count total snapshots for a battle."""
        try:
            stmt = (
                select(func.count())
                .select_from(BattleSnapshot)
                .where(BattleSnapshot.battle_id == battle_id)
            )
            result = await self._session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as exc:
            logger.exception("battle.count_snapshots.db_error", battle_id=str(battle_id), error=str(exc))
            raise DatabaseError("Failed to count battle snapshots.") from exc
