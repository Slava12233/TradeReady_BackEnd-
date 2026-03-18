"""Backfill historical candles from any exchange into candles_backfill.

Fetches OHLCV klines via CCXT (110+ exchanges) or the Binance public API
and batch-inserts them into the ``candles_backfill`` TimescaleDB hypertable
so that backtests can cover years of historical data.

Usage::

    python scripts/backfill_history.py --all                       # Daily + hourly (Binance)
    python scripts/backfill_history.py --daily                     # All pairs, 1d, from 2017-01-01
    python scripts/backfill_history.py --hourly                    # Top 100 pairs, 1h, 5 years
    python scripts/backfill_history.py --symbols BTCUSDT,ETHUSDT --interval 1d --start 2017-01-01
    python scripts/backfill_history.py --daily --dry-run           # Preview only
    python scripts/backfill_history.py --daily --resume            # Skip already-fetched ranges
    python scripts/backfill_history.py --exchange okx --daily      # Backfill from OKX via CCXT
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import logging
import sys
import time

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
MAX_CANDLES_PER_REQUEST = 1000
BATCH_INSERT_SIZE = 5000
DEFAULT_DAILY_START = datetime(2017, 1, 1, tzinfo=UTC)
DEFAULT_HOURLY_LOOKBACK_YEARS = 5
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0

_UPSERT_SQL = text("""
    INSERT INTO candles_backfill (bucket, symbol, interval, open, high, low, close, volume, trade_count)
    VALUES (:bucket, :symbol, :interval, :open, :high, :low, :close, :volume, :trade_count)
    ON CONFLICT (symbol, interval, bucket) DO NOTHING
""")


# ---------------------------------------------------------------------------
# Binance API helpers
# ---------------------------------------------------------------------------


async def _fetch_klines_page(
    client: httpx.AsyncClient,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
) -> list[list]:
    """Fetch one page of klines with retries and backoff."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": MAX_CANDLES_PER_REQUEST,
    }

    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(BINANCE_KLINES_URL, params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", backoff))
                logger.warning("Rate limited, sleeping %ds", retry_after)
                await asyncio.sleep(retry_after)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            if attempt < MAX_RETRIES - 1:
                logger.warning(
                    "Retry %d/%d for %s %s: %s",
                    attempt + 1, MAX_RETRIES, symbol, interval, exc,
                )
                await asyncio.sleep(backoff)
                backoff *= 2
            else:
                raise
    return []


async def _fetch_top_volume_symbols(client: httpx.AsyncClient, limit: int = 100) -> list[str]:
    """Fetch top USDT pairs by 24h quote volume from Binance."""
    resp = await client.get(BINANCE_TICKER_URL, timeout=30.0)
    resp.raise_for_status()
    tickers = resp.json()

    usdt_tickers = [t for t in tickers if t["symbol"].endswith("USDT")]
    usdt_tickers.sort(key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)
    return [t["symbol"] for t in usdt_tickers[:limit]]


async def _get_our_trading_pairs(session_factory: async_sessionmaker) -> set[str]:
    """Fetch symbols from our trading_pairs table."""
    async with session_factory() as session:
        result = await session.execute(text("SELECT symbol FROM trading_pairs"))
        return {row[0] for row in result.fetchall()}


# ---------------------------------------------------------------------------
# Core backfill logic
# ---------------------------------------------------------------------------


async def _backfill_symbol(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker,
    symbol: str,
    interval: str,
    start_dt: datetime,
    end_dt: datetime,
    resume: bool,
    dry_run: bool,
    semaphore: asyncio.Semaphore,
    progress: dict,
    exchange_id: str = "binance",
    ccxt_adapter: object | None = None,
) -> int:
    """Backfill one symbol. Returns number of candles inserted."""
    async with semaphore:
        actual_start = start_dt

        if resume:
            async with session_factory() as session:
                result = await session.execute(
                    text(
                        "SELECT MAX(bucket) FROM candles_backfill "
                        "WHERE symbol = :s AND interval = :i"
                    ),
                    {"s": symbol, "i": interval},
                )
                row = result.fetchone()
                if row and row[0] is not None:
                    actual_start = row[0] + timedelta(milliseconds=1)
                    if actual_start >= end_dt:
                        logger.info("[%s] %s %s: already complete", progress["label"], symbol, interval)
                        return 0

        start_ms = int(actual_start.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        total_candles = 0
        batch: list[dict] = []
        page = 0

        while start_ms < end_ms:
            page += 1
            try:
                if ccxt_adapter is not None:
                    klines = await _fetch_klines_page_ccxt(
                        ccxt_adapter, symbol, interval, start_ms, end_ms,
                    )
                else:
                    klines = await _fetch_klines_page(client, symbol, interval, start_ms, end_ms)
            except Exception as exc:
                logger.error("Failed to fetch %s %s page %d: %s", symbol, interval, page, exc)
                break

            if not klines:
                break

            for k in klines:
                batch.append({
                    "bucket": datetime.fromtimestamp(k[0] / 1000, tz=UTC),
                    "symbol": symbol,
                    "interval": interval,
                    "open": Decimal(str(k[1])),
                    "high": Decimal(str(k[2])),
                    "low": Decimal(str(k[3])),
                    "close": Decimal(str(k[4])),
                    "volume": Decimal(str(k[5])),
                    "trade_count": int(k[8]),
                })

            if not dry_run and len(batch) >= BATCH_INSERT_SIZE:
                async with session_factory() as session:
                    await session.execute(_UPSERT_SQL, batch)
                    await session.commit()
                total_candles += len(batch)
                batch.clear()

            # Advance past the last candle
            last_open_ms = klines[-1][0]
            start_ms = last_open_ms + 1

            # Progress
            progress["done"] += 1
            elapsed = time.monotonic() - progress["wall_start"]
            elapsed_str = _fmt_duration(elapsed)
            logger.info(
                "[%d/%d] %s %s: %d candles (page %d) | Elapsed: %s",
                progress["done"], progress["total"], symbol, interval,
                total_candles + len(batch), page, elapsed_str,
            )

            # Rate limit
            await asyncio.sleep(0.1)

            if len(klines) < MAX_CANDLES_PER_REQUEST:
                break

        # Flush remaining batch
        if batch and not dry_run:
            async with session_factory() as session:
                await session.execute(_UPSERT_SQL, batch)
                await session.commit()
            total_candles += len(batch)

        if dry_run:
            total_candles = len(batch) + total_candles

        return total_candles


def _fmt_duration(seconds: float) -> str:
    """Format seconds as Xm or Xs."""
    if seconds >= 60:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds)}s"


