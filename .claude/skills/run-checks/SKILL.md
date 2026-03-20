---
name: run-checks
description: "Quick quality gate: runs ruff check, mypy, and pytest on changed files. Lighter than full review-changes pipeline — use for fast feedback during development."
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
Separate into Python files (`.py`) and TypeScript files (`.ts`, `.tsx`).

### 2. Python checks (if Python files changed)

**Lint:**
```bash
ruff check <changed-python-files>
```

**Type check:**
```bash
mypy <changed-python-files> --ignore-missing-imports
```

**Tests:**
Map changed source files to test files:
- `src/foo/bar.py` -> `tests/unit/test_bar.py`
- Run only the mapped tests:
```bash
python -m pytest <mapped-test-files> -v --tb=short
```

### 3. Frontend checks (if TypeScript files changed)

```bash
cd Frontend && npx tsc --noEmit
```

### 4. Summary
```
Quick Checks:
  Lint:  PASS/FAIL (N issues)
  Types: PASS/FAIL (N errors)
  Tests: PASS/FAIL (N passed, M failed)
```

## Rules
- Only check files that actually changed — never run full suite
- If everything passes, say so in one line
- If anything fails, show the specific errors with file:line
- Don't fix anything — just report (use /review-changes for fixes)
