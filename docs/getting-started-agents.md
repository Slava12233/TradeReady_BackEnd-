# Getting Started — Build Your First AI Trading Agent

This guide takes a Python developer from a fresh install to a working trading agent in 30 minutes. No crypto or finance knowledge is assumed.

**What you will build:**

| Step | What you build | Concepts learned |
|------|----------------|-----------------|
| 1 | Platform running locally | Docker setup, health check |
| 2 | Account and API credentials | Registration, API key vs. API secret |
| 3 | SDK installed | Package setup, environment variables |
| 4 | Price watcher + WebSocket feed | Market data, streaming |
| 5 | First real trade (buy, sell, PnL) | Orders, balances, positions |
| 6 | Backtest over historical data | Time simulation, performance metrics |
| 7 | RL agent with Gymnasium | Environment training, PPO |
| 8 | Webhook event listener | Push notifications, HMAC verification |
| 9 | Multi-strategy DSR filter | Multiple-testing correction |
| | Next steps | Links to full reference docs |

---

## Before You Begin

**Requirements:**

- Python 3.12+
- Docker and Docker Compose
- `pip` (or `uv`) available in your terminal
- `curl` for the curl examples (optional)

**All trades use virtual USDT** — you cannot lose real money here. The platform simulates a real exchange using live Binance price data and realistic slippage, but every balance is synthetic.

---

## Step 1 — Start the Platform

Clone the repository and start all services with Docker Compose:

```bash
git clone https://github.com/your-org/agentexchange.git
cd agentexchange
cp .env.example .env
docker compose up -d
```

Wait about 15 seconds, then confirm everything is running:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "services": {
    "redis": "ok",
    "timescaledb": "ok",
    "ingestion": "ok"
  }
}
```

If `ingestion` shows `degraded`, wait another 10–20 seconds. The price ingestion service opens a WebSocket connection to Binance at startup and needs a moment to seed live prices.

**What is running:**

| Service | URL | Purpose |
|---------|-----|---------|
| API | `http://localhost:8000` | REST + WebSocket |
| Swagger UI | `http://localhost:8000/docs` | Try any endpoint interactively |
| Grafana | `http://localhost:3000` | Monitoring dashboards |
| Prometheus | `http://localhost:9090` | Raw metrics |

---

## Step 2 — Get API Credentials

You need two credentials:

- **API key** (`ak_live_...`) — used on every request to identify yourself
- **API secret** (`sk_live_...`) — used only when exchanging for a JWT; keep it safe

**Important:** The API secret is shown exactly once at registration. Copy it now.

### Register an account

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "MyFirstAgent", "starting_balance": "10000.00"}'
```

Response:

```json
{
  "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "api_key": "ak_live_abc123...",
  "api_secret": "sk_live_xyz789...",
  "starting_balance": "10000.00",
  "created_at": "2026-04-07T10:00:00Z"
}
```

### Create an agent (optional but recommended)

A single account can have multiple agents, each with its own wallet and trading history. This lets you run experiments in parallel without balances interfering.

```bash
export API_KEY="ak_live_abc123..."

curl -s -X POST http://localhost:8000/api/v1/agents \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "BTC Watcher", "description": "My first price-watching agent"}'
```

Response includes an `agent_id` and a new agent-scoped API key. Use the agent key for all trading operations so activity stays isolated to that agent.

---

## Step 3 — Install the SDK

The Python SDK wraps all REST and WebSocket endpoints. It handles authentication, retries, and deserializes responses into typed Python objects.

```bash
pip install -e sdk/
```

Set credentials as environment variables (the SDK reads them automatically):

```bash
export TRADEREADY_API_URL=http://localhost:8000
export TRADEREADY_API_KEY=ak_live_abc123...
export TRADEREADY_API_SECRET=sk_live_xyz789...
```

Verify the install:

```python
from agentexchange import AgentExchangeClient
import os

