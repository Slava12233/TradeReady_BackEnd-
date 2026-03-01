---
name: timescaledb-sqlalchemy
description: |
  Teaches the agent how to build and maintain TimescaleDB + async SQLAlchemy for the AiTradingAgent crypto trading platform.
  Use when: adding migrations, models, tables; creating hypertables or continuous aggregates; writing repositories; or working with time-series data in this project.
---

# TimescaleDB + SQLAlchemy

## Stack

- SQLAlchemy 2.0, asyncpg driver, async sessions
- Alembic for migrations
- TimescaleDB for time-series data

## Project Layout

| Purpose | Path |
|---------|------|
| Models | `src/database/models.py` |
| Session factory | `src/database/session.py` |
| Repositories | `src/database/repositories/` |

## Tables

| Table | Purpose |
|-------|---------|
| accounts | User accounts |
| balances | Account balances |
| trading_sessions | Sessions per account |
| orders | Order records |
| trades | Executed trades |
| positions | Open positions |
| ticks | Raw tick data (hypertable) |
| portfolio_snapshots | Portfolio snapshots (hypertable) |
| trading_pairs | Supported pairs |
| audit_log | Audit trail |

## Hypertables

- `ticks`: time-series tick data
- `portfolio_snapshots`: portfolio snapshots over time

## Continuous Aggregates

- `candles_1m`
- `candles_5m`
- `candles_1h`
- `candles_1d`

## Compression & Retention

- Enable compression on chunks older than 7 days
- Retention policy: 90 days for raw ticks

## Repositories

| Repo | Purpose |
|------|---------|
| tick_repo | Tick inserts, queries |
| account_repo | Account CRUD |
| order_repo | Order CRUD |
| trade_repo | Trade execution |
| balance_repo | Balance updates |
| snapshot_repo | Portfolio snapshots |

## Conventions

- All repos use async/await, async sessions.
- Use atomic transactions for trade execution (order + trade + balance updates).
- Use `asyncpg.copy_to_table` (or equivalent) for bulk tick inserts.
- Index on time column for hypertables; add indexes for common filters.
- Use Alembic for migrations; keep migrations idempotent where possible.

## Bulk Inserts

- Prefer `COPY` for bulk tick inserts (e.g. `asyncpg.copy_to_table`).
- Avoid per-row inserts for large tick batches.

## Indexing

- Hypertables: index on time column.
- Add indexes for: account_id, symbol, order_id, status where frequently queried.
- Avoid over-indexing; measure before adding.

## References

- For the complete database schema, see [references/schema.sql](references/schema.sql)
