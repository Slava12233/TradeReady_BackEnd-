"""MCP server entry point for the AI Agent Crypto Trading Platform.

Runs as a standalone process via ``python -m src.mcp.server`` and
communicates with MCP-compatible clients (e.g. Claude Desktop, cline)
over the stdio transport.

All 12 trading tools are registered via :func:`~src.mcp.tools.register_tools`
and internally forward their calls to the platform REST API using an
``httpx.AsyncClient`` authenticated with the agent's API key.

Configuration (environment variables):

    API_BASE_URL   Base URL of the trading platform REST API.
                   Defaults to ``http://localhost:8000``.
    MCP_API_KEY    API key (``ak_live_...``) used to authenticate every
                   REST call.  **Required** — the server will not start
                   without it.
    MCP_JWT_TOKEN  Optional pre-issued JWT.  When provided the server
                   sends ``Authorization: Bearer <token>`` alongside the
                   API key so that all endpoints that require JWT auth
                   work out of the box.
    LOG_LEVEL      Python logging level for the MCP process.
                   Defaults to ``WARNING`` so that debug noise does not
                   corrupt the stdio JSON-RPC stream.

Usage::

    # Minimal (API key only)
    MCP_API_KEY=ak_live_... python -m src.mcp.server

    # With JWT (recommended for authenticated endpoints)
    MCP_API_KEY=ak_live_... MCP_JWT_TOKEN=eyJ... python -m src.mcp.server

    # Point at a remote platform instance
    API_BASE_URL=https://api.example.com \\
    MCP_API_KEY=ak_live_... \\
    python -m src.mcp.server
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import os
import sys

import httpx

from mcp.server import Server
from mcp.server.stdio import stdio_server
from src.mcp.tools import register_tools

# ---------------------------------------------------------------------------
# Logging — keep it quiet by default so debug output does not corrupt the
# JSON-RPC stdio stream that Claude / other clients read from stdout.
# ---------------------------------------------------------------------------

_LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,  # always log to stderr — stdout is owned by MCP transport
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

_API_BASE_URL: str = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
_MCP_API_KEY: str = os.environ.get("MCP_API_KEY", "")
_MCP_JWT_TOKEN: str = os.environ.get("MCP_JWT_TOKEN", "")

_SERVER_NAME = "agentexchange"
_SERVER_VERSION = "1.0.0"
_SERVER_INSTRUCTIONS = (
    "You are connected to AgentExchange — a simulated crypto trading platform "
    "powered by real-time Binance market data. Use the available tools to check "
    "prices, manage your portfolio, and place orders with virtual funds."
)

# ---------------------------------------------------------------------------
# HTTP client factory
# ---------------------------------------------------------------------------


def _build_http_client() -> httpx.AsyncClient:
    """Build an authenticated ``httpx.AsyncClient`` for REST API calls.

    Returns:
        A configured async HTTP client with base URL and auth headers set.

    Raises:
        SystemExit: When ``MCP_API_KEY`` is not set, the process exits with
            a descriptive error message to avoid silently running unauthenticated.
    """
    if not _MCP_API_KEY:
        logger.critical(
            "MCP_API_KEY environment variable is not set. "
            "The MCP server cannot authenticate REST API calls. "
            "Set MCP_API_KEY=ak_live_<your_key> and restart."
        )
        sys.exit(1)

    headers: dict[str, str] = {"X-API-Key": _MCP_API_KEY}
    if _MCP_JWT_TOKEN:
        headers["Authorization"] = f"Bearer {_MCP_JWT_TOKEN}"

    client = httpx.AsyncClient(
        base_url=_API_BASE_URL,
        headers=headers,
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )
    logger.info("HTTP client initialised — base_url=%s", _API_BASE_URL)
    return client


# ---------------------------------------------------------------------------
# MCP server lifespan — owns the httpx client lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(server: Server) -> AsyncIterator[dict[str, httpx.AsyncClient]]:
    """Async context manager that manages the httpx client lifecycle.

    Yields a dict that is stored as the server's lifespan context.  The
    ``register_tools`` closure captures the client at registration time, so
    this context does not need to be accessed at call time, but it provides
    a clean shutdown hook.

    Args:
        server: The MCP ``Server`` instance (unused; required by the signature).

    Yields:
        Mapping with key ``"http_client"`` pointing at the live client.
    """
    http_client = _build_http_client()
    logger.debug("MCP lifespan: HTTP client created")
    try:
        yield {"http_client": http_client}
    finally:
        await http_client.aclose()
        logger.debug("MCP lifespan: HTTP client closed")


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server() -> tuple[Server, httpx.AsyncClient]:
    """Instantiate the MCP server and register all 12 tools.

    The HTTP client is created here (before the lifespan runs) so that it
    can be injected into ``register_tools``.  The same client is also
    returned and will be reused inside the lifespan context — the lifespan
    only manages its cleanup.

    Returns:
        A 2-tuple of ``(server, http_client)``.

    Raises:
        SystemExit: Propagated from :func:`_build_http_client` when
            ``MCP_API_KEY`` is missing.
    """
    http_client = _build_http_client()

    server: Server = Server(
        name=_SERVER_NAME,
        version=_SERVER_VERSION,
        instructions=_SERVER_INSTRUCTIONS,
    )

    register_tools(server, http_client)
    logger.info("MCP server '%s' v%s ready with 12 tools", _SERVER_NAME, _SERVER_VERSION)
    return server, http_client


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the MCP server over the stdio transport until the client disconnects.

    This coroutine:
    1. Creates the MCP ``Server`` instance and registers all 12 tools.
    2. Opens the stdio transport context manager.
    3. Calls ``server.run()`` with the read/write streams and initialisation
       options, blocking until the session ends or an unrecoverable error
       occurs.
    4. Ensures the httpx client is always closed on exit.
    """
    server, http_client = create_server()

    try:
        async with stdio_server() as (read_stream, write_stream):
            init_options = server.create_initialization_options()
            logger.debug("Starting MCP server session (stdio transport)")
            await server.run(
                read_stream=read_stream,
                write_stream=write_stream,
                initialization_options=init_options,
            )
    finally:
        await http_client.aclose()
        logger.debug("MCP server shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
