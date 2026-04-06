---
name: battle_not_found_error_pattern
description: The battle_repo.py defined a local BattleNotFoundError(Exception) that caused INTERNAL_ERROR 500 instead of 404 — must use TradingPlatformError subclasses in repos
type: feedback
---

## Rule
Never define local `*Error(Exception)` classes in repository modules. Always import from `src.utils.exceptions` so that exceptions inherit from `TradingPlatformError` and are properly serialized by the global exception handler.

**Why:** The local `BattleNotFoundError(Exception)` in `battle_repo.py` was a plain Python exception, not a `TradingPlatformError`. When `get_battle()` raised it for a non-existent battle ID, it propagated through the service layer (which didn't catch it), through the route handler, and was caught by the generic `Exception` handler in `main.py` — returning `{"error": {"code": "INTERNAL_ERROR", ...}}` with HTTP 500 instead of the correct HTTP 404 `BATTLE_NOT_FOUND` response.

**How to apply:** 
- When a repo raises a "not found" error, always use the `BattleNotFoundError`, `BacktestNotFoundError`, etc. from `src.utils.exceptions` (these map to HTTP 404).
- If a repo needs to re-export the exception for existing callers that `from repo_module import NotFoundError`, add a module-level `__all__` with the re-export but import from `src.utils.exceptions`.
- Also catch `(TypeError, ValueError)` after `except SQLAlchemyError` in JSONB-writing methods — asyncpg raises these (not SQLAlchemyError) when a dict contains non-JSON-serializable Python objects.
