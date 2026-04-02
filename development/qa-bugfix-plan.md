---
type: plan
tags:
  - qa
  - bugfix
  - production
  - sprint
date: 2026-04-01
status: active
---

# QA Bug Fix Plan — A to Z

> **Source:** `development/test-results/test1.md` (53 tests) + `development/reports/tester-report-1.md` (17 bugs)
> **Date:** 2026-04-01
> **Score:** 39 PASS / 20 FAIL — 17 unique bugs (3 P0, 6 P1, 5 P2, 3 P3)

---

## Overview

After a full A-Z QA sweep of the production API, 17 bugs were found across 9 domains. This plan covers every bug with confirmed root cause, exact file locations, fix instructions, and verification steps. Organized into 4 sprints by priority.

### Bug Severity Map

| ID | Severity | Domain | Root Cause Type | Sprint |
|----|----------|--------|-----------------|--------|
| BUG-001 | P0 | Account | Design gap — no balance at registration | 1 |
| BUG-002 | P1 | Account | NOT NULL violation — missing `agent_id` | 1 |
| BUG-003 | P0 | Battles | Unhandled exception in `create_battle()` | 2 |
| BUG-004 | P1 | Agents | Missing CASCADE on FK constraints | 1 |
| BUG-005 | P0 | Strategies | Unhandled `ValidationError` → HTTP 500 | 2 |
| BUG-006 | P1 | Backtesting | Historical data never loaded | 3 |
| BUG-007 | P1 | Backtesting | QA used wrong URL (route exists) | 1 |
| BUG-008 | P1 | Backtesting | QA used wrong URL (route exists) | 1 |
| BUG-009 | P1 | Backtesting | QA used wrong URL (route exists) | 1 |
| BUG-010 | P2 | Analytics | QA used wrong URL (route exists) | 1 |
| BUG-011 | P2 | Analytics | Win rate ignores fees / NULL `realized_pnl` | 2 |
| BUG-012 | P2 | Market | `symbols` param required, should be optional | 2 |
| BUG-013 | P2 | Market | Path param only — no query param variant | 3 |
| BUG-014 | P2 | Market | Stale pair seed data | 3 |
| BUG-015 | P3 | Trading | `stop_price` vs `price` field naming | 3 |
| BUG-016 | P3 | Risk | Error message unclear (behavior is correct) | 3 |
| BUG-017 | P3 | Account | Hardcoded epoch-zero `opened_at` | 2 |

---

## Sprint 1 — Unblock Users (Critical Path)

### FIX-001: New accounts have zero balance (BUG-001)

**Priority:** P0 — blocks every new user
**Root cause:** `AccountService.register()` does NOT create a USDT `Balance` row. By design, balances are agent-scoped — they're created in `AgentService.create_agent()`. But accounts without agents show $0.

**File:** `src/accounts/service.py:183-226`

**Fix approach — Option A (recommended): Auto-create default agent at registration**

After the account is persisted in `register()`, automatically call agent creation logic to create a "Default" agent with the starting balance. This preserves the agent-scoped balance model while giving users an immediate working balance.

```python
# In src/accounts/service.py register(), after line ~210 (account created)
# Create a default agent so the account has a usable balance immediately
from src.agents.service import AgentService
agent_service = AgentService(self._session, self._account_repo)
await agent_service.create_agent(
    account_id=account.id,
    name=f"{display_name}'s Agent",
    description="Default trading agent",
    starting_balance=balance_amount,
)
```

**Fix approach — Option B: Document the two-step flow**

If auto-creating is undesirable, update all docs, SDK, and frontend onboarding to make agent creation mandatory before trading. Add a clear error message when querying balance with no agents.

**Verification:**
```bash
# Register new account
curl -X POST /api/v1/auth/register -d '{"display_name":"TestUser","starting_balance":"10000"}'
# Immediately check portfolio (should show 10000 USDT)
curl /api/v1/account/portfolio -H "X-API-Key: <key>"
```

---

### FIX-002: Account reset DATABASE_ERROR (BUG-002)

**Priority:** P1
**Root cause:** `reset_account()` creates a new `TradingSession` and `Balance` without `agent_id`, but both columns are NOT NULL.

