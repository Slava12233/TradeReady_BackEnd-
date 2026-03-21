---
paths:
  - "tests/**/*"
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/__tests__/**"
---

# Testing Rules

<!-- BOOTSTRAP: Customize for your test framework -->

## Test Philosophy

- Tests verify behavior, not implementation
- Every bug fix needs a regression test
- New features need tests before merging
- Tests must be deterministic — no flaky tests

## Test Structure

- Group related tests in classes/describe blocks
- Test names describe behavior: `test_rejects_negative_quantity` not `test_order_3`
- Follow Arrange-Act-Assert pattern
- One assertion focus per test (multiple asserts OK if testing one behavior)

## What to Test (Priority Order)

1. Public methods — every public method has at least one test
2. Error handling — exceptions, validation failures, edge cases
3. Business logic — calculations, state transitions, conditional branches
4. Integration points — correct calls to dependencies with right args

## What NOT to Test

- Private methods (test through public API)
- Third-party library behavior
- Simple getters/setters with no logic
- Framework internals

## Mocking Rules

- Mock external dependencies (DB, APIs, cache, file system)
- Never mock the unit under test
- Use the project's established mock patterns and fixtures
- Prefer fakes over mocks when practical

## Test File Location

- Co-located: `src/module/module.test.ts` next to source
- Separate: `tests/unit/test_module.py` mirroring source structure
- Integration: `tests/integration/` for cross-module tests

## Coverage

- Aim for meaningful coverage, not 100%
- Uncovered code should be intentional (documented why no test)
- Coverage alone doesn't mean quality — review what the tests actually verify
