# Battles Module

<!-- last-updated: 2026-03-19 -->

> Agent-vs-agent trading competitions with live monitoring, historical replay, wallet isolation, and ranking.

## What This Module Does

The battles module orchestrates competitive trading sessions between AI agents. It supports two modes:

- **Live battles**: Agents trade against real-time Binance prices using their actual or provisioned wallets. A Celery beat task captures equity snapshots every 5 seconds.
- **Historical battles**: Agents compete on past market data using backtesting infrastructure (shared virtual clock + price feed, isolated per-agent sandboxes). Deterministic and reproducible.

The battle lifecycle follows a state machine: `draft -> pending -> active -> completed`, with `cancelled` reachable from draft/pending/active/paused, and `paused -> active` for resuming.

## Key Files

| File | Purpose |
|------|---------|
| `service.py` | `BattleService` -- full lifecycle orchestrator (create, start, pause, resume, stop, cancel, replay). Coordinates repo, wallet manager, ranking calculator, and historical engine. |
| `snapshot_engine.py` | `SnapshotEngine` -- periodic equity capture for live battles. Queries DB balances + Redis prices to compute equity, unrealized/realized PnL, trade count, open positions per participant. |
| `ranking.py` | `RankingCalculator` + `ParticipantMetrics` dataclass. Delegates to unified metrics calculator (`src.metrics.calculator`). Ranks participants by configurable metric. |
| `wallet_manager.py` | `WalletManager` -- snapshot, provision (fresh mode), and restore agent wallets. Two modes: `fresh` (isolated battle wallet) and `existing` (no-op, agents use real wallets). |
| `presets.py` | 8 frozen `BattlePreset` dataclasses (5 live + 3 historical). `get_preset_config()` returns JSONB-ready config dicts. |
| `historical_engine.py` | `HistoricalBattleEngine` -- shared `TimeSimulator` + `DataReplayer` with per-agent `BacktestSandbox` instances. Module-level registry (`_active_engines`) for in-memory engine tracking. |
| `__init__.py` | Empty module init. |

## Architecture & Patterns

### State Machine

Valid transitions are enforced by `_VALID_TRANSITIONS` dict in `service.py`:

```
draft    -> {pending, cancelled}
pending  -> {active, cancelled}
active   -> {paused, completed, cancelled}
paused   -> {active, completed, cancelled}
```

`BattleInvalidStateError` is raised for illegal transitions.

### Wallet Modes (Live Battles)

Controlled by `config["wallet_mode"]` on the Battle model:

- **`"fresh"`**: On start, `WalletManager.snapshot_wallet()` records pre-battle equity, then `provision_fresh_wallet()` wipes balances and creates a single USDT balance. On stop/cancel, `restore_wallet()` reverts to snapshot. Destructive -- always snapshot first.
- **`"existing"`** (default): No wallet changes. Agents trade with their real balances.

### Historical Engine Registry

`historical_engine.py` maintains a module-level `_active_engines: dict[str, HistoricalBattleEngine]` for in-flight historical battles. Three functions manage it:

- `register_engine(battle_id, engine)` -- called during `_start_historical_battle()`
- `get_engine(battle_id)` -- called by step/order/price endpoints
- `remove_engine(battle_id)` -- called after `_stop_historical_battle()` completes

This is analogous to `BacktestEngine._active` for backtests. If the server restarts, in-memory engines are lost.

### Unified Metrics Pipeline

Both `RankingCalculator` (live) and `HistoricalBattleEngine.complete()` (historical) use `src.metrics.calculator.calculate_unified_metrics()` with appropriate adapters:

- Live: `from_db_trades()` + `from_battle_snapshots()` -> `ParticipantMetrics`
- Historical: `from_sandbox_trades()` + `from_sandbox_snapshots()` -> metrics dict

### Snapshot Capture (Live)

`SnapshotEngine` is called by Celery beat every 5 seconds. For each active participant it queries:
1. `Balance` table (available + locked) for equity
2. `Position` table + `PriceCache` (Redis) for unrealized PnL
3. `Trade` table for realized PnL and trade count

Snapshots are bulk-inserted via `BattleRepository.insert_snapshots_bulk()`.

### Historical Battle Data Persistence

On `complete()`, the historical engine persists per agent:
- A `BacktestSession` row (strategy_label = `battle_{battle_id}`)
- `BacktestTrade` rows from sandbox trades
- `BacktestSnapshot` rows from sandbox snapshots
- `BattleSnapshot` rows (duplicated from sandbox snapshots for the battle replay view)