**File:** `src/accounts/service.py:380-484`

**Fix:**

The reset function needs to be agent-aware. Two changes:

1. Accept `agent_id` parameter (or iterate all agents for the account)
2. Pass `agent_id` to both `Balance()` and `TradingSession()` constructors

```python
# src/accounts/service.py:reset_account()

# Change 1: At line ~448 (Balance creation)
new_balance = Balance(
    account_id=account_id,
    agent_id=agent_id,       # <-- ADD THIS
    asset="USDT",
    available=starting,
    locked=Decimal("0"),
)

# Change 2: At line ~458 (TradingSession creation)
new_session = TradingSession(
    account_id=account_id,
    agent_id=agent_id,       # <-- ADD THIS
    starting_balance=starting,
    status="active",
)
```

If the endpoint is account-level (no `agent_id` in request), the handler should iterate all agents for the account and reset each one. Alternatively, redirect to `AgentService.reset_agent()` which already works correctly (test 7.4 passed).

**Verification:**
```bash
curl -X POST /api/v1/account/reset -H "X-API-Key: <key>" -d '{"confirm":true}'
# Should return success, balance reset to starting amount
```

---

### FIX-004: Agent deletion DATABASE_ERROR (BUG-004)

**Priority:** P1
**Root cause:** Hard delete fails because newer agent ecosystem tables (`agent_sessions`, `agent_messages`, `agent_decisions`, `agent_journal`, `agent_api_calls`, `agent_strategy_signals`) have FK references to `agents.id` without `ON DELETE CASCADE`.

**Files:**
- `src/agents/service.py:290-300`
- `src/database/models.py` (agent ecosystem models)
- Alembic migrations 018/019/020

**Fix — Option A (recommended): Add CASCADE to FKs via migration**

Create a new Alembic migration that adds `ON DELETE CASCADE` to all FK references from agent ecosystem tables to `agents.id`:

```python
# New migration: add_cascade_to_agent_fks.py
def upgrade():
    # For each table: agent_sessions, agent_messages, agent_decisions,
    # agent_journal, agent_api_calls, agent_strategy_signals
    for table in ['agent_sessions', 'agent_messages', 'agent_decisions',
                  'agent_journal', 'agent_api_calls', 'agent_strategy_signals']:
        op.drop_constraint(f'fk_{table}_agent_id', table, type_='foreignkey')
        op.create_foreign_key(
            f'fk_{table}_agent_id', table, 'agents',
            ['agent_id'], ['id'], ondelete='CASCADE'
        )
```

**Fix — Option B: Soft delete (faster, no migration)**

Change `delete_agent()` to set `status = 'deleted'` instead of hard deleting:

```python
# src/agents/service.py:290
async def delete_agent(self, agent_id: UUID, account_id: UUID) -> None:
    agent = await self._agent_repo.get_by_id(agent_id)
    if not agent or agent.account_id != account_id:
        raise AgentNotFoundError(agent_id)
    agent.status = "deleted"
    await self._session.flush()
```

**Verification:**
```bash
curl -X DELETE /api/v1/agents/<agent_id> -H "Authorization: Bearer <jwt>"
# Should return 200/204, agent removed from list
```

---

### FIX-007/008/009: Backtest endpoints 404 — Wrong URLs (BUG-007/008/009)

**Priority:** P1 (not code bugs — URL mismatch)
**Root cause:** The routes exist but QA tested wrong paths.

**Correct URLs (confirmed from `src/api/routes/backtest.py`):**

| QA Tested (404) | Correct URL | Line |
|-----------------|-------------|------|
| `POST /backtest/{id}/trade` | `POST /api/v1/backtest/{session_id}/order` | backtest.py |
| `GET /backtest/{id}/equity` | `GET /api/v1/backtest/{session_id}/results/equity-curve` | backtest.py:624 |
| `GET /backtest/sessions` | `GET /api/v1/backtest/list` | backtest.py:684 |

**Fix:** No code change needed. Update:
1. API documentation to list correct paths
2. SDK client methods to use correct paths
3. QA test scripts to use correct paths

