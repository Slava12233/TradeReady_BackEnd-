# Battle Historical Mode -- 500 Error Investigation

**Date of investigation:** 2026-03-20
**Bug reported:** 2026-03-18 (noted in development/context.md)
**Status:** FIXED as of 2026-03-18

---

## Summary

The 500 INTERNAL_ERROR on POST /api/v1/battles (historical mode create) was caused by two separate defects that were both fixed on 2026-03-18. The current codebase has neither defect. Historical battle creation is unblocked.

---

## Root Cause (Original Bugs, Now Fixed)

### Bug 1: datetime serialization crash in JSONB column

**Where:** src/api/routes/battles.py, line 138

**What it was:** HistoricalBattleConfig is a Pydantic schema with start_time/end_time datetime fields. Before the fix the route passed the raw Pydantic model object as backtest_config into BattleService.create_battle(), which stored it in the Battle.backtest_config JSONB column. PostgreSQL received a Python datetime object it could not serialize, throwing a DataError at flush time -- surfaced as a 500.

**The fix (present in current code):**

    # src/api/routes/battles.py:138
    backtest_config=body.backtest_config.model_dump(mode="json") if body.backtest_config else None

model_dump(mode="json") converts all datetime fields to ISO 8601 strings, producing a plain dict that PostgreSQL stores in JSONB without error. HistoricalBattleEngine.initialize() reads these back via datetime.fromisoformat().

### Bug 2: Local BattleInvalidStateError had wrong HTTP status

**Where:** A now-deleted local BattleInvalidStateError class in src/battles/service.py.

**What it was:** The service originally defined its own BattleInvalidStateError inheriting http_status = 500 (the default from TradingPlatformError). Any validation error at the service layer raised this local exception, which the global handler serialized as 500 instead of 409 Conflict.

**The fix (present in current code):**

The local class was deleted. service.py now imports from src.utils.exceptions at line 30:

    from src.utils.exceptions import BattleInvalidStateError, PermissionDeniedError

The canonical BattleInvalidStateError (exceptions.py lines 920-942) has http_status = 409 and code = "BATTLE_INVALID_STATE".

---

## Verification: Current Code Is Correct

All relevant code was read and confirmed correct as of this investigation:

| File | Lines | Finding |
|------|-------|---------|
| src/api/routes/battles.py | 138 | .model_dump(mode="json") present |
| src/battles/service.py | 30 | Imports from src.utils.exceptions |
| src/utils/exceptions.py | 920-942 | BattleInvalidStateError has http_status = 409 |
| src/battles/service.py | 139-155 | create_battle() raises BattleInvalidStateError when historical + no backtest_config |
| src/battles/historical_engine.py | 128-188 | initialize() parses ISO strings via datetime.fromisoformat() |

---

## Steps to Reproduce the Original Bug (Reference Only)

**The datetime crash** -- any valid historical create request:

    POST /api/v1/battles
    Authorization: Bearer <jwt>
    { "name": "Test", "battle_mode": "historical",
      "backtest_config": { "start_time": "2024-01-01T00:00:00Z",
                           "end_time":   "2024-01-08T00:00:00Z",
                           "candle_interval": 60 } }

Old code: 500 (DataError on JSONB flush). Current code: 201 Created.

**The wrong-status bug** -- missing backtest_config:

    POST /api/v1/battles
    { "name": "Missing Config", "battle_mode": "historical" }

Old code: 500. Current code: 409 BATTLE_INVALID_STATE.

---

## Remaining Operational Constraints (Not Bugs)

### 1. Historical candle data must exist for the date range

HistoricalBattleEngine.initialize() raises a bare ValueError("No historical data found") when zero candles are returned. This ValueError is not a TradingPlatformError subclass so it surfaces as a 500. The BattleRunner must verify data availability before running battles.

Mitigation: Run python scripts/backfill_history.py or check GET /api/v1/market/data-range.

A proper fix: wrap this ValueError in BacktestNoDataError (HTTP 400, already in the hierarchy) inside initialize(). That is a separate improvement.

### 2. Agents must be provisioned before battle creation

initialize() queries each agent_id from the agents table. If not found, no exception is raised -- account_id for that agent BacktestSession is silently set to None. The current BattleRunner provisions agents first. That pattern must be preserved.

### 3. In-memory engine lost on server restart

The HistoricalBattleEngine lives in _active_engines (module-level dict). Server restart drops all active engines while battle rows remain status "active" in the DB with no recovery mechanism. The evolutionary loop must complete each battle within a single server session.

### 4. JWT required for all battle endpoints

POST /api/v1/battles requires Authorization: Bearer (JWT only -- API key is not accepted). The BattleRunner correctly calls POST /api/v1/auth/login on construction. Any new consumer must do the same.

---

## Impact on Evolutionary Training Pipeline

The BattleRunner in agent/strategies/evolutionary/battle_runner.py uses POST /api/v1/battles to run historical battles for per-agent fitness evaluation (fitness = sharpe - 0.5 * max_drawdown). The 500 error it encountered on 2026-03-18 is resolved. The pipeline is unblocked with no code changes required, subject to:

1. Candle data available for the configured date range
2. Agent provisioning before battle creation (BattleRunner already does this)
3. JWT authentication via POST /api/v1/auth/login on construction (BattleRunner already does this)

---

## Key Files

- src/api/routes/battles.py -- create_battle route, line 138 (datetime fix)
- src/battles/service.py -- line 30 (correct exception import), lines 108-155 (create_battle)
- src/utils/exceptions.py -- BattleInvalidStateError, lines 920-942
- src/battles/historical_engine.py -- HistoricalBattleEngine.initialize(), lines 128-188
- src/api/schemas/battles.py -- HistoricalBattleConfig, lines 29-36
- src/database/repositories/battle_repo.py -- BattleRepository.create_battle(), lines 50-61
- agent/strategies/evolutionary/battle_runner.py -- BattleRunner (consumer of the fixed API)
