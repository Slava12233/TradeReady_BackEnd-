---
type: code-review
date: 2026-03-20
reviewer: perf-checker
verdict: NEEDS FIXES
scope: agent-strategies
tags:
  - review
  - performance
  - strategies
---

# Performance Audit Report - agent/strategies/

**Date:** 2026-03-20
**Auditor:** perf-checker agent
**Branch:** V.0.0.2

---

## Summary

- **15 findings: 0 CRITICAL, 8 HIGH, 5 MEDIUM, 2 LOW**
- Scope: all Python files under `agent/strategies/` (5 subdirectories, 34 files)

---

## Findings

---

### [HIGH] N+1 API calls - per-symbol price fetch in live trading loop

- **File:** `agent/strategies/rl/deploy.py:832-837`
- **Check:** N+1 API Call Pattern
- **Issue:** `run_live()` fetches current prices in a sequential `for sym in self._config.env_symbols:` loop, issuing one `await client.get_price(sym)` HTTP call per symbol per step. With 3 symbols (default) this is 3 sequential round-trips per iteration. At 50ms server latency, this adds 150ms of serial latency per step before any inference occurs.
- **Impact:** Step latency grows linearly with symbol count. At 10 symbols with 50ms RTT, the price fetch phase alone costs 500ms -- already at the 500ms budget ceiling before model inference.
- **Suggestion:** Gather all price requests concurrently: `asyncio.gather(*[client.get_price(sym) for sym in self._config.env_symbols])` and zip results into `prices`. This reduces the fetch phase to one round-trip regardless of symbol count.

---

### [HIGH] N+1 API calls - sequential agent creation in evolution setup

- **File:** `agent/strategies/evolutionary/battle_runner.py:237-246`
- **Check:** N+1 API Call Pattern
- **Issue:** `setup_agents()` creates platform agents in a sequential `for i in range(population_size):` loop, calling `await self._create_agent(name)` once per agent. With the default population of 12, this issues 12 sequential `POST /api/v1/agents` requests before the first generation begins.
- **Impact:** Setup cost scales linearly with population size. If each REST call takes 100ms under load, setup alone costs 1.2s. Any server-side latency spike multiplies across all 12 calls.
- **Suggestion:** Gather all agent creation calls concurrently with `asyncio.gather` plus `asyncio.Semaphore(5)` to avoid overwhelming the server connection pool.

---

### [HIGH] N+1 API calls - sequential agent reset per generation (360 total calls)

- **File:** `agent/strategies/evolutionary/battle_runner.py:309-330`
- **Check:** N+1 API Call Pattern
- **Issue:** `reset_agents()` resets each platform agent in a sequential `for agent_id in agent_ids:` loop. With 12 agents x 30 generations = **360 sequential `POST /api/v1/agents/{id}/reset` calls** over a full evolution run. Called at the start of every generation.
- **Impact:** If each reset call takes 80ms, generation setup overhead is 960ms per generation -- ~29 seconds of pure wait time across 30 generations. Under server load this can be 2-5x worse.
- **Suggestion:** Gather all resets concurrently with `asyncio.gather` and a bounded semaphore. Resets are independent -- they touch different agent records.

---

### [HIGH] N+1 API calls - sequential strategy assignment per generation

- **File:** `agent/strategies/evolutionary/battle_runner.py:366-411`
- **Check:** N+1 API Call Pattern
- **Issue:** `assign_strategies()` iterates over agents sequentially, calling `await self._create_or_version_strategy(agent_id, genome)` per agent. Each call may issue 1-2 REST requests. With 12 agents, this is 12-24 sequential HTTP requests per generation.
- **Impact:** Combined with sequential reset overhead, the per-generation setup phase consumes 1.5-2 seconds before any battle trading begins, significantly inflating total evolution time.
- **Suggestion:** Gather strategy assignments concurrently with `asyncio.gather` and a semaphore for server-side safety.

---
### [HIGH] N+1 API calls - sequential participant registration per battle

- **File:** `agent/strategies/evolutionary/battle_runner.py:599-616`
- **Check:** N+1 API Call Pattern
- **Issue:** `_add_participants()` adds each agent to the battle in a sequential `for agent_id in agent_ids:` loop with individual `await self._http.post(...)` calls. With 12 agents, this is 12 sequential `POST /api/v1/battles/{id}/participants` requests per generation.
- **Impact:** Adds latency to every generation battle setup. Multiplied over 30 generations this is 360 sequential registration calls across the full run.
- **Suggestion:** Check whether the battle endpoint accepts a list payload. If not, gather the individual calls concurrently with `asyncio.gather`.

---

### [HIGH] Sequential asset validation - should be gathered

- **File:** `agent/strategies/rl/data_prep.py:692-730`
- **Check:** N+1 API Call Pattern
- **Issue:** `validate_data()` checks each asset in a sequential `for symbol in assets:` loop, calling `await check_asset(symbol)` per symbol. Asset validation calls are independent of each other.
- **Impact:** For 10 assets, sequential validation adds 10x the single-asset validation latency, blocking training pipeline startup.
- **Suggestion:** `results = await asyncio.gather(*[check_asset(sym) for sym in assets], return_exceptions=True)` then process results in bulk.

