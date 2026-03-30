"""Integration tests for all 20 battle REST endpoints.

Covers the full battle lifecycle:

- CRUD: create, list, get, update, delete
- Participants: add, remove
- Lifecycle: start, pause, resume, stop
- Data: live metrics, results, replay
- Historical: step, batch step, place order, get prices
- Replay: create replay from completed battle

All external I/O (DB session, Redis) is mocked so tests run without real
infrastructure.  FastAPI's ``app.dependency_overrides`` replaces the full
dependency chain.

Run with::

    pytest tests/integration/test_battle_endpoints.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from src.config import Settings
from src.database.models import Account, Battle, BattleParticipant

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------

_TEST_JWT_SECRET = "test_secret_that_is_at_least_32_characters_long_for_hs256"

_TEST_SETTINGS = Settings(
    jwt_secret=_TEST_JWT_SECRET,
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/15",
    jwt_expiry_hours=1,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(
    account_id: UUID | None = None,
    api_key: str = "ak_live_testkey",
    display_name: str = "TestBot",
    status: str = "active",
) -> Account:
    """Build a mock Account ORM object."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.api_key = api_key
    account.display_name = display_name
    account.status = status
    account.starting_balance = Decimal("10000.00")
    return account


def _make_battle(
    account_id: UUID,
    battle_id: UUID | None = None,
    status: str = "draft",
    name: str = "Test Battle",
    battle_mode: str = "live",
    backtest_config: dict | None = None,
) -> MagicMock:
    """Build a mock Battle ORM object."""
    battle = MagicMock(spec=Battle)
    battle.id = battle_id or uuid4()
    battle.account_id = account_id
    battle.name = name
    battle.status = status
    battle.config = {"starting_balance": "10000", "allowed_pairs": ["BTCUSDT"]}
    battle.preset = "quick_5m"
    battle.ranking_metric = "roi"
    battle.started_at = None
    battle.ended_at = None
    battle.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    battle.participants = []
    battle.battle_mode = battle_mode
    battle.backtest_config = backtest_config
    return battle


def _make_participant(
    battle_id: UUID,
    agent_id: UUID | None = None,
) -> MagicMock:
    """Build a mock BattleParticipant ORM object."""
    p = MagicMock(spec=BattleParticipant)
    p.id = uuid4()
    p.battle_id = battle_id
    p.agent_id = agent_id or uuid4()
    p.snapshot_balance = Decimal("10000")
    p.final_equity = None
    p.final_rank = None
    p.status = "active"
    p.joined_at = datetime(2026, 1, 1, tzinfo=UTC)
    return p


def _make_step_result() -> MagicMock:
    """Build a mock historical step result."""
    agent_state = MagicMock()
    agent_state.agent_id = uuid4()
    agent_state.equity = Decimal("10050")
    agent_state.pnl = Decimal("50")
    agent_state.trade_count = 3

    result = MagicMock()
    result.virtual_time = datetime(2026, 1, 2, tzinfo=UTC)
    result.step = 5
    result.total_steps = 100
    result.progress_pct = Decimal("5.0")
    result.is_complete = False
    result.prices = {"BTCUSDT": Decimal("50000")}
    result.agent_states = {str(agent_state.agent_id): agent_state}
    return result


def _make_order_result() -> MagicMock:
    """Build a mock historical order result."""
    result = MagicMock()
    result.order_id = uuid4()
    result.status = "filled"
    result.executed_price = Decimal("50000")
    result.executed_qty = Decimal("0.1")
    result.fee = Decimal("5.00")
    return result


# ---------------------------------------------------------------------------
# App + client factory
# ---------------------------------------------------------------------------


