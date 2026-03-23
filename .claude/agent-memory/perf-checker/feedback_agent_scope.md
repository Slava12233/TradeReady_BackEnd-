---
name: agent_scope
description: This perf-checker runs against agent/ trading code (SDK-backed), not only the main src/ platform backend
type: feedback
---

When Task descriptions reference files in `agent/`, audit those files using the same checks (N+1, blocking calls, unbounded growth, etc.) applied to SDK HTTP client calls instead of SQLAlchemy session calls.

**Why:** The agent/ subsystem uses AsyncAgentExchangeClient (SDK) and httpx for I/O. The same N+1 and blocking patterns apply but look different (loops around `await client.get_price(sym)` instead of `await session.execute(...)`).

**How to apply:** Treat `await client.get_price(sym)` / `await rest.get(...)` calls inside loops the same as DB N+1 queries. Flag new SDK client instances created per-call in hot paths the same as ad-hoc DB connections bypassing the pool.
