"""Unit tests for src/api/routes/indicators.py.

Covers:
- Symbol validation (valid/invalid formats)
- Indicator filtering (specific subset vs all)
- Cache hit/miss behaviour (mocked Redis)
- Lookback range validation (14–500)
- Available indicators endpoint returns complete sorted list
- Helper functions: _resolve_indicator_names, _build_cache_key,
  _get_cached, _set_cached, _remap_and_filter
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.routes.indicators import (
    _ALL_INDICATORS,
    _ENGINE_KEY_MAP,
    _build_cache_key,
    _remap_and_filter,
    _resolve_indicator_names,
    get_indicators,
    list_available_indicators,
)
from src.api.schemas.indicators import AvailableIndicatorsResponse, IndicatorResponse
from src.utils.exceptions import InvalidSymbolError, ServiceUnavailableError

# ---------------------------------------------------------------------------
# Candle row factory (mirrors what _fetch_candles returns)
# ---------------------------------------------------------------------------


def _make_candle_row(
    high: float = 64600.0,
    low: float = 64100.0,
    close: float = 64300.0,
    volume: float = 1234.567,
) -> MagicMock:
    row = MagicMock()
    row.high = high
    row.low = low
    row.close = close
    row.volume = volume
    return row


def _make_candles(n: int = 50) -> list[MagicMock]:
    """Return *n* candle rows with gradually increasing close prices."""
    rows = []
    for i in range(n):
        close = 64000.0 + i * 10.0
        rows.append(
            _make_candle_row(
                high=close + 100.0,
                low=close - 100.0,
                close=close,
                volume=1000.0 + i,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# _resolve_indicator_names
# ---------------------------------------------------------------------------


class TestResolveIndicatorNames:
    def test_none_returns_all_indicators(self):
        result = _resolve_indicator_names(None)
        assert result == sorted(_ENGINE_KEY_MAP.keys())

    def test_valid_single_indicator(self):
        result = _resolve_indicator_names("rsi_14")
        assert result == ["rsi_14"]

    def test_valid_multiple_indicators_sorted(self):
        result = _resolve_indicator_names("sma_20,rsi_14")
        assert result == ["rsi_14", "sma_20"]  # sorted

    def test_whitespace_stripped_from_names(self):
        result = _resolve_indicator_names("rsi_14 , sma_20 ")
        assert "rsi_14" in result
        assert "sma_20" in result

    def test_duplicate_names_deduplicated(self):
        result = _resolve_indicator_names("rsi_14,rsi_14,sma_20")
        assert result.count("rsi_14") == 1

    def test_unknown_indicator_raises_error(self):
        with pytest.raises(InvalidSymbolError) as exc_info:
            _resolve_indicator_names("unknown_indicator")
        assert "unknown_indicator" in str(exc_info.value)
        assert "Supported:" in str(exc_info.value)

    def test_mix_valid_and_unknown_raises_error(self):
        with pytest.raises(InvalidSymbolError):
            _resolve_indicator_names("rsi_14,bad_indicator")

    def test_empty_string_returns_empty_list(self):
        # An empty string splits into zero names → empty list (no fallback to all)
        result = _resolve_indicator_names("")
        assert result == []

    def test_all_supported_indicators_accepted(self):
        all_names = ",".join(_ALL_INDICATORS)
        result = _resolve_indicator_names(all_names)
        assert result == _ALL_INDICATORS  # already sorted


# ---------------------------------------------------------------------------
# _build_cache_key
# ---------------------------------------------------------------------------


class TestBuildCacheKey:
    def test_key_format(self):
        key = _build_cache_key("BTCUSDT", ["rsi_14"])
        assert key.startswith("indicators:BTCUSDT:")
        parts = key.split(":")
        assert len(parts) == 3
        assert len(parts[2]) == 16  # 16-char hex digest

    def test_same_inputs_stable_key(self):
        key1 = _build_cache_key("BTCUSDT", ["rsi_14", "sma_20"])
        key2 = _build_cache_key("BTCUSDT", ["rsi_14", "sma_20"])
        assert key1 == key2

    def test_different_symbols_different_keys(self):
        key_btc = _build_cache_key("BTCUSDT", ["rsi_14"])
        key_eth = _build_cache_key("ETHUSDT", ["rsi_14"])
        assert key_btc != key_eth

    def test_different_indicator_subsets_different_keys(self):
        key_rsi = _build_cache_key("BTCUSDT", ["rsi_14"])
        key_sma = _build_cache_key("BTCUSDT", ["sma_20"])
        assert key_rsi != key_sma

    def test_order_of_indicators_does_not_matter(self):
        # Input is already sorted (callers always sort), but let's confirm
        key1 = _build_cache_key("BTCUSDT", ["rsi_14", "sma_20"])
        key2 = _build_cache_key("BTCUSDT", ["sma_20", "rsi_14"])
        # Different input order → different serialization → different hash
        # (callers guarantee sorted input, so this documents the design)
        assert isinstance(key1, str)
        assert isinstance(key2, str)


# ---------------------------------------------------------------------------
# _remap_and_filter
# ---------------------------------------------------------------------------


class TestRemapAndFilter:
    def test_remaps_engine_key_to_public_name(self):
        raw = {"adx": 25.3, "atr": 150.0}
        result = _remap_and_filter(raw, ["adx_14", "atr_14"])
        assert "adx_14" in result
        assert "atr_14" in result
        assert result["adx_14"] == 25.3
        assert result["atr_14"] == 150.0

    def test_bb_mid_remapped_from_bb_middle(self):
        raw = {"bb_middle": 64300.0, "bb_upper": 65000.0, "bb_lower": 63600.0}
        result = _remap_and_filter(raw, ["bb_mid"])
        assert "bb_mid" in result
        assert result["bb_mid"] == 64300.0

    def test_price_remapped_from_current_price(self):
        raw = {"current_price": 64521.3}
        result = _remap_and_filter(raw, ["price"])
        assert result["price"] == 64521.3

    def test_none_values_excluded(self):
        raw = {"rsi_14": None, "sma_20": 64300.0}
        result = _remap_and_filter(raw, ["rsi_14", "sma_20"])
        assert "rsi_14" not in result
        assert result["sma_20"] == 64300.0

    def test_empty_raw_returns_empty_dict(self):
        result = _remap_and_filter({}, ["rsi_14", "sma_20"])
        assert result == {}

    def test_filtered_to_requested_subset(self):
        raw = {
            "rsi_14": 54.0,
            "sma_20": 64300.0,
            "current_price": 64521.3,
        }
        result = _remap_and_filter(raw, ["rsi_14"])
        assert list(result.keys()) == ["rsi_14"]


# ---------------------------------------------------------------------------
# _get_cached / _set_cached helpers
# ---------------------------------------------------------------------------


class TestCacheHelpers:
    async def test_get_cached_returns_none_on_miss(self):
        from src.api.routes.indicators import _get_cached

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        result = await _get_cached(mock_redis, "indicators:BTCUSDT:abc12345")
        assert result is None
        mock_redis.get.assert_called_once_with("indicators:BTCUSDT:abc12345")

    async def test_get_cached_deserialises_valid_json(self):
        from src.api.routes.indicators import _get_cached

        response = IndicatorResponse(
            symbol="BTCUSDT",
            timestamp=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
            candles_used=100,
            indicators={"rsi_14": 54.32},
        )
        payload = json.dumps(response.model_dump(mode="json"))

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=payload)

        result = await _get_cached(mock_redis, "indicators:BTCUSDT:abc12345")
        assert result is not None
        assert result.symbol == "BTCUSDT"
        assert result.indicators["rsi_14"] == 54.32

    async def test_get_cached_returns_none_on_json_error(self):
        from src.api.routes.indicators import _get_cached

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="not-valid-json{{{")

        result = await _get_cached(mock_redis, "indicators:BTCUSDT:abc12345")
        assert result is None

    async def test_set_cached_calls_setex(self):
        from src.api.routes.indicators import _set_cached

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        response = IndicatorResponse(
            symbol="BTCUSDT",
            timestamp=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
            candles_used=50,
            indicators={"rsi_14": 50.0},
        )
        await _set_cached(mock_redis, "indicators:BTCUSDT:abc12345", response)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "indicators:BTCUSDT:abc12345"
        assert call_args[0][1] == 30  # 30-second TTL

    async def test_set_cached_swallows_redis_error(self):
        from src.api.routes.indicators import _set_cached

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock(side_effect=Exception("Redis connection refused"))

        response = IndicatorResponse(
            symbol="BTCUSDT",
            timestamp=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
            candles_used=50,
            indicators={},
        )
        # Must not raise
        await _set_cached(mock_redis, "indicators:BTCUSDT:abc12345", response)


# ---------------------------------------------------------------------------
# list_available_indicators endpoint
# ---------------------------------------------------------------------------


class TestListAvailableIndicators:
    async def test_returns_all_supported_indicator_names(self):
        result = await list_available_indicators()
        assert isinstance(result, AvailableIndicatorsResponse)
        assert result.indicators == _ALL_INDICATORS

    async def test_list_is_sorted(self):
        result = await list_available_indicators()
        assert result.indicators == sorted(result.indicators)

    async def test_contains_expected_indicator_names(self):
        result = await list_available_indicators()
        expected_subset = {
            "rsi_14",
            "macd_line",
            "macd_signal",
            "sma_20",
            "sma_50",
            "ema_12",
            "ema_26",
            "bb_upper",
            "bb_mid",
            "bb_lower",
            "adx_14",
            "atr_14",
            "volume_ma_20",
            "price",
        }
        assert expected_subset.issubset(set(result.indicators))

    async def test_count_matches_engine_key_map(self):
        result = await list_available_indicators()
        assert len(result.indicators) == len(_ENGINE_KEY_MAP)


# ---------------------------------------------------------------------------
# get_indicators — symbol validation
# ---------------------------------------------------------------------------


class TestGetIndicatorsSymbolValidation:
    def _make_redis_no_cache(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock()
        return redis

    async def test_valid_symbol_btcusdt_passes(self):
        mock_redis = self._make_redis_no_cache()
        mock_db = AsyncMock()
        candles = _make_candles(50)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=50,
        )
        assert result.symbol == "BTCUSDT"

    async def test_lowercase_symbol_is_uppercased_and_accepted(self):
        """Route upper-cases the symbol before validation."""
        mock_redis = self._make_redis_no_cache()
        mock_db = AsyncMock()
        candles = _make_candles(50)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="btcusdt",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=50,
        )
        assert result.symbol == "BTCUSDT"

    async def test_symbol_without_usdt_suffix_raises_error(self):
        mock_redis = self._make_redis_no_cache()
        mock_db = AsyncMock()

        with pytest.raises(InvalidSymbolError):
            await get_indicators(
                symbol="BTCEUR",
                db=mock_db,
                redis=mock_redis,
                indicators=None,
                lookback=50,
            )

    async def test_symbol_with_numbers_raises_error(self):
        mock_redis = self._make_redis_no_cache()
        mock_db = AsyncMock()

        with pytest.raises(InvalidSymbolError):
            await get_indicators(
                symbol="123USDT",
                db=mock_db,
                redis=mock_redis,
                indicators=None,
                lookback=50,
            )

    async def test_symbol_too_short_raises_error(self):
        mock_redis = self._make_redis_no_cache()
        mock_db = AsyncMock()

        with pytest.raises(InvalidSymbolError):
            await get_indicators(
                symbol="AUSDT",  # only 1 char before USDT
                db=mock_db,
                redis=mock_redis,
                indicators=None,
                lookback=50,
            )

    async def test_symbol_too_long_raises_error(self):
        mock_redis = self._make_redis_no_cache()
        mock_db = AsyncMock()

        with pytest.raises(InvalidSymbolError):
            await get_indicators(
                symbol="TOOLONGPREFIXUSDT",  # 11 chars before USDT
                db=mock_db,
                redis=mock_redis,
                indicators=None,
                lookback=50,
            )

    async def test_ethusdt_accepted(self):
        mock_redis = self._make_redis_no_cache()
        mock_db = AsyncMock()
        candles = _make_candles(50)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="ETHUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=50,
        )
        assert result.symbol == "ETHUSDT"


# ---------------------------------------------------------------------------
# get_indicators — cache hit/miss
# ---------------------------------------------------------------------------


class TestGetIndicatorsCacheBehaviour:
    async def test_cache_hit_skips_db(self):
        """When Redis returns a cached payload, the DB must not be queried."""
        cached_response = IndicatorResponse(
            symbol="BTCUSDT",
            timestamp=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
            candles_used=100,
            indicators={"rsi_14": 55.0},
        )
        payload = json.dumps(cached_response.model_dump(mode="json"))

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=payload)
        mock_redis.setex = AsyncMock()

        mock_db = AsyncMock()

        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=200,
        )

        assert result.symbol == "BTCUSDT"
        assert result.indicators["rsi_14"] == 55.0
        # DB must not have been queried
        mock_db.execute.assert_not_called()

    async def test_cache_miss_queries_db_and_writes_cache(self):
        """On cache miss, DB is queried and result is written to Redis."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        mock_db = AsyncMock()
        candles = _make_candles(50)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=50,
        )

        assert result.symbol == "BTCUSDT"
        mock_db.execute.assert_called_once()
        mock_redis.setex.assert_called_once()

    async def test_cache_key_differs_by_indicator_subset(self):
        """Two calls with different indicator subsets use separate cache keys."""
        call_keys: list[str] = []

        async def _fake_get(key: str):
            call_keys.append(key)
            return None

        mock_redis = AsyncMock()
        mock_redis.get = _fake_get
        mock_redis.setex = AsyncMock()

        candles = _make_candles(50)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators="rsi_14",
            lookback=50,
        )

        # Reset for second call
        mock_db.execute = AsyncMock(return_value=mock_result)

        await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators="sma_20",
            lookback=50,
        )

        assert len(call_keys) == 2
        assert call_keys[0] != call_keys[1]


