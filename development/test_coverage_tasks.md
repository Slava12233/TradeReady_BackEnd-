# Test Coverage Tasks — Full Gap Fill Plan

**Branch:** V.0.0.2
**Created:** 2026-03-17
**Status:** All phases (1–9) complete
**Current state:** ~884 test cases across 58 unit + 20 integration files. All major subsystems tested: Celery tasks, API endpoints, repository CRUD, price ingestion, metrics adapters, middleware, DB session, error scenarios, and WebSocket manager. Shared test infrastructure (factories, markers) added in Phase 9.

---

## Phase 1 — Celery Background Tasks (HIGH PRIORITY)

Zero test coverage today. These tasks run in production every 1–60 seconds. A silent failure here means stale orders, missing snapshots, or orphaned sessions.

### Task 1.1 — `tests/unit/test_task_limit_order_monitor.py`
**Covers:** `src/tasks/limit_order_monitor.py`
**Pattern:** Mock `get_session_factory`, `OrderRepository`, `PriceCache`, `OrderEngine`
**Tests:**
- [x] `test_matches_pending_limit_buy_when_price_drops` — limit buy fills when market price ≤ limit price
- [x] `test_matches_pending_limit_sell_when_price_rises` — limit sell fills when market price ≥ limit price
- [x] `test_triggers_stop_loss_order` — stop-loss triggers when price drops below threshold
- [x] `test_triggers_take_profit_order` — take-profit triggers when price rises above threshold
- [x] `test_skips_already_filled_orders` — does not re-process filled/cancelled orders
- [x] `test_no_pending_orders_returns_zero` — returns `{"matched": 0}` when nothing to match
- [x] `test_individual_order_failure_does_not_abort_batch` — one order error logs but continues processing others
- [x] `test_session_factory_called_and_closed` — DB session is properly created and closed
- [x] `test_sync_wrapper_calls_async_impl` — sync Celery entry point calls the async implementation

### Task 1.2 — `tests/unit/test_task_battle_snapshots.py`
**Covers:** `src/tasks/battle_snapshots.py`
**Pattern:** Mock `BattleRepository`, `SnapshotEngine`, `PriceCache`
**Tests:**
- [x] `test_captures_snapshot_for_active_battle` — creates equity snapshot for each active participant
- [x] `test_skips_non_active_battles` — ignores draft/completed/cancelled battles
- [x] `test_auto_completes_expired_battle` — battle past `end_time` is auto-stopped and ranked
- [x] `test_snapshot_includes_all_participants` — snapshot covers every participant, not just first
- [x] `test_individual_battle_failure_isolated` — error in one battle does not skip others
- [x] `test_returns_count_of_snapshots_captured` — return dict has `{"snapshots": N, "completed": M}`
- [x] `test_no_active_battles_returns_zero` — graceful no-op when nothing is active

### Task 1.3 — `tests/unit/test_task_backtest_cleanup.py`
**Covers:** `src/tasks/backtest_cleanup.py`
**Pattern:** Mock `BacktestRepository`, DB session
**Tests:**
- [x] `test_cancels_stale_running_sessions` — sessions running > threshold marked as failed
- [x] `test_deletes_old_detail_data` — snapshots/trades older than retention deleted
- [x] `test_preserves_recent_sessions` — sessions within retention window untouched
- [x] `test_preserves_completed_session_summary` — session row kept even when detail data pruned
- [x] `test_returns_cleanup_counts` — return dict has `{"cancelled": N, "deleted_details": M}`
- [x] `test_empty_database_no_op` — no sessions = no errors, returns zeros

### Task 1.4 — `tests/unit/test_task_portfolio_snapshots.py`
**Covers:** `src/tasks/portfolio_snapshots.py`
**Pattern:** Mock `SnapshotRepository`, `BalanceRepository`, `PriceCache`
**Tests:**
- [x] `test_captures_equity_snapshot_per_account` — snapshot row per active account
- [x] `test_snapshot_includes_position_values` — equity = cash + sum(position × price)
- [x] `test_skips_accounts_with_no_activity` — inactive accounts not snapshotted
- [x] `test_individual_account_failure_isolated` — one account error does not abort batch
- [x] `test_returns_snapshot_count` — return dict with `{"snapshots": N}`

### Task 1.5 — `tests/unit/test_task_candle_aggregation.py`
**Covers:** `src/tasks/candle_aggregation.py`
**Pattern:** Mock DB session, raw SQL execution
**Tests:**
- [x] `test_refreshes_materialized_views` — calls REFRESH on OHLCV views
- [x] `test_handles_empty_tick_data` — no ticks = no error, views still refreshed
- [x] `test_returns_success_status` — return dict confirms completion

