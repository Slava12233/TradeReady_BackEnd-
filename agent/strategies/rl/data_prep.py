"""Historical data validation and train/val/test split calculator for RL training.

Queries the platform's market data API to determine how much OHLCV candle data is
available for each asset in the training universe.  For each asset it computes:

- Coverage percentage vs. the expected candle count over the full available window
- Per-split (train / val / test) coverage percentages using an 8/2/2 ratio
- Gap detection: runs of consecutive missing candles above a configurable threshold

The script exits with code 1 if any asset has less than ``min_coverage_pct``
coverage in any split (default 95 %).

Usage::

    python -m agent.strategies.rl.data_prep \\
        --base-url http://localhost:8000 \\
        --assets BTCUSDT ETHUSDT SOLUSDT \\
        --interval 1h \\
        --min-coverage 95.0

Output (stdout, JSON-serialisable)::

    {
      "status": "ok" | "insufficient_data",
      "data_range": {"earliest": "...", "latest": "...", "total_pairs": 123},
      "splits": {"train": {...}, "val": {...}, "test": {...}},
      "assets": [
        {
          "symbol": "BTCUSDT",
          "interval": "1h",
          "splits": {
            "train": {"start": "...", "end": "...", "expected": 1000, "actual": 998, "coverage_pct": 99.8, "gaps": []},
            "val":   {...},
            "test":  {...}
          },
          "overall_coverage_pct": 99.8,
          "ready": true
        }
      ],
      "ready_assets": ["BTCUSDT"],
      "unready_assets": []
    }
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field

# ── Logging ──────────────────────────────────────────────────────────────────

logger = structlog.get_logger(__name__)

# ── Interval helpers ─────────────────────────────────────────────────────────

# Mapping from candle interval string to its duration in seconds.
# These are the four intervals supported by GET /api/v1/market/candles/{symbol}.
_INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "1h": 3_600,
    "1d": 86_400,
}

# Split ratios: 8/2/2 (train / val / test).
_TRAIN_RATIO = 8 / 12
_VAL_RATIO = 2 / 12
_TEST_RATIO = 2 / 12

# ── Pydantic models ───────────────────────────────────────────────────────────


class SplitDateRange(BaseModel):
    """A single time-bounded split (train, val, or test).

    Args:
        name: Split name — ``"train"``, ``"val"``, or ``"test"``.
        start: Inclusive start timestamp (UTC).
        end: Inclusive end timestamp (UTC).
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Split label: train, val, or test")
    start: datetime = Field(..., description="Inclusive UTC start of this split")
    end: datetime = Field(..., description="Inclusive UTC end of this split")


class GapInfo(BaseModel):
    """A detected run of consecutive missing candles.

    Args:
        gap_start: UTC timestamp of the first missing candle bucket.
        gap_end: UTC timestamp of the last missing candle bucket.
        missing_candles: Number of candles absent in this gap.
    """

    model_config = ConfigDict(frozen=True)

    gap_start: datetime = Field(..., description="UTC start of the gap")
    gap_end: datetime = Field(..., description="UTC end of the gap")
    missing_candles: int = Field(..., ge=1, description="Number of missing candles in this gap")


class SplitCoverage(BaseModel):
    """Coverage statistics for one split of one asset.

    Args:
        start: Split start timestamp (UTC, inclusive).
        end: Split end timestamp (UTC, inclusive).
        expected_candles: Number of candles expected if data is 100% complete.
        actual_candles: Number of candles the platform actually returned.
        coverage_pct: ``actual / expected * 100`` (capped at 100.0).
        gaps: Detected gaps where ``missing_candles > gap_threshold``.
    """

    model_config = ConfigDict(frozen=True)

    start: datetime = Field(..., description="Split start (UTC, inclusive)")
    end: datetime = Field(..., description="Split end (UTC, inclusive)")
    expected_candles: int = Field(..., ge=0, description="Candles expected at 100% coverage")
    actual_candles: int = Field(..., ge=0, description="Candles the platform returned")
    coverage_pct: float = Field(..., ge=0.0, le=100.0, description="actual / expected * 100")
    gaps: list[GapInfo] = Field(default_factory=list, description="Detected data gaps")