# ---------------------------------------------------------------------------
# Job orchestration
# ---------------------------------------------------------------------------


async def run_backfill(
    symbols: list[str],
    interval: str,
    start_dt: datetime,
    end_dt: datetime,
    resume: bool,
    dry_run: bool,
    session_factory: async_sessionmaker,
    exchange_id: str = "binance",
) -> tuple[int, int, int]:
    """Run backfill for a list of symbols. Returns (ok, failed, total_candles)."""
    semaphore = asyncio.Semaphore(3)
    progress = {
        "done": 0,
        "total": len(symbols),
        "wall_start": time.monotonic(),
        "label": f"{exchange_id}:{interval}",
    }

    ok = 0
    failed = 0
    total_candles = 0

    # For non-Binance exchanges, use CCXT.  For Binance, use the direct API
    # (proven, faster, handles rate limits better).
    use_ccxt = exchange_id != "binance"
    ccxt_adapter = None

    if use_ccxt:
        ccxt_adapter = await _create_ccxt_adapter(exchange_id)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            tasks = []
            for sym in symbols:
                tasks.append(
                    _backfill_symbol(
                        client, session_factory, sym, interval,
                        start_dt, end_dt, resume, dry_run, semaphore, progress,
                        exchange_id=exchange_id,
                        ccxt_adapter=ccxt_adapter,
                    )
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    logger.error("Symbol %s failed: %s", symbols[i], res)
                    failed += 1
                else:
                    ok += 1
                    total_candles += res
    finally:
        if ccxt_adapter is not None:
            await ccxt_adapter.close()  # type: ignore[union-attr]

    return ok, failed, total_candles


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill historical candles into candles_backfill (Binance or any CCXT exchange).",
    )
    parser.add_argument("--all", action="store_true", help="Run both --daily and --hourly jobs")
    parser.add_argument("--daily", action="store_true", help="All pairs, 1d, from 2017-01-01")
    parser.add_argument("--hourly", action="store_true", help="Top 100 pairs, 1h, 5 years")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols (e.g. BTCUSDT,ETHUSDT)")
    parser.add_argument("--interval", type=str, default="1d", help="Candle interval (1m, 5m, 1h, 1d)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--resume", action="store_true", help="Skip already-fetched ranges")
    parser.add_argument(
        "--exchange", type=str, default="binance",
        help="Exchange ID for CCXT (e.g. binance, okx, bybit). Default: binance",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# CCXT-based kline fetching (for non-Binance exchanges)
# ---------------------------------------------------------------------------


async def _fetch_klines_page_ccxt(
    adapter: object,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
) -> list[list]:
    """Fetch one page of klines via CCXT adapter.

    Returns data in the same format as the Binance API for compatibility
    with the existing _backfill_symbol logic.
    """
    since_dt = datetime.fromtimestamp(start_ms / 1000, tz=UTC)
    candles = await adapter.fetch_ohlcv(  # type: ignore[union-attr]
        symbol, timeframe=interval, since=since_dt, limit=MAX_CANDLES_PER_REQUEST,
    )
    # Convert ExchangeCandle objects to Binance-compatible list format:
    # [open_time_ms, open, high, low, close, volume, ?, ?, trade_count, ...]
    result = []
    for c in candles:
        open_ms = int(c.timestamp.timestamp() * 1000)
        if open_ms > end_ms:
            break
        result.append([
            open_ms,             # [0] open time ms
            str(c.open),         # [1] open
            str(c.high),         # [2] high
            str(c.low),          # [3] low
            str(c.close),        # [4] close
            str(c.volume),       # [5] volume
            0,                   # [6] close time (unused)
            "0",                 # [7] quote volume (unused)
            c.trade_count,       # [8] trade count
        ])
    return result


async def _fetch_ccxt_symbols(exchange_id: str, quote_asset: str = "USDT") -> list[str]:
    """Fetch all active trading pair symbols from an exchange via CCXT."""
    from src.exchange.ccxt_adapter import CCXTAdapter  # noqa: PLC0415

    adapter = CCXTAdapter(exchange_id)
    await adapter.initialize()
    try:
        markets = await adapter.fetch_markets(quote_asset)
        return sorted(m.symbol for m in markets)
    finally:
        await adapter.close()


async def _create_ccxt_adapter(exchange_id: str) -> object:
    """Create and initialize a CCXT adapter for kline fetching."""
    from src.exchange.ccxt_adapter import CCXTAdapter  # noqa: PLC0415

    adapter = CCXTAdapter(exchange_id)
    await adapter.initialize()
    return adapter


async def main() -> None:
    """Entry point."""
    args = _parse_args()

    # Validate args
    if not (args.all or args.daily or args.hourly or args.symbols):
        logger.error("Specify --all, --daily, --hourly, or --symbols")
        sys.exit(1)

    # DB setup
    try:
        from src.config import get_settings  # noqa: PLC0415
        settings = get_settings()
        database_url = settings.database_url
    except Exception:
        import os  # noqa: PLC0415
        database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://agentexchange:change_me_in_production@localhost:5432/agentexchange",
        )
        logger.warning("Could not load src.config — falling back to DATABASE_URL env var.")

    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    wall_start = time.monotonic()

    try:
        now = datetime.now(tz=UTC)
        total_ok = 0
        total_failed = 0
        total_candles = 0

        exchange_id = args.exchange.lower()
        logger.info("Exchange: %s", exchange_id)

        if args.symbols:
            # Custom symbol mode
            symbols = [s.strip().upper() for s in args.symbols.split(",")]
            start_dt = (
                datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
                if args.start else DEFAULT_DAILY_START
            )
            ok, failed, candles = await run_backfill(
                symbols, args.interval, start_dt, now,
                args.resume, args.dry_run, factory,
                exchange_id=exchange_id,
            )
            total_ok += ok
            total_failed += failed
            total_candles += candles

        else:
            # Preset jobs
            if args.all or args.daily:
                # For non-Binance exchanges, fetch symbols via CCXT.
                if exchange_id != "binance":
                    symbols = await _fetch_ccxt_symbols(exchange_id)
                    if not symbols:
                        logger.error("No USDT pairs found on %s via CCXT.", exchange_id)
                        sys.exit(1)
                else:
                    our_pairs = await _get_our_trading_pairs(factory)
                    if not our_pairs:
                        logger.error("No trading pairs in DB. Run seed_pairs.py first.")
                        sys.exit(1)
                    symbols = sorted(our_pairs)

                logger.info("Daily backfill: %d symbols from %s (%s)", len(symbols), DEFAULT_DAILY_START.date(), exchange_id)

                ok, failed, candles = await run_backfill(
                    symbols, "1d", DEFAULT_DAILY_START, now,
                    args.resume, args.dry_run, factory,
                    exchange_id=exchange_id,
                )
                total_ok += ok
                total_failed += failed
                total_candles += candles

            if args.all or args.hourly:
                if exchange_id != "binance":
                    # For non-Binance, use the same CCXT symbols (no volume sorting yet).
                    symbols = await _fetch_ccxt_symbols(exchange_id)
                    symbols = symbols[:100]  # Top 100 by alphabetical (volume sort TBD)
                else:
                    our_pairs = await _get_our_trading_pairs(factory)
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        top_symbols = await _fetch_top_volume_symbols(client, limit=100)
                    symbols = [s for s in top_symbols if s in our_pairs]

                hourly_start = now - timedelta(days=365 * DEFAULT_HOURLY_LOOKBACK_YEARS)
                logger.info("Hourly backfill: %d symbols from %s (%s)", len(symbols), hourly_start.date(), exchange_id)

                ok, failed, candles = await run_backfill(
                    symbols, "1h", hourly_start, now,
                    args.resume, args.dry_run, factory,
                    exchange_id=exchange_id,
                )
                total_ok += ok
                total_failed += failed
                total_candles += candles

        elapsed = time.monotonic() - wall_start
        action = "previewed" if args.dry_run else "inserted"
        logger.info(
            "Summary: %d symbols OK, %d failed | %s candles %s | %s elapsed",
            total_ok, total_failed, f"{total_candles:,}", action, _fmt_duration(elapsed),
        )

        if total_failed > 0:
            sys.exit(1)

    except Exception as exc:
        logger.exception("Backfill failed: %s", exc)
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
