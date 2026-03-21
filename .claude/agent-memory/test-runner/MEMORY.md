# Test Runner Agent Memory

## Core Infrastructure (read before running any tests)

**Key config files**
- `pyproject.toml` — `asyncio_mode = "auto"` set; no `@pytest.mark.asyncio` needed or wanted (double-wrapping issue)
- `tests/conftest.py` — shared fixtures + ORM factory functions
- `tests/CLAUDE.md` — canonical fixture inventory, gotchas, running instructions

**App factory rule**
- Integration tests: always `from src.main import create_app; app = create_app()`
- Never `from src.main import app` — middleware and dependencies won't be initialized

**`get_settings()` lru_cache gotcha**
- `get_settings()` caches on first call — tests MUST patch `src.config.get_settings` before the cached instance is created
- The `test_settings` fixture in conftest handles this correctly; always use it, never construct `Settings` manually

## Test Counts (last verified 2026-03-21)

- Unit tests: 72 files, 1203 tests (`tests/unit/`) — added `test_agent_api_call_repo.py` (9 tests), `test_agent_strategy_signal_repo.py` (10 tests)
- Integration tests: 24 files, 504 tests (`tests/integration/`)
- Frontend tests: 207 unit tests (`Frontend/tests/`)
- Agent package tests: 32 files (`agent/tests/`) — added `test_logging_writer.py` (17 tests)
- Agent strategy tests: 578 tests (`agent/strategies/`)

**Pre-existing failures in `agent/tests/` (245 total, as of 2026-03-21):**
- `test_regime.py` — ImportError: `_print_evaluation` removed from `classifier.py`; skip with `--ignore=agent/tests/test_regime.py`
- `test_veto.py` — 29 failures (pre-existing, unrelated to logging)
- `test_memory_retrieval.py` — some failures (pre-existing)
- These are NOT caused by new test additions; `test_logging.py` has 0 failures

## Mock Wiring Patterns (conftest.py)

**Async vs sync mocks**
- Async DB/Redis methods → `AsyncMock`
- `session.add()` → `MagicMock` (synchronous in SQLAlchemy, even with async sessions)
- `asyncpg_pool.acquire()` → `MagicMock` with `__aenter__`/`__aexit__` as `AsyncMock`
- `redis.pipeline()` → mock pipeline where `hset`/`publish` are sync `MagicMock`, `execute` is `AsyncMock`
- `session.begin_nested()` → async context manager mock

**Wiring a mock DB query result**
```python
mock_result = MagicMock()
mock_result.scalars.return_value.first.return_value = make_account()
mock_db_session.execute.return_value = mock_result
```

## ORM Factory Functions (plain functions, not fixtures)

Import directly: `from tests.conftest import make_account`

| Factory | Key Defaults |
|---------|-------------|
| `make_tick()` | BTCUSDT, price=64521.30 |
| `make_account()` | balance=10000, status=active |
| `make_agent()` | starting_balance=10000 |
| `make_order()` | BTCUSDT market buy, qty=0.01 |
| `make_trade()` | BTCUSDT buy, price=50000 |
| `make_battle()` | draft, live mode, 60min |
| `make_balance()` | 10000 USDT available |

All auto-generate UUIDs via `uuid4()`. Pass the same UUID explicitly to both factories when testing FK relationships.

## estimate_llm_cost Substring-Match Gotcha

`estimate_llm_cost("", ...)` returns non-zero (matches first pricing table entry) because `"" in key` is always True in Python. Do not assert `== 0.0` for empty string; assert `> 0.0` or document the implementation-defined behavior.

## Common Test Failure Patterns

- `lru_cache` not patched → real `.env` or stale config bleeds into test
- `AsyncMock` on `session.add()` → runtime error (it's sync)
- `@pytest.mark.asyncio` added → double-wrapping causes "coroutine never awaited" or fixture errors
- `app` imported directly instead of `create_app()` → middleware missing, dependency injection broken
- `float` used in financial assertions → rounding mismatch; use `Decimal` and `NUMERIC(20,8)` precision
- `pytest.raises(Exception)` on frozen Pydantic model mutation → too broad; use `(ValidationError, TypeError)`

## Test Markers

- `@pytest.mark.slow` — full app startup or >5s tests; skip with `pytest -m "not slow"`
- `@pytest.mark.celery` — Celery task tests; run with `pytest -m celery`

## Ruff Rules for Tests

- `ANN` (type annotations) — disabled for `tests/**/*.py`
- `S` (security/bandit) — disabled for `tests/**/*.py`
- No type annotations needed on test functions

## File-to-Module Mapping Convention

Unit test files mirror source layout: `tests/unit/test_order_engine.py` → `src/order_engine/`
New tests go in `tests/unit/test_<module_name>.py`

## Agent Package Test Isolation Pattern

Agent tests use `monkeypatch` to set env vars and pass `_env_file=None` to `AgentConfig` to prevent reading a real `.env` during tests.

**Agent pytest quirk:** `agent/pyproject.toml` does not include `pytest-timeout`, so `--timeout=30` flag is rejected with exit code 4. Do not pass `--timeout` when running `agent/tests/`.