### Task 1.6 — `tests/unit/test_task_cleanup.py`
**Covers:** `src/tasks/cleanup.py`
**Pattern:** Mock `OrderRepository`, `SnapshotRepository`, DB session
**Tests:**
- [x] `test_cancels_expired_pending_orders` — orders past expiry window cancelled
- [x] `test_prunes_old_tick_data` — ticks older than retention deleted
- [x] `test_prunes_old_portfolio_snapshots` — snapshots older than retention deleted
- [x] `test_returns_cleanup_counts` — return dict with per-category counts
- [x] `test_no_expired_data_returns_zeros` — graceful no-op

---

## Phase 2 — API Route Endpoint Tests (HIGH PRIORITY)

Four route modules with zero endpoint-level tests. These are the contract between frontend/SDK and backend.

### Task 2.1 — `tests/integration/test_agent_endpoints.py`
**Covers:** `src/api/routes/agents.py` (11 endpoints)
**Pattern:** `create_app()` + `TestClient`, JWT auth via `_authenticate_request` patch, dependency overrides for `AgentService`
**Tests:**
- [x] `test_create_agent_returns_201` — POST /agents returns agent + API key (shown once)
- [x] `test_create_agent_with_custom_balance` — custom starting_balance echoed
- [x] `test_create_agent_requires_jwt_auth` — 401 without JWT
- [x] `test_create_agent_missing_display_name_returns_422` — 422 with missing required fields
- [x] `test_create_agent_empty_display_name_returns_422` — min_length violation
- [x] `test_create_agent_negative_balance_returns_422` — gt=0 violation
- [x] `test_create_agent_with_all_fields` — all optional fields accepted
- [x] `test_list_agents_returns_agents` — GET /agents scoped to account
- [x] `test_list_agents_returns_empty_list` — returns empty list, not error
- [x] `test_list_agents_with_query_params` — include_archived, limit, offset
- [x] `test_overview_returns_agents` — GET /agents/overview returns agents with summary stats
- [x] `test_overview_empty` — empty overview returns empty list
- [x] `test_get_agent_returns_agent` — GET /agents/{id} returns agent detail
- [x] `test_get_agent_not_found_returns_500` — nonexistent agent returns 500
- [x] `test_get_agent_wrong_account_returns_403` — 403 for another account's agent
- [x] `test_get_agent_response_shape` — response includes all expected fields
- [x] `test_update_agent_returns_updated` — PUT /agents/{id} updates config fields
- [x] `test_update_agent_partial_fields` — partial update accepted
- [x] `test_update_agent_empty_body_accepted` — empty body valid
- [x] `test_clone_agent_returns_201` — POST /agents/{id}/clone creates copy with new API key
- [x] `test_clone_agent_with_new_name` — clone with custom name
- [x] `test_reset_agent_returns_agent` — POST /agents/{id}/reset resets balances
- [x] `test_archive_agent_returns_agent` — POST /agents/{id}/archive soft deletes
- [x] `test_delete_agent_returns_204` — DELETE /agents/{id} hard deletes
- [x] `test_delete_agent_permission_denied` — 403 when not owner
- [x] `test_regenerate_key_returns_new_key` — POST /agents/{id}/regenerate-key returns new key
- [x] `test_regenerate_key_contains_message` — response includes message
- [x] `test_skill_md_returns_text_markdown` — GET /agents/{id}/skill.md returns text/markdown
- [x] `test_skill_md_contains_agent_header` — skill file contains agent name and ID
- [x] `test_skill_md_wrong_account_returns_403` — 403 for another account's agent

