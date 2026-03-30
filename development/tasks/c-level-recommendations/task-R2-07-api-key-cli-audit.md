---
task_id: R2-07
title: "Audit remaining --api-key CLI arg exposure"
type: task
agent: "security-reviewer"
phase: 2
depends_on: []
status: "completed"
priority: "medium"
board: "[[c-level-recommendations/README]]"
files: ["agent/", "scripts/"]
tags:
  - task
  - security
  - cli
  - secrets
---

# Task R2-07: Audit Remaining `--api-key` CLI Arg Exposure

## Assigned Agent: `security-reviewer`

## Objective
Verify no CLI scripts expose API keys in process lists via `--api-key` arguments. Remove any remaining instances.

## Context
HIGH-3 from strategies security review: `--api-key` CLI argument in strategy scripts exposes `ak_live_...` keys in `ps aux` and shell history. Reported as "partially fixed."

## Acceptance Criteria
- [ ] `grep -rn "\-\-api.key\|argparse.*api.key\|add_argument.*api.key" agent/ src/ scripts/` returns zero results
- [ ] All API key access reads from env vars via `AgentConfig` (pydantic-settings)
- [ ] No `ak_live_` strings appear in any argparse definitions

## Dependencies
None — audit + fix task

## Agent Instructions
1. Run grep to find all instances
2. For each instance, replace with env var reading via `AgentConfig`
3. Verify pydantic-settings already supports the env var pattern

## Estimated Complexity
Low — audit and mechanical replacement
