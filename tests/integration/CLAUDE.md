# Integration Tests

<!-- last-updated: 2026-04-06 -->

> End-to-end and API-level tests for every REST endpoint, WebSocket, and the backtesting/battle engines, using either mocked infrastructure or real Docker services.

## What This Module Does

Integration tests verify the full request-response cycle through the FastAPI application: middleware (auth, rate limiting, logging), route handlers, dependency injection, Pydantic validation, and error serialization. Two distinct patterns exist:

1. **Mocked-infra tests** (majority): Use `FastAPI TestClient` (sync) with `app.dependency_overrides` and `unittest.mock.patch` to replace DB, Redis, and service layers. No Docker required.
2. **Docker-dependent tests** (backtest E2E group): Use `httpx.AsyncClient` with `app=create_app()` against real TimescaleDB and Redis. Marked `pytest.mark.integration` and `pytest.mark.slow`; skip automatically when no historical data is available.

## Test Inventory

| File | Tests | What It Covers |
|------|-------|----------------|
| `test_account_endpoints.py` | 11 | Account info, settings, balance endpoints |
| `test_agent_backtest_workflow.py` | 1 | Multi-backtest compare/best/mode-switch workflow (Docker) |
| `test_agent_connectivity.py` | 24 | Agent API key auth, connectivity checks |
| `test_agent_endpoints.py` | 30 | Agent CRUD, clone, reset, archive, delete, regenerate-key |
| `test_agent_scoped_backtest.py` | 1 | Two agents under one account; backtest list isolation (Docker) |
| `test_analytics_endpoints.py` | 8 | Analytics/portfolio summary endpoints |
| `test_auth_endpoints.py` | 31 | Register (happy + validation + duplicate), login (JWT, expired, wrong secret, suspended), bearer auth on protected routes |
| `test_backtest_api.py` | 9 | Backtest endpoint validation: auth required, invalid inputs, error format, list/best/mode |
| `test_backtest_e2e.py` | 1 | Full backtest lifecycle: create, start, step, order, batch step, cancel, results, equity curve, trade log (Docker) |
| `test_battle_endpoints.py` | 30 | All 20 battle REST endpoints: CRUD, participants, lifecycle (start/pause/resume/stop), live metrics, results, replay, historical step/batch/order/prices |
| `test_strategy_api.py` | 8 | Strategy REST endpoints: CRUD, versions, deploy/undeploy, owner isolation |
| `test_strategy_test_flow.py` | 5 | Strategy test flow: start test, list, get results, cancel, compare versions |
| `test_training_api.py` | 6 | Training API: register run, report episode, complete, list, learning curve, compare |
| `test_battle_websocket.py` | 8 | Battle WebSocket channel subscriptions and events |
| `test_concurrent_backtests.py` | 1 | 5 concurrent backtests with independent results (Docker) |
| `test_full_trade_flow.py` | 5 | Full trading flow: order placement through execution |
| `test_historical_battle_e2e.py` | 5 | Historical battle lifecycle (all currently skipped -- placeholder for CI with DB) |
| `test_ingestion_flow.py` | 10 | Price ingestion pipeline: tick buffer, flush, candle aggregation |
| `test_market_endpoints.py` | 65 | Market data endpoints: prices, tickers, candles, order book, data-range |
| `test_no_lookahead.py` | 1 | Candle timestamps never exceed virtual clock during backtest (Docker) |
| `test_rate_limiting.py` | 56 | Rate limit middleware: per-endpoint limits, headers, 429 responses, reset timing |
| `test_trading_endpoints.py` | 87 | All trading endpoints: place order (market/limit/stop/TP), get/list/cancel orders, trade history, validation, error codes |
| `test_real_user_scenario_e2e.py` | 52 | Full realistic user scenario: register, create agents, place trades, backtests, battles, analytics, account management (Docker) |
| `test_websocket.py` | 49 | WebSocket connect/disconnect, subscribe/unsubscribe, ticker/candle/order/portfolio channels, heartbeat, subscription cap, Redis bridge |
| `test_agent_ecosystem_phase1.py` | 28 | Agent ecosystem Phase 1 E2E: session creation, memory store, conversation history, context assembly, intent routing, DB persistence |
| `test_agent_ecosystem_phase2.py` | 22 | Agent ecosystem Phase 2 E2E: permissions enforcement, budget limits, capability grants, audit logging, trading loop integration |

