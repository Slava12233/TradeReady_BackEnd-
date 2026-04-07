---
type: code-review
date: 2026-04-07
reviewer: code-reviewer
verdict: NEEDS FIXES
scope: battle-live-crash-fix
tags:
  - review
  - battles
  - service
  - schemas
  - frontend
---

# Code Review Report

- **Date:** 2026-04-07 22:26
- **Reviewer:** code-reviewer agent
- **Verdict:** NEEDS FIXES

## Files Reviewed
- `src/api/schemas/battles.py`
- `src/api/routes/battles.py`
- `src/battles/service.py`
- `Frontend/src/components/battles/BattleDetail.tsx`
- `Frontend/src/components/battles/AgentPerformanceCard.tsx`
- `Frontend/src/components/battles/BattleList.tsx`

## CLAUDE.md Files Consulted
- `CLAUDE.md` (root)
- `src/battles/CLAUDE.md`
- `src/api/CLAUDE.md`
- `src/api/routes/CLAUDE.md`
- `src/api/schemas/CLAUDE.md`
- `Frontend/CLAUDE.md`
- `Frontend/src/components/CLAUDE.md`
- `Frontend/src/components/battles/CLAUDE.md`
- `.claude/rules/backend-code-standards.md`
- `.claude/rules/architecture.md`

---

## Critical Issues

### 1. N+1 query loop on a 5-second polling endpoint

**File:** `src/battles/service.py:741-795`

**Rule violated:** Performance / architecture — the live endpoint is polled every 5 seconds by the frontend. The current loop issues **2 × N DB queries inside a for-loop** per poll, plus sorting overhead.

For N participants:
- 1 × `get_by_id(participant.agent_id)` per participant (agent lookup)
- 1 × `get_agent_equity(participant.agent_id)` per participant (balance query)
- 2 × `SELECT COUNT(*)` per participant with trades (total + wins)

For a 4-agent battle this is up to 12 sequential DB round-trips on every 5-second tick. Under any meaningful load this will cause latency accumulation and session pool exhaustion. The CLAUDE.md for the battles module explicitly documents that `SnapshotEngine` already collects trade counts and equity via bulk queries — the service should consume that pre-aggregated data rather than re-querying.

**Fix:** Either (a) delegate to `SnapshotEngine.capture_battle_snapshots()` and read from `BattleSnapshot` rows (already populated every 5 seconds), or (b) batch the agent lookups with a single `WHERE id = ANY(...)` query and replace the per-participant COUNT queries with one aggregated GROUP BY query. At minimum the two separate `SELECT COUNT(*)` calls should be collapsed into one:

```python
stmt_win_total = (
    select(
        sa_func.count().label("total"),
        sa_func.count(
            sa_func.nullif(Trade.realized_pnl <= 0, True)
        ).label("wins"),
    )
    .select_from(Trade)
    .where(
        Trade.agent_id == participant.agent_id,
        Trade.created_at >= since,
    )
)
```

---

### 2. Raw `SELECT` queries bypass the repository layer

**File:** `src/battles/service.py:756-783`

**Rule violated:** Dependency direction — Services must not build and execute raw SQLAlchemy `select()` statements directly. DB access must go through repository classes. The project standard is "Routes → Services → Repositories + Cache → Models + Session". This change issues raw ORM queries on `self._session` from inside the service, bypassing `TradeRepository`.

`TradeRepository` already exists (`src/database/repositories/trade_repo.py`) and is part of the dependency set documented in `src/battles/CLAUDE.md`. Adding a `count_trades_since(agent_id, since)` method to `TradeRepository` (or reusing an existing method) would keep the pattern consistent and make the service testable.

**Fix:** Add a `count_wins_and_total(agent_id: UUID, since: datetime) -> tuple[int, int]` method to `TradeRepository`, inject `TradeRepository` into `BattleService.__init__`, and call it instead of building raw statements inside the service.

---

### 3. Potential `TypeError` on timezone-naive `battle.started_at`

**File:** `src/api/routes/battles.py:414-417`

**Rule violated:** Error handling / type safety.

```python
elapsed_td = now - battle.started_at
```

`now = datetime.now(UTC)` is timezone-aware. `battle.started_at` is a `Mapped[datetime | None]` column defined as `TIMESTAMP(timezone=True)`, which SQLAlchemy returns as a timezone-aware datetime. However if the DB value lacks timezone info (e.g., produced by a migration or a test fixture that inserted a naive datetime), this subtraction raises `TypeError: can't subtract offset-naive and offset-aware datetimes`, crashing the endpoint.

The fix is cheap and defensive:

```python
started = battle.started_at
if started is not None:
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed_td = now - started
```

---

### 4. `float(duration_minutes)` on a `JSONB` field — implicit float conversion of monetary-adjacent config

**File:** `src/api/routes/battles.py:420`

