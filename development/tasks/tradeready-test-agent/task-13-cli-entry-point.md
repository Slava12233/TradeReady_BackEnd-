---
task_id: 13
title: "CLI entry point (main.py)"
type: task
agent: "backend-developer"
phase: 6
depends_on: [9, 10, 11, 12]
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "high"
files:
  - "agent/main.py"
tags:
  - task
  - testing-agent
---

# Task 13: CLI entry point (main.py)

## Assigned Agent: `backend-developer`

## Objective
Implement the CLI entry point that ties everything together — workflow selection, model override, structured logging setup, and report output.

## Files to Create
- `agent/main.py` — entry point with:
  - `argparse` CLI with workflow selection: `smoke`, `trade`, `backtest`, `strategy`, `all`
  - `--model` flag for runtime model override
  - structlog configuration (JSON output, timestamps)
  - Workflow dispatch map
  - Report saving to `agent/reports/` as JSON
  - Error handling for missing config, platform unreachable, etc.

## Acceptance Criteria
- [ ] CLI works: `python -m agent.main smoke`
- [ ] All 5 workflow options available (smoke, trade, backtest, strategy, all)
- [ ] `--model` override works for switching models
- [ ] structlog configured with JSON output
- [ ] Reports saved as timestamped JSON in `agent/reports/`
- [ ] Graceful error handling for missing `.env`, platform down, bad API key
- [ ] Exit code 0 on success, 1 on failure

## Dependencies
- Tasks 9-12 (all workflow modules must exist)

## Agent Instructions
- Follow the pattern in plan Section 6 for the CLI structure
- Use `asyncio.run(main(...))` as the entry point
- Configure structlog before any workflow runs
- Save reports as `agent/reports/{workflow}-{timestamp}.json`
- The `all` workflow runs smoke → trade → backtest → strategy in sequence

## Estimated Complexity
Medium — glue code tying together all modules