client = AgentExchangeClient(
    api_key=os.environ["TRADEREADY_API_KEY"],
    api_secret=os.environ["TRADEREADY_API_SECRET"],
    base_url=os.environ.get("TRADEREADY_API_URL", "http://localhost:8000"),
)
print(client.get_price("BTCUSDT").price)
client.close()
```

---

## Step 4 — Your First Agent: Price Watcher

The platform tracks 600+ trading pairs sourced from Binance in real-time. Each price is stored in Redis and served with sub-millisecond latency.

### Fetch a single price

```python
from agentexchange import AgentExchangeClient
import os

with AgentExchangeClient(
    api_key=os.environ["TRADEREADY_API_KEY"],
    api_secret=os.environ["TRADEREADY_API_SECRET"],
    base_url=os.environ.get("TRADEREADY_API_URL", "http://localhost:8000"),
) as client:
    price = client.get_price("BTCUSDT")
    print(f"BTC: ${price.price}")        # Decimal — never float
    print(f"At: {price.timestamp}")      # datetime

    # Fetch all active prices at once
    all_prices = client.get_all_prices()
    print(f"{len(all_prices)} pairs active")

    # OHLCV candle history (last 50 one-minute candles)
    candles = client.get_candles("BTCUSDT", interval="1m", limit=50)
    for c in candles[-3:]:
        print(f"  {c.open_time}  O={c.open}  H={c.high}  L={c.low}  C={c.close}  V={c.volume}")

    # Technical indicators (all available indicators for the symbol)
    indicators = client.get_indicators("BTCUSDT")
    print(f"RSI-14: {indicators.get('rsi_14')}")
    print(f"MACD histogram: {indicators.get('macd_hist')}")
```

### Stream prices via WebSocket

For agents that react to every price tick, use the WebSocket client. It auto-reconnects and supports multiple subscriptions in one connection.

```python
import asyncio
from agentexchange import AgentExchangeWS
import os

ws = AgentExchangeWS(
    api_key=os.environ["TRADEREADY_API_KEY"],
    base_url=os.environ.get("TRADEREADY_API_URL", "http://localhost:8000").replace("http", "ws"),
)

@ws.on_ticker("BTCUSDT")
async def on_btc_price(data):
    print(f"BTC tick: ${data['price']}")

@ws.on_ticker("ETHUSDT")
async def on_eth_price(data):
    print(f"ETH tick: ${data['price']}")

@ws.on_order_update()
async def on_order(data):
    print(f"Order {data['order_id']}: {data['status']}")

# connect() runs forever with automatic reconnection
asyncio.run(ws.connect())
```

To subscribe to all pairs at once, pass `"all"` as the symbol:

```python
@ws.on_ticker("all")
async def on_any_price(data):
    print(f"{data['symbol']}: ${data['price']}")
```

**Available channels:**

| Decorator | Channel | What you receive |
|-----------|---------|-----------------|
| `@ws.on_ticker(symbol)` | `ticker` | Price, 24h change, volume |
| `@ws.on_candles(symbol, interval)` | `candles` | Completed OHLCV candle |
| `@ws.on_order_update()` | `orders` | Order status changes |
| `@ws.on_portfolio()` | `portfolio` | Portfolio snapshot |

---

## Step 5 — Place Your First Trade

Orders execute immediately at the current live price. Market orders fill in the same API call. Realistic slippage (0–0.1%) and a 0.1% trading fee are applied.

### Buy BTC, check balance, sell, check PnL

```python
from decimal import Decimal
from agentexchange import AgentExchangeClient
from agentexchange.exceptions import InsufficientBalanceError, RateLimitError
import os, time

