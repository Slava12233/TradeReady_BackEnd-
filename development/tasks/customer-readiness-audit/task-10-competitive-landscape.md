---
task_id: 10
title: "Competitive Landscape & Market Research"
type: task
agent: "planner"
phase: 1
depends_on: []
status: "pending"
priority: "medium"
board: "[[customer-readiness-audit/README]]"
files:
  - "development/tasks/customer-readiness-audit/sub-reports/10-competitive-landscape.md"
tags:
  - task
  - audit
  - market-research
  - competitive
  - positioning
---

# Task 10: Competitive Landscape & Market Research

## Assigned Agent: `planner`

## Objective
Research the competitive landscape for AI trading platforms. Understand who the competitors are, what they offer, how they price, and where TradeReady has unique advantages. This informs the marketing message and identifies which features matter most to early customers.

## Context
TradeReady is a simulated crypto exchange for AI agents. Key differentiators (from platform-tools-report.md):
- Virtual USDT + real Binance prices (no financial risk)
- 600+ trading pairs
- Agent-vs-agent battle system
- MCP + SDK + REST + WebSocket connectivity
- Gymnasium environments for RL training
- Multi-agent architecture with isolated wallets

Target: AI developers, quant researchers, crypto traders building bots.

## Research Areas

### 1. Direct Competitors
Research platforms that offer simulated/paper trading for AI agents or bots:
- **Alpaca** — Paper trading API for stocks/crypto
- **QuantConnect** — Cloud-based algo trading platform
- **Freqtrade** — Open-source crypto trading bot framework
- **Hummingbot** — Open-source market making bot
- **TradingView** — Pine Script strategy backtesting
- **Backtrader** — Python backtesting framework
- **Jesse** — Crypto algo trading framework
- **Zipline** — Quantopian's backtesting library (archived)
- **3Commas** — Crypto bot marketplace
- Any new AI-specific trading platforms

### 2. Feature Comparison
For each competitor, assess:

| Feature | TradeReady | Competitor A | Competitor B | ... |
|---------|-----------|-------------|-------------|-----|
| Simulated crypto trading | Y | ? | ? | |
| Real-time market data | Y (600+) | ? | ? | |
| REST API | Y (127+) | ? | ? | |
| WebSocket | Y | ? | ? | |
| Python SDK | Y | ? | ? | |
| MCP server for LLMs | Y | ? | ? | |
| Gymnasium RL envs | Y | ? | ? | |
| Agent battle system | Y | ? | ? | |
| Backtesting | Y | ? | ? | |
| Multi-agent support | Y | ? | ? | |
| Free tier | ? | ? | ? | |

### 3. Pricing Analysis
- What do competitors charge?
- What's the standard pricing model (freemium, per-trade, monthly)?
- Is our planned Free / Pro $29 / Enterprise right for the market?
- What limits should free tier have?

### 4. Target Customer Segments
Who would use TradeReady?
1. **AI/ML researchers** building RL trading agents
2. **Crypto bot developers** testing strategies
3. **Hackathon participants** wanting a quick trading sandbox
4. **Quant finance students** learning algorithmic trading
5. **LLM agent builders** wanting tool-use environments

### 5. Unique Selling Proposition
What makes TradeReady different? Draft 3 positioning options:
- "The gym for AI trading agents"
- "Battle-tested strategies, zero risk"
- "From RL training to live crypto trading"

### 6. Onboarding Friction Assessment
How easy is it for a new user to get started compared to competitors?
- Steps from signup to first trade
- Documentation quality
- SDK quickstart experience
- LLM skill.md integration (unique!)

## Output Format

Write findings to `development/tasks/customer-readiness-audit/sub-reports/10-competitive-landscape.md`:

```markdown
# Sub-Report 10: Competitive Landscape

**Date:** 2026-04-15
**Agent:** planner

## Top Competitors

| Platform | Type | Crypto? | AI-Focused? | Pricing | Key Strength |
|----------|------|---------|-------------|---------|-------------|
| Alpaca | Brokerage API | Yes | No | Free tier | Established, real trading |
| ... | ... | ... | ... | ... | ... |

## Feature Comparison Matrix
{filled comparison table}

## Pricing Analysis
{market pricing landscape and recommendation}

## Target Segments (ranked by fit)
1. {Best fit segment} — Why
2. {Second segment} — Why
3. {Third segment} — Why

## TradeReady's Unique Advantages
1. {advantage 1}
2. {advantage 2}
3. {advantage 3}

## TradeReady's Weaknesses vs Competitors
1. {weakness 1}
2. {weakness 2}

## Recommended Positioning
{1-sentence pitch and supporting rationale}

## First 10 Customers Strategy
{Who to target, where to find them, how to onboard them}
```

## Acceptance Criteria
- [ ] At least 5 competitors researched
- [ ] Feature comparison matrix completed
- [ ] Pricing analysis with recommendation
- [ ] Target segments ranked
- [ ] USP articulated
- [ ] First 10 customers strategy defined

## Agent Instructions
Use web search to research current competitor offerings, pricing, and features. Focus on what's available today, not announcements. Prioritize competitors that serve the AI/bot trading niche specifically.

## Estimated Complexity
Medium — research and analysis, no code changes
