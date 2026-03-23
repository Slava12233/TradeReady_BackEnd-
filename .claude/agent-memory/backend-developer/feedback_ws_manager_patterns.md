---
name: feedback_ws_manager_patterns
description: Patterns for adding WSManager WebSocket integration to TradingLoop and AgentServer (Task 27)
type: feedback
---

## WSManager Integration Patterns

### How AgentExchangeWS is used

The existing `AgentExchangeWS` SDK client (sdk/agentexchange/ws_client.py) uses a decorator registration pattern (`@ws.on_ticker(symbol)`) and a blocking `await ws.connect()` call that handles reconnection internally. The correct pattern for integration is to run `ws.connect()` in a background asyncio task, not to `await` it directly from startup code.

**Why:** `ws.connect()` blocks until `disconnect()` is called. Starting it as a task lets the server remain non-blocking.

**How to apply:** Always wrap `ws.connect()` in `asyncio.get_event_loop().create_task(ws.connect())`.

### URL scheme conversion

`AgentExchangeWS` expects a `ws://` or `wss://` base URL. `AgentConfig.platform_base_url` uses `http://` or `https://`. Convert with:
```python
ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://")
```

**Why:** The SDK client constructs the full WS URL by appending `/ws/v1?api_key=...`.

### Closure variable capture in handler registration

When registering per-symbol handlers in a loop, use a default arg to capture the loop variable:
```python
for symbol in self._config.symbols:
    @self._ws.on_ticker(symbol)
    async def _on_tick(data: dict, _sym: str = symbol) -> None:
        await self._handle_ticker(data, _sym)
```

**Why:** Without the default arg, all closures capture the same `symbol` binding (the last value).

### Test patching for `AgentExchangeWS`

Since `_build_ws_client()` uses a local import (`from agentexchange import AgentExchangeWS`), patching at `agent.trading.ws_manager.AgentExchangeWS` does NOT work. Patch at `agentexchange.ws_client.AgentExchangeWS` — or mock `_build_ws_client` directly — to control the WS client in tests.

**How to apply:** Use `patch("agent.trading.ws_manager.WSManager._build_ws_client", return_value=mock_ws)` to inject a mock WS client without caring about the import path.

### Order-fill event timeout in tick()

The order-fill check in `tick()` uses a very short timeout (`_WS_FILL_CHECK_TIMEOUT_S = 0.05s`). This is intentional — the fill check must never meaningfully delay the trading cycle. If a fill just arrived but the timeout was missed, the next tick will pick it up.

### WSManager.disconnect() in TradingLoop.stop()

`TradingLoop.stop()` disconnects the `ws_manager` even if the manager was injected externally. This is safe because the server's `_shutdown()` also calls `ws_manager.disconnect()` — the SDK client handles double-disconnect gracefully.
