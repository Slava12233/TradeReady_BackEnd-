# Test Case Specifications

Detailed test case specifications for the AiTradingAgent platform.

## Unit Tests

### test_order_engine.py

- test_market_buy_executes_at_current_price
- test_market_sell_executes_at_current_price
- test_limit_buy_queued_when_price_above_target
- test_limit_buy_executes_when_price_at_target
- test_stop_loss_triggers_when_price_drops
- test_take_profit_triggers_when_price_rises
- test_order_rejected_insufficient_balance
- test_order_rejected_invalid_symbol
- test_order_rejected_zero_quantity
- test_order_rejected_account_suspended
- test_cancel_pending_order_unlocks_funds
- test_cancel_filled_order_fails

### test_slippage.py

- test_small_order_minimal_slippage
- test_large_order_significant_slippage
- test_buy_slippage_increases_price
- test_sell_slippage_decreases_price
- test_fee_calculation_correct

### test_risk_manager.py

- test_order_within_all_limits_approved
- test_position_size_exceeded_rejected
- test_daily_loss_limit_blocks_trading
- test_max_open_orders_exceeded
- test_min_order_size_rejected
- test_rate_limit_exceeded
- test_custom_risk_profile_applied

### test_balance_manager.py

- test_credit_increases_available
- test_debit_decreases_available
- test_debit_below_zero_fails
- test_lock_moves_from_available_to_locked
- test_unlock_moves_from_locked_to_available
- test_execute_trade_buy_updates_both_assets
- test_execute_trade_sell_updates_both_assets
- test_atomic_trade_execution

### test_portfolio_metrics.py

- test_sharpe_ratio_calculation
- test_max_drawdown_calculation
- test_win_rate_calculation
- test_profit_factor_calculation
- test_empty_portfolio_returns_defaults

### test_auth.py

- test_api_key_generation_format
- test_api_key_verification_valid
- test_api_key_verification_invalid
- test_jwt_creation_and_verification
- test_jwt_expired_token_rejected

## Integration Tests

### test_full_trade_flow.py

Steps:

1. Register new agent account
2. Verify starting balance is 10000 USDT
3. Get BTC price
4. Place market buy order for 0.1 BTC
5. Verify order status is "filled"
6. Verify USDT balance decreased by correct amount
7. Verify BTC balance is 0.1
8. Verify position exists with correct entry price
9. Place market sell order for 0.1 BTC
10. Verify USDT balance reflects PnL
11. Verify position closed
12. Check trade history has 2 trades
13. Check portfolio shows correct realized PnL

### test_price_ingestion.py

1. Start price ingestion service
2. Wait 5 seconds
3. Verify Redis has prices for 600+ pairs
4. Verify TimescaleDB has ticks
5. Verify no gaps in major pairs

### test_websocket.py

1. Connect WebSocket with API key
2. Subscribe to ticker:BTCUSDT
3. Verify price updates received within 5 seconds
4. Subscribe to orders channel
5. Place an order via REST
6. Verify order fill notification received via WebSocket
7. Test heartbeat ping/pong
8. Test reconnection after disconnect

### test_api_endpoints.py

- Test every REST endpoint with valid and invalid inputs
- Test auth: valid key, invalid key, expired JWT, no auth header
- Test rate limiting: exceed limit, verify 429 response
- Test error responses match documented format

## Load Test Scenarios (Locust)

### Agent Behavior

```python
class TradingAgent(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        # Register and store API key
        resp = self.client.post("/api/v1/auth/register", json={...})
        self.api_key = resp.json()["api_key"]
        self.headers = {"X-API-Key": self.api_key}

    @task(50)
    def check_price(self):
        symbol = random.choice(SYMBOLS)
        self.client.get(f"/api/v1/market/price/{symbol}", headers=self.headers)

    @task(10)
    def check_balance(self):
        self.client.get("/api/v1/account/balance", headers=self.headers)

    @task(10)
    def check_positions(self):
        self.client.get("/api/v1/account/positions", headers=self.headers)

    @task(5)
    def place_order(self):
        self.client.post("/api/v1/trade/order", headers=self.headers, json={
            "symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": 0.001
        })

    @task(5)
    def trade_history(self):
        self.client.get("/api/v1/trade/history?limit=20", headers=self.headers)

    @task(1)
    def performance(self):
        self.client.get("/api/v1/analytics/performance", headers=self.headers)
```

### Targets

- 50 concurrent users, ~400 req/s total
- p50 < 50ms, p95 < 100ms, p99 < 200ms
- 500 WebSocket connections, price update latency < 100ms
