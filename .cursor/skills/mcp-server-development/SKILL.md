---
name: mcp-server-development
description: |
  Teaches the agent how to build the MCP (Model Context Protocol) server that
  exposes trading tools for Claude-based agents and MCP-compatible frameworks.
  Use when: adding MCP tools, defining tool schemas, wiring tools to REST/service
  layer, or working with src/mcp/ in this project.
---

# MCP Server Development

## Overview

- Runs as separate process.
- Exposes trading tools for Claude-based agents and MCP-compatible frameworks.
- **Files**: `src/mcp/server.py`, `src/mcp/tools.py`.
- Tools internally call the same service layer as REST endpoints.

## Tool List (12 Tools)

| Tool | Purpose |
|------|---------|
| `get_price` | Single symbol price |
| `get_all_prices` | All symbol prices |
| `get_candles` | OHLCV candles |
| `get_balance` | Account balance |
| `get_positions` | Open positions |
| `place_order` | Submit order |
| `cancel_order` | Cancel order |
| `get_order_status` | Order status |
| `get_portfolio` | Portfolio summary |
| `get_trade_history` | Trade history |
| `get_performance` | Performance metrics |
| `reset_account` | Reset account (requires confirm) |

## Tool Requirements

- Each tool: description, params with types/required, return schema.
- Parameter schemas must be properly typed (`str`, `number`, `bool`, enums where applicable).

## place_order Parameters

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `symbol` | str | yes | e.g. BTCUSDT |
| `side` | str | yes | enum: `buy`, `sell` |
| `type` | str | yes | enum: `market`, `limit`, `stop_loss`, `take_profit` |
| `quantity` | number | yes | Order size |
| `price` | number | no | Required for limit/stop_loss/take_profit |

## get_candles Parameters

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `symbol` | str | yes | e.g. BTCUSDT |
| `interval` | str | yes | enum: `1m`, `5m`, `15m`, `1h`, `4h`, `1d` |
| `limit` | int | no | Default 100 |

## reset_account Parameters

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `confirm` | bool | yes | Must be `true` to execute |

## Implementation Guidelines

1. Define tool schemas with explicit types and enums.
2. Map each tool to the corresponding service/REST layer call.
3. Return consistent JSON schema for all tools.
4. Handle errors and surface them in tool response.
5. Ensure `reset_account` only runs when `confirm=true`.

## Checklist

1. Implement all 12 tools in `tools.py`.
2. Register tools with MCP server in `server.py`.
3. Use enums for `side`, `type`, `interval`.
4. Wire tools to existing service layer (no duplicate logic).
5. Add `confirm` guard for `reset_account`.
