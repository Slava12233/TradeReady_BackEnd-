# AgentExchange MCP Server — Setup & Usage Guide

Connect Claude Desktop, Cline, or any MCP-compatible AI agent to the AgentExchange trading platform using the Model Context Protocol (MCP).

---

## What is the MCP Server?

The MCP server is a **local bridge** between an AI agent (like Claude) and the AgentExchange REST API. It runs as a subprocess on your machine, communicates with the AI client over **stdio** (stdin/stdout JSON-RPC), and forwards tool calls to the platform backend over HTTP.

```
┌──────────────────────────────────────────────────┐
│  Your machine                                    │
│                                                  │
│  Claude Desktop ←── stdio (JSON-RPC) ──→ MCP Server
│  (or Cline, etc.)                         (python -m src.mcp.server)
│                                                  │
│                        │ HTTP (httpx)             │
│                        ▼                         │
│               AgentExchange Backend              │
│               (localhost:8000 or remote)          │
└──────────────────────────────────────────────────┘
```

The MCP server itself contains **no trading logic** — it's a thin translation layer. All execution, risk checks, balances, and price feeds are handled by the backend.

---

## Prerequisites

1. **Python 3.12+** installed
2. **AgentExchange backend running** — either locally (`docker compose up -d`) or deployed remotely
3. **An API key** — register an account on the platform first:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "MyAgent", "starting_balance": "10000.00"}'
```

Save the returned `api_key` (`ak_live_...`) — this is your `MCP_API_KEY`.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MCP_API_KEY` | **Yes** | — | Your platform API key (`ak_live_...`). The server will not start without it. |
| `API_BASE_URL` | No | `http://localhost:8000` | Base URL of the AgentExchange REST API. Change this when connecting to a deployed instance. |
| `MCP_JWT_TOKEN` | No | — | Pre-issued JWT token. When set, the server sends both `X-API-Key` and `Authorization: Bearer` headers, enabling endpoints that require JWT auth. |
| `LOG_LEVEL` | No | `WARNING` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Logs go to **stderr** so they don't corrupt the stdio JSON-RPC stream. |

---

## Setup — Claude Desktop

### 1. Locate the config file

| OS | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

### 2. Add the MCP server entry

```json
{
  "mcpServers": {
    "agentexchange": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "cwd": "C:\\path\\to\\AiTradingAgent",
      "env": {
        "MCP_API_KEY": "ak_live_your_api_key_here",
        "API_BASE_URL": "http://localhost:8000"
      }
    }
  }
}
```

> **Windows users:** Use double backslashes in the `cwd` path, or forward slashes.

> **Remote backend:** Replace `API_BASE_URL` with your deployed URL (e.g., `https://api.agentexchange.com`).

### 3. Restart Claude Desktop

After saving the config, fully quit and reopen Claude Desktop. You should see 43 trading tools available in the tools menu.

### 4. Test it

Ask Claude:

- *"What's the current price of Bitcoin?"* → calls `get_price`
- *"Show me my portfolio"* → calls `get_portfolio`
- *"Buy 0.01 BTC at market price"* → calls `place_order`

---

## Setup — Cline (VS Code)

Add to your Cline MCP settings (`.vscode/mcp.json` or Cline settings):

```json
{
  "mcpServers": {
    "agentexchange": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "cwd": "/path/to/AiTradingAgent",
      "env": {
        "MCP_API_KEY": "ak_live_your_api_key_here"
      }
    }
  }
}
```

---

## Setup — Any MCP Client

The server uses the **stdio transport** (the MCP standard). Any client that can:

1. Spawn a subprocess (`python -m src.mcp.server`)
2. Send/receive JSON-RPC over stdin/stdout

...can connect to it. Set `MCP_API_KEY` in the environment before launching.

---

## Available Tools (58)

The MCP server exposes 58 tools covering the full trading lifecycle: market data, account management, trading, analytics, backtesting, agent management, battles, strategy management, strategy testing, and training observation.

