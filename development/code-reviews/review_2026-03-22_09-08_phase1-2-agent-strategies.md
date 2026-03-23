---
type: code-review
date: 2026-03-22
reviewer: code-reviewer
verdict: PASS WITH WARNINGS
scope: phase1-2-agent-strategies
tags:
  - review
  - agent
  - strategies
  - regime
  - rl
  - evolutionary
  - risk
  - ensemble
  - sdk-tools
---

# Code Review Report

- **Date:** 2026-03-22 09:08
- **Reviewer:** code-reviewer agent
- **Verdict:** PASS WITH WARNINGS

## Files Reviewed

**Task 08 (Regime features):**
- `agent/strategies/regime/labeler.py`
- `agent/strategies/regime/classifier.py`

**Task 10 (Composite RL reward):**
- `tradeready-gym/tradeready_gym/rewards/composite.py`
- `tradeready-gym/tradeready_gym/rewards/__init__.py`
- `agent/strategies/rl/config.py`
- `agent/strategies/rl/train.py`

**Task 12 (Evolutionary fitness):**
- `agent/strategies/evolutionary/config.py`
- `agent/strategies/evolutionary/battle_runner.py`
- `agent/strategies/evolutionary/evolve.py`

**Task 16 (Position sizing):**
- `agent/strategies/risk/sizing.py`
- `agent/strategies/risk/__init__.py`

**Task 17 (Drawdown profiles):**
- `agent/strategies/risk/risk_agent.py`
- `agent/strategies/risk/veto.py`

**Task 18 (Correlation risk):**
- `agent/strategies/risk/middleware.py`

**Task 19 (Circuit breakers):**
- `agent/strategies/ensemble/circuit_breaker.py`
- `agent/strategies/ensemble/run.py`

**Task 20 (Advanced order tools):**
- `agent/tools/sdk_tools.py`

## CLAUDE.md Files Consulted

- `CLAUDE.md` (root)
- `agent/CLAUDE.md`
- `agent/strategies/CLAUDE.md`
- `agent/strategies/regime/CLAUDE.md`
- `agent/strategies/rl/CLAUDE.md`
- `agent/strategies/evolutionary/CLAUDE.md`
- `agent/strategies/risk/CLAUDE.md`
- `agent/strategies/ensemble/CLAUDE.md`
- `agent/tools/CLAUDE.md`
- `tradeready-gym/CLAUDE.md`

---

## Critical Issues

None.

---

## Warnings (should fix)

### W1 — `RLConfig` missing composite weight sum validator

- **File:** `agent/strategies/rl/config.py` (composite weight fields, ~L256–297)
- **Rule violated:** Data integrity / fail-fast validation
- **Issue:** `CompositeReward.__init__()` validates that `sortino_weight + pnl_weight + activity_weight + drawdown_weight == 1.0` at construction time and raises `ValueError` on mismatch. However, `RLConfig` does not validate that the four `composite_*_weight` fields sum to 1.0. A misconfigured `.env` file (e.g., a typo setting `RL_COMPOSITE_PNL_WEIGHT=0.4` instead of 0.3) will pass `RLConfig` validation, persist silently until `_build_reward()` is called during training, and then raise inside the gym environment constructor — far from the misconfiguration site.
- **Fix:** Add a `@model_validator(mode="after")` to `RLConfig`:

```python
from pydantic import model_validator
import math

@model_validator(mode="after")
def validate_composite_weights_sum_to_one(self) -> "RLConfig":
    if self.reward_type == "composite":
        total = (
            self.composite_sortino_weight
            + self.composite_pnl_weight
            + self.composite_activity_weight
            + self.composite_drawdown_weight
        )
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(
                f"composite_*_weight fields must sum to 1.0 when reward_type='composite', "
                f"got {total:.6f}."
            )
    return self
```

---

### W2 — Redis pipeline usage does not use `async with` context manager

