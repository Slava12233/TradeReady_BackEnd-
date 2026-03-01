---
name: testing-load-testing
description: |
  Teaches the agent how to implement and run tests for the AiTradingAgent crypto trading platform.
  Use when: adding unit/integration/load tests; configuring fixtures; or working with tests/ in this project.
---

# Testing & Load Testing

## Stack

- pytest + pytest-asyncio for unit and integration tests
- Locust for load testing
- Async fixtures for DB, Redis, test accounts

## Project Layout

| Purpose | Path |
|---------|------|
| Unit tests | `tests/unit/` |
| Integration tests | `tests/integration/` |
| Load tests | `tests/load/` |
| Shared fixtures | `tests/conftest.py` |
| Locust file | `tests/load/locustfile.py` |

## Run Commands

```bash
pytest tests/unit -v
pytest tests/integration -v
pytest tests/unit tests/integration -v
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

## Shared Fixtures (conftest.py)

- `db_session` — async DB session for tests; rollback or truncate after each test
- `redis_client` — async Redis client; flush or use isolated namespace per test
- `test_account` — account with known balance; seed via factory
- `mock_prices` — mock price feed for symbol(s); inject into Redis or mock

Use `@pytest.fixture` with `scope="function"` for isolation. Use `@pytest.fixture(scope="session")` only for expensive setup (e.g. DB schema).

## Unit Tests

Target: 90%+ coverage for core modules.

| Module | Tests | Focus |
|--------|-------|-------|
| Order engine | `test_order_engine.py` | Order creation, validation, execution flow |
| Slippage | `test_slippage.py` | Slippage calculation, bounds |
| Risk manager | `test_risk_manager.py` | Limits, daily loss, position checks |
| Balance manager | `test_balance_manager.py` | Lock/unlock, balance updates |
| Portfolio metrics | `test_portfolio_metrics.py` | PnL, returns, metrics |
| Auth | `test_auth.py` | API key, JWT validation |

- Mock external dependencies (Redis, DB) where appropriate.
- Use factory pattern for test data (e.g. `create_account()`, `create_order()`).
- Use `pytest.mark.asyncio` for async tests.

## Integration Tests

| Test | Flow | Purpose |
|------|------|---------|
| `test_full_trade_flow` | register → fund → buy → sell → check PnL | End-to-end trade lifecycle |
| `test_price_ingestion` | Ingest ticks → verify DB/Redis | Price pipeline |
| `test_websocket` | Connect → subscribe → receive updates | WS connectivity |
| `test_api_endpoints` | Hit protected endpoints with auth | API auth and responses |

- Use real or test containers (DB, Redis) for integration.
- Clean state between tests; avoid shared mutable state.
- Use `httpx.AsyncClient` for API calls against test app.

## Load Testing (Locust)

### Targets

- 50 concurrent agents (simulated users)
- ~400 req/s total throughput
- Zero errors under load

### Performance Targets

| Metric | Target |
|--------|--------|
| p50 latency | < 50ms |
| p95 latency | < 100ms |
| p99 latency | < 200ms |
| Error rate | 0% |

### WebSocket Load

- 500 concurrent WebSocket connections
- Price update latency < 100ms from publish to client receive

### Locustfile Structure

- Define `HttpUser` or `User` classes for API/WS behavior.
- Use `@task` decorator for weighted tasks (e.g. 70% read, 30% write).
- Use `on_start` for auth/setup per user.
- Use `wait_time` for think time between requests.

## Factory Pattern for Test Data

```python
def create_account(balance: float = 10000.0, **kwargs) -> Account:
    ...

def create_order(account_id: str, symbol: str = "BTCUSDT", **kwargs) -> Order:
    ...
```

- Use `factory_boy` or plain factory functions.
- Override only needed fields; use sensible defaults.

## Async Fixtures

- Use `async def` fixtures for DB/Redis setup.
- Use `asyncio.run()` or `pytest-asyncio` for async test execution.
- Ensure teardown runs (e.g. `yield` in fixture, cleanup in finally).

## Conventions

- Prefix test files with `test_`; prefix test functions with `test_`.
- Use `pytest.mark.parametrize` for multiple inputs.
- Use `pytest.raises` for expected exceptions.
- Keep tests fast; mock slow or external calls in unit tests.
- Use `pytest -x` to stop on first failure during development.
- Do not commit secrets; use env vars or test config for credentials.

## References

- For detailed test case specifications, see [references/test-cases.md](references/test-cases.md)
