# MCP Server

<!-- last-updated: 2026-03-17 -->

> Exposes 12 trading tools over MCP stdio transport so AI agents (Claude Desktop, cline, etc.) can discover and invoke trading operations against the platform REST API.

## What This Module Does

The MCP (Model Context Protocol) server runs as a standalone process (`python -m src.mcp.server`) that communicates with MCP-compatible clients over **stdio transport** (JSON-RPC over stdin/stdout). It translates MCP tool calls into authenticated REST API requests against the trading platform using `httpx.AsyncClient`.

The server registers 12 tools covering market data, account management, trading, and analytics. All REST calls are authenticated via `X-API-Key` header (and optionally `Authorization: Bearer` for JWT-protected endpoints).

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package docstring; no exports |
| `server.py` | Entry point: env config, HTTP client factory, MCP `Server` creation, stdio transport loop |
| `tools.py` | 12 tool definitions (`_TOOL_DEFINITIONS`), `register_tools()`, `_dispatch()` routing, REST call helpers |

## Architecture & Patterns

### Startup flow

1. `main()` calls `create_server()` which builds an authenticated `httpx.AsyncClient` and a `mcp.server.Server` instance.
2. `register_tools(server, http_client)` registers two MCP handlers on the server:
   - `list_tools()` -- returns the static `_TOOL_DEFINITIONS` list.
   - `call_tool(name, arguments)` -- dispatches to `_dispatch()` which uses `match/case` to route tool names to REST endpoints.
3. `stdio_server()` opens the stdin/stdout transport; `server.run()` blocks until the client disconnects.
4. On shutdown, the `httpx.AsyncClient` is closed in a `finally` block.

### Tool dispatch pattern

`_dispatch()` uses Python 3.10+ structural pattern matching (`match name: case "get_price": ...`) to map each tool name to an `_call_api()` call with the appropriate HTTP method, path, and parameters. Errors are caught at the `call_tool` level and formatted via `_error_content()`.

### Logging

All logging goes to **stderr** (never stdout) because stdout is owned by the MCP JSON-RPC transport. Default log level is `WARNING` to avoid corrupting the stream.

## Public API / Interfaces

### `register_tools(server: Server, http_client: httpx.AsyncClient) -> None`

Registers all 12 tools on the given MCP server. Called once at startup.

### `create_server() -> tuple[Server, httpx.AsyncClient]`

Factory that builds the configured server and HTTP client. Exits with code 1 if `MCP_API_KEY` is missing.

### `main() -> None`

Async entry point. Run via `python -m src.mcp.server`.

### The 12 Tools

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 1 | `get_price` | GET | `/api/v1/market/price/{symbol}` | `symbol` |
| 2 | `get_all_prices` | GET | `/api/v1/market/prices` | (none) |
| 3 | `get_candles` | GET | `/api/v1/market/candles/{symbol}` | `symbol`, `interval` |
| 4 | `get_balance` | GET | `/api/v1/account/balance` | (none) |
| 5 | `get_positions` | GET | `/api/v1/account/positions` | (none) |
| 6 | `place_order` | POST | `/api/v1/trade/order` | `symbol`, `side`, `type`, `quantity` |
| 7 | `cancel_order` | DELETE | `/api/v1/trade/order/{order_id}` | `order_id` |
| 8 | `get_order_status` | GET | `/api/v1/trade/order/{order_id}` | `order_id` |
| 9 | `get_portfolio` | GET | `/api/v1/account/portfolio` | (none) |
| 10 | `get_trade_history` | GET | `/api/v1/trade/history` | (none; optional `symbol`, `limit`) |
| 11 | `get_performance` | GET | `/api/v1/analytics/performance` | (none; optional `period`) |
| 12 | `reset_account` | POST | `/api/v1/account/reset` | `confirm` (must be `true`) |

## Dependencies

### External packages

- `mcp` -- MCP SDK (`mcp.server.Server`, `mcp.server.stdio.stdio_server`, `mcp.types`)
- `httpx` -- Async HTTP client for REST API calls (30s timeout, follows redirects)

### Internal

- No imports from other `src.*` modules. The MCP server is fully decoupled from the main application; it communicates exclusively via HTTP.

## Common Tasks

### Running the server

```bash
# Minimal
MCP_API_KEY=ak_live_... python -m src.mcp.server

# With JWT for authenticated endpoints
MCP_API_KEY=ak_live_... MCP_JWT_TOKEN=eyJ... python -m src.mcp.server

# Against a remote instance
API_BASE_URL=https://api.example.com MCP_API_KEY=ak_live_... python -m src.mcp.server
```

### Adding a new tool

1. Add a `types.Tool(...)` entry to `_TOOL_DEFINITIONS` in `tools.py` with name, description, and `inputSchema`.
2. Add a `case "tool_name":` branch in `_dispatch()` that calls the corresponding REST endpoint.
3. Update the tool count in docstrings (`server.py` line 179, `__init__.py`, `tools.py` header).

### Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `MCP_API_KEY` | Yes | (none) | API key for authenticating REST calls (`X-API-Key` header) |
| `MCP_JWT_TOKEN` | No | (none) | JWT token sent as `Authorization: Bearer` header |
| `API_BASE_URL` | No | `http://localhost:8000` | Base URL of the trading platform REST API |
| `LOG_LEVEL` | No | `WARNING` | Python log level for the MCP process |

## Gotchas & Pitfalls

- **stdout is sacred.** All logging MUST go to stderr. Any stray `print()` or stdout logging will corrupt the JSON-RPC transport and crash the MCP session.
- **`MCP_API_KEY` is mandatory.** The server calls `sys.exit(1)` if it is not set. There is no fallback or interactive prompt.
- **HTTP client is created twice.** `create_server()` builds the client eagerly (outside the lifespan). The `_lifespan` context manager exists but is not used by `main()`. The client cleanup happens in the `finally` block of `main()` instead.
- **`place_order` converts `quantity` and `price` to strings** before sending the JSON body, matching the API's `Decimal`-as-string convention.
- **`reset_account` has a client-side guard.** If `confirm` is not `true`, the tool returns an abort message without hitting the API.
- **No agent scoping.** The MCP server authenticates with a single API key. Agent context depends on which agent's API key is provided via `MCP_API_KEY`.
- **No retry logic.** Failed HTTP requests surface immediately as MCP error content. The client (e.g., Claude) is expected to handle retries at a higher level.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
