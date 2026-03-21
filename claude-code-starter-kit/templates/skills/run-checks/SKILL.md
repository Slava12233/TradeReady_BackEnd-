---
name: run-checks
description: "Quick quality gate: runs lint, type check, and tests on changed files. Lighter than full review-changes pipeline — use for fast feedback during development."
user-invocable: true
allowed-tools: Bash, Read, Grep, Glob
---

# Quick Quality Checks

Run lint, type check, and tests on recently changed files for fast feedback.

## Process

### 1. Find changed files
```bash
git diff --name-only HEAD
git diff --name-only --cached
```

### 2. Run checks on changed files

**Lint:**
```bash
{{LINT_COMMAND}} <changed-files>
```

**Type check:**
```bash
{{TYPE_CHECK_COMMAND}} <changed-files>
```

**Tests:**
Map changed source files to test files and run only those:
```bash
{{TEST_COMMAND}} <mapped-test-files>
```

### 3. Summary
```
Quick Checks:
  Lint:  PASS/FAIL (N issues)
  Types: PASS/FAIL (N errors)
  Tests: PASS/FAIL (N passed, M failed)
```

## Rules
- Only check files that actually changed — never run full suite
- If everything passes, say so in one line
- If anything fails, show specific errors with file:line
- Don't fix anything — just report (use /review-changes for fixes)
