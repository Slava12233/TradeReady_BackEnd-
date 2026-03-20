---
task_id: 18
title: "Tests for enhanced agent tools"
agent: "test-runner"
phase: 1
depends_on: [16, 17]
status: "pending"
priority: "medium"
files: ["tests/unit/test_agent_tools.py"]
---

# Task 18: Tests for enhanced agent tools

## Assigned Agent: `test-runner`

## Objective
Write unit tests for all 5 enhanced agent tools.

## Files to Create
- `tests/unit/test_agent_tools.py` — tests for all agent-specific tools

## Acceptance Criteria
- [ ] At least 3 tests per tool (15+ total)
- [ ] `reflect_on_trade` tested with: successful reflection, trade not found, incomplete trade
- [ ] `review_portfolio` tested with: healthy portfolio, concentrated portfolio, empty portfolio
- [ ] `scan_opportunities` tested with: matches found, no matches, criteria edge cases
- [ ] `journal_entry` tested with: normal entry, auto-tagging, market context capture
- [ ] `request_platform_feature` tested with: new request, duplicate detection
- [ ] All external calls mocked (SDK, Redis, DB)

## Dependencies
- Tasks 16, 17 (all tools must exist)

## Agent Instructions
1. Mock SDK client, Redis, and DB repos
2. Test each tool in isolation
3. Verify that tools persist data (journal entries, learnings) via mocked repos
4. Test error paths: what happens when SDK is unavailable?

## Estimated Complexity
Medium — 15+ tests covering all tool functionality.