**Total: ~554 test functions across 26 files.**

## Setup & Dependencies

### Mocked-infra tests (no Docker needed)

Most test files construct their own `TestClient` via a local `_build_client()` helper that:

1. Patches lifespan hooks: `init_db`, `close_db`, `get_redis_client`, `start_redis_bridge`, `stop_redis_bridge`, `ConnectionManager.disconnect_all`
2. Calls `create_app()` inside the patched context
3. Uses `app.dependency_overrides` to replace: `get_settings`, `get_db_session`, `get_redis`, and the relevant service dependency (e.g., `get_account_service`, `get_battle_service`, `get_order_engine`)
4. Patches `_authenticate_request` in `src.api.middleware.auth` to inject a mock `Account` (bypassing real auth)

Each file defines its own `_TEST_SETTINGS` instance with safe defaults (fake DB URL, fake Redis URL, test JWT secret).

### Docker-dependent tests (backtest E2E group)

Files: `test_backtest_e2e.py`, `test_backtest_api.py`, `test_no_lookahead.py`, `test_concurrent_backtests.py`, `test_agent_backtest_workflow.py`, `test_agent_scoped_backtest.py`

These use `httpx.AsyncClient(app=create_app(), base_url="http://test")` and hit real services. They:
- Register a fresh account via `POST /api/v1/auth/register`
- Check `GET /api/v1/market/data-range` and skip if `total_pairs == 0`
- Require running TimescaleDB with historical candle data and Redis

Marked with: `pytestmark = [pytest.mark.integration, pytest.mark.slow]`

### Shared fixtures (`tests/conftest.py`)

The root conftest provides factory functions and mock fixtures used by both unit and integration tests:
- `test_settings` -- patches `get_settings()` lru_cache with safe values
- `make_tick()`, `sample_tick`, `sample_ticks` -- Tick namedtuple factories
- `make_account()`, `make_agent()`, `make_order()`, `make_trade()`, `make_battle()`, `make_balance()` -- ORM model factories
- `mock_asyncpg_pool`, `mock_redis`, `mock_db_session`, `mock_price_cache` -- pre-wired async mocks

There is no `conftest.py` inside `tests/integration/` itself; each file is self-contained.

## App Factory Pattern

All tests use the app factory. Two variants:

### Variant 1: Sync `TestClient` (mocked infra)

Used by `test_auth_endpoints.py`, `test_trading_endpoints.py`, `test_market_endpoints.py`, `test_battle_endpoints.py`, `test_websocket.py`, `test_rate_limiting.py`, and others.

```python
from src.main import create_app

# Inside patched context to suppress lifespan hooks:
with patch("src.database.session.init_db", new_callable=AsyncMock), ...:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS
    app.dependency_overrides[get_db_session] = _override_db
    # ...
    client = TestClient(app, raise_server_exceptions=False)
```

### Variant 2: Async `httpx.AsyncClient` (Docker services)

Used by `test_backtest_e2e.py`, `test_no_lookahead.py`, `test_concurrent_backtests.py`, `test_agent_backtest_workflow.py`, `test_agent_scoped_backtest.py`.

```python
from src.main import create_app

@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c
```

No dependency overrides -- the app uses real DB and Redis connections.

## Common Tasks

### Adding a new integration test

1. **Choose your pattern**: If the test needs real DB data (backtest replay, historical prices), use the async `httpx.AsyncClient` pattern with Docker. Otherwise, use the sync `TestClient` with mocked infra.

2. **For mocked-infra tests**:
   - Copy the `_build_client()` pattern from a similar file (e.g., `test_auth_endpoints.py` for auth, `test_battle_endpoints.py` for battles)
   - Define `_TEST_SETTINGS` at module level
   - Mock the specific service your endpoints depend on
   - Patch `_authenticate_request` to bypass auth middleware, or leave it unpatched to test auth behavior

