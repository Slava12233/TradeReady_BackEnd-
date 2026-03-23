---
name: context_builder_cache
description: ContextBuilder._fetch_portfolio_section() creates a new SDK client on every build() call — Task 37 adds a 30s TTL cache
type: project
---

`agent/conversation/context.py` `ContextBuilder._fetch_portfolio_section()` opens a fresh `AsyncAgentExchangeClient` (and makes two API calls: `get_balance` + `get_performance`) on every `build()` call. There is no caching.

**Why:** Task 37 requires a 30-second TTL cache for the portfolio state section to avoid hammering the platform API during frequent LLM context builds.

**How to apply:** When auditing context.py, flag the per-call client construction and the two sequential SDK calls as HIGH severity. The fix is an instance-level `_portfolio_cache: tuple[str, float] | None` with a 30s TTL checked at the top of `_fetch_portfolio_section`.

Similarly, `_fetch_strategy_section` opens a new `httpx.AsyncClient` per call — should also be cached or use a shared client.
