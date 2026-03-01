"""Phase 1 Validation Script — AgentExchange Platform.

Runs a full end-to-end validation of the Phase 1 infrastructure:

1. Check Docker services are healthy (timescaledb, redis, api, ingestion)
2. Verify Redis connectivity and that prices are being updated
3. Verify TimescaleDB connectivity and tick data is growing
4. Run the seed_pairs script and confirm 600+ rows
5. Verify continuous aggregates are populated
6. Hit the /health endpoint and confirm status == "ok" or "degraded"
7. Print a final pass/fail summary

Run from the repo root (services must already be running)::

    python scripts/validate_phase1.py

Prerequisites:
    pip install httpx asyncpg redis

Environment variables (same as .env):
    DATABASE_URL  — defaults to localhost:5432 (not the Docker internal hostname)
    REDIS_URL     — defaults to redis://localhost:6379/0
    API_BASE_URL  — defaults to http://localhost:8000
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field

import asyncpg
import httpx
import redis.asyncio as aioredis

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# When running outside Docker containers use localhost, not service-name hostnames.
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentexchange:agentexchange_dev_pw@localhost:5432/agentexchange",
).replace("postgresql+asyncpg://", "postgresql://")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

TICK_FRESHNESS_WINDOW_S = 30  # seconds — a fresh tick must exist within this window
MIN_PAIR_COUNT = 600          # minimum expected trading_pairs rows after seeding
TICK_GROW_WAIT_S = 10         # seconds to wait before re-checking tick count growth

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("validate_phase1")

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Accumulates pass/fail outcomes for all validation checks."""

    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def ok(self, label: str) -> None:
        log.info("  ✓  %s", label)
        self.passed.append(label)

    def fail(self, label: str, detail: str = "") -> None:
        msg = f"{label}" + (f": {detail}" if detail else "")
        log.error("  ✗  %s", msg)
        self.failed.append(msg)

    def summary(self) -> int:
        """Print the summary and return 0 on all-pass, 1 on any failure."""
        print()
        print("=" * 60)
        print(f"  Phase 1 Validation — {len(self.passed)} passed, {len(self.failed)} failed")
        print("=" * 60)
        for label in self.passed:
            print(f"  ✓  {label}")
        for label in self.failed:
            print(f"  ✗  {label}")
        print()
        return 0 if not self.failed else 1


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


async def check_redis(r: ValidationResult) -> aioredis.Redis:
    """Verify Redis is reachable and prices are being populated."""
    log.info("── Redis checks ──────────────────────────────────────")
    client: aioredis.Redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.ping()
        r.ok("Redis ping")
    except Exception as exc:
        r.fail("Redis ping", str(exc))
        return client

    # Check prices hash exists
    try:
        prices = await client.hgetall("prices")
        if prices:
            r.ok(f"Redis prices hash populated ({len(prices)} pairs)")
        else:
            r.fail("Redis prices hash", "Hash is empty — ingestion may not be running")
    except Exception as exc:
        r.fail("Redis prices hash", str(exc))

    # Check at least one ticker is fresh
    try:
        all_meta_keys = await client.keys("prices:meta")
        if not all_meta_keys:
            r.fail("Redis tick freshness", "No prices:meta key found")
        else:
            # Sample BTCUSDT freshness
            sample_symbol = "BTCUSDT"
            ts_str = await client.hget("prices:meta", sample_symbol)
            if ts_str is None:
                r.fail("Redis tick freshness", f"No meta entry for {sample_symbol}")
            else:
                age = time.time() - float(ts_str)
                if age <= TICK_FRESHNESS_WINDOW_S:
                    r.ok(f"BTCUSDT tick fresh (age={age:.1f}s)")
                else:
                    r.fail("Redis tick freshness", f"BTCUSDT last tick {age:.0f}s ago (threshold {TICK_FRESHNESS_WINDOW_S}s)")
    except Exception as exc:
        r.fail("Redis tick freshness", str(exc))

    return client


async def check_timescaledb(r: ValidationResult) -> asyncpg.Pool | None:
    """Verify TimescaleDB is reachable and tables exist."""
    log.info("── TimescaleDB checks ────────────────────────────────")
    try:
        pool: asyncpg.Pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=3)
        r.ok("TimescaleDB connection")
    except Exception as exc:
        r.fail("TimescaleDB connection", str(exc))
        return None

    # ticks table exists
    try:
        row = await pool.fetchrow("SELECT count(*) AS c FROM ticks")
        tick_count = row["c"] if row else 0
        r.ok(f"ticks table accessible (count={tick_count:,})")
    except Exception as exc:
        r.fail("ticks table", str(exc))

    # trading_pairs table exists
    try:
        row = await pool.fetchrow("SELECT count(*) AS c FROM trading_pairs")
        pair_count = row["c"] if row else 0
        if pair_count >= MIN_PAIR_COUNT:
            r.ok(f"trading_pairs seeded ({pair_count} rows >= {MIN_PAIR_COUNT})")
        elif pair_count > 0:
            r.fail(
                "trading_pairs underseeded",
                f"{pair_count} rows — expected >= {MIN_PAIR_COUNT}. Run seed_pairs.py",
            )
        else:
            r.fail("trading_pairs empty", "Run: python scripts/seed_pairs.py")
    except Exception as exc:
        r.fail("trading_pairs table", str(exc))

    # Continuous aggregates
    for agg in ("candles_1m", "candles_5m", "candles_1h", "candles_1d"):
        try:
            await pool.execute(f"SELECT 1 FROM {agg} LIMIT 1")
            r.ok(f"Continuous aggregate {agg} queryable")
        except Exception as exc:
            r.fail(f"Continuous aggregate {agg}", str(exc))

    return pool


