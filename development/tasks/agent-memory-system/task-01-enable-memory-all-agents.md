---
task_id: 01
title: "Enable memory: project on all 16 agents"
type: task
agent: "context-manager"
phase: 1
depends_on: []
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "high"
files:
  - ".claude/agents/api-sync-checker.md"
  - ".claude/agents/backend-developer.md"
  - ".claude/agents/deploy-checker.md"
  - ".claude/agents/doc-updater.md"
  - ".claude/agents/e2e-tester.md"
  - ".claude/agents/frontend-developer.md"
  - ".claude/agents/migration-helper.md"
  - ".claude/agents/ml-engineer.md"
  - ".claude/agents/perf-checker.md"
  - ".claude/agents/security-auditor.md"
  - ".claude/agents/test-runner.md"
  - ".claude/agents/codebase-researcher.md"
tags:
  - task
  - agent
  - memory
---

# Task 01: Enable memory: project on all 16 agents

## Assigned Agent: `context-manager`

## Objective
Add `memory: project` to the YAML frontmatter of all 12 agents that currently lack it. 4 agents already have it: `code-reviewer`, `context-manager`, `planner`, `security-reviewer`.

## Context
Phase 1 of the Agent Memory Strategy. Currently only 4/16 agents have persistent memory enabled. All agents should share project-level learning via git-committed memory files.

## Files to Modify
- `.claude/agents/api-sync-checker.md` — add `memory: project` to frontmatter
- `.claude/agents/backend-developer.md` — add `memory: project` to frontmatter
- `.claude/agents/codebase-researcher.md` — add `memory: project` to frontmatter
- `.claude/agents/deploy-checker.md` — add `memory: project` to frontmatter
- `.claude/agents/doc-updater.md` — add `memory: project` to frontmatter
- `.claude/agents/e2e-tester.md` — add `memory: project` to frontmatter
- `.claude/agents/frontend-developer.md` — add `memory: project` to frontmatter
- `.claude/agents/migration-helper.md` — add `memory: project` to frontmatter
- `.claude/agents/ml-engineer.md` — add `memory: project` to frontmatter
- `.claude/agents/perf-checker.md` — add `memory: project` to frontmatter
- `.claude/agents/security-auditor.md` — add `memory: project` to frontmatter
- `.claude/agents/test-runner.md` — add `memory: project` to frontmatter

## Acceptance Criteria
- [ ] All 16 agent `.md` files have `memory: project` in their YAML frontmatter
- [ ] No other frontmatter fields are changed
- [ ] Agent descriptions and prompts remain unchanged

## Agent Instructions
For each file, add `memory: project` after the `model:` line in the YAML frontmatter block (between `---` delimiters). Example:
```yaml
---
name: backend-developer
description: "..."
tools: Read, Write, Edit, Grep, Glob, Bash
model: sonnet
memory: project
---
```

Do NOT modify any content below the frontmatter.

## Estimated Complexity
Low — 12 identical single-line additions to YAML frontmatter.