### Task 2.2 — `tests/integration/test_battle_endpoints.py`
**Covers:** `src/api/routes/battles.py` (20 endpoints)
**Pattern:** `create_app()` + `TestClient`, JWT auth via `_authenticate_request` patch, dependency overrides for `BattleService`
**Tests:**
- [x] `test_create_battle_draft` — POST /battles returns draft battle
- [x] `test_create_battle_with_preset` — preset key populates config
- [x] `test_create_battle_requires_jwt` — 401 without JWT
- [x] `test_list_battles` — GET /battles returns list
- [x] `test_list_battles_with_status_filter` — ?status=active filters correctly
- [x] `test_get_presets` — GET /battles/presets returns 8 presets
- [x] `test_get_battle_by_id` — GET /battles/{id} returns detail with participants
- [x] `test_get_battle_not_found` — 404 when service raises NotFoundError
- [x] `test_update_battle_in_draft` — PUT /battles/{id} updates config
- [x] `test_update_battle_not_draft_rejected` — 409 for non-draft battle
- [x] `test_delete_battle` — DELETE /battles/{id} cancels/deletes (204)
- [x] `test_add_participant` — POST /battles/{id}/participants adds agent (201)
- [x] `test_add_duplicate_participant_rejected` — 409 for already-added agent
- [x] `test_remove_participant` — DELETE /battles/{id}/participants/{agent_id} (204)
- [x] `test_start_battle` — POST /battles/{id}/start transitions to active
- [x] `test_start_battle_needs_min_2` — 409 with < 2 agents
- [x] `test_pause_agent` — POST /battles/{id}/pause/{agent_id}
- [x] `test_resume_agent` — POST /battles/{id}/resume/{agent_id}
- [x] `test_stop_battle` — POST /battles/{id}/stop calculates rankings
- [x] `test_get_live_metrics` — GET /battles/{id}/live returns snapshot
- [x] `test_get_live_metrics_wrong_owner` — 403 for non-owner
- [x] `test_get_results` — GET /battles/{id}/results returns rankings
- [x] `test_get_results_not_completed` — 409 for non-completed battle
- [x] `test_get_replay_data` — GET /battles/{id}/replay returns time-series
- [x] `test_step_historical_battle` — POST /battles/{id}/step advances clock
- [x] `test_step_historical_rejects_live` — 400 for live battle
- [x] `test_step_batch_historical` — POST /battles/{id}/step/batch advances N steps
- [x] `test_place_historical_order` — POST /battles/{id}/trade/order in sandbox
- [x] `test_get_historical_prices` — GET /battles/{id}/market/prices
- [x] `test_replay_battle` — POST /battles/{id}/replay creates new draft (201)

### Task 2.3 — `tests/integration/test_analytics_endpoints.py`
**Covers:** `src/api/routes/analytics.py`
**Pattern:** `create_app()` + `TestClient`, auth via `_authenticate_request` patch, dependency overrides for `PerformanceMetrics`, `SnapshotService`
**Tests:**
- [x] `test_get_performance_all_time` — GET /analytics/performance returns metrics
- [x] `test_get_performance_by_period` — ?period=7d filters correctly
- [x] `test_get_performance_no_trades` — returns zeroed metrics, not error
- [x] `test_get_performance_requires_auth` — 401 without auth
- [x] `test_get_portfolio_history` — GET /analytics/portfolio/history returns time series
- [x] `test_get_portfolio_history_intervals` — ?interval=1d maps to daily snapshot_type
- [x] `test_get_leaderboard` — GET /analytics/leaderboard returns ranked agents
- [x] `test_get_leaderboard_by_period` — ?period=30d filters

### Task 2.4 — `tests/integration/test_account_endpoints.py`
**Covers:** `src/api/routes/account.py`
**Pattern:** `create_app()` + `TestClient`, JWT auth via `_authed_request` helper, dependency overrides for `BalanceManager`, `PortfolioTracker`
**Tests:**
- [x] `test_get_account_info` — GET /account/info returns account status + risk profile
- [x] `test_get_account_info_requires_auth` — 401 without auth
- [x] `test_get_balance` — GET /account/balance returns asset list
- [x] `test_get_balance_requires_auth` — 401 without auth
- [x] `test_get_positions` — GET /account/positions returns open positions
- [x] `test_get_positions_empty` — returns empty list, not error
- [x] `test_get_portfolio` — GET /account/portfolio returns equity summary
- [x] `test_get_pnl` — GET /account/pnl returns PnL breakdown
- [x] `test_get_pnl_by_period` — ?period=7d filters
- [x] `test_update_risk_profile` — PUT /account/risk-profile updates limits
- [x] `test_reset_account` — POST /account/reset resets balances, preserves history

---

## Phase 3 — Repository CRUD Tests (HIGH PRIORITY)

Repositories are the data layer contract. Testing them catches SQL bugs, scoping issues, and constraint violations before they hit production.

### Task 3.1 — `tests/unit/test_account_repo.py`
**Covers:** `src/database/repositories/account_repo.py`
**Pattern:** Mock `AsyncSession`, verify SQL statements
**Tests:**
- [x] `test_create_account` — inserts row, flushes (no commit)
- [x] `test_create_duplicate_api_key_raises` — DuplicateAccountError on api_key violation
- [x] `test_create_duplicate_email_raises` — DuplicateAccountError on email violation
- [x] `test_create_db_error_raises` — DatabaseError on generic error
- [x] `test_get_by_id_returns_account` — returns account when found
- [x] `test_get_by_id_not_found_raises` — AccountNotFoundError when no row
- [x] `test_get_by_id_db_error_raises` — DatabaseError on SQLAlchemy error
- [x] `test_get_by_api_key_returns_account` — looks up by API key
- [x] `test_get_by_api_key_not_found_raises` — AccountNotFoundError for missing key
- [x] `test_get_by_email_returns_account` — looks up by email
- [x] `test_get_by_email_not_found_raises` — AccountNotFoundError for missing email
- [x] `test_update_status_returns_updated` — updates status, returns model
- [x] `test_update_status_not_found_raises` — AccountNotFoundError when missing
- [x] `test_update_risk_profile_succeeds` — updates risk_profile field
- [x] `test_update_risk_profile_not_found_raises` — AccountNotFoundError when missing
- [x] `test_list_by_status_returns_accounts` — returns matching accounts
- [x] `test_list_by_status_empty` — returns empty list
- [x] `test_list_by_status_db_error_raises` — DatabaseError on error

