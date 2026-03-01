"""Seed the ``trading_pairs`` table from Binance REST exchange info.

Standalone script — run directly or via ``python -m scripts.seed_pairs``.

Fetches all symbols from the Binance ``/api/v3/exchangeInfo`` endpoint,
filters for pairs that are **TRADING** and have **USDT** as the quote asset,
extracts LOT_SIZE and MIN_NOTIONAL filter values, then upserts each pair into
the ``trading_pairs`` table (insert-or-update by symbol primary key).

Usage::

    # With default DATABASE_URL from .env:
    python scripts/seed_pairs.py

    # Override database URL:
    DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db python scripts/seed_pairs.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
QUOTE_ASSET_FILTER = "USDT"
ACTIVE_STATUS = "TRADING"

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------


def _extract_lot_size(
    filters: list[dict[str, Any]],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Return (min_qty, max_qty, step_size) from a symbol's filter list.

    Args:
        filters: The ``filters`` list from a single Binance symbol entry.

    Returns:
        A three-tuple of ``Decimal`` values, or ``None`` for each field if the
        LOT_SIZE filter is absent or a value cannot be parsed.
    """
    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            try:
                min_qty = Decimal(f["minQty"])
                max_qty = Decimal(f["maxQty"])
                step_size = Decimal(f["stepSize"])
                return min_qty, max_qty, step_size
            except (KeyError, InvalidOperation):
                logger.warning("Could not parse LOT_SIZE filter: %s", f)
                return None, None, None
    return None, None, None


def _extract_min_notional(filters: list[dict[str, Any]]) -> Decimal | None:
    """Return the min-notional value from a symbol's filter list.

    Checks both ``MIN_NOTIONAL`` (legacy) and ``NOTIONAL`` (newer) filter
    types, since Binance has used both names over time.

    Args:
        filters: The ``filters`` list from a single Binance symbol entry.

    Returns:
        The minimum notional as a ``Decimal``, or ``None`` if not found.
    """
    for filter_type in ("MIN_NOTIONAL", "NOTIONAL"):
        for f in filters:
            if f.get("filterType") == filter_type:
                raw = f.get("minNotional") or f.get("notional")
                if raw is not None:
                    try:
                        return Decimal(raw)
                    except InvalidOperation:
                        logger.warning(
                            "Could not parse %s filter value %r", filter_type, raw
                        )
    return None


# ---------------------------------------------------------------------------
# Binance fetch
# ---------------------------------------------------------------------------


async def fetch_usdt_pairs(
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Fetch and filter USDT trading pairs from Binance exchange info.

    Args:
        client: An active :class:`httpx.AsyncClient` instance.

    Returns:
        List of raw symbol dicts where status is TRADING and quoteAsset is USDT.

    Raises:
        httpx.HTTPStatusError: If the Binance API returns a non-2xx status.
        httpx.RequestError: On connection / timeout errors.
    """
    logger.info("Fetching exchange info from %s …", EXCHANGE_INFO_URL)
    response = await client.get(EXCHANGE_INFO_URL, timeout=30.0)
    response.raise_for_status()

    data = response.json()
    symbols: list[dict[str, Any]] = data.get("symbols", [])
    logger.info("Total symbols from Binance: %d", len(symbols))

    usdt_pairs = [
        s
        for s in symbols
        if s.get("status") == ACTIVE_STATUS
        and s.get("quoteAsset") == QUOTE_ASSET_FILTER
    ]
    logger.info(
        "Filtered to %d active USDT pairs (status=%s, quoteAsset=%s)",
        len(usdt_pairs),
        ACTIVE_STATUS,
        QUOTE_ASSET_FILTER,
    )
    return usdt_pairs


# ---------------------------------------------------------------------------
# Database upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = text(
    """
    INSERT INTO trading_pairs
        (symbol, base_asset, quote_asset, status, min_qty, max_qty, step_size, min_notional, updated_at)
    VALUES
        (:symbol, :base_asset, :quote_asset, :status, :min_qty, :max_qty, :step_size, :min_notional, NOW())
    ON CONFLICT (symbol) DO UPDATE SET
        base_asset    = EXCLUDED.base_asset,
        quote_asset   = EXCLUDED.quote_asset,
        status        = EXCLUDED.status,
        min_qty       = EXCLUDED.min_qty,
        max_qty       = EXCLUDED.max_qty,
        step_size     = EXCLUDED.step_size,
        min_notional  = EXCLUDED.min_notional,
        updated_at    = NOW()
    """
)


async def seed_pairs(
    session: AsyncSession,
    pairs: list[dict[str, Any]],
) -> int:
    """Upsert all pairs into the ``trading_pairs`` table.

    Each pair is inserted or updated atomically.  The entire batch is
    committed in a single transaction.

    Args:
        session: An open :class:`AsyncSession` pointing at the target database.
        pairs: Raw symbol dicts from the Binance exchange info response.

    Returns:
        The number of rows upserted.
    """
    rows: list[dict[str, Any]] = []
    for sym in pairs:
        filters: list[dict[str, Any]] = sym.get("filters", [])
        min_qty, max_qty, step_size = _extract_lot_size(filters)
        min_notional = _extract_min_notional(filters)

        rows.append(
            {
                "symbol": sym["symbol"],
                "base_asset": sym["baseAsset"],
                "quote_asset": sym["quoteAsset"],
                "status": "active",
                "min_qty": min_qty,
                "max_qty": max_qty,
                "step_size": step_size,
                "min_notional": min_notional,
            }
        )

    if not rows:
        logger.warning("No rows to upsert — exiting early.")
        return 0

    await session.execute(_UPSERT_SQL, rows)
    await session.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Main entry point: fetch pairs, seed the database, log results."""
    # Import here so the script can also run from the repo root without
    # the full FastAPI app being initialised (src.config is still used for
    # the DATABASE_URL default).
    try:
        from src.config import get_settings  # noqa: PLC0415

        settings = get_settings()
        database_url = settings.database_url
    except Exception:
        # Fallback: allow DATABASE_URL env var without pydantic-settings
        import os  # noqa: PLC0415

        database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://agentexchange:change_me_in_production@localhost:5432/agentexchange",
        )
        logger.warning(
            "Could not load src.config — falling back to DATABASE_URL env var."
        )

    logger.info("Connecting to database …")
    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    try:
        async with httpx.AsyncClient() as http_client:
            pairs = await fetch_usdt_pairs(http_client)

        if not pairs:
            logger.error("No USDT pairs returned from Binance — aborting.")
            sys.exit(1)

        async with factory() as session:
            count = await seed_pairs(session, pairs)

        logger.info("Successfully upserted %d trading pairs.", count)

    except httpx.RequestError as exc:
        logger.error("Network error fetching Binance exchange info: %s", exc)
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Binance API returned HTTP %d: %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unexpected error during seeding: %s", exc)
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
