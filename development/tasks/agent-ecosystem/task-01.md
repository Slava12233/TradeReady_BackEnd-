---
task_id: 01
title: "Database models for agent ecosystem tables"
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
files: ["src/database/models.py"]
---

# Task 01: Database models for agent ecosystem tables

## Assigned Agent: `backend-developer`

## Objective
Add SQLAlchemy ORM models for all 10 new agent ecosystem tables to `src/database/models.py`. These models will be used by the migration in Task 02.

## Tables to Model

1. **agent_sessions** — conversation sessions (FK to `agents.id`)
   - `id` (UUID PK), `agent_id` (FK), `title`, `started_at`, `ended_at`, `summary`, `message_count`, `is_active`

2. **agent_messages** — chat history per session (FK to `agent_sessions.id`)
   - `id` (UUID PK), `session_id` (FK), `role` (enum: user/assistant/system/tool), `content` (TEXT), `tool_calls` (JSONB), `tool_results` (JSONB), `tokens_used` (INT), `created_at`

3. **agent_decisions** — trade decisions with reasoning (FK to `agents.id`, optional FK to `orders.id`)
   - `id` (UUID PK), `agent_id` (FK), `session_id` (FK nullable), `decision_type` (enum: trade/hold/exit/rebalance), `symbol`, `direction` (enum: buy/sell/hold), `confidence` (NUMERIC(5,4)), `reasoning` (TEXT), `market_snapshot` (JSONB), `signals` (JSONB), `risk_assessment` (JSONB), `order_id` (FK nullable), `outcome_pnl` (NUMERIC(20,8) nullable), `outcome_recorded_at` (TIMESTAMP nullable), `created_at`

4. **agent_journal** — trading journal entries (FK to `agents.id`)
   - `id` (UUID PK), `agent_id` (FK), `entry_type` (enum: reflection/insight/mistake/improvement/daily_review/weekly_review), `title`, `content` (TEXT), `market_context` (JSONB), `related_decisions` (JSONB array of decision IDs), `tags` (JSONB array), `created_at`

5. **agent_learnings** — extracted knowledge (FK to `agents.id`)
   - `id` (UUID PK), `agent_id` (FK), `memory_type` (enum: episodic/semantic/procedural), `content` (TEXT), `source` (TEXT — what triggered this learning), `confidence` (NUMERIC(5,4)), `times_reinforced` (INT default 1), `last_accessed_at`, `expires_at` (nullable), `embedding` (JSONB nullable — for future vector search), `created_at`, `updated_at`

6. **agent_feedback** — platform improvement ideas (FK to `agents.id`)
   - `id` (UUID PK), `agent_id` (FK), `category` (enum: missing_data/missing_tool/performance_issue/bug/feature_request), `title`, `description` (TEXT), `priority` (enum: low/medium/high/critical), `status` (enum: new/acknowledged/in_progress/resolved/wont_fix), `resolution_notes` (TEXT nullable), `created_at`, `resolved_at`

7. **agent_permissions** — per-agent capability map (FK to `agents.id`)
   - `id` (UUID PK), `agent_id` (FK, UNIQUE), `role` (enum: viewer/paper_trader/live_trader/admin), `capabilities` (JSONB — dict of capability: bool), `granted_by` (FK to accounts.id), `granted_at`, `updated_at`

8. **agent_budgets** — daily/weekly trade limits (FK to `agents.id`)
   - `id` (UUID PK), `agent_id` (FK, UNIQUE), `max_trades_per_day` (INT), `max_exposure_pct` (NUMERIC(5,2)), `max_daily_loss_pct` (NUMERIC(5,2)), `max_position_size_pct` (NUMERIC(5,2)), `trades_today` (INT default 0), `exposure_today` (NUMERIC(20,8) default 0), `loss_today` (NUMERIC(20,8) default 0), `last_reset_at`, `updated_at`

9. **agent_performance** — rolling strategy stats (FK to `agents.id`)
   - `id` (UUID PK), `agent_id` (FK), `strategy_name`, `period` (enum: daily/weekly/monthly), `period_start`, `period_end`, `total_trades` (INT), `winning_trades` (INT), `total_pnl` (NUMERIC(20,8)), `sharpe_ratio` (NUMERIC(10,4) nullable), `max_drawdown_pct` (NUMERIC(10,4) nullable), `win_rate` (NUMERIC(5,4) nullable), `avg_trade_duration` (INTERVAL nullable), `metadata` (JSONB), `created_at`

10. **agent_observations** — market snapshots at decision points (TimescaleDB hypertable)
    - `time` (TIMESTAMPTZ, part of PK), `agent_id` (FK, part of PK), `decision_id` (FK nullable), `prices` (JSONB), `indicators` (JSONB), `regime` (VARCHAR), `portfolio_state` (JSONB), `signals` (JSONB)

## Files to Create/Modify
- `src/database/models.py` — add all 10 model classes

## Acceptance Criteria
- [ ] All 10 models defined with correct column types, FKs, and indexes
- [ ] Enums defined as Python `enum.Enum` or SQLAlchemy `Enum` types
- [ ] `NUMERIC(20,8)` used for all price/money columns (never float)
- [ ] `agent_observations` includes a comment for hypertable creation (handled in migration)
- [ ] All models have `__tablename__` and `__repr__`
- [ ] FK relationships defined with `relationship()` where useful
- [ ] Models follow existing patterns in `src/database/models.py`

## Dependencies
None — this is the first task.

## Agent Instructions
1. Read `src/database/models.py` to understand existing model patterns
2. Read `src/database/CLAUDE.md` for conventions
3. Add all 10 models at the bottom of `models.py`
4. Use `NUMERIC(20,8)` for price/money, `JSONB` for flexible data, `TEXT` for long strings
5. Create proper indexes on `agent_id` + `created_at` for all tables
6. For `agent_observations`, note it will become a hypertable — PK must include `time`

## Estimated Complexity
High — 10 models with relationships, enums, and indexes. Core foundation for everything.