3. **For Docker-dependent tests**:
   - Use the `client` and `auth_headers` fixture pattern from `test_backtest_e2e.py`
   - Always check data availability and `pytest.skip()` if no historical data
   - Mark with `pytestmark = [pytest.mark.integration, pytest.mark.slow]`

4. **Auth in tests**:
   - Mocked: Patch `_authenticate_request` to return `(mock_account, None)` for authenticated, `(None, None)` for unauthenticated
   - Docker: Register via `POST /api/v1/auth/register`, use the returned `api_key` in `X-API-Key` header
   - JWT tests: Use `create_jwt()` from `src.accounts.auth` with `_TEST_JWT_SECRET`

5. **Asserting error responses**: Verify the standard error envelope `{"error": {"code": "...", "message": "..."}}` and the correct HTTP status code.

### Running integration tests

```bash
# All integration tests (mocked ones run without Docker)
pytest tests/integration/ -v

# Only Docker-dependent tests (requires running services)
pytest tests/integration/ -v -m "integration and slow"

# Single file
pytest tests/integration/test_auth_endpoints.py -v

# Skip slow tests
pytest tests/integration/ -v -m "not slow"
```

## Gotchas & Pitfalls

- **No shared `conftest.py` in this directory**: Each test file builds its own client and mocks. This means duplicated `_build_client()` helpers across files. When changing the app factory or middleware, you may need to update multiple files.

- **`_authenticate_request` patch must stay active**: The auth middleware calls `_authenticate_request` at request time (not app creation time). The battle endpoint tests use `patch.start()`/`patch.stop()` instead of context managers, and have an `autouse` fixture calling `patch.stopall()` to clean up.

- **`raise_server_exceptions=False`**: Most `TestClient` instances are created with this flag so that 500 errors return as HTTP responses rather than raising exceptions in the test. This is intentional -- tests assert on status codes.

- **Docker tests skip gracefully**: All Docker-dependent tests check `data_range["total_pairs"]` and call `pytest.skip()` if zero. They will not fail in CI without infrastructure.

- **`test_historical_battle_e2e.py` is all skipped**: Every test in this file calls `pytest.skip("Requires running database with historical data")`. It serves as a placeholder.

- **`get_settings()` lru_cache**: The settings object is cached. Mocked tests create `_TEST_SETTINGS` directly and inject via `dependency_overrides[get_settings]`, bypassing the cache. If you import `get_settings()` at module level in test code, you may get the real (cached) settings instead.

- **Redis pipeline mocks**: The rate limit middleware uses `async with redis.pipeline() as pipe:`. The mock must wire up `__aenter__`/`__aexit__` on the pipeline object, plus sync `incr`/`expire` methods (pipeline commands are sync; only `execute()` is async).

- **Battle exception hierarchy unified (2026-03-18)**: The duplicate `BattleInvalidStateError` in `src.battles.service` was removed. Only `src.utils.exceptions.BattleInvalidStateError` exists now, mapping correctly to HTTP 409.

- **Backtest tests create real accounts**: The Docker-dependent backtest tests register accounts via the API. If the DB is not clean between runs, you may get `DuplicateAccountError`. Each test uses a unique `display_name` to mitigate this.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
- `2026-03-18` -- Updated battle exception gotcha (duplicate class removed). Fixed lint: E402 in test_auth_endpoints, N801 suppressed in test_real_user_scenario_e2e.
- `2026-03-18` -- Added `test_real_user_scenario_e2e.py` (52 tests) to inventory table. Total remains ~504 tests across 24 files (table sum verified).
- `2026-03-19` -- Synced with codebase: confirmed 24 test files, 504 test functions (grep verified). All inventory entries match files on disk.
- `2026-04-06` — Added `test_agent_ecosystem_phase1.py` (28 tests) and `test_agent_ecosystem_phase2.py` (22 tests) for agent ecosystem integration. File count: 24 → 26. Total: ~554 tests.
- `2026-03-20` — Verified: still 24 test files on disk. No new integration test files added this session.