### Task 3.2 — `tests/unit/test_balance_repo.py`
**Covers:** `src/database/repositories/balance_repo.py`
**Pattern:** Mock `AsyncSession`, verify SQL statements and Decimal precision
**Tests:**
- [x] `test_get_balance_returns_balance` — returns balance for account+asset
- [x] `test_get_balance_not_found_returns_none` — returns None for missing asset
- [x] `test_get_balance_db_error_raises` — DatabaseError on SQLAlchemy error
- [x] `test_get_by_agent_returns_balance` — scoped to agent_id
- [x] `test_get_by_agent_not_found_returns_none` — returns None for missing pair
- [x] `test_get_all_balances_returns_list` — returns all balances for account
- [x] `test_get_all_empty_returns_empty_list` — returns empty list
- [x] `test_create_balance` — inserts balance row and flushes
- [x] `test_create_duplicate_raises` — DatabaseError on duplicate
- [x] `test_credit_increases_available` — positive delta credits balance
- [x] `test_debit_decreases_available` — negative delta debits balance
- [x] `test_debit_insufficient_raises` — InsufficientBalanceError on CHECK violation
- [x] `test_update_available_not_found_raises` — DatabaseError when row missing
- [x] `test_lock_funds_increases_locked` — positive delta locks funds
- [x] `test_unlock_funds_decreases_locked` — negative delta unlocks funds
- [x] `test_unlock_insufficient_raises` — InsufficientBalanceError on CHECK violation
- [x] `test_atomic_lock_moves_available_to_locked` — atomic available→locked
- [x] `test_atomic_lock_zero_amount_raises_value_error` — rejects zero/negative
- [x] `test_atomic_lock_insufficient_raises` — InsufficientBalanceError
- [x] `test_atomic_unlock_moves_locked_to_available` — atomic locked→available
- [x] `test_atomic_unlock_zero_amount_raises_value_error` — rejects zero/negative

### Task 3.3 — `tests/unit/test_order_repo.py`
**Covers:** `src/database/repositories/order_repo.py`
**Pattern:** Mock `AsyncSession`
**Tests:**
- [x] `test_create_order_inserts_and_flushes` — inserts order, flushes
- [x] `test_create_integrity_error_raises` — DatabaseError on FK violation
- [x] `test_create_db_error_raises` — DatabaseError on generic error
- [x] `test_get_by_id_returns_order` — returns order when found
- [x] `test_get_by_id_not_found_raises` — OrderNotFoundError when no row
- [x] `test_get_by_id_with_account_scope` — adds ownership filter
- [x] `test_list_by_account_returns_orders` — returns orders for account
- [x] `test_list_by_account_with_status_filter` — status filter works
- [x] `test_list_by_account_with_symbol_filter` — symbol filter works
- [x] `test_list_by_account_with_agent_filter` — agent_id filter works
- [x] `test_list_by_agent_returns_orders` — scoped to agent_id
- [x] `test_list_by_agent_db_error_raises` — DatabaseError on error
- [x] `test_list_pending_returns_pending_orders` — filters by status=pending
- [x] `test_list_pending_with_symbol_filter` — filters by symbol+status
- [x] `test_cancel_pending_order_succeeds` — transitions to cancelled
- [x] `test_cancel_filled_order_raises` — OrderNotCancellableError
- [x] `test_update_status_returns_updated` — returns order with new status
- [x] `test_update_status_with_extra_fields` — passes extra_fields to UPDATE
- [x] `test_update_status_not_found_raises` — OrderNotFoundError when missing
- [x] `test_count_open_by_account` — returns count of pending orders
- [x] `test_count_open_by_agent` — returns count for specific agent

