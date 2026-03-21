---
task_id: 26
title: "Trading loop — main loop and signal generator"
type: task
agent: "backend-developer"
phase: 2
depends_on: [13, 23]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "high"
files: ["agent/trading/__init__.py", "agent/trading/loop.py", "agent/trading/signal_generator.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 26: Trading loop — main loop and signal generator

## Assigned Agent: `backend-developer`

## Objective
Create the main trading loop and signal generator. The loop runs at configurable intervals, observing the market, generating signals from all 5 strategies, checking permissions, and deciding on actions.

## Files to Create
- `agent/trading/__init__.py` — export public classes
- `agent/trading/loop.py` — `TradingLoop` class
- `agent/trading/signal_generator.py` — `SignalGenerator` class

## Key Design

### loop.py
```python
class TradingLoop:
    """Main trading loop: observe → analyze → decide → check → execute → record → learn."""

    def __init__(self, agent_id: str, config: AgentConfig, enforcer: PermissionEnforcer): ...

    async def start(self) -> None:
        """Start the trading loop at configured interval."""

    async def stop(self) -> None:
        """Stop the loop gracefully."""

    async def tick(self) -> TradingCycleResult:
        """Execute one cycle of the trading loop."""
        # 1. Observe: fetch prices, indicators, positions
        # 2. Analyze: run signal generator
        # 3. Decide: LLM reasoning on signals → action
        # 4. Check: permission enforcement
        # 5. Execute: place orders via SDK
        # 6. Record: save decision to agent_decisions
        # 7. Learn: extract insights for memory
```

### signal_generator.py
```python
class SignalGenerator:
    """Combines all 5 strategies into actionable signals."""

    async def generate(self, symbols: list[str]) -> list[TradingSignal]:
        """
        For each symbol:
        1. Run all 5 strategies (RL, evolutionary, regime, risk overlay, ensemble)
        2. Aggregate into a single signal with confidence
        3. Apply risk overlay as final filter
        """
```

## Acceptance Criteria
- [ ] Loop runs at configurable interval (1h, 4h, 1d)
- [ ] Signal generator integrates with all 5 strategies in `agent/strategies/`
- [ ] Permission check happens BEFORE trade execution
- [ ] Budget check happens BEFORE trade execution
- [ ] Every decision (trade or hold) is recorded to `agent_decisions`
- [ ] Market observations saved to `agent_observations` hypertable
- [ ] Loop handles errors gracefully (one failed symbol doesn't stop others)
- [ ] Configurable via `agent/config.py` settings

## Dependencies
- Task 13 (agent server), Task 23 (permission enforcement)

## Agent Instructions
1. Read `agent/strategies/CLAUDE.md` for strategy integration patterns
2. Read `agent/strategies/ensemble/` for the existing ensemble combiner
3. The signal generator should use the existing ensemble runner — do not duplicate logic
4. Permission check: `enforcer.require_action(agent_id, "trade", {"symbol": ..., "value": ...})`
5. Use `asyncio.sleep()` for loop timing, with `asyncio.Event` for shutdown

## Estimated Complexity
High — central trading orchestrator integrating strategies, permissions, and persistence.