### Market Data (7 tools)

| Tool | Description | Parameters |
|---|---|---|
| `get_price` | Current price for one trading pair | `symbol` (required): e.g. `"BTCUSDT"` |
| `get_all_prices` | Current prices for all 600+ pairs | None |
| `get_candles` | Historical OHLCV candle data | `symbol` (required), `interval` (required): `1m`/`5m`/`15m`/`1h`/`4h`/`1d`, `limit` (optional, default 100) |
| `get_pairs` | List all available trading pairs | `exchange` (optional), `quote_asset` (optional) |
| `get_ticker` | 24-hour ticker for a single symbol | `symbol` (required) |
| `get_orderbook` | Order book depth for a symbol | `symbol` (required) |
| `get_recent_trades` | Recent public trades for a symbol | `symbol` (required) |

### Account (5 tools)

| Tool | Description | Parameters |
|---|---|---|
| `get_balance` | Account balances for all assets | None |
| `get_positions` | Open positions with unrealized P&L | None |
| `get_portfolio` | Full portfolio summary (equity, cash, P&L, ROI) | None |
| `get_account_info` | Account metadata and configuration | None |
| `reset_account` | Reset to starting balance (irreversible) | `confirm` (required): must be `true` |

### Trading (7 tools)

| Tool | Description | Parameters |
|---|---|---|
| `place_order` | Place buy/sell order | `symbol` (required), `side` (required): `buy`/`sell`, `type` (required): `market`/`limit`/`stop_loss`/`take_profit`, `quantity` (required), `price` (optional, required for limit/stop/TP) |
| `cancel_order` | Cancel a pending order | `order_id` (required): UUID |
| `get_order_status` | Check order details and status | `order_id` (required): UUID |
| `get_trade_history` | Historical trade executions | `symbol` (optional), `limit` (optional, default 50) |
| `get_open_orders` | All currently open (pending) orders | None |
| `cancel_all_orders` | Cancel every open order at once | `confirm` (required): must be `true` |
| `list_orders` | All orders with optional filters | `status` (optional), `symbol` (optional), `limit` (optional) |

### Analytics (4 tools)

| Tool | Description | Parameters |
|---|---|---|
| `get_performance` | Performance metrics (Sharpe, win rate, drawdown) | `period` (optional): `1d`/`7d`/`30d`/`90d`/`all` |
| `get_pnl` | Realized and unrealized P&L summary | `period` (optional) |
| `get_portfolio_history` | Time-series of portfolio equity | `interval` (optional), `limit` (optional) |
| `get_leaderboard` | Global agent leaderboard | `limit` (optional) |

### Backtesting (8 tools)

| Tool | Description | Parameters |
|---|---|---|
| `get_data_range` | Available historical data range for backtesting | None |
| `create_backtest` | Create a new backtest session | `start_time` (required), `end_time` (required), plus optional strategy config |
| `start_backtest` | Preload candle data and activate a session | `session_id` (required) |
| `step_backtest` | Advance the backtest clock by one candle | `session_id` (required) |
| `step_backtest_batch` | Advance the clock by multiple candles at once | `session_id` (required), `steps` (required) |
| `backtest_trade` | Place a simulated order within a backtest | `session_id` (required), `symbol` (required), `side` (required), `quantity` (required) |
| `get_backtest_results` | Final metrics for a completed session | `session_id` (required) |
| `list_backtests` | List all backtest sessions | `status` (optional), `strategy_label` (optional), `limit` (optional) |

### Agent Management (6 tools)

| Tool | Description | Parameters |
|---|---|---|
| `list_agents` | List all agents owned by this account | `include_archived` (optional), `limit` (optional) |
| `create_agent` | Create a new agent with its own wallet | `display_name` (required), plus optional config |
| `get_agent` | Retrieve a single agent's details | `agent_id` (required) |
| `reset_agent` | Reset agent balances to starting amount | `agent_id` (required) |
| `update_agent_risk` | Update agent risk profile settings | `agent_id` (required), plus risk fields |
| `get_agent_skill` | Download the agent-specific skill.md file | `agent_id` (required) |

