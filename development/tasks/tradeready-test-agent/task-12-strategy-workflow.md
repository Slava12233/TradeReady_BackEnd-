---
task_id: 12
title: "Strategy workflow"
type: task
agent: "backend-developer"
phase: 5
depends_on: [6, 7, 8]
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "medium"
files:
  - "agent/workflows/strategy_workflow.py"
tags:
  - task
  - testing-agent
---

# Task 12: Strategy workflow

## Assigned Agent: `backend-developer`

## Objective
Implement the strategy iteration workflow: create a strategy → test it → analyze results → create improved V2 → compare versions.

## Files to Create
- `agent/workflows/strategy_workflow.py` — `async def run_strategy_workflow(config: AgentConfig) -> WorkflowResult`:

  **Steps:**
  1. Agent designs a simple strategy definition (e.g., SMA crossover)
  2. REST: `POST /api/v1/strategies` — create strategy
  3. REST: `POST /api/v1/strategies/{id}/test` — run strategy test
  4. REST: poll `GET /api/v1/strategies/{id}/tests/{test_id}` until complete
  5. Agent reviews test results and recommendations
  6. Agent creates improved V2 definition based on findings
  7. REST: `POST /api/v1/strategies/{id}/versions` — create V2
  8. REST: `POST /api/v1/strategies/{id}/test` — test V2
  9. REST: `GET /api/v1/strategies/{id}/compare-versions` — V1 vs V2 comparison
  10. Agent evaluates: did the platform's tools help iterate?
  11. Return `WorkflowResult` with strategy comparison

## Acceptance Criteria
- [ ] Full strategy lifecycle from creation through version comparison
- [ ] LLM designs initial strategy definition
- [ ] LLM analyzes test results and proposes improvements
- [ ] V2 creation based on V1 findings
- [ ] Version comparison results captured
- [ ] Polling loop with timeout for test completion
- [ ] Structured evaluation of platform tooling effectiveness

## Dependencies
- Task 6 (REST tools for strategy endpoints)
- Task 7 (output models)
- Task 8 (system prompt)

## Agent Instructions
- Read `src/strategies/CLAUDE.md` for strategy definition format
- Read `src/api/routes/strategy_routes.py` for exact endpoint shapes
- The strategy definition format varies — check what the API expects
- Polling: check test status every 5 seconds, timeout after 120 seconds
- Use the LLM for strategy design and improvement — that's the interesting part

## Estimated Complexity
High — multi-step workflow with LLM-driven strategy design and iteration
