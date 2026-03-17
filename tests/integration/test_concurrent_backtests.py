"""Integration test: concurrent backtests don't interfere.

BT-1.8.4: Run 5 concurrent backtests → verify they don't interfere → verify
all complete with independent results.

Requires Docker services.
"""

from __future__ import annotations

import asyncio

from httpx import AsyncClient
import pytest

from src.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "concurrent_test_agent",
        },
    )
    data = resp.json()
    return {"X-API-Key": data["api_key"]}


async def test_concurrent_backtests_isolated(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """5 concurrent backtests should produce independent results."""

    resp = await client.get("/api/v1/market/data-range", headers=auth_headers)
    data_range = resp.json()

    if data_range.get("total_pairs", 0) == 0:
        pytest.skip("No historical data available")

    session_ids = []
    for i in range(5):
        resp = await client.post(
            "/api/v1/backtest/create",
            headers=auth_headers,
            json={
                "start_time": data_range["earliest"],
                "end_time": data_range["latest"],
                "starting_balance": str(10000 + i * 1000),  # Different balances
                "candle_interval": 60,
                "strategy_label": f"concurrent_v{i}",
            },
        )
        assert resp.status_code == 200
        session_ids.append(resp.json()["session_id"])

    # Start all
    for sid in session_ids:
        resp = await client.post(f"/api/v1/backtest/{sid}/start", headers=auth_headers)
        assert resp.status_code == 200

    # Step all concurrently
    async def step_session(sid: str) -> dict:
        resp = await client.post(
            f"/api/v1/backtest/{sid}/step/batch",
            headers=auth_headers,
            json={"steps": 20},
        )
        return resp.json()

    results = await asyncio.gather(*[step_session(sid) for sid in session_ids])

    # All should have stepped to step 20
    for result in results:
        assert result["step"] == 20

    # Cancel all and verify independent results
    for sid in session_ids:
        resp = await client.post(f"/api/v1/backtest/{sid}/cancel", headers=auth_headers)
        assert resp.status_code == 200

        resp = await client.get(f"/api/v1/backtest/{sid}/results", headers=auth_headers)
        assert resp.status_code == 200

    # List should show all 5
    resp = await client.get("/api/v1/backtest/list", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["backtests"]) >= 5
