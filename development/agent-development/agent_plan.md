---
type: plan
title: "Agent Plan: TradeReady Platform Testing Agent (V1)"
status: complete
phase: agent-development
tags:
  - plan
  - agent-development
---

# Agent Plan: TradeReady Platform Testing Agent (V1)

> **Goal:** Build an autonomous AI agent that performs "real-life" testing of the TradeReady platform — validating that the platform's tools genuinely improve an agent's trading abilities.

---

## 1. Framework Decision: Pydantic AI + OpenRouter

### Why Pydantic AI


| Criterion          | Pydantic AI                                                      | Runner-up (OpenAI Agents SDK) |
| ------------------ | ---------------------------------------------------------------- | ------------------------------- |
| OpenRouter support | **Native** — `OpenRouterModel` class, one-line setup             | Via `base_url` hack             |
| MCP client         | **Native** — stdio, SSE, Streamable HTTP transports              | Native but less mature          |
| Structured outputs | **Best-in-class** — Pydantic models as `output_type`             | Good, Pydantic support          |
| Stack alignment    | Perfect — our platform uses Pydantic v2 + FastAPI + async Python | Decent                          |
| Async support      | Full — `agent.run()`, `agent.run_sync()`, `agent.run_stream()`   | Full                            |
| Autonomous loops   | `Agent.iter()` async iterator + durable agents                   | Built-in agent loop             |
| Custom tools       | `@agent.tool` decorator, identical to FastAPI `Depends()`        | `@function_tool`                |
| Weight             | Lightweight, minimal deps                                        | Lightweight                     |


**Rejected frameworks:**

- **LangGraph/LangChain** — heavy abstraction, overkill for single agent
- **CrewAI** — role-based multi-agent focus, not suited for trading loop
- **AutoGen** — maintenance mode, not production-ready
- **Claude Agent SDK** — locked to Anthropic models only, no OpenRouter
- **Agno** — OpenRouter integration has known bugs

### OpenRouter Integration

- API: `https://openrouter.ai/api/v1` (OpenAI-compatible)
- 400+ models across all providers (Claude, GPT, Gemini, DeepSeek, Llama, Mistral)
- Model switching: change one string to swap models
- Free models available for testing
- Usage in Pydantic AI:

```python
from pydantic_ai import Agent
agent = Agent('openrouter:anthropic/claude-sonnet-4-5')
```

---

## 2. What This Agent Does

The agent is a **platform validator**, not a production trading bot. Its purpose:

1. **Validate platform tools** — Exercise every integration surface (MCP, REST API, SDK) to confirm they work correctly
2. **Test trading workflows** — Register, create agents, trade, backtest, run battles, use strategies
3. **Measure improvement** — Can the platform's tools (backtesting, strategies, analytics) actually help an AI agent make better trades?
4. **Find bugs** — Real-life usage patterns that unit/integration tests miss
5. **Stress-test flows** — Multi-step workflows that cross service boundaries

### V1 Scope (this plan)

A single agent that can:

- Connect to the platform via all 3 integration methods (MCP, SDK, REST)
- Register an account and create sub-agents
- Execute trades based on market analysis
- Run backtests and analyze results
- Use strategy testing to evaluate approaches
- Report findings as structured output

### NOT in V1

- Cron/scheduling (future — continuous monitoring)
- Multi-agent orchestration (future — CrewAI layer)
- RL training via Gymnasium (future — separate concern)
- WebSocket streaming (future — real-time reactions)
- Battle automation (future — agent-vs-agent comparison)

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────┐
│                  TradeReady Test Agent               │
│                   (Pydantic AI)                      │
│                                                      │
│  ┌─────────────┐  ┌────────────┐  ┌──────────────┐  │
│  │ OpenRouter   │  │ Tool Layer │  │ Output Models│  │
│  │ Model Switch │  │            │  │ (Pydantic)   │  │
│  └──────┬──────┘  │ ┌────────┐ │  └──────────────┘  │
│         │         │ │MCP     │ │                     │
│         │         │ │Client  │ │                     │
│         │         │ ├────────┤ │                     │
│         │         │ │SDK     │ │                     │
│         │         │ │Client  │ │                     │
│         │         │ ├────────┤ │                     │
│         │         │ │REST    │ │                     │
│         │         │ │Direct  │ │                     │
│         │         │ └────────┘ │                     │
│         │         └─────┬──────┘                     │
└─────────┼───────────────┼────────────────────────────┘
          │               │
          ▼               ▼
   ┌──────────┐    ┌──────────────┐
   │OpenRouter│    │  TradeReady  │
   │  API     │    │  Platform    │
   │(400+     │    │  (localhost  │
   │ models)  │    │   :8000)     │
   └──────────┘    └──────────────┘
