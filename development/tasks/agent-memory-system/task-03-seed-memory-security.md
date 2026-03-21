---
task_id: 03
title: "Create & seed MEMORY.md for security agents"
type: task
agent: "context-manager"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-memory-system/README]]"
priority: "high"
files:
  - ".claude/agent-memory/security-reviewer/MEMORY.md"
  - ".claude/agent-memory/security-auditor/MEMORY.md"
tags:
  - task
  - agent
  - memory
---

# Task 03: Create & seed MEMORY.md for security agents

## Assigned Agent: `context-manager`

## Objective
Create seeded MEMORY.md files for security agents: `security-reviewer` and `security-auditor`.

## Context
Phase 1 of Agent Memory Strategy. Security agents need historical knowledge of vulnerabilities found, fixes applied, and project-specific security patterns. `security-reviewer` already has `memory: project` in frontmatter.

## Files to Create
- `.claude/agent-memory/security-reviewer/MEMORY.md` — seed with:
  - 4 CRITICAL fixes from `development/code-reviews/security-review-permissions.md` (float precision, TOCTOU race, fail-open, default role)
  - 3 HIGH deferred issues from agent strategies security review
  - Project auth patterns (API key `ak_live_` prefix, JWT auth, agent scoping)
  - Known sensitive areas (agent/permissions/, src/accounts/, src/api/middleware/)

- `.claude/agent-memory/security-auditor/MEMORY.md` — seed with:
  - Areas previously audited and their status
  - OWASP patterns relevant to this project (injection via SQLAlchemy OK, XSS via React OK)
  - Auth flow summary (API key → agents table → fallback accounts table)
  - Rate limiting patterns (Redis INCR + EXPIRE)

## Acceptance Criteria
- [ ] 2 MEMORY.md files created
- [ ] Content references actual security findings from code review reports
- [ ] Known vulnerabilities and their fix status are documented
- [ ] Each file <100 lines

## Agent Instructions
Read `development/code-reviews/security-review-permissions.md` and `development/code-reviews/security-review-agent-strategies.md` for real findings. Cross-reference with `src/api/middleware/CLAUDE.md` and `agent/permissions/CLAUDE.md`.

## Estimated Complexity
Medium — requires reading security reports and extracting actionable patterns.
