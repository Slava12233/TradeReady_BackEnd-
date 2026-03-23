---
name: agent_strategies_patterns
description: Established patterns in agent/strategies/ that must be preserved across all reviews
type: project
---

Key patterns confirmed correct in Phase 1-2 review (Tasks 08, 10, 12, 16, 17, 18, 19, 20):

- **Decimal for money:** All position sizes, fractions, and monetary values in `risk/sizing.py`, `risk/veto.py`, `risk/middleware.py` use `decimal.Decimal` internally; converted to `float` only at JSON output.
- **Fail-open Redis:** `StrategyCircuitBreaker` returns `False`/`1.0`/`None` on `RedisError` — never blocks trading on Redis outage.
- **Checksum security:** `RegimeClassifier.load()` runs `verify_checksum()` before `joblib.load()` — always verify before pickle deserialization.
- **No CLI API keys:** API keys come from `agent/.env` via `AgentConfig`, never from `--api-key` CLI arguments.
- **Lazy imports with noqa:** All optional/heavy imports (`xgboost`, `sklearn`, `torch`, `joblib`, `httpx`) use `# noqa: PLC0415` inside functions.
- **Non-crashing middleware:** `RiskMiddleware.process_signal()` wraps every stage in try/except; callers always receive a valid `ExecutionDecision`.
- **`asyncio.gather` for concurrent fetches:** `_check_correlation()` fetches candles for all symbols concurrently via `asyncio.gather(..., return_exceptions=True)`.
- **`_serialize_order()` helper:** All SDK order-returning tools use this shared helper for consistent Decimal-to-str and datetime-to-isoformat conversion.

**Why:** These patterns are load-bearing for correctness, security, and the agent's non-crashing guarantee.