**Optional improvement:** Add redirect aliases for common wrong paths:
```python
# src/api/routes/backtest.py
@router.get("/backtest/sessions")
async def list_sessions_redirect(request: Request):
    return RedirectResponse("/api/v1/backtest/list")
```

---

### FIX-010: Portfolio history 404 — Wrong URL (BUG-010)

**Priority:** P2 (not a code bug)
**Root cause:** QA tested `GET /analytics/portfolio-history`. Actual path is `GET /api/v1/analytics/portfolio/history` (slash, not hyphen).

**File:** `src/api/routes/analytics.py:247-248`

**Fix:** No code change. Update documentation. Optionally add a redirect alias.

---

## Sprint 2 — Restore Features

### FIX-003: Battle creation INTERNAL_ERROR (BUG-003)

**Priority:** P0 — entire battle system broken
**Root cause:** `BattleService.create_battle()` has no exception handling. Any DB error (constraint violation, serialization issue) propagates as untyped exception → HTTP 500.

**Files:**
- `src/battles/service.py:106-153`
- `src/api/routes/battles.py:125-140`

**Investigation steps (do first):**
1. Check server logs for the actual stack trace
2. Add temporary debug logging to `create_battle()`:
   ```python
   import logging
   logger = logging.getLogger(__name__)
   # Before the repo call
   logger.error(f"Creating battle: {battle.__dict__}")
   ```
3. Test locally with a debugger to find the exact exception

**Likely fixes needed:**

1. **Add error handling in service:**
```python
# src/battles/service.py:create_battle()
try:
    await self._battle_repo.create_battle(battle)
    await self._session.flush()
except SQLAlchemyError as e:
    logger.exception("Battle creation failed")
    raise DatabaseError(f"Failed to create battle: {e}") from e
```

2. **Check for missing data:** The battle may require agents to have certain fields (e.g., `starting_balance`, active `TradingSession`) that are NULL. Validate prerequisites before DB insert.

3. **Check JSONB serialization:** If `backtest_config` or `battle_config` contains non-serializable types (UUID, Decimal, datetime), wrap with `model_dump(mode="json")`.

**Verification:**
```bash
curl -X POST /api/v1/battles -H "Authorization: Bearer <jwt>" \
  -d '{"name":"Test","type":"live","agent_ids":["<id1>","<id2>"],"duration_minutes":5}'
# Should return battle_id
```

---

### FIX-005: Strategy creation INTERNAL_ERROR (BUG-005)

**Priority:** P0 — entire strategy system broken
**Root cause:** `StrategyService.create_strategy()` calls `StrategyDefinition(**definition)` which raises `ValidationError` when the dict doesn't match the expected schema. This `ValidationError` is never caught → HTTP 500.

**File:** `src/strategies/service.py:44-64`

**Fix:**

```python
# src/strategies/service.py:create_strategy(), around line 63
from pydantic import ValidationError
from src.utils.exceptions import InputValidationError

try:
    validated_def = StrategyDefinition(**definition)
except ValidationError as e:
    raise InputValidationError(
        message=f"Invalid strategy definition: {e.error_count()} validation errors",
        details={"errors": e.errors()},
    ) from e
```

Also: document the expected `StrategyDefinition` schema in API docs so clients know what fields are required (especially `pairs`, which is likely required but not documented).

**Verification:**
```bash
# With correct schema
curl -X POST /api/v1/strategies -H "X-API-Key: <key>" \
  -d '{"name":"MA Cross","description":"test","definition":{"pairs":["BTCUSDT"],...}}'
# Should return strategy_id

# With bad schema
curl -X POST /api/v1/strategies -d '{"name":"Bad","definition":{}}'
# Should return 400 with validation errors, NOT 500
```

---

### FIX-011: Win rate calculation incorrect (BUG-011)

**Priority:** P2
**Root cause:** `Trade.realized_pnl` may be NULL for some trades, causing the win rate calculation to misclassify trades. Fees may also not be factored in.

**Files:**
- `src/portfolio/tracker.py` (where `PerformanceMetrics.calculate()` lives)
- `src/accounts/balance_manager.py` (where `realized_pnl` is set on trade execution)