### Task 3.4 — `tests/unit/test_trade_repo.py`
**Covers:** `src/database/repositories/trade_repo.py`
**Pattern:** Mock `AsyncSession`
**Tests:**
- [x] `test_create_trade_inserts_and_flushes` — inserts trade, flushes
- [x] `test_create_integrity_error_raises` — DatabaseError on FK violation
- [x] `test_create_db_error_raises` — DatabaseError on generic error
- [x] `test_get_by_id_returns_trade` — returns trade when found
- [x] `test_get_by_id_not_found_raises` — TradeNotFoundError when no row
- [x] `test_get_by_id_with_account_scope` — adds ownership filter
- [x] `test_list_by_account_returns_trades` — scoped to account_id
- [x] `test_list_by_account_with_symbol_filter` — filters by symbol
- [x] `test_list_by_account_with_side_filter` — filters by buy/sell
- [x] `test_list_by_account_with_agent_filter` — scoped to agent_id
- [x] `test_list_by_account_with_pagination` — limit + offset work correctly
- [x] `test_list_by_account_db_error_raises` — DatabaseError on error
- [x] `test_list_by_agent_returns_trades` — scoped to agent_id
- [x] `test_list_by_symbol_returns_trades` — filters by symbol
- [x] `test_list_by_symbol_empty` — returns empty list for unknown symbol
- [x] `test_get_trade_count` — returns total count for account
- [x] `test_get_trade_count_with_agent` — scoped to agent_id
- [x] `test_get_trade_count_db_error_raises` — DatabaseError on error
- [x] `test_sum_daily_realized_pnl_returns_decimal` — returns Decimal sum
- [x] `test_sum_daily_realized_pnl_zero_when_no_trades` — returns 0
- [x] `test_sum_daily_realized_pnl_with_specific_day` — accepts day parameter

### Task 3.5 — `tests/unit/test_tick_repo.py`
**Covers:** `src/database/repositories/tick_repo.py`
**Pattern:** Mock `AsyncSession`, TimescaleDB-specific queries
**Tests:**
- [x] `test_get_latest_returns_tick` — returns most recent tick
- [x] `test_get_latest_no_ticks_returns_none` — returns None when no tick
- [x] `test_get_latest_db_error_raises` — DatabaseError on error
- [x] `test_get_range_returns_ticks` — returns ticks within time range
- [x] `test_get_range_with_limit` — limit parameter respected
- [x] `test_get_range_empty_returns_empty_list` — no ticks returns empty list
- [x] `test_get_range_db_error_raises` — DatabaseError on error
- [x] `test_get_price_at_returns_tick` — returns tick closest to target time
- [x] `test_get_price_at_no_data_returns_none` — returns None when no data
- [x] `test_count_in_range_returns_count` — returns integer count
- [x] `test_count_in_range_empty_returns_zero` — returns 0 when no ticks
- [x] `test_get_vwap_returns_decimal` — returns VWAP as Decimal
- [x] `test_get_vwap_no_ticks_returns_none` — returns None when no ticks
- [x] `test_get_vwap_db_error_raises` — DatabaseError on error

### Task 3.6 — `tests/unit/test_snapshot_repo.py`
**Covers:** `src/database/repositories/snapshot_repo.py`
**Pattern:** Mock `AsyncSession`
**Tests:**
- [x] `test_create_snapshot_inserts_and_flushes` — inserts portfolio snapshot
- [x] `test_create_integrity_error_raises` — DatabaseError on constraint violation
- [x] `test_create_db_error_raises` — DatabaseError on generic error
- [x] `test_get_history_returns_snapshots` — returns snapshots for account
- [x] `test_get_history_by_agent` — scoped to agent_id
- [x] `test_get_history_with_time_bounds` — since/until filtering
- [x] `test_get_history_with_limit` — limit parameter respected
- [x] `test_get_history_empty_returns_empty` — returns empty list
- [x] `test_get_history_db_error_raises` — DatabaseError on error
- [x] `test_get_latest_returns_snapshot` — returns most recent snapshot
- [x] `test_get_latest_no_snapshot_returns_none` — returns None when empty
- [x] `test_list_by_account_returns_snapshots` — returns all snapshot types
- [x] `test_delete_old_snapshots` — prunes snapshots older than cutoff
- [x] `test_delete_before_no_old_data_returns_zero` — returns 0 when nothing to prune
- [x] `test_delete_before_db_error_raises` — DatabaseError on error

---

## Phase 4 — Price Ingestion Service (MEDIUM PRIORITY)

The live price feed is the heartbeat of the platform. Currently untested at the service/connection level.

### Task 4.1 — `tests/unit/test_price_ingestion_service.py`
**Covers:** `src/price_ingestion/service.py`
**Pattern:** Mock `BinanceWebSocket`, `PriceCache`, `TickBuffer`, `PriceBroadcaster`
**Tests:**
- [x] `test_service_initializes_dependencies` — creates WS client, cache, buffer, broadcaster
- [x] `test_processes_tick_message` — incoming WS message → cache update + buffer append
- [x] `test_shutdown_flushes_buffer` — pending ticks flushed on shutdown
- [x] `test_shutdown_closes_connections` — Redis and DB connections closed cleanly
- [x] `test_handles_fatal_error_in_loop` — cleanup runs, then re-raises
- [x] `test_request_shutdown_sets_flag` — signal handler sets module flag