- **File:** `agent/strategies/ensemble/circuit_breaker.py:347`, `circuit_breaker.py:512`
- **Rule violated:** Project standard — `src/cache/CLAUDE.md` and the root `CLAUDE.md` state: _"Redis pipeline usage requires `async with redis.pipeline() as pipe:`"_
- **Issue:** Both pipeline calls use `self._redis.pipeline()` as a plain object assignment, not as an async context manager:

```python
# current (non-conformant):
pipe = self._redis.pipeline()
pipe.lpush(key, outcome)
...
await pipe.execute()
```

The `redis.asyncio` pipeline supports `async with` which ensures the pipeline is always reset/closed on error. While the bare object form works in practice, it deviates from the project's documented pattern and may not release pipeline resources on exception paths that escape the surrounding `except Exception` block.
- **Fix:**

```python
async with self._redis.pipeline() as pipe:
    pipe.lpush(key, outcome)
    pipe.ltrim(key, 0, limit - 1)
    pipe.expire(key, LOSSES_LIST_TTL_SECONDS)
    await pipe.execute()
```

Apply the same change to the `record_signal_outcome()` pipeline block at line 512.

---

### W3 — `_serialize_order()` silently drops unknown fields, not documented as exhaustive

- **File:** `agent/tools/sdk_tools.py:47`
- **Rule violated:** Maintainability / API surface
- **Issue:** `_serialize_order()` is a hard-coded list of 14 field names extracted from the `Order` dataclass. If the SDK's `Order` model gains new fields in the future (e.g., `agent_id`, `strategy_id`), they will be silently omitted from the tool response. The CLAUDE.md for `agent/tools/` documents this dict as the authoritative response shape, but callers (including the LLM) have no way to know they may be missing fields.
- **Fix:** Either add a `# NOTE: extend this list when Order gains new fields` comment clearly calling out the maintenance obligation, or use a more defensive approach that iterates the dataclass fields:

```python
import dataclasses

def _serialize_order(order: Any) -> dict[str, Any]:
    result = {}
    for f in dataclasses.fields(order):
        val = getattr(order, f.name)
        if hasattr(val, 'isoformat'):
            result[f.name] = val.isoformat() if val is not None else None
        elif hasattr(val, '__str__') and type(val).__module__ != 'builtins':
            result[f.name] = str(val) if val is not None else None
        else:
            result[f.name] = val
    return result
```

This is a low-priority warning — the current implementation is correct today and matches the documented API surface.

---

### W4 — `CompositeReward._sortino_increment()` modifies `self._returns` inside a method that is expected to be idempotent

- **File:** `tradeready-gym/tradeready_gym/rewards/composite.py:182`
- **Rule violated:** Correctness (subtle stateful side-effect in a compute method)
- **Issue:** `_sortino_increment()` both appends to `self._returns` and trims it. This means calling `compute()` twice with the same arguments (e.g., in a test assertion or if a caller retries on failure) will produce different rewards and corrupt the Sortino history. The `CustomReward` base class defines `compute()` as the primary method, but the internal helper performing state mutation without being clearly separated from the read path is a subtle bug surface.
- **Fix:** The mutation of `self._returns` should remain in `_sortino_increment()` (that is the right design for a per-step reward), but the method should be clearly documented as stateful:

```python
def _sortino_increment(self, prev_equity: float, curr_equity: float) -> float:
    """Delta of the rolling Sortino ratio. STATEFUL: appends to self._returns."""
```

This is a documentation warning, not a code change. The existing docstring does not signal statefulness, which may lead to test authors accidentally calling `compute()` multiple times in assertions and observing non-deterministic results.

---

## Suggestions (consider)

### S1 — `_volume_ratio_series()` warm-up inconsistency with other features

