---
task_id: 04
title: "Migrate strategy CLI structlog configs"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "medium"
files: ["agent/strategies/rl/config.py", "agent/strategies/evolutionary/config.py", "agent/strategies/ensemble/config.py"]
tags:
  - task
  - agent
  - logging
---

# Task 04: Migrate Strategy CLI Structlog Configs

## Assigned Agent: `backend-developer`

## Objective
Replace duplicate `structlog.configure()` calls in the 3 strategy CLI entry points with `configure_agent_logging()`.

## Files to Modify
- `agent/strategies/rl/config.py` (or wherever `main()` calls structlog.configure)
- `agent/strategies/evolutionary/config.py`
- `agent/strategies/ensemble/config.py`

## Implementation Details
1. Search each file for `structlog.configure(` calls
2. Replace with `from agent.logging import configure_agent_logging; configure_agent_logging()`
3. Remove unused structlog imports
4. If the strategy CLI has a log level option, pass it through

## Acceptance Criteria
- [ ] No inline `structlog.configure()` in any strategy config file
- [ ] Each strategy CLI still produces JSON log output when run standalone
- [ ] `ruff check` passes on all modified files

## Agent Instructions
- Grep for `structlog.configure` across `agent/strategies/` to find all locations
- Some files may have the config inside a `main()` or `if __name__ == "__main__"` block — keep the call location but replace the content
- These are standalone CLIs (run as `python -m agent.strategies.rl.train`) — they need their own `configure_agent_logging()` call

## Estimated Complexity
Low — 3 files, same pattern each
