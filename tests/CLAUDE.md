# Tests

<!-- last-updated: 2026-03-17 -->

> Shared fixtures, factory functions, and conventions for all unit and integration tests.

## What This Module Does

The `tests/` directory contains all automated tests for the trading platform. Tests are split into two categories: **unit tests** (mock all external dependencies) and **integration tests** (use the FastAPI app factory and may require Docker services). A shared `conftest.py` at the top level provides mock infrastructure and ORM model factories used by both.

## Key Files

| File | Purpose |
|------|---------|
| `conftest.py` | Shared fixtures: mock DB session, mock Redis, mock price cache, ORM factories, test settings |
| `unit/` | 60+ unit test files; each tests a single module in isolation with mocks |
| `integration/` | 21 integration test files; test API endpoints, E2E workflows, WebSocket, backtesting flows |
| `__init__.py` | Empty package marker (exists at `tests/`, `tests/unit/`, `tests/integration/`) |

## Architecture & Patterns

### Unit vs Integration

- **Unit tests** (`tests/unit/`): Mock all external dependencies (DB, Redis, Binance). Test one class or function at a time. File naming mirrors source layout, e.g. `test_order_engine.py` tests `src/order_engine/`.
- **Integration tests** (`tests/integration/`): Use the FastAPI app factory (`from src.main import create_app; app = create_app()`) to spin up a real ASGI app with `httpx.AsyncClient`. May require Docker services (TimescaleDB, Redis) for full E2E flows.

### Async-First

- `asyncio_mode = "auto"` is set in `pyproject.toml` -- you do **not** need `@pytest.mark.asyncio` on async test functions.
- The `event_loop_policy` fixture (session-scoped) uses `asyncio.DefaultEventLoopPolicy`.
- `pytest_plugins = ("pytest_asyncio",)` is declared in `conftest.py`.

### Mock Wiring Conventions

All mocks follow a consistent pattern:

- **Async methods** use `AsyncMock` (e.g., `session.execute`, `redis.hget`).
- **Sync methods** that return async context managers use `MagicMock` with `__aenter__`/`__aexit__` wired as `AsyncMock`. This is critical for:
  - `asyncpg_pool.acquire()` -- returns an async context manager wrapping a mock connection.
  - `redis.pipeline()` -- returns a mock pipeline where `hset`/`publish` are sync `MagicMock` but `execute` is `AsyncMock`.
  - `session.begin_nested()` -- returns a mock nested transaction context manager.
- **`session.add`** is `MagicMock` (sync), not `AsyncMock`, because SQLAlchemy's `session.add()` is synchronous.

### Factory Functions (not fixtures)

The conftest exposes plain functions (not fixtures) for building ORM model instances:

| Factory | Returns | Key Defaults |
|---------|---------|--------------|
| `make_tick()` | `Tick` namedtuple | BTCUSDT, price=64521.30 |
| `make_account()` | `Account` ORM model | balance=10000, status=active |
| `make_agent()` | `Agent` ORM model | starting_balance=10000 |
| `make_order()` | `Order` ORM model | BTCUSDT market buy, 0.01 qty |
| `make_trade()` | `Trade` ORM model | BTCUSDT buy, price=50000 |
| `make_battle()` | `Battle` ORM model | draft, live mode, 60min |
| `make_balance()` | `Balance` ORM model | 10000 USDT available |

All factories auto-generate UUIDs via `uuid4()` but accept overrides for deterministic tests. Import them directly: `from tests.conftest import make_account`.

## Test Fixtures (conftest.py)

### `test_settings`
Returns a `Settings` instance with safe defaults (fake DB/Redis URLs, short buffers). Patches `src.config.get_settings` to bypass the `lru_cache` -- critical because the real `get_settings()` caches on first call.

### `sample_tick` / `sample_ticks`
Pre-built `Tick` namedtuples. `sample_ticks` returns 3 ticks across BTCUSDT and ETHUSDT.

### `mock_asyncpg_pool`
Mock asyncpg `Pool` with a working `acquire()` async context manager. The inner connection has `copy_records_to_table` as an `AsyncMock` for `TickBuffer` tests.

### `mock_redis`
Mock `redis.asyncio.Redis` with all common commands pre-wired:
- `hset`, `hget`, `hgetall`, `publish` as `AsyncMock`
- `register_script` as `MagicMock` returning an `AsyncMock` script
- `pipeline()` returning a mock pipeline with sync `hset`/`publish` and async `execute`

