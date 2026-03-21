---
task_id: 16
title: "E2E smoke test against live platform"
type: task
agent: "e2e-tester"
phase: 6
depends_on: [13, 15]
status: "skipped"
board: "[[tradeready-test-agent/README]]"
priority: "high"
files: []
tags:
  - task
  - testing-agent
---

# Task 16: E2E smoke test against live platform

## Assigned Agent: `e2e-tester`

## Objective
Run the agent's smoke test workflow against the live platform to validate end-to-end connectivity and trading functionality.

## Test Scenarios
1. Install the agent package: `pip install -e agent/`
2. Set up `.env` with valid platform credentials
3. Run `python -m agent.main smoke` and verify all 10 steps pass
4. Verify trades appear in the platform database
5. Verify the generated report file is valid JSON

## Acceptance Criteria
- [ ] Agent package installs without errors
- [ ] Smoke test completes without crashes
- [ ] At least 8/10 smoke test steps pass
- [ ] Test trade visible in platform (verify via REST API)
- [ ] Report JSON file generated in `agent/reports/`
- [ ] Return platform credentials for manual UI verification

## Dependencies
- Task 13 (CLI must be complete)
- Task 15 (code review must pass — no critical issues)

## Agent Instructions
- Platform must be running (docker compose or local uvicorn)
- Register a new test account for the agent
- Use a real OpenRouter API key (or mock the LLM for basic connectivity)
- If OpenRouter isn't available, test with direct REST/SDK calls only
- Capture stdout/stderr for debugging

## Estimated Complexity
Medium — running live tests against the platform