### Task 4.2 — `tests/unit/test_binance_ws.py`
**Covers:** `src/price_ingestion/binance_ws.py`
**Pattern:** Mock `websockets`, test message parsing
**Tests:**
- [x] `test_parses_trade_message` — Binance trade JSON → Tick namedtuple
- [x] `test_parses_price_fields_as_decimal` — price/quantity are Decimal, not float
- [x] `test_parses_timestamp_as_utc_datetime` — milliseconds → UTC datetime
- [x] `test_parses_buyer_maker_flag` — boolean correctly parsed
- [x] `test_ignores_non_trade_messages` — heartbeats/errors skipped
- [x] `test_ignores_malformed_json` — bad JSON returns None
- [x] `test_ignores_missing_fields` — missing required fields returns None
- [x] `test_ignores_empty_data` — no data field returns None
- [x] `test_single_chunk_url` — few symbols produce single URL
- [x] `test_multiple_chunks_for_many_symbols` — >max_streams produces multiple URLs
- [x] `test_subscribes_to_correct_stream_names` — lowercase symbol + @trade suffix
- [x] `test_empty_symbols_returns_empty` — no symbols → no URLs
- [x] `test_get_all_pairs_returns_copy` — returns copy, not reference

---

## Phase 5 — Metrics Adapters & Middleware (MEDIUM PRIORITY)

### Task 5.1 — `tests/unit/test_metrics_adapters.py`
**Covers:** `src/metrics/adapters.py`
**Pattern:** Build domain objects, verify conversion to `MetricTradeInput`/`MetricSnapshotInput`
**Tests:**
- [x] `test_from_sandbox_trades_converts_fields` — SandboxTrade → MetricTradeInput with correct Decimal fields
- [x] `test_from_sandbox_trades_empty_list` — [] → []
- [x] `test_from_sandbox_trades_preserves_order` — output order matches input order
- [x] `test_from_sandbox_snapshots_converts_fields` — SandboxSnapshot → MetricSnapshotInput
- [x] `test_from_sandbox_snapshots_empty_list` — [] → []
- [x] `test_from_sandbox_snapshots_preserves_order` — output order matches input order
- [x] `test_from_db_trades_converts_fields` — DB Trade model → MetricTradeInput
- [x] `test_from_db_trades_handles_none_pnl` — trade with None pnl passes through
- [x] `test_from_db_trades_empty_list` — [] → []
- [x] `test_from_battle_snapshots_converts_fields` — BattleSnapshot → MetricSnapshotInput
- [x] `test_from_battle_snapshots_decimal_passthrough` — already-Decimal values not double-converted
- [x] `test_from_battle_snapshots_non_decimal_converted` — float equity → Decimal
- [x] `test_from_battle_snapshots_empty_list` — [] → []

### Task 5.2 — `tests/unit/test_rate_limit_middleware.py`
**Covers:** `src/api/middleware/rate_limit.py`
**Pattern:** Build ASGI app with middleware, mock Redis for rate counters
**Tests:**
- [x] `test_orders_tier` — trade paths resolve to orders tier (100/min)
- [x] `test_market_data_tier` — market paths resolve to market_data tier (1200/min)
- [x] `test_general_tier` — other /api/v1/ paths resolve to general tier (600/min)
- [x] `test_unknown_path_defaults_to_general` — unknown paths default to general
- [x] `test_health_is_public` — /health bypasses rate limiting
- [x] `test_docs_is_public` — /docs bypasses rate limiting
- [x] `test_auth_is_public` — /api/v1/auth/ bypasses rate limiting
- [x] `test_trade_is_not_public` — trade paths are not public
- [x] `test_allows_request_under_limit` — request passes through with headers
- [x] `test_rate_limit_headers_present` — X-RateLimit-* headers injected
- [x] `test_public_path_bypasses_rate_limit` — health endpoint passes through
- [x] `test_unauthenticated_request_passes_through` — no account passes through
- [x] `test_redis_failure_allows_request` — fail-open on Redis error