### `mock_db_session`
Mock `AsyncSession` with `execute`, `flush`, `commit`, `rollback`, `refresh` (all `AsyncMock`), `add` (`MagicMock`), and `begin_nested` returning an async context manager.

### `mock_price_cache`
Mock `PriceCache` with `get_price`, `set_price`, `get_all_prices`, `update_ticker` as `AsyncMock`.

## Running Tests

```bash
# All tests with coverage
pytest --cov=src --cov-report=html

# Unit tests only
pytest tests/unit/

# Integration tests only (may need Docker services)
pytest tests/integration/

# Single file
pytest tests/unit/test_order_engine.py

# Single test function
pytest tests/unit/test_order_engine.py::test_market_buy_fills

# Skip slow tests
pytest -m "not slow"

# Only Celery task tests
pytest -m celery
```

Coverage is configured via `addopts` in `pyproject.toml` and runs automatically.

## Common Tasks

### Adding a new unit test

1. Create `tests/unit/test_<module_name>.py`.
2. Import factories from `tests.conftest` (e.g., `from tests.conftest import make_order`).
3. Use fixtures from conftest (`mock_db_session`, `mock_redis`, etc.) as function parameters.
4. Write async test functions -- no `@pytest.mark.asyncio` needed.
5. Mock external dependencies; never hit real Redis/DB in unit tests.
6. Run `ruff check tests/unit/test_<module_name>.py` -- `ANN` and `S` rules are disabled for test files.

### Adding a new integration test

1. Create `tests/integration/test_<feature>.py`.
2. Use the app factory: `from src.main import create_app; app = create_app()`.
3. Create an `httpx.AsyncClient` with the ASGI transport for API endpoint tests.
4. If the test needs Docker services, consider marking it `@pytest.mark.slow`.

### Wiring a mock DB query result

```python
async def test_repo_get(mock_db_session):
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = make_account()
    mock_db_session.execute.return_value = mock_result
    # ... call your repo method with mock_db_session
```

## Gotchas & Pitfalls

1. **`get_settings()` uses `lru_cache`** -- Tests must patch `src.config.get_settings` *before* the cached instance is created, or they will get the real config. The `test_settings` fixture handles this correctly; use it instead of constructing `Settings` manually.

2. **Redis pipeline mock** -- Inside a real pipeline, `hset`/`publish` are synchronous (only `execute()` is awaited). The `mock_redis` fixture mirrors this: pipeline methods are `MagicMock`, not `AsyncMock`. If your code uses `async with redis.pipeline() as pipe:`, both `__aenter__` and `__aexit__` must be `AsyncMock` on the pipeline object.

3. **`session.add` is sync** -- SQLAlchemy's `session.add()` is synchronous even with async sessions. The `mock_db_session` fixture correctly uses `MagicMock` for `add`. Do not change it to `AsyncMock`.

4. **`asyncio_mode = "auto"`** -- Do not add `@pytest.mark.asyncio` decorators. They are unnecessary and may cause double-wrapping issues with pytest-asyncio.

5. **Decimal, never float** -- All money/price values use `Decimal`. Factory functions accept strings (`"10000.00000000"`) to avoid float precision issues. Follow this pattern in new tests.

6. **Factory functions vs fixtures** -- `make_tick`, `make_account`, `make_agent`, `make_order`, `make_trade`, `make_battle`, `make_balance` are plain functions, not fixtures. Import and call them directly. Only `sample_tick` and `sample_ticks` are fixtures wrapping `make_tick`.

7. **Integration tests need `create_app()`** -- Never import `app` directly from `src.main`. Always use the factory `create_app()` so middleware and dependencies are properly initialized.

8. **Ruff rules relaxed for tests** -- `ANN` (type annotations) and `S` (security/bandit) rules are skipped for `tests/**/*.py` in `pyproject.toml`. You do not need type annotations on test functions.

9. **Custom markers** -- Two markers are registered: `slow` (full app startup or >5s) and `celery` (Celery task tests). Use `pytest -m "not slow"` to skip heavy tests during rapid iteration.

10. **UUIDs in factories** -- All factory functions auto-generate UUIDs but accept overrides. When testing relationships between models (e.g., an order belonging to an agent), pass the same UUID explicitly to both factories to ensure FK consistency.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