---

### [HIGH] Blocking model.predict() in async live trading loop

- **File:** `agent/strategies/rl/deploy.py:857` (live path), `agent/strategies/ensemble/run.py:679`
- **Check:** Blocking Calls in Async Code
- **Issue:** `self._model.predict(obs, deterministic=True)` is a synchronous PyTorch neural-network forward pass called directly from within async functions (`run_live()` and `_get_rl_signals()`). PyTorch CPU inference takes 5-50ms depending on network size, blocking the entire asyncio event loop for its duration.
- **Impact:** Any other async tasks on the same event loop (WebSocket handlers, heartbeat tasks, concurrent strategy steps) are frozen during each inference call. In the ensemble pipeline where `step()` is called repeatedly, this creates a consistent per-step freeze.
- **Suggestion:** Offload via `await asyncio.get_event_loop().run_in_executor(None, lambda: self._model.predict(obs, deterministic=True))`. For high-frequency calling, use a dedicated `ThreadPoolExecutor` with 1-2 threads to avoid spawning overhead.

---

### [HIGH] Blocking sklearn training in async initialisation path

- **File:** `agent/strategies/ensemble/run.py:575`
- **Check:** Blocking Calls in Async Code
- **Issue:** `_train_fallback_regime_classifier()` trains a RandomForest classifier (300 estimators, ~600 samples) synchronously inside `initialize()`, which is called from an async context. `RandomForestClassifier.fit()` is CPU-bound and takes 1-3 seconds on a typical CPU.
- **Impact:** Any caller that awaits `EnsembleRunner.initialize()` freezes the event loop for 1-3 seconds, stalling all concurrent requests and background tasks.
- **Suggestion:** Wrap in `run_in_executor`: `await asyncio.get_event_loop().run_in_executor(None, self._train_fallback_regime_classifier)`. Alternatively, move classifier training to a separate explicit async method rather than inline in `initialize()`.

---
### [MEDIUM] Per-step full indicator recomputation in regime switcher

- **File:** `agent/strategies/regime/switcher.py:194-195`
- **Check:** Inefficient Computation in Hot Path
- **Issue:** `detect_regime()` calls `generate_training_data(candles, window=20)` on every single invocation. This recomputes all 5 technical indicators (ADX, ATR, Bollinger Bands, RSI, MACD histogram) over the full candle window from scratch, allocating new NumPy arrays and a Pandas DataFrame each time. With a 100-candle rolling window, this is O(100 x 5) computations per step per symbol.
- **Impact:** For the <500ms per-step target with multiple symbols, each per-symbol regime detection call adds avoidable allocation and computation. At 100 candles x 5 indicators x 3 symbols, 1,500 indicator data points are recalculated every step even when only the last candle is new.
- **Suggestion:** Cache the most recent feature vector keyed by the last candle timestamp. On `detect_regime()` entry, if the last candle timestamp is unchanged, return the cached regime and confidence. Otherwise recompute. Reduces amortized cost to O(1) per step when candles are stable.

---

### [MEDIUM] Unbounded _step_history list during ensemble backtest runs

- **File:** `agent/strategies/ensemble/run.py:384` (declaration), line ~1007 (append in `step()`)
- **Check:** Memory Leak / Unbounded Growth
- **Issue:** `self._step_history: list[StepResult]` accumulates one entry per `step()` call with no eviction during a run. Each `StepResult` holds nested `SymbolStepResult` and `SignalContribution` objects. At `max_iterations=1000` with 3 symbols and 3 sources, this list holds ~9,000 nested Pydantic objects.
- **Impact:** Pydantic model overhead (~200-500 bytes each) puts peak memory at 1.8-4.5 MB per run. At `max_iterations=10000` this scales to 18-45 MB. Multiple concurrent sessions multiply this. Note: `run_backtest()` correctly clears `_step_history` at the start (line 1105), so this does not leak across runs.
- **Suggestion:** Cap via `collections.deque(maxlen=500)` and stream completed steps to a file or return as a generator rather than accumulating all in RAM.

---

### [MEDIUM] Unbounded regime_history list in switcher

- **File:** `agent/strategies/regime/switcher.py:153`
- **Check:** Memory Leak / Unbounded Growth
- **Issue:** `self.regime_history: list[RegimeRecord]` grows by one entry for every detected regime switch with no cap, eviction, or TTL. In a long-running backtest (10,000 steps at 1-minute candles), regime transitions can be frequent.
- **Impact:** Memory consumption is proportional to regime transitions over the session lifetime. Low severity in isolation but compounds when multiple `RegimeSwitcher` instances are held concurrently across ensemble sessions.
- **Suggestion:** Cap to the last N records via `collections.deque(maxlen=500)`, or document that callers are responsible for reading and clearing the history periodically.

---

### [MEDIUM] Sequential candle fetching per symbol in ensemble backtest loop