### Task 5.3 — `tests/unit/test_logging_middleware.py`
**Covers:** `src/api/middleware/logging.py`
**Pattern:** Build ASGI app with middleware, capture log output
**Tests:**
- [x] `test_uses_x_forwarded_for_first` — prefers XFF header for client IP
- [x] `test_falls_back_to_client_host` — falls back to direct client address
- [x] `test_returns_unknown_when_no_client` — returns 'unknown' when no info
- [x] `test_logs_request_method_and_path` — structured log includes method, path
- [x] `test_logs_response_status_code` — structured log includes status code
- [x] `test_logs_request_duration` — latency_ms field present
- [x] `test_excludes_health_check` — /health not logged (noise reduction)
- [x] `test_excludes_metrics_endpoint` — /metrics not logged
- [x] `test_assigns_request_id` — request_id UUID included in log
- [x] `test_logs_error_for_5xx` — 5xx responses logged at error level

---

## Phase 6 — Database & Session (MEDIUM PRIORITY)

### Task 6.1 — `tests/unit/test_database_session.py`
**Covers:** `src/database/session.py`
**Pattern:** Mock `create_async_engine`, `async_sessionmaker`
**Tests:**
- [x] `test_creates_engine_with_database_url` — engine created with DATABASE_URL from settings
- [x] `test_engine_pool_settings` — pool_size=10, max_overflow=20, pool_pre_ping=True
- [x] `test_get_engine_creates_on_first_call` — lazy engine creation
- [x] `test_get_engine_returns_cached` — singleton caching
- [x] `test_creates_factory_on_first_call` — session factory creation
- [x] `test_returns_cached_factory` — factory singleton caching
- [x] `test_raises_if_not_initialized` — RuntimeError if pool not init'd
- [x] `test_returns_pool_after_init` — pool returned after init
- [x] `test_closes_pool_and_engine` — close_db disposes all resources
- [x] `test_close_db_no_op_when_not_initialized` — no error when nothing to close

---

## Phase 7 — Error Scenario & Edge Case Tests (MEDIUM PRIORITY)

### Task 7.1 — `tests/unit/test_error_scenarios.py`
**Covers:** Cross-cutting error handling across services
**Tests:**
- [x] `test_all_exceptions_have_to_dict` — all platform exceptions serialize
- [x] `test_insufficient_balance_includes_details` — asset/required/available in details
- [x] `test_order_not_cancellable_includes_status` — order_id/status in details
- [x] `test_price_not_available_includes_symbol` — symbol in details
- [x] `test_http_status_codes_correct` — each exception has correct HTTP status
- [x] `test_order_repo_not_found_raises` — OrderNotFoundError for missing order
- [x] `test_balance_repo_debit_insufficient_raises` — InsufficientBalanceError on CHECK violation
- [x] `test_atomic_lock_rejects_zero_amount` — ValueError for zero amount
- [x] `test_atomic_lock_rejects_negative_amount` — ValueError for negative amount
- [x] `test_trade_not_found_raises` — TradeNotFoundError for missing trade
- [x] `test_account_not_found_by_id` — AccountNotFoundError by UUID
- [x] `test_account_not_found_by_api_key` — AccountNotFoundError by API key

### Task 7.2 — `tests/unit/test_decimal_edge_cases.py`
**Covers:** Decimal precision across order engine, balance, sandbox
**Tests:**
- [x] `test_very_small_quantity` — 0.00000001 BTC processes correctly
- [x] `test_very_large_quantity` — max precision Decimal(20,8) boundary
- [x] `test_zero_balance_after_exact_sell` — exact sell leaves 0, not -0.00000001
- [x] `test_fee_rounding_small_order` — fee on small order rounds correctly (no negative fee)
- [x] `test_slippage_on_very_low_price` — very low price + slippage stays positive
- [x] `test_pnl_precision` — realized PnL matches manual calculation
- [x] `test_decimal_division_precision` — division preserves Decimal type
- [x] `test_negative_zero_equals_zero` — Decimal('-0') == Decimal('0')
- [x] `test_sandbox_initializes_with_decimal_balance` — BacktestSandbox uses Decimal
- [x] `test_sandbox_no_positions_initially` — empty positions list

---

## Phase 8 — WebSocket & Connection Tests (LOW PRIORITY)

