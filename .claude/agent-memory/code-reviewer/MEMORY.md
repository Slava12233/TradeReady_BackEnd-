# Code Reviewer Agent Memory

## Project Conventions (always enforce)

**Financial values**
- `Decimal` required for ALL money/price/balance values — never `float`
- This extends to signal heuristics that compute on prices (e.g., SMA crossover helpers)
- Redis `INCRBYFLOAT` must receive `str(Decimal(...))`, not `float(...)` — float conversion causes precision drift that can bypass budget/exposure caps (security finding, CRITICAL-1 in `security-review-permissions.md`)
- Factory functions in tests accept strings ("10000.00000000") not floats

**Exception handling**
- Never bare `except:` — swallows `KeyboardInterrupt`/`SystemExit`
- Never `except Exception` for HTTP calls — narrow to `(httpx.HTTPStatusError, httpx.RequestError)`
- Keep `except Exception` only where LLM or pydantic-ai surfaces varied types
- All exceptions must inherit `TradingPlatformError` (src/utils/exceptions.py); `to_dict()` → `{"error": {"code", "message", "details"}}`

**Import order**
- stdlib → third-party → local (enforced by ruff isort)
- Lazy imports inside functions require `# noqa: PLC0415` — only valid for circular import avoidance, not convenience
- stdlib modules (e.g., `copy`) must not be lazy-imported

**Logging**
- All modules must use `structlog.get_logger(__name__)`, never stdlib `logging.getLogger`
- Applies to agent/ package and all src/ modules

**Pydantic v2**
- `output_type=` not `result_type=`; `.output` not `.data` — `result_type` is deprecated v1 API
- Frozen model mutation raises `ValidationError` or `TypeError` — test with `pytest.raises((ValidationError, TypeError))`, not bare `pytest.raises(Exception)`
- Bare `dict` in Field requires `dict[str, Any]` — mypy strict mode flags unparameterised `dict`

**Dependency direction** (never violate)
- Routes → Schemas + Services → Repositories + Cache + External clients → Models + Session
- Never import upward in this chain

**API design**
- All routes under `/api/v1/` prefix
- Error format: `{"error": {"code": "...", "message": "..."}}`
- Rate limit headers required on every response

**Naming**
- Files: `snake_case.py`, Classes: `PascalCase`, Functions: `snake_case`, Constants: `UPPER_SNAKE_CASE`, Private: `_prefix`
- Google-style docstrings on every public class and function

## Actual Issues Found Across Reviews (patterns to watch for)

**Critical issues found in production code:**
- Bare `except:` in gym `live_env.py` swallowed KeyboardInterrupt (review_2026-03-18)
- MCP `_call_api` crashed on 204/empty responses — `response.json()` called unconditionally (review_2026-03-18)
- React hook called inside `runIds.map(...)` loop — Rules of Hooks violation, runtime crash (review_2026-03-18)
- `globals.css` landing CSS extraction declared done but not actually removed — 1089 lines remained (review_2026-03-20)
- Zustand `selectPrice(symbol)` selector created on every render (new function reference), defeating memoization (review_2026-03-20)
- `redis.get(f"agent:memory:*:{memory_id}")` — Redis GET does not support glob patterns; always returns None (review_2026-03-22, Phase 0 Group A)
- `log_api_call()` `writer` parameter wired in tests but not in the actual function signature — 61 tests exercise code that does not exist (review_2026-03-22, Phase 0 Group A)
- `float(c.close)` in `handle_analyze()` and `float(p.unrealized_pnl)` in `handle_portfolio()` — monetary values cast to float, violating Decimal rule (review_2026-03-22, Phase 0 Group A)

**Warning-level patterns found repeatedly:**
- `except Exception` on pure HTTP calls without narrowing (multiple workflows)
- Missing `f` prefix on string literals inside multi-line f-string concatenation — silent template leak to LLM
- `steps_total` magic numbers without named constants (inconsistent across workflow files)
- Using deprecated pydantic-ai `result_type=` / `.data` instead of `output_type=` / `.output`
- Unparameterised `dict` in Pydantic fields → mypy strict failure
- Calling private method `client._get(...)` or `cache._get_redis()` from outside the class (encapsulation violation)
- stdlib `logging` instead of `structlog` (one file out of sync)
- Task descriptions may not match implementation — always verify the code, not just the task spec (Phase 0 Group A: 3 tasks had spec/implementation mismatches)

**Security findings (from security review reports):**
- `float(Decimal(...))` passed to Redis INCRBYFLOAT — precision drift allows budget cap bypass
- TOCTOU race on budget check vs. trade record (check-then-act without atomic lock)
- Fail-open default in enforcement (missing capability → allowed instead of denied)
- Default role too permissive (`TRADER` instead of `OBSERVER`)

## Known False Positive Patterns

- `# noqa: PLC0415` on lazy imports inside `src/dependencies.py` dependency functions — these are intentional to avoid circular imports, not laziness
- `# type: ignore[prop-decorator]` on `@computed_field @property` in pydantic-settings config — known pydantic v2 limitation
- `ANN` and `S` ruff rules are disabled for `tests/**/*.py` — no type annotations required on test functions
- `asyncio_mode = "auto"` in pyproject.toml means no `@pytest.mark.asyncio` needed — absence is correct
- `# noqa: BLE001` on `except Exception` in LLM steps where pydantic-ai raises varied types — legitimate suppression

## Review Report Format

Verdicts: `PASS`, `PASS WITH WARNINGS`, `NEEDS FIXES`
Report path: `development/code-reviews/review_YYYY-MM-DD_HH-MM_{scope}.md`
Sections: Critical Issues (must fix) → Warnings (should fix) → Suggestions (optional) → Passed Checks
- [feedback_redis_pipeline.md](feedback_redis_pipeline.md) — Redis pipeline must use `async with redis.pipeline() as pipe:` pattern
- [feedback_composite_weights.md](feedback_composite_weights.md) — Composite weight fields need cross-field sum validator in pydantic-settings configs
- [project_agent_strategies_patterns.md](project_agent_strategies_patterns.md) — Key patterns for agent/strategies/ code: Decimal, fail-open Redis, checksum on joblib, no CLI API keys
