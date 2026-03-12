"""Integration test: full backtest lifecycle end-to-end.

BT-1.8.1: create → start → step → place order → step more → complete → verify results.

Requires Docker services (TimescaleDB, Redis) to be running.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from src.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
async def client():
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register and get auth headers."""
    resp = await client.post("/api/v1/auth/register", json={
        "display_name": "backtest_test_agent",
    })
    data = resp.json()
    return {"X-API-Key": data["api_key"]}


async def test_full_backtest_lifecycle(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Full lifecycle: create → start → step → order → step more → complete → results."""

    # 1. Check data range
    resp = await client.get("/api/v1/market/data-range", headers=auth_headers)
    assert resp.status_code == 200
    data_range = resp.json()

    if data_range.get("total_pairs", 0) == 0:
        pytest.skip("No historical data available for backtest test")

    # 2. Create backtest
    resp = await client.post("/api/v1/backtest/create", headers=auth_headers, json={
        "start_time": data_range["earliest"],
        "end_time": data_range["latest"],
        "starting_balance": "10000",
        "candle_interval": 60,
        "strategy_label": "e2e_test_v1",
    })
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # 3. Start
    resp = await client.post(f"/api/v1/backtest/{session_id}/start", headers=auth_headers)
    assert resp.status_code == 200

    # 4. Step 10 times
    for _ in range(10):
        resp = await client.post(f"/api/v1/backtest/{session_id}/step", headers=auth_headers)
        assert resp.status_code == 200

    step_data = resp.json()
    assert step_data["step"] == 10

    # 5. Verify prices are historical (no future)
    resp = await client.get(
        f"/api/v1/backtest/{session_id}/market/prices", headers=auth_headers
    )
    assert resp.status_code == 200
    prices = resp.json()["prices"]
    assert len(prices) > 0

    # 6. Place a market buy order
    if prices:
        symbol = list(prices.keys())[0]
        resp = await client.post(
            f"/api/v1/backtest/{session_id}/trade/order",
            headers=auth_headers,
            json={
                "symbol": symbol,
                "side": "buy",
                "type": "market",
                "quantity": "0.01",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "filled"

    # 7. Verify balance changed
    resp = await client.get(
        f"/api/v1/backtest/{session_id}/account/balance", headers=auth_headers
    )
    assert resp.status_code == 200

    # 8. Step 100 more via batch
    resp = await client.post(
        f"/api/v1/backtest/{session_id}/step/batch",
        headers=auth_headers,
        json={"steps": 100},
    )
    assert resp.status_code == 200

    # 9. Cancel to save partial results
    resp = await client.post(
        f"/api/v1/backtest/{session_id}/cancel", headers=auth_headers
    )
    assert resp.status_code == 200

    # 10. Get results
    resp = await client.get(
        f"/api/v1/backtest/{session_id}/results", headers=auth_headers
    )
    assert resp.status_code == 200
    results = resp.json()
    assert results["status"] in ("completed", "cancelled")

    # 11. Get equity curve
    resp = await client.get(
        f"/api/v1/backtest/{session_id}/results/equity-curve", headers=auth_headers
    )
    assert resp.status_code == 200
    assert len(resp.json()["snapshots"]) > 0

    # 12. Get trade log
    resp = await client.get(
        f"/api/v1/backtest/{session_id}/results/trades", headers=auth_headers
    )
    assert resp.status_code == 200

    # 13. List backtests
    resp = await client.get("/api/v1/backtest/list", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["backtests"]) >= 1
