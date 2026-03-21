---
task_id: 19
title: "Agent config extensions for ecosystem"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "medium"
files: ["agent/config.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 19: Agent config extensions for ecosystem

## Assigned Agent: `backend-developer`

## Objective
Extend `agent/config.py` with configuration fields for the memory system, conversation system, server settings, and permission defaults.

## Files to Modify
- `agent/config.py` — add new config sections

## New Config Fields
```python
# Memory settings
MEMORY_SEARCH_LIMIT: int = 10
MEMORY_CACHE_TTL: int = 3600  # seconds
MEMORY_CLEANUP_CONFIDENCE_THRESHOLD: float = 0.2
MEMORY_CLEANUP_AGE_DAYS: int = 90

# Conversation settings
CONTEXT_MAX_TOKENS: int = 8000
CONTEXT_RECENT_MESSAGES: int = 20
CONTEXT_SUMMARY_THRESHOLD: int = 50  # summarize after N messages

# Server settings
AGENT_SERVER_HOST: str = "0.0.0.0"
AGENT_SERVER_PORT: int = 8001
AGENT_HEALTH_CHECK_INTERVAL: int = 60  # seconds
AGENT_SCHEDULED_REVIEW_HOUR: int = 8  # UTC hour for morning review

# Permission defaults
DEFAULT_AGENT_ROLE: str = "paper_trader"
DEFAULT_MAX_TRADES_PER_DAY: int = 50
DEFAULT_MAX_EXPOSURE_PCT: float = 25.0
DEFAULT_MAX_DAILY_LOSS_PCT: float = 5.0

# Trading loop settings
TRADING_LOOP_INTERVAL: int = 3600  # seconds (1 hour)
TRADING_MIN_CONFIDENCE: float = 0.6
```

## Acceptance Criteria
- [ ] All new fields added with sensible defaults
- [ ] Environment variable overrides work (via `.env`)
- [ ] Fields have type annotations and docstrings
- [ ] No breaking changes to existing config usage
- [ ] Config fields follow existing naming conventions

## Dependencies
- Task 01 (need to know what entities need configuration)

## Agent Instructions
1. Read `agent/config.py` for current config structure
2. Add new fields to existing config class (do not create a separate class)
3. Group fields with comments for clarity
4. All new env vars should have `AGENT_` prefix for namespace isolation

## Estimated Complexity
Low — straightforward config additions.
