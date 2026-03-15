"""FastAPI application factory for the AgentExchange AI Trading Platform.

Wires together all middleware, REST routers, WebSocket endpoint, Prometheus
metrics, and startup/shutdown lifecycle hooks.

Run locally::

    uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
import structlog

from src.api.middleware.auth import AuthMiddleware
from src.api.middleware.logging import LoggingMiddleware
from src.api.middleware.rate_limit import RateLimitMiddleware
from src.api.routes.account import router as account_router
from src.api.routes.agents import router as agents_router
from src.api.routes.analytics import router as analytics_router
from src.api.routes.auth import router as auth_router
from src.api.routes.backtest import router as backtest_router
from src.api.routes.battles import router as battles_router
from src.api.routes.market import router as market_router
from src.api.routes.trading import router as trading_router
from src.api.routes.waitlist import router as waitlist_router
from src.api.websocket.handlers import (
    handle_message,
    start_redis_bridge,
    stop_redis_bridge,
)
from src.api.websocket.manager import ConnectionManager
from src.cache.redis_client import get_redis_client
from src.database.session import close_db, init_db
from src.monitoring.health import router as health_router
from src.utils.exceptions import TradingPlatformError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Manage application-wide resources across the full process lifetime.

    Startup sequence:
    1. Initialise async SQLAlchemy engine + asyncpg pool.
    2. Open the Redis connection pool.
    3. Create the WebSocket ``ConnectionManager`` and attach it to ``app.state``.
    4. Start the Redis pub/sub → WebSocket price bridge.

    Shutdown sequence (reverse order):
    1. Stop the Redis pub/sub bridge.
    2. Disconnect all active WebSocket clients.
    3. Close Redis pool.
    4. Close DB engine + asyncpg pool.

    Args:
        application: The FastAPI application instance (injected by Starlette).

    Yields:
        Control to the running application.
    """
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    # ── Database ──────────────────────────────────────────────────────────────
    await init_db()
    logger.info("startup.db_ready")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis = await get_redis_client()
    application.state.redis = redis
    logger.info("startup.redis_ready")

    # ── WebSocket manager ─────────────────────────────────────────────────────
    ws_manager = ConnectionManager()
    application.state.ws_manager = ws_manager
    logger.info("startup.ws_manager_ready")

    # ── Redis pub/sub → WebSocket bridge ──────────────────────────────────────
    await start_redis_bridge(redis, ws_manager)
    logger.info("startup.redis_bridge_ready")

    logger.info("startup.complete", extra={"version": "0.1.0"})

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("shutdown.starting")

    await stop_redis_bridge()
    logger.info("shutdown.bridge_stopped")

    await ws_manager.disconnect_all()
    logger.info("shutdown.ws_disconnected")

    await close_db()
    logger.info("shutdown.db_closed")

    logger.info("shutdown.complete")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Creates the ``FastAPI`` instance, registers all middleware (CORS, auth,
    rate-limiting, logging), mounts REST routers under ``/api/v1``, adds the
    WebSocket endpoint at ``/ws/v1``, registers the global exception handler,
    and mounts the Prometheus metrics endpoint at ``/metrics``.

    Returns:
        The fully configured :class:`~fastapi.FastAPI` instance.

    Example::

        # In tests:
        from src.main import create_app
        app = create_app()
    """
    application = FastAPI(
        title="AgentExchange — AI Trading Platform",
        description=(
            "Simulated crypto exchange powered by real-time Binance market data. "
            "AI agents trade with virtual funds against live prices."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Explicit origins list so that allow_credentials=True works correctly.
    # Browsers reject responses with `Access-Control-Allow-Origin: *` when
    # credentials (cookies / auth headers) are involved; explicit origins are
    # required in that case.  Add production domains here or via env var.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
    )

    # ── Custom middleware (registered in reverse execution order) ─────────────
    # Starlette executes middleware in LIFO order, so we add them outermost-last.
    # Desired execution order: LoggingMiddleware → AuthMiddleware → RateLimitMiddleware → route
    # Auth must run before RateLimitMiddleware so that request.state.account is
    # populated before the rate-limiter reads it.
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(AuthMiddleware)
    application.add_middleware(LoggingMiddleware)

    # ── Global exception handler ──────────────────────────────────────────────
    @application.exception_handler(TradingPlatformError)
    async def _trading_error_handler(
        request: Request,
        exc: TradingPlatformError,
    ) -> JSONResponse:
        """Serialise any ``TradingPlatformError`` subclass to the standard envelope.

        Returns:
            JSON response with ``{"error": {"code": ..., "message": ..., "details": ...}}``
            and the appropriate HTTP status code.
        """
        return JSONResponse(exc.to_dict(), status_code=exc.http_status)

    @application.exception_handler(Exception)
    async def _unhandled_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Catch-all for unexpected errors; returns a generic 500 envelope.

        Returns:
            JSON 500 response with a non-leaking error message.
        """
        logger.exception("unhandled_error", extra={"path": request.url.path, "error": str(exc)})
        return JSONResponse(
            {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
            status_code=500,
        )

    # ── REST routers ──────────────────────────────────────────────────────────
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(market_router)
    application.include_router(trading_router)
    application.include_router(account_router)
    application.include_router(agents_router)
    application.include_router(analytics_router)
    application.include_router(backtest_router)
    application.include_router(battles_router)
    application.include_router(waitlist_router)

    # ── WebSocket endpoint ────────────────────────────────────────────────────
    @application.websocket("/ws/v1")
    async def websocket_endpoint(
        websocket: WebSocket,
        api_key: str = "",
    ) -> None:
        """WebSocket gateway for real-time price feeds and order notifications.

        Authentication is performed via the ``api_key`` query parameter.  The
        connection is rejected (close code 4401) if the key is invalid or the
        account is not active.

        After a successful connection the client may send subscribe/unsubscribe
        JSON messages handled by :func:`~src.api.websocket.handlers.handle_message`.

        Args:
            websocket: The incoming WebSocket connection (injected by FastAPI).
            api_key:   API key supplied as ``?api_key=ak_live_...`` query param.

        Example client usage::

            ws = await websockets.connect("ws://localhost:8000/ws/v1?api_key=ak_live_...")
            await ws.send(json.dumps({"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"}))
        """
        manager: ConnectionManager = websocket.app.state.ws_manager
        connection_id = await manager.connect(websocket, api_key)

        if connection_id is None:
            # Authentication failed — manager already closed the socket
            return

        try:
            async for message in websocket.iter_json():
                await handle_message(connection_id, message, manager)
        except Exception:  # noqa: BLE001, S110
            # Client disconnected abruptly or sent invalid JSON
            pass
        finally:
            await manager.disconnect(connection_id)

    # ── Prometheus metrics ────────────────────────────────────────────────────
    metrics_app = make_asgi_app()
    application.mount("/metrics", metrics_app)

    return application


# ---------------------------------------------------------------------------
# Module-level app instance (used by uvicorn / gunicorn)
# ---------------------------------------------------------------------------

app = create_app()
