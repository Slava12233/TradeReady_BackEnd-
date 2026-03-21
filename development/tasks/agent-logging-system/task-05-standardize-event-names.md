---
task_id: 05
title: "Standardize event names across agent codebase"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "medium"
files: ["agent/**/*.py"]
tags:
  - task
  - agent
  - logging
---

# Task 05: Standardize Event Names Across Agent Codebase

## Assigned Agent: `backend-developer`

## Objective
Audit all 54 files in `agent/` that use structlog and normalize log event names to follow the `"{component}.{operation}[.{outcome}]"` convention.

## Context
Existing event names are mostly dot-notation but inconsistent in prefix (some use module names, some use arbitrary strings). This task creates a consistent taxonomy.

## Event Name Convention

| Component prefix | Scope |
|-----------------|-------|
| `agent.server` | AgentServer lifecycle |
| `agent.session` | Conversation session management |
| `agent.decision` | Trade decision pipeline |
| `agent.trade` | Trade execution |
| `agent.memory` | Memory CRUD operations |
| `agent.permission` | Permission checks |
| `agent.budget` | Budget enforcement |
| `agent.strategy` | Strategy pipeline |
| `agent.api` | Outbound API calls |
| `agent.llm` | LLM interactions |
| `agent.workflow` | Workflow step execution |
| `agent.task` | Celery task execution |

## Implementation Details
1. Grep for all `logger.info(`, `logger.warning(`, `logger.error(`, `logger.debug(`, `logger.exception(` calls in `agent/`
2. For each, check the first argument (event name string)
3. If it doesn't match the convention, rename it using the table above
4. Ensure all keyword arguments use descriptive names (not `extra={}` dict)

## Acceptance Criteria
- [ ] All log event names in `agent/` follow `component.operation[.outcome]` format
- [ ] No event names use raw module names or arbitrary strings
- [ ] All structured context uses kwargs, not `extra={}` dicts
- [ ] `ruff check agent/` passes
- [ ] No functional behavior changes

## Agent Instructions
- This is a bulk search-and-replace task — be systematic
- Read `agent/CLAUDE.md` for the full file inventory
- Do NOT change log levels or add/remove log calls — only rename events and fix kwargs
- Group changes by component (server files, memory files, trading files, etc.)

## Estimated Complexity
Medium — many files, but each change is simple (string rename)