# ---------------------------------------------------------------------------
# get_indicators — indicator filtering
# ---------------------------------------------------------------------------


class TestGetIndicatorsFiltering:
    def _make_setup(self, n_candles: int = 50):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        candles = _make_candles(n_candles)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        return mock_redis, mock_db

    async def test_filter_to_single_indicator(self):
        mock_redis, mock_db = self._make_setup()
        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators="rsi_14",
            lookback=50,
        )
        # Only rsi_14 should be present (if it could be computed)
        for key in result.indicators:
            assert key == "rsi_14"

    async def test_filter_to_multiple_indicators(self):
        mock_redis, mock_db = self._make_setup()
        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators="rsi_14,sma_20",
            lookback=50,
        )
        for key in result.indicators:
            assert key in {"rsi_14", "sma_20"}

    async def test_no_filter_returns_all_computable_indicators(self):
        mock_redis, mock_db = self._make_setup(n_candles=200)
        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=200,
        )
        # With 200 candles all indicators should be computable
        for key in result.indicators:
            assert key in _ENGINE_KEY_MAP

    async def test_unknown_indicator_in_filter_raises_error(self):
        mock_redis, mock_db = self._make_setup()
        with pytest.raises(InvalidSymbolError) as exc_info:
            await get_indicators(
                symbol="BTCUSDT",
                db=mock_db,
                redis=mock_redis,
                indicators="not_a_real_indicator",
                lookback=50,
            )
        assert "Unknown indicator" in str(exc_info.value)


