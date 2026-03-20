---
task_id: 22
title: "Permission system — budget enforcement"
agent: "backend-developer"
phase: 2
depends_on: [21]
status: "pending"
priority: "high"
files: ["agent/permissions/budget.py"]
---

# Task 22: Permission system — budget enforcement

## Assigned Agent: `backend-developer`

## Objective
Create the budget management system that enforces daily trade limits, exposure caps, and loss limits. This is the financial safety net.

## Files to Create
- `agent/permissions/budget.py` — `BudgetManager` class

## Key Design
```python
class BudgetManager:
    """Enforces financial limits on agent trading activity."""

    async def check_budget(self, agent_id: str, trade_value: Decimal) -> BudgetCheckResult:
        """
        Returns:
        - allowed: bool
        - reason: str (if denied)
        - remaining_trades: int
        - remaining_exposure: Decimal
        - remaining_loss_budget: Decimal
        """

    async def record_trade(self, agent_id: str, trade_value: Decimal) -> None:
        """Record a trade against the daily budget."""

    async def record_loss(self, agent_id: str, loss_amount: Decimal) -> None:
        """Record a loss against the daily budget."""

    async def get_budget_status(self, agent_id: str) -> BudgetStatus:
        """Current budget utilization."""

    async def reset_daily(self, agent_id: str) -> None:
        """Reset daily counters (called by Celery beat task)."""
```

## Acceptance Criteria
- [ ] `check_budget()` validates against all 4 limits (trades, exposure, loss, position size)
- [ ] Budget counters use Redis for fast atomic increments (persisted to DB periodically)
- [ ] `record_trade()` and `record_loss()` are atomic (no race conditions)
- [ ] Budget denial returns a clear reason
- [ ] `BudgetStatus` model shows current utilization as percentages
- [ ] Integration with existing risk manager in `src/risk/`

## Dependencies
- Task 21 (capabilities for permission checking)

## Agent Instructions
1. Read `src/risk/CLAUDE.md` for existing risk management patterns
2. Use Redis `INCR` for atomic counter updates
3. Persist to DB every 5 minutes (not every trade) to reduce DB load
4. Budget check must be fast (<5ms) — always read from Redis
5. Output model `BudgetCheckResult` should be clear about why a trade was denied

## Estimated Complexity
Medium — atomic counters with Redis + periodic DB persistence.
