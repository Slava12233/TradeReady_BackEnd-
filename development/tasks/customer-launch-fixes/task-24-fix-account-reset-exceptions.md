---
task_id: 24
title: "Fix account reset silent exception swallow"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["src/accounts/service.py"]
tags:
  - task
  - backend
  - error-handling
  - P2
---

# Task 24: Fix account reset silent exception swallow

## Assigned Agent: `backend-developer`

## Objective
Account reset silently swallows ALL exceptions with a bare `except: pass`. This hides real errors and makes debugging impossible.

## Context
Code standards review (SR-04) flagged this as HIGH. Bare exception handlers mask bugs that could corrupt account state.

## Files to Modify
- `src/accounts/service.py` — Find the account reset function and add proper error handling

## Acceptance Criteria
- [ ] No bare `except: pass` in account reset code
- [ ] Specific exceptions are caught and logged with structlog
- [ ] Unexpected exceptions propagate (or are caught, logged, and re-raised)
- [ ] Account reset still works for the happy path
- [ ] Test: verify that a DB error during reset is logged and raised

## Agent Instructions
1. Search for `except:` or `except Exception:` followed by `pass` in `src/accounts/service.py`
2. Replace with specific exception handling (e.g., catch `SQLAlchemyError`, log it, re-raise or return error)
3. Use `structlog.get_logger()` for logging

## Estimated Complexity
Low — replace bare except with proper handler
