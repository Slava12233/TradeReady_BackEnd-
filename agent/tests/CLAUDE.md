# agent/tests — Agent Package Unit Tests

<!-- last-updated: 2026-03-24 -->

> Unit tests for the `agent` package. All external dependencies are mocked; no running platform or LLM is required.

## What This Module Does

Provides isolated unit tests for the agent's configuration, output models, and tool factories. Tests cover field validation, error handling contracts, HTTP request shapes, and factory structure — not workflow orchestration or LLM behaviour. The test suite is independent of the main platform test suite in `tests/` and does not use the platform's `conftest.py` or app factory.

## Key Files

| File | Purpose |
|------|---------|
| `test_models.py` | 54 tests — all 6 Pydantic output models: field validation, boundaries, immutability, round-trips |
| `test_config.py` | 13 tests — `AgentConfig` field defaults, required fields, env var overrides, computed fields |
| `test_sdk_tools.py` | 60 tests — `get_sdk_tools()` factory structure and all 15 tool function behaviours |
| `test_signal_generator.py` | 23 tests — volume filter logic, confidence threshold, `_compute_volume_ratio`, `_apply_volume_filter` |
| `test_rest_tools.py` | 26 tests — `PlatformRESTClient` methods and `get_rest_tools()` factory structure |
| `test_server_writer_wiring.py` | 20 tests — `LogBatchWriter` singleton wiring in `AgentServer` lifecycle |
| `test_server_handlers.py` | 54 tests — 7 intent handler functions + `REASONING_LOOP_SENTINEL` fallback routing |
| `test_redis_memory_cache.py` | Updated — 4 new tests in `TestGetCached` class; pipeline mock verifies 24h TTL |
| `test_ws_manager.py` | 46 tests — `WSManager` lifecycle, price buffer, order-fill events, `TradingLoop` WS integration |
| `test_pair_selector.py` | 42 tests — `PairSelector` cache, filters, ranking, momentum tier, batch splitting, concurrency |
| `__init__.py` | Empty package marker |

Additional test files (all 37 master plan tasks + C-level recommendations):
- `test_kelly_hybrid_sizing.py` — Kelly/Hybrid sizer tests
- `test_evolutionary_fitness.py` — OOS composite fitness tests
- `test_drawdown_profiles.py` — DrawdownProfile/DrawdownTier preset tests
- `test_circuit_breaker.py` — `StrategyCircuitBreaker` 3-trigger tests (56 tests)
- `test_recovery_manager.py` — `RecoveryManager` FSM tests (53 tests)
- `test_memory_learning_loop.py` — memory-driven learning (29 tests)
- `test_drift_detector.py` — `DriftDetector` Page-Hinkley tests
- `test_retrain.py` — `RetrainOrchestrator` 4-schedule + A/B gate tests (57 tests)
- `test_walk_forward.py` — walk-forward validation (94 tests)
- `test_attribution.py` — `AttributionLoader` + `MetaLearner.apply_attribution_weights()` (45 tests)
- `test_dynamic_weights.py` — dynamic ensemble weights (55 tests)
- `test_ensemble_backtest_validation.py` — `BacktestValidationReport` + acceptance criteria (40 tests)
- `test_optimize_weights.py` — weight optimizer utilities
- `test_regime.py`, `test_regime_labeler.py` — regime features (189 total regime tests)
- `test_risk_middleware.py` — correlation gate tests (59 total)
- `test_security_regressions.py` — 20 regression tests for 7 security fixes (ADMIN role checks, BudgetManager.close(), audit log, checksum strict mode)
- `test_retrain_celery.py` — 29 integration tests for `src/tasks/retrain_tasks.py` Celery task wiring and `RetrainOrchestrator` Celery bridge

Total: **2300+ tests** across 52 test files in `agent/tests/`.

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
| `test_sdk_tools.py` | 48 |
| `test_rest_tools.py` | 26 |
| `test_server_writer_wiring.py` | 20 |
| `test_server_handlers.py` | 54 |
| **Total (base files)** | **215+** |

## Gotchas

- **`AgentConfig(_env_file=None)`**: The `_env_file=None` argument bypasses the `agent/.env` file. Without it, tests would silently read real credentials from disk if an `.env` file exists, making them environment-dependent.
- **`OPENROUTER_API_KEY` must be set via `monkeypatch.setenv`**: `AgentConfig` requires this field and raises `ValidationError` if it is absent. Every test that constructs an `AgentConfig` sets it.
- **`patch("agentexchange.async_client.AsyncAgentExchangeClient", ...)`**: The patch target is the import path inside `sdk_tools.py`, not `agentexchange.async_client`. If the import in `sdk_tools.py` changes, this patch target must be updated.
- **Workflow tests are not in this directory**: `run_smoke_test`, `run_trading_workflow`, etc. are not unit-tested here because they require either a live platform or complex multi-layer mocking. End-to-end workflow testing is done by the `e2e-tester` agent.
- **No `conftest.py`**: The agent test suite does not share fixtures with the platform tests. Each test class sets up its own state via `_setup()` helpers and `monkeypatch`.

