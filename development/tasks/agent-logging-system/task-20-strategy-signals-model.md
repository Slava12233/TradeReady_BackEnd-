---
task_id: 20
title: "Create AgentStrategySignal database model"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["src/database/models.py"]
tags:
  - task
  - agent
  - logging
---

# Task 20: Create AgentStrategySignal Database Model

## Assigned Agent: `backend-developer`

## Objective
Add the `AgentStrategySignal` SQLAlchemy ORM model for persisting per-strategy signal data before ensemble combination.

## Files to Modify
- `src/database/models.py` — add `AgentStrategySignal` model

## Schema
```python
class AgentStrategySignal(Base):
    __tablename__ = "agent_strategy_signals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trace_id = Column(String(32), nullable=False, index=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    strategy_name = Column(String(50), nullable=False)  # 'rl_ppo', 'evolutionary', 'regime', 'risk', 'ensemble'
    symbol = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)   # 'buy', 'sell', 'hold'
    confidence = Column(Numeric(5, 4), nullable=True)
    weight = Column(Numeric(5, 4), nullable=True)  # weight in ensemble
    signal_data = Column(JSONB, nullable=True)     # strategy-specific details
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    agent = relationship("Agent", back_populates="strategy_signals")
```

## Indexes
- `ix_agent_signals_trace` on `(trace_id)`
- `ix_agent_signals_agent_created` on `(agent_id, created_at DESC)`

## Acceptance Criteria
- [ ] `AgentStrategySignal` model added to `src/database/models.py`
- [ ] FK to `agents` with CASCADE delete
- [ ] Back-populate relationship on `Agent` model
- [ ] JSONB column for strategy-specific signal data
- [ ] `NUMERIC(5,4)` for confidence and weight (matches `AgentDecision.confidence`)
- [ ] `ruff check src/database/models.py` passes

## Agent Instructions
- Place near the other `Agent*` models
- Follow `AgentDecision` pattern for confidence column type
- The `signal_data` JSONB column stores strategy-specific details (e.g., RL action weights, GA genome params, regime label)

## Estimated Complexity
Low — standard ORM model
