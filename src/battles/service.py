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

from src.api.websocket.channels import BattleChannel
from src.battles.presets import get_preset_config
from src.battles.ranking import ParticipantMetrics, RankingCalculator
from src.battles.wallet_manager import WalletManager
from src.config import Settings
from src.database.models import Battle, BattleParticipant
from src.database.repositories.agent_repo import AgentRepository
from src.database.repositories.battle_repo import BattleRepository
from src.database.repositories.trade_repo import TradeRepository
from src.utils.exceptions import BattleInvalidStateError, PermissionDeniedError

logger = structlog.get_logger(__name__)

# Notification event types emitted via WebSocket status channel
NOTIFY_BATTLE_STARTED = "battle_started"
NOTIFY_BATTLE_COMPLETED = "battle_completed"
NOTIFY_BATTLE_CANCELLED = "battle_cancelled"
NOTIFY_AGENT_PAUSED = "agent_paused"
NOTIFY_AGENT_RESUMED = "agent_resumed"
NOTIFY_AGENT_BLOWN_UP = "agent_blown_up"
NOTIFY_AGENT_TOOK_LEAD = "agent_took_lead"

# Valid state transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending", "cancelled"},
    "pending": {"active", "cancelled"},
    "active": {"paused", "completed", "cancelled"},
    "paused": {"active", "completed", "cancelled"},
}


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

    @staticmethod
    def _emit_notification(
        battle_id: UUID,
        event: str,
        data: dict[str, object] | None = None,
    ) -> None:
        """Emit a battle notification via the WebSocket status channel.

        This is a fire-and-forget log + serialization helper.  The actual
        broadcast happens in the route layer or Celery task where a
        :class:`ConnectionManager` reference is available.  Here we only
        build the payload and log it so the route layer can pick it up
        from ``battle._pending_notifications`` if we decide to buffer.
        For now we simply log, and the route handlers broadcast directly.
        """
        payload = BattleChannel.serialize_status(
            str(battle_id), event, data or {}
        )
        logger.info(
            "battle.notification",
            battle_id=str(battle_id),
            event_type=event,
            payload=payload,
        )

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
        battle_mode: str = "live",
        backtest_config: dict[str, object] | None = None,
    ) -> Battle:
        """Create a new battle in draft status.

        If a preset is specified, its config is used as the base. Custom
        config values override preset defaults.

        Args:
            account_id:     Owner account UUID.
            name:           Battle name.
            preset:         Optional preset key.
            config:         Custom config overrides.
            ranking_metric: Metric for ranking.
            battle_mode:    ``"live"`` or ``"historical"``.
            backtest_config: Required if ``battle_mode == "historical"``.
        """
        battle_config: dict[str, object] = {}
        if preset:
            battle_config = get_preset_config(preset)
        if config:
            battle_config.update(config)

        # Validate historical mode
        if battle_mode == "historical" and not backtest_config:
            raise BattleInvalidStateError(
                "backtest_config is required for historical battles.",
            )

        battle = Battle(
            account_id=account_id,
            name=name,
            status="draft",
            config=battle_config,
            preset=preset,
            ranking_metric=ranking_metric,
            battle_mode=battle_mode,
            backtest_config=backtest_config,
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

        For live battles: snapshots/provisions wallets per existing flow.
        For historical battles: creates HistoricalBattleEngine, no wallet changes.
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

        starting_balance_str = (
            battle.config.get("starting_balance", "10000") if isinstance(battle.config, dict) else "10000"
        )
        starting_balance = Decimal(str(starting_balance_str))

        if getattr(battle, "battle_mode", "live") == "historical":
            # Historical mode — use HistoricalBattleEngine
            await self._start_historical_battle(battle, participants, starting_balance)
        else:
            # Live mode — existing wallet snapshot/provision flow
            await self._start_live_battle(battle, participants, starting_balance)

        now = datetime.now(UTC)
        result = await self._battle_repo.update_status(
            battle_id, "active", started_at=now
        )
        self._emit_notification(
            battle_id,
            NOTIFY_BATTLE_STARTED,
            {"battle_name": battle.name, "participant_count": len(participants)},
        )
        return result

    async def _start_live_battle(
        self,
        battle: Battle,
        participants: Sequence[BattleParticipant],
        starting_balance: Decimal,
    ) -> None:
        """Start a live battle: snapshot and provision wallets."""
        wallet_mode = battle.config.get("wallet_mode", "existing") if isinstance(battle.config, dict) else "existing"

        for participant in participants:
            agent = await self._agent_repo.get_by_id(participant.agent_id)
            snapshot = await self._wallet_manager.snapshot_wallet(
                participant.agent_id, agent.account_id
            )
            await self._battle_repo.update_participant(
                battle.id, participant.agent_id, snapshot_balance=snapshot
            )

            if wallet_mode == "fresh":
                await self._wallet_manager.provision_fresh_wallet(
                    participant.agent_id, agent.account_id, starting_balance
                )

    async def _start_historical_battle(
        self,
        battle: Battle,
        participants: Sequence[BattleParticipant],
        starting_balance: Decimal,
    ) -> None:
        """Start a historical battle: create and initialize HistoricalBattleEngine."""
        from src.battles.historical_engine import (  # noqa: PLC0415
            HistoricalBattleEngine,
            register_engine,
        )

        backtest_cfg = battle.backtest_config
        if not backtest_cfg:
            raise BattleInvalidStateError("Historical battle requires backtest_config.")

        agent_ids = [p.agent_id for p in participants]
        engine = HistoricalBattleEngine(
            battle_id=str(battle.id),
            config=backtest_cfg,
            participant_agent_ids=agent_ids,
            starting_balance=starting_balance,
            ranking_metric=battle.ranking_metric,
        )
        await engine.initialize(self._session)
        register_engine(str(battle.id), engine)

        # Set snapshot balance for all participants (virtual starting balance)
        for participant in participants:
            await self._battle_repo.update_participant(
                battle.id, participant.agent_id, snapshot_balance=starting_balance
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

        result = await self._battle_repo.update_participant(
            battle_id, agent_id, status="paused"
        )
        self._emit_notification(
            battle_id,
            NOTIFY_AGENT_PAUSED,
            {"agent_id": str(agent_id), "battle_name": battle.name},
        )
        return result

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

        result = await self._battle_repo.update_participant(
            battle_id, agent_id, status="active"
        )
        self._emit_notification(
            battle_id,
            NOTIFY_AGENT_RESUMED,
            {"agent_id": str(agent_id), "battle_name": battle.name},
        )
        return result

    async def stop_battle(self, battle_id: UUID, account_id: UUID) -> Battle:
        """Stop a battle — calculate final rankings and complete.

        For live battles: force-closes positions, calculates rankings, restores wallets.
        For historical battles: calls engine.complete() for rankings and persistence.
        """
        battle = await self._battle_repo.get_battle(battle_id)
        if battle.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        self._validate_transition(battle.status, "completed")

        participants = await self._battle_repo.get_participants(battle_id)

        if getattr(battle, "battle_mode", "live") == "historical":
            await self._stop_historical_battle(battle, participants)
        else:
            await self._stop_live_battle(battle, participants)

        now = datetime.now(UTC)
        result = await self._battle_repo.update_status(
            battle_id, "completed", ended_at=now
        )

        # Determine winner from updated participants
        updated_participants = await self._battle_repo.get_participants(battle_id)
        ranked = sorted(
            [p for p in updated_participants if p.final_rank is not None],
            key=lambda p: p.final_rank or 999,
        )
        winner_agent_id = str(ranked[0].agent_id) if ranked else None

        self._emit_notification(
            battle_id,
            NOTIFY_BATTLE_COMPLETED,
            {
                "battle_name": battle.name,
                "winner_agent_id": winner_agent_id,
                "participant_count": len(participants),
            },
        )
        return result

    async def _stop_live_battle(
        self,
        battle: Battle,
        participants: Sequence[BattleParticipant],
    ) -> None:
        """Stop a live battle: compute rankings, restore wallets."""
        wallet_mode = battle.config.get("wallet_mode", "existing") if isinstance(battle.config, dict) else "existing"

        all_metrics: list[ParticipantMetrics] = []
        for participant in participants:
            agent = await self._agent_repo.get_by_id(participant.agent_id)
            final_equity = await self._wallet_manager.get_agent_equity(participant.agent_id)
            start_balance = participant.snapshot_balance or Decimal(str(agent.starting_balance))

            snapshots = await self._battle_repo.get_snapshots(
                battle.id, agent_id=participant.agent_id
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

        ranked = self._ranking.rank_participants(all_metrics, battle.ranking_metric)

        for rank, metrics in enumerate(ranked, 1):
            await self._battle_repo.update_participant(
                battle.id,
                metrics.agent_id,
                final_equity=metrics.final_equity,
                final_rank=rank,
                status="stopped",
            )

        if wallet_mode == "fresh":
            for participant in participants:
                if participant.snapshot_balance is not None:
                    agent = await self._agent_repo.get_by_id(participant.agent_id)
                    await self._wallet_manager.restore_wallet(
                        participant.agent_id,
                        agent.account_id,
                        participant.snapshot_balance,
                    )

    async def _stop_historical_battle(
        self,
        battle: Battle,
        participants: Sequence[BattleParticipant],
    ) -> None:
        """Stop a historical battle: run engine.complete(), update participants."""
        from src.battles.historical_engine import get_engine, remove_engine  # noqa: PLC0415

        engine = get_engine(str(battle.id))
        if engine is None:
            raise BattleInvalidStateError("Historical battle engine not found.")

        results = await engine.complete(self._session)

        # Rank and update participants
        metric_key = battle.ranking_metric if results and battle.ranking_metric in results[0] else "roi_pct"
        ranked = sorted(results, key=lambda r: r.get(metric_key, Decimal("0")), reverse=True)

        for rank, r in enumerate(ranked, 1):
            agent_id = r["agent_id"]
            await self._battle_repo.update_participant(
                battle.id,
                agent_id,
                final_equity=r["final_equity"],
                final_rank=rank,
                status="stopped",
                backtest_session_id=r.get("session_id"),
            )

        remove_engine(str(battle.id))

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
        result = await self._battle_repo.update_status(
            battle_id, "cancelled", ended_at=now
        )
        self._emit_notification(
            battle_id,
            NOTIFY_BATTLE_CANCELLED,
            {"battle_name": battle.name},
        )
        return result

    # ------------------------------------------------------------------
    # Historical battle operations
    # ------------------------------------------------------------------

    async def step_historical(self, battle_id: UUID) -> object:
        """Advance a historical battle by one step."""
        from src.battles.historical_engine import get_engine  # noqa: PLC0415

        engine = get_engine(str(battle_id))
        if engine is None:
            raise BattleInvalidStateError("Historical battle engine not found.")
        return await engine.step()

    async def step_historical_batch(self, battle_id: UUID, steps: int) -> object:
        """Advance a historical battle by N steps."""
        from src.battles.historical_engine import get_engine  # noqa: PLC0415

        engine = get_engine(str(battle_id))
        if engine is None:
            raise BattleInvalidStateError("Historical battle engine not found.")
        return await engine.step_batch(steps)

    async def place_historical_order(
        self,
        battle_id: UUID,
        agent_id: UUID,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> object:
        """Place an order in a historical battle for a specific agent."""
        from src.battles.historical_engine import get_engine  # noqa: PLC0415

        engine = get_engine(str(battle_id))
        if engine is None:
            raise BattleInvalidStateError("Historical battle engine not found.")
        return engine.place_order(
            agent_id=agent_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
        )

    async def get_historical_prices(
        self, battle_id: UUID
    ) -> tuple[dict[str, Decimal], datetime]:
        """Get current prices at virtual time for a historical battle."""
        from src.battles.historical_engine import get_engine  # noqa: PLC0415

        engine = get_engine(str(battle_id))
        if engine is None:
            raise BattleInvalidStateError("Historical battle engine not found.")
        virtual_time = engine.virtual_time
        if virtual_time is None:
            raise BattleInvalidStateError("Historical battle has not been initialized.")
        return engine.current_prices, virtual_time

    # ------------------------------------------------------------------
    # Battle replay
    # ------------------------------------------------------------------

    async def replay_battle(
        self,
        battle_id: UUID,
        account_id: UUID,
        *,
        override_config: dict[str, object] | None = None,
        override_agents: list[UUID] | None = None,
    ) -> Battle:
        """Create a new historical battle from a completed battle's config.

        For live battles: uses ``started_at`` / ``ended_at`` as the time range.
        For historical battles: reuses ``backtest_config``.
        Custom ``override_config`` fields are merged on top of the derived config.
        ``override_agents`` replaces the participant list if provided.

        Args:
            battle_id:       Source battle UUID.
            account_id:      Owner account UUID.
            override_config: Optional dict merged into the derived backtest config.
            override_agents: Optional list of agent UUIDs to use instead of original participants.

        Returns:
            A new :class:`Battle` in draft status with ``battle_mode="historical"``.

        Raises:
            BattleInvalidStateError: If the source battle is not completed.
            PermissionDeniedError:   If the caller does not own the source battle.
        """
        source = await self._battle_repo.get_battle(battle_id)
        if source.account_id != account_id:
            raise PermissionDeniedError("You do not own this battle.")
        if source.status != "completed":
            raise BattleInvalidStateError(
                "Can only replay completed battles.",
                current_status=source.status,
                required_status="completed",
            )

        # Derive backtest_config from source
        if getattr(source, "battle_mode", "live") == "historical" and source.backtest_config:
            replay_backtest_config: dict[str, object] = dict(source.backtest_config)
        else:
            # Live battle — derive time range from started_at / ended_at
            if not source.started_at or not source.ended_at:
                raise BattleInvalidStateError(
                    "Source battle has no start/end timestamps for replay."
                )
            replay_backtest_config = {
                "start_time": source.started_at.isoformat(),
                "end_time": source.ended_at.isoformat(),
                "candle_interval": 60,
            }

        # Merge overrides
        if override_config:
            replay_backtest_config.update(override_config)

        # Create new battle in draft
        new_battle = await self.create_battle(
            account_id=account_id,
            name=f"Replay: {source.name}",
            config=dict(source.config) if isinstance(source.config, dict) else {},
            ranking_metric=source.ranking_metric,
            battle_mode="historical",
            backtest_config=replay_backtest_config,
        )

        # Add participants from source or override
        if override_agents:
            agent_ids = override_agents
        else:
            participants = await self._battle_repo.get_participants(battle_id)
            agent_ids = [p.agent_id for p in participants]

        for aid in agent_ids:
            await self.add_participant(new_battle.id, aid, account_id)

        return await self._battle_repo.get_battle(new_battle.id)

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
