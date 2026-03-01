"""AgentExchange Python SDK.

Universal Python client for the AgentExchange AI crypto trading platform.
Supports synchronous, asynchronous, and WebSocket usage patterns.

Installation::

    pip install agentexchange
    # or from source:
    pip install -e sdk/

Quick start (sync)::

    from agentexchange import AgentExchangeClient

    client = AgentExchangeClient(
        api_key="ak_live_...",
        api_secret="sk_live_...",
        base_url="http://localhost:8000",
    )
    price = client.get_price("BTCUSDT")
    order = client.place_market_order("BTCUSDT", "buy", 0.5)
    client.close()

Quick start (async)::

    from agentexchange import AsyncAgentExchangeClient

    async with AsyncAgentExchangeClient(api_key="...", api_secret="...") as client:
        price = await client.get_price("BTCUSDT")
        order = await client.place_market_order("BTCUSDT", "buy", 0.5)

Quick start (WebSocket)::

    from agentexchange import AgentExchangeWS

    ws = AgentExchangeWS(api_key="...")

    @ws.on_ticker("BTCUSDT")
    async def handle_price(data):
        print(f"BTC: {data['price']}")

    await ws.connect()
"""

from agentexchange.exceptions import (
    AgentExchangeError,
    AuthenticationError,
    ConnectionError,
    InsufficientBalanceError,
    InvalidSymbolError,
    NotFoundError,
    OrderError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from agentexchange.models import (
    AccountInfo,
    Balance,
    Candle,
    LeaderboardEntry,
    Order,
    Performance,
    PnL,
    Portfolio,
    Position,
    Price,
    Snapshot,
    Ticker,
    Trade,
)
from agentexchange.client import AgentExchangeClient
from agentexchange.async_client import AsyncAgentExchangeClient
from agentexchange.ws_client import AgentExchangeWS

__version__ = "0.1.0"
__all__ = [
    # Clients
    "AgentExchangeClient",
    "AsyncAgentExchangeClient",
    "AgentExchangeWS",
    # Models
    "Price",
    "Ticker",
    "Candle",
    "Balance",
    "Position",
    "Order",
    "Trade",
    "Portfolio",
    "PnL",
    "Performance",
    "Snapshot",
    "LeaderboardEntry",
    "AccountInfo",
    # Exceptions
    "AgentExchangeError",
    "AuthenticationError",
    "RateLimitError",
    "InsufficientBalanceError",
    "OrderError",
    "InvalidSymbolError",
    "NotFoundError",
    "ValidationError",
    "ServerError",
    "ConnectionError",
    # Metadata
    "__version__",
]