**Rule violated:** While `duration_minutes` is not a monetary value, the broader rule is to avoid opaque `float()` casts on values read directly from JSONB. `battle.config.get("duration_minutes")` can return `int`, `float`, `str`, or `None` depending on how the config was stored. The current code silently converts it with `float(duration_minutes)`, which would crash with `ValueError` if it is a string like `"60"` (valid JSONB) and with `TypeError` if it is `None` (the `if duration_minutes:` guard prevents the `None` case, but a string `"0"` would be falsy and silently skipped).

**Fix:**

```python
try:
    duration_minutes = float(battle.config.get("duration_minutes", 0) or 0)
except (TypeError, ValueError):
    duration_minutes = None
if duration_minutes:
    remaining = max(0.0, duration_minutes - elapsed)
```

---

## Warnings

### W1. `win_rate` computed without an index-covered query path

**File:** `src/battles/service.py:773-784`

The `Trade` table has indexes on `(agent_id)` and `(account_id, created_at)`, but **not** on `(agent_id, created_at)` which is precisely what the new COUNT query filters on. A composite index `(agent_id, created_at)` would make these queries index-only scans. Without it, the plan falls back to a partial sequential scan of all trades for the agent, filtered by date — inefficient for active agents.

This is a performance warning rather than a critical bug because the per-call cost is bounded and the `except Exception` guard prevents crashes. However for high-frequency battles (many trades, polled every 5 seconds) this will degrade over time.

**Fix:** Add a database migration to create `Index("idx_trades_agent_created_at", "agent_id", "created_at")` on the `Trade` table.

---

### W2. `BattleLiveParticipantSchema` fields missing `Field(description=..., examples=[...])`

**File:** `src/api/schemas/battles.py:117-131`

The schemas CLAUDE.md requires every `Field()` to carry `description` and `examples` for OpenAPI doc quality. All fields in the new `BattleLiveParticipantSchema` use bare type annotations with no `Field()` definitions at all. This causes blank OpenAPI docs for the live endpoint response shape.

**Fix:** Add `Field(description="...", examples=["..."])` to each field, consistent with how other schemas in the file define their fields.

---

### W3. Lazy model imports inside a hot-path loop are re-executed on every call

**File:** `src/battles/service.py:756-759`

```python
from sqlalchemy import func as sa_func  # noqa: PLC0415
from sqlalchemy import select  # noqa: PLC0415
from src.database.models import Trade  # noqa: PLC0415
```

These three imports are inside a `for participant in participants` loop. Python caches the module in `sys.modules` so the import itself is cheap, but the lookup + assignment runs on every loop iteration. The docstring for this service already explains that lazy imports are only used for circular-import avoidance — and `sqlalchemy` / `src.database.models` are not circular with `service.py`. These imports should either be moved to module level or at least hoisted above the `for` loop. The `# noqa: PLC0415` suppression is misleading here.

**Fix:** Move the three imports above the `for participant in participants:` loop (still inside the method body if a circular import concern exists, but outside the loop):

```python
since = battle.started_at
if since is not None:
    from sqlalchemy import func as sa_func, select  # noqa: PLC0415
    from src.database.models import Trade  # noqa: PLC0415
    # now enter the loop
```

---

### W4. `AgentPerformanceCard.tsx` missing `"use client"` directive

**File:** `Frontend/src/components/battles/AgentPerformanceCard.tsx:1`

This component uses no hooks itself, but it is already rendered inside `LivePanel` and `ResultsPanel` which are part of `BattleDetail.tsx` (a `"use client"` component). However the component receives props that include `parseFloat()` calls and conditional rendering — these are not hooks so the absence of `"use client"` is technically correct. No change needed, this is a pass.

Actually on re-review: the component does not use React state, effects, or event handlers — it is a pure display component and correctly omits `"use client"`. This is correct per the CLAUDE.md rule: "Pure display components that only receive props do not need it."

---

### W5. `BattleList.tsx` — `leader.roi_pct` accessed on `BattleParticipant`, not `BattleLiveParticipant`

**File:** `Frontend/src/components/battles/BattleList.tsx:105`

```typescript
const roiPct = leader.roi_pct;
```

`leader` comes from `battle.participants` which is typed as `BattleParticipant[]` (the overview-level participant type from `types.ts`). Looking at the `BattleParticipant` type in `types.ts` (lines 808-817), `roi_pct` is typed as `string | null` on `BattleParticipant`. The fix uses `!= null` (loose equality) rather than `!== null`, which correctly handles both `null` and `undefined`. The null-safe logic added is correct for this type.

This is actually a pass — the fix is correct. No change needed.

---

### W6. `elapsed_minutes` and `remaining_minutes` are `float` in the Pydantic schema — may serialize with excessive decimal places in JSON

**File:** `src/api/schemas/battles.py:137-138`

```python
elapsed_minutes: float | None = None
remaining_minutes: float | None = None
```

`float` serializes as a raw IEEE 754 decimal in JSON, e.g. `12.333333333333334`. There is no `@field_serializer` rounding this to a reasonable precision. The frontend calls `.toFixed(0)` which masks the issue, but the raw API response will contain unrounded floats. This is inconsistent with the project standard of using `Decimal` with serializers for all numeric financial/time fields. Consider `Annotated[float, Field(description="Elapsed minutes", examples=[12.5])]` with a field serializer that rounds to 1 decimal place.

