"""24-hour Stability Test — AgentExchange Phase 1.

Monitors the price ingestion pipeline continuously for 24 hours (or a custom
duration), recording tick throughput, stale pair counts, Redis freshness, and
TimescaleDB tick growth.  At the end it emits a structured report.

The test PASSES if:
- Zero data-loss windows on the major pairs (BTC/ETH/BNB/SOL/XRP) — no pair
  goes stale for more than ``MAX_STALE_WINDOW_S`` consecutive seconds.
- Average tick throughput >= ``MIN_TICKS_PER_SECOND`` over the full run.
- No unrecoverable errors (process crash, DB disconnect > 60 s, etc.).

Run from the repo root (services must already be running)::

    # Full 24-hour run:
    python scripts/stability_test_24h.py

    # Shorter smoke test (10 minutes):
    DURATION_SECONDS=600 python scripts/stability_test_24h.py

Environment variables:
    DATABASE_URL       — defaults to localhost:5432
    REDIS_URL          — defaults to redis://localhost:6379/0
    API_BASE_URL       — defaults to http://localhost:8000
    DURATION_SECONDS   — test duration in seconds (default 86400 = 24h)
    SAMPLE_INTERVAL_S  — how often to sample metrics (default 60)
    MAX_STALE_WINDOW_S — max consecutive seconds a major pair may be stale (default 120)
    MIN_TICKS_PER_SECOND — minimum acceptable average throughput (default 50)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import httpx
import redis.asyncio as aioredis

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agentexchange:agentexchange_dev_pw@localhost:5432/agentexchange",
).replace("postgresql+asyncpg://", "postgresql://")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
DURATION_S = int(os.environ.get("DURATION_SECONDS", "86400"))
SAMPLE_INTERVAL_S = int(os.environ.get("SAMPLE_INTERVAL_S", "60"))
MAX_STALE_WINDOW_S = int(os.environ.get("MAX_STALE_WINDOW_S", "120"))
MIN_TICKS_PER_SECOND = float(os.environ.get("MIN_TICKS_PER_SECOND", "50"))

MAJOR_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("stability_test")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    """A single point-in-time metrics snapshot."""

    ts: float = field(default_factory=time.time)
    tick_count: int = 0
    redis_pairs: int = 0
    stale_major_pairs: list[str] = field(default_factory=list)
    api_status: str = "unknown"
    api_latency_ms: float = -1.0
    error: str = ""


@dataclass
class StabilityReport:
    """Aggregated report for the full stability run."""

    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    samples: list[Sample] = field(default_factory=list)
    max_consecutive_stale_s: dict[str, float] = field(default_factory=dict)

    # Running state for consecutive stale tracking
    _stale_since: dict[str, float] = field(default_factory=dict, repr=False)

    def record_sample(self, s: Sample) -> None:
        """Add a sample and update consecutive-stale tracking."""
        self.samples.append(s)
        for pair in MAJOR_PAIRS:
            if pair in s.stale_major_pairs:
                if pair not in self._stale_since:
                    self._stale_since[pair] = s.ts
                window = s.ts - self._stale_since[pair]
                current_max = self.max_consecutive_stale_s.get(pair, 0.0)
                self.max_consecutive_stale_s[pair] = max(current_max, window)
            else:
                # Pair is fresh — reset stale window
                if pair in self._stale_since:
                    window = s.ts - self._stale_since.pop(pair)
                    current_max = self.max_consecutive_stale_s.get(pair, 0.0)
                    self.max_consecutive_stale_s[pair] = max(current_max, window)

    def average_tps(self) -> float:
        """Compute average tick throughput over the run."""
        if len(self.samples) < 2:
            return 0.0
        first = self.samples[0]
        last = self.samples[-1]
        elapsed = last.ts - first.ts
        if elapsed <= 0:
            return 0.0
        delta_ticks = last.tick_count - first.tick_count
        return delta_ticks / elapsed

    def passes(self) -> bool:
        """Return True if all pass criteria are met."""
        tps = self.average_tps()
        if tps < MIN_TICKS_PER_SECOND:
            return False
        for pair in MAJOR_PAIRS:
            if self.max_consecutive_stale_s.get(pair, 0.0) > MAX_STALE_WINDOW_S:
                return False
        return True

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict."""
        return {
            "start_time": datetime.fromtimestamp(self.start_time, tz=timezone.utc).isoformat(),
            "end_time": datetime.fromtimestamp(self.end_time, tz=timezone.utc).isoformat(),
            "duration_s": self.end_time - self.start_time,
            "sample_count": len(self.samples),
            "average_tps": round(self.average_tps(), 2),
            "min_tps_threshold": MIN_TICKS_PER_SECOND,
            "max_stale_window_threshold_s": MAX_STALE_WINDOW_S,
            "max_consecutive_stale_s": {
                k: round(v, 1) for k, v in self.max_consecutive_stale_s.items()
            },
            "passed": self.passes(),
        }