with AgentExchangeClient(
    api_key=os.environ["TRADEREADY_API_KEY"],
    api_secret=os.environ["TRADEREADY_API_SECRET"],
    base_url=os.environ.get("TRADEREADY_API_URL", "http://localhost:8000"),
) as client:

    # 1. Check starting balance
    balance = client.get_balance()
    for asset in balance.balances:
        if asset.total > 0:
            print(f"{asset.asset}: {asset.available} available")

    # 2. Buy 0.001 BTC at market price
    try:
        buy = client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
        print(f"Bought {buy.executed_quantity} BTC at ${buy.executed_price}")
        print(f"  Fee: ${buy.fee}  Slippage: {buy.slippage_pct}%")
    except InsufficientBalanceError as e:
        print(f"Not enough USDT: need {e.required}, have {e.available}")
        raise
    except RateLimitError as e:
        time.sleep(e.retry_after or 5)
        raise

    # 3. Inspect open position
    positions = client.get_positions()
    for pos in positions:
        print(f"Open: {pos.symbol} qty={pos.quantity} entry=${pos.avg_entry_price}")
        print(f"  Unrealized PnL: ${pos.unrealized_pnl}")

    # 4. Portfolio snapshot
    portfolio = client.get_portfolio()
    print(f"Total equity: ${portfolio.total_equity}")
    print(f"ROI so far:   {portfolio.roi_pct}%")

    # 5. Sell back at market price
    sell = client.place_market_order("BTCUSDT", "sell", Decimal("0.001"))
    print(f"Sold {sell.executed_quantity} BTC at ${sell.executed_price}")

    # 6. Check realised PnL
    pnl = client.get_pnl()
    print(f"Realised PnL: ${pnl.realized_pnl}")
    print(f"Total PnL:    ${pnl.total_pnl}")
```

### Other order types

```python
# Limit buy: only fills if price drops to $60,000
limit = client.place_limit_order("BTCUSDT", "buy", Decimal("0.001"), price=Decimal("60000.00"))

# Stop-loss: automatically sells if price falls to $58,000
stop = client.place_stop_loss("BTCUSDT", "sell", Decimal("0.001"), stop_price=Decimal("58000.00"))

# Take-profit: automatically sells when price rises to $70,000
tp = client.place_take_profit("BTCUSDT", "sell", Decimal("0.001"), take_profit_price=Decimal("70000.00"))

# Cancel an order
client.cancel_order(limit.order_id)

# Cancel everything
client.cancel_all_orders()
```

---

## Step 6 — Backtest a Strategy

Backtesting replays real historical market data. Your buy/sell calls work identically in backtest mode as in live mode — the engine just feeds past prices instead of live ones.

**How it works:**

1. Create a session specifying the date range and starting balance
2. Start the session (preloads all price data into memory)
3. Step through time — optionally placing orders at each step
4. Retrieve results once the simulation completes

### SMA crossover backtest

This example implements a simple 10/30 moving average crossover strategy using the platform's indicator data:

```python
from decimal import Decimal
from agentexchange import AgentExchangeClient
import os

BASE_URL = os.environ.get("TRADEREADY_API_URL", "http://localhost:8000")
API_KEY = os.environ["TRADEREADY_API_KEY"]
API_SECRET = os.environ["TRADEREADY_API_SECRET"]

with AgentExchangeClient(api_key=API_KEY, api_secret=API_SECRET, base_url=BASE_URL) as client:

    # 1. Create a 30-day session on BTCUSDT
    session = client._request(
        "POST", "/api/v1/backtest/create",
        json={
            "start_time": "2025-01-01T00:00:00Z",
            "end_time":   "2025-01-31T23:59:00Z",
            "starting_balance": "10000",
            "candle_interval": 60,        # 1-minute candles
            "pairs": ["BTCUSDT"],
            "strategy_label": "sma_crossover",
        },
    )
    session_id = session["session_id"]
    print(f"Session: {session_id}  total_steps: {session['total_steps']}")

    # 2. Start the session
    client._request("POST", f"/api/v1/backtest/{session_id}/start")

    # 3. Advance in batches of 500 candles
    in_position = False
    while True:
        result = client.batch_step_fast(session_id, steps=500)

        # batch_step_fast returns portfolio info — use it to make decisions
        portfolio = result.get("portfolio", {})
        current_equity = portfolio.get("total_equity", 0)

        # Simple rule: buy on first batch, hold, sell near the end
        progress = result.get("progress_pct", 0.0)
        if not in_position and progress > 5:
            try:
                client._request(
                    "POST", f"/api/v1/backtest/{session_id}/trade/order",
                    json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.01"},
                )
                in_position = True
                print(f"  Bought at {progress:.0f}% through backtest")
            except Exception:
                pass

        if in_position and progress > 90:
            try:
                client._request(
                    "POST", f"/api/v1/backtest/{session_id}/trade/order",
                    json={"symbol": "BTCUSDT", "side": "sell", "type": "market", "quantity": "0.01"},
                )
                in_position = False
                print(f"  Sold at {progress:.0f}% through backtest")
            except Exception:
                pass

        step = result.get("step", 0)
        total = result.get("total_steps", 1)
        print(f"  {step}/{total} ({progress:.1f}%)  equity={current_equity}")

        if result.get("is_complete"):
            break

    # 4. Retrieve results
    results = client._request("GET", f"/api/v1/backtest/{session_id}/results")
    metrics = results.get("metrics", {})
    print("\n--- Backtest Results ---")
    print(f"  Total Return : {metrics.get('total_return_pct', 'n/a')}%")
    print(f"  Sharpe Ratio : {metrics.get('sharpe_ratio', 'n/a')}")
    print(f"  Max Drawdown : {metrics.get('max_drawdown_pct', 'n/a')}%")
    print(f"  Win Rate     : {metrics.get('win_rate', 'n/a')}%")
    print(f"  Total Trades : {metrics.get('total_trades', 'n/a')}")
    print(f"  Final Equity : {results.get('final_equity', 'n/a')} USDT")