class AssetReadiness(BaseModel):
    """Data readiness report for a single asset across all three splits.

    Args:
        symbol: Trading pair symbol (e.g. ``"BTCUSDT"``).
        interval: Candle interval queried (e.g. ``"1h"``).
        splits: Per-split coverage reports keyed by ``"train"``, ``"val"``, ``"test"``.
        overall_coverage_pct: Weighted-average coverage across all three splits.
        ready: ``True`` when all splits meet the minimum coverage threshold.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading pair symbol")
    interval: str = Field(..., description="Candle interval")
    splits: dict[str, SplitCoverage] = Field(..., description="train / val / test split coverage")
    overall_coverage_pct: float = Field(
        ..., ge=0.0, le=100.0, description="Weighted average coverage across all splits"
    )
    ready: bool = Field(..., description="True when all splits meet min_coverage_pct")


class DataReadiness(BaseModel):
    """Full data readiness report for an RL training universe.

    This is the top-level output model.  Serialise to JSON via
    ``report.model_dump_json(indent=2)``.

    Args:
        status: ``"ok"`` when all assets are ready, ``"insufficient_data"`` otherwise.
        checked_at: UTC timestamp when the check was performed.
        interval: Candle interval used for all checks.
        min_coverage_pct: Minimum required coverage percentage per split.
        gap_threshold: Minimum gap size (in candles) to be reported.
        data_range: Platform-reported available data window.
        splits: Recommended date ranges for train / val / test splits.
        assets: Per-asset readiness reports.
        ready_assets: Symbols that pass the coverage threshold.
        unready_assets: Symbols that fail the coverage threshold (block training).
    """

    model_config = ConfigDict(frozen=True)

    status: str = Field(..., description="ok | insufficient_data")
    checked_at: datetime = Field(..., description="UTC timestamp of the check")
    interval: str = Field(..., description="Candle interval used for all checks")
    min_coverage_pct: float = Field(
        ..., ge=0.0, le=100.0, description="Required coverage threshold (%)"
    )
    gap_threshold: int = Field(..., ge=1, description="Min gap size (candles) to report")
    data_range: dict[str, Any] = Field(..., description="Platform data range response")
    splits: dict[str, SplitDateRange] = Field(
        ..., description="Recommended train / val / test date ranges"
    )
    assets: list[AssetReadiness] = Field(..., description="Per-asset coverage details")
    ready_assets: list[str] = Field(..., description="Symbols that pass the coverage threshold")
    unready_assets: list[str] = Field(..., description="Symbols that fail the coverage threshold")


# ── REST client ───────────────────────────────────────────────────────────────


class DataPrepClient:
    """Thin async HTTP client for the market data and backtest data-range endpoints.

    Args:
        base_url: Platform base URL (e.g. ``"http://localhost:8000"``).
        api_key: Platform API key with ``X-API-Key`` header authentication.
        timeout: HTTP request timeout in seconds (default 30).
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    async def __aenter__(self) -> DataPrepClient:
        """Enter async context, returning self."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit async context and close the underlying HTTP client."""
        await self._client.aclose()

    async def get_data_range(self) -> dict[str, Any]:
        """Fetch the available historical data window from the platform.

        Calls ``GET /api/v1/market/data-range``.

        Returns:
            Dict with keys ``earliest``, ``latest``, ``total_pairs``,
            ``intervals_available``, ``data_gaps``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            httpx.RequestError: On network errors.
        """
        try:
            response = await self._client.get("/api/v1/market/data-range")
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            logger.error(
                "agent.strategy.data_prep.range_fetch_failed",
                status=exc.response.status_code,
                body=exc.response.text[:200],
            )
            raise
        except httpx.RequestError as exc:
            logger.error("agent.strategy.data_prep.range_network_error", error=str(exc))
            raise

    async def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candles for one asset over a time window.

        Calls ``GET /api/v1/market/candles/{symbol}`` with start_time / end_time
        filters.  Pages through results if ``expected_candles > limit`` by
        advancing the ``start_time`` pointer.

        Args:
            symbol: Trading pair symbol (e.g. ``"BTCUSDT"``).
            interval: Candle interval — ``"1m"``, ``"5m"``, ``"1h"``, or ``"1d"``.
            start_time: Window start (UTC, inclusive).
            end_time: Window end (UTC, inclusive).
            limit: Number of candles per page (max 1000, platform limit).

        Returns:
            List of candle dicts, each with keys ``bucket``, ``open``, ``high``,
            ``low``, ``close``, ``volume``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            httpx.RequestError: On network errors.
        """
        all_candles: list[dict[str, Any]] = []
        # Work forward in time by using end_time DESC ordering as the API
        # returns data DESC.  We collect pages until we run out of data.
        # The API sorts DESC; to paginate forward we use end_time sliding.
        current_end = end_time

        while True:
            try:
                response = await self._client.get(
                    f"/api/v1/market/candles/{symbol}",
                    params={
                        "interval": interval,
                        "limit": limit,
                        "start_time": start_time.isoformat(),
                        "end_time": current_end.isoformat(),
                    },
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "agent.strategy.data_prep.candles_fetch_failed",
                    symbol=symbol,
                    interval=interval,
                    status=exc.response.status_code,
                    body=exc.response.text[:200],
                )
                raise
            except httpx.RequestError as exc:
                logger.error("agent.strategy.data_prep.candles_network_error", symbol=symbol, error=str(exc))
                raise

            candles: list[dict[str, Any]] = data.get("candles", [])
            if not candles:
                break

            all_candles.extend(candles)

            # If we got fewer than `limit` candles, there is no earlier page.
            if len(candles) < limit:
                break

            # The API returns DESC; the last element in the page is the oldest.
            # Move end pointer to just before the oldest returned candle.
            oldest_bucket_str: str = candles[-1]["bucket"]
            oldest_bucket = datetime.fromisoformat(oldest_bucket_str.replace("Z", "+00:00"))
            interval_secs = _INTERVAL_SECONDS[interval]
            current_end = oldest_bucket - timedelta(seconds=interval_secs)

            # Stop if we have gone past the requested start.
            if current_end < start_time:
                break

        return all_candles


# ── Gap detection ─────────────────────────────────────────────────────────────


def _detect_gaps(
    candles: list[dict[str, Any]],
    interval: str,
    start_time: datetime,
    end_time: datetime,
    gap_threshold: int,
) -> list[GapInfo]:
    """Detect runs of missing candles larger than ``gap_threshold``.

    Builds the complete set of expected bucket timestamps and compares it
    against the set of returned buckets.  Consecutive missing timestamps are
    grouped into gap records.

    Args:
        candles: Candle dicts from the platform, each containing a ``bucket`` key.
        interval: Candle interval string (``"1m"``, ``"5m"``, ``"1h"``, ``"1d"``).
        start_time: Window start (UTC, inclusive).
        end_time: Window end (UTC, inclusive).
        gap_threshold: Minimum number of consecutive missing candles to report.

    Returns:
        List of :class:`GapInfo` records, sorted by ``gap_start`` ascending.
    """
    interval_secs = _INTERVAL_SECONDS[interval]
    interval_td = timedelta(seconds=interval_secs)

    # Build set of returned bucket timestamps.  The API serialises as ISO-8601
    # strings; normalise to UTC-aware datetimes for comparison.
    returned_buckets: set[datetime] = set()
    for c in candles:
        raw = c.get("bucket", "")
        if raw:
            try:
                ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                returned_buckets.add(ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC))
            except ValueError:
                pass

    # Walk every expected bucket from start to end.
    gaps: list[GapInfo] = []
    current = start_time.astimezone(UTC)
    end_utc = end_time.astimezone(UTC)

    gap_run_start: datetime | None = None
    gap_run_count = 0

    def _flush_gap(gap_start: datetime, count: int, gap_end: datetime) -> GapInfo | None:
        if count >= gap_threshold:
            return GapInfo(gap_start=gap_start, gap_end=gap_end, missing_candles=count)
        return None

    while current <= end_utc:
        if current not in returned_buckets:
            if gap_run_start is None:
                gap_run_start = current
                gap_run_count = 1
            else:
                gap_run_count += 1
            gap_run_last = current
        else:
            if gap_run_start is not None:
                gap = _flush_gap(gap_run_start, gap_run_count, gap_run_last)
                if gap is not None:
                    gaps.append(gap)
                gap_run_start = None
                gap_run_count = 0

        current += interval_td

    # Flush trailing gap.
    if gap_run_start is not None and gap_run_count > 0:
        gap = _flush_gap(gap_run_start, gap_run_count, gap_run_last)  # type: ignore[possibly-undefined]
        if gap is not None:
            gaps.append(gap)

    return gaps


# ── Coverage calculation ──────────────────────────────────────────────────────


def _compute_expected_candles(start: datetime, end: datetime, interval: str) -> int:
    """Calculate the number of candles expected between ``start`` and ``end``.

    Args:
        start: Window start (UTC, inclusive).
        end: Window end (UTC, inclusive).
        interval: Candle interval string.

    Returns:
        Expected candle count (>= 0).
    """
    interval_secs = _INTERVAL_SECONDS[interval]
    total_secs = (end - start).total_seconds()
    # +1 because both endpoints are inclusive.
    return max(0, math.floor(total_secs / interval_secs) + 1)


def _compute_split_coverage(
    candles: list[dict[str, Any]],
    split: SplitDateRange,
    interval: str,
    gap_threshold: int,
) -> SplitCoverage:
    """Compute coverage statistics for a single split window.

    Filters ``candles`` to those within the split window, then calculates the
    coverage percentage and detects gaps.

    Args:
        candles: All candles fetched for this asset (may span multiple splits).
        split: The split to compute coverage for.
        interval: Candle interval string.
        gap_threshold: Minimum gap size (candles) to report.

    Returns:
        :class:`SplitCoverage` for the given split.
    """
    split_start_utc = split.start.astimezone(UTC)
    split_end_utc = split.end.astimezone(UTC)

    # Filter to candles inside this split window.
    split_candles: list[dict[str, Any]] = []
    for c in candles:
        raw = c.get("bucket", "")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            ts_utc = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        except ValueError:
            continue
        if split_start_utc <= ts_utc <= split_end_utc:
            split_candles.append(c)

    expected = _compute_expected_candles(split_start_utc, split_end_utc, interval)
    actual = len(split_candles)
    coverage = min(100.0, (actual / expected * 100.0) if expected > 0 else 100.0)

    gaps = _detect_gaps(split_candles, interval, split_start_utc, split_end_utc, gap_threshold)

    return SplitCoverage(
        start=split_start_utc,
        end=split_end_utc,
        expected_candles=expected,
        actual_candles=actual,
        coverage_pct=round(coverage, 2),
        gaps=gaps,
    )


# ── Split boundary calculator ─────────────────────────────────────────────────


def _compute_splits(earliest: datetime, latest: datetime) -> dict[str, SplitDateRange]:
    """Divide the available date range into train / val / test splits (8/2/2).

    Args:
        earliest: Earliest available candle timestamp (UTC).
        latest: Latest available candle timestamp (UTC).

    Returns:
        Dict with keys ``"train"``, ``"val"``, ``"test"``, each a
        :class:`SplitDateRange`.
    """
    total_seconds = (latest - earliest).total_seconds()
    train_secs = total_seconds * _TRAIN_RATIO
    val_secs = total_seconds * _VAL_RATIO

    train_end = earliest + timedelta(seconds=train_secs)
    val_end = train_end + timedelta(seconds=val_secs)
    # test_end is `latest` itself.

    return {
        "train": SplitDateRange(name="train", start=earliest, end=train_end),
        "val": SplitDateRange(name="val", start=train_end, end=val_end),
        "test": SplitDateRange(name="test", start=val_end, end=latest),
    }


# ── Core validation logic ─────────────────────────────────────────────────────


async def check_asset(
    client: DataPrepClient,
    symbol: str,
    interval: str,
    splits: dict[str, SplitDateRange],
    min_coverage_pct: float,
    gap_threshold: int,
) -> AssetReadiness:
    """Fetch and analyse candle data for a single asset.

    Fetches all candles from the platform for the full available window
    (earliest → latest), then computes per-split coverage statistics.

    Args:
        client: Initialised :class:`DataPrepClient`.
        symbol: Trading pair symbol.
        interval: Candle interval string.
        splits: Dict of split boundaries (from :func:`_compute_splits`).
        min_coverage_pct: Minimum coverage % required for ``ready=True``.
        gap_threshold: Minimum gap size (candles) to report.

    Returns:
        :class:`AssetReadiness` with per-split coverage data.
    """
    # Determine full fetch window from the union of all splits.
    all_starts = [s.start for s in splits.values()]
    all_ends = [s.end for s in splits.values()]
    window_start = min(all_starts).astimezone(UTC)
    window_end = max(all_ends).astimezone(UTC)

    logger.info(
        "agent.strategy.data_prep.checking_asset",
        symbol=symbol,
        interval=interval,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
    )

    candles = await client.get_candles(
        symbol=symbol,
        interval=interval,
        start_time=window_start,
        end_time=window_end,
    )

    logger.info("agent.strategy.data_prep.candles_fetched", symbol=symbol, count=len(candles))

    split_coverages: dict[str, SplitCoverage] = {}
    for split_name, split in splits.items():
        coverage = _compute_split_coverage(candles, split, interval, gap_threshold)
        split_coverages[split_name] = coverage
        logger.info(
            "agent.strategy.data_prep.split_coverage",
            symbol=symbol,
            split=split_name,
            coverage_pct=coverage.coverage_pct,
            actual=coverage.actual_candles,
            expected=coverage.expected_candles,
            gaps=len(coverage.gaps),
        )

    # Weighted overall coverage (by split duration).
    total_expected = sum(c.expected_candles for c in split_coverages.values())
    total_actual = sum(c.actual_candles for c in split_coverages.values())
    overall = min(100.0, (total_actual / total_expected * 100.0) if total_expected > 0 else 100.0)

    ready = all(c.coverage_pct >= min_coverage_pct for c in split_coverages.values())

    return AssetReadiness(
        symbol=symbol,
        interval=interval,
        splits=split_coverages,
        overall_coverage_pct=round(overall, 2),
        ready=ready,
    )


async def validate_data(
    base_url: str,
    api_key: str,
    assets: list[str],
    interval: str = "1h",
    min_coverage_pct: float = 95.0,
    gap_threshold: int = 5,
) -> DataReadiness:
    """Run the full data validation pipeline for a list of assets.

    This is the main entry point for programmatic use.  It:

    1. Fetches the platform data range (earliest / latest timestamps).
    2. Computes 8/2/2 train/val/test split boundaries.
    3. For each asset, fetches candles and computes per-split coverage.
    4. Assembles a :class:`DataReadiness` report.

    Args:
        base_url: Platform base URL (e.g. ``"http://localhost:8000"``).
        api_key: Platform API key (``ak_live_...`` format).
        assets: List of trading pair symbols to check.
        interval: Candle interval — ``"1m"``, ``"5m"``, ``"1h"``, or ``"1d"``.
            Default: ``"1h"``.
        min_coverage_pct: Minimum acceptable coverage percentage per split.
            Any asset with a split below this threshold is flagged as unready.
            Default: ``95.0``.
        gap_threshold: Minimum number of consecutive missing candles to include
            in the gaps list.  Smaller gaps are ignored.  Default: ``5``.

    Returns:
        :class:`DataReadiness` report (JSON-serialisable via
        ``.model_dump_json()``).
    """
    if interval not in _INTERVAL_SECONDS:
        raise ValueError(
            f"Unsupported interval '{interval}'. "
            f"Valid values: {', '.join(_INTERVAL_SECONDS)}"
        )

    checked_at = datetime.now(UTC)

    async with DataPrepClient(base_url, api_key) as client:
        # Step 1: Get platform data range.
        logger.info("agent.strategy.data_prep.fetching_data_range", base_url=base_url)
        data_range_raw = await client.get_data_range()

        earliest_str: str | None = data_range_raw.get("earliest")
        latest_str: str | None = data_range_raw.get("latest")

        if not earliest_str or not latest_str:
            # Platform has no data at all — return an all-failed report.
            logger.warning("agent.strategy.data_prep.no_data_range_available")
            empty_splits: dict[str, SplitDateRange] = {
                "train": SplitDateRange(name="train", start=checked_at, end=checked_at),
                "val": SplitDateRange(name="val", start=checked_at, end=checked_at),
                "test": SplitDateRange(name="test", start=checked_at, end=checked_at),
            }
            return DataReadiness(
                status="insufficient_data",
                checked_at=checked_at,
                interval=interval,
                min_coverage_pct=min_coverage_pct,
                gap_threshold=gap_threshold,
                data_range=data_range_raw,
                splits=empty_splits,
                assets=[],
                ready_assets=[],
                unready_assets=assets,
            )

        earliest = datetime.fromisoformat(earliest_str.replace("Z", "+00:00")).astimezone(UTC)
        latest = datetime.fromisoformat(latest_str.replace("Z", "+00:00")).astimezone(UTC)

        logger.info(
            "agent.strategy.data_prep.data_range_received",
            earliest=earliest.isoformat(),
            latest=latest.isoformat(),
            total_pairs=data_range_raw.get("total_pairs", 0),
        )

        # Step 2: Compute split boundaries.
        splits = _compute_splits(earliest, latest)
        logger.info(
            "agent.strategy.data_prep.splits_computed",
            train_start=splits["train"].start.isoformat(),
            train_end=splits["train"].end.isoformat(),
            val_start=splits["val"].start.isoformat(),
            val_end=splits["val"].end.isoformat(),
            test_start=splits["test"].start.isoformat(),
            test_end=splits["test"].end.isoformat(),
        )

        # Step 3: Check all assets concurrently — each asset's candle fetch is
        # independent.  Use return_exceptions=True so one bad asset does not
        # cancel the others.
        asset_tasks = [
            check_asset(
                client=client,
                symbol=symbol,
                interval=interval,
                splits=splits,
                min_coverage_pct=min_coverage_pct,
                gap_threshold=gap_threshold,
            )
            for symbol in assets
        ]
        raw_results = await asyncio.gather(*asset_tasks, return_exceptions=True)

        asset_reports: list[AssetReadiness] = []
        for symbol, result in zip(assets, raw_results):
            if isinstance(result, httpx.HTTPStatusError | httpx.RequestError):
                logger.error("agent.strategy.data_prep.asset_check_failed", symbol=symbol, error=str(result))
                # Mark the asset as having zero coverage on all splits.
                zero_splits = {
                    name: SplitCoverage(
                        start=split.start,
                        end=split.end,
                        expected_candles=_compute_expected_candles(
                            split.start.astimezone(UTC),
                            split.end.astimezone(UTC),
                            interval,
                        ),
                        actual_candles=0,
                        coverage_pct=0.0,
                        gaps=[],
                    )
                    for name, split in splits.items()
                }
                asset_reports.append(
                    AssetReadiness(
                        symbol=symbol,
                        interval=interval,
                        splits=zero_splits,
                        overall_coverage_pct=0.0,
                        ready=False,
                    )
                )
            elif isinstance(result, Exception):
                # Re-raise unexpected errors so the caller sees them.
                raise result
            else:
                asset_reports.append(result)

    ready_assets = [a.symbol for a in asset_reports if a.ready]
    unready_assets = [a.symbol for a in asset_reports if not a.ready]
    overall_status = "ok" if not unready_assets else "insufficient_data"

    return DataReadiness(
        status=overall_status,
        checked_at=checked_at,
        interval=interval,
        min_coverage_pct=min_coverage_pct,
        gap_threshold=gap_threshold,
        data_range=data_range_raw,
        splits=splits,
        assets=asset_reports,
        ready_assets=ready_assets,
        unready_assets=unready_assets,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent.strategies.rl.data_prep",
        description=(
            "Validate historical data availability for RL training. "
            "Exits with code 1 if any asset has < min_coverage in any split."
        ),
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Platform REST API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        metavar="SYMBOL",
        help="Trading pair symbols to check (default: BTCUSDT ETHUSDT SOLUSDT)",
    )
    parser.add_argument(
        "--interval",
        default="1h",
        choices=list(_INTERVAL_SECONDS.keys()),
        help="Candle interval (default: 1h)",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=95.0,
        metavar="PCT",
        help="Minimum required coverage %% per split (default: 95.0). "
             "Exit code 1 if any asset falls below this.",
    )
    parser.add_argument(
        "--gap-threshold",
        type=int,
        default=5,
        metavar="N",
        help="Minimum consecutive missing candles to flag as a gap (default: 5)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw JSON only (no human-readable summary). Useful for piping.",
    )
    return parser


def _log_human_summary(report: DataReadiness) -> None:
    """Log data readiness summary via structlog.

    Args:
        report: The completed :class:`DataReadiness` report.
    """
    dr = report.data_range
    asset_rows = []
    for asset in report.assets:
        tc = asset.splits.get("train")
        vc = asset.splits.get("val")
        ec = asset.splits.get("test")
        total_gaps = sum(len(s.gaps) for s in asset.splits.values())
        asset_rows.append({
            "symbol": asset.symbol,
            "overall_pct": round(asset.overall_coverage_pct, 1),
            "train_pct": round(tc.coverage_pct, 1) if tc else None,
            "val_pct": round(vc.coverage_pct, 1) if vc else None,
            "test_pct": round(ec.coverage_pct, 1) if ec else None,
            "gaps": total_gaps,
            "ready": asset.ready,
        })

    logger.info(
        "agent.strategy.data_prep.readiness_report",
        checked_at=report.checked_at.strftime("%Y-%m-%d %H:%M UTC"),
        status=report.status.upper(),
        interval=report.interval,
        min_coverage_pct=report.min_coverage_pct,
        data_range_earliest=dr.get("earliest", "N/A"),
        data_range_latest=dr.get("latest", "N/A"),
        total_pairs=dr.get("total_pairs", 0),
        splits={
            name: {
                "start": split.start.strftime("%Y-%m-%d %H:%M"),
                "end": split.end.strftime("%Y-%m-%d %H:%M"),
            }
            for name, split in report.splits.items()
        },
        assets=asset_rows,
        unready_assets=report.unready_assets,
    )


async def _async_main(argv: list[str] | None = None) -> int:
    """Async entry point for the data preparation CLI.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: ``0`` on success, ``1`` on insufficient data or error.
    """
    from agent.logging import configure_agent_logging  # noqa: PLC0415

    configure_agent_logging()

    parser = _build_parser()
    args = parser.parse_args(argv)

    import os  # noqa: PLC0415

    api_key = os.environ.get("PLATFORM_API_KEY", "") or os.environ.get("RL_PLATFORM_API_KEY", "")

    try:
        report = await validate_data(
            base_url=args.base_url,
            api_key=api_key,
            assets=[s.upper() for s in args.assets],
            interval=args.interval,
            min_coverage_pct=args.min_coverage,
            gap_threshold=args.gap_threshold,
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.error("agent.strategy.data_prep.validation_failed", error=str(exc))
        print(f"ERROR: Failed to connect to platform at {args.base_url}: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    except ValueError as exc:
        logger.error("agent.strategy.data_prep.invalid_args", error=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    if args.json_output:
        print(report.model_dump_json(indent=2))  # noqa: T201
    else:
        _log_human_summary(report)
        print(report.model_dump_json(indent=2))  # noqa: T201

    if report.unready_assets:
        return 1
    return 0


def main(argv: list[str] | None = None) -> None:
    """Synchronous entry point — runs the async main function.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).
    """
    sys.exit(asyncio.run(_async_main(argv)))


if __name__ == "__main__":
    main()