- **File:** `agent/strategies/ensemble/run.py:1172-1194`
- **Check:** N+1 API Call Pattern
- **Issue:** The backtest main loop fetches candles for each symbol in a sequential `for sym in self._config.symbols:` loop, one `await self._rest.get(...)` per symbol per iteration. With 3 symbols this is 3 sequential HTTP requests per iteration before any trading logic runs.
- **Impact:** At 50ms per candle fetch, 3 symbols x 1,000 iterations = 150 seconds of serial HTTP wait time versus ~50 seconds with concurrent gathering. Directly impacts the ensemble pipeline step latency budget.
- **Suggestion:** Gather candle fetches concurrently with `asyncio.gather`. The 404/409/410 early-exit logic needs to be handled in the gathered result processing rather than via `break` inside the sequential loop.

---

### [MEDIUM] Mutable function attribute for cross-run state contamination

- **File:** `agent/strategies/evolutionary/evolve.py:231`
- **Check:** Memory / State Contamination
- **Issue:** `_save_champion_strategy._strategy_id = None` assigns a mutable attribute directly to the function object. This persists across calls within the same Python process. If two evolution runs execute in the same process, the second run sees the `_strategy_id` left by the first and may incorrectly skip strategy creation, producing a versioning bug.
- **Impact:** Correctness bug under multi-run scenarios. In production, if the evolution system is called as a service with multiple runs per process, the first run champion strategy ID contaminates subsequent runs.
- **Suggestion:** Move cross-call state into a proper instance variable scoped to the current run, or pass the strategy ID as an explicit mutable container rather than a function attribute.

---

### [LOW] _REGIME_ACTION dict recreated on every regime_to_signals() call

- **File:** `agent/strategies/ensemble/meta_learner.py:453`
- **Check:** Inefficient Allocation in Hot Path
- **Issue:** The static method `regime_to_signals()` defines `_REGIME_ACTION: dict[RegimeType, TradeAction]` as a local variable inside the function body. The dict is allocated and garbage-collected on every call. Called once per symbol per ensemble step.
- **Impact:** LOW -- dict allocation is ~200ns. Negligible at 3 symbols. Marginally noticeable if symbol count grows to 100+.
- **Suggestion:** Move `_REGIME_ACTION` to a module-level constant. Allocates once at import time.

---

### [LOW] Blocking file write in _save_training_log() after each seed

- **File:** `agent/strategies/rl/runner.py:749-757`
- **Check:** Blocking Calls in Async Code (minor)
- **Issue:** `_save_training_log()` uses `log_path.write_text(json.dumps(log_data))` -- a synchronous blocking file write called once per seed completion. Training itself is synchronous (SB3 `model.learn()` blocks), so this is not currently an event-loop violation.
- **Impact:** LOW -- called once per seed, not in a hot loop. Blocking duration is ~1ms for typical log sizes. No current event-loop impact.
- **Suggestion:** If `train_seed()` is ever wrapped in an async executor, replace with `aiofiles.write_text()`. Low priority for now.

---
## Overall Assessment

The five strategy modules are well-structured with proper separation of concerns, lazy model loading, and clear async/sync boundaries in most places. The most significant performance cluster is **N+1 API call patterns in the evolutionary battle runner** -- five separate locations in `battle_runner.py` issue sequential HTTP requests where concurrent `asyncio.gather()` calls would reduce total latency by 80-90%. Across a 30-generation x 12-agent run, the cumulative overhead from these serial calls is estimated at **30-60 seconds of avoidable wait time**.

The second highest-risk issue is **blocking CPU-bound calls in async contexts** -- `model.predict()` in `deploy.py` and `run.py`, and `_train_fallback_regime_classifier()` in `run.py`. These freeze the event loop for 5-50ms and 1-3 seconds respectively.

The **regime switcher per-step full indicator recomputation** (`switcher.py:194`) is the primary threat to the <10ms regime inference budget. While the XGBoost classifier itself is sub-millisecond, the `generate_training_data()` preprocessing call performs O(N) indicator computation over the full candle window on every step.

The **unbounded `_step_history` list** in `ensemble/run.py` is memory-safe for single-session backtests (cleared at run start) but will become a concern if `max_iterations` is increased or concurrent sessions accumulate.

No CRITICAL issues were found. There are no database N+1 patterns, unbounded Redis key growth, or missing indexes (the strategy layer uses platform REST APIs, not direct DB access). The evolutionary loop memory growth (30 gen x 12 agents) is bounded and acceptable.

### Priority Fix Order

1. `battle_runner.py` -- gather all 5 sequential API call loops (HIGH, addresses ~30-60s of evolution overhead)
2. `deploy.py:857` and `run.py:679` -- `run_in_executor` for `model.predict()` (HIGH, prevents event-loop freezes per step)
3. `run.py:575` -- `run_in_executor` for fallback classifier training (HIGH, prevents 1-3s event-loop stall at init)
4. `run.py:1172` -- gather per-symbol candle fetches in backtest loop (MEDIUM, reduces step latency by ~2/3)
5. `switcher.py:194` -- cache indicator features between steps (MEDIUM, protects <10ms regime inference budget)