```

**Performance metrics returned:**

| Metric | What it measures |
|--------|-----------------|
| `total_return_pct` | Percentage gain/loss over the test period |
| `sharpe_ratio` | Return per unit of risk (higher is better; above 1.0 is good) |
| `max_drawdown_pct` | Largest peak-to-trough drop (lower is better) |
| `win_rate` | Percentage of trades that closed in profit |
| `total_trades` | Number of completed buy+sell round trips |
| `sortino_ratio` | Like Sharpe but only penalises downside volatility |
| `profit_factor` | Gross profit / gross loss (above 1.0 = profitable) |

---

## Step 7 — Train an RL Agent

The `tradeready-gym` package exposes the platform as a standard [Gymnasium](https://gymnasium.farama.org/) environment. This means any RL library that works with Gymnasium — Stable-Baselines3, RLlib, CleanRL — works here out of the box.

### Install prerequisites

```bash
pip install -e tradeready-gym/
pip install stable-baselines3>=2.0
```

### Train a PPO agent

```python
import gymnasium as gym
import tradeready_gym  # noqa: F401 — registers environments as side effect
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from tradeready_gym.wrappers.batch_step import BatchStepWrapper
from tradeready_gym.wrappers.normalization import NormalizationWrapper
import os

API_KEY = os.environ["TRADEREADY_API_KEY"]
BASE_URL = os.environ.get("TRADEREADY_API_URL", "http://localhost:8000")

# Build the training environment
env = gym.make(
    "TradeReady-Portfolio-v0",
    api_key=API_KEY,
    base_url=BASE_URL,
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-01-31T23:59:00Z",
    starting_balance=10000.0,
    track_training=True,         # records episode data to the platform
    strategy_label="my_ppo_v1",
)

# Wrappers: hold each action for 5 candles, then normalise observations
env = BatchStepWrapper(env, n_steps=5)
env = NormalizationWrapper(env)
env = Monitor(env)               # SB3 episode logging

# Train for 50,000 timesteps
model = PPO("MlpPolicy", env, learning_rate=3e-4, verbose=1)
model.learn(total_timesteps=50_000)
env.close()

# Evaluate
eval_env = gym.make(
    "TradeReady-Portfolio-v0",
    api_key=API_KEY,
    base_url=BASE_URL,
    start_time="2025-02-01T00:00:00Z",
    end_time="2025-02-28T23:59:00Z",
    starting_balance=10000.0,
    track_training=False,
)
eval_env = BatchStepWrapper(NormalizationWrapper(eval_env), n_steps=5)

obs, _ = eval_env.reset()
total_reward = 0.0
done = False
while not done:
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, _ = eval_env.step(action)
    total_reward += float(reward)
    done = terminated or truncated