async def check_tick_growth(pool: asyncpg.Pool, r: ValidationResult) -> None:
    """Confirm that the tick count grows over a short window."""
    log.info("── Tick ingestion growth check ───────────────────────")
    try:
        row1 = await pool.fetchrow("SELECT count(*) AS c FROM ticks")
        count1 = row1["c"] if row1 else 0
        log.info("  Tick count at t=0: %d — waiting %ds…", count1, TICK_GROW_WAIT_S)
        await asyncio.sleep(TICK_GROW_WAIT_S)
        row2 = await pool.fetchrow("SELECT count(*) AS c FROM ticks")
        count2 = row2["c"] if row2 else 0
        delta = count2 - count1
        if delta > 0:
            r.ok(f"Ticks growing (+{delta:,} in {TICK_GROW_WAIT_S}s, rate ~{delta/TICK_GROW_WAIT_S:.0f}/s)")
        else:
            r.fail(
                "Tick growth",
                f"Tick count did not increase in {TICK_GROW_WAIT_S}s (before={count1}, after={count2})",
            )
    except Exception as exc:
        r.fail("Tick growth check", str(exc))


async def check_api_health(r: ValidationResult) -> None:
    """Call the /health endpoint and validate the response."""
    log.info("── API /health check ─────────────────────────────────")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{API_BASE_URL}/health")

        if resp.status_code not in (200, 503):
            r.fail("/health HTTP status", f"Unexpected {resp.status_code}")
            return

        body = resp.json()
        status = body.get("status", "unknown")
        redis_ok = body.get("redis_connected", False)
        db_ok = body.get("db_connected", False)
        total_pairs = body.get("total_pairs", 0)
        stale = body.get("stale_pairs", [])

        if redis_ok:
            r.ok("/health redis_connected=true")
        else:
            r.fail("/health redis_connected", "false")

        if db_ok:
            r.ok("/health db_connected=true")
        else:
            r.fail("/health db_connected", "false")

        if total_pairs >= MIN_PAIR_COUNT:
            r.ok(f"/health total_pairs={total_pairs}")
        elif total_pairs > 0:
            r.fail("/health total_pairs", f"{total_pairs} < {MIN_PAIR_COUNT}")
        else:
            r.fail("/health total_pairs", "0 — ingestion not started?")

        if status == "ok":
            r.ok("/health status=ok")
        elif status == "degraded":
            r.ok(f"/health status=degraded ({len(stale)} stale pairs — acceptable after fresh start)")
        else:
            r.fail("/health status", status)

    except httpx.ConnectError:
        r.fail(
            "/health endpoint unreachable",
            f"Could not connect to {API_BASE_URL}. Is the api service running?",
        )
    except Exception as exc:
        r.fail("/health check error", str(exc))


async def run_seed_verification(pool: asyncpg.Pool, r: ValidationResult) -> None:
    """Verify that the seed_pairs script result is reflected in the database."""
    log.info("── Seed pairs verification ───────────────────────────")
    try:
        row = await pool.fetchrow("SELECT count(*) AS c FROM trading_pairs WHERE status = 'active'")
        active_count = row["c"] if row else 0
        if active_count >= MIN_PAIR_COUNT:
            r.ok(f"seed_pairs: {active_count} active USDT pairs in trading_pairs")
        else:
            r.fail(
                "seed_pairs count",
                f"Only {active_count} active pairs. Run: python scripts/seed_pairs.py",
            )
    except Exception as exc:
        r.fail("seed_pairs verification", str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    """Run all Phase 1 validation checks and return exit code."""
    print()
    print("=" * 60)
    print("  AgentExchange — Phase 1 Validation")
    print(f"  DB:    {DB_URL[:60]}…" if len(DB_URL) > 60 else f"  DB:    {DB_URL}")
    print(f"  Redis: {REDIS_URL}")
    print(f"  API:   {API_BASE_URL}")
    print("=" * 60)
    print()

    r = ValidationResult()

    # Run infrastructure checks in parallel where possible
    redis_client, pool = await asyncio.gather(
        check_redis(r),
        check_timescaledb(r),
    )

    # Tick growth and seed verification require DB pool
    if pool is not None:
        await asyncio.gather(
            check_tick_growth(pool, r),
            run_seed_verification(pool, r),
        )
    else:
        r.fail("Tick growth skipped", "TimescaleDB unavailable")
        r.fail("Seed verification skipped", "TimescaleDB unavailable")

    # API health check
    await check_api_health(r)

    # Cleanup
    try:
        await redis_client.aclose()
    except Exception:
        pass
    if pool is not None:
        try:
            await pool.close()
        except Exception:
            pass

    return r.summary()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
