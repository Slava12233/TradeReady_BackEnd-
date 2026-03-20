---
task_id: 27
title: "Trading loop — execution engine and position monitor"
agent: "backend-developer"
phase: 2
depends_on: [26]
status: "pending"
priority: "high"
files: ["agent/trading/execution.py", "agent/trading/monitor.py"]
---

# Task 27: Trading loop — execution engine and position monitor

## Assigned Agent: `backend-developer`

## Objective
Create the trade execution wrapper (pre/post logging around SDK calls) and the position monitor (watches open positions, manages exits, triggers stop-losses).

## Files to Create
- `agent/trading/execution.py` — `TradeExecutor` class
- `agent/trading/monitor.py` — `PositionMonitor` class

## Key Design

### execution.py
```python
class TradeExecutor:
    """Execute trades through SDK with pre/post logging."""

    async def execute(self, decision: TradeDecision) -> ExecutionResult:
        """
        1. Log pre-trade state (portfolio, prices)
        2. Submit order via SDK
        3. Wait for fill confirmation
        4. Log post-trade state
        5. Record to agent_decisions with order_id
        6. Update budget counters
        7. Return result
        """

    async def execute_batch(self, decisions: list[TradeDecision]) -> list[ExecutionResult]: ...
```

### monitor.py
```python
class PositionMonitor:
    """Monitors open positions and manages exits."""

    async def check_positions(self, agent_id: str) -> list[PositionAction]:
        """
        For each open position:
        1. Check current P&L
        2. Check against stop-loss / take-profit levels
        3. Check max holding duration
        4. Recommend: hold, partial exit, full exit
        """

    async def execute_exits(self, actions: list[PositionAction]) -> list[ExecutionResult]:
        """Execute recommended exits through TradeExecutor."""
```

## Acceptance Criteria
- [ ] Execution logs pre/post state for every trade
- [ ] Execution updates budget counters after each trade
- [ ] Execution handles SDK failures gracefully (retry once, then abort)
- [ ] Monitor checks stop-loss/take-profit levels
- [ ] Monitor respects permission system for exit actions
- [ ] All executions recorded in `agent_decisions` with `order_id`
- [ ] Batch execution runs sequentially (not parallel) for safety

## Dependencies
- Task 26 (trading loop and signal generator)

## Agent Instructions
1. Read `agent/tools/sdk_tools.py` for SDK trading patterns
2. Read `src/order_engine/CLAUDE.md` for order execution details
3. Execution must be idempotent — if interrupted, no duplicate orders
4. Use the SDK's order placement, not direct REST calls
5. Position monitor should run after every trading loop tick

## Estimated Complexity
High — trade execution requires careful error handling and idempotency.
