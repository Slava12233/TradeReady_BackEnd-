# Fix: Battle Live UI Crash — "Cannot read properties of undefined (reading 'toFixed')"

**Created:** 2026-04-07
**Priority:** HIGH — blocks live battle observation
**Status:** Plan ready

---

## Root Cause Analysis

The crash occurs because there is a **major frontend/backend data shape mismatch** on the live battle endpoint.

### What the backend actually returns

`GET /api/v1/battles/{battle_id}/live` returns `BattleLiveResponse`:

```python
# src/api/schemas/battles.py:120
class BattleLiveResponse(_BaseSchema):
    battle_id: UUID
    status: str
    timestamp: datetime
    participants: list[dict[str, object]]  # untyped dict!
```

Each participant dict from `src/battles/service.py:717-725`:
```python
{
    "agent_id": str,
    "display_name": str,
    "equity": str,         # current equity as string
    "pnl": str,            # total PnL as string
    "pnl_pct": str,        # PnL percentage as string
    "status": str,         # participant status
}
```

**Missing from backend response:**
- `remaining_minutes` / `elapsed_minutes` — NOT in response at all
- `current_equity` — backend sends `equity` (different key name)
- `roi_pct` — backend sends `pnl_pct` (different key name)
- `total_pnl` — backend sends `pnl` (different key name)
- `total_trades` — NOT computed during live
- `win_rate` — NOT computed during live (only on battle completion)
- `sharpe_ratio` — NOT computed during live (only on battle completion)
- `max_drawdown_pct` — NOT computed during live (only on battle completion)
- `rank` — NOT computed during live
- `avatar_url` — NOT included
- `color` — NOT included

### What the frontend expects

`Frontend/src/lib/types.ts:864-887` — `BattleLiveParticipant`:
```typescript
{
    agent_id: string;
    display_name: string;
    avatar_url: string | null;
    color: string | null;
    current_equity: string;      // backend sends "equity"
    roi_pct: string;             // backend sends "pnl_pct"
    total_pnl: string;           // backend sends "pnl"
    total_trades: number;        // NOT in backend response
    win_rate: string | null;     // NOT in backend response
    sharpe_ratio: string | null; // NOT in backend response
    max_drawdown_pct: string | null; // NOT in backend response
    rank: number | null;         // NOT in backend response
    status: ParticipantStatus;
}
```

`BattleLiveResponse`:
```typescript
{
    battle_id: string;
    status: BattleStatus;
    elapsed_minutes: number | null;    // NOT in backend response
    remaining_minutes: number | null;  // NOT in backend response
    participants: BattleLiveParticipant[];
    updated_at: string;                // backend sends "timestamp"
}
```

### Crash locations (all from undefined fields)

| File | Line | Expression | Why it crashes |
|------|------|------------|----------------|
| `AgentPerformanceCard.tsx` | 92 | `parseFloat(p.roi_pct ?? "0")` | `p.roi_pct` is `undefined` (backend sends `pnl_pct`), `?? "0"` saves it — **safe** |
| `AgentPerformanceCard.tsx` | 191 | `roi.toFixed(2)` | Safe due to line 92 fallback — **safe** |
| `AgentPerformanceCard.tsx` | 227 | `String(p.total_trades)` | `undefined` → `"undefined"` — **cosmetic bug** |
| `BattleDetail.tsx` | 312 | `live.remaining_minutes.toFixed(0)` | `remaining_minutes` is `undefined` (not in response). The null guard on line 308 catches `null` but NOT `undefined` — **CRASH** |
| `BattleList.tsx` | 112 | `parseFloat(leader.roi_pct).toFixed(2)` | `roi_pct` is `undefined` → `parseFloat(undefined)` = `NaN` → `NaN.toFixed(2)` = `"NaN"` — **cosmetic bug** |

