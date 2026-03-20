---
task_id: 3
title: "Research SDK/MCP/REST integration surfaces"
agent: "codebase-researcher"
phase: 1
depends_on: []
status: "completed"
priority: "high"
files: []
---

# Task 3: Research SDK/MCP/REST integration surfaces

## Assigned Agent: `codebase-researcher`

## Objective
Research and document the exact API surfaces the agent will integrate with — SDK methods, MCP tool signatures, and REST endpoints for backtesting/strategies/battles.

## Context
The agent connects to the TradeReady platform via three methods. The tool layer (Tasks 4-6) needs precise method signatures, endpoint paths, and auth patterns. This research task produces a reference that the backend-developer agent will use.

## Research Questions
1. **SDK (`sdk/`):** What methods does `AsyncAgentExchangeClient` expose? List all public methods with signatures and return types.
2. **MCP (`src/mcp/`):** How does the MCP server start? What env vars does it need? How does a Pydantic AI agent connect via `MCPServerStdio`?
3. **REST backtesting (`src/api/routes/`):** What are the exact endpoint paths for backtest create, start, step, step/batch, trade, results? What request/response shapes?
4. **REST strategies (`src/api/routes/`):** What are the strategy CRUD + test + compare-versions endpoints?
5. **Auth patterns:** How does X-API-Key auth work? How does JWT auth work? Which does the agent need?

## Deliverable
Write findings to `development/tasks/tradeready-test-agent/research-integration-surfaces.md` with exact method signatures, endpoint paths, request/response shapes, and auth requirements.

## Acceptance Criteria
- [ ] All `AsyncAgentExchangeClient` public methods documented with signatures
- [ ] MCP server connection pattern documented (env vars, cwd, command)
- [ ] All backtest REST endpoints listed with paths and JSON shapes
- [ ] All strategy REST endpoints listed with paths and JSON shapes
- [ ] Auth requirements clear for each integration method

## Dependencies
None — pure research task.

## Agent Instructions
- Start by reading `sdk/CLAUDE.md`, `src/mcp/CLAUDE.md`, `src/api/routes/CLAUDE.md`
- Read `sdk/agentexchange/async_client.py` for SDK method signatures
- Read `src/mcp/server.py` for MCP tool registration
- Read `src/api/routes/backtest_routes.py` and `src/api/routes/strategy_routes.py` for endpoint definitions
- Grep for `MCPServerStdio` in pydantic-ai docs patterns if needed

## Estimated Complexity
Medium — requires reading multiple files across several modules
