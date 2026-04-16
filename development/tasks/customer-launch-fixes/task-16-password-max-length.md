---
task_id: 16
title: "Add password max_length validation"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/api/schemas/auth.py"]
tags:
  - task
  - security
  - validation
  - P1
---

# Task 16: Add password max_length validation

## Assigned Agent: `backend-developer`

## Objective
Password fields lack `max_length`. bcrypt silently truncates passwords at 72 bytes, meaning a 100-character password and the same password truncated to 72 characters would both work. Add explicit max_length validation.

## Context
Security audit (SR-06) flagged this as MEDIUM. Silent truncation is a security edge case — users may believe their full password is being used when it's actually truncated.

## Files to Modify
- `src/api/schemas/auth.py` — Add `max_length=72` to password fields in registration and login schemas

## Acceptance Criteria
- [ ] Password field has `max_length=72` in Pydantic schema
- [ ] Passwords longer than 72 characters return a clear validation error
- [ ] Error message explains the 72-byte limit
- [ ] Existing passwords still work (no migration needed)
- [ ] Test: 73-character password returns 422

## Agent Instructions
1. Read `src/api/schemas/CLAUDE.md` for schema patterns
2. Add `Field(max_length=72)` to password fields
3. Consider also adding `min_length=8` if not already present

## Estimated Complexity
Low — single field constraint addition
