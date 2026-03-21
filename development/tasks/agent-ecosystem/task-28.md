---
task_id: 28
title: "Trading journal system"
type: task
agent: "backend-developer"
phase: 2
depends_on: [26, 27]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "medium"
files: ["agent/trading/journal.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 28: Trading journal system

## Assigned Agent: `backend-developer`

## Objective
Create the trading journal that records every decision with full context: market snapshot, strategy signals, risk assessment, reasoning, and post-trade reflection.

## Files to Create
- `agent/trading/journal.py` — `TradingJournal` class

## Key Design
```python
class TradingJournal:
    """Records and analyzes all trading decisions."""

    async def record_decision(
        self,
        agent_id: str,
        decision: TradeDecision,
        market_snapshot: dict,
        signals: list[TradingSignal],
        risk_assessment: dict,
        reasoning: str,
    ) -> str:
        """Record a trade decision with full context. Returns decision_id."""

    async def record_outcome(
        self,
        decision_id: str,
        pnl: Decimal,
        hold_duration: timedelta,
        max_adverse_excursion: Decimal,
    ) -> None:
        """Record the outcome of a trade decision."""

    async def generate_reflection(self, decision_id: str) -> JournalEntry:
        """
        LLM-powered post-trade reflection:
        - What went right/wrong?
        - Was the entry timing good?
        - Was the exit optimal?
        - What would I do differently?
        Saves as journal entry + extracts learnings.
        """

    async def get_entries(self, agent_id: str, entry_type: str | None = None, limit: int = 20) -> list[JournalEntry]: ...
    async def daily_summary(self, agent_id: str) -> JournalEntry: ...
    async def weekly_review(self, agent_id: str) -> JournalEntry: ...
```

## Acceptance Criteria
- [ ] Every decision recorded with full market context
- [ ] Outcomes linked back to decisions via `decision_id`
- [ ] Post-trade reflection uses LLM to generate insights
- [ ] Learnings extracted from reflections and saved to memory system
- [ ] Daily summary aggregates all decisions for the day
- [ ] Weekly review identifies patterns, best/worst trades, strategy performance
- [ ] Data stored in `agent_decisions` and `agent_journal` tables

## Dependencies
- Task 26 (trading loop provides decisions), Task 27 (execution provides outcomes)

## Agent Instructions
1. Use `agent_decision_repo` and `agent_journal_repo` for persistence
2. Use the existing Pydantic AI agent for LLM-powered reflection
3. Market snapshot should include: top 10 positions, key indicator values, current regime
4. For weekly review: query last 7 days of decisions, calculate win rate, avg P&L
5. Extract learnings: if reflection mentions a pattern, save to `agent_learnings`

## Estimated Complexity
Medium — structured journaling with LLM-powered reflection.
