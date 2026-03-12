"""Unit tests for src/monitoring/health.py — health check endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from src.monitoring.health import _probe_db, _probe_ingestion, _probe_redis, health_check

# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------


class TestProbeRedis:
    @patch("src.cache.redis_client.get_redis_client")
    async def test_success(self, mock_get_client):
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_get_client.return_value = mock_client

        ok, latency = await _probe_redis()
        assert ok is True
        assert latency >= 0

    @patch("src.cache.redis_client.get_redis_client")
    async def test_failure(self, mock_get_client):
        mock_get_client.side_effect = ConnectionError("down")

        ok, latency = await _probe_redis()
        assert ok is False
        assert latency == -1.0


class TestProbeDb:
    @patch("src.database.session.get_engine")
    async def test_success(self, mock_get_engine):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = cm
        mock_get_engine.return_value = mock_engine

        ok, latency = await _probe_db()
        assert ok is True
        assert latency >= 0

    @patch("src.database.session.get_engine")
    async def test_failure(self, mock_get_engine):
        mock_get_engine.side_effect = Exception("db down")

        ok, latency = await _probe_db()
        assert ok is False
        assert latency == -1.0


class TestProbeIngestion:
    @patch("src.cache.price_cache.PriceCache")
    @patch("src.cache.redis_client.get_redis_client")
    async def test_active(self, mock_get_client, mock_cache_cls):
        mock_client = AsyncMock()
        mock_get_client.return_value = mock_client

        mock_cache = AsyncMock()
        mock_cache.get_all_prices = AsyncMock(return_value={"BTCUSDT": "60000"})
        mock_cache.get_stale_pairs = AsyncMock(return_value=[])
        mock_cache_cls.return_value = mock_cache

        active, stale, total = await _probe_ingestion()
        assert active is True
        assert stale == []
        assert total == 1

    @patch("src.cache.redis_client.get_redis_client")
    async def test_inactive(self, mock_get_client):
        mock_get_client.side_effect = Exception("down")

        active, stale, total = await _probe_ingestion()
        assert active is False
        assert total == 0


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @patch("src.monitoring.health._probe_ingestion")
    @patch("src.monitoring.health._probe_db")
    @patch("src.monitoring.health._probe_redis")
    async def test_all_ok(self, mock_redis, mock_db, mock_ingestion):
        mock_redis.return_value = (True, 0.5)
        mock_db.return_value = (True, 1.2)
        mock_ingestion.return_value = (True, [], 612)

        resp = await health_check()
        assert resp.status_code == 200
        import json

        body = json.loads(resp.body)
        assert body["status"] == "ok"

    @patch("src.monitoring.health._probe_ingestion")
    @patch("src.monitoring.health._probe_db")
    @patch("src.monitoring.health._probe_redis")
    async def test_degraded(self, mock_redis, mock_db, mock_ingestion):
        mock_redis.return_value = (True, 0.5)
        mock_db.return_value = (True, 1.2)
        mock_ingestion.return_value = (True, ["XYZUSDT"], 612)

        resp = await health_check()
        assert resp.status_code == 200
        import json

        body = json.loads(resp.body)
        assert body["status"] == "degraded"

    @patch("src.monitoring.health._probe_ingestion")
    @patch("src.monitoring.health._probe_db")
    @patch("src.monitoring.health._probe_redis")
    async def test_unhealthy_redis_down(self, mock_redis, mock_db, mock_ingestion):
        mock_redis.return_value = (False, -1.0)
        mock_db.return_value = (True, 1.2)
        mock_ingestion.return_value = (False, [], 0)

        resp = await health_check()
        assert resp.status_code == 503

    @patch("src.monitoring.health._probe_ingestion")
    @patch("src.monitoring.health._probe_db")
    @patch("src.monitoring.health._probe_redis")
    async def test_unhealthy_db_down(self, mock_redis, mock_db, mock_ingestion):
        mock_redis.return_value = (True, 0.5)
        mock_db.return_value = (False, -1.0)
        mock_ingestion.return_value = (True, [], 612)

        resp = await health_check()
        assert resp.status_code == 503