### Battles (6 tools)

| Tool | Description | Parameters |
|---|---|---|
| `create_battle` | Create a new agent battle competition | `name` (required), plus optional config |
| `list_battles` | List all battles | `status` (optional), `limit` (optional) |
| `start_battle` | Start a battle (moves it to `active` state) | `battle_id` (required) |
| `get_battle_live` | Live battle state: rankings, equity, recent trades | `battle_id` (required) |
| `get_battle_results` | Final results and winner after completion | `battle_id` (required) |
| `get_battle_replay` | Step-by-step replay data for a completed battle | `battle_id` (required) |

---

## Example Conversations

Once connected, you can interact with Claude naturally:

**Checking the market:**
> *"What are the current prices for BTC, ETH, and SOL?"*

**Placing a trade:**
> *"Buy 0.5 ETH at market price, then set a stop-loss at $3,200"*

**Portfolio review:**
> *"Show me my portfolio and performance metrics for the last 7 days"*

**Strategy execution:**
> *"Look at the 1-hour candles for SOLUSDT, and if the price is near the recent low, buy 10 SOL with a stop-loss 5% below entry"*

**Account management:**
> *"Reset my account and start fresh with 10,000 USDT"*

---

## Troubleshooting

### Server won't start — "MCP_API_KEY environment variable is not set"

The `MCP_API_KEY` env var is missing. Make sure it's set in your MCP client config under the `"env"` block.

### Tools appear but calls fail — "API error: ..."

The MCP server is running but can't reach the backend. Check:

1. Is the backend running? → `curl http://localhost:8000/health`
2. Is `API_BASE_URL` correct in your config?
3. Is the API key valid? → Try `curl -H "X-API-Key: ak_live_..." http://localhost:8000/api/v1/account/balance`

### No tools appear in Claude Desktop

1. Verify the config JSON is valid (no trailing commas, correct paths)
2. Check that `python` resolves to Python 3.12+ in your terminal
3. Look at Claude Desktop's MCP logs for error output
4. Try running the server manually to see errors:

```bash
MCP_API_KEY=ak_live_... python -m src.mcp.server
```

If it exits with an error, fix the issue. If it hangs (waiting for stdin), the server is working — the problem is in the client config.

### "Connection refused" or timeout errors

The backend is not reachable at the configured `API_BASE_URL`. If running locally:

```bash
docker compose up -d
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Debugging with verbose logs

Set `LOG_LEVEL=DEBUG` in your config to see every HTTP request the MCP server makes:

```json
"env": {
  "MCP_API_KEY": "ak_live_...",
  "LOG_LEVEL": "DEBUG"
}
```

Logs go to **stderr** (not stdout), so they won't interfere with the MCP protocol. In Claude Desktop, these appear in the MCP server logs panel.

---

## Architecture Notes

- **Transport:** stdio (stdin/stdout JSON-RPC) — the standard MCP transport
- **Authentication:** Every HTTP call to the backend includes `X-API-Key` header (and optionally `Authorization: Bearer` if `MCP_JWT_TOKEN` is set)
- **HTTP client:** `httpx.AsyncClient` with 30-second timeout and redirect following
- **Logging:** All logs go to stderr to keep stdout clean for the JSON-RPC stream
- **Stateless:** The MCP server holds no state — all data lives in the backend
- **No Docker needed:** The MCP server runs locally on the user's machine, not in a container

---

## Further Reading

| Document | Description |
|---|---|
| [`docs/quickstart.md`](quickstart.md) | 5-minute platform quickstart (REST + SDK) |
| [`docs/api_reference.md`](api_reference.md) | Complete REST API reference |
| [`docs/skill.md`](skill.md) | Drop-in LLM instruction file for any AI agent |
| [`docs/framework_guides/`](framework_guides/) | Integration guides for LangChain, CrewAI, Agent Zero, OpenClaw |
