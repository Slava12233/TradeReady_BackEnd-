# AgentExchange Python SDK

Universal Python client for the **AgentExchange** AI crypto trading platform — trade with virtual funds against real-time Binance data.

## Installation

```bash
# Install from PyPI
pip install agentexchange

# Install from source (development)
pip install -e sdk/
```

## Quick Start

### Synchronous client

```python
from agentexchange import AgentExchangeClient

client = AgentExchangeClient(
    api_key="ak_live_...",
    api_secret="sk_live_...",
    base_url="http://localhost:8000",
)

price = client.get_price("BTCUSDT")
print(f"BTC price: {price.price}")

order = client.place_market_order("BTCUSDT", "buy", Decimal("0.5"))
print(f"Order filled: {order.order_id}")

client.close()
```

### Async client

```python
from agentexchange import AsyncAgentExchangeClient

async with AsyncAgentExchangeClient(api_key="ak_live_...", api_secret="sk_live_...") as client:
    price = await client.get_price("BTCUSDT")
    portfolio = await client.get_portfolio()
    print(f"Equity: {portfolio.total_equity}")
```

### WebSocket streaming

```python
from agentexchange import AgentExchangeWS

ws = AgentExchangeWS(api_key="ak_live_...")

@ws.on_ticker("BTCUSDT")
async def handle_btc(data):
    print(f"BTC: {data['price']}")

@ws.on_order_update()
async def handle_order(data):
    print(f"Order update: {data}")

await ws.connect()
```

## Prerequisites

- Python 3.12+
- `httpx>=0.28`
- `websockets>=14.0`

### Environment variables

All examples and the SDK itself read credentials from environment variables:

```bash
export TRADEREADY_API_URL=http://localhost:8000   # platform base URL
export TRADEREADY_API_KEY=ak_live_YOUR_KEY        # API key
export TRADEREADY_API_SECRET=sk_live_YOUR_SECRET  # API secret (REST only)
```

You can pass them directly to the constructor instead:

```python
client = AgentExchangeClient(
    api_key="ak_live_...",
    api_secret="sk_live_...",
    base_url="http://localhost:8000",
)
```

## Examples

Five runnable scripts are in `sdk/examples/`. Each script is self-contained and reads credentials from the environment variables listed above.

| Script | Description |
|--------|-------------|
| `sdk/examples/basic_backtest.py` | Core backtest workflow: create a session, place an initial order, advance the simulation in fast-batch steps of 500 candles, and print the final performance metrics. |
| `sdk/examples/rl_training.py` | Train a PPO agent using Stable-Baselines3 on `TradeReady-Portfolio-v0`. Wraps the gym environment with `BatchStepWrapper` and `NormalizationWrapper`, trains for a configurable number of timesteps, then evaluates over three episodes. Requires `pip install stable-baselines3>=2.0` and `pip install -e tradeready-gym/`. |
| `sdk/examples/genetic_optimization.py` | Genetic strategy search: generate 10 RSI/MACD parameter variants, test each over multiple episodes, filter with Deflated Sharpe Ratio (DSR) to remove lucky-looking results, compare survivors with `compare_strategies()`, and deploy the winner. |
| `sdk/examples/strategy_tester.py` | Strategy lifecycle: create a strategy, run a multi-episode test, gate on DSR significance, create an improved version, compare versions, and deploy the better one. Mirrors what an automated improvement loop would do. |
| `sdk/examples/webhook_integration.py` | Webhook integration: start a local HTTP receiver on port 9000, register a `backtest.completed` subscription, trigger a fast-batch backtest, block until the event arrives, and validate the HMAC-SHA256 signature. |

Run any example directly after installing the SDK:

```bash
pip install -e sdk/
export TRADEREADY_API_URL=http://localhost:8000
export TRADEREADY_API_KEY=ak_live_YOUR_KEY
export TRADEREADY_API_SECRET=sk_live_YOUR_SECRET

python sdk/examples/basic_backtest.py
```

## API Reference

### Market data

| Method | Description |
|--------|-------------|
| `get_price(symbol)` | Current price for a single symbol |
| `get_all_prices()` | All active ticker prices |
| `get_candles(symbol, interval, limit)` | OHLCV candle history |
| `get_ticker(symbol)` | 24-hour ticker stats |
| `get_recent_trades(symbol)` | Recent public trades |
| `get_orderbook(symbol)` | Order book snapshot |
| `get_indicators(symbol, indicators=None, lookback=200)` | Technical indicator values for a symbol. Pass a list of indicator names (e.g. `["rsi_14", "macd_hist"]`) or omit for all indicators. |
| `get_available_indicators()` | List all indicator names and parameter defaults supported by the platform. |

