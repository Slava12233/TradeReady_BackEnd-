"""Integration tests for the market indicators REST endpoints.

Covers:
- ``GET /api/v1/market/indicators/available`` — static list, shape
- ``GET /api/v1/market/indicators/{symbol}``   — full response shape,
  indicator filtering, cache hit/miss, invalid symbol returns 422,
  unavailable data returns 503

All external I/O (DB session, Redis) is mocked via ``app.dependency_overrides``
so no real infrastructure is needed.

Run with::

    pytest tests/integration/test_indicators_endpoint.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from src.config import Settings

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Test settings — safe defaults, no real infrastructure
# ---------------------------------------------------------------------------

_TEST_SETTINGS = Settings(
    jwt_secret="test_secret_that_is_at_least_32_characters_long_for_hs256",
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/15",
    jwt_expiry_hours=1,
)


# ---------------------------------------------------------------------------
# Candle row factory
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
# App + client factory
# ---------------------------------------------------------------------------


def _build_client(
    *,
    db_session: AsyncMock | None = None,
    mock_redis: AsyncMock | None = None,
) -> TestClient:
    """Create a TestClient with mocked DB and Redis for indicators tests."""
    from src.dependencies import (
        get_db_session,
        get_redis,
        get_settings,
    )

    if db_session is None:
        db_session = AsyncMock()

    if mock_redis is None:
        mock_redis = _make_redis_no_cache()

    _db = db_session
    _redis = mock_redis

    with (
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch(
            "src.cache.redis_client.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch(
            "src.api.websocket.manager.ConnectionManager.disconnect_all",
            new_callable=AsyncMock,
        ),
    ):
        from src.main import create_app

        app = create_app()

        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

        async def _override_db():
            yield _db

        app.dependency_overrides[get_db_session] = _override_db

        async def _override_redis():
            yield _redis

        app.dependency_overrides[get_redis] = _override_redis

        return TestClient(app, raise_server_exceptions=False)


def _make_redis_no_cache() -> AsyncMock:
    """Return an AsyncMock Redis client that always reports a cache miss."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    # Rate limit middleware pipeline
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 60])
    redis.pipeline = MagicMock(return_value=mock_pipe)

    redis.hget = AsyncMock(return_value=None)
    redis.hset = AsyncMock(return_value=1)
    return redis


