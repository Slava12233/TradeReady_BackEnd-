"""Price Ingestion Service — main entry point.

Run as a standalone process::

    python -m src.price_ingestion.service

Supports two modes controlled by the ``EXCHANGE_ID`` environment variable:

- **Legacy mode** (``EXCHANGE_ID=binance`` or unset): Uses the battle-tested
  ``BinanceWebSocketClient`` for direct Binance WebSocket streaming.
- **CCXT mode** (any value, e.g. ``EXCHANGE_ID=okx``): Uses the new
  ``ExchangeWebSocketClient`` powered by CCXT for exchange-agnostic streaming.

Both modes produce identical ``Tick`` namedtuples, so the downstream pipeline
(``PriceCache``, ``TickBuffer``, ``PriceBroadcaster``) is unchanged.

Responsibilities:
1. Connect to the configured exchange's WebSocket stream for all active USDT pairs.
2. For every incoming tick:
   a. Update Redis ``prices`` hash with the latest price (overwrite).
   b. Update Redis ``ticker:{symbol}`` with rolling 24-h stats.
   c. Add the tick to the in-memory :class:`~src.price_ingestion.tick_buffer.TickBuffer`.
3. Flush the buffer to TimescaleDB every 1 second (or when it hits 5 000 ticks);
   broadcast the same batch to Redis pub/sub subscribers.
4. Handle SIGINT / SIGTERM gracefully: finish the final buffer flush before exit.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
import logging
import signal
import sys

import structlog

from src.cache.price_cache import PriceCache
from src.cache.redis_client import RedisClient
from src.cache.types import Tick
from src.config import get_settings
from src.database.session import close_db, get_asyncpg_pool, init_db
from src.price_ingestion.broadcaster import PriceBroadcaster
from src.price_ingestion.tick_buffer import TickBuffer

# Module-level logger — structlog.configure() is called in main() so that
# importing this module in tests does not mutate the global structlog singleton.
log = structlog.get_logger(__name__)

# Module-level flag set by the signal handler to request a graceful shutdown.
_shutdown_requested: bool = False

# When set to True, forces the legacy BinanceWebSocketClient even if CCXT is
# available.  Useful as a safety fallback during the transition period.
_FORCE_LEGACY_BINANCE: bool = False


def _request_shutdown(signum: int, _frame: object) -> None:
    """Signal handler that requests graceful shutdown."""
    global _shutdown_requested  # noqa: PLW0603
    signal_name = signal.Signals(signum).name
    log.info("Shutdown signal received", signal=signal_name)
    _shutdown_requested = True


async def _create_tick_source(settings: object) -> tuple[AsyncGenerator[Tick, None], list[str], object]:
    """Create the appropriate tick source based on configuration.

    Returns:
        Tuple of (tick_generator, pair_list, client_object_for_cleanup).
    """
    exchange_id = getattr(settings, "exchange_id", "binance")

    # ── Force-legacy path: always use the battle-tested BinanceWebSocketClient ──
    if _FORCE_LEGACY_BINANCE:
        from src.price_ingestion.binance_ws import BinanceWebSocketClient  # noqa: PLC0415

        ws_client = BinanceWebSocketClient(
            ws_base_url=getattr(settings, "binance_ws_url", "wss://stream.binance.com:9443/stream"),
        )
        await ws_client.fetch_pairs()
        pairs = ws_client.get_all_pairs()
        log.info("Using legacy Binance WebSocket client (forced)", pairs=len(pairs))
        return ws_client.listen(), pairs, ws_client

    # ── Binance: try CCXT first, fall back to legacy if CCXT unavailable ──
    if exchange_id == "binance":
        try:
            from src.price_ingestion.exchange_ws import ExchangeWebSocketClient  # noqa: PLC0415

            client = ExchangeWebSocketClient(exchange_id)
            await client.initialize()
            pairs = client.get_all_pairs()
            log.info("Using CCXT-based exchange client", exchange=exchange_id, pairs=len(pairs))
            return client.listen(), pairs, client
        except ImportError:
            log.info("CCXT not available — falling back to legacy Binance client")
        except Exception as exc:  # noqa: BLE001 — fall back to legacy Binance; logged below
            log.warning(
                "CCXT client initialization failed — falling back to legacy Binance client",
                error=str(exc),
            )

        from src.price_ingestion.binance_ws import BinanceWebSocketClient  # noqa: PLC0415

        ws_client = BinanceWebSocketClient(
            ws_base_url=getattr(settings, "binance_ws_url", "wss://stream.binance.com:9443/stream"),
        )
        await ws_client.fetch_pairs()
        pairs = ws_client.get_all_pairs()
        log.info("Using legacy Binance WebSocket client", pairs=len(pairs))
        return ws_client.listen(), pairs, ws_client

    # ── Non-Binance exchange: must use CCXT ──
    from src.price_ingestion.exchange_ws import ExchangeWebSocketClient  # noqa: PLC0415

    try:
        client = ExchangeWebSocketClient(exchange_id)
        await client.initialize()
    except Exception as exc:
        log.error("CCXT client init failed for exchange", exchange=exchange_id, error=str(exc))
        raise

    pairs = client.get_all_pairs()
    log.info("Using CCXT-based exchange client", exchange=exchange_id, pairs=len(pairs))
    return client.listen(), pairs, client


async def run() -> None:
    """Main ingestion loop.

    Initialises all dependencies, starts the periodic flush background task,
    then consumes ticks from the configured exchange until a shutdown is requested.
    """
    settings = get_settings()

    log.info(
        "Price ingestion service starting",
        exchange=settings.exchange_id,
        flush_interval=settings.tick_flush_interval,
        buffer_max_size=settings.tick_buffer_max_size,
    )

    # ── Initialise infrastructure ──────────────────────────────────────────
    await init_db()
    db_pool = await get_asyncpg_pool()

    redis_client = RedisClient(settings.redis_url)
    await redis_client.connect()
    redis = redis_client.get_client()

    price_cache = PriceCache(redis)
    broadcaster = PriceBroadcaster(redis)

    # Pass broadcaster into TickBuffer so broadcast_batch() is called inside
    # _write_batch() — one pipeline round-trip per flush instead of one PUBLISH
    # per tick.
    buffer = TickBuffer(
        db_pool=db_pool,
        flush_interval=settings.tick_flush_interval,
        max_size=settings.tick_buffer_max_size,
        broadcaster=broadcaster,
    )

    # ── Create tick source (CCXT or legacy Binance) ────────────────────────
    tick_source, pairs, ws_client = await _create_tick_source(settings)
    log.info("Streaming pairs loaded", count=len(pairs))

    # ── Start background flush task ────────────────────────────────────────
    flush_task = asyncio.create_task(
        buffer.start_periodic_flush(),
        name="tick-buffer-flush",
    )

    # ── Main tick loop ─────────────────────────────────────────────────────
    tick_count: int = 0
    _fatal_exc: BaseException | None = None
    try:
        async for tick in tick_source:
            if _shutdown_requested:
                break

            # a. Update current price in Redis
            await price_cache.set_price(tick.symbol, tick.price, tick.timestamp)

            # Record price ingestion lag (staleness of the tick relative to now).
            from src.monitoring.metrics import platform_price_ingestion_lag  # noqa: PLC0415

            staleness = (datetime.now(tz=UTC) - tick.timestamp).total_seconds()
            platform_price_ingestion_lag.set(staleness)

            # b. Update rolling 24-h ticker stats
            await price_cache.update_ticker(tick)

            # c. Buffer for bulk DB insert + batched pub/sub broadcast.
            #    Broadcasting is handled inside TickBuffer._write_batch() via
            #    broadcast_batch() so that all PUBLISH calls for a flush are
            #    sent in a single Redis pipeline round-trip.
            await buffer.add(tick)

            tick_count += 1
            if tick_count % 10_000 == 0:
                log.info("Ingestion heartbeat", ticks_processed=tick_count)

    except asyncio.CancelledError:
        log.info("Ingestion loop cancelled")
    except Exception as exc:
        log.error("Fatal error in ingestion loop", error=str(exc), exc_info=True)
        _fatal_exc = exc
    finally:
        # Graceful shutdown always runs, regardless of how the loop exited.
        # This ensures Redis and DB connections are never leaked on fatal errors.
        log.info("Shutting down ingestion service…", ticks_processed=tick_count)

        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass

        await buffer.shutdown()

        # Close the exchange client if it has a close method.
        if hasattr(ws_client, "close"):
            await ws_client.close()

        await redis_client.disconnect()
        await close_db()

        log.info("Price ingestion service stopped cleanly")

    if _fatal_exc is not None:
        raise _fatal_exc


def main() -> None:
    """CLI entry point: register signal handlers and run the async loop."""
    # Configure structlog here — inside main() rather than at module level —
    # so that importing service.py in tests does not mutate the global
    # structlog singleton and break log assertions.
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )

    # Register POSIX signal handlers for graceful shutdown.
    # On Windows SIGTERM may not be available; guard accordingly.
    signal.signal(signal.SIGINT, _request_shutdown)
    try:
        signal.signal(signal.SIGTERM, _request_shutdown)
    except (OSError, ValueError):
        pass  # SIGTERM not available on this platform (e.g. Windows)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