**Primary crash: `BattleDetail.tsx:312`** — `live.remaining_minutes` is `undefined` (field doesn't exist in backend response). The guard `live.remaining_minutes !== null` passes for `undefined` (since `undefined !== null` is `true`), so it tries to call `.toFixed(0)` on `undefined`.

---

## Fix Plan

### Phase 1: Backend — Enrich the live endpoint response (HIGH priority)

**Goal:** Make the backend return all fields the frontend needs.

#### Task 1.1: Add computed fields to `get_live_snapshot()` in `src/battles/service.py`

**File:** `src/battles/service.py` (lines 704-728)

Add to each participant dict:
- `current_equity` (alias for `equity` — keep both for compatibility)
- `roi_pct` (alias for `pnl_pct` — keep both for compatibility)
- `total_pnl` (alias for `pnl` — keep both for compatibility)
- `avatar_url` from the agent model
- `color` from the BattleParticipant model (if stored) or generate from agent
- `total_trades` — query trade count from the trading repo for this agent during battle period
- `win_rate` — compute from trades if any exist, else `null`
- `sharpe_ratio` — compute from snapshots if enough data, else `null`
- `max_drawdown_pct` — compute from equity snapshots, else `null`
- `rank` — compute live ranking by equity (sort participants by equity descending, assign rank)

#### Task 1.2: Add time fields to the route handler in `src/api/routes/battles.py`

**File:** `src/api/routes/battles.py` (lines 413-418)

Add to the `BattleLiveResponse` construction:
- `elapsed_minutes`: compute from `battle.started_at` to `now`
- `remaining_minutes`: compute from `battle.duration_minutes - elapsed_minutes` (or `null` if no duration limit)
- `updated_at`: rename from `timestamp` or add as alias

#### Task 1.3: Update `BattleLiveResponse` Pydantic schema

**File:** `src/api/schemas/battles.py` (lines 120-127)

Change from untyped `list[dict[str, object]]` to a properly typed response:
```python
class BattleLiveParticipantSchema(_BaseSchema):
    agent_id: UUID
    display_name: str
    avatar_url: str | None = None
    color: str | None = None
    current_equity: str
    roi_pct: str
    total_pnl: str
    total_trades: int
    win_rate: str | None = None
    sharpe_ratio: str | None = None
    max_drawdown_pct: str | None = None
    rank: int | None = None
    status: str

class BattleLiveResponse(_BaseSchema):
    battle_id: UUID
    status: str
    elapsed_minutes: float | None = None
    remaining_minutes: float | None = None
    participants: list[BattleLiveParticipantSchema]
    updated_at: datetime
```

### Phase 2: Frontend — Add null safety guards (MEDIUM priority)

Even after backend fixes, the frontend must be resilient to null/undefined values.

#### Task 2.1: Fix `BattleDetail.tsx` line 308 — remaining_minutes guard

**File:** `Frontend/src/components/battles/BattleDetail.tsx` (line 308)

```tsx
// BEFORE — catches null but not undefined
{live.remaining_minutes !== null && (

// AFTER — catches both null and undefined
{live.remaining_minutes != null && (
```

This is the **primary crash fix**. Using loose equality `!= null` catches both `null` and `undefined`.

#### Task 2.2: Fix `AgentPerformanceCard.tsx` — defensive parsing

**File:** `Frontend/src/components/battles/AgentPerformanceCard.tsx`

Line 92 — already safe via `?? "0"`, no change needed.

Line 227 — `total_trades`:
```tsx
// BEFORE
value={String(p.total_trades)}

// AFTER
value={p.total_trades != null ? String(p.total_trades) : "—"}
```

#### Task 2.3: Fix `BattleList.tsx` line 112 — leader roi_pct guard

**File:** `Frontend/src/components/battles/BattleList.tsx` (line 104)

```tsx
// BEFORE
{leader.roi_pct && (

// AFTER — extra safety
{leader.roi_pct != null && leader.roi_pct !== "" && (
```

#### Task 2.4: Update `BattleLiveResponse` TypeScript type to match backend

**File:** `Frontend/src/lib/types.ts` (lines 880-887)

Ensure the TypeScript interface exactly matches the new backend schema. Add `timestamp` as optional for backward compat if needed.

#### Task 2.5: Fix field name mapping in `use-battle-results.ts` hook (if needed)

If the backend field renames can't happen (keeping `equity` instead of `current_equity`), add a transform in the TanStack Query `select` option to map backend field names to frontend field names.

### Phase 3: Add elapsed time display

#### Task 3.1: Show elapsed time in BattleDetail

Once `elapsed_minutes` is available from the backend, display it alongside remaining time:
```tsx
{live.elapsed_minutes != null && (
  <span>{Math.floor(live.elapsed_minutes)}m elapsed</span>
)}
```

---

## Implementation Order

```
1. Phase 2, Task 2.1  ← IMMEDIATE hotfix (stops the crash)
2. Phase 2, Tasks 2.2-2.3  ← Quick defensive fixes
3. Phase 1, Task 1.3  ← Backend schema update
4. Phase 1, Task 1.2  ← Add time fields to route
5. Phase 1, Task 1.1  ← Enrich participant data
6. Phase 2, Tasks 2.4-2.5  ← Frontend type sync
7. Phase 3  ← Elapsed time display
```

**Quick fix (stops crash immediately):** Change `!== null` to `!= null` on `BattleDetail.tsx:308`. This alone prevents the crash while the backend is enhanced.

---

## Files to Modify

| File | Changes |
|------|---------|
| `src/battles/service.py` | Enrich `get_live_snapshot()` with all participant fields |
| `src/api/routes/battles.py` | Add `elapsed_minutes`, `remaining_minutes`, `updated_at` to response |
| `src/api/schemas/battles.py` | Type the response properly with `BattleLiveParticipantSchema` |
| `Frontend/src/components/battles/BattleDetail.tsx` | Fix `!== null` → `!= null` on line 308 |
| `Frontend/src/components/battles/AgentPerformanceCard.tsx` | Null-safe `total_trades` display |
| `Frontend/src/components/battles/BattleList.tsx` | Defensive `roi_pct` guard |
| `Frontend/src/lib/types.ts` | Sync `BattleLiveResponse` with new backend schema |
| `Frontend/src/hooks/use-battle-results.ts` | Field name mapping if needed |

## Testing

- Run existing battle tests: `pytest tests/ -k battle`
- Manual: create a battle, start it, open `/battles/{id}` — should not crash
- Verify all metrics show appropriate fallback values ("—") when not yet computed
- Verify time remaining/elapsed display correctly
- Verify metrics populate as battle runs and trades happen