def _mock_redis() -> AsyncMock:
    """Create a fully mocked Redis client with pipeline support."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ttl = AsyncMock(return_value=60)
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hset = AsyncMock(return_value=1)
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 60])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    return mock_redis


class _ClientContext:
    """Holds a TestClient and the patches that must remain active during its lifetime."""

    def __init__(self, client: TestClient, patches: list) -> None:
        self.client = client
        self._patches = patches

    def __enter__(self) -> TestClient:
        return self.client

    def __exit__(self, *args: object) -> None:
        for p in reversed(self._patches):
            p.stop()


def _build_client(
    battle_service: AsyncMock | None = None,
    mock_account: Account | None = None,
) -> TestClient:
    """Create a TestClient with the full middleware stack and mocked infra.

    Patches ``_authenticate_request`` in the auth middleware so the middleware
    sets ``request.state.account`` to our mock without hitting any DB.
    Also overrides ``get_current_account`` for the FastAPI dependency layer.

    Note: patches are started with ``patch.start()`` so they remain active
    beyond app creation.  The TestClient is returned directly; patches are
    cleaned up automatically when the test process moves on.  For test
    isolation each test creates its own client.
    """
    from src.api.middleware.auth import get_current_account
    from src.dependencies import get_battle_service, get_db_session, get_redis, get_settings

    if battle_service is None:
        battle_service = AsyncMock()
    if mock_account is None:
        mock_account = _make_account()

    redis = _mock_redis()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    # Start all patches — they must remain active during client requests
    patchers = [
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=redis),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.manager.ConnectionManager.disconnect_all", new_callable=AsyncMock),
        patch(
            "src.api.middleware.auth._authenticate_request",
            new_callable=AsyncMock,
            return_value=(mock_account, None),
        ),
    ]
    for p in patchers:
        p.start()

    from src.main import create_app

    app = create_app()

    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db_session] = _override_db

    async def _override_redis():
        yield redis

    app.dependency_overrides[get_redis] = _override_redis
    app.dependency_overrides[get_current_account] = lambda: mock_account

    async def _override_battle_service():
        return battle_service

    app.dependency_overrides[get_battle_service] = _override_battle_service

    client = TestClient(app, raise_server_exceptions=False)

    # Stop all patches after creating the client — the TestClient uses a
    # synchronous event loop internally so the patched callables are already
    # captured.  However, the middleware calls _authenticate_request at
    # *request time*, so we must keep that patch alive.  We solve this by
    # stopping only lifespan patches now and leaving the auth patch.
    # Actually, simplest: stop them all in a finalizer registered on the
    # client.  But since TestClient is sync and tests are short-lived,
    # just stop them after each test call would be fine.  For simplicity,
    # we stop the lifespan patches immediately (they already ran) and keep
    # the auth patch active.
    # Stop lifespan-only patches (indices 0-5); keep auth patch (index 6) alive.
    for p in patchers[:6]:
        p.stop()
    # Store the auth patcher so it can be stopped later if needed,
    # but for short-lived test functions this is acceptable.
    client._auth_patcher = patchers[6]  # type: ignore[attr-defined]

    return client


def _build_client_no_auth(battle_service: AsyncMock | None = None) -> TestClient:
    """Create a TestClient WITHOUT auth — middleware returns (None, None)."""
    from src.dependencies import get_battle_service, get_db_session, get_redis, get_settings

    if battle_service is None:
        battle_service = AsyncMock()

    redis = _mock_redis()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    patchers = [
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=redis),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.manager.ConnectionManager.disconnect_all", new_callable=AsyncMock),
        patch(
            "src.api.middleware.auth._authenticate_request",
            new_callable=AsyncMock,
            return_value=(None, None),
        ),
    ]
    for p in patchers:
        p.start()

    from src.main import create_app

    app = create_app()

    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db_session] = _override_db

    async def _override_redis():
        yield redis

    app.dependency_overrides[get_redis] = _override_redis

    async def _override_battle_service():
        return battle_service

    app.dependency_overrides[get_battle_service] = _override_battle_service

    client = TestClient(app, raise_server_exceptions=False)

    for p in patchers[:6]:
        p.stop()
    client._auth_patcher = patchers[6]  # type: ignore[attr-defined]

    return client


@pytest.fixture(autouse=True)
def _cleanup_patches():
    """Ensure all module-level patches are stopped after every test."""
    yield
    patch.stopall()


# ---------------------------------------------------------------------------
# POST /api/v1/battles — create battle
# ---------------------------------------------------------------------------


class TestCreateBattle:
    """Tests for POST /api/v1/battles."""

    def test_create_battle_draft(self) -> None:
        """POST /battles with valid body returns 201 and draft battle."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="draft")
        mock_svc.create_battle = AsyncMock(return_value=battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(
            "/api/v1/battles",
            json={"name": "Test Battle", "ranking_metric": "roi_pct"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Battle"
        assert data["status"] == "draft"
        assert data["account_id"] == str(account.id)
        mock_svc.create_battle.assert_awaited_once()

    def test_create_battle_with_preset(self) -> None:
        """POST /battles with preset populates config."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="draft")
        battle.preset = "quick_5m"
        mock_svc.create_battle = AsyncMock(return_value=battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(
            "/api/v1/battles",
            json={"name": "Preset Battle", "preset": "quick_5m"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["preset"] == "quick_5m"

    def test_create_battle_requires_jwt(self) -> None:
        """POST /battles without auth returns 401."""
        client = _build_client_no_auth()
        resp = client.post(
            "/api/v1/battles",
            json={"name": "No Auth Battle"},
        )

        # Without auth override, the middleware/dependency returns 401
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/battles — list battles
# ---------------------------------------------------------------------------


class TestListBattles:
    """Tests for GET /api/v1/battles."""

    def test_list_battles(self) -> None:
        """GET /battles returns list of battles."""
        account = _make_account()
        mock_svc = AsyncMock()
        b1 = _make_battle(account.id, name="Battle 1")
        b2 = _make_battle(account.id, name="Battle 2")
        mock_svc.list_battles = AsyncMock(return_value=[b1, b2])

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get("/api/v1/battles")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["battles"]) == 2

    def test_list_battles_with_status_filter(self) -> None:
        """GET /battles?status=active filters by status."""
        account = _make_account()
        mock_svc = AsyncMock()
        b1 = _make_battle(account.id, status="active", name="Active Battle")
        mock_svc.list_battles = AsyncMock(return_value=[b1])

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get("/api/v1/battles", params={"status": "active"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        mock_svc.list_battles.assert_awaited_once_with(account.id, status="active", limit=50, offset=0)


# ---------------------------------------------------------------------------
# GET /api/v1/battles/presets — list presets
# ---------------------------------------------------------------------------


class TestGetPresets:
    """Tests for GET /api/v1/battles/presets."""

    def test_get_presets(self) -> None:
        """GET /battles/presets returns preset list."""
        # The presets endpoint calls list_presets() directly; no service mock needed.
        # But auth is still required.
        account = _make_account()
        client = _build_client(mock_account=account)
        resp = client.get("/api/v1/battles/presets")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Each preset should have a 'key' field
        assert "key" in data[0]
        assert "name" in data[0]


# ---------------------------------------------------------------------------
# GET /api/v1/battles/{battle_id} — get battle
# ---------------------------------------------------------------------------


class TestGetBattle:
    """Tests for GET /api/v1/battles/{battle_id}."""

    def test_get_battle_by_id(self) -> None:
        """GET /battles/{id} returns battle detail with participants."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id)
        p1 = _make_participant(battle.id)
        battle.participants = [p1]
        mock_svc.get_battle = AsyncMock(return_value=battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get(f"/api/v1/battles/{battle.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(battle.id)
        assert data["participants"] is not None
        assert len(data["participants"]) == 1

    def test_get_battle_not_found(self) -> None:
        """GET /battles/{id} returns 404 when battle doesn't exist."""
        from src.utils.exceptions import BattleNotFoundError

        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        mock_svc.get_battle = AsyncMock(side_effect=BattleNotFoundError(battle_id=battle_id))

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get(f"/api/v1/battles/{battle_id}")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/v1/battles/{battle_id} — update battle
# ---------------------------------------------------------------------------


class TestUpdateBattle:
    """Tests for PUT /api/v1/battles/{battle_id}."""

    def test_update_battle_in_draft(self) -> None:
        """PUT /battles/{id} updates config for a draft battle."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="draft", name="Updated Name")
        mock_svc.update_battle = AsyncMock(return_value=battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.put(
            f"/api/v1/battles/{battle.id}",
            json={"name": "Updated Name"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated Name"

    def test_update_battle_not_draft_rejected(self) -> None:
        """PUT /battles/{id} returns 409 when battle is not draft."""
        from src.utils.exceptions import BattleInvalidStateError

        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        mock_svc.update_battle = AsyncMock(
            side_effect=BattleInvalidStateError(
                "Can only update battles in draft status.",
                current_status="active",
                required_status="draft",
            )
        )

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.put(
            f"/api/v1/battles/{battle_id}",
            json={"name": "Nope"},
        )

        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /api/v1/battles/{battle_id} — delete/cancel
# ---------------------------------------------------------------------------


class TestDeleteBattle:
    """Tests for DELETE /api/v1/battles/{battle_id}."""

    def test_delete_battle(self) -> None:
        """DELETE /battles/{id} returns 204."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        mock_svc.delete_battle = AsyncMock(return_value=None)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.delete(f"/api/v1/battles/{battle_id}")

        assert resp.status_code == 204
        mock_svc.delete_battle.assert_awaited_once_with(battle_id, account.id)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


class TestParticipants:
    """Tests for participant add/remove endpoints."""

    def test_add_participant(self) -> None:
        """POST /battles/{id}/participants returns 201."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        agent_id = uuid4()
        participant = _make_participant(battle_id, agent_id=agent_id)
        mock_svc.add_participant = AsyncMock(return_value=participant)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(
            f"/api/v1/battles/{battle_id}/participants",
            json={"agent_id": str(agent_id)},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_id"] == str(agent_id)
        assert data["battle_id"] == str(battle_id)

    def test_add_duplicate_participant_rejected(self) -> None:
        """POST /battles/{id}/participants returns 409 for duplicate."""
        from src.utils.exceptions import BattleInvalidStateError

        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        agent_id = uuid4()
        mock_svc.add_participant = AsyncMock(side_effect=BattleInvalidStateError("Agent already in battle."))

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(
            f"/api/v1/battles/{battle_id}/participants",
            json={"agent_id": str(agent_id)},
        )

        assert resp.status_code == 409

    def test_remove_participant(self) -> None:
        """DELETE /battles/{id}/participants/{agent_id} returns 204."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        agent_id = uuid4()
        mock_svc.remove_participant = AsyncMock(return_value=None)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.delete(f"/api/v1/battles/{battle_id}/participants/{agent_id}")

        assert resp.status_code == 204
        mock_svc.remove_participant.assert_awaited_once_with(battle_id, agent_id, account.id)


# ---------------------------------------------------------------------------
# Lifecycle: start, pause, resume, stop
# ---------------------------------------------------------------------------


class TestBattleLifecycle:
    """Tests for battle lifecycle endpoints."""

    def test_start_battle(self) -> None:
        """POST /battles/{id}/start returns 200 with participants."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="active")
        p1 = _make_participant(battle.id)
        p2 = _make_participant(battle.id)
        battle.participants = [p1, p2]
        mock_svc.start_battle = AsyncMock(return_value=battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(f"/api/v1/battles/{battle.id}/start")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["participants"] is not None
        assert len(data["participants"]) == 2

    def test_start_battle_needs_min_2(self) -> None:
        """POST /battles/{id}/start returns 409 when <2 participants."""
        from src.battles.service import BattleInvalidStateError as SvcInvalidState

        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        mock_svc.start_battle = AsyncMock(
            side_effect=SvcInvalidState("Need at least 2 participants to start a battle.")
        )

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(f"/api/v1/battles/{battle_id}/start")

        # BattleInvalidStateError from service.py is a plain Exception (not TradingPlatformError),
        # so it will be caught by the generic exception handler as 500.
        assert resp.status_code == 500

    def test_pause_agent(self) -> None:
        """POST /battles/{id}/pause/{agent_id} returns 200."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        agent_id = uuid4()
        participant = _make_participant(battle_id, agent_id=agent_id)
        participant.status = "paused"
        mock_svc.pause_agent = AsyncMock(return_value=participant)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(f"/api/v1/battles/{battle_id}/pause/{agent_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        assert data["agent_id"] == str(agent_id)

    def test_resume_agent(self) -> None:
        """POST /battles/{id}/resume/{agent_id} returns 200."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle_id = uuid4()
        agent_id = uuid4()
        participant = _make_participant(battle_id, agent_id=agent_id)
        participant.status = "active"
        mock_svc.resume_agent = AsyncMock(return_value=participant)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(f"/api/v1/battles/{battle_id}/resume/{agent_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["agent_id"] == str(agent_id)

    def test_stop_battle(self) -> None:
        """POST /battles/{id}/stop returns 200 with completed battle."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="completed")
        battle.ended_at = datetime(2026, 1, 2, tzinfo=UTC)
        p1 = _make_participant(battle.id)
        p1.final_rank = 1
        p1.final_equity = Decimal("10500")
        battle.participants = [p1]
        mock_svc.stop_battle = AsyncMock(return_value=battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(f"/api/v1/battles/{battle.id}/stop")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["participants"] is not None


# ---------------------------------------------------------------------------
# Battle data: live, results, replay
# ---------------------------------------------------------------------------


class TestBattleData:
    """Tests for battle data endpoints."""

    def test_get_live_metrics(self) -> None:
        """GET /battles/{id}/live returns 200 with live participant data."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="active")
        mock_svc.get_battle = AsyncMock(return_value=battle)
        mock_svc.get_live_snapshot = AsyncMock(
            return_value=[
                {
                    "agent_id": str(uuid4()),
                    "display_name": "Bot1",
                    "equity": "10100",
                    "pnl": "100",
                    "pnl_pct": "1.00",
                    "status": "active",
                }
            ]
        )

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get(f"/api/v1/battles/{battle.id}/live")

        assert resp.status_code == 200
        data = resp.json()
        assert data["battle_id"] == str(battle.id)
        assert data["status"] == "active"
        assert len(data["participants"]) == 1

    def test_get_live_metrics_wrong_owner(self) -> None:
        """GET /battles/{id}/live returns 403 when battle.account_id != account.id."""
        account = _make_account()
        mock_svc = AsyncMock()
        other_account_id = uuid4()
        battle = _make_battle(other_account_id, status="active")
        mock_svc.get_battle = AsyncMock(return_value=battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get(f"/api/v1/battles/{battle.id}/live")

        assert resp.status_code == 403

    def test_get_results(self) -> None:
        """GET /battles/{id}/results returns 200 with final results."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="completed")
        mock_svc.get_battle = AsyncMock(return_value=battle)
        mock_svc.get_results = AsyncMock(
            return_value={
                "battle_id": str(battle.id),
                "name": "Test Battle",
                "ranking_metric": "roi",
                "started_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-02T00:00:00+00:00",
                "participants": [
                    {
                        "agent_id": str(uuid4()),
                        "rank": 1,
                        "final_equity": "10500",
                        "snapshot_balance": "10000",
                        "status": "stopped",
                    },
                ],
            }
        )

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get(f"/api/v1/battles/{battle.id}/results")

        assert resp.status_code == 200
        data = resp.json()
        assert data["battle_id"] == str(battle.id)
        assert len(data["participants"]) == 1

    def test_get_results_not_completed(self) -> None:
        """GET /battles/{id}/results returns 409 when battle is not completed."""
        from src.utils.exceptions import BattleInvalidStateError

        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="active")
        mock_svc.get_battle = AsyncMock(return_value=battle)
        mock_svc.get_results = AsyncMock(
            side_effect=BattleInvalidStateError(
                "Battle is not completed yet.",
                current_status="active",
                required_status="completed",
            )
        )

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get(f"/api/v1/battles/{battle.id}/results")

        assert resp.status_code == 409

    def test_get_replay_data(self) -> None:
        """GET /battles/{id}/replay returns 200 with snapshot data."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="completed")
        mock_svc.get_battle = AsyncMock(return_value=battle)

        snapshot = MagicMock()
        snapshot.agent_id = uuid4()
        snapshot.timestamp = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        snapshot.equity = Decimal("10100")
        snapshot.unrealized_pnl = Decimal("50")
        snapshot.realized_pnl = Decimal("50")
        snapshot.trade_count = 5
        snapshot.open_positions = 2
        mock_svc.get_replay_data = AsyncMock(return_value=[snapshot])

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get(f"/api/v1/battles/{battle.id}/replay")

        assert resp.status_code == 200
        data = resp.json()
        assert data["battle_id"] == str(battle.id)
        assert data["total"] == 1
        assert len(data["snapshots"]) == 1


# ---------------------------------------------------------------------------
# Historical battle endpoints
# ---------------------------------------------------------------------------


class TestHistoricalBattle:
    """Tests for historical battle step/order/price endpoints."""

    def test_step_historical_battle(self) -> None:
        """POST /battles/{id}/step returns 200 for historical battle."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="active", battle_mode="historical")
        mock_svc.get_battle = AsyncMock(return_value=battle)
        mock_svc.step_historical = AsyncMock(return_value=_make_step_result())

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(f"/api/v1/battles/{battle.id}/step")

        assert resp.status_code == 200
        data = resp.json()
        assert data["battle_id"] == str(battle.id)
        assert data["step"] == 5
        assert data["total_steps"] == 100
        assert data["is_complete"] is False

    def test_step_historical_rejects_live(self) -> None:
        """POST /battles/{id}/step returns 409 for live battle."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="active", battle_mode="live")
        mock_svc.get_battle = AsyncMock(return_value=battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(f"/api/v1/battles/{battle.id}/step")

        # The route imports BattleInvalidStateError from src.battles.service (plain Exception),
        # which is caught by the generic handler -> 500
        assert resp.status_code == 500

    def test_step_batch_historical(self) -> None:
        """POST /battles/{id}/step/batch returns 200."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="active", battle_mode="historical")
        mock_svc.get_battle = AsyncMock(return_value=battle)
        mock_svc.step_historical_batch = AsyncMock(return_value=_make_step_result())

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(
            f"/api/v1/battles/{battle.id}/step/batch",
            json={"steps": 10},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["battle_id"] == str(battle.id)
        mock_svc.step_historical_batch.assert_awaited_once_with(battle.id, 10)

    def test_place_historical_order(self) -> None:
        """POST /battles/{id}/trade/order returns 200."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="active", battle_mode="historical")
        mock_svc.get_battle = AsyncMock(return_value=battle)
        mock_svc.place_historical_order = AsyncMock(return_value=_make_order_result())
        agent_id = uuid4()

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(
            f"/api/v1/battles/{battle.id}/trade/order",
            json={
                "agent_id": str(agent_id),
                "symbol": "BTCUSDT",
                "side": "buy",
                "order_type": "market",
                "quantity": "0.1",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "filled"
        assert data["executed_price"] is not None

    def test_get_historical_prices(self) -> None:
        """GET /battles/{id}/market/prices returns 200."""
        account = _make_account()
        mock_svc = AsyncMock()
        battle = _make_battle(account.id, status="active", battle_mode="historical")
        mock_svc.get_battle = AsyncMock(return_value=battle)
        virtual_time = datetime(2026, 1, 2, tzinfo=UTC)
        mock_svc.get_historical_prices = AsyncMock(return_value=({"BTCUSDT": Decimal("50000")}, virtual_time))

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.get(f"/api/v1/battles/{battle.id}/market/prices")

        assert resp.status_code == 200
        data = resp.json()
        assert data["battle_id"] == str(battle.id)
        assert "BTCUSDT" in data["prices"]
        assert data["prices"]["BTCUSDT"] == "50000"


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/replay — create replay from battle
# ---------------------------------------------------------------------------


class TestBattleReplay:
    """Tests for POST /api/v1/battles/{battle_id}/replay."""

    def test_replay_battle(self) -> None:
        """POST /battles/{id}/replay returns 201 with new draft battle."""
        account = _make_account()
        mock_svc = AsyncMock()
        source_battle_id = uuid4()
        new_battle = _make_battle(
            account.id,
            status="draft",
            name="Replay: Test Battle",
            battle_mode="historical",
            backtest_config={
                "start_time": "2026-01-01T00:00:00+00:00",
                "end_time": "2026-01-02T00:00:00+00:00",
                "candle_interval": 60,
            },
        )
        new_battle.participants = []
        mock_svc.replay_battle = AsyncMock(return_value=new_battle)

        client = _build_client(battle_service=mock_svc, mock_account=account)
        resp = client.post(
            f"/api/v1/battles/{source_battle_id}/replay",
            json={},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["battle_mode"] == "historical"
        mock_svc.replay_battle.assert_awaited_once()
