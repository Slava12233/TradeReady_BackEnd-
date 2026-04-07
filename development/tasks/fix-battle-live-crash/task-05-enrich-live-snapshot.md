---
task_id: 5
title: "Enrich get_live_snapshot() with all participant fields"
type: task
agent: "backend-developer"
phase: 2
depends_on: [3]
status: "pending"
priority: "high"
board: "[[fix-battle-live-crash/README]]"
files:
  - "src/battles/service.py"
tags:
  - task
  - battles
  - backend
  - service
---

# Task 05: Enrich get_live_snapshot() with all participant fields

## Assigned Agent: `backend-developer`

## Objective
Expand `get_live_snapshot()` in `src/battles/service.py` to return all fields the frontend expects, matching the new `BattleLiveParticipantSchema`.

## Context
Currently `get_live_snapshot()` (lines 704-728) returns only 6 fields per participant: `agent_id`, `display_name`, `equity`, `pnl`, `pnl_pct`, `status`. The frontend expects 13 fields. Field names also differ (`equity` vs `current_equity`).

## Files to Modify
- `src/battles/service.py` — Expand the participant dict in `get_live_snapshot()` (lines 704-728)

## Specific Changes

Update the participant dict to include all fields:

```python
async def get_live_snapshot(self, battle_id: UUID) -> list[dict[str, object]]:
    """Get live metrics for all participants in an active battle."""
    battle = await self._battle_repo.get_battle(battle_id)
    participants = await self._battle_repo.get_participants(battle_id)

    results: list[dict[str, object]] = []
    
    # Compute live rankings by equity (descending)
    equity_map: dict[UUID, Decimal] = {}
    for participant in participants:
        agent = await self._agent_repo.get_by_id(participant.agent_id)
        equity = await self._wallet_manager.get_agent_equity(participant.agent_id)
        equity_map[participant.agent_id] = equity

    # Sort by equity descending for ranking
    sorted_agents = sorted(equity_map.items(), key=lambda x: x[1], reverse=True)
    rank_map = {agent_id: i + 1 for i, (agent_id, _) in enumerate(sorted_agents)}

    for participant in participants:
        agent = await self._agent_repo.get_by_id(participant.agent_id)
        equity = equity_map[participant.agent_id]
        start = participant.snapshot_balance or Decimal(str(agent.starting_balance))
        pnl = equity - start
        pnl_pct = (pnl / start * 100) if start > 0 else Decimal("0")

        # Get trade count for this agent during the battle period
        total_trades = 0
        win_rate = None
        try:
            # Use trade repo to count trades since battle start
            trades = await self._trade_repo.get_agent_trades(
                participant.agent_id,
                since=battle.started_at,
            )
            total_trades = len(trades)
            if total_trades > 0:
                wins = sum(1 for t in trades if t.realized_pnl and t.realized_pnl > 0)
                win_rate = str(round(Decimal(wins) / Decimal(total_trades) * 100, 1))
        except Exception:
            pass  # Trade data unavailable — leave defaults

        results.append(
            {
                "agent_id": str(participant.agent_id),
                "display_name": agent.display_name,
                "avatar_url": getattr(agent, "avatar_url", None),
                "color": getattr(participant, "color", None),
                "current_equity": str(equity),
                "roi_pct": str(round(pnl_pct, 2)),
                "total_pnl": str(pnl),
                "total_trades": total_trades,
                "win_rate": win_rate,
                "sharpe_ratio": None,  # Only computed on battle completion
                "max_drawdown_pct": None,  # Only computed on battle completion
                "rank": rank_map.get(participant.agent_id),
                "status": participant.status,
            }
        )

    return results
```

**Important notes:**
- Keep backward-compatible field names (`equity`/`pnl`/`pnl_pct` can be removed since the schema now enforces `current_equity`/`total_pnl`/`roi_pct`)
- `sharpe_ratio` and `max_drawdown_pct` remain `None` during live battles — they require full trade history analysis that only happens at battle completion
- `win_rate` CAN be computed live if trades exist
- `rank` is computed live by sorting participants by equity descending
- `avatar_url` comes from the agent model
- `color` comes from the participant model (if the field exists) or defaults to `None`

## Acceptance Criteria
- [ ] `get_live_snapshot()` returns all 13 fields per participant matching `BattleLiveParticipantSchema`
- [ ] Field names match frontend expectations: `current_equity`, `roi_pct`, `total_pnl`
- [ ] `rank` is computed live (1 = highest equity)
- [ ] `total_trades` reflects actual trade count during battle
- [ ] `win_rate` is computed from trades if any exist, `None` otherwise
- [ ] `sharpe_ratio` and `max_drawdown_pct` are `None` (computed only on completion)
- [ ] No exceptions thrown if trade repo or agent fields are unavailable
- [ ] `ruff check src/battles/service.py` passes
- [ ] `mypy src/battles/service.py` passes

## Dependencies
Task 03 must complete first — need the schema to validate field names.

## Agent Instructions
Read `src/battles/CLAUDE.md` first. Check what repositories are available on `self` — you'll need `self._trade_repo` or similar. Check the Agent model for `avatar_url` field. Check the BattleParticipant model for a `color` field. If `get_agent_trades` doesn't exist with a `since` parameter, use whatever trade query method is available, or add a simple count query. Use `getattr()` with defaults for fields that might not exist on the model. Wrap trade queries in try/except to be resilient.

**Performance note:** This method is called every 5 seconds by the frontend. Avoid expensive queries. If trade counting is too slow, consider caching or simplifying.

## Estimated Complexity
Medium — requires integrating with trade repo and computing live metrics