```

### Directory Structure

```
agent/                          # New top-level directory
├── __init__.py
├── README.md                   # Quick start guide
├── pyproject.toml              # Dependencies (pydantic-ai, openrouter, our SDK)
├── .env.example                # OPENROUTER_API_KEY, platform credentials
│
├── config.py                   # Agent configuration (models, platform URL, etc.)
├── main.py                     # Entry point — run the agent
│
├── models/                     # Pydantic output models
│   ├── __init__.py
│   ├── trade_signal.py         # TradeSignal, TradeDecision
│   ├── analysis.py             # MarketAnalysis, BacktestAnalysis
│   └── report.py               # TestReport, PlatformValidation
│
├── tools/                      # Tool implementations
│   ├── __init__.py
│   ├── mcp_tools.py            # MCP server connection (58 tools auto-discovered)
│   ├── sdk_tools.py            # SDK-wrapped tools (typed, with error handling)
│   └── rest_tools.py           # Direct REST tools (for endpoints SDK doesn't cover)
│
├── prompts/                    # System prompts and context
│   ├── __init__.py
│   ├── system.py               # Base system prompt (who the agent is)
│   └── skill_context.py        # Loads skill.md from platform for context
│
├── workflows/                  # Multi-step test workflows
│   ├── __init__.py
│   ├── smoke_test.py           # Basic connectivity validation
│   ├── trading_workflow.py     # Full trade lifecycle test
│   ├── backtest_workflow.py    # Backtest + analyze + improve loop
│   └── strategy_workflow.py    # Strategy create → test → compare → deploy
│
└── reports/                    # Generated test reports (gitignored)
    └── .gitkeep
```

---

## 4. Implementation Plan

### Phase 1: Foundation (Days 1-2)

#### 1.1 Project Setup

```bash
# New directory alongside existing code
mkdir agent
cd agent
```

`**pyproject.toml`:**

```toml
[project]
name = "tradeready-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic-ai-slim[openrouter]>=0.2",
    "agentexchange",              # Our SDK (pip install -e ../sdk/)
    "httpx>=0.28",
    "python-dotenv>=1.0",
    "structlog>=24.0",            # Structured logging
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "ruff"]
```

`**.env.example`:**

```env
# OpenRouter
OPENROUTER_API_KEY=sk-or-v1-...

# Platform credentials (from registration)
PLATFORM_BASE_URL=http://localhost:8000
PLATFORM_API_KEY=ak_live_...
PLATFORM_API_SECRET=sk_live_...

# Model selection (any OpenRouter model ID)
AGENT_MODEL=openrouter:anthropic/claude-sonnet-4-5
AGENT_CHEAP_MODEL=openrouter:google/gemini-2.0-flash-001   # For bulk/cheap tasks
```

#### 1.2 Configuration

`**agent/config.py`:**

```python
from pydantic_settings import BaseSettings

class AgentConfig(BaseSettings):
    # OpenRouter
    openrouter_api_key: str
    agent_model: str = "openrouter:anthropic/claude-sonnet-4-5"
    agent_cheap_model: str = "openrouter:google/gemini-2.0-flash-001"

    # Platform
    platform_base_url: str = "http://localhost:8000"
    platform_api_key: str = ""
    platform_api_secret: str = ""

    # Agent behavior
    max_trade_pct: float = 0.05       # Max 5% of equity per trade
    symbols: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

#### 1.3 Core Agent Definition

`**agent/main.py`:**

