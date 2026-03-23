"""Unit tests for agent/trading/pair_selector.py :: PairSelector.

Tests cover:
- get_active_pairs() — cache hit returns existing result without HTTP call
- get_active_pairs() — cache miss triggers refresh
- get_active_pairs() — concurrent callers share a single refresh (lock)
- get_active_pairs() — fallback to config symbols when REST client is None
- get_active_pairs() — fallback to config symbols when platform has < MIN symbols
- get_active_pairs() — fallback to config symbols on HTTP error
- get_active_pairs() — fallback to stale cache on refresh failure
- invalidate()       — forces next call to refresh
- cached_result      — returns None before first refresh, SelectedPairs after
- _passes_filter()   — rejects below-volume pairs
- _passes_filter()   — rejects above-spread pairs
- _passes_filter()   — accepts pairs that meet both thresholds
- _parse_ticker()    — returns None on None close
- _parse_ticker()    — returns None on zero close
- _parse_ticker()    — returns None on missing quote_volume
- _parse_ticker()    — computes spread_pct from high/low/close
- _parse_ticker()    — uses zero spread when high/low absent
- _parse_ticker()    — handles change_pct fallback to "0"
- _fetch_ticker_batches() — splits into batches of ≤ _TICKER_BATCH_SIZE
- volume ranking    — top-N by quote_volume (descending)
- momentum tier     — top-M by absolute change_pct
- all_symbols       — volume_ranked first, then unique momentum additions
- SelectedPairs.is_stale() — returns False within TTL
- SelectedPairs.is_stale() — returns True after TTL
- _to_decimal()     — converts str / int / float / Decimal
- _to_decimal()     — returns None for None or unparseable
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from agent.config import AgentConfig
from agent.trading.pair_selector import (
    MIN_QUOTE_VOLUME_USD,
    TOP_N_PAIRS,
    PairInfo,
    PairSelector,
    SelectedPairs,
    _to_decimal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    """Build a minimal AgentConfig without reading agent/.env."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-pair-selector")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _prices_response(symbols: list[str]) -> dict:
    """Build a /market/prices response dict for the given symbols."""
    return {
        "prices": {sym: "100.0" for sym in symbols},
        "count": len(symbols),
        "stale": False,
        "data_age_seconds": 0,
        "timestamp": "2026-03-22T00:00:00Z",
    }


def _ticker_entry(
    *,
    quote_volume: str = "50000000",
    change_pct: str = "0.02",
    close: str = "100.0",
    high: str = "102.0",
    low: str = "98.5",
) -> dict:
    """Build a single ticker dict as the platform returns it."""
    return {
        "close": close,
        "high": high,
        "low": low,
        "volume": "500000",
        "quote_volume": quote_volume,
        "change_pct": change_pct,
        "trade_count": 0,
        "open": "98.0",
        "change": "2.0",
        "timestamp": "2026-03-22T00:00:00Z",
    }


def _tickers_response(symbols: list[str], **ticker_kwargs: str) -> dict:
    """Build a /market/tickers response dict for the given symbols."""
    return {
        "tickers": {sym: _ticker_entry(**ticker_kwargs) for sym in symbols},  # type: ignore[arg-type]
        "count": len(symbols),
        "timestamp": "2026-03-22T00:00:00Z",
    }


def _mock_rest(
    prices_body: dict,
    tickers_body: dict,
    prices_status: int = 200,
    tickers_status: int = 200,
) -> AsyncMock:
    """Build a mock httpx.AsyncClient that returns preset responses."""
    rest = AsyncMock(spec=httpx.AsyncClient)

    def _make_response(body: dict, status: int) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status
        resp.json.return_value = body
        if status >= 400:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                message=f"HTTP {status}",
                request=MagicMock(),
                response=resp,
            )
        else:
            resp.raise_for_status.return_value = None
        return resp

    prices_resp = _make_response(prices_body, prices_status)
    tickers_resp = _make_response(tickers_body, tickers_status)

    async def _get(url: str, **_kwargs: object) -> MagicMock:
        if "tickers" in url and "ticker/" not in url:
            return tickers_resp
        return prices_resp

    rest.get.side_effect = _get
    return rest


# ── Symbols used in the bulk of tests ──────────────────────────────────────────
_SYMS = [f"COIN{i}USDT" for i in range(10)]


# ---------------------------------------------------------------------------
# SelectedPairs — staleness
# ---------------------------------------------------------------------------