## Public API / Interfaces

### BattleService (service.py)

```python
class BattleService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None

    # CRUD
    async def create_battle(account_id, name, *, preset, config, ranking_metric, battle_mode, backtest_config) -> Battle
    async def get_battle(battle_id) -> Battle
    async def list_battles(account_id, *, status, limit, offset) -> Sequence[Battle]
    async def update_battle(battle_id, account_id, **fields) -> Battle  # draft only
    async def delete_battle(battle_id, account_id) -> None

    # Participants
    async def add_participant(battle_id, agent_id, account_id) -> BattleParticipant  # draft/pending only
    async def remove_participant(battle_id, agent_id, account_id) -> None
    async def get_participants(battle_id) -> Sequence[BattleParticipant]

    # Lifecycle
    async def start_battle(battle_id, account_id) -> Battle       # requires >= 2 participants
    async def pause_agent(battle_id, agent_id, account_id) -> BattleParticipant
    async def resume_agent(battle_id, agent_id, account_id) -> BattleParticipant
    async def stop_battle(battle_id, account_id) -> Battle
    async def cancel_battle(battle_id, account_id) -> Battle

    # Historical
    async def step_historical(battle_id) -> object
    async def step_historical_batch(battle_id, steps) -> object
    async def place_historical_order(battle_id, agent_id, symbol, side, order_type, quantity, price) -> object
    async def get_historical_prices(battle_id) -> tuple[dict[str, Decimal], datetime]

    # Results & replay
    async def get_live_snapshot(battle_id) -> list[dict]
    async def get_results(battle_id) -> dict                      # completed only
    async def get_replay_data(battle_id, *, limit, offset) -> Sequence
    async def replay_battle(battle_id, account_id, *, override_config, override_agents) -> Battle
```

### SnapshotEngine (snapshot_engine.py)

```python
class SnapshotEngine:
    def __init__(self, session: AsyncSession, price_cache: PriceCache) -> None
    async def capture_battle_snapshots(battle_id: UUID) -> int      # returns snapshot count
    async def capture_all_active_battles() -> int                   # called by Celery beat
```

### RankingCalculator (ranking.py)

```python
class RankingCalculator:
    def compute_participant_metrics(agent_id, start_balance, final_equity, snapshots, trades) -> ParticipantMetrics
    @staticmethod
    def rank_participants(metrics, ranking_metric) -> list[ParticipantMetrics]
```

Supported ranking metrics: `roi_pct`, `total_pnl`, `sharpe_ratio`, `win_rate`, `profit_factor`.

### HistoricalBattleEngine (historical_engine.py)

```python
class HistoricalBattleEngine:
    def __init__(self, battle_id, config, participant_agent_ids, starting_balance, ranking_metric) -> None
    async def initialize(db: AsyncSession) -> None                  # preloads data, creates sandboxes
    async def step() -> HistoricalStepResult                        # advance one candle
    async def step_batch(n: int) -> HistoricalStepResult            # advance N candles
    def place_order(agent_id, symbol, side, order_type, quantity, price) -> OrderResult
    async def complete(db: AsyncSession) -> list[dict]              # close positions, rank, persist
    def get_agent_portfolio(agent_id) -> PortfolioSummary

    # Properties
    is_initialized: bool
    current_prices: dict[str, Decimal]
    virtual_time: datetime | None
```

### Presets (presets.py)

```python
def get_preset(key: str) -> BattlePreset | None
def get_preset_config(key: str) -> dict[str, object]     # JSONB-ready config
def list_presets() -> list[dict[str, object]]             # all presets serialized
```

8 presets: `quick_1h`, `day_trader`, `marathon`, `scalper_duel`, `survival`, `historical_day`, `historical_week`, `historical_month`.

### WalletManager (wallet_manager.py)

```python
class WalletManager:
    def __init__(self, session: AsyncSession) -> None
    async def snapshot_wallet(agent_id, account_id) -> Decimal            # returns total equity
    async def provision_fresh_wallet(agent_id, account_id, starting_balance) -> None  # destructive
    async def restore_wallet(agent_id, account_id, snapshot_balance) -> None
    async def get_agent_equity(agent_id) -> Decimal
```

## Dependencies

