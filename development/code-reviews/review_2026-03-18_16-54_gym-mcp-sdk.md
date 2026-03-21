---
type: code-review
date: 2026-03-18
reviewer: code-reviewer
verdict: NEEDS FIXES
scope: gym-mcp-sdk
tags:
  - review
  - gym
  - mcp
  - sdk
---

# Code Review Report

- **Date:** 2026-03-18 16:54
- **Reviewer:** code-reviewer agent
- **Verdict:** NEEDS FIXES

## Files Reviewed

### STR-3 (tradeready-gym package)
- `tradeready-gym/pyproject.toml`
- `tradeready-gym/tradeready_gym/__init__.py`
- `tradeready-gym/tradeready_gym/envs/base_trading_env.py`
- `tradeready-gym/tradeready_gym/envs/single_asset_env.py`
- `tradeready-gym/tradeready_gym/envs/multi_asset_env.py`
- `tradeready-gym/tradeready_gym/envs/live_env.py`
- `tradeready-gym/tradeready_gym/spaces/action_spaces.py`
- `tradeready-gym/tradeready_gym/spaces/observation_builders.py`
- `tradeready-gym/tradeready_gym/rewards/custom_reward.py`
- `tradeready-gym/tradeready_gym/rewards/pnl_reward.py`
- `tradeready-gym/tradeready_gym/rewards/sharpe_reward.py`
- `tradeready-gym/tradeready_gym/rewards/sortino_reward.py`
- `tradeready-gym/tradeready_gym/rewards/drawdown_penalty_reward.py`
- `tradeready-gym/tradeready_gym/utils/training_tracker.py`
- `tradeready-gym/tradeready_gym/wrappers/feature_engineering.py`
- `tradeready-gym/tradeready_gym/wrappers/normalization.py`
- `tradeready-gym/tradeready_gym/wrappers/batch_step.py`
- `tradeready-gym/tests/test_gymnasium_compliance.py`
- `tradeready-gym/examples/10_live_trading.py` (representative)

### STR-4 (MCP Tools expansion)
- `src/mcp/tools.py`
- `src/mcp/CLAUDE.md`

### SDK extensions
- `sdk/agentexchange/client.py`
- `sdk/agentexchange/async_client.py`

## CLAUDE.md Files Consulted
- `CLAUDE.md` (root)
- `src/mcp/CLAUDE.md`
- `src/strategies/CLAUDE.md`
- `src/training/CLAUDE.md`
- `src/utils/CLAUDE.md`
- `tests/CLAUDE.md`
- `sdk/CLAUDE.md`
- `development/context.md`

---

## Critical Issues (must fix)

### 1. Bare `except:` in `live_env.py` — swallows all exceptions including `KeyboardInterrupt`

- **File:** `tradeready-gym/tradeready_gym/envs/live_env.py:111`
- **Rule violated:** Code Standards — "never bare `except:`"
- **Issue:** The order submission loop uses a bare `except: pass` which swallows `KeyboardInterrupt`, `SystemExit`, and any `BaseException`. This means Ctrl+C while the live env is running an order would be silently consumed, making the process impossible to interrupt gracefully.
- **Fix:**
  ```python
  # Replace:
  except Exception:
      pass
  # With:
  except httpx.HTTPStatusError as exc:
      logger.debug("Live order rejected: %s", exc.response.text)
  except httpx.TransportError as exc:
      logger.warning("Live order transport error: %s", exc)
  ```

### 2. `_call_api` in `tools.py` crashes on 204 / empty body responses