class TestSelectedPairsIsStale:
    def test_fresh_within_ttl(self) -> None:
        sp = SelectedPairs(refreshed_at=time.monotonic())
        assert not sp.is_stale(ttl_seconds=3600.0)

    def test_stale_after_ttl(self) -> None:
        sp = SelectedPairs(refreshed_at=time.monotonic() - 7200.0)
        assert sp.is_stale(ttl_seconds=3600.0)

    def test_exactly_at_boundary(self) -> None:
        # At exactly TTL it should be stale (>=).
        sp = SelectedPairs(refreshed_at=time.monotonic() - 3600.0)
        assert sp.is_stale(ttl_seconds=3600.0)


# ---------------------------------------------------------------------------
# _to_decimal
# ---------------------------------------------------------------------------


class TestToDecimal:
    def test_string(self) -> None:
        assert _to_decimal("123.456") == Decimal("123.456")

    def test_int(self) -> None:
        assert _to_decimal(42) == Decimal("42")

    def test_float(self) -> None:
        result = _to_decimal(1.5)
        assert result is not None
        assert abs(result - Decimal("1.5")) < Decimal("0.001")

    def test_decimal_passthrough(self) -> None:
        d = Decimal("99.99")
        assert _to_decimal(d) == d

    def test_none_returns_none(self) -> None:
        assert _to_decimal(None) is None

    def test_empty_string_returns_none(self) -> None:
        # "".strip() is empty; Decimal("") raises InvalidOperation
        assert _to_decimal("") is None

    def test_unparseable_returns_none(self) -> None:
        assert _to_decimal("not-a-number") is None


# ---------------------------------------------------------------------------
# PairInfo / _passes_filter
# ---------------------------------------------------------------------------

def _make_pair(
    symbol: str = "BTCUSDT",
    quote_volume: str = "50000000",
    change_pct: str = "0.02",
    spread_pct: str = "0.01",
    close: str = "100.0",
) -> PairInfo:
    return PairInfo(
        symbol=symbol,
        quote_volume=Decimal(quote_volume),
        change_pct=Decimal(change_pct),
        spread_pct=Decimal(spread_pct),
        close=Decimal(close),
    )


class TestPassesFilter:
    def setup_method(self) -> None:
        self._selector = PairSelector.__new__(PairSelector)
        self._selector._min_volume = MIN_QUOTE_VOLUME_USD  # $10 M
        self._selector._max_spread = Decimal("0.05")

    def test_passes_both_filters(self) -> None:
        pair = _make_pair(quote_volume="20000000", spread_pct="0.02")
        assert self._selector._passes_filter(pair)

    def test_fails_volume_filter(self) -> None:
        pair = _make_pair(quote_volume="5000000", spread_pct="0.01")
        assert not self._selector._passes_filter(pair)

    def test_fails_spread_filter(self) -> None:
        pair = _make_pair(quote_volume="20000000", spread_pct="0.06")
        assert not self._selector._passes_filter(pair)

    def test_fails_both_filters(self) -> None:
        pair = _make_pair(quote_volume="1000000", spread_pct="0.10")
        assert not self._selector._passes_filter(pair)

    def test_exactly_at_volume_threshold(self) -> None:
        # Exactly at threshold should pass (>=).
        pair = _make_pair(quote_volume=str(MIN_QUOTE_VOLUME_USD), spread_pct="0.01")
        assert self._selector._passes_filter(pair)

    def test_exactly_at_spread_threshold(self) -> None:
        # Exactly at spread threshold should pass (<=).
        pair = _make_pair(quote_volume="20000000", spread_pct="0.05")
        assert self._selector._passes_filter(pair)


# ---------------------------------------------------------------------------
# _parse_ticker
# ---------------------------------------------------------------------------