### Task 8.1 — `tests/unit/test_ws_manager.py`
**Covers:** `src/api/websocket/manager.py`
**Pattern:** Mock WebSocket connections
**Tests:**
- [x] `test_add_subscription` — channel added to subscription set
- [x] `test_add_subscription_idempotent` — duplicate add is no-op
- [x] `test_add_subscription_cap_reached` — cap (10) enforced
- [x] `test_remove_subscription` — channel removed from set
- [x] `test_remove_nonexistent_subscription` — no-op for unknown channel
- [x] `test_is_subscribed` — returns correct boolean
- [x] `test_notify_pong_sets_event` — pong event set
- [x] `test_initial_state` — new manager has 0 connections
- [x] `test_subscribe_to_channel` — client added to channel
- [x] `test_subscribe_unknown_connection` — returns False
- [x] `test_unsubscribe_from_channel` — client removed from channel
- [x] `test_unsubscribe_unknown_connection` — no-op
- [x] `test_get_subscriptions_unknown` — returns empty set
- [x] `test_get_connection` — returns Connection or None
- [x] `test_broadcast_to_channel` — message sent to all subscribers
- [x] `test_broadcast_to_account` — message sent to all account connections
- [x] `test_broadcast_skips_disconnected` — dead connections handled
- [x] `test_disconnect_removes_from_pool` — connection cleaned up
- [x] `test_disconnect_unknown_is_noop` — no error for unknown
- [x] `test_notify_pong` — manager signals correct connection
- [x] `test_notify_pong_unknown` — no error for unknown
- [x] `test_account_connection_ids` — returns all IDs for account
- [x] `test_account_connection_ids_unknown` — returns empty set

---

## Phase 9 — Shared Test Infrastructure (LOW PRIORITY)

### Task 9.1 — Add shared fixtures to `tests/conftest.py`
**Goal:** Reduce duplication across test files
**Items:**
- [x] `make_account(display_name, balance)` — factory for Account model
- [x] `make_agent(account_id, name, risk_profile)` — factory for Agent model
- [x] `make_order(symbol, side, type, quantity, price, status)` — factory for Order model
- [x] `make_trade(symbol, side, quantity, price, fee, pnl)` — factory for Trade model
- [x] `make_battle(name, status, mode, config)` — factory for Battle model
- [x] `make_balance(asset, available, locked)` — factory for Balance model
- [x] `mock_db_session` — shared `AsyncSession` mock with execute/flush/commit/rollback
- [x] `mock_price_cache` — shared `PriceCache` mock with get_price/set_price

### Task 9.2 — Add test markers and categories
**Goal:** Run test subsets quickly
**Items:**
- [x] Add `@pytest.mark.slow` to integration tests that need full app startup
- [x] Add `@pytest.mark.celery` to Celery task tests
- [x] Register markers in `pyproject.toml`
- [x] Document marker usage below

**Marker usage:**
- `pytest -m celery` — run only Celery task tests (88 tests)
- `pytest -m slow` — run only slow integration tests (422 tests)
- `pytest -m "not slow"` — skip integration tests for fast feedback
- `pytest -m "not celery"` — skip Celery task tests

---

## Execution Order & Dependencies

```
Phase 1 (Celery tasks)    ← no dependencies, start here
Phase 2 (API routes)      ← no dependencies, can parallelize with Phase 1
Phase 3 (Repositories)    ← no dependencies, can parallelize
Phase 4 (Price ingestion) ← after Phase 1 (similar patterns)
Phase 5 (Adapters/middleware) ← after Phase 3 (uses repo patterns)
Phase 6 (DB session)      ← after Phase 3
Phase 7 (Error scenarios) ← after Phases 1-3 (needs service understanding)
Phase 8 (WebSocket)       ← after Phase 2
Phase 9 (Infrastructure)  ← after Phase 3 (knows what to extract)
```

---

## Conventions Checklist (applied to every new test file)

- [x] `async def test_*()` — no `@pytest.mark.asyncio` needed (asyncio_mode=auto)
- [x] `AsyncMock` for async deps, `MagicMock` for sync
- [x] `Decimal("...")` for all money/price values — never `float`
- [x] `datetime(..., tzinfo=UTC)` for all timestamps
- [x] `uuid4()` for test IDs
- [x] Helpers prefixed with `_` (e.g., `_make_order_mock()`)
- [x] Test classes group related tests: `class TestCreate:`, `class TestUpdate:`
- [x] File header: `from __future__ import annotations`
- [x] After writing: `ruff check tests/unit/test_*.py` passes
- [x] After writing: `pytest tests/unit/test_*.py` passes

---

## Summary

| Phase | Files | Test Cases | Status |
|-------|-------|------------|--------|
| 1. Celery Tasks | 6 | 38 | DONE |
| 2. API Routes | 4 | 68 | DONE |
| 3. Repositories | 6 | 110 | DONE |
| 4. Price Ingestion | 2 | 19 | DONE |
| 5. Adapters/Middleware | 3 | 36 | DONE |
| 6. DB Session | 1 | 10 | DONE |
| 7. Error Scenarios | 2 | 22 | DONE |
| 8. WebSocket Manager | 1 | 23 | DONE |
| 9. Infrastructure | — | — | DONE |
| **Total new** | **25** | **326** | **ALL DONE** |

All 326 new test cases pass. Combined with the ~558 existing tests, the project now has ~884 test cases across 58 unit + 20 integration files.
