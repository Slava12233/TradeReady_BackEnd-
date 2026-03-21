---
task_id: 19
title: "Create AgentApiCall database model"
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

# Task 19: Create AgentApiCall Database Model

## Assigned Agent: `backend-developer`

## Objective
Add the `AgentApiCall` SQLAlchemy ORM model to `src/database/models.py` for persisting agent API call logs.

## Files to Modify
- `src/database/models.py` — add `AgentApiCall` model

## Schema
```python
class AgentApiCall(Base):
    __tablename__ = "agent_api_calls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trace_id = Column(String(32), nullable=False, index=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(10), nullable=False)   # 'sdk', 'mcp', 'rest', 'db'
    endpoint = Column(String(200), nullable=False)
    method = Column(String(10), nullable=True)     # 'GET', 'POST', etc.
    status_code = Column(SmallInteger, nullable=True)
    latency_ms = Column(Numeric(10, 2), nullable=True)
    request_size = Column(Integer, nullable=True)
    response_size = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    agent = relationship("Agent", back_populates="api_calls")
```

Also add `trace_id = Column(String(32), nullable=True)` to the existing `AgentDecision` model.

## Indexes
- `ix_agent_api_calls_agent_trace` on `(agent_id, trace_id)`
- `ix_agent_api_calls_created` on `(created_at DESC)`

## Acceptance Criteria
- [ ] `AgentApiCall` model added to `src/database/models.py`
- [ ] `trace_id` column added to `AgentDecision` model
- [ ] Proper FK relationship to `agents` table with CASCADE delete
- [ ] Back-populate relationship added to `Agent` model
- [ ] `ruff check src/database/models.py` passes
- [ ] NOT a TimescaleDB hypertable (regular table with indexes)

## Agent Instructions
- Read `src/database/models.py` and `src/database/CLAUDE.md` first
- Place the model near the other `Agent*` models (around line 2600+)
- Follow the same patterns as `AgentDecision`, `AgentJournal`, etc.
- Use `NUMERIC(10,2)` for `latency_ms` (matches platform conventions for precision)

## Estimated Complexity
Low — standard ORM model following existing patterns
