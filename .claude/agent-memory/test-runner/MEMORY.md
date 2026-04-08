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

## Celery Stub Pattern for agent/tests/ (2026-03-23)

When testing `src/tasks/*.py` from `agent/tests/`, Celery is NOT installed. Use a sys.modules stub:
1. Create `_FakeCelery` with `.tasks` dict and `.conf` with `beat_schedule`/`task_routes`
2. Create `_FakeConf` with `.update(**kwargs)` method (celery_app calls `app.conf.update(...)`)
3. Inject into `sys.modules["celery"]`, `sys.modules["celery.schedules"]`, `sys.modules["kombu"]` at module level before any `src.tasks.*` import
4. Import `src.tasks.celery_app` first (registers beat_schedule), then `src.tasks.retrain_tasks` (fires `@app.task` decorators)
5. Test `_*_async` functions directly with `patch.multiple("agent.strategies.retrain", RetrainConfig=..., RetrainOrchestrator=...)`
6. For sync wrapper `duration_ms` tests, use `patch.object(rt, "_*_async", new=async_fn)` then call wrapper directly
7. `ANN401` allowed on stub `__init__`/`task` methods — use `*_args: object, **_kwargs: object` to avoid it

**Why:** Celery is a platform-side dependency, not in agent's pyproject.toml. Tests must use stubs.
**How to apply:** Any `agent/tests/` file testing `src/tasks/*.py` should copy this pattern.

## CapabilityManager ADMIN-Check Pattern (2026-03-30)

`grant_capability` and `revoke_capability` now require the grantor to have `ADMIN` role (added 2026-03-23, R2-01). Tests must:
1. Mock `get_role` on the manager to return `AgentRole.ADMIN` for the grantor: `patch.object(self.manager, "get_role", new=AsyncMock(return_value=AgentRole.ADMIN))`
2. For `revoke_capability`, pass an explicit `granted_by=revoker_id` (UUID string) — calling without `granted_by` now raises `PermissionDenied`
3. Import `AgentRole` inside the test: `from agent.permissions.roles import AgentRole`

## MCP Tool Count (last verified 2026-03-30)

`TOOL_COUNT = 58` (not 43). 15 strategy/training tools were added to `src/mcp/tools.py`:
- Strategy management (7): `create_strategy`, `get_strategies`, `get_strategy`, `create_strategy_version`, `get_strategy_versions`, `deploy_strategy`, `undeploy_strategy`
- Strategy testing (4): `run_strategy_test`, `get_test_status`, `get_test_results`, `compare_versions`
- Strategy recommendations (1): `get_strategy_recommendations`
- Training observation (3): `get_training_runs`, `get_training_run_detail`, `compare_training_runs`

`compare_training_runs` validates each run_id as a UUID. Use real UUIDs (e.g. `"550e8400-e29b-41d4-a716-446655440001"`) in tests, not short strings like `"run-1"`.

## Test Counts (last verified 2026-04-06)

- Unit tests: 74 files, 1751 tests (`tests/unit/`) — added `test_backtest_schemas.py` (9 tests), 6 sandbox tests to `test_backtest_sandbox.py`, 2 results tests to `test_backtest_results.py`

## QA Bugfix Sprint Patterns (2026-04-01)

Two recurring test breakage patterns introduced by the QA bugfix sprint:

**Pattern A — `reset_account` BUG-002 agent-awareness**: `AccountService.reset_account()` now fetches agents via `self._agent_repo.list_by_account()` before the write path. Tests calling `reset_account()` must mock:
1. `svc._agent_repo.list_by_account = AsyncMock(return_value=[mock_agent])` — where `mock_agent` has `.id` and `.starting_balance`
2. `svc._balance_repo.get_all_by_agent = AsyncMock(return_value=[...])` — replaces old `get_all`
3. `session.delete = AsyncMock()` — the loop calls `await session.delete(bal)` per balance row
Old pattern (`svc._balance_repo.get_all = AsyncMock(...)`) no longer works.