class TestParseTicker:
    def setup_method(self) -> None:
        self._selector = PairSelector.__new__(PairSelector)
        # Inject minimal logger stub.
        self._selector._log = MagicMock()

    def test_valid_ticker(self) -> None:
        entry = _ticker_entry(close="100.0", high="105.0", low="95.0")
        info = self._selector._parse_ticker("BTCUSDT", entry)
        assert info is not None
        assert info.symbol == "BTCUSDT"
        assert info.close == Decimal("100.0")
        assert info.quote_volume == Decimal("50000000")
        assert info.change_pct == Decimal("0.02")

    def test_spread_computed_from_high_low(self) -> None:
        # spread = (105 - 95) / 100 = 0.10
        entry = _ticker_entry(close="100.0", high="105.0", low="95.0")
        info = self._selector._parse_ticker("BTCUSDT", entry)
        assert info is not None
        assert abs(info.spread_pct - Decimal("0.10")) < Decimal("0.0001")

    def test_zero_spread_when_high_low_absent(self) -> None:
        entry = {
            "close": "100.0",
            "quote_volume": "50000000",
            "change_pct": "0.02",
            # no high / no low
        }
        info = self._selector._parse_ticker("BTCUSDT", entry)
        assert info is not None
        assert info.spread_pct == Decimal("0")

    def test_none_close_returns_none(self) -> None:
        entry = _ticker_entry()
        entry["close"] = None
        assert self._selector._parse_ticker("BTCUSDT", entry) is None

    def test_zero_close_returns_none(self) -> None:
        entry = _ticker_entry(close="0")
        assert self._selector._parse_ticker("BTCUSDT", entry) is None

    def test_none_quote_volume_returns_none(self) -> None:
        entry = _ticker_entry()
        entry["quote_volume"] = None
        assert self._selector._parse_ticker("BTCUSDT", entry) is None

    def test_change_pct_defaults_to_zero_when_absent(self) -> None:
        entry = {
            "close": "100.0",
            "high": "105.0",
            "low": "95.0",
            "quote_volume": "50000000",
            # no change_pct key
        }
        info = self._selector._parse_ticker("BTCUSDT", entry)
        assert info is not None
        assert info.change_pct == Decimal("0")

    def test_unparseable_value_returns_none(self) -> None:
        entry = _ticker_entry(close="not-a-price")
        assert self._selector._parse_ticker("BTCUSDT", entry) is None


# ---------------------------------------------------------------------------
# PairSelector — cache behaviour
# ---------------------------------------------------------------------------


class TestCacheBehaviour:
    def test_cached_result_none_before_first_refresh(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        selector = PairSelector(config=config, rest_client=None)
        assert selector.cached_result is None

    async def test_get_active_pairs_sets_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body=_tickers_response(_SYMS),
        )
        selector = PairSelector(config=config, rest_client=rest, ttl_seconds=3600.0)
        result = await selector.get_active_pairs()
        assert selector.cached_result is result

    async def test_cache_hit_skips_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body=_tickers_response(_SYMS),
        )
        selector = PairSelector(config=config, rest_client=rest, ttl_seconds=3600.0)

        first = await selector.get_active_pairs()
        # Reset call count so we can verify no new calls are made.
        rest.get.reset_mock()
        second = await selector.get_active_pairs()

        assert second is first  # same object returned from cache
        rest.get.assert_not_called()

    async def test_invalidate_forces_refresh(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body=_tickers_response(_SYMS),
        )
        selector = PairSelector(config=config, rest_client=rest, ttl_seconds=3600.0)

        first = await selector.get_active_pairs()
        selector.invalidate()
        assert selector.cached_result is None

        rest.get.reset_mock()
        second = await selector.get_active_pairs()
        # A new refresh must have been issued.
        assert rest.get.called
        # The result should be a fresh SelectedPairs (different object).
        assert second is not first

    async def test_stale_cache_triggers_refresh(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body=_tickers_response(_SYMS),
        )
        selector = PairSelector(config=config, rest_client=rest, ttl_seconds=0.0)
        # TTL=0 means every call is stale.
        await selector.get_active_pairs()
        rest.get.reset_mock()
        await selector.get_active_pairs()
        assert rest.get.called


# ---------------------------------------------------------------------------
# PairSelector — fallback behaviour
# ---------------------------------------------------------------------------