- **File:** `src/mcp/tools.py:1211-1213`
- **Rule violated:** Correctness / robustness — the helper always calls `response.json()` without checking for empty body.
- **Issue:** The existing `_call_api` helper calls `response.raise_for_status()` then unconditionally calls `response.json()`. Several endpoints return HTTP 204 No Content or a response with no body (e.g., `undeploy_strategy`, `cancel_order`). This will raise a `json.JSONDecodeError` at runtime, which then surfaces to the MCP caller as an opaque "Error:" message rather than success.
- **Fix:**
  ```python
  async def _call_api(...) -> dict[str, Any]:
      response = await client.request(method, path, params=params, json=json)
      response.raise_for_status()
      if response.status_code == 204 or not response.content:
          return {}
      return response.json()
  ```
  Note: `BaseTradingEnv._api_call()` in the gym package already handles this correctly (lines 115-117). The MCP `_call_api` simply missed the same guard.

### 3. `TrainingTracker.__del__` is unreliable and dangerous

- **File:** `tradeready-gym/tradeready_gym/utils/training_tracker.py:110-116`
- **Rule violated:** Error handling / async patterns — `__del__` is not guaranteed to run and can cause issues during interpreter shutdown.
- **Issue:** `__del__` is called during garbage collection, which may occur during interpreter teardown when the `httpx.Client` may already be closed or in an undefined state. During CPython shutdown, module globals are set to `None`, so `httpx` and `logger` may be `None` when `__del__` fires. The outer `try/except Exception` catches this but silently. More importantly, if `complete_run()` calls `self._http.close()` in its `finally` block and `__del__` calls `complete_run()` again, the HTTP client is already closed, causing a second `RuntimeError`.
- **Fix:** Remove the `__del__` method entirely. Instead, document that callers must call `env.close()` (which calls `tracker.complete_run()`) or use the environment as a context manager. The `close()` method in `BaseTradingEnv` already handles this correctly. The `__del__` provides false safety with real risks.

### 4. Test file imports are at the bottom — breaks test discovery and IDE analysis

- **File:** `tradeready-gym/tests/test_gymnasium_compliance.py:370-374`
- **Rule violated:** Standard Python convention; ruff `E402` rule (module level import not at top of file) — these imports are explicitly marked `# noqa: E402` which hides the structural problem.
- **Issue:** `SingleAssetTradingEnv`, `MultiAssetTradingEnv`, `NormalizationWrapper`, `BatchStepWrapper`, and `FeatureEngineeringWrapper` are imported at line 370, *after* the test classes that use them (lines 97-329). The test classes reference these names without any local import, which means any static analysis tool will flag them as undefined at the class definition site. pytest will find and run the tests only because Python executes the module top-to-bottom before running collected tests — but the classes are syntactically referencing names that aren't yet bound.
- **Fix:** Move all imports to the top of the file:
  ```python
  from tradeready_gym.envs.single_asset_env import SingleAssetTradingEnv
  from tradeready_gym.envs.multi_asset_env import MultiAssetTradingEnv
  from tradeready_gym.wrappers.normalization import NormalizationWrapper
  from tradeready_gym.wrappers.batch_step import BatchStepWrapper
  from tradeready_gym.wrappers.feature_engineering import FeatureEngineeringWrapper
  ```
  Remove the `# noqa: E402` comments.

### 5. `starting_balance` uses `float` — violates project Decimal standard

- **File:** `tradeready-gym/tradeready_gym/envs/base_trading_env.py:50`
- **Rule violated:** Code Standards — "`Decimal` (never `float`) for money/prices"
- **Issue:** `BaseTradingEnv.__init__` accepts `starting_balance: float = 10000.0`. This is a monetary value. While the gym package is a separate package from the main platform, it represents financial starting capital, and using `float` for it introduces imprecision that propagates into the `str(self.starting_balance)` conversion sent to the API (e.g. `"10000.0"` instead of `"10000.00000000"`). `SingleAssetTradingEnv` then does `Decimal(str(equity * self.position_size_pct / current_price))` where `equity` is a `float`, which means all quantity calculations are float-based.
- **Fix:** Accept `Decimal | float | str` and normalise to `Decimal` internally — consistent with how the main SDK handles monetary inputs:
  ```python
  from decimal import Decimal
  # In __init__:
  self.starting_balance: Decimal = Decimal(str(starting_balance))
  ```
  And update the uses: `self._prev_equity: Decimal = self.starting_balance`.
  If keeping `float` throughout the gym package for RL-framework compatibility, add a comment explaining the intentional deviation and ensure the API call always uses `str(Decimal(str(self.starting_balance)))` to avoid float-to-string precision issues.