- **File:** `agent/strategies/regime/labeler.py:231`
- **Issue:** `_volume_ratio_series()` uses `period=20` matching Bollinger Bands and the volume SMA reference in `generate_training_data()`. However, the function starts producing non-NaN values from index `period-1 = 19` (i.e., the 20th candle), while `_adx_series()` and `_atr_series()` start at `period+1`. This means the NaN drop in `generate_training_data()` is always gated by the slowest indicator (ADX/ATR at ~index 21+), so `volume_ratio` never actually causes any additional rows to be dropped. This is correct behaviour, but worth noting in the function docstring for future maintainers.

### S2 — `KellyFractionalSizer.calculate_size()` returns `0.0` for no-edge case, bypassing `min_trade_pct`

- **File:** `agent/strategies/risk/sizing.py:565`
- **Issue:** The method deliberately returns `0.0` when Kelly is zero or negative (no edge), bypassing `min_trade_pct`. The docstring documents this: _"Returns 0.0 when the strategy has no edge (negative or zero Kelly fraction), which intentionally falls below min_trade_pct to signal 'do not trade'."_ This is intentional and correct. However, callers in `middleware.py` and `ensemble/run.py` must handle the `0.0` case explicitly — they should check `if final_size == 0.0: skip trade`. This is currently handled by the veto pipeline (size=0.0 from a no-edge Kelly result would be caught by `size_pct > 0.0` field constraint on `TradeSignal`), but it would be worth adding an explicit guard in `RiskMiddleware.execute_if_approved()` for clarity.

### S3 — `StrategyCircuitBreaker` TTL strategy for `LOSSES_LIST_TTL_SECONDS` is generous but not sliding

- **File:** `agent/strategies/ensemble/circuit_breaker.py:88`
- **Issue:** `LOSSES_LIST_TTL_SECONDS = 48 * 3600 + 3600` is set once per `record_outcome()` call via `pipe.expire(key, ...)`. This means the TTL is refreshed on every new loss/win record — effectively a sliding window. This is the correct behaviour for a rolling consecutive-loss window. However, this also means a strategy that gets exactly 3 consecutive losses and triggers a 24h pause could have its loss list expire before the pause expires (if no further outcomes are recorded), and then when it resumes, the count is back to 0. This is the intended behaviour (fresh start after pause), but it should be documented in the class docstring.

### S4 — `evolve.py` `compute_composite_fitness()` should validate weight constants against `CompositeReward` defaults

- **File:** `agent/strategies/evolutionary/evolve.py`
- **Issue:** The 5-factor fitness formula in `evolve.py` uses hardcoded weights (0.35, 0.25, -0.20, 0.10, 0.10). These are independent of the `CompositeReward` gym weights (0.4, 0.3, 0.2, 0.1). This is correct because the two operate in completely different contexts (battle-level fitness vs. per-step RL reward). However, a comment in `evolve.py` explaining the distinction would prevent future maintainers from assuming they should stay in sync.

### S5 — `middleware.py` `_error_decision()` constructs `VetoDecision` without `scale_factor`

- **File:** `agent/strategies/risk/middleware.py:932`
- **Issue:** The error `VetoDecision` is constructed without a `scale_factor` argument:

```python
veto = VetoDecision(
    action="VETOED",
    original_size_pct=signal.size_pct,
    adjusted_size_pct=0.0,
    reason=f"Pipeline error — trade blocked: {error}",
)
```

`VetoDecision.scale_factor` has `default=1.0`, so this is valid. But on an error path where no assessment was produced, `scale_factor=1.0` could be misleading (it implies no drawdown scaling was applied, when in reality nothing was assessed). The `assessment` created in `_error_decision()` has `verdict="HALT"`, which normally forces `scale_factor=0.0`. Consider passing `scale_factor=0.0` explicitly on the error `VetoDecision` to stay consistent with the HALT-verdict semantics.

---

## Passed Checks