**Internal (within src/):**
- `src.backtesting.data_replayer.DataReplayer` -- historical price feed
- `src.backtesting.sandbox.BacktestSandbox` -- isolated in-memory exchange per agent
- `src.backtesting.time_simulator.TimeSimulator` -- shared virtual clock
- `src.metrics.calculator.calculate_unified_metrics` -- unified metrics computation
- `src.metrics.adapters` -- 4 adapter functions for normalizing domain types
- `src.cache.price_cache.PriceCache` -- Redis-backed current prices (live snapshots)
- `src.database.models` -- `Battle`, `BattleParticipant`, `BattleSnapshot`, `Balance`, `Position`, `Trade`, `Agent`, `BacktestSession`, `BacktestTrade`, `BacktestSnapshot`
- `src.database.repositories.battle_repo.BattleRepository` -- battle CRUD and snapshot persistence
- `src.database.repositories.agent_repo.AgentRepository` -- agent lookup
- `src.database.repositories.balance_repo.BalanceRepository` -- balance queries (wallet manager)
- `src.database.repositories.trade_repo.TradeRepository` -- trade queries (live ranking)
- `src.api.websocket.channels.BattleChannel` -- WebSocket notification serialization
- `src.config.Settings` -- app configuration
- `src.utils.exceptions.PermissionDeniedError` -- ownership checks

**External:**
- `sqlalchemy.ext.asyncio.AsyncSession` -- all DB operations
- `structlog` -- structured logging
- `decimal.Decimal` -- all monetary values

## Common Tasks

### Adding a new preset
Add a `BattlePreset` entry to `BATTLE_PRESETS` in `presets.py`. If it is a historical preset, add its candle interval to the `candle_intervals` dict inside `get_preset_config()`.

### Adding a new ranking metric
1. Ensure the metric exists on `UnifiedMetrics` in `src/metrics/calculator.py`
2. Add the attribute to `ParticipantMetrics` dataclass in `ranking.py`
3. Map it in `RankingCalculator.rank_participants()` `metric_attr` dict
4. Update `BattleService._stop_historical_battle()` if the metric key differs from the dataclass attribute

### Changing snapshot interval (live)
The 5-second interval is configured in the Celery beat schedule (`src/tasks/battle_snapshots.py`), not in this module. The `snapshot_interval_seconds=5` passed to `calculate_unified_metrics` in `ranking.py` must match.

### Testing
- Unit: `tests/unit/test_snapshot_engine.py`, `test_snapshot_engine_pnl.py`, `test_battle_ranking.py`, `test_battle_replay.py`, `test_historical_battle_engine.py`
- Integration: `tests/integration/test_battle_endpoints.py`, `test_historical_battle_e2e.py`

## Gotchas & Pitfalls

1. **`provision_fresh_wallet` is destructive.** It deletes all existing balances for the agent. Always call `snapshot_wallet` first. The service layer handles this, but direct `WalletManager` usage must be careful.

2. **Historical engine is in-memory.** If the server restarts, all active `HistoricalBattleEngine` instances are lost. Unlike backtests (which have orphan detection), historical battles currently have no recovery mechanism. The battle will remain in `active` status in the DB with no corresponding engine.

3. **Lazy imports in `service.py`.** `HistoricalBattleEngine`, `get_engine`, `register_engine`, `remove_engine` are imported inside method bodies (`# noqa: PLC0415`) to avoid circular imports. Do not move these to module level.

4. **`battle_mode` accessed via `getattr(battle, "battle_mode", "live")`** in service.py because the column was added in migration 015 and older Battle objects might not have it loaded. This defensive pattern should remain until all battles in the DB have the column.

5. **Snapshot engine skips non-active participants.** Only participants with `status == "active"` get snapshots. Paused agents do not accumulate snapshot data, which creates gaps in their equity curves.

6. **Wallet restore on cancel.** If a battle in `fresh` wallet mode is cancelled, wallets are restored. If in `existing` mode, no restoration happens (agents keep whatever P&L they accumulated).

7. **Historical battle creates BacktestSession rows.** The `complete()` method writes to `backtest_sessions`, `backtest_trades`, and `backtest_snapshots` in addition to `battle_snapshots`. This means historical battle data appears in both the backtest list and the battle replay views.

8. **`RankingCalculator.rank_participants` sorts descending.** All metrics are treated as "higher is better" including `max_drawdown`. If you add a metric where lower is better, you need to handle the sort direction.

9. **BattleService does not commit.** The caller (route handler) is responsible for committing the session. All service methods assume a transactional context provided externally.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
- `2026-03-18` -- Fixed battle creation 500: `model_dump(mode="json")` for datetime serialization in JSONB. Removed local `BattleInvalidStateError` class — now uses the correct one from `src.utils.exceptions` (maps to HTTP 409 instead of 500).
