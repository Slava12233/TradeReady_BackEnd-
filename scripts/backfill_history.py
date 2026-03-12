"""Backfill historical candles from Binance public API into candles_backfill.

Fetches OHLCV klines from ``GET /api/v3/klines`` (no API key needed) and
batch-inserts them into the ``candles_backfill`` TimescaleDB hypertable so
that backtests can cover years of historical data.

Usage::

    python scripts/backfill_history.py --all                       # Daily + hourly
    python scripts/backfill_history.py --daily                     # All pairs, 1d, from 2017-01-01
    python scripts/backfill_history.py --hourly                    # Top 100 pairs, 1h, 5 years
    python scripts/backfill_history.py --symbols BTCUSDT,ETHUSDT --interval 1d --start 2017-01-01
    python scripts/backfill_history.py --daily --dry-run           # Preview only
    python scripts/backfill_history.py --daily --resume            # Skip already-fetched ranges
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
) -> tuple[int, int, int]:
    """Run backfill for a list of symbols. Returns (ok, failed, total_candles)."""
    semaphore = asyncio.Semaphore(3)
    progress = {
        "done": 0,
        "total": len(symbols),
        "wall_start": time.monotonic(),
        "label": f"{interval}",
    }

    ok = 0
    failed = 0
    total_candles = 0

    async with httpx.AsyncClient(timeout=15.0) as client:
        tasks = []
        for sym in symbols:
            tasks.append(
                _backfill_symbol(
                    client, session_factory, sym, interval,
                    start_dt, end_dt, resume, dry_run, semaphore, progress,
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

    return ok, failed, total_candles


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill historical candles from Binance into candles_backfill.",
    )
    parser.add_argument("--all", action="store_true", help="Run both --daily and --hourly jobs")
    parser.add_argument("--daily", action="store_true", help="All pairs, 1d, from 2017-01-01")
    parser.add_argument("--hourly", action="store_true", help="Top 100 pairs, 1h, 5 years")
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols (e.g. BTCUSDT,ETHUSDT)")
    parser.add_argument("--interval", type=str, default="1d", help="Candle interval (1m, 5m, 1h, 1d)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    parser.add_argument("--resume", action="store_true", help="Skip already-fetched ranges")
    return parser.parse_args()


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
            )
            total_ok += ok
            total_failed += failed
            total_candles += candles

        else:
            # Preset jobs
            if args.all or args.daily:
                # Fetch all our trading pairs
                our_pairs = await _get_our_trading_pairs(factory)
                if not our_pairs:
                    logger.error("No trading pairs in DB. Run seed_pairs.py first.")
                    sys.exit(1)
                symbols = sorted(our_pairs)
                logger.info("Daily backfill: %d symbols from %s", len(symbols), DEFAULT_DAILY_START.date())

                ok, failed, candles = await run_backfill(
                    symbols, "1d", DEFAULT_DAILY_START, now,
                    args.resume, args.dry_run, factory,
                )
                total_ok += ok
                total_failed += failed
                total_candles += candles

            if args.all or args.hourly:
                our_pairs = await _get_our_trading_pairs(factory)
                async with httpx.AsyncClient(timeout=30.0) as client:
                    top_symbols = await _fetch_top_volume_symbols(client, limit=100)

                # Intersect with our pairs
                symbols = [s for s in top_symbols if s in our_pairs]
                hourly_start = now - timedelta(days=365 * DEFAULT_HOURLY_LOOKBACK_YEARS)
                logger.info("Hourly backfill: %d symbols from %s", len(symbols), hourly_start.date())

                ok, failed, candles = await run_backfill(
                    symbols, "1h", hourly_start, now,
                    args.resume, args.dry_run, factory,
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