**Pattern B — `_upsert_position` BUG-011 fee argument**: `OrderEngine._upsert_position()` signature changed from `(account_id, symbol, side, fill_qty, fill_price, *, agent_id)` to `(account_id, symbol, side, fill_qty, fill_price, fee, *, agent_id)`. The `fee` is now a required positional argument. Tests must pass `fee=Decimal("60")` (or appropriate value) — missing it gives `TypeError: missing 1 required positional argument: 'fee'`.
- Integration tests: 24 files, 504 tests (`tests/integration/`)
- Frontend tests: 207 unit tests (`Frontend/tests/`)
- Agent package tests: 37 files (`agent/tests/`) — added `test_retrain_celery.py` (29 tests, 2026-03-23); previously added `test_redis_memory_cache.py`, `test_server_writer_wiring.py`, `test_server_handlers.py`, `test_security_regressions.py`
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

- `ANN` (type annotations) — disabled for `tests/**/*.py` (platform tests) BUT **enabled** for `agent/tests/` — all test methods need `-> None` return annotations and typed parameters
- `S` (security/bandit) — disabled for `tests/**/*.py`
- `agent/pyproject.toml` has no per-file-ignores, so `ANN` applies to `agent/tests/` fully

## File-to-Module Mapping Convention

Unit test files mirror source layout: `tests/unit/test_order_engine.py` → `src/order_engine/`
New tests go in `tests/unit/test_<module_name>.py`

## Agent Package Test Isolation Pattern

Agent tests use `monkeypatch` to set env vars and pass `_env_file=None` to `AgentConfig` to prevent reading a real `.env` during tests.

**Agent pytest quirk:** `agent/pyproject.toml` does not include `pytest-timeout`, so `--timeout=30` flag is rejected with exit code 4. Do not pass `--timeout` when running `agent/tests/`.

## Phase 0 Group A Wiring Pattern (2026-03-22)

`log_api_call()` in `agent/logging_middleware.py` accepts an optional keyword-only `writer: LogBatchWriter | None = None` parameter. When provided, a record dict with `channel`, `endpoint`, `method`, `latency_ms`, and error info is passed to `writer.add_api_call(record)` after the body completes (success or failure). Writer errors are always swallowed.

`AgentServer` in `agent/server.py` has a `batch_writer` property backed by `_batch_writer: LogBatchWriter | None`. The writer is created and started in `_init_dependencies()` when DB is available, and `writer.stop()` is called first in `_shutdown()` (before `_persist_state`) so buffered records are drained before closing connections. Writer stop errors are swallowed and logged.
## sa_inspect + MagicMock Pattern (2026-04-07)

`sa_inspect(obj)` raises `NoInspectionAvailable` when `obj` is a `MagicMock(spec=SomeOrmModel)`. Any route helper that calls `sa_inspect()` must wrap it in `try/except NoInspectionAvailable` and fall back to direct attribute access. The pattern:
```python
try:
    state = sa_inspect(battle)
    loaded = "participants" not in state.unloaded
except NoInspectionAvailable:
    loaded = True  # non-ORM object: treat attributes as accessible
```
**Why:** Integration tests mock ORM objects as `MagicMock(spec=Battle)` — SQLAlchemy can't inspect these.
**How to apply:** Any route helper using `sa_inspect` for lazy-load guarding needs this try/except.

## BattleLiveParticipantSchema Field Names (2026-04-07)

The new `BattleLiveParticipantSchema` (added in the battle live endpoint refactor) uses these required fields:
`current_equity`, `roi_pct`, `total_pnl`, `status` — NOT the old `equity`/`pnl`/`pnl_pct` names.
Integration test mocks for `get_live_snapshot` must use the new names. Also, the route must call
`BattleLiveParticipantSchema.model_validate(p)` on each raw dict from the service to satisfy mypy's
type check (service returns `list[dict]`, schema expects `list[BattleLiveParticipantSchema]`).

- [feedback_ann401_any_intentional.md](feedback_ann401_any_intentional.md) — ANN401 errors in ML strategy files are intentional and pre-existing
- [project_agent_tests_location.md](project_agent_tests_location.md) — agent/ tests are independent from tests/ and use their own conftest
- [feedback_f821_ensemble_run.md](feedback_f821_ensemble_run.md) — F821 undefined RiskMiddleware bug found and fixed in ensemble/run.py