```python
import asyncio
from pydantic_ai import Agent
from agent.config import AgentConfig
from agent.tools.sdk_tools import get_sdk_tools
from agent.prompts.system import SYSTEM_PROMPT

config = AgentConfig()

# The core agent — uses SDK tools for typed access
trading_agent = Agent(
    config.agent_model,
    system_prompt=SYSTEM_PROMPT,
    tools=get_sdk_tools(config),
    retries=2,
)

async def main():
    """Run the agent with a task."""
    result = await trading_agent.run(
        "Connect to the platform, check your balance, "
        "analyze BTC price, and make a small test trade."
    )
    print(result.output)

if __name__ == "__main__":
    asyncio.run(main())
```

---

### Phase 2: Tool Layer (Days 2-3)

Three integration methods, each as a tool module. The agent can use whichever is most appropriate.

#### 2.1 SDK Tools (Primary — typed, with error handling)

`**agent/tools/sdk_tools.py`:**

```python
"""SDK-based tools — typed, auto-auth, retry built-in."""
from decimal import Decimal
from pydantic_ai import RunContext
from agentexchange import AsyncAgentExchangeClient
from agent.config import AgentConfig


def get_sdk_tools(config: AgentConfig) -> list:
    """Build tool functions that use the SDK client."""

    client = AsyncAgentExchangeClient(
        api_key=config.platform_api_key,
        api_secret=config.platform_api_secret,
        base_url=config.platform_base_url,
    )

    async def get_price(ctx: RunContext, symbol: str) -> dict:
        """Get current price for a trading pair."""
        price = await client.get_price(symbol)
        return {"symbol": symbol, "price": str(price.price), "timestamp": str(price.timestamp)}

    async def get_balance(ctx: RunContext) -> dict:
        """Get account balance breakdown."""
        balance = await client.get_balance()
        return {"total_equity": str(balance.total_equity), "assets": balance.assets}

    async def place_market_order(ctx: RunContext, symbol: str, side: str, quantity: str) -> dict:
        """Place a market order. side='buy' or 'sell'. quantity as string."""
        order = await client.place_market_order(symbol, side, Decimal(quantity))
        return {"order_id": str(order.order_id), "status": order.status, "filled_qty": str(order.filled_quantity)}

    async def get_candles(ctx: RunContext, symbol: str, interval: str = "1h", limit: int = 50) -> list:
        """Get OHLCV candles for technical analysis."""
        candles = await client.get_candles(symbol, interval, limit)
        return [{"t": str(c.timestamp), "o": str(c.open), "h": str(c.high),
                 "l": str(c.low), "c": str(c.close), "v": str(c.volume)} for c in candles]

    async def get_performance(ctx: RunContext) -> dict:
        """Get performance metrics (Sharpe, drawdown, win rate, etc.)."""
        perf = await client.get_performance()
        return perf.__dict__

    async def get_positions(ctx: RunContext) -> list:
        """Get all open positions with unrealized PnL."""
        positions = await client.get_positions()
        return [p.__dict__ for p in positions]

    async def get_trade_history(ctx: RunContext, limit: int = 20) -> list:
        """Get recent trade execution history."""
        trades = await client.get_trade_history(limit=limit)
        return [t.__dict__ for t in trades]

    return [get_price, get_balance, place_market_order, get_candles,
            get_performance, get_positions, get_trade_history]
```

#### 2.2 MCP Tools (Auto-discovered — all 58 platform tools)

`**agent/tools/mcp_tools.py`:**

```python
"""MCP-based tools — auto-discovers all 58 platform tools."""
import os
from pydantic_ai.mcp import MCPServerStdio

def get_mcp_server(config) -> MCPServerStdio:
    """Create MCP server connection to our platform."""
    return MCPServerStdio(
        "python", ["-m", "src.mcp.server"],
        env={
            "MCP_API_KEY": config.platform_api_key,
            "API_BASE_URL": config.platform_base_url,
            **os.environ,
        },
        cwd=str(config.platform_root),  # project root
    )

# Usage in agent:
# agent = Agent('openrouter:...', mcp_servers=[get_mcp_server(config)])
# All 58 MCP tools become available automatically
```

#### 2.3 REST Tools (For endpoints the SDK doesn't cover)

`**agent/tools/rest_tools.py`:**