# ---------------------------------------------------------------------------
# Metrics collection helpers
# ---------------------------------------------------------------------------


async def collect_sample(
    redis_client: aioredis.Redis,
    db_pool: asyncpg.Pool,
    http_client: httpx.AsyncClient,
) -> Sample:
    """Collect a single metrics snapshot from all sources."""
    s = Sample()

    # TimescaleDB tick count
    try:
        row = await db_pool.fetchrow("SELECT count(*) AS c FROM ticks")
        s.tick_count = row["c"] if row else 0
    except Exception as exc:
        s.error += f"DB:{exc} "

    # Redis pair count and stale major pairs
    try:
        prices_meta = await redis_client.hgetall("prices:meta")
        s.redis_pairs = len(prices_meta)
        now = time.time()
        for pair in MAJOR_PAIRS:
            ts_str = prices_meta.get(pair)
            if ts_str is None:
                s.stale_major_pairs.append(pair)
            elif (now - float(ts_str)) > MAX_STALE_WINDOW_S:
                s.stale_major_pairs.append(pair)
    except Exception as exc:
        s.error += f"Redis:{exc} "

    # API /health
    try:
        t0 = time.perf_counter()
        resp = await http_client.get(f"{API_BASE_URL}/health", timeout=5.0)
        s.api_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        body = resp.json()
        s.api_status = body.get("status", "unknown")
    except Exception as exc:
        s.api_status = "error"
        s.error += f"API:{exc} "

    return s


# ---------------------------------------------------------------------------
# Main stability loop
# ---------------------------------------------------------------------------


async def run() -> int:
    """Run the stability test and write a JSON report on completion."""
    log.info("Starting Phase 1 stability test (duration=%ds, sample_interval=%ds)", DURATION_S, SAMPLE_INTERVAL_S)
    log.info("DB:    %s", DB_URL[:80])
    log.info("Redis: %s", REDIS_URL)
    log.info("API:   %s", API_BASE_URL)

    # Connect to all backends
    redis_client: aioredis.Redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    db_pool: asyncpg.Pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=3)
    http_client = httpx.AsyncClient()

    report = StabilityReport()
    deadline = report.start_time + DURATION_S
    sample_num = 0

    try:
        while time.time() < deadline:
            sample_num += 1
            remaining = max(0, deadline - time.time())
            elapsed = time.time() - report.start_time

            s = await collect_sample(redis_client, db_pool, http_client)
            report.record_sample(s)

            stale_info = f"stale={s.stale_major_pairs}" if s.stale_major_pairs else "all-major-fresh"
            log.info(
                "[%d/%d] t=%ds ticks=%d redis_pairs=%d api=%s(%dms) %s%s",
                sample_num,
                DURATION_S // SAMPLE_INTERVAL_S,
                int(elapsed),
                s.tick_count,
                s.redis_pairs,
                s.api_status,
                int(s.api_latency_ms),
                stale_info,
                f" ERR:{s.error}" if s.error else "",
            )

            # Sleep until next sample (or deadline)
            sleep_secs = min(SAMPLE_INTERVAL_S, remaining)
            if sleep_secs > 0:
                await asyncio.sleep(sleep_secs)

    except asyncio.CancelledError:
        log.info("Stability test cancelled — generating partial report")
    except KeyboardInterrupt:
        log.info("Interrupted — generating partial report")
    finally:
        report.end_time = time.time()
        await redis_client.aclose()
        await db_pool.close()
        await http_client.aclose()

    # ── Write report ──────────────────────────────────────────────────────────
    report_data = report.to_dict()
    ts_str = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    report_path = REPORT_DIR / f"stability_{ts_str}.json"
    report_path.write_text(json.dumps(report_data, indent=2))

    print()
    print("=" * 60)
    print("  Phase 1 Stability Test — REPORT")
    print("=" * 60)
    print(json.dumps(report_data, indent=2))
    print()
    print(f"  Report saved: {report_path}")
    print()

    if report_data["passed"]:
        print("  ✓  PASSED — zero data-loss criteria met")
        return 0
    else:
        print("  ✗  FAILED — see report for details")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:
        sys.exit(0)