---

## Suggestions

### S1. `getattr(agent, "avatar_url", None)` and `getattr(participant, "color", None)` — defensive access suggests schema uncertainty

**File:** `src/battles/service.py:815-816`

Using `getattr(..., None)` on ORM model attributes instead of direct attribute access hides potential `AttributeError`s that would indicate a real model mismatch. If `Agent.avatar_url` and `BattleParticipant.color` are defined columns in `models.py` (which they appear to be), direct attribute access is safer — a missing column would then fail loudly at startup rather than silently returning `None` at runtime. Consider replacing with direct attribute access once confirmed that these columns exist in the models.

---

### S2. `LivePanel` signature includes unused `startingBalance` prop

**File:** `Frontend/src/components/battles/BattleDetail.tsx:288`

```typescript
function LivePanel({ battleId }: { battleId: string; startingBalance: number }) {
```

`startingBalance` is declared in the prop signature but never used in the function body. The same applies to `ResultsPanel`. TypeScript does not flag unused destructured props by default, but this is dead interface surface. Either use the prop or remove it from the signature.

---

### S3. `BattleLiveParticipantSchema.current_equity`, `total_pnl`, `roi_pct`, `win_rate` are typed as `str` but carry numeric semantics — add a `field_serializer` note

**File:** `src/api/schemas/battles.py:124-130`

These string fields hold serialized `Decimal` values (they are pre-stringified in `service.py` via `str(equity)` etc.). The schemas CLAUDE.md documents that `Decimal` fields must use `@field_serializer` to convert to `str`. Because the service already returns `str` and the schema declares `str`, there is no precision risk here — but the pattern deviates from the standard where schemas hold `Decimal` and serializers convert. This is acceptable given the service does the conversion, but worth documenting in a comment for future maintainers.

---

### S4. The `BattleLiveResponse.updated_at` field replaces the old `timestamp` field — consider API backward compatibility

**File:** `src/api/schemas/battles.py:144`

The diff shows `timestamp` was renamed to `updated_at`. Any existing client that reads `response.timestamp` will silently get `undefined`. If this endpoint is consumed by the frontend `useBattleLive` hook, the TypeScript type in `types.ts` (`BattleLiveResponse`) already uses `updated_at` — the type file was updated in sync. However external API consumers using the old field name will break silently. If backward compatibility is required, add `timestamp` as a deprecated alias field for one release cycle.

---

## Passed Checks

- **Dependency direction**: `routes/battles.py` correctly delegates to `BattleService`; no upward imports.
- **Security — SQL injection**: All new queries use SQLAlchemy ORM parameterized expressions (`Trade.agent_id == participant.agent_id`, `Trade.created_at >= since`). No f-strings in SQL. No injection risk.
- **Decimal usage in service**: All monetary arithmetic (`equity`, `pnl`, `roi_pct`, `win_rate`) uses `Decimal` throughout. `str(Decimal)` pattern used for serialization. No `float()` on monetary values.
- **Error handling in service**: The `except Exception: # noqa: BLE001` block is appropriate — it wraps a non-critical enrichment step (trade counting) and fails gracefully to `total_trades=0`. The suppression is legitimate and consistent with the project's BLE001 suppression policy.
- **TypeScript type sync**: `BattleLiveParticipant` and `BattleLiveResponse` in `types.ts` match the new Pydantic schema exactly — `elapsed_minutes`, `remaining_minutes`, `updated_at`, all 13 participant fields are present and correctly typed.
- **Frontend null safety**: `BattleDetail.tsx` correctly uses `!= null` (not `!== null`) for `remaining_minutes`, which guards both `null` and `undefined` as intended.
- **Frontend design tokens**: All color usage in changed files uses `text-profit`, `text-loss`, `text-accent`, `text-muted-foreground`, `border-border`. No hardcoded hex colors introduced.
- **`font-mono tabular-nums`**: Applied correctly to all numeric displays in `BattleDetail.tsx` (elapsed/remaining time, equity) and `AgentPerformanceCard.tsx`.
- **Named exports**: All three frontend components use named exports, no default exports.
- **`"use client"` placement**: `BattleDetail.tsx` and `BattleList.tsx` correctly have `"use client"` at line 1. `AgentPerformanceCard.tsx` correctly omits it (pure display component).
- **Pydantic v2 patterns**: `_BaseSchema` inherited correctly; `ConfigDict` used. No deprecated v1 patterns.
- **Battle state machine**: `tabsForStatus()` in `BattleDetail.tsx` correctly handles all 6 states: draft, pending, active, paused, completed, cancelled.
- **Middleware execution order**: Not changed; no regressions.
- **Auth patterns**: Route still uses `CurrentAccountDep` and `battle.account_id != account.id` ownership check.
- **API prefix**: Endpoint remains under `/api/v1/battles/`.
- **Naming conventions**: All new Python identifiers follow `snake_case`; TypeScript identifiers follow `camelCase`/`PascalCase` as required.
