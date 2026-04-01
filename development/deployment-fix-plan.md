---
type: plan
date: 2026-04-01
status: completed
tags:
  - deployment
  - ci-cd
  - mypy
---

# Deployment Fix Plan — CI/CD Pipeline Failures

## Problem

The CI/CD pipeline (`test.yml`) was failing on the **mypy type checker** step with 4 errors in 2 files:

```
src/mcp/tools.py:1317: error: Unused "type: ignore[no-untyped-call]" comment  [unused-ignore]
agent/strategies/rl/runner.py:195: error: Class cannot subclass "BaseCallback" (has type "Any")  [misc]
agent/strategies/rl/runner.py:208: error: Unused "type: ignore" comment  [unused-ignore]
agent/strategies/rl/runner.py:211: error: Unused "type: ignore" comment  [unused-ignore]
```

## Root Cause Analysis

The errors stem from **environment differences** between local development and CI:

1. **CI environment:** Runs `mypy src/ --ignore-missing-imports` on Ubuntu with `requirements.txt` + `requirements-dev.txt`. The `--ignore-missing-imports` flag combined with missing SB3/MCP stubs causes different type resolution than local.

2. **`agent/strategies/rl/runner.py`** (3 errors):
   - `stable-baselines3` has no type stubs. On CI, `BaseCallback` resolves as `Any` → `disallow_subclassing_any = true` triggers `[misc]`
   - On CI, since `ep_info_buffer` is `Any`, the `[arg-type]` and `[union-attr]` ignores are unnecessary → `warn_unused_ignores = true` triggers `[unused-ignore]`
   - Locally with SB3 installed, the types resolve properly, so `[arg-type]` and `[union-attr]` ARE needed but `[misc]` is NOT

3. **`src/mcp/tools.py`** (1 error):
   - The `mcp` package's `server.list_tools()` decorator is typed on CI but untyped locally → `[no-untyped-call]` ignore is unused on CI but needed locally

**Key insight:** `warn_unused_ignores = true` in `pyproject.toml` combined with different type stub availability across environments makes it impossible to have `type: ignore` comments that are correct everywhere.

## Fix Plan

### Phase 1: Add mypy per-module overrides (COMPLETED)

**File: `pyproject.toml`**

Add two `[[tool.mypy.overrides]]` sections:

1. `agent.strategies.rl.*` — disable `warn_unused_ignores` and `disallow_subclassing_any`
   - These files use SB3's `BaseCallback` which has no stubs
   - Type ignores needed locally conflict with CI environment

2. `src.mcp.tools` — disable `warn_unused_ignores`
   - MCP SDK type stubs differ between environments

### Phase 2: Restore necessary type ignores (COMPLETED)

**File: `agent/strategies/rl/runner.py`**

- Line 195: Keep `# type: ignore[misc]` for `BaseCallback` subclass (needed on CI where it's `Any`)
- Line 208: Keep `# type: ignore[arg-type]` for `len(self.model.ep_info_buffer)` (needed locally where type is `deque[Any] | None`)
- Line 211: Keep `# type: ignore[union-attr]` for iterating `ep_info_buffer` (needed locally)

**File: `src/mcp/tools.py`**

- Line 1317: Keep `# type: ignore[misc, no-untyped-call]` (both may fire depending on environment)

### Phase 3: Verify (COMPLETED)

- `mypy src/ --ignore-missing-imports` → **Success: 0 errors in 153 files**
- `mypy src/mcp/tools.py agent/strategies/rl/runner.py --ignore-missing-imports` → **Success: 0 errors**
- `ruff check src/mcp/tools.py` → **All checks passed**

## Files Changed

| File | Change |
|------|--------|
| `pyproject.toml` | Added 2 mypy override sections for `agent.strategies.rl.*` and `src.mcp.tools` |
| `src/mcp/tools.py` | Restored `no-untyped-call` to type ignore comment on line 1317 |
| `agent/strategies/rl/runner.py` | Added `# type: ignore[misc]` to `BaseCallback` subclass on line 195 |

## Prevention

For future SB3/MCP type issues:
- Any file that imports from packages without type stubs should have a mypy override in `pyproject.toml` disabling `warn_unused_ignores`
- This is the standard approach for mixed-stubs codebases