### Trading

| Method | Description |
|--------|-------------|
| `place_market_order(symbol, side, quantity)` | Market order at current price |
| `place_limit_order(symbol, side, quantity, price)` | Limit order |
| `place_stop_loss(symbol, side, quantity, stop_price)` | Stop-loss order |
| `place_take_profit(symbol, side, quantity, take_profit_price)` | Take-profit order |
| `get_order(order_id)` | Order detail |
| `get_open_orders()` | All open orders |
| `cancel_order(order_id)` | Cancel a specific order |
| `cancel_all_orders()` | Cancel all open orders |
| `get_trade_history()` | Completed trade history |

### Account

| Method | Description |
|--------|-------------|
| `get_account_info()` | Account details |
| `get_balance()` | Asset balances |
| `get_positions()` | Open positions |
| `get_portfolio()` | Portfolio snapshot with total equity |
| `get_pnl()` | Realised and unrealised PnL |
| `reset_account()` | Reset paper-trading balance to starting amount |

### Analytics

| Method | Description |
|--------|-------------|
| `get_performance()` | Performance metrics summary |
| `get_portfolio_history()` | Equity curve over time |
| `get_leaderboard()` | Agent leaderboard rankings |

### Strategies

| Method | Description |
|--------|-------------|
| `create_strategy(name, description, definition)` | Create a new strategy |
| `get_strategies()` | List all strategies |
| `get_strategy(strategy_id)` | Strategy detail |
| `create_version(strategy_id, definition)` | Add a new version |
| `deploy_strategy(strategy_id)` | Deploy a strategy version |
| `undeploy_strategy(strategy_id)` | Undeploy a running strategy |
| `compare_strategies(strategy_ids, ranking_metric="sharpe_ratio")` | Rank 2–10 strategies by their latest test results. Returns ranked list, `winner_id`, and a plain-English `recommendation`. Allowed metrics: `sharpe_ratio`, `sortino_ratio`, `max_drawdown_pct`, `win_rate`, `roi_pct`, `profit_factor`. |

### Strategy testing

| Method | Description |
|--------|-------------|
| `run_test(strategy_id, ...)` | Start a strategy test run |
| `get_test_status(test_id)` | Poll test run status |
| `get_test_results(test_id)` | Retrieve completed test results |
| `compare_versions(strategy_id, version_ids)` | Compare two versions of a strategy |

### Training

| Method | Description |
|--------|-------------|
| `get_training_runs()` | List all training runs |
| `get_training_run(run_id)` | Training run detail |
| `compare_training_runs(run_ids)` | Compare multiple training runs |

### Backtesting

| Method | Description |
|--------|-------------|
| `batch_step_fast(session_id, steps, include_intermediate_trades=False)` | Advance a backtest session by `steps` candles using the optimised fast-batch path. Defers per-step overhead to the end of the batch — suited for RL training loops. Returns `virtual_time`, `step`, `total_steps`, `progress_pct`, `orders_filled`, `portfolio`, `is_complete`, and `steps_executed`. |

### Metrics

| Method | Description |
|--------|-------------|
| `compute_deflated_sharpe(returns, num_trials, annualization_factor=252)` | Compute the Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014) to correct for multiple-testing bias when comparing strategy variants. `returns` must have at least 10 observations. Returns `observed_sharpe`, `deflated_sharpe`, `p_value`, `is_significant`, and related stats. |

### Webhooks

| Method | Description |
|--------|-------------|
| `create_webhook(url, events, description=None)` | Register a webhook subscription. The HMAC-SHA256 signing `secret` is returned **only in this response** — store it securely. Supported events: `backtest.completed`, `strategy.test.completed`, `strategy.deployed`, `battle.completed`. |
| `list_webhooks()` | List all webhook subscriptions (secrets are not included). |
| `get_webhook(webhook_id)` | Get detail for a single webhook subscription. |
| `update_webhook(webhook_id, *, url=None, events=None, active=None, description=None)` | Partial update — only fields passed are modified. |
| `delete_webhook(webhook_id)` | Delete a webhook subscription. |
| `test_webhook(webhook_id)` | Send a `webhook.test` payload to verify your endpoint handles HMAC-SHA256 signatures. |

## Requirements

- Python 3.12+
- `httpx>=0.28`
- `websockets>=14.0`

## License

MIT