```python
"""Direct REST tools for endpoints not in SDK (backtesting, battles, strategies)."""
import httpx
from agent.config import AgentConfig


class PlatformRESTClient:
    """Thin REST wrapper for non-SDK endpoints."""

    def __init__(self, config: AgentConfig):
        self.base = f"{config.platform_base_url}/api/v1"
        self.headers = {"X-API-Key": config.platform_api_key}
        self._client = httpx.AsyncClient(timeout=30.0)

    async def create_backtest(self, start_time: str, end_time: str,
                               symbols: list[str], interval: str = "1h") -> dict:
        r = await self._client.post(f"{self.base}/backtest/create", headers=self.headers,
            json={"start_time": start_time, "end_time": end_time,
                  "symbols": symbols, "interval": interval})
        r.raise_for_status()
        return r.json()

    async def start_backtest(self, session_id: str) -> dict:
        r = await self._client.post(f"{self.base}/backtest/{session_id}/start",
                                     headers=self.headers)
        r.raise_for_status()
        return r.json()

    async def step_backtest_batch(self, session_id: str, steps: int) -> dict:
        r = await self._client.post(f"{self.base}/backtest/{session_id}/step/batch",
            headers=self.headers, json={"steps": steps})
        r.raise_for_status()
        return r.json()

    async def backtest_trade(self, session_id: str, symbol: str,
                              side: str, quantity: str) -> dict:
        r = await self._client.post(f"{self.base}/backtest/{session_id}/trade/order",
            headers=self.headers,
            json={"symbol": symbol, "side": side, "type": "market", "quantity": quantity})
        r.raise_for_status()
        return r.json()

    async def get_backtest_results(self, session_id: str) -> dict:
        r = await self._client.get(f"{self.base}/backtest/{session_id}/results",
                                    headers=self.headers)
        r.raise_for_status()
        return r.json()

    # ... strategies, battles, training endpoints similarly
```

---

### Phase 3: Output Models (Day 3)

#### 3.1 Structured Agent Outputs

`**agent/models/trade_signal.py`:**

```python
from pydantic import BaseModel
from decimal import Decimal
from enum import Enum

class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class TradeSignal(BaseModel):
    """What the agent decides to do after analysis."""
    symbol: str
    signal: SignalType
    confidence: float          # 0.0-1.0
    quantity_pct: float        # % of equity to use (0.01-0.10)
    reasoning: str             # Why this trade
    risk_notes: str            # What could go wrong
```

`**agent/models/report.py`:**

```python
from pydantic import BaseModel

class WorkflowResult(BaseModel):
    """Result of a test workflow run."""
    workflow_name: str
    status: str                # "pass", "fail", "partial"
    steps_completed: int
    steps_total: int
    findings: list[str]        # What we discovered
    bugs_found: list[str]      # Platform bugs/issues
    suggestions: list[str]     # Platform improvement ideas
    metrics: dict              # Performance numbers

class PlatformValidationReport(BaseModel):
    """Overall report from a full test session."""
    session_id: str
    model_used: str
    workflows_run: list[WorkflowResult]
    platform_health: str       # "healthy", "degraded", "broken"
    summary: str
```

---

### Phase 4: System Prompt & Context (Day 3)

#### 4.1 System Prompt

`**agent/prompts/system.py`:**

```python
SYSTEM_PROMPT = """
You are a TradeReady Platform Testing Agent. Your job is to validate that the
TradeReady crypto trading platform works correctly and that its tools genuinely
help improve trading outcomes.

## Your Identity
- You are an AI agent connected to a simulated crypto trading platform
- You trade with virtual USDT against real Binance market data (600+ pairs)
- Your purpose is platform validation, not profit maximization

## What You Test
1. **Tool correctness** — Do API calls return expected data? Are errors handled?
2. **Trading workflows** — Can you register, trade, track PnL, analyze performance?
3. **Backtesting** — Does historical replay work? Are results consistent?
4. **Strategy testing** — Can you create strategies, test them, compare versions?
5. **Improvement loop** — Can the platform's analytics actually guide better decisions?

## How You Work
- Start by checking connectivity (get price, get balance)
- Execute the requested workflow step by step
- Report findings as structured output
- Flag any bugs, errors, or unexpected behavior immediately
- Track whether the platform's tools helped you make better decisions

## Trading Rules
- Never risk more than 5% of equity per trade
- Always check your balance before trading
- Use limit orders when you have a specific price target
- Document your reasoning for every trade decision

## When Something Fails
- Capture the exact error message and context
- Note the tool/endpoint that failed
- Try an alternative approach if possible
- Include the failure in your report
"""
```

