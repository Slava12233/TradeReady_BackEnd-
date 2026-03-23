"""Dynamic pair selector — ranks and caches tradeable pairs by volume and momentum.

:class:`PairSelector` fetches 24h market data from the platform REST API, applies
volume / spread / staleness filters, ranks pairs by USDT quote-volume, and adds a
"momentum tier" of the biggest absolute movers.  Results are cached for a
configurable TTL (default 1 hour) to avoid hammering the platform on every tick.

Architecture::

    PairSelector.get_active_pairs()
           │
           ├── (cache hit)  → return cached SelectedPairs
           │
           └── (cache miss)
                    │
                    ├── GET /api/v1/market/prices   → all active symbols
                    │
                    ├── GET /api/v1/market/tickers?symbols=…  (batched, ≤100 at a time)
                    │
                    ├── Filter: quote_volume ≥ MIN_QUOTE_VOLUME_USD
                    │         spread_pct ≤ MAX_SPREAD_PCT
                    │
                    ├── Rank by quote_volume DESC → top TOP_N_PAIRS
                    │
                    ├── Momentum tier: top MOMENTUM_N_PAIRS by |change_pct| (gainers + losers)
                    │
                    └── Merge, deduplicate, cache → SelectedPairs

Usage::

    import httpx
    from agent.config import AgentConfig
    from agent.trading.pair_selector import PairSelector

    config = AgentConfig()
    async with httpx.AsyncClient(base_url=config.platform_base_url) as rest:
        selector = PairSelector(config=config, rest_client=rest)
        pairs = await selector.get_active_pairs()
        print(pairs.volume_ranked[:5])    # Top 5 by volume
        print(pairs.momentum_tier[:5])    # Top 5 big movers
        print(pairs.all_symbols[:20])     # Combined ranked list (no duplicates)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog

from agent.config import AgentConfig

logger = structlog.get_logger(__name__)

# ── Module-level constants ─────────────────────────────────────────────────────

# Minimum 24h quote volume (USDT) a pair must have to pass the volume filter.
# $10 M is deliberately conservative — illiquid pairs produce noisy signals.
MIN_QUOTE_VOLUME_USD: Decimal = Decimal("10_000_000")

# Maximum synthetic spread (high−low / close) to accept.
# Pairs wider than 5% are too illiquid for reliable fills.
MAX_SPREAD_PCT: Decimal = Decimal("0.05")

# Number of pairs selected by the volume ranking (the "main" tier).
TOP_N_PAIRS: int = 30

# Number of pairs selected by the momentum ranking (big movers, both directions).
MOMENTUM_N_PAIRS: int = 10

# Maximum number of symbols to send in a single /market/tickers request.
# The platform caps this at 100 per request.
_TICKER_BATCH_SIZE: int = 100

# Default cache TTL in seconds (1 hour).
_DEFAULT_TTL_SECONDS: float = 3600.0

# If the prices endpoint returns fewer than this many symbols the platform
# probably has not finished warming its cache; skip the refresh and return
# whatever we have (or defaults).
_MIN_SYMBOLS_THRESHOLD: int = 5


# ── Public data models ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PairInfo:
    """Snapshot of a single pair's key market metrics.

    Attributes:
        symbol:       Uppercase trading pair symbol, e.g. ``"BTCUSDT"``.
        quote_volume: 24h traded volume in USDT.
        change_pct:   24h price change as a fraction (e.g. ``0.03`` = +3%).
        spread_pct:   Synthetic spread (high−low)/close as a fraction.
        close:        Latest close price in USDT.
    """

    symbol: str
    quote_volume: Decimal
    change_pct: Decimal
    spread_pct: Decimal
    close: Decimal


@dataclass
class SelectedPairs:
    """Result of a :class:`PairSelector` refresh cycle.

    Attributes:
        volume_ranked:  Top-N pairs ranked by 24h USDT volume (descending).
        momentum_tier:  Top-M pairs ranked by absolute 24h change (big movers).
        all_symbols:    Deduplicated union of volume_ranked + momentum_tier in
                        stable order (volume_ranked first, then any momentum
                        additions).
        refreshed_at:   Unix timestamp (seconds) when this result was computed.
        total_scanned:  Number of symbols considered before filtering.
        total_passed_filter: Number of symbols that passed volume + spread filters.
    """

    volume_ranked: list[str] = field(default_factory=list)
    momentum_tier: list[str] = field(default_factory=list)
    all_symbols: list[str] = field(default_factory=list)
    refreshed_at: float = field(default_factory=time.monotonic)
    total_scanned: int = 0
    total_passed_filter: int = 0

    def is_stale(self, ttl_seconds: float) -> bool:
        """Return True when the cache has expired.

        Args:
            ttl_seconds: Cache lifetime in seconds.

        Returns:
            ``True`` if the age of this result exceeds *ttl_seconds*.
        """
        return (time.monotonic() - self.refreshed_at) >= ttl_seconds


# ── PairSelector ───────────────────────────────────────────────────────────────


class PairSelector:
    """Dynamically selects the top tradeable pairs by volume and momentum.

    Fetches 24h ticker data from the platform REST API, filters by minimum
    USDT quote-volume and maximum spread, then produces two ranked lists:

    - **Volume tier** — top :data:`TOP_N_PAIRS` pairs by 24h USDT quote-volume.
    - **Momentum tier** — top :data:`MOMENTUM_N_PAIRS` pairs by absolute 24h
      change percentage (the biggest gainers *and* losers combined).

    Results are cached for *ttl_seconds* (default 1 hour).  Concurrent callers
    share the same refresh — only one refresh runs at a time thanks to an
    internal :class:`asyncio.Lock`.

    Args:
        config:          :class:`~agent.config.AgentConfig` instance (for
                         platform URL and credentials).
        rest_client:     An :class:`httpx.AsyncClient` already pointing at the
                         platform base URL.  If ``None``, ``get_active_pairs()``
                         always returns the fallback symbols from *config*.
        ttl_seconds:     How long to cache a result before refreshing.
                         Default is ``3600.0`` (1 hour).
        min_volume_usd:  Minimum 24h USDT quote-volume filter threshold.
                         Override from :data:`MIN_QUOTE_VOLUME_USD` if needed.
        max_spread_pct:  Maximum synthetic spread filter threshold.
                         Override from :data:`MAX_SPREAD_PCT` if needed.
        top_n_pairs:     Number of pairs to keep in the volume tier.
                         Override from :data:`TOP_N_PAIRS` if needed.
        momentum_n_pairs: Number of pairs to keep in the momentum tier.
                         Override from :data:`MOMENTUM_N_PAIRS` if needed.

    Example::

        selector = PairSelector(config=config, rest_client=rest)
        pairs = await selector.get_active_pairs()
        signals = await generator.generate(pairs.all_symbols[:20])
    """

    def __init__(
        self,
        config: AgentConfig,
        rest_client: httpx.AsyncClient | None = None,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        min_volume_usd: Decimal = MIN_QUOTE_VOLUME_USD,
        max_spread_pct: Decimal = MAX_SPREAD_PCT,
        top_n_pairs: int = TOP_N_PAIRS,
        momentum_n_pairs: int = MOMENTUM_N_PAIRS,
        min_symbols_threshold: int = _MIN_SYMBOLS_THRESHOLD,
    ) -> None:
        self._config = config
        self._rest = rest_client
        self._ttl = ttl_seconds
        self._min_volume = min_volume_usd
        self._max_spread = max_spread_pct
        self._top_n = top_n_pairs
        self._momentum_n = momentum_n_pairs
        self._min_symbols = min_symbols_threshold

        self._cache: SelectedPairs | None = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._log = logger.bind(component="pair_selector")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_active_pairs(self) -> SelectedPairs:
        """Return the current ranked pair list, refreshing if the cache is stale.

        When the cache is fresh (within TTL) this is a no-op returning the
        cached :class:`SelectedPairs`.  When stale (or on first call) this
        fetches all symbols and ticker data from the platform, applies filters,
        and recomputes both tiers.

        Only one concurrent refresh can run at a time.  Additional callers that
        arrive while a refresh is in progress will wait on the internal lock and
        then receive the freshly-computed result without triggering a second
        refresh.

        Returns:
            :class:`SelectedPairs` with ``volume_ranked``, ``momentum_tier``,
            and ``all_symbols`` lists.  Falls back to *config.symbols* when the
            REST client is unavailable or the platform returns no data.
        """
        # Fast path: cache is valid, skip the lock entirely.
        if self._cache is not None and not self._cache.is_stale(self._ttl):
            self._log.debug(
                "agent.pair_selector.cache_hit",
                symbols=len(self._cache.all_symbols),
            )
            return self._cache

        async with self._lock:
            # Re-check inside the lock: another coroutine may have refreshed
            # while we were waiting.
            if self._cache is not None and not self._cache.is_stale(self._ttl):
                return self._cache

            self._log.info("agent.pair_selector.refresh_start")
            try:
                self._cache = await self._refresh()
            except Exception as exc:  # noqa: BLE001
                # Non-crashing: log and fall back to config symbols.
                self._log.error(
                    "agent.pair_selector.refresh_failed",
                    error=str(exc),
                )
                # Keep stale cache if we have it, else build a minimal fallback.
                if self._cache is None:
                    self._cache = self._fallback_result()

            self._log.info(
                "agent.pair_selector.refresh_complete",
                volume_ranked=len(self._cache.volume_ranked),
                momentum_tier=len(self._cache.momentum_tier),
                total_symbols=len(self._cache.all_symbols),
            )
            return self._cache

    def invalidate(self) -> None:
        """Force the next :meth:`get_active_pairs` call to refresh.

        Useful after major market events or when the caller wants to ensure
        a fresh selection (e.g. at the start of a trading session).
        """
        self._cache = None
        self._log.debug("agent.pair_selector.cache_invalidated")

    @property
    def cached_result(self) -> SelectedPairs | None:
        """Return the current cache entry without triggering a refresh.

        Returns:
            The cached :class:`SelectedPairs`, or ``None`` if never refreshed.
        """
        return self._cache

    # ------------------------------------------------------------------
    # Internal refresh pipeline
    # ------------------------------------------------------------------

    async def _refresh(self) -> SelectedPairs:
        """Execute the full refresh pipeline and return a new :class:`SelectedPairs`.

        Pipeline:
          1. Fetch all active symbols from ``GET /api/v1/market/prices``.
          2. Fetch 24h ticker data in batches of :data:`_TICKER_BATCH_SIZE`.
          3. Apply volume and spread filters.
          4. Rank by quote-volume → volume tier.
          5. Rank by |change_pct| → momentum tier.
          6. Merge and deduplicate.

        Returns:
            A fresh :class:`SelectedPairs` instance.

        Raises:
            RuntimeError: When no REST client is configured.
            httpx.HTTPStatusError: On non-2xx responses from the platform.
            httpx.RequestError: On transport-level failures.
        """
        if self._rest is None:
            raise RuntimeError("PairSelector requires a REST client for refresh.")

        # ── Step 1: Discover active symbols ─────────────────────────────
        all_symbols = await self._fetch_all_symbols()
        if len(all_symbols) < self._min_symbols:
            self._log.warning(
                "agent.pair_selector.too_few_symbols",
                count=len(all_symbols),
                threshold=self._min_symbols,
            )
            raise RuntimeError(
                f"Too few symbols from platform ({len(all_symbols)} < {self._min_symbols}); "
                "platform cache may not be warm yet."
            )

        # ── Step 2: Fetch ticker data in batches ─────────────────────────
        pair_infos = await self._fetch_ticker_batches(all_symbols)
        total_scanned = len(pair_infos)

        # ── Step 3: Apply filters ────────────────────────────────────────
        filtered = [p for p in pair_infos if self._passes_filter(p)]
        total_passed = len(filtered)

        self._log.debug(
            "agent.pair_selector.filter_applied",
            scanned=total_scanned,
            passed=total_passed,
            rejected=total_scanned - total_passed,
        )

        if not filtered:
            self._log.warning(
                "agent.pair_selector.no_pairs_after_filter",
                min_volume=str(self._min_volume),
                max_spread=str(self._max_spread),
            )
            return SelectedPairs(
                volume_ranked=list(self._config.symbols),
                momentum_tier=[],
                all_symbols=list(self._config.symbols),
                refreshed_at=time.monotonic(),
                total_scanned=total_scanned,
                total_passed_filter=0,
            )

        # ── Step 4: Volume tier ──────────────────────────────────────────
        by_volume = sorted(filtered, key=lambda p: p.quote_volume, reverse=True)
        volume_ranked = [p.symbol for p in by_volume[: self._top_n]]

        # ── Step 5: Momentum tier ────────────────────────────────────────
        by_abs_change = sorted(filtered, key=lambda p: abs(p.change_pct), reverse=True)
        momentum_tier = [p.symbol for p in by_abs_change[: self._momentum_n]]

        # ── Step 6: Merge (volume_ranked first, then unique momentum) ─────
        seen: set[str] = set(volume_ranked)
        extra_momentum: list[str] = [s for s in momentum_tier if s not in seen]
        all_symbols_merged = volume_ranked + extra_momentum

        return SelectedPairs(
            volume_ranked=volume_ranked,
            momentum_tier=momentum_tier,
            all_symbols=all_symbols_merged,
            refreshed_at=time.monotonic(),
            total_scanned=total_scanned,
            total_passed_filter=total_passed,
        )

    # ------------------------------------------------------------------
    # Platform API helpers
    # ------------------------------------------------------------------

    async def _fetch_all_symbols(self) -> list[str]:
        """Fetch the list of all active trading pair symbols from the platform.

        Uses ``GET /api/v1/market/prices`` (no auth required) which returns a
        ``{symbol: price}`` map for every pair the platform has a price for.

        Returns:
            List of uppercase symbol strings.  Empty list on error.
        """
        assert self._rest is not None  # guarded by caller
        try:
            resp = await self._rest.get("/api/v1/market/prices")
            resp.raise_for_status()
            body = resp.json()
            prices: dict[str, Any] = body.get("prices", body) if isinstance(body, dict) else {}
            return [sym.upper() for sym in prices if sym]
        except httpx.HTTPStatusError as exc:
            self._log.warning(
                "agent.pair_selector.fetch_symbols.http_error",
                status=exc.response.status_code,
                error=str(exc),
            )
            return []
        except httpx.RequestError as exc:
            self._log.warning(
                "agent.pair_selector.fetch_symbols.request_error",
                error=str(exc),
            )
            return []

    async def _fetch_ticker_batches(self, symbols: list[str]) -> list[PairInfo]:
        """Fetch 24h ticker data for all *symbols* in parallel batches.

        Splits *symbols* into chunks of :data:`_TICKER_BATCH_SIZE` and runs all
        batch requests concurrently with ``asyncio.gather``.

        Args:
            symbols: Full list of symbol strings to fetch tickers for.

        Returns:
            List of :class:`PairInfo` for every symbol that returned valid
            ticker data.  Symbols whose ticker fetch failed are silently omitted.
        """
        batches = [
            symbols[i : i + _TICKER_BATCH_SIZE]
            for i in range(0, len(symbols), _TICKER_BATCH_SIZE)
        ]

        batch_results = await asyncio.gather(
            *[self._fetch_ticker_batch(batch) for batch in batches],
            return_exceptions=True,
        )

        pair_infos: list[PairInfo] = []
        for result in batch_results:
            if isinstance(result, Exception):
                self._log.warning(
                    "agent.pair_selector.fetch_batch.gather_error",
                    error=str(result),
                )
                continue
            pair_infos.extend(result)

        return pair_infos

    async def _fetch_ticker_batch(self, symbols: list[str]) -> list[PairInfo]:
        """Fetch ticker data for a single batch of symbols.

        Args:
            symbols: Up to :data:`_TICKER_BATCH_SIZE` symbols.

        Returns:
            List of :class:`PairInfo` for symbols with available ticker data.
            Symbols missing from the response are silently omitted.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
            httpx.RequestError:    On transport failure.
        """
        assert self._rest is not None  # guarded by caller
        symbols_param = ",".join(symbols)
        try:
            resp = await self._rest.get(
                "/api/v1/market/tickers",
                params={"symbols": symbols_param},
            )
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPStatusError as exc:
            self._log.warning(
                "agent.pair_selector.fetch_batch.http_error",
                symbols_count=len(symbols),
                status=exc.response.status_code,
                error=str(exc),
            )
            return []
        except httpx.RequestError as exc:
            self._log.warning(
                "agent.pair_selector.fetch_batch.request_error",
                symbols_count=len(symbols),
                error=str(exc),
            )
            return []

        # The /market/tickers endpoint returns {"tickers": {symbol: {...}}, "count": N, ...}
        tickers_map: dict[str, Any] = body.get("tickers", {}) if isinstance(body, dict) else {}
        pair_infos: list[PairInfo] = []

        for sym, ticker in tickers_map.items():
            info = self._parse_ticker(sym.upper(), ticker)
            if info is not None:
                pair_infos.append(info)

        return pair_infos

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_ticker(self, symbol: str, ticker: dict[str, Any]) -> PairInfo | None:
        """Parse a raw ticker dict into a :class:`PairInfo`.

        Handles missing or malformed fields gracefully by returning ``None``.

        Args:
            symbol: Uppercase symbol string.
            ticker: Raw ticker dict from the platform response.

        Returns:
            A populated :class:`PairInfo`, or ``None`` if the data is unusable.
        """
        try:
            close = _to_decimal(ticker.get("close") or ticker.get("price"))
            high = _to_decimal(ticker.get("high"))
            low = _to_decimal(ticker.get("low"))
            quote_volume = _to_decimal(ticker.get("quote_volume") or ticker.get("volume_usdt"))
            change_pct = _to_decimal(ticker.get("change_pct") or "0")

            if close is None or close <= Decimal("0"):
                return None
            if quote_volume is None or quote_volume < Decimal("0"):
                return None

            # Compute synthetic spread from high−low.  When high/low are absent
            # we use spread=0 (treat as narrow enough to pass the filter).
            if high is not None and low is not None and close > Decimal("0"):
                spread_pct = (high - low) / close
            else:
                spread_pct = Decimal("0")

            return PairInfo(
                symbol=symbol,
                quote_volume=quote_volume,
                change_pct=change_pct if change_pct is not None else Decimal("0"),
                spread_pct=spread_pct,
                close=close,
            )
        except (InvalidOperation, ZeroDivisionError, KeyError, TypeError):
            self._log.debug(
                "agent.pair_selector.parse_ticker.failed",
                symbol=symbol,
            )
            return None

    def _passes_filter(self, pair: PairInfo) -> bool:
        """Return True when *pair* passes all configured filters.

        Filters applied (in order):
          1. Quote-volume ≥ :attr:`_min_volume` (at least $10 M by default).
          2. Spread ≤ :attr:`_max_spread` (at most 5% by default).

        Args:
            pair: :class:`PairInfo` to evaluate.

        Returns:
            ``True`` if *pair* passes all filters; ``False`` to reject it.
        """
        if pair.quote_volume < self._min_volume:
            return False
        if pair.spread_pct > self._max_spread:
            return False
        return True

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _fallback_result(self) -> SelectedPairs:
        """Build a minimal :class:`SelectedPairs` using config symbols.

        Called when no REST client is configured or when the refresh pipeline
        fails completely.  Returns the agent's pre-configured default symbols
        without any volume or momentum metadata.

        Returns:
            :class:`SelectedPairs` with ``config.symbols`` as both
            ``volume_ranked`` and ``all_symbols``; ``momentum_tier`` is empty.
        """
        default = list(self._config.symbols)
        return SelectedPairs(
            volume_ranked=default,
            momentum_tier=[],
            all_symbols=default,
            refreshed_at=time.monotonic(),
            total_scanned=0,
            total_passed_filter=0,
        )


# ── Internal decimal helper ────────────────────────────────────────────────────


def _to_decimal(value: Any) -> Decimal | None:  # noqa: ANN401
    """Convert *value* to :class:`~decimal.Decimal`, or return ``None``.

    Accepts strings, ints, floats, and existing :class:`~decimal.Decimal`
    instances.  Returns ``None`` for ``None``, empty strings, or values that
    cannot be parsed.

    Args:
        value: Raw value from a JSON response field.

    Returns:
        A :class:`~decimal.Decimal` on success, ``None`` otherwise.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
