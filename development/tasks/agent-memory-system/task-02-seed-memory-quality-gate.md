---
task_id: 02
title: "Create & seed MEMORY.md for quality gate agents"
type: task
agent: "context-manager"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "high"
files:
  - ".claude/agent-memory/code-reviewer/MEMORY.md"
  - ".claude/agent-memory/test-runner/MEMORY.md"
  - ".claude/agent-memory/context-manager/MEMORY.md"
tags:
  - task
  - agent
  - memory
---

# Task 02: Create & seed MEMORY.md for quality gate agents

## Assigned Agent: `context-manager`

## Objective
Create seeded MEMORY.md files for the 3 quality gate agents: `code-reviewer`, `test-runner`, `context-manager`. Each file should contain domain-specific patterns learned from the project's history.

## Context
Phase 1 of Agent Memory Strategy. These agents run after every code change and will benefit most from accumulated knowledge. Seed content should come from existing code review reports in `development/code-reviews/` and project conventions in CLAUDE.md files.

## Files to Create
- `.claude/agent-memory/code-reviewer/MEMORY.md` — seed with:
  - Common issues found in past reviews (validation gaps, N+1 queries, async errors)
  - Security patterns from `development/code-reviews/security-review-permissions.md`
  - Project conventions (Decimal for money, TradingPlatformError hierarchy, dependency direction)
  - Known false positive patterns to avoid

- `.claude/agent-memory/test-runner/MEMORY.md` — seed with:
  - Test patterns: asyncio_mode="auto", app factory, get_settings lru_cache gotcha
  - Fixture inventory highlights (from `tests/CLAUDE.md`)
  - Common test failures and their fixes
  - Coverage gaps found in past runs

- `.claude/agent-memory/context-manager/MEMORY.md` — seed with:
  - CLAUDE.md file inventory (66 files)
  - Update patterns (what sections change most frequently)
  - Naming conventions for milestones in context.md

## Acceptance Criteria
- [ ] 3 MEMORY.md files created in `.claude/agent-memory/<name>/`
- [ ] Each file is <100 lines (leave room for agent to add learnings)
- [ ] Content is factual and derived from actual project state
- [ ] Files use standard markdown (no frontmatter needed for memory files)

## Agent Instructions
Read `development/code-reviews/` reports and relevant CLAUDE.md files to extract real patterns. Do NOT invent issues — only document patterns that actually exist in the codebase. Format as categorized bullet lists.

## Estimated Complexity
Medium — requires reading existing reports and extracting patterns.
