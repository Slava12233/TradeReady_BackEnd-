# agent/tests — Agent Package Unit Tests

<!-- last-updated: 2026-03-20 -->

> Unit tests for the `agent` package. All external dependencies are mocked; no running platform or LLM is required.

## What This Module Does

Provides isolated unit tests for the agent's configuration, output models, and tool factories. Tests cover field validation, error handling contracts, HTTP request shapes, and factory structure — not workflow orchestration or LLM behaviour. The test suite is independent of the main platform test suite in `tests/` and does not use the platform's `conftest.py` or app factory.

## Key Files

| File | Purpose |
|------|---------|
| `test_models.py` | 54 tests — all 6 Pydantic output models: field validation, boundaries, immutability, round-trips |
| `test_config.py` | 13 tests — `AgentConfig` field defaults, required fields, env var overrides, computed fields |
| `test_sdk_tools.py` | 24 tests — `get_sdk_tools()` factory structure and all 7 tool function behaviours |
| `test_rest_tools.py` | 26 tests — `PlatformRESTClient` methods and `get_rest_tools()` factory structure |
| `__init__.py` | Empty package marker |

Total: **117 tests**.

## Patterns

### Running the tests

```bash
# Run all agent tests
pytest agent/tests/ -v

# Run a specific file
pytest agent/tests/test_models.py -v

# With coverage (from repo root)
pytest agent/tests/ --cov=agent --cov-report=term-missing
```

`asyncio_mode = "auto"` is set in `agent/pyproject.toml` — no `@pytest.mark.asyncio` decorator is needed on async test methods.

### Mocking — SDK tools (`test_sdk_tools.py`)

`AsyncAgentExchangeClient` is patched at the module level with `unittest.mock.patch`:

```python
with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
    from agent.tools.sdk_tools import get_sdk_tools
    tools = get_sdk_tools(config)
```

The mock client is an `AsyncMock()` so all `await client.*()` calls resolve to configurable return values. SDK response objects (price, candle, balance, etc.) are `MagicMock()` instances with the relevant attributes set as `Decimal` values.

### Mocking — REST tools (`test_rest_tools.py`)

`httpx.AsyncClient` is patched to return a mock that provides `.get()` and `.post()` as `AsyncMock`. The `_mock_response()` helper builds a mock `httpx.Response` that returns the desired JSON and calls `raise_for_status()` as a no-op (2xx) or raises `httpx.HTTPStatusError` (4xx/5xx).

### Mocking — config (`test_config.py`)

`monkeypatch.setenv()` is used to inject environment variables. `AgentConfig(_env_file=None)` bypasses the `agent/.env` file so tests do not depend on a physical `.env` file being present or absent.

### Test organisation

Each test file uses a class-per-subject structure (e.g. `TestTradeSignal`, `TestGetSdkToolsStructure`, `TestGetPrice`). Each class has a `_valid_kwargs()` or `_setup()` helper that provides a default valid state, and individual tests mutate only the field under test.

## Test Counts per File

| File | Tests |
|------|-------|
| `test_models.py` | 54 |
| `test_config.py` | 13 |
| `test_sdk_tools.py` | 24 |
| `test_rest_tools.py` | 26 |
| **Total** | **117** |

## Gotchas

- **`AgentConfig(_env_file=None)`**: The `_env_file=None` argument bypasses the `agent/.env` file. Without it, tests would silently read real credentials from disk if an `.env` file exists, making them environment-dependent.
- **`OPENROUTER_API_KEY` must be set via `monkeypatch.setenv`**: `AgentConfig` requires this field and raises `ValidationError` if it is absent. Every test that constructs an `AgentConfig` sets it.
- **`patch("agentexchange.async_client.AsyncAgentExchangeClient", ...)`**: The patch target is the import path inside `sdk_tools.py`, not `agentexchange.async_client`. If the import in `sdk_tools.py` changes, this patch target must be updated.
- **Workflow tests are not in this directory**: `run_smoke_test`, `run_trading_workflow`, etc. are not unit-tested here because they require either a live platform or complex multi-layer mocking. End-to-end workflow testing is done by the `e2e-tester` agent.
- **No `conftest.py`**: The agent test suite does not share fixtures with the platform tests. Each test class sets up its own state via `_setup()` helpers and `monkeypatch`.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
