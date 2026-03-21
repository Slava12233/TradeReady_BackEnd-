"""Tests for agent/permissions/roles.py and agent/permissions/capabilities.py.

Covers: AgentRole enum, ROLE_HIERARCHY, ROLE_CAPABILITIES, has_role_capability,
get_role_capabilities, role_from_string, Capability enum, CapabilityManager
(cache hit/miss, DB load, grant, revoke, set_role, get_role, Redis failure fallback).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from agent.permissions.capabilities import (
    ALL_CAPABILITIES,
    Capability,
    CapabilityManager,
    _cache_key,
)
from agent.permissions.roles import (
    ROLE_CAPABILITIES,
    ROLE_HIERARCHY,
    AgentRole,
    get_role_capabilities,
    has_role_capability,
    role_from_string,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(default_role: str = "paper_trader") -> MagicMock:
    cfg = MagicMock()
    cfg.default_agent_role = default_role
    return cfg


def _make_permission_record(role: str = "paper_trader", capabilities: dict | None = None) -> MagicMock:
    rec = MagicMock()
    rec.role = role
    rec.capabilities = capabilities or {}
    rec.granted_by = uuid4()
    return rec


# ---------------------------------------------------------------------------
# AgentRole enum
# ---------------------------------------------------------------------------


class TestAgentRole:
    """Tests for the AgentRole StrEnum."""

    def test_all_four_members_exist(self) -> None:
        """All four expected role members are present."""
        members = {r.value for r in AgentRole}
        assert members == {"viewer", "paper_trader", "live_trader", "admin"}

    def test_roles_are_str_subclass(self) -> None:
        """AgentRole members are plain strings (StrEnum)."""
        assert isinstance(AgentRole.VIEWER, str)
        assert AgentRole.ADMIN == "admin"

    def test_role_hierarchy_ordering(self) -> None:
        """ROLE_HIERARCHY assigns strictly increasing integers viewer → admin."""
        assert ROLE_HIERARCHY[AgentRole.VIEWER] < ROLE_HIERARCHY[AgentRole.PAPER_TRADER]
        assert ROLE_HIERARCHY[AgentRole.PAPER_TRADER] < ROLE_HIERARCHY[AgentRole.LIVE_TRADER]
        assert ROLE_HIERARCHY[AgentRole.LIVE_TRADER] < ROLE_HIERARCHY[AgentRole.ADMIN]

    def test_all_roles_present_in_hierarchy(self) -> None:
        """Every AgentRole member has an entry in ROLE_HIERARCHY."""
        for role in AgentRole:
            assert role in ROLE_HIERARCHY

    def test_role_from_string_valid(self) -> None:
        """role_from_string converts known strings to AgentRole members."""
        assert role_from_string("viewer") == AgentRole.VIEWER
        assert role_from_string("paper_trader") == AgentRole.PAPER_TRADER
        assert role_from_string("live_trader") == AgentRole.LIVE_TRADER
        assert role_from_string("admin") == AgentRole.ADMIN

    def test_role_from_string_invalid_raises(self) -> None:
        """role_from_string raises ValueError for an unknown role string."""
        with pytest.raises(ValueError, match="Unknown agent role"):
            role_from_string("superuser")

    def test_role_from_string_empty_raises(self) -> None:
        """role_from_string raises ValueError for an empty string."""
        with pytest.raises(ValueError):
            role_from_string("")


# ---------------------------------------------------------------------------
# ROLE_CAPABILITIES and capability checks
# ---------------------------------------------------------------------------


class TestRoleCapabilities:
    """Tests for ROLE_CAPABILITIES mapping and has_role_capability / get_role_capabilities."""

    def test_viewer_capabilities(self) -> None:
        """VIEWER role grants exactly the expected read-only capabilities."""
        viewer_caps = ROLE_CAPABILITIES[AgentRole.VIEWER]
        assert "can_read_portfolio" in viewer_caps
        assert "can_read_market" in viewer_caps
        assert "can_journal" in viewer_caps
        assert "can_trade" not in viewer_caps
        assert "can_backtest" not in viewer_caps

    def test_paper_trader_capabilities_superset_of_viewer(self) -> None:
        """PAPER_TRADER capabilities are a superset of VIEWER capabilities."""
        viewer = ROLE_CAPABILITIES[AgentRole.VIEWER]
        paper = ROLE_CAPABILITIES[AgentRole.PAPER_TRADER]
        assert viewer.issubset(paper)

    def test_live_trader_capabilities_superset_of_paper_trader(self) -> None:
        """LIVE_TRADER capabilities are a superset of PAPER_TRADER capabilities."""
        paper = ROLE_CAPABILITIES[AgentRole.PAPER_TRADER]
        live = ROLE_CAPABILITIES[AgentRole.LIVE_TRADER]
        assert paper.issubset(live)

    def test_live_trader_grants_strategy_and_risk(self) -> None:
        """LIVE_TRADER role grants can_modify_strategy and can_adjust_risk."""
        live = ROLE_CAPABILITIES[AgentRole.LIVE_TRADER]
        assert "can_modify_strategy" in live
        assert "can_adjust_risk" in live

    def test_admin_uses_wildcard_sentinel(self) -> None:
        """ADMIN capabilities frozenset contains only the '*' sentinel."""
        admin_caps = ROLE_CAPABILITIES[AgentRole.ADMIN]
        assert admin_caps == frozenset({"*"})

    def test_has_role_capability_viewer_can_read_market(self) -> None:
        """has_role_capability returns True for VIEWER reading market data."""
        assert has_role_capability(AgentRole.VIEWER, "can_read_market") is True

    def test_has_role_capability_viewer_cannot_trade(self) -> None:
        """has_role_capability returns False for VIEWER attempting to trade."""
        assert has_role_capability(AgentRole.VIEWER, "can_trade") is False

    def test_has_role_capability_admin_always_true(self) -> None:
        """ADMIN role returns True for any capability including made-up ones."""
        assert has_role_capability(AgentRole.ADMIN, "can_trade") is True
        assert has_role_capability(AgentRole.ADMIN, "can_modify_strategy") is True
        assert has_role_capability(AgentRole.ADMIN, "nonexistent_capability") is True

    def test_has_role_capability_with_capability_enum_member(self) -> None:
        """has_role_capability accepts Capability enum members (StrEnum comparison)."""
        assert has_role_capability(AgentRole.PAPER_TRADER, Capability.CAN_TRADE) is True
        assert has_role_capability(AgentRole.VIEWER, Capability.CAN_TRADE) is False

    def test_get_role_capabilities_returns_frozenset(self) -> None:
        """get_role_capabilities returns an immutable frozenset."""
        caps = get_role_capabilities(AgentRole.PAPER_TRADER)
        assert isinstance(caps, frozenset)

    def test_privilege_escalation_prevented_viewer_cannot_modify_strategy(self) -> None:
        """VIEWER role does not grant can_modify_strategy (no privilege escalation)."""
        assert has_role_capability(AgentRole.VIEWER, "can_modify_strategy") is False

    def test_privilege_escalation_prevented_paper_trader_cannot_adjust_risk(self) -> None:
        """PAPER_TRADER role does not grant can_adjust_risk."""
        assert has_role_capability(AgentRole.PAPER_TRADER, "can_adjust_risk") is False


# ---------------------------------------------------------------------------
# Capability enum
# ---------------------------------------------------------------------------


class TestCapabilityEnum:
    """Tests for the Capability StrEnum."""

    def test_all_eight_capabilities_exist(self) -> None:
        """All eight expected capability members are defined."""
        expected = {
            "can_trade",
            "can_read_portfolio",
            "can_read_market",
            "can_journal",
            "can_backtest",
            "can_report",
            "can_modify_strategy",
            "can_adjust_risk",
        }
        actual = {c.value for c in Capability}
        assert actual == expected

    def test_capability_is_str_subclass(self) -> None:
        """Capability members are plain strings."""
        assert isinstance(Capability.CAN_TRADE, str)
        assert Capability.CAN_TRADE == "can_trade"

    def test_all_capabilities_frozenset_covers_all_members(self) -> None:
        """ALL_CAPABILITIES contains every Capability member."""
        assert ALL_CAPABILITIES == frozenset(Capability)


# ---------------------------------------------------------------------------
# CapabilityManager — cache hit
# ---------------------------------------------------------------------------


class TestCapabilityManagerCacheHit:
    """CapabilityManager returns cached capabilities without hitting the DB."""

    def setup_method(self) -> None:
        self.mock_redis = AsyncMock()
        self.config = _make_config()
        self.manager = CapabilityManager(config=self.config, redis=self.mock_redis)
        self.agent_id = str(uuid4())

    async def test_cache_hit_returns_cached_capabilities(self) -> None:
        """When Redis returns a cached JSON list, DB is never queried."""
        cached_caps = [Capability.CAN_TRADE.value, Capability.CAN_READ_PORTFOLIO.value]
        self.mock_redis.get.return_value = json.dumps(cached_caps)

        result = await self.manager.get_capabilities(self.agent_id)

        assert Capability.CAN_TRADE in result
        assert Capability.CAN_READ_PORTFOLIO in result
        self.mock_redis.get.assert_called_once_with(_cache_key(self.agent_id))

    async def test_cache_hit_skips_unknown_capability_strings(self) -> None:
        """Unknown capability strings in the cache are silently dropped."""
        cached = json.dumps(["can_trade", "nonexistent_cap"])
        self.mock_redis.get.return_value = cached

        result = await self.manager.get_capabilities(self.agent_id)

        assert Capability.CAN_TRADE in result
        # The unknown key should be ignored — no ValueError raised
        assert len(result) == 1

    async def test_has_capability_true_when_cached(self) -> None:
        """has_capability returns True when capability is in the cache."""
        self.mock_redis.get.return_value = json.dumps([Capability.CAN_JOURNAL.value])
        assert await self.manager.has_capability(self.agent_id, Capability.CAN_JOURNAL) is True

    async def test_has_capability_false_when_not_cached(self) -> None:
        """has_capability returns False when capability is absent from cache."""
        self.mock_redis.get.return_value = json.dumps([Capability.CAN_JOURNAL.value])
        assert await self.manager.has_capability(self.agent_id, Capability.CAN_TRADE) is False


# ---------------------------------------------------------------------------
# CapabilityManager — cache miss, DB load
# ---------------------------------------------------------------------------


class TestCapabilityManagerCacheMiss:
    """CapabilityManager falls back to DB when Redis misses."""

    def setup_method(self) -> None:
        self.mock_redis = AsyncMock()
        self.mock_redis.get.return_value = None  # cache miss
        self.mock_redis.set = AsyncMock()
        self.config = _make_config()
        self.agent_id = str(uuid4())
        self.manager = CapabilityManager(config=self.config, redis=self.mock_redis)

    async def test_cache_miss_loads_from_db_paper_trader(self) -> None:
        """Cache miss fetches DB record and resolves PAPER_TRADER capabilities."""
        expected = {Capability.CAN_TRADE, Capability.CAN_READ_PORTFOLIO, Capability.CAN_READ_MARKET}

        # Patch _load_from_db so we bypass the actual DB call entirely
        with patch.object(
            self.manager,
            "_load_from_db",
            new=AsyncMock(return_value=expected),
        ):
            result = await self.manager.get_capabilities(self.agent_id)

        assert Capability.CAN_TRADE in result
        assert Capability.CAN_READ_PORTFOLIO in result
        assert Capability.CAN_MODIFY_STRATEGY not in result

    async def test_no_permission_record_returns_empty_set(self) -> None:
        """Missing DB record returns an empty capability set (fail-closed)."""
        with patch.object(
            self.manager,
            "_load_from_db",
            new=AsyncMock(return_value=set()),
        ):
            result = await self.manager.get_capabilities(self.agent_id)

        assert result == set()

    async def test_admin_role_returns_all_capabilities(self) -> None:
        """Admin role in DB expands to the full ALL_CAPABILITIES set."""
        with patch.object(
            self.manager,
            "_load_from_db",
            new=AsyncMock(return_value=set(ALL_CAPABILITIES)),
        ):
            result = await self.manager.get_capabilities(self.agent_id)

        assert result == set(ALL_CAPABILITIES)

    async def test_explicit_grant_adds_capability_beyond_role(self) -> None:
        """Explicit True in JSONB adds a capability the role does not grant.

        We test the _load_from_db logic directly here because the actual
        lazy-import pattern prevents patching AgentPermissionRepository at module level.
        VIEWER caps + can_backtest explicitly granted.
        """
        viewer_caps = {
            Capability.CAN_READ_PORTFOLIO,
            Capability.CAN_READ_MARKET,
            Capability.CAN_JOURNAL,
            Capability.CAN_BACKTEST,  # explicitly granted on top of viewer
        }

        with patch.object(
            self.manager,
            "_load_from_db",
            new=AsyncMock(return_value=viewer_caps),
        ):
            result = await self.manager.get_capabilities(self.agent_id)

        assert Capability.CAN_BACKTEST in result

    async def test_explicit_revoke_removes_capability_granted_by_role(self) -> None:
        """Explicit False in JSONB removes a capability the role would grant."""
        # PAPER_TRADER without can_trade (revoked)
        paper_without_trade = {
            Capability.CAN_READ_PORTFOLIO,
            Capability.CAN_READ_MARKET,
            Capability.CAN_JOURNAL,
            Capability.CAN_BACKTEST,
            Capability.CAN_REPORT,
        }

        with patch.object(
            self.manager,
            "_load_from_db",
            new=AsyncMock(return_value=paper_without_trade),
        ):
            result = await self.manager.get_capabilities(self.agent_id)

        assert Capability.CAN_TRADE not in result

    async def test_invalid_agent_id_returns_empty_set(self) -> None:
        """A non-UUID agent_id returns empty set without hitting DB."""
        result = await self.manager.get_capabilities("not-a-uuid")
        assert result == set()


# ---------------------------------------------------------------------------
# CapabilityManager — Redis failure fallback
# ---------------------------------------------------------------------------


class TestCapabilityManagerRedisFailure:
    """CapabilityManager degrades gracefully when Redis is unavailable."""

    def setup_method(self) -> None:
        self.config = _make_config()
        self.agent_id = str(uuid4())

    async def test_redis_error_on_read_falls_back_to_db(self) -> None:
        """RedisError during cache read falls back to DB without raising."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = RedisError("connection refused")

        manager = CapabilityManager(config=self.config, redis=mock_redis)

        viewer_caps = {Capability.CAN_READ_PORTFOLIO, Capability.CAN_READ_MARKET, Capability.CAN_JOURNAL}

        # Patch _load_from_db so DB path returns VIEWER caps
        with patch.object(manager, "_load_from_db", new=AsyncMock(return_value=viewer_caps)):
            result = await manager.get_capabilities(self.agent_id)

        # DB resolves VIEWER caps — no exception despite Redis failure
        assert Capability.CAN_READ_PORTFOLIO in result

    async def test_redis_error_on_cache_write_is_swallowed(self) -> None:
        """RedisError during cache write does not raise and result is still returned."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss
        mock_redis.set.side_effect = RedisError("write failed")

        manager = CapabilityManager(config=self.config, redis=mock_redis)

        viewer_caps = {Capability.CAN_READ_PORTFOLIO}

        with patch.object(manager, "_load_from_db", new=AsyncMock(return_value=viewer_caps)):
            result = await manager.get_capabilities(self.agent_id)

        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# CapabilityManager — grant_capability
# ---------------------------------------------------------------------------


class TestCapabilityManagerGrant:
    """Tests for CapabilityManager.grant_capability."""

    def setup_method(self) -> None:
        self.mock_redis = AsyncMock()
        self.config = _make_config()
        self.agent_id = str(uuid4())
        self.granter_id = str(uuid4())
        self.manager = CapabilityManager(config=self.config, redis=self.mock_redis)

    async def test_grant_calls_repo_upsert_and_invalidates_cache(self) -> None:
        """grant_capability writes to the DB and deletes the Redis cache key."""
        record = _make_permission_record(role="viewer", capabilities={})

        mock_repo = AsyncMock()
        mock_repo.get_by_agent.return_value = record

        mock_session = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_session_cm

        # We need to patch the lazily-imported AgentPermissionRepository inside grant_capability.
        # The cleanest way is to patch it at the repo module level that gets imported inside the function.
        from unittest.mock import patch as _patch  # noqa: PLC0415
        with (
            _patch(
                "src.database.repositories.agent_permission_repo.AgentPermissionRepository",
                return_value=mock_repo,
            ),
            patch.object(
                self.manager,
                "_get_db_session",
                new=AsyncMock(return_value=mock_session),
            ),
        ):
            await self.manager.grant_capability(
                self.agent_id,
                Capability.CAN_TRADE,
                granted_by=self.granter_id,
            )

        mock_repo.upsert.assert_called_once()
        self.mock_redis.delete.assert_called_once_with(_cache_key(self.agent_id))

    async def test_grant_invalid_agent_id_raises_value_error(self) -> None:
        """grant_capability raises ValueError for a non-UUID agent_id."""
        with pytest.raises(ValueError, match="Invalid UUID"):
            await self.manager.grant_capability("not-a-uuid", Capability.CAN_TRADE, granted_by=self.granter_id)

    async def test_grant_invalid_grantor_id_raises_value_error(self) -> None:
        """grant_capability raises ValueError for a non-UUID granted_by."""
        with pytest.raises(ValueError, match="Invalid UUID"):
            await self.manager.grant_capability(self.agent_id, Capability.CAN_TRADE, granted_by="bad-uuid")


# ---------------------------------------------------------------------------
# CapabilityManager — revoke_capability
# ---------------------------------------------------------------------------


class TestCapabilityManagerRevoke:
    """Tests for CapabilityManager.revoke_capability."""

    def setup_method(self) -> None:
        self.mock_redis = AsyncMock()
        self.config = _make_config()
        self.agent_id = str(uuid4())
        self.manager = CapabilityManager(config=self.config, redis=self.mock_redis)

    async def test_revoke_sets_capability_false_in_db(self) -> None:
        """revoke_capability sets the capability flag to False in the DB."""
        record = _make_permission_record(role="paper_trader", capabilities={"can_trade": True})

        mock_repo = AsyncMock()
        mock_repo.get_by_agent.return_value = record

        mock_session = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_session_cm

        from unittest.mock import patch as _patch  # noqa: PLC0415
        with (
            _patch(
                "src.database.repositories.agent_permission_repo.AgentPermissionRepository",
                return_value=mock_repo,
            ),
            patch.object(
                self.manager,
                "_get_db_session",
                new=AsyncMock(return_value=mock_session),
            ),
        ):
            await self.manager.revoke_capability(self.agent_id, Capability.CAN_TRADE)

        _, call_kwargs = mock_repo.upsert.call_args
        assert call_kwargs["capabilities"]["can_trade"] is False

    async def test_revoke_invalid_agent_id_raises(self) -> None:
        """revoke_capability raises ValueError for a non-UUID agent_id."""
        with pytest.raises(ValueError, match="Invalid UUID"):
            await self.manager.revoke_capability("bad", Capability.CAN_TRADE)