class TestFallbackBehaviour:
    async def test_no_rest_client_returns_config_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        selector = PairSelector(config=config, rest_client=None)
        result = await selector.get_active_pairs()
        assert result.all_symbols == list(config.symbols)
        assert result.momentum_tier == []

    async def test_http_error_on_prices_returns_config_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        rest = _mock_rest(
            prices_body={},
            tickers_body={},
            prices_status=503,
        )
        selector = PairSelector(config=config, rest_client=rest)
        result = await selector.get_active_pairs()
        assert result.all_symbols == list(config.symbols)

    async def test_too_few_symbols_returns_config_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        # Only 3 symbols — below _MIN_SYMBOLS_THRESHOLD=5.
        rest = _mock_rest(
            prices_body=_prices_response(["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
            tickers_body=_tickers_response(["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
        )
        selector = PairSelector(config=config, rest_client=rest)
        result = await selector.get_active_pairs()
        assert result.all_symbols == list(config.symbols)

    async def test_all_pairs_filtered_returns_config_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        # All pairs have $0 quote_volume — all fail the volume filter.
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body=_tickers_response(_SYMS, quote_volume="0"),
        )
        selector = PairSelector(config=config, rest_client=rest)
        result = await selector.get_active_pairs()
        assert result.all_symbols == list(config.symbols)

    async def test_stale_cache_kept_on_refresh_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body=_tickers_response(_SYMS),
        )
        selector = PairSelector(config=config, rest_client=rest, ttl_seconds=3600.0)
        first = await selector.get_active_pairs()
        first_symbols = list(first.all_symbols)

        # Mark cache as stale by backdating refreshed_at — do NOT invalidate
        # (invalidate clears _cache to None, which loses the stale reference).
        stale = SelectedPairs(
            volume_ranked=first.volume_ranked,
            momentum_tier=first.momentum_tier,
            all_symbols=first.all_symbols,
            refreshed_at=time.monotonic() - 7200.0,  # 2h ago — definitely stale
            total_scanned=first.total_scanned,
            total_passed_filter=first.total_passed_filter,
        )
        selector._cache = stale

        # Simulate REST failure on the forced refresh.
        async def _fail(*_args: object, **_kwargs: object) -> None:
            raise httpx.RequestError("network down")

        rest.get.side_effect = _fail
        second = await selector.get_active_pairs()

        # Stale cache is preserved when refresh fails.
        assert second.all_symbols == first_symbols


# ---------------------------------------------------------------------------
# PairSelector — ranking
# ---------------------------------------------------------------------------


class TestRanking:
    async def test_volume_ranked_descending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        symbols = [f"COIN{i}USDT" for i in range(6)]
        # Assign ascending volumes so COIN5 has the most volume (index 5 → 6*20M=120M).
        tickers: dict = {
            sym: _ticker_entry(quote_volume=str((i + 1) * 20_000_000))
            for i, sym in enumerate(symbols)
        }
        rest = _mock_rest(
            prices_body=_prices_response(symbols),
            tickers_body={"tickers": tickers, "count": len(tickers), "timestamp": ""},
        )
        selector = PairSelector(
            config=config,
            rest_client=rest,
            top_n_pairs=6,
            momentum_n_pairs=2,
        )
        result = await selector.get_active_pairs()
        # COIN5 has highest volume (index 0) → COIN0 has lowest.
        assert result.volume_ranked[0] == "COIN5USDT"
        assert result.volume_ranked[-1] == "COIN0USDT"

    async def test_momentum_tier_by_absolute_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        # 4 pairs: two big gainers, two small movers.
        tickers: dict = {
            "HIGHPOSUSDT": _ticker_entry(quote_volume="50000000", change_pct="0.15"),
            "HIGHNEGUSDT": _ticker_entry(quote_volume="50000000", change_pct="-0.12"),
            "SMALLAUSDT": _ticker_entry(quote_volume="50000000", change_pct="0.01"),
            "SMALLBUSDT": _ticker_entry(quote_volume="50000000", change_pct="-0.005"),
        }
        symbols = list(tickers.keys())
        rest = _mock_rest(
            prices_body=_prices_response(symbols),
            tickers_body={"tickers": tickers, "count": len(tickers), "timestamp": ""},
        )
        selector = PairSelector(
            config=config,
            rest_client=rest,
            top_n_pairs=4,
            momentum_n_pairs=2,
            min_symbols_threshold=1,
        )
        result = await selector.get_active_pairs()
        # Momentum tier must contain the biggest movers by absolute change.
        assert "HIGHPOSUSDT" in result.momentum_tier
        assert "HIGHNEGUSDT" in result.momentum_tier

    async def test_all_symbols_volume_first_then_unique_momentum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        # 4 pairs: top 2 by volume, top 2 momentum.
        # MOMENONLY has high change but low volume (not in top_n_pairs=2 volume list).
        tickers: dict = {
            "HIGVOL1USDT": _ticker_entry(quote_volume="100000000", change_pct="0.01"),
            "HIGVOL2USDT": _ticker_entry(quote_volume="80000000", change_pct="0.01"),
            "MOMENONLYUSDT": _ticker_entry(quote_volume="15000000", change_pct="0.20"),
            "LOWALLOUSDT": _ticker_entry(quote_volume="12000000", change_pct="0.005"),
        }
        symbols = list(tickers.keys())
        rest = _mock_rest(
            prices_body=_prices_response(symbols),
            tickers_body={"tickers": tickers, "count": len(tickers), "timestamp": ""},
        )
        selector = PairSelector(
            config=config,
            rest_client=rest,
            top_n_pairs=2,           # only HIGVOL1 + HIGVOL2 in volume tier
            momentum_n_pairs=1,      # only MOMENONLY in momentum tier
            min_symbols_threshold=1,
        )
        result = await selector.get_active_pairs()
        # all_symbols = volume_ranked + unique momentum additions
        assert result.all_symbols[:2] == result.volume_ranked[:2]
        assert "MOMENONLYUSDT" in result.all_symbols
        assert len(result.all_symbols) == 3  # 2 volume + 1 unique momentum

    async def test_no_duplicate_in_all_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        # All pairs have identical high change_pct so they are in BOTH tiers.
        tickers: dict = {sym: _ticker_entry(change_pct="0.20") for sym in _SYMS}
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body={"tickers": tickers, "count": len(tickers), "timestamp": ""},
        )
        selector = PairSelector(
            config=config,
            rest_client=rest,
            top_n_pairs=5,
            momentum_n_pairs=5,
        )
        result = await selector.get_active_pairs()
        assert len(result.all_symbols) == len(set(result.all_symbols))


# ---------------------------------------------------------------------------
# PairSelector — batch splitting
# ---------------------------------------------------------------------------


class TestBatchSplitting:
    async def test_large_symbol_list_batched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        # 150 symbols → should need 2 batch requests (100 + 50).
        syms = [f"COIN{i:03d}USDT" for i in range(150)]
        call_count = 0

        async def _get(url: str, **kwargs: object) -> MagicMock:
            nonlocal call_count
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.raise_for_status.return_value = None
            if "tickers" in url and "ticker/" not in url:
                call_count += 1
                # Extract the symbols from params.
                params = kwargs.get("params", {})
                assert isinstance(params, dict)
                batch = [s for s in params.get("symbols", "").split(",") if s]
                resp.json.return_value = _tickers_response(batch)
            else:
                resp.json.return_value = _prices_response(syms)
            return resp

        rest = AsyncMock(spec=httpx.AsyncClient)
        rest.get.side_effect = _get
        selector = PairSelector(config=config, rest_client=rest, top_n_pairs=10)
        await selector.get_active_pairs()
        assert call_count == 2  # ceil(150 / 100) = 2


# ---------------------------------------------------------------------------
# PairSelector — concurrency (lock)
# ---------------------------------------------------------------------------


class TestConcurrentRefresh:
    async def test_concurrent_callers_share_single_refresh(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        prices_call_count = 0

        async def _get(url: str, **kwargs: object) -> MagicMock:
            nonlocal prices_call_count
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.raise_for_status.return_value = None
            if "tickers" in url and "ticker/" not in url:
                resp.json.return_value = _tickers_response(_SYMS)
            else:
                prices_call_count += 1
                # Add a tiny yield so coroutines interleave.
                await asyncio.sleep(0)
                resp.json.return_value = _prices_response(_SYMS)
            return resp

        rest = AsyncMock(spec=httpx.AsyncClient)
        rest.get.side_effect = _get
        selector = PairSelector(config=config, rest_client=rest, ttl_seconds=3600.0)

        results = await asyncio.gather(
            selector.get_active_pairs(),
            selector.get_active_pairs(),
            selector.get_active_pairs(),
        )
        # All three callers get the same SelectedPairs object.
        assert results[0] is results[1] is results[2]
        # The prices endpoint should have been called exactly once.
        assert prices_call_count == 1


# ---------------------------------------------------------------------------
# Integration: get_active_pairs() happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_returns_selected_pairs_with_all_tiers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body=_tickers_response(_SYMS),
        )
        selector = PairSelector(config=config, rest_client=rest)
        result = await selector.get_active_pairs()

        assert isinstance(result, SelectedPairs)
        assert len(result.volume_ranked) <= TOP_N_PAIRS
        assert isinstance(result.momentum_tier, list)
        assert isinstance(result.all_symbols, list)
        assert result.total_scanned > 0
        assert result.total_passed_filter > 0

    async def test_metadata_counts_correct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _make_config(monkeypatch)
        # 10 symbols, all passing.
        rest = _mock_rest(
            prices_body=_prices_response(_SYMS),
            tickers_body=_tickers_response(_SYMS),
        )
        selector = PairSelector(config=config, rest_client=rest)
        result = await selector.get_active_pairs()
        assert result.total_scanned == len(_SYMS)
        assert result.total_passed_filter == len(_SYMS)
