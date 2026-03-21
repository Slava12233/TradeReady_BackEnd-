---
task_id: 07
title: "Add memory protocol to all agent prompts"
type: task
agent: "context-manager"
phase: 1
depends_on: [2, 3, 4, 5, 6]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "high"
files:
  - ".claude/agents/api-sync-checker.md"
  - ".claude/agents/backend-developer.md"
  - ".claude/agents/codebase-researcher.md"
  - ".claude/agents/code-reviewer.md"
  - ".claude/agents/context-manager.md"
  - ".claude/agents/deploy-checker.md"
  - ".claude/agents/doc-updater.md"
  - ".claude/agents/e2e-tester.md"
  - ".claude/agents/frontend-developer.md"
  - ".claude/agents/migration-helper.md"
  - ".claude/agents/ml-engineer.md"
  - ".claude/agents/perf-checker.md"
  - ".claude/agents/planner.md"
  - ".claude/agents/security-auditor.md"
  - ".claude/agents/security-reviewer.md"
  - ".claude/agents/test-runner.md"
tags:
  - task
  - agent
  - memory
---

# Task 07: Add memory protocol to all agent prompts

## Assigned Agent: `context-manager`

## Objective
Add a "Memory Protocol" section to each agent's system prompt (the markdown body below the frontmatter) instructing agents to read their memory at startup and update it when they finish.

## Context
Phase 1 of Agent Memory Strategy. Memory files exist (Tasks 02-06) and frontmatter is enabled (Task 01), but agents need explicit instructions to use their memory effectively.

## What to Add
Add the following section to each agent's markdown body, ideally after the "Context Loading" section:

```markdown
## Memory Protocol

Before starting work:
1. Read your `MEMORY.md` for patterns, conventions, and learnings from previous runs
2. Apply relevant learnings to the current task

After completing work:
1. Note any new patterns, issues, or conventions discovered
2. Update your `MEMORY.md` with actionable learnings (not raw logs)
3. Keep memory under 100 lines — summarize and consolidate older entries
4. Remove entries that are no longer relevant
```

## Acceptance Criteria
- [ ] All 16 agent `.md` files contain a "Memory Protocol" section
- [ ] Section is placed consistently (after Context Loading, before Workflow)
- [ ] Instructions are clear and actionable
- [ ] No other agent content is modified

## Agent Instructions
Read each agent file, find the appropriate insertion point (after "Context Loading" or at the beginning if no such section exists), and add the Memory Protocol section. Adapt slightly for read-only agents (security-auditor, perf-checker, codebase-researcher) — they should read memory but note that they can still update memory with learnings even though they don't modify code.

## Estimated Complexity
Low — 16 identical section insertions with minor per-agent adaptation.