**Investigation steps:**
1. Read `src/portfolio/tracker.py` — find the `calculate()` method
2. Check if `realized_pnl` is set during trade execution in `balance_manager.py`
3. Check if the win/loss classification uses `realized_pnl` or raw price diff

**Fix approach:**
- Ensure `realized_pnl` is computed as `(sell_price - avg_entry_price) * quantity - fees` during trade execution
- Ensure win rate uses `realized_pnl > 0` (not gross PnL) for classification
- If `realized_pnl` is NULL, skip that trade from win/loss stats (don't count as loss)

**Verification:**
```bash
# After fix: execute a profitable sell, check analytics
curl /api/v1/analytics/performance -H "X-API-Key: <key>"
# win_rate should be > 0 for profitable trades
```

---

### FIX-012: Tickers endpoint requires `symbols` parameter (BUG-012)

**Priority:** P2
**File:** `src/api/routes/market.py:342-351`

**Fix:** Make `symbols` optional with default `None`. When omitted, return all tickers.

```python
# src/api/routes/market.py, tickers endpoint
# Change:
#   symbols: str = Query(...)
# To:
symbols: str | None = Query(default=None, description="Comma-separated symbols. Omit for all.")

# In handler body, add:
if symbols is None:
    # Return all available tickers
    all_prices = await price_cache.get_all_prices()
    # ... build ticker response for all symbols
```

**Verification:**
```bash
curl /api/v1/market/tickers -H "X-API-Key: <key>"
# Should return all tickers, not 422
```

---

### FIX-017: Position `opened_at` is epoch zero (BUG-017)

**Priority:** P3 (but easy fix)
**Root cause:** `_position_view_to_item()` in `account.py:108-122` hardcodes `opened_at = datetime.fromtimestamp(0, tz=UTC)` because `PositionView` doesn't include that field.

**File:** `src/api/routes/account.py:108-122`

**Fix — Option A: Add `opened_at` to PositionView**

In `src/portfolio/tracker.py`, add `opened_at: datetime` to the `PositionView` dataclass. When building position views, join with the `positions` table to get the real timestamp.

**Fix — Option B: Fetch Position rows separately (simpler)**

In the route handler, after getting position views, fetch the corresponding `Position` ORM objects to get `opened_at`:

```python
# src/api/routes/account.py, in the positions endpoint
from src.database.models import Position

# After getting position_views from tracker:
position_rows = await db.execute(
    select(Position).where(Position.agent_id == agent_id)
)
opened_at_map = {p.symbol: p.opened_at for p in position_rows.scalars()}

# In _position_view_to_item():
opened_at = opened_at_map.get(view.symbol, datetime.now(UTC))
```

---

## Sprint 3 — Data, Docs & Polish

### FIX-006: Historical backtest data unavailable (BUG-006)

**Priority:** P1 (but operational, not code)
**Root cause:** `scripts/backfill_history.py` has never been run in production. The `candles_backfill` table is empty. Only live-ingested ticks from today exist.

**Fix:**
```bash
# Run on production server (or via Docker exec)
python scripts/backfill_history.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT \
  --start 2025-01-01 --end 2026-04-01 --intervals 1m,5m,15m,1h,4h,1d
```

**Considerations:**
- This fetches from Binance public API — rate limits apply
- For 8 symbols x 6 intervals x 15 months, expect ~2M candle rows
- Run during off-peak hours
- May need to be batched (1 month at a time per symbol)

**Post-fix:** Update docs to reflect actual data range available.

---

### FIX-013: Candles endpoint path vs query param (BUG-013)

**Priority:** P2 (documentation issue)
**Root cause:** Route is `GET /market/candles/{symbol}` (path param). Docs/SDK may reference query param style.

**Fix options:**
1. **(Recommended)** Update all documentation and SDK to use path param: `/market/candles/BTCUSDT?interval=1h&limit=100`
2. **(Optional)** Add a second route accepting query param for backward compat

---

### FIX-014: Pair count mismatch — 439 vs 647 (BUG-014)

**Priority:** P2 (data freshness)
**Fix:**
```bash
# Re-run seed script to fetch current Binance pairs
python scripts/seed_pairs.py
```
Then update documentation with actual count.

---

### FIX-015: Stop-loss `stop_price` vs `price` field name (BUG-015)

**Priority:** P3
**File:** `src/api/schemas/trading.py:112-128`

**Fix — add alias:**
```python
# src/api/schemas/trading.py, in OrderRequest
price: Decimal | None = Field(
    default=None,
    description="Price for limit/stop-loss/take-profit orders",
    alias="stop_price",          # Accept stop_price as alias
    validation_alias=AliasChoices("price", "stop_price"),  # Accept either
)
```

Also update API docs to clearly state that `price` is the canonical field for ALL order types.

---

### FIX-016: Position limit error message unclear (BUG-016)

**Priority:** P3
**File:** `src/risk/manager.py:780-803`

**Root cause:** The rejection is correct (combined position exceeds 25%), but the error message doesn't explain the math.

**Fix:** Improve the error message:

```python
# src/risk/manager.py:_check_position_limit()
raise OrderRejectedError(
    f"position_limit_exceeded: {symbol} position would be "
    f"{new_position_pct:.1f}% of equity (limit: {max_position_pct}%). "
    f"Current: {existing_value:.2f} USDT, "
    f"Requested: {order_value:.2f} USDT, "
    f"Equity: {total_equity:.2f} USDT"
)
```

---

## Execution Order

```
Sprint 1 (Day 1-2):  FIX-001 → FIX-002 → FIX-004 → FIX-007/008/009/010 (docs)
Sprint 2 (Day 3-5):  FIX-003 → FIX-005 → FIX-011 → FIX-012 → FIX-017
Sprint 3 (Day 6-7):  FIX-006 → FIX-013 → FIX-014 → FIX-015 → FIX-016
```

### Dependency Graph

```
FIX-001 (balance at registration)
  └── No dependencies, fix first — unblocks all new users

FIX-002 (account reset)
  └── Depends on understanding from FIX-001 (agent-scoped balances)

FIX-004 (agent delete)
  └── Requires migration — can run in parallel with FIX-001/002

FIX-003 (battles)
  └── Needs investigation first — may depend on FIX-001 (agent balance)

FIX-005 (strategies)
  └── Independent — pure error handling fix

FIX-011 (win rate)
  └── Needs investigation of metrics calculation pipeline

FIX-006 (historical data)
  └── Independent — operational task, can run anytime
```

### Post-Fix Validation

After all fixes are deployed, re-run the full QA test suite:

```bash
# Re-run all 53 tests from test1.md
# Expected: 53/53 PASS (0 FAIL)
```

### Files That Will Be Modified

| File | Bugs Fixed |
|------|------------|
| `src/accounts/service.py` | BUG-001, BUG-002 |
| `src/agents/service.py` | BUG-004 |
| `src/battles/service.py` | BUG-003 |
| `src/strategies/service.py` | BUG-005 |
| `src/api/routes/account.py` | BUG-017 |
| `src/api/routes/market.py` | BUG-012 |
| `src/api/schemas/trading.py` | BUG-015 |
| `src/risk/manager.py` | BUG-016 |
| `src/portfolio/tracker.py` | BUG-011 |
| New Alembic migration | BUG-004 |
| API documentation | BUG-007/008/009/010/013/014/015 |

### Testing Strategy

For each fix:
1. Write a regression test that reproduces the bug
2. Apply the fix
3. Verify the regression test passes
4. Run existing tests to ensure no regressions (`pytest tests/unit/ tests/integration/`)
5. Deploy and verify against production API

---

## Notes

- **BUG-007/008/009/010** are NOT code bugs — the routes exist at different paths than the QA team tested. These require documentation updates only.
- **BUG-013/014** are documentation/data freshness issues, not code bugs.
- **BUG-016** behavior is correct — only the error message needs improvement.
- **BUG-001** is the most impactful — every single new user hits this immediately.
- **BUG-003 and BUG-005** need server log investigation before coding the fix — the generic `INTERNAL_ERROR` hides the real exception.

---

*Plan created: 2026-04-01*
*Status: Ready for execution*