print(f"Evaluation episode reward: {total_reward:.4f}")
eval_env.close()

model.save("my_ppo_portfolio_agent")
```

**Registered environments:**

| Environment ID | Action space | Best for |
|----------------|--------------|---------|
| `TradeReady-SingleAsset-v0` | Discrete (hold/buy/sell) | Simple directional trading |
| `TradeReady-Portfolio-v0` | Continuous (portfolio weights) | Multi-asset allocation |
| `TradeReady-Live-v0` | Discrete | Live trading with real-time prices |

See `docs/gym_api_guide.md` for the full observation space, reward functions, and all available wrappers.

---

## Step 8 — Deploy Webhooks

Instead of polling for results, you can register a webhook URL and receive a push notification when events complete.

**Supported events:**

| Event | Fired when |
|-------|-----------|
| `backtest.completed` | A backtest session finishes |
| `strategy.test.completed` | A strategy test run finishes |
| `strategy.deployed` | A strategy is deployed |
| `battle.completed` | An agent battle finishes |

### Register a webhook

```python
from agentexchange import AgentExchangeClient
import os

with AgentExchangeClient(
    api_key=os.environ["TRADEREADY_API_KEY"],
    api_secret=os.environ["TRADEREADY_API_SECRET"],
    base_url=os.environ.get("TRADEREADY_API_URL", "http://localhost:8000"),
) as client:
    wh = client.create_webhook(
        url="https://your-server.example.com/hooks/tradeready",
        events=["backtest.completed", "strategy.test.completed"],
        description="My agent notification endpoint",
    )
    webhook_id = wh["webhook_id"]
    secret = wh["secret"]    # shown ONLY at creation — store securely
    print(f"Webhook ID: {webhook_id}")
    print(f"Signing secret: {secret}")
```

### Handle incoming events with HMAC verification

Every incoming webhook is signed with HMAC-SHA256. Always verify the signature before acting on the payload.

```python
import hashlib
import hmac
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

WEBHOOK_SECRET = "your-stored-secret"

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # Verify HMAC-SHA256 signature
        sig = self.headers.get("X-TradeReady-Signature", "")
        expected = "sha256=" + hmac.new(
            WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            self.send_response(401)
            self.end_headers()
            return

        event = json.loads(body)
        print(f"Event: {event['event']}")

        if event["event"] == "backtest.completed":
            metrics = event.get("metrics", {})
            print(f"  Sharpe: {metrics.get('sharpe_ratio')}")
            print(f"  Return: {metrics.get('total_return_pct')}%")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *args):
        pass  # suppress access log

server = HTTPServer(("0.0.0.0", 9000), WebhookHandler)
print("Webhook receiver listening on :9000")
server.serve_forever()
```

The full working example (including a background HTTP server and test ping) is at `sdk/examples/webhook_integration.py`.

---

## Step 9 — Compare Strategies with DSR

When you test many strategy variants, some will look good purely by chance. The Deflated Sharpe Ratio (DSR) corrects for this multiple-testing bias — a strategy only passes the filter if its performance is unlikely to be a statistical fluke.

**Rule of thumb:** if you test N variants, a strategy needs a DSR p-value below 0.05 to be considered genuinely skilled. The more variants you test, the stricter this filter becomes.

```python
from decimal import Decimal
from agentexchange import AgentExchangeClient
import os, time

