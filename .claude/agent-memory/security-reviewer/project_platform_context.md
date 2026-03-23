---
name: Platform Security Context
description: Core security patterns and architecture facts for the AiTradingAgent platform
type: project
---

This is a simulated crypto exchange where AI agents trade virtual USDT against real market data.

**Security architecture layers:**
- Platform layer (`src/`): enforces hard per-order limits (8-step chain), API key auth, rate limiting, bcrypt passwords
- Agent strategies layer (`agent/strategies/`): portfolio-level overlay on top of platform; does NOT duplicate platform controls
- Agent strategies layer has NO direct DB access — all calls go through SDK or REST client

**Key security patterns confirmed working:**
- All monetary values in `agent/strategies/risk/` use `Decimal` throughout; float only at JSON output boundary (return values)
- Redis key construction uses validated agent_id strings — no injection vectors found
- `_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}$")` sanitizes symbol inputs before sector lookup
- Recovery manager Redis ops use pipeline for atomicity (`hset` mapping in pipeline)
- Circuit breaker Redis ops use pipeline for loss tracking (lpush + ltrim + expire in one pipe)
- Error decisions in middleware use fail-closed pattern: `verdict="HALT"` synthetic assessment

**Why:** Platform is deployed in production with CI/CD. Agent strategies layer is called frequently on each trading tick.
**How to apply:** When reviewing agent/strategies code, verify Decimal usage and that errors produce fail-closed behavior (HALT/VETOED, not fail-open).