#### 4.2 Skill Context Loader

```python
# agent/prompts/skill_context.py
async def load_skill_context(config) -> str:
    """Load the platform's skill.md for rich context."""
    import httpx
    async with httpx.AsyncClient() as client:
        # If we have an agent_id, fetch personalized skill.md
        r = await client.get(
            f"{config.platform_base_url}/api/v1/agents/{config.agent_id}/skill.md",
            headers={"Authorization": f"Bearer {config.jwt_token}"},
        )
        if r.status_code == 200:
            return r.text
    return ""  # Fallback: use system prompt only
```

---

### Phase 5: Test Workflows (Days 4-5)

#### 5.1 Smoke Test

```python
# agent/workflows/smoke_test.py
"""Validates basic platform connectivity across all integration methods."""

async def run_smoke_test(agent, config):
    """
    Steps:
    1. SDK: get_price("BTCUSDT") — verify non-zero price
    2. SDK: get_balance() — verify starting balance
    3. SDK: get_candles("BTCUSDT", "1h", 10) — verify historical data
    4. SDK: place_market_order("BTCUSDT", "buy", "0.0001") — tiny test trade
    5. SDK: get_positions() — verify position opened
    6. SDK: get_trade_history() — verify trade recorded
    7. SDK: get_performance() — verify metrics calculate
    8. MCP: get_price, get_pairs — verify MCP server responds
    9. REST: /health — verify platform health
    10. Report: structured WorkflowResult
    """
```

#### 5.2 Trading Workflow

```python
# agent/workflows/trading_workflow.py
"""Full trading lifecycle: analyze → decide → trade → monitor → close."""

async def run_trading_workflow(agent, config):
    """
    Steps:
    1. Fetch 1h candles for BTC, ETH, SOL (last 100)
    2. Agent analyzes trends (moving averages, momentum)
    3. Agent generates TradeSignal with reasoning
    4. Execute the trade via SDK
    5. Monitor position (check price 3 times with 10s delay)
    6. Close position
    7. Check PnL and performance metrics
    8. Agent evaluates: did the analysis help?
    9. Report: WorkflowResult with trade details
    """
```

#### 5.3 Backtest Workflow

```python
# agent/workflows/backtest_workflow.py
"""Create backtest → trade in sandbox → analyze results → learn."""

async def run_backtest_workflow(agent, config):
    """
    Steps:
    1. REST: GET /market/data-range — find available data window
    2. REST: POST /backtest/create — 7-day window, BTC+ETH
    3. REST: POST /backtest/{id}/start — initialize sandbox
    4. Loop 100 steps:
       a. REST: GET /backtest/{id}/market/candles/BTCUSDT — get candles at virtual time
       b. Agent decides: buy/sell/hold based on candle data
       c. REST: POST /backtest/{id}/trade/order — execute in sandbox
       d. REST: POST /backtest/{id}/step/batch — advance 5 candles
    5. REST: GET /backtest/{id}/results — get metrics
    6. Agent analyzes: Sharpe ratio, max drawdown, win rate
    7. Agent proposes: what would it do differently?
    8. Report: BacktestAnalysis with improvement plan
    """
```

#### 5.4 Strategy Workflow

```python
# agent/workflows/strategy_workflow.py
"""Create strategy → test → iterate → compare versions."""

async def run_strategy_workflow(agent, config):
    """
    Steps:
    1. Agent designs a simple strategy definition (SMA crossover)
    2. REST: POST /strategies — create it
    3. REST: POST /strategies/{id}/test — run strategy test
    4. REST: GET /strategies/{id}/tests/{test_id} — poll until complete
    5. Agent reviews results and test-results recommendations
    6. Agent creates improved V2 based on findings
    7. REST: POST /strategies/{id}/versions — create V2
    8. REST: POST /strategies/{id}/test — test V2
    9. REST: GET /strategies/{id}/compare-versions — V1 vs V2
    10. Agent evaluates: did the platform's tools help iterate?
    11. Report: StrategyAnalysis with comparison
    """
```

