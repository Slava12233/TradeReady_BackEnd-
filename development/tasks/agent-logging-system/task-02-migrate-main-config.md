---
task_id: 02
title: "Migrate main.py structlog config"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/main.py"]
tags:
  - task
  - agent
  - logging
---

# Task 02: Migrate main.py Structlog Config

## Assigned Agent: `backend-developer`

## Objective
Replace the inline `structlog.configure(...)` block in `agent/main.py` (lines 63-77) with a single call to `configure_agent_logging()` from the new centralized module.

## Files to Modify
- `agent/main.py` — replace inline structlog config with `from agent.logging import configure_agent_logging`

## Implementation Details
1. Remove the entire `structlog.configure(...)` block
2. Replace with: `from agent.logging import configure_agent_logging` + `configure_agent_logging(log_level)`
3. Remove any now-unused structlog imports at the top of the file
4. Verify the `log_level` variable is still passed correctly (it comes from CLI args)

## Acceptance Criteria
- [ ] No inline `structlog.configure()` call remains in `agent/main.py`
- [ ] `python -m agent.main smoke` still produces JSON log output
- [ ] Log level CLI arg still works (`--log-level DEBUG`)
- [ ] `ruff check agent/main.py` passes

## Agent Instructions
- Read `agent/main.py` fully before making changes
- The `log_level` variable is parsed from CLI arguments — make sure the import and call happen after arg parsing
- Do NOT remove `structlog.get_logger()` calls elsewhere in the file — only the `configure()` block

## Estimated Complexity
Low — simple import swap