- **Architecture / Dependency Direction:** All imports follow the strict chain. The `risk/` layer imports from `risk_agent` and `veto` but not from `ensemble/` or `rl/`. No upward imports observed.
- **Type Safety:** Full type annotations on all public functions and methods. `Decimal` used for all monetary values in `sizing.py` and `veto.py`. No bare `float` for money.
- **Async Patterns:** All I/O in `middleware.py` uses `async/await`. `asyncio.gather` used for concurrent candle fetches in `_check_correlation()`. No blocking calls in async paths.
- **Error Handling:** All external calls wrapped in `try/except`. Custom exceptions used where appropriate. `StrategyCircuitBreaker` fails open (returns `False`/`1.0`) on Redis errors — documented and correct. `RiskMiddleware` never raises; all errors surface in `ExecutionDecision.error`.
- **Security:** No hardcoded secrets. No f-strings in SQL (no DB calls in these modules). API keys read via `AgentConfig`/pydantic-settings, never from CLI args. `classifier.py` loads joblib only after SHA-256 checksum verification (`verify_checksum()`) — correct security posture for pickle deserialization.
- **Naming Conventions:** All files `snake_case.py`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`, private helpers `_prefix`. `SizingMethod` enum correct. `DrawdownTier`/`DrawdownProfile` data classes correct.
- **Composite Reward Logic:** `CompositeReward.compute()` correctly validates that weights sum to 1.0 in `__init__()`. Sortino window validation (`>= 2`) and activity bonus validation (`>= 0`) are both present. Division-by-zero guards in `_pnl_normalised()` (denominator floor at 1.0) and `_sortino_increment()` (epsilon for downside std = 1e-8) are correct.
- **Feature Engineering (Task 08):** `_volume_ratio_series()` correctly handles the zero-SMA case (returns `nan`, which is then dropped by the NaN filter in `generate_training_data()`). The 6-feature `FEATURE_NAMES` list in `RegimeClassifier.__init__()` matches the column order produced by `generate_training_data()` exactly.
- **Kelly Criterion (Task 16):** `calculate_kelly_fraction()` handles all edge cases: zero ratio → 0.0, zero win rate → 0.0, negative Kelly → 0.0. `HybridSizer` correctly falls back to the raw fractional Kelly when ATR or close price is zero.
- **Circuit Breaker Logic (Task 19):** The `record_pnl_contribution()` method correctly checks `already_paused` before triggering another pause (avoids resetting TTL on an existing pause). `filter_active_sources()` correctly returns a filtered list without side effects. `size_multiplier()` returns `1.0` when accuracy is `None` (insufficient data) — fail-open is correct here.
- **SDK Tools (Task 20):** The `_serialize_order()` helper correctly converts `Decimal` → str, datetime → ISO-8601, and preserves `None`. All 6 new tools (`place_limit_order`, `place_stop_loss`, `place_take_profit`, `cancel_order`, `cancel_all_orders`, `get_open_orders`) follow the same `log_api_call` / `AgentExchangeError` catch / `{"error": ...}` return pattern as the original 7 tools. The `get_sdk_tools()` factory return list correctly includes all 13 tools.
- **OOS Composite Fitness (Task 12):** The `EvolutionConfig` correctly defaults `fitness_fn` to `"composite"` and exposes `oos_split_ratio=0.30`. The fitness formula weights (0.35 sharpe + 0.25 profit_factor - 0.20 max_drawdown + 0.10 win_rate + 0.10 oos_sharpe) sum to 1.00 as specified.
- **Drawdown Profiles (Task 17):** `DrawdownProfile` validates at construction that tiers exist and that the first tier has `threshold=0.0`. `scale_factor()` correctly picks the highest-threshold tier whose threshold is exceeded by the current drawdown. `VetoDecision.scale_factor` field is correctly documented and passed through the pipeline.
- **Correlation Risk (Task 18):** `_check_correlation()` correctly deduplicates position symbols, skips self-correlation, uses `asyncio.gather(..., return_exceptions=True)` for concurrent fetching, falls back to pre-correlation size on any exception, and applies the 2× single-position exposure cap. `_pearson_correlation()` aligns on the most-recent `n` observations and returns 0.0 on degenerate inputs.
