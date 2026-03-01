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

## Requirements

- Python 3.12+
- `httpx>=0.28`
- `websockets>=14.0`

## License

MIT
