# Documentation

<!-- last-updated: 2026-03-18 -->

> Public-facing documentation for the AgentExchange platform: API reference, guides, tutorials, and framework integrations for AI agent developers.

## What This Module Does

The `docs/` directory contains all user-facing documentation for the AgentExchange trading platform. It serves three distinct audiences: new users getting started, AI agent developers integrating via SDK or MCP, and framework-specific integration guides for popular agent frameworks. None of these files contain application logic; they are reference and instructional material only.

## Document Inventory

| Document | Audience | Purpose |
|----------|----------|---------|
| `quickstart.md` | New users, developers | 5-minute onboarding: Docker setup, account registration, first trade via curl and Python SDK |
| `api_reference.md` | Backend developers, agent builders | Complete REST API reference covering all endpoints (auth, market, trading, account, analytics), WebSocket protocol, error codes, rate limits, and response shapes |
| `skill.md` | LLM agents (system prompt injection) | Drop-in Markdown instruction file for any AI agent's context window; contains full API spec, auth flow, order types, error handling, and trading workflows in LLM-readable format (~46KB) |
| `mcp_server.md` | AI agent developers using MCP clients | Setup guide for the Model Context Protocol server: Claude Desktop, Cline, and generic MCP client configuration; lists all 43 available tools with parameters across 7 categories (market data, account, trading, analytics, backtesting, agent management, battles) |
| `backtesting-guide.md` | Agent developers, strategy builders | Technical guide covering the full backtesting lifecycle: session creation, stepping, sandbox trading, order types, results endpoints, strategy examples (SMA crossover, RSI, breakout, rotation), step batching, and position sizing |
| `backtesting-explained.md` | Non-technical users, stakeholders | Plain-English explanation of backtesting using analogies (flight simulator, time machine); covers metrics definitions (Sharpe, drawdown, win rate), strategy types, and iteration workflow without code |
| `framework_guides/langchain.md` | LangChain developers | Step-by-step integration: SDK client setup, LangChain `Tool` and `StructuredTool` wrappers, `AgentExecutor` with ReAct prompt, WebSocket streaming, async agent pattern |
| `framework_guides/crewai.md` | CrewAI developers | Multi-agent crew setup: `@tool`-decorated SDK wrappers, 3-agent crew (analyst/trader/risk manager), sequential and hierarchical `Process` modes, autonomous strategy loop |
| `framework_guides/agent_zero.md` | Agent Zero developers | Skill file integration: drop `skill.md` into Agent Zero's skills directory, credential injection via system prompt, SDK tool registration, WebSocket background feed |
| `framework_guides/openclaw.md` | OpenClaw developers | Skill-based integration: `agent.yaml` configuration, `@openclaw.tool` SDK wrappers, session-based and autonomous agent patterns |
| `plan-task.md` | Internal (team) | 6-phase execution plan: CCXT integration, MCP expansion, SDK polish, freemium tiers, launch competition, framework integrations |
| `tradeready_research.md` | Internal (team) | Competitive landscape analysis: 15+ competitors, positioning, differentiators, go-to-market |
| `ccxt_resarch_report.md` | Internal (team) | CCXT integration analysis: pricing ($0), 110 exchanges, architecture, implementation roadmap |
| `pricing_tiers_business_report.md` | Internal (team) | Freemium tier design and business model analysis |
| `rate_limits.md` | Developers | API rate limit documentation per endpoint group |

## Common Tasks

**Adding a new endpoint to docs**: Update `api_reference.md` with the endpoint spec (method, path, params, response shape, error codes). If the endpoint is relevant to AI agents, also update `skill.md` so LLM agents can discover and use it.

**Adding a new framework guide**: Create a new file under `framework_guides/`. Follow the existing pattern: prerequisites, account registration, SDK client setup, tool wrappers, agent configuration, example prompts, error handling table, troubleshooting section. Add a cross-reference link in all other guide files' "Next Steps" section.

**Updating backtesting docs**: If the backtesting API changes, update both `backtesting-guide.md` (technical) and `backtesting-explained.md` (non-technical) to keep them in sync. The guide is the source of truth for API shapes; the explained doc is the source of truth for plain-English descriptions.

**Updating skill.md**: This file is consumed by LLM agents at runtime. Changes affect agent behavior directly. Keep it self-contained (no external links agents cannot follow), use explicit examples, and always include error handling guidance.

## Recent Changes

- `2026-03-17` — Initial CLAUDE.md created
- `2026-03-18` — Added plan-task.md, tradeready_research.md, ccxt_resarch_report.md, pricing_tiers_business_report.md, rate_limits.md to inventory
- `2026-03-18` — Updated mcp_server.md inventory entry: 12 tools → 43 tools (Phase 2 MCP expansion)