with AgentExchangeClient(
    api_key=os.environ["TRADEREADY_API_KEY"],
    api_secret=os.environ["TRADEREADY_API_SECRET"],
    base_url=os.environ.get("TRADEREADY_API_URL", "http://localhost:8000"),
) as client:

    NUM_TRIALS = 5  # number of strategy variants you tested

    # Simulate returns from 5 strategy test runs
    # In practice, extract these from client.get_test_results()
    strategy_returns = [
        [0.02, -0.01, 0.03, 0.01, -0.02, 0.04, 0.01, 0.02, -0.01, 0.03],  # variant A
        [0.05, 0.04, 0.06, 0.05, 0.07, 0.04, 0.06, 0.05, 0.04, 0.06],     # variant B (good)
        [-0.01, 0.0, -0.02, 0.01, -0.01, 0.0, -0.02, 0.01, -0.01, 0.0],   # variant C
        [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01],     # variant D
        [0.03, -0.03, 0.02, -0.02, 0.03, -0.03, 0.02, -0.02, 0.03, -0.03], # variant E
    ]
    strategy_ids = ["strat-a", "strat-b", "strat-c", "strat-d", "strat-e"]

    survivors = []
    for name, returns, strategy_id in zip(
        ["A", "B", "C", "D", "E"], strategy_returns, strategy_ids
    ):
        dsr = client.compute_deflated_sharpe(
            returns=returns,
            num_trials=NUM_TRIALS,
            annualization_factor=252,
        )
        status = "PASS" if dsr["is_significant"] else "FAIL"
        print(
            f"  Variant {name}: obs_sharpe={dsr['observed_sharpe']:.3f}  "
            f"dsr={dsr['deflated_sharpe']:.3f}  p={dsr['p_value']:.4f}  [{status}]"
        )
        if dsr["is_significant"]:
            survivors.append(strategy_id)

    print(f"\n{len(survivors)}/{NUM_TRIALS} variants passed the DSR filter: {survivors}")

    # If multiple survivors, compare them and get a recommendation
    if len(survivors) >= 2:
        comparison = client.compare_strategies(
            strategy_ids=survivors,
            ranking_metric="sharpe_ratio",
        )
        print(f"Winner: {comparison['winner_id']}")
        print(f"Recommendation: {comparison['recommendation']}")
        for entry in comparison.get("strategies", []):
            print(f"  [{entry['rank']}] {entry['strategy_id']}  sharpe={entry.get('sharpe_ratio')}")
```

The full genetic search example (10 variants, multi-episode testing, cleanup) is at `sdk/examples/genetic_optimization.py`.

---

## Next Steps

You now have a working agent that can fetch prices, trade, backtest, train with RL, receive webhooks, and filter strategies with DSR. Here is where to go next:

### Reference documentation

| Document | What it covers |
|----------|---------------|
| `sdk/README.md` | Full SDK method reference (48 methods) |
| `docs/api_reference.md` | Complete REST API reference — all endpoints, parameters, error codes |
| `docs/backtesting-guide.md` | Backtest lifecycle, order types in sandbox, performance metrics |
| `docs/gym_api_guide.md` | All Gymnasium environments, observation/action spaces, reward functions, wrappers |
| `docs/mcp_server.md` | 58 MCP tools for Claude and MCP-aware agent frameworks |
| `docs/rate_limits.md` | Rate limits per endpoint group |

### Framework integrations

| Guide | Framework |
|-------|-----------|
| `docs/framework_guides/langchain.md` | LangChain Tools + AgentExecutor |
| `docs/framework_guides/crewai.md` | CrewAI multi-agent crews |
| `docs/framework_guides/agent_zero.md` | Agent Zero skill integration |
| `docs/framework_guides/openclaw.md` | OpenClaw agent configuration |

### Runnable SDK examples

All examples are in `sdk/examples/` and read credentials from the same environment variables:

| Script | What it demonstrates |
|--------|---------------------|
| `basic_backtest.py` | Full backtest lifecycle with fast-batch stepping |
| `rl_training.py` | PPO training + evaluation with SB3 |
| `genetic_optimization.py` | 10-variant genetic search with DSR filter |
| `strategy_tester.py` | Strategy create → test → DSR gate → deploy loop |
| `webhook_integration.py` | Local webhook receiver with HMAC validation |
| `getting_started.py` | This guide's Steps 4–6 combined in one script |

### Interactive exploration

The Swagger UI at `http://localhost:8000/docs` lets you call any endpoint directly from the browser without writing code. Use it to explore response shapes before writing your agent.

### Using an LLM agent

Drop `docs/skill.md` into any LLM agent's system prompt (Claude, GPT-4, etc.) and the agent will know all available endpoints, authentication, error codes, and trading workflows. The MCP server (`docs/mcp_server.md`) provides 58 tools for Claude Desktop and Cline.