---

## Warnings (should fix)

### W1. `get_test_status` and `get_test_results` hit the same endpoint — no functional distinction

- **File:** `src/mcp/tools.py:1770-1784`, `sdk/agentexchange/client.py:932-962`
- **Issue:** Both `get_test_status` and `get_test_results` (MCP tools #52 and #53) and both `get_test_status` / `get_test_results` SDK methods dispatch to `GET /api/v1/strategies/{id}/tests/{test_id}`. They are identical. The duplication is user-visible (an LLM seeing two MCP tools with the same underlying call will be confused), and the SDK methods are byte-for-byte copies. The same issue exists in the CLAUDE.md table (tools 52 and 53 are listed with identical REST endpoints).
- **Fix:** Either collapse them into one tool, or route `get_test_status` to a status-only endpoint (if one exists or should be created) that returns only `status`, `progress_pct`, and `episodes_completed` — without the full results payload.

### W2. `adx` feature in `ObservationBuilder` is a placeholder, not actual ADX

- **File:** `tradeready-gym/tradeready_gym/spaces/observation_builders.py:181-187`
- **Issue:** The `adx` feature is documented as "ADX value" but is implemented as `abs(close_i - close_{i-1}) / close_{i-1}` — this is a raw price momentum / return, not ADX (Average Directional Index). ADX requires the directional movement calculation (+DM, -DM, TR, and smoothed averages). A user requesting `adx` as a feature will get a mislabeled observation that does not match the documented indicator.
- **Fix:** Either implement true ADX (consistent with the `IndicatorEngine` in `src/strategies/`) or rename the feature to `"price_momentum"` and update `_FEATURE_DIMS` accordingly. A comment marking it as a placeholder is insufficient because the feature name `"adx"` is part of the public API contract.

### W3. `DrawdownPenaltyReward` peak equity not reset on environment reset

- **File:** `tradeready-gym/tradeready_gym/rewards/drawdown_penalty_reward.py:21-23`
- **Issue:** `_peak_equity` is initialised at `0.0` in `__init__` but is never reset when the environment calls `reset()`. In a multi-episode training loop, `_peak_equity` carries over from the previous episode. After a good episode where equity reached 11,000, the next episode starts with `_peak_equity = 11,000`, so a drawdown of 10% of 10,000 (the new starting balance) would be calculated against the old peak, creating an incorrect and misleading penalty. The same issue applies to `SharpeReward._returns`, `SortinoReward._returns`, and their `_prev_sharpe` / `_prev_sortino` accumulators.
- **Fix:** Expose a `reset()` method on `CustomReward` base class (or implement it on each stateful reward class), and call it from `BaseTradingEnv.reset()`:
  ```python
  # In CustomReward base class:
  def reset(self) -> None:
      """Reset internal state between episodes. Override in stateful subclasses."""

  # In DrawdownPenaltyReward:
  def reset(self) -> None:
      self._peak_equity = 0.0

  # In BaseTradingEnv.reset():
  self.reward_fn.reset()
  ```

### W4. `_json_content` lazy-imports `json` inside a hot path function

- **File:** `src/mcp/tools.py:1262`
- **Issue:** `_json_content` is called on every successful tool invocation and does `import json` inside the function body. While Python caches module imports after the first load, the `import` statement still costs a dictionary lookup on every call. This is a minor performance issue in a hot-path helper. Standard library imports should be at module level.
- **Fix:** Move `import json` to the top of `tools.py` with the other stdlib imports.

### W5. `LiveTradingEnv` inherits `_create_session` override but parent's `reset()` calls it

- **File:** `tradeready-gym/tradeready_gym/envs/live_env.py:49-51` and `base_trading_env.py:161`
- **Issue:** `LiveTradingEnv._create_session()` returns the string `"live"`. `BaseTradingEnv.reset()` calls `self._create_session()` — but `LiveTradingEnv` overrides `reset()` entirely and does NOT call `super().reset()`. This is correct behaviour, but the `_create_session` override in `LiveTradingEnv` is dead code that is never called. It creates confusion about the design intent: a reader seeing `_create_session` overridden might assume `super().reset()` is called somewhere.
- **Fix:** Remove `_create_session` from `LiveTradingEnv` and add a comment in `LiveTradingEnv.reset()` explaining why `super().reset()` is deliberately not called.

### W6. `TrainingTracker.register_run` is silently called twice if the env sends multiple episodes before the first completes

- **File:** `tradeready-gym/tradeready_gym/envs/base_trading_env.py:178-179`
- **Issue:** `register_run()` is only called when `self._episode_count == 1`. The guard in `TrainingTracker.register_run()` (`if self._registered: return`) prevents double-registration. This is correct. However, `report_episode()` in the tracker calls `self.register_run()` if not registered — so there are now two code paths that trigger registration. The first is the `if self._episode_count == 1` guard in the env, and the second is the auto-register in `report_episode`. If `track_training=True` and the first call to `step()` returns `is_complete=True` before `register_run()` has been called (which can happen if the dataset is extremely short), the episode report would trigger registration. This is fine functionally, but the conditional in the env is misleading — it suggests registration only happens on episode 1, when it actually happens on first `report_episode` call regardless.
- **Fix:** Remove the `if self._episode_count == 1` guard and let the tracker's own idempotency guard handle it. Simpler and more correct:
  ```python
  if self._tracker:
      self._tracker.register_run()  # idempotent
  ```

### W7. SDK `client.py` section comment says "Analytics (3 methods)" but there are 4 analytics methods

- **File:** `sdk/agentexchange/client.py:733`
- **Issue:** The comment `# Analytics (3 methods)` appears after the strategy/test/training methods are added, but counting from the comment there are 4 analytics-related methods: `get_performance`, `get_portfolio_history`, and `get_leaderboard` (which comes later, with its own section header). The section boundaries in the comments no longer match the method groups. This is a documentation inconsistency, not a functional bug.
- **Fix:** Update the section comment to `# Analytics (1 method)` since only `get_performance` and `get_portfolio_history` appear under that header before `get_leaderboard` gets its own section. Or reorganise to group `get_performance`, `get_portfolio_history`, and `get_leaderboard` together under one section header.

---

## Suggestions (consider)

### S1. `ObservationBuilder` duplicates indicator logic already in `src/strategies/indicators.py`

- **File:** `tradeready-gym/tradeready_gym/spaces/observation_builders.py:201-289`
- The gym package re-implements RSI, MACD, Bollinger Bands, and ATR as list-based pure Python. The main platform already has a `IndicatorEngine` with numpy-based implementations. The gym package is a separate installable, so it cannot import from `src/`, but the duplication means two divergent implementations for the same indicators. Consider extracting the indicator logic into a small shared utility (e.g., `tradeready-gym/tradeready_gym/utils/indicators.py`) that can also be referenced from examples and tests, to at least keep the duplication within the gym package itself clearly isolated.

### S2. `BaseTradingEnv` API key is exposed as a public attribute (`self.api_key`)

- **File:** `tradeready-gym/tradeready_gym/envs/base_trading_env.py:63`
- `self.api_key = api_key` stores the key as a public attribute. It is used to create the `httpx.Client` and the `TrainingTracker`. Consider using `self._api_key` (private prefix, per project naming conventions) to discourage accidental exposure via serialization or `vars(env)` introspection.

### S3. Examples hardcode `"ak_live_YOUR_KEY"` — consider a clear placeholder convention

- **File:** `tradeready-gym/examples/10_live_trading.py:22` and others
- The placeholder `"ak_live_YOUR_KEY"` works but `"ak_live_..."` (consistent with the project's established placeholder) would better match the docstrings, CLAUDE.md files, and README examples throughout the rest of the codebase.

### S4. MCP `_dispatch` `case _:` raises `ValueError` — consider returning an error content instead

- **File:** `src/mcp/tools.py:1829-1830`
- If an unknown tool name reaches `_dispatch`, a `ValueError` is raised. The outer `call_tool` handler catches all `Exception` and returns `_error_content`. This works, but since `_dispatch` is an internal function, raising `ValueError` is fine. The suggestion is to use a more descriptive message that includes the full list of known tool names for easier debugging during development.

### S5. `pyproject.toml` for the gym package does not pin `mypy` or type stubs in dev dependencies

- **File:** `tradeready-gym/pyproject.toml:26-28`
- The dev dependencies include `ruff` but not `mypy` or `gymnasium-stubs`. Since `gymnasium` has typed stubs in `gymnasium.py` (it is `py.typed`), mypy would benefit from being in the dev toolchain from day one.

---

## Passed Checks

- **Naming conventions**: All files use `snake_case.py`. All classes use `PascalCase`. Functions and methods use `snake_case`. Constants use `UPPER_SNAKE_CASE`. Private attributes use `_prefix`. Consistent throughout.
- **Gymnasium API compliance**: `reset()` returns `(obs, info)` tuple. `step()` returns `(obs, reward, terminated, truncated, info)` 5-tuple. Both match the Gymnasium v0.29 API contract.
- **Dependency direction (gym package)**: The gym package imports nothing from `src.*`. It communicates exclusively via HTTP. Architecture is correct.
- **MCP tool count consistency**: `TOOL_COUNT = 58` in `tools.py`, `register_tools` docstring says 58, `CLAUDE.md` says 58, `__init__.py` says 58. All in sync.
- **MCP dispatch completeness**: All 58 tool names in `_TOOL_DEFINITIONS` have corresponding `case` branches in `_dispatch()`. No orphaned definitions or missing dispatch paths.
- **SDK sync**: All 13 new methods added to `client.py` (`create_strategy`, `get_strategies`, `get_strategy`, `create_version`, `deploy_strategy`, `undeploy_strategy`, `run_test`, `get_test_status`, `get_test_results`, `compare_versions`, `get_training_runs`, `get_training_run`, `compare_training_runs`) have identical async counterparts in `async_client.py`. The CLAUDE.md requirement for sync parity is met.
- **Decimal for API order quantities**: `SingleAssetTradingEnv` and `MultiAssetTradingEnv` both use `Decimal(str(...))` when constructing quantity strings for order API calls. This is correct.
- **No secrets hardcoded**: No API keys, JWT tokens, or passwords in source files. Examples use placeholder strings only.
- **`asyncio_mode = "auto"` in gym test config**: The `pyproject.toml` for the gym package sets `asyncio_mode = "auto"`, consistent with the main project's test conventions.
- **MCP tools security — confirm guards on destructive operations**: `reset_account` and `cancel_all_orders` both check `confirm == True` client-side and return an abort message without hitting the API if not confirmed. Strategy management tools (deploy, undeploy) do not have confirmation guards — this is appropriate because those are not account-destroying operations.
- **Reward functions stateless base class**: `CustomReward` and `PnLReward` are stateless (no mutable instance fields). `PnLReward.compute` is a pure function. Correct.
- **`BatchStepWrapper` correctly sums rewards**: The batch wrapper accumulates `total_reward += float(reward)` and breaks early on `terminated`. This is the standard implementation for frame-skipping wrappers.
- **`NormalizationWrapper` uses Welford's algorithm**: The online mean/variance update is implemented correctly — delta computed before and after mean update.
- **Google-style docstrings**: All public classes and methods have docstrings with Args/Returns sections where applicable.
- **`gymnasium.register` called at module import**: All 7 environments are registered at module-level import time in `__init__.py`. The `register_envs` entry point is correctly defined as a no-op since registration happens on import.
