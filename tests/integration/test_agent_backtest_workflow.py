"""Integration test: agent workflow with multiple backtests.

BT-1.8.3: Create backtest A (strategy_v1) → run → create backtest B (strategy_v2)
→ run → compare → verify comparison → get best → verify correct → switch mode.

Requires Docker services.
"""

from __future__ import annotations

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
    resp = await client.post("/api/v1/auth/register", json={
        "display_name": "workflow_test_agent",
    })
    data = resp.json()
    return {"X-API-Key": data["api_key"]}


async def test_multi_backtest_compare_workflow(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Agent creates two backtests, compares, picks best, switches mode."""

    resp = await client.get("/api/v1/market/data-range", headers=auth_headers)
    data_range = resp.json()

    if data_range.get("total_pairs", 0) == 0:
        pytest.skip("No historical data available")

    session_ids = []

    for label in ["momentum_v1", "momentum_v2"]:
        # Create
        resp = await client.post("/api/v1/backtest/create", headers=auth_headers, json={
            "start_time": data_range["earliest"],
            "end_time": data_range["latest"],
            "starting_balance": "10000",
            "candle_interval": 60,
            "strategy_label": label,
        })
        assert resp.status_code == 200
        sid = resp.json()["session_id"]
        session_ids.append(sid)

        # Start + run some steps
        await client.post(f"/api/v1/backtest/{sid}/start", headers=auth_headers)
        await client.post(
            f"/api/v1/backtest/{sid}/step/batch",
            headers=auth_headers, json={"steps": 50},
        )
        # Cancel to save results
        await client.post(f"/api/v1/backtest/{sid}/cancel", headers=auth_headers)

    # Compare
    resp = await client.get(
        f"/api/v1/backtest/compare?sessions={','.join(session_ids)}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    compare = resp.json()
    assert len(compare["comparisons"]) == 2
    assert compare["best_by_roi"] is not None

    # Get best
    resp = await client.get(
        "/api/v1/backtest/best?metric=roi_pct",
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Switch mode
    resp = await client.post(
        "/api/v1/account/mode",
        headers=auth_headers,
        json={"mode": "backtest", "strategy_label": "momentum_v2"},
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "backtest"

    # Check mode
    resp = await client.get("/api/v1/account/mode", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["mode"] == "backtest"

    # Switch back to live
    resp = await client.post(
        "/api/v1/account/mode",
        headers=auth_headers,
        json={"mode": "live"},
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "live"