def _make_db_with_candles(n: int = 50) -> AsyncMock:
    """Return a mock DB session that yields *n* candle rows."""
    candles = _make_candles(n)
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=candles)
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _make_db_empty() -> AsyncMock:
    """Return a mock DB session that yields zero candle rows."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/available
# ---------------------------------------------------------------------------


class TestAvailableIndicatorsEndpoint:
    def test_returns_200(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/available")
        assert response.status_code == 200

    def test_response_shape(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/available")
        data = response.json()
        assert "indicators" in data
        assert isinstance(data["indicators"], list)
        assert len(data["indicators"]) > 0

    def test_response_is_sorted(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/available")
        names = response.json()["indicators"]
        assert names == sorted(names)

    def test_response_contains_expected_names(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/available")
        names = set(response.json()["indicators"])
        expected = {
            "rsi_14",
            "macd_line",
            "macd_signal",
            "macd_hist",
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
        assert expected == names

    def test_no_auth_required(self):
        """Market endpoints are public — no API key header needed."""
        client = _build_client()
        response = client.get("/api/v1/market/indicators/available")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/{symbol} — happy path
# ---------------------------------------------------------------------------


class TestGetIndicatorsEndpoint:
    def test_returns_200_with_valid_symbol(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT")
        assert response.status_code == 200

    def test_response_shape(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT")
        data = response.json()
        assert "symbol" in data
        assert "timestamp" in data
        assert "candles_used" in data
        assert "indicators" in data

    def test_symbol_in_response_matches_request(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/ETHUSDT")
        assert response.json()["symbol"] == "ETHUSDT"

    def test_lowercase_symbol_normalised_to_uppercase(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/btcusdt")
        assert response.status_code == 200
        assert response.json()["symbol"] == "BTCUSDT"

    def test_candles_used_reflects_fetched_count(self):
        db = _make_db_with_candles(30)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT?lookback=200")
        assert response.json()["candles_used"] == 30

    def test_indicators_dict_values_are_numbers(self):
        db = _make_db_with_candles(100)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT")
        for name, value in response.json()["indicators"].items():
            assert isinstance(value, int | float), f"{name} value is {type(value)}"

    def test_no_auth_required(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/{symbol} — invalid symbol
# ---------------------------------------------------------------------------


class TestGetIndicatorsInvalidSymbol:
    def test_symbol_without_usdt_suffix_returns_400(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/BTCETH")
        assert response.status_code == 400

    def test_invalid_symbol_response_has_error_envelope(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/NOTVALID")
        data = response.json()
        assert "error" in data
        assert "code" in data["error"]
        assert data["error"]["code"] == "INVALID_SYMBOL"

    def test_symbol_with_lowercase_mixed_still_validates_after_upper(self):
        """Mixed-case that becomes valid after uppercasing should not 400."""
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        # "BtcUsdt".upper() == "BTCUSDT" → valid
        response = client.get("/api/v1/market/indicators/BtcUsdt")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/{symbol} — lookback query param
# ---------------------------------------------------------------------------


class TestGetIndicatorsLookback:
    def test_lookback_below_minimum_returns_422(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/BTCUSDT?lookback=13")
        assert response.status_code == 422

    def test_lookback_above_maximum_returns_422(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/BTCUSDT?lookback=501")
        assert response.status_code == 422

    def test_lookback_at_minimum_accepted(self):
        db = _make_db_with_candles(14)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT?lookback=14")
        assert response.status_code == 200

    def test_lookback_at_maximum_accepted(self):
        db = _make_db_with_candles(500)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT?lookback=500")
        assert response.status_code == 200

    def test_lookback_non_integer_returns_422(self):
        client = _build_client()
        response = client.get("/api/v1/market/indicators/BTCUSDT?lookback=abc")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/{symbol} — indicator filter query param
# ---------------------------------------------------------------------------


class TestGetIndicatorsFilterParam:
    def test_filter_to_single_indicator(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT?indicators=rsi_14")
        assert response.status_code == 200
        indicators = response.json()["indicators"]
        for key in indicators:
            assert key == "rsi_14"

    def test_filter_to_multiple_indicators(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT?indicators=rsi_14,sma_20")
        assert response.status_code == 200
        for key in response.json()["indicators"]:
            assert key in {"rsi_14", "sma_20"}

    def test_unknown_indicator_returns_400(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT?indicators=fake_indicator")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "INVALID_SYMBOL" in data["error"]["code"]


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/{symbol} — cache behaviour
# ---------------------------------------------------------------------------


class TestGetIndicatorsCacheIntegration:
    def test_cache_hit_returns_200(self):
        """If Redis has a cached response, the endpoint returns it directly."""
        from src.api.schemas.indicators import IndicatorResponse

        cached = IndicatorResponse(
            symbol="BTCUSDT",
            timestamp=datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC),
            candles_used=100,
            indicators={"rsi_14": 62.5},
        )
        payload = json.dumps(cached.model_dump(mode="json"))

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=payload)
        redis.setex = AsyncMock()

        mock_pipe = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_pipe.incr = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[1, 60])
        redis.pipeline = MagicMock(return_value=mock_pipe)
        redis.hget = AsyncMock(return_value=None)
        redis.hset = AsyncMock(return_value=1)

        db = AsyncMock()  # DB should not be called

        client = _build_client(db_session=db, mock_redis=redis)
        response = client.get("/api/v1/market/indicators/BTCUSDT")

        assert response.status_code == 200
        assert response.json()["indicators"]["rsi_14"] == 62.5
        # DB should not have been queried
        db.execute.assert_not_called()

    def test_cache_miss_falls_through_to_db(self):
        db = _make_db_with_candles(50)
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/BTCUSDT")
        assert response.status_code == 200
        db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/{symbol} — no data available
# ---------------------------------------------------------------------------


class TestGetIndicatorsNoData:
    def test_empty_candle_data_returns_503(self):
        db = _make_db_empty()
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/XYZUSDT")
        assert response.status_code == 503

    def test_503_response_has_error_envelope(self):
        db = _make_db_empty()
        client = _build_client(db_session=db)
        response = client.get("/api/v1/market/indicators/XYZUSDT")
        data = response.json()
        assert "error" in data
        assert "code" in data["error"]
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"
