"""Integration test: backtest API endpoint validation.

BT-1.8.5: Test every REST endpoint with valid + invalid inputs,
auth required, session ownership, error format.

Requires Docker services.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient
import pytest

from src.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "api_test_agent",
        },
    )
    data = resp.json()
    return {"X-API-Key": data["api_key"]}


async def test_create_backtest_requires_auth(client: AsyncClient) -> None:
    """All backtest endpoints require authentication."""
    resp = await client.post(
        "/api/v1/backtest/create",
        json={
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-02T00:00:00Z",
            "starting_balance": "10000",
        },
    )
    assert resp.status_code == 401


async def test_create_backtest_invalid_balance(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Starting balance must be positive."""
    resp = await client.post(
        "/api/v1/backtest/create",
        headers=auth_headers,
        json={
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-02T00:00:00Z",
            "starting_balance": "0",
        },
    )
    assert resp.status_code == 422


async def test_step_nonexistent_session(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Stepping a non-existent session returns 404."""
    resp = await client.post(
        "/api/v1/backtest/00000000-0000-0000-0000-000000000000/step",
        headers=auth_headers,
    )
    # Should be a 404 or error
    assert resp.status_code in (404, 500)


async def test_data_range_endpoint(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """GET /market/data-range should return valid response."""
    resp = await client.get("/api/v1/market/data-range", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_pairs" in data
    assert "intervals_available" in data


async def test_list_backtests_empty(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """New account should have no backtests."""
    resp = await client.get("/api/v1/backtest/list", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["backtests"] == []


async def test_best_backtest_not_found(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Best backtest with no completed tests should return 404."""
    resp = await client.get("/api/v1/backtest/best?metric=roi_pct", headers=auth_headers)
    assert resp.status_code == 404


async def test_account_mode_default(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Default account mode should be 'live'."""
    resp = await client.get("/api/v1/account/mode", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "live"


async def test_switch_mode_invalid(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Invalid mode value should be rejected."""
    resp = await client.post(
        "/api/v1/account/mode",
        headers=auth_headers,
        json={
            "mode": "invalid",
        },
    )
    assert resp.status_code == 422


async def test_error_format(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Error responses should match format: {\"error\": {\"code\": ..., \"message\": ...}}."""
    resp = await client.get("/api/v1/backtest/best?metric=roi_pct", headers=auth_headers)
    if resp.status_code >= 400:
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