---

### Phase 6: Entry Point & CLI (Day 5)

`**agent/main.py**` (full version):

```python
import asyncio
import argparse
import structlog
from agent.config import AgentConfig
from agent.workflows import smoke_test, trading_workflow, backtest_workflow, strategy_workflow

log = structlog.get_logger()

WORKFLOWS = {
    "smoke": smoke_test.run_smoke_test,
    "trade": trading_workflow.run_trading_workflow,
    "backtest": backtest_workflow.run_backtest_workflow,
    "strategy": strategy_workflow.run_strategy_workflow,
    "all": None,  # Runs everything
}

async def main(workflow: str, model: str | None = None):
    config = AgentConfig()
    if model:
        config.agent_model = model

    log.info("starting_agent", model=config.agent_model, workflow=workflow)

    if workflow == "all":
        for name, fn in WORKFLOWS.items():
            if fn is not None:
                log.info("running_workflow", name=name)
                await fn(config)
    else:
        await WORKFLOWS[workflow](config)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TradeReady Platform Testing Agent")
    parser.add_argument("workflow", choices=WORKFLOWS.keys(), default="smoke",
                        help="Which test workflow to run")
    parser.add_argument("--model", type=str, default=None,
                        help="Override model (e.g., openrouter:openai/gpt-4o)")
    args = parser.parse_args()
    asyncio.run(main(args.workflow, args.model))
```

**Usage:**

```bash
cd agent
python -m agent.main smoke                                    # Quick connectivity test
python -m agent.main trade                                    # Full trading workflow
python -m agent.main backtest                                 # Backtest workflow
python -m agent.main strategy                                 # Strategy iteration
python -m agent.main all                                      # Everything
python -m agent.main trade --model openrouter:openai/gpt-4o   # Test with different model
```

---

## 5. Dependencies

```
pydantic-ai-slim[openrouter]>=0.2    # Core framework + OpenRouter provider
agentexchange                         # Our SDK (pip install -e ../sdk/)
httpx>=0.28                           # Async HTTP (for REST tools)
python-dotenv>=1.0                    # .env loading
structlog>=24.0                       # Structured logging
pydantic-settings>=2.0                # Config from env
```

Dev dependencies:

```
pytest>=8.0
pytest-asyncio>=0.24
ruff>=0.8
```

---

## 6. Integration Matrix

How the agent uses each platform surface:


| Integration         | Used For                                      | Tools Count   | Auth Method         |
| ------------------- | --------------------------------------------- | ------------- | ------------------- |
| **SDK** (primary)   | Trading, market data, account, analytics      | 35 methods    | API key + auto-JWT  |
| **MCP** (discovery) | Full platform access, auto-discovered tools   | 58 tools      | API key via env var |
| **REST** (direct)   | Backtesting, strategies, battles (not in SDK) | 90+ endpoints | API key header      |
| **skill.md**        | System prompt enrichment                      | N/A           | Fetched via REST    |


### When to Use What


| Task                                         | Integration            |
| -------------------------------------------- | ---------------------- |
| Get price, place trade, check balance        | SDK (typed, retries)   |
| Run backtest lifecycle                       | REST (not in SDK)      |
| Create/test strategies                       | REST (not in SDK)      |
| Auto-discover all platform capabilities      | MCP (58 tools at once) |
| Enrich agent context with platform knowledge | skill.md               |


---

## 7. Model Strategy

OpenRouter lets us swap models per task:


| Task Type                    | Model                         | Why                              |
| ---------------------------- | ----------------------------- | -------------------------------- |
| Trading analysis & decisions | `anthropic/claude-sonnet-4-5` | Best reasoning                   |
| Bulk data processing         | `google/gemini-2.0-flash-001` | Cheap, fast, large context       |
| Creative strategy design     | `anthropic/claude-sonnet-4-5` | Creative + structured            |
| Simple validations           | `google/gemini-2.0-flash-001` | Cost-effective                   |
| Testing model diversity      | Any model on OpenRouter       | Validate platform works with all |


```python
# Swap models at runtime
analysis_agent = Agent('openrouter:anthropic/claude-sonnet-4-5', ...)
validation_agent = Agent('openrouter:google/gemini-2.0-flash-001', ...)
```

