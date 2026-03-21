---
task_id: 08
title: "Update .gitignore for agent memory directories"
type: task
agent: "context-manager"
phase: 1
depends_on: []
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "low"
files:
  - ".gitignore"
tags:
  - task
  - agent
  - memory
---

# Task 08: Update .gitignore for agent memory directories

## Assigned Agent: `context-manager`

## Objective
Add `.claude/agent-memory-local/` to the project `.gitignore` so local-only agent memory is never committed.

## Context
Phase 1 of Agent Memory Strategy. `memory: project` stores in `.claude/agent-memory/` (committed to git). `memory: local` stores in `.claude/agent-memory-local/` (should NOT be committed).

## Files to Modify
- `.gitignore` — add entry:
  ```
  # Agent local memory (not shared)
  .claude/agent-memory-local/
  ```

## Acceptance Criteria
- [ ] `.gitignore` contains `.claude/agent-memory-local/` entry
- [ ] Entry has a descriptive comment
- [ ] No other `.gitignore` entries are modified

## Estimated Complexity
Low — single line addition.
