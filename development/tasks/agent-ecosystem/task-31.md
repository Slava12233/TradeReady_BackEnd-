---
task_id: 31
title: "Tests for trading loop and journal"
agent: "test-runner"
phase: 2
depends_on: [26, 27, 28]
status: "pending"
priority: "high"
files: ["tests/unit/test_trading_loop.py", "tests/unit/test_trade_executor.py", "tests/unit/test_trading_journal.py"]
---

# Task 31: Tests for trading loop and journal

## Assigned Agent: `test-runner`

## Objective
Write unit tests for the trading loop, execution engine, and journal system.

## Files to Create
- `tests/unit/test_trading_loop.py` — test loop cycle, signal generation, permission checks
- `tests/unit/test_trade_executor.py` — test execution, pre/post logging, error handling
- `tests/unit/test_trading_journal.py` — test decision recording, outcome tracking, reflection

## Acceptance Criteria
- [ ] At least 8 tests for trading loop (full cycle, permission denial, budget denial, error recovery)
- [ ] At least 6 tests for trade executor (successful trade, SDK failure, retry, batch)
- [ ] At least 6 tests for journal (record decision, record outcome, daily summary)
- [ ] 20+ tests total
- [ ] Mock all external dependencies (SDK, strategies, repos)
- [ ] Test that permission denial prevents trade execution
- [ ] Test that budget exhaustion prevents trade execution
- [ ] Test error recovery in the loop (one failure doesn't crash the loop)

## Dependencies
- Tasks 26, 27, 28 (trading system components)

## Agent Instructions
1. Mock the signal generator to return predictable signals
2. Mock the SDK to return predictable order results
3. Test the full loop cycle: observe → analyze → decide → check → execute → record
4. Test the error case: signal generator throws, verify loop continues
5. Verify that every trade results in an `agent_decisions` entry

## Estimated Complexity
Medium — testing the core trading pipeline with many mock dependencies.