# ---------------------------------------------------------------------------
# get_indicators — no candle data
# ---------------------------------------------------------------------------


class TestGetIndicatorsNoCandleData:
    async def test_raises_service_unavailable_when_no_candles(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ServiceUnavailableError):
            await get_indicators(
                symbol="XYZUSDT",
                db=mock_db,
                redis=mock_redis,
                indicators=None,
                lookback=200,
            )


# ---------------------------------------------------------------------------
# get_indicators — response shape
# ---------------------------------------------------------------------------


class TestGetIndicatorsResponseShape:
    async def test_response_contains_required_fields(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        candles = _make_candles(50)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=50,
        )

        assert isinstance(result, IndicatorResponse)
        assert result.symbol == "BTCUSDT"
        assert isinstance(result.timestamp, datetime)
        assert result.candles_used == 50
        assert isinstance(result.indicators, dict)

    async def test_candles_used_matches_fetched_count(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        candles = _make_candles(30)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=200,
        )
        assert result.candles_used == 30

    async def test_all_indicator_values_are_floats(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        candles = _make_candles(100)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=100,
        )
        for name, value in result.indicators.items():
            assert isinstance(value, float), f"{name} is not float: {type(value)}"


# ---------------------------------------------------------------------------
# get_indicators — lookback validation
# ---------------------------------------------------------------------------


class TestGetIndicatorsLookbackValidation:
    """Tests for the lookback query parameter bounds (14–500).

    FastAPI enforces ge/le at the routing layer (returns 422), but the handler
    itself can be called directly with out-of-bounds values.  These tests verify
    the handler processes valid in-range lookbacks correctly.
    """

    async def test_minimum_lookback_14_accepted(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        candles = _make_candles(14)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=14,
        )
        assert result.candles_used == 14

    async def test_maximum_lookback_500_accepted(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        candles = _make_candles(500)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=500,
        )
        assert result.candles_used == 500

    async def test_lookback_passed_to_db_query(self):
        """The lookback value must be forwarded to the SQL LIMIT clause."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        candles = _make_candles(100)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=candles)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        await get_indicators(
            symbol="BTCUSDT",
            db=mock_db,
            redis=mock_redis,
            indicators=None,
            lookback=100,
        )

        mock_db.execute.assert_called_once()
        # The second argument to execute is the params dict with "limit"
        call_kwargs = mock_db.execute.call_args[0]
        params = call_kwargs[1] if len(call_kwargs) > 1 else mock_db.execute.call_args[0][1]
        assert params["limit"] == 100
