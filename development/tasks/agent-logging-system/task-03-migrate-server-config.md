---
task_id: 03
title: "Migrate server.py structlog config"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/server.py"]
tags:
  - task
  - agent
  - logging
---

# Task 03: Migrate server.py Structlog Config

## Assigned Agent: `backend-developer`

## Objective
Replace inline structlog configuration in `agent/server.py` with `configure_agent_logging()`. Additionally, bind the `agent_id` context so all log lines from this server instance include the agent identifier.

## Files to Modify
- `agent/server.py` — replace structlog config, add `set_agent_id()` call in `__init__`

## Implementation Details
1. Replace inline `structlog.configure(...)` with `configure_agent_logging()`
2. In `AgentServer.__init__()` (or `start()`), call `set_agent_id(str(agent_id))` to bind the agent context
3. Remove now-unused structlog imports

## Acceptance Criteria
- [ ] No inline `structlog.configure()` in `agent/server.py`
- [ ] Every log line from AgentServer includes `agent_id` field
- [ ] `python -m agent chat` still works (server mode)
- [ ] `ruff check agent/server.py` passes

## Agent Instructions
- Read `agent/server.py` fully first
- The `set_agent_id()` call should happen as early as possible — in `__init__` or at the start of `start()`
- Verify that `agent_id` is available at the point where you call `set_agent_id()`

## Estimated Complexity
Low — import swap + one additional call
