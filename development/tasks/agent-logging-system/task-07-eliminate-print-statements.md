---
task_id: 07
title: "Eliminate unnecessary print() statements"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "low"
files: ["agent/**/*.py"]
tags:
  - task
  - agent
  - logging
---

# Task 07: Eliminate Unnecessary print() Statements

## Assigned Agent: `backend-developer`

## Objective
Audit all `print()` calls in `agent/` (30 files) and replace CLI progress output with structured logging. Keep pre-logger stderr writes and Rich terminal UI output.

## Rules for Each Category

| Category | Action |
|----------|--------|
| Config load failures (before structlog configured) | **Keep** as `sys.stderr` writes |
| CLI progress output (`print(f"Step {n}: ...")`) | **Replace** with `logger.info("agent.workflow.step", step=n, ...)` |
| Rich terminal UI fallback (`TerminalUI` in `cli.py`) | **Keep** — user-facing display, not logging |
| Strategy CLI progress | **Replace** with `logger.info(...)` |

## Implementation Details
1. Grep for `print(` across `agent/` (excluding `agent/tests/`)
2. Classify each occurrence using the table above
3. Replace CLI progress prints with structlog calls
4. Add `# noqa: T201` comment to any intentionally kept `print()` calls that don't already have it

## Acceptance Criteria
- [ ] All replaceable `print()` calls converted to structlog
- [ ] Remaining `print()` calls have `# noqa: T201` annotation
- [ ] No user-facing terminal output is broken
- [ ] `ruff check agent/` passes (T201 rule)

## Agent Instructions
- Run `grep -rn "print(" agent/ --include="*.py" | grep -v test` to find all occurrences
- Be careful with `cli.py` — the `TerminalUI` class uses `print()` intentionally for terminal rendering
- Strategy CLIs (`agent/strategies/*/`) often have progress bars with `print()` — convert these

## Estimated Complexity
Low — bulk search and classify, then replace or annotate
