---
name: known_patterns_agent_trading
description: Known safe and unsafe patterns in agent/ trading subsystem discovered during Task 37 audit
type: project
---

## Known Safe Patterns (do not flag)

- `SignalGenerator._fetch_all_candles()` uses `asyncio.gather()` — all symbol candle fetches are concurrent. Correct.
- `TradingLoop._record()` batches all `AgentDecision` inserts into a single DB transaction (one `session.begin()` block) — not N+1.
- `WSManager._price_buffer` is bounded to `config.symbols` count (~3-30 symbols). Not an unbounded growth risk.
- `journal.daily_summary()` and `journal.weekly_review()` each make a single bulk DB query (`_fetch_decisions_in_range`) — no N+1.

## Known Issues Found (Task 37, 2026-03-22)

- `ContextBuilder._fetch_portfolio_section()`: opens a new `AsyncAgentExchangeClient` AND makes 2 sequential SDK calls (`get_balance` + `get_performance`) every `build()` call. No caching. HIGH.
- `ContextBuilder._fetch_strategy_section()`: opens a new `httpx.AsyncClient` every call. No caching. MEDIUM.
- `ContextBuilder._build_system_section()`: calls `load_skill_context()` on every `build()` — reads from disk or REST each time. LOW (file I/O is cheap, but could be cached).
- `TradingLoop._record()`: calls `await decision_repo.create(decision_row)` sequentially for each signal in a `for sig in signals:` loop (lines 841-873). With 3 default symbols this is 3 sequential INSERTs in one transaction instead of `add_all()`. MEDIUM.
- `signal_generator._rsi()`: computes `deltas` list only to immediately `del` it and recompute — dead computation, harmless but wasteful. LOW.
- `journal.record_outcome()`: fetches the existing row (`repo.get_by_id`) then immediately calls `repo.update_outcome` in the same transaction. Two round-trips where one UPDATE would suffice. MEDIUM.
- `WSManager` Task 27: confirmed WS integration is working correctly — `_observe()` reads from `_price_buffer` and skips REST when buffer is populated. API call reduction is effective.