---

## 8. Success Criteria for V1

### Must Have (MVP)

- Agent connects to platform via SDK and executes a trade
- Agent fetches and analyzes candle data
- Agent runs a backtest and reads results
- Structured output (Pydantic models) for all responses
- Smoke test workflow passes end-to-end
- Works with at least 2 different models via OpenRouter

### Should Have

- Trading workflow: analyze → decide → trade → evaluate
- Backtest workflow: create → trade in sandbox → analyze
- Strategy workflow: create → test → iterate
- Error handling for all platform failures
- Structured test reports saved to disk

### Nice to Have (V1.1)

- MCP auto-discovery mode (agent explores all 58 tools)
- Multi-model comparison (same workflow, different models)
- skill.md context injection for richer reasoning

---

## 9. Risks & Mitigations


| Risk                           | Impact               | Mitigation                                       |
| ------------------------------ | -------------------- | ------------------------------------------------ |
| OpenRouter rate limits         | Agent stalls         | Use cheap model for bulk ops, cache results      |
| Platform not running           | All workflows fail   | Smoke test first; clear error messages           |
| Model hallucinating tool calls | Invalid API calls    | Pydantic output validation, structured tools     |
| SDK version mismatch           | Methods fail         | Pin SDK version, run smoke test                  |
| Cost runaway                   | High OpenRouter bill | Set max tokens, use flash models for cheap tasks |


---

## 10. Future Roadmap (Post-V1)


| Version | Feature                   | Description                                                    |
| ------- | ------------------------- | -------------------------------------------------------------- |
| V1.1    | **Cron loop**             | Scheduled continuous testing (every hour)                      |
| V1.2    | **WebSocket integration** | Real-time price reactions, live monitoring                     |
| V1.3    | **Battle automation**     | Agent creates and runs agent-vs-agent battles                  |
| V1.4    | **Multi-agent crew**      | Analyst + Trader + Risk Manager (CrewAI layer)                 |
| V1.5    | **Gymnasium RL**          | Train agents on historical data, track improvement             |
| V2.0    | **Self-improving loop**   | Agent backtests → finds weakness → updates strategy → re-tests |


---

## 11. Task Breakdown for Implementation


| #   | Task                                            | Estimated Effort | Dependencies |
| --- | ----------------------------------------------- | ---------------- | ------------ |
| 1   | Create `agent/` directory structure             | 30 min           | None         |
| 2   | Write `pyproject.toml` + install deps           | 30 min           | #1           |
| 3   | Implement `config.py`                           | 30 min           | #2           |
| 4   | Implement SDK tools (`tools/sdk_tools.py`)      | 2 hrs            | #3           |
| 5   | Implement MCP connection (`tools/mcp_tools.py`) | 1 hr             | #3           |
| 6   | Implement REST tools (`tools/rest_tools.py`)    | 2 hrs            | #3           |
| 7   | Define output models (`models/`)                | 1 hr             | #2           |
| 8   | Write system prompt                             | 1 hr             | None         |
| 9   | Implement smoke test workflow                   | 2 hrs            | #4, #5, #6   |
| 10  | Implement trading workflow                      | 3 hrs            | #4, #7, #8   |
| 11  | Implement backtest workflow                     | 3 hrs            | #6, #7       |
| 12  | Implement strategy workflow                     | 3 hrs            | #6, #7       |
| 13  | Write CLI entry point (`main.py`)               | 1 hr             | #9-12        |
| 14  | End-to-end test: smoke → trade → backtest       | 2 hrs            | #13          |
| 15  | Documentation (README.md)                       | 1 hr             | #14          |


**Total: ~22 hours of implementation**

---

## 12. How to Start

```bash
# 1. Ensure platform is running
docker compose up -d
# Or: uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 2. Create agent directory and install
cd agent
pip install -e ".[dev]"
pip install -e ../sdk/

# 3. Set up credentials
cp .env.example .env
# Edit .env: add OPENROUTER_API_KEY

# 4. Register on platform (one-time)
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "TestAgent", "starting_balance": "10000.00"}'
# Save api_key and api_secret to .env

# 5. Run smoke test
python -m agent.main smoke

# 6. Run full test suite
python -m agent.main all
```