## Recent Changes

- `2026-03-23` — Added `test_security_regressions.py` (20 tests) covering: ADMIN role check in `grant_capability`, `revoke_capability`, `set_role`; `BudgetManager.close()` resource cleanup; `AgentAuditLog` row persistence; checksum `strict=True` behavior. Added `test_retrain_celery.py` (29 tests) covering: Celery task registration, `run_retraining_cycle` dispatcher, all 4 sub-tasks, beat schedule entries, `ml_training` queue routing, `asyncio.run()` bridge. Test file count: 50 → 52. Total: 2300+ tests.
- `2026-03-22` — ALL 37/37 Trading Agent Master Plan tasks complete. Added test files for: `test_drift_detector.py`, `test_retrain.py` (57 tests), `test_dynamic_weights.py` (55 tests), `test_ensemble_backtest_validation.py` (40 tests), `test_regime.py`, `test_regime_labeler.py`, `test_risk_middleware.py`, `test_optimize_weights.py`, `test_kelly_hybrid_sizing.py`, `test_evolutionary_fitness.py`, `test_drawdown_profiles.py`. Total: 50 test files, 1400+ tests.
- `2026-03-22` — Task 31: Created `test_attribution.py` (45 tests) covering `MetaLearner.weights` property, `apply_attribution_weights()` (positive boost, negative shrink, min_weight floor, unknown strategy names ignored), `AttributionLoader` init variants, no-data path, data path with DB mock, auto-pause logic (negative PnL → `StrategyCircuitBreaker.pause()` with 48h TTL, already-paused skip, all-negative pauses all), error capture (DB errors, CB errors, ML errors never raise), `EnsembleRunner.load_attribution()` integration (no-op before initialize, wires meta_learner and circuit_breaker). Fixed: non-UUID agent IDs accepted in tests via try/except in `_fetch_attribution`.
- `2026-03-22` — Task 15: Created `test_ensemble_backtest_validation.py` (40 tests) covering `EnsembleReport` new financial metric fields, `BacktestValidationReport` model, `build_validation_report()` acceptance criteria (5 criteria, all pass/fail paths), `EnsembleRunner._fetch_backtest_metrics()` (success, nested/flat response, HTTP errors, bad session IDs, missing keys, non-numeric values), `_build_report()` platform_metrics propagation, `run_backtest()` end-to-end metrics attachment, and `_cli_main()` backtest mode dual-file output.
- `2026-03-22` — Task 32: Created `test_memory_learning_loop.py` (29 tests) covering the full memory creation and retrieval cycle: `TradingJournal.save_episodic_memory()`, `save_procedural_memory()` (with reinforce path), `_save_learnings_to_memory()` routing, `generate_reflection()` integration, and `ContextBuilder._fetch_learnings_section()` / `build()` / `build_trade_context()` with symbol + regime scoping.
- `2026-03-22` — Task 26: Created `test_pair_selector.py` (42 tests) covering `PairSelector` cache hit/miss, TTL staleness, `asyncio.Lock` concurrency, filter thresholds, volume ranking, momentum tier, batch splitting, all fallback paths, and `_to_decimal`/`_parse_ticker`/`SelectedPairs.is_stale` helpers. Default `_ticker_entry` spread is 3.5% (passes 5% filter). Tests with fewer than 5 symbols use `min_symbols_threshold=1` constructor kwarg.
- `2026-03-22` — Task 24: added 12 tests for `get_ticker` and `get_pnl` in `test_sdk_tools.py` (count 48 → 60). Created `test_signal_generator.py` (23 tests) covering `_compute_volume_ratio`, `_apply_volume_filter`, and confidence threshold behaviour. Updated tool-count assertion (13 → 15).
- `2026-03-22` — Task 20: added 24 new tests for 6 new SDK tools (`place_limit_order`, `place_stop_loss`, `place_take_profit`, `cancel_order`, `cancel_all_orders`, `get_open_orders`). Updated `test_sdk_tools.py` tool-count assertion (7 → 13). Added shared `_make_pending_order()` helper. test_sdk_tools.py: 24 → 48 tests.
- `2026-03-22` — Added `test_server_writer_wiring.py` (20 tests) and `test_server_handlers.py` (54 tests). Updated `test_redis_memory_cache.py` with 4 new `TestGetCached` tests and pipeline TTL verification. Updated file inventory and test counts.
- `2026-03-20` — Initial CLAUDE.md created.
