"""Granular capability management for the agent permission system.

Capabilities are fine-grained feature flags that control what actions an
agent is allowed to perform.  They can be granted or revoked *independently*
of the agent's broad :class:`~agent.permissions.roles.AgentRole` — the
effective capability set is the union of role-based grants and explicit
per-agent overrides stored in the ``agent_permissions.capabilities`` JSONB
column.

Redis caching strategy
-----------------------
``CapabilityManager.get_capabilities()`` and ``has_capability()`` check a
Redis key before hitting Postgres.  The cache key pattern is::

    agent:permissions:{agent_id}

The value is a JSON-encoded list of capability strings that the agent
currently holds (role grants + explicit grants, minus explicit revocations).
TTL is :data:`_PERMISSIONS_CACHE_TTL` (300 seconds).

Any mutating operation (``grant_capability``, ``revoke_capability``,
``set_role``) calls ``_invalidate_cache()`` to delete the key immediately,
so the next read re-fetches from Postgres.

All Redis operations catch :class:`~redis.exceptions.RedisError` and degrade
gracefully to a Postgres-only path so that a Redis outage never blocks
permission checks.

Example::

    from agent.permissions.capabilities import Capability, CapabilityManager
    from agent.permissions.roles import AgentRole
    from agent.config import AgentConfig

    config = AgentConfig()
    manager = CapabilityManager(config=config)

    caps = await manager.get_capabilities("agent-uuid")
    allowed = await manager.has_capability("agent-uuid", Capability.CAN_TRADE)

    await manager.grant_capability("agent-uuid", Capability.CAN_TRADE, granted_by="account-uuid")
    await manager.revoke_capability("agent-uuid", Capability.CAN_TRADE)
    await manager.set_role("agent-uuid", AgentRole.LIVE_TRADER, granted_by="account-uuid")
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from redis.exceptions import RedisError

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11 shim
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from agent.config import AgentConfig
    from agent.permissions.roles import AgentRole

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Cache constants
# ---------------------------------------------------------------------------

# Key pattern: agent:permissions:{agent_id}  ->  JSON list of capability strings
_PERMISSIONS_CACHE_KEY = "agent:permissions:{agent_id}"

# 5-minute TTL — balances freshness vs Postgres query rate.
_PERMISSIONS_CACHE_TTL: int = 300


def _cache_key(agent_id: str) -> str:
    return _PERMISSIONS_CACHE_KEY.format(agent_id=agent_id)


# ---------------------------------------------------------------------------
# Capability enum
# ---------------------------------------------------------------------------


class Capability(StrEnum):
    """Granular capability flags that gate individual agent actions.

    Each value is the string key used in the ``capabilities`` JSONB column of
    the ``agent_permissions`` table and in Redis cache entries.

    Attributes:
        CAN_TRADE:            Place and cancel orders (any side).
        CAN_READ_PORTFOLIO:   Read portfolio state, positions, and PnL.
        CAN_READ_MARKET:      Read market data (prices, candles, order book).
        CAN_JOURNAL:          Write trading journal entries.
        CAN_BACKTEST:         Create and run backtest sessions.
        CAN_REPORT:           Generate and export performance reports.
        CAN_MODIFY_STRATEGY:  Create, update, and deploy strategies.
        CAN_ADJUST_RISK:      Modify risk parameters (stop-loss, position
                              limits, max exposure).
    """

    CAN_TRADE = "can_trade"
    CAN_READ_PORTFOLIO = "can_read_portfolio"
    CAN_READ_MARKET = "can_read_market"
    CAN_JOURNAL = "can_journal"
    CAN_BACKTEST = "can_backtest"
    CAN_REPORT = "can_report"
    CAN_MODIFY_STRATEGY = "can_modify_strategy"
    CAN_ADJUST_RISK = "can_adjust_risk"


# Complete set of all defined capabilities for wildcard expansion.
ALL_CAPABILITIES: frozenset[Capability] = frozenset(Capability)


# ---------------------------------------------------------------------------
# CapabilityManager
# ---------------------------------------------------------------------------


class CapabilityManager:
    """Manages granular capability grants for agents.

    Capabilities are resolved by combining the agent's role-based grants
    (from :data:`~agent.permissions.roles.ROLE_CAPABILITIES`) with any
    explicit per-agent overrides stored in the ``agent_permissions`` table.
    The resolved set is cached in Redis with a 5-minute TTL.

    The manager requires access to the Postgres-backed
    :class:`~src.database.repositories.agent_permission_repo.AgentPermissionRepository`
    and optionally a ``redis.asyncio.Redis`` instance for caching.  Both are
    injected lazily so that the manager is safe to instantiate without a live
    database or Redis connection (useful in tests with mocks).

    Args:
        config: :class:`~agent.config.AgentConfig` instance — used to obtain
            the shared Redis connection on first use.
        session_factory: Optional async callable that returns an
            :class:`~sqlalchemy.ext.asyncio.AsyncSession`.  When ``None``,
            ``get_async_session()`` from ``src.database.session`` is used.
        redis: Optional pre-built ``redis.asyncio.Redis`` instance.  When
            ``None``, the handle is obtained lazily from
            :func:`~src.cache.redis_client.get_redis_client`.  Pass an
            explicit instance in tests to inject a mock.

    Example::

        manager = CapabilityManager(config=config)
        caps = await manager.get_capabilities("agent-uuid")
        ok = await manager.has_capability("agent-uuid", Capability.CAN_TRADE)
    """

    def __init__(
        self,
        config: AgentConfig,
        redis: aioredis.Redis | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._config = config
        self._redis: aioredis.Redis | None = redis  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_redis(self) -> aioredis.Redis:  # type: ignore[type-arg]
        """Return the shared Redis client, initialising the singleton lazily.

        Returns:
            A connected ``redis.asyncio.Redis`` instance.
        """
        if self._redis is None:
            from src.cache.redis_client import get_redis_client  # noqa: PLC0415

            self._redis = await get_redis_client()
        return self._redis

    async def _get_db_session(self) -> AsyncSession:
        """Return a new async DB session from the shared session factory.

        Returns:
            An :class:`~sqlalchemy.ext.asyncio.AsyncSession` (context
            manager).
        """
        from src.database.session import get_session_factory  # noqa: PLC0415

        factory = get_session_factory()
        return factory()

    async def _load_from_db(self, agent_id: str) -> set[Capability]:
        """Fetch the resolved capability set for *agent_id* from Postgres.

        The resolved set is the union of:

        1. Capabilities granted by the agent's current role (via
           :data:`~agent.permissions.roles.ROLE_CAPABILITIES`).
        2. Capabilities explicitly set to ``true`` in the ``capabilities``
           JSONB column (independent grants).

        An explicit ``false`` value in the JSONB column *overrides* the
        role-based grant for that capability (revocation).

        If no permission record exists the agent is treated as having
        *no capabilities* (fail-closed).

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Set of :class:`Capability` values the agent currently holds.
        """
        # Import here to avoid circular imports at module load time.
        from src.database.repositories.agent_permission_repo import (  # noqa: PLC0415
            AgentPermissionNotFoundError,
            AgentPermissionRepository,
        )

        from agent.permissions.roles import (  # noqa: PLC0415
            AgentRole,
            has_role_capability,
        )

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError) as exc:
            logger.warning(
                "capability_manager.invalid_agent_id",
                agent_id=agent_id,
                error=str(exc),
            )
            return set()

        session = await self._get_db_session()
        try:
            async with session as s:
                repo = AgentPermissionRepository(s)
                try:
                    record = await repo.get_by_agent(agent_uuid)
                except AgentPermissionNotFoundError:
                    logger.debug(
                        "capability_manager.no_permission_record",
                        agent_id=agent_id,
                    )
                    return set()

                # Resolve role-based grants.
                try:
                    role = AgentRole(record.role)
                except ValueError:
                    logger.warning(
                        "capability_manager.unknown_role",
                        agent_id=agent_id,
                        role=record.role,
                    )
                    role = AgentRole.VIEWER

                # Admin wildcard: expand to all capabilities immediately.
                if role == AgentRole.ADMIN:
                    return set(ALL_CAPABILITIES)

                role_caps: set[Capability] = {
                    cap
                    for cap in Capability
                    if has_role_capability(role, cap)
                }

                # Apply explicit JSONB overrides.
                explicit: dict[str, Any] = record.capabilities or {}
                for key, value in explicit.items():
                    try:
                        cap = Capability(key)
                    except ValueError:
                        # Unknown capability key — skip silently.
                        continue
                    if value is True or value == 1:
                        role_caps.add(cap)
                    elif value is False or value == 0:
                        role_caps.discard(cap)

                return role_caps

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "capability_manager.db_load_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return set()

    # ------------------------------------------------------------------
    # Cache operations
    # ------------------------------------------------------------------

    async def _read_cache(self, agent_id: str) -> set[Capability] | None:
        """Return the cached capability set for *agent_id*, or ``None`` on miss.

        Returns ``None`` on any Redis error so the caller falls back to
        Postgres.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Cached :class:`Capability` set, or ``None`` if not cached.
        """
        try:
            redis = await self._get_redis()
            raw: str | None = await redis.get(_cache_key(agent_id))
            if raw is None:
                return None
            data: list[str] = json.loads(raw)
            caps: set[Capability] = set()
            for item in data:
                try:
                    caps.add(Capability(item))
                except ValueError:
                    pass
            return caps
        except RedisError as exc:
            logger.debug(
                "capability_manager.cache_read_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return None
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "capability_manager.cache_deserialise_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return None

    async def _write_cache(self, agent_id: str, caps: set[Capability]) -> None:
        """Write the capability set for *agent_id* to Redis with TTL.

        Silently swallows Redis errors so a cache write failure never blocks
        the caller.

        Args:
            agent_id: UUID string of the agent.
            caps: The resolved capability set to store.
        """
        try:
            redis = await self._get_redis()
            payload = json.dumps([cap.value for cap in caps])
            await redis.set(_cache_key(agent_id), payload, ex=_PERMISSIONS_CACHE_TTL)
            logger.debug(
                "capability_manager.cache_written",
                agent_id=agent_id,
                count=len(caps),
                ttl=_PERMISSIONS_CACHE_TTL,
            )
        except RedisError as exc:
            logger.debug(
                "capability_manager.cache_write_error",
                agent_id=agent_id,
                error=str(exc),
            )
        except (TypeError, ValueError) as exc:
            logger.warning(
                "capability_manager.cache_serialise_error",
                agent_id=agent_id,
                error=str(exc),
            )

    async def _invalidate_cache(self, agent_id: str) -> None:
        """Delete the cached capability entry for *agent_id*.

        Must be called after any mutation (role change, grant, or revoke) so
        the next read forces a fresh Postgres lookup.

        Args:
            agent_id: UUID string of the agent.
        """
        try:
            redis = await self._get_redis()
            await redis.delete(_cache_key(agent_id))
            logger.debug(
                "capability_manager.cache_invalidated",
                agent_id=agent_id,
            )
        except RedisError as exc:
            logger.debug(
                "capability_manager.cache_invalidate_error",
                agent_id=agent_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_capabilities(self, agent_id: str) -> set[Capability]:
        """Return the full resolved capability set for *agent_id*.

        Resolution order:

        1. Redis cache hit → return immediately (5-minute TTL).
        2. Postgres read → resolve role + JSONB overrides → cache → return.

        On any DB or deserialisation error the method returns an empty set
        (fail-closed).  Callers should always handle the empty-set case.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            :class:`set` of :class:`Capability` values the agent currently
            holds.
        """
        cached = await self._read_cache(agent_id)
        if cached is not None:
            logger.debug(
                "capability_manager.cache_hit",
                agent_id=agent_id,
                count=len(cached),
            )
            return cached

        caps = await self._load_from_db(agent_id)
        await self._write_cache(agent_id, caps)
        return caps

    async def has_capability(
        self, agent_id: str, capability: Capability
    ) -> bool:
        """Return ``True`` if *agent_id* currently holds *capability*.

        Resolves via :meth:`get_capabilities` so Redis caching applies.

        Args:
            agent_id: UUID string of the agent.
            capability: The :class:`Capability` to check.

        Returns:
            ``True`` if the agent holds the capability, ``False`` otherwise
            (including on any error — fail-closed).
        """
        caps = await self.get_capabilities(agent_id)
        return capability in caps

    async def grant_capability(
        self,
        agent_id: str,
        capability: Capability,
        granted_by: str,
    ) -> None:
        """Explicitly grant *capability* to *agent_id* in Postgres.

        Performs an upsert that sets the capability key to ``true`` in the
        ``capabilities`` JSONB column.  If the agent already has this
        capability through their role, the explicit grant is redundant but
        harmless.

        The Redis cache is invalidated after the write.

        Args:
            agent_id: UUID string of the agent receiving the capability.
            capability: The :class:`Capability` to grant.
            granted_by: UUID string of the account performing the grant.

        Raises:
            ValueError: If *agent_id* or *granted_by* are not valid UUIDs.
            Exception: Propagates unexpected DB errors after logging.
        """
        from src.database.repositories.agent_permission_repo import (  # noqa: PLC0415
            AgentPermissionNotFoundError,
            AgentPermissionRepository,
        )

        try:
            agent_uuid = UUID(agent_id)
            grantor_uuid = UUID(granted_by)
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"Invalid UUID for agent_id={agent_id!r} or granted_by={granted_by!r}"
            ) from exc

        session = await self._get_db_session()
        try:
            async with session.begin():
                repo = AgentPermissionRepository(session)

                # Read current record to merge capabilities.
                try:
                    record = await repo.get_by_agent(agent_uuid)
                    current_caps: dict[str, Any] = dict(record.capabilities or {})
                    current_role: str = record.role
                except AgentPermissionNotFoundError:
                    current_caps = {}
                    current_role = self._config.default_agent_role

                current_caps[capability.value] = True
                await repo.upsert(
                    agent_id=agent_uuid,
                    granted_by=grantor_uuid,
                    role=current_role,
                    capabilities=current_caps,
                )

            logger.info(
                "capability_manager.capability_granted",
                agent_id=agent_id,
                capability=capability.value,
                granted_by=granted_by,
            )
        except (ValueError, TypeError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "capability_manager.grant_error",
                agent_id=agent_id,
                capability=capability.value,
                error=str(exc),
            )
            raise
        finally:
            await self._invalidate_cache(agent_id)

    async def revoke_capability(
        self,
        agent_id: str,
        capability: Capability,
    ) -> None:
        """Explicitly revoke *capability* from *agent_id* in Postgres.

        Sets the capability key to ``false`` in the ``capabilities`` JSONB
        column.  This overrides any role-based grant for the same capability
        — i.e., even if the agent's role would normally grant the capability,
        the explicit ``false`` takes precedence.

        The Redis cache is invalidated after the write.

        Args:
            agent_id: UUID string of the agent losing the capability.
            capability: The :class:`Capability` to revoke.

        Raises:
            ValueError: If *agent_id* is not a valid UUID.
            Exception: Propagates unexpected DB errors after logging.
        """
        from src.database.repositories.agent_permission_repo import (  # noqa: PLC0415
            AgentPermissionNotFoundError,
            AgentPermissionRepository,
        )

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"Invalid UUID for agent_id={agent_id!r}") from exc

        session = await self._get_db_session()
        try:
            async with session.begin():
                repo = AgentPermissionRepository(session)

                # Read current record to merge capabilities.
                try:
                    record = await repo.get_by_agent(agent_uuid)
                    current_caps: dict[str, Any] = dict(record.capabilities or {})
                    current_role: str = record.role
                    grantor_uuid = record.granted_by
                except AgentPermissionNotFoundError:
                    current_caps = {}
                    current_role = self._config.default_agent_role
                    grantor_uuid = agent_uuid  # self-grant placeholder

                current_caps[capability.value] = False
                await repo.upsert(
                    agent_id=agent_uuid,
                    granted_by=grantor_uuid,
                    role=current_role,
                    capabilities=current_caps,
                )

            logger.info(
                "capability_manager.capability_revoked",
                agent_id=agent_id,
                capability=capability.value,
            )
        except (ValueError, TypeError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "capability_manager.revoke_error",
                agent_id=agent_id,
                capability=capability.value,
                error=str(exc),
            )
            raise
        finally:
            await self._invalidate_cache(agent_id)

    async def set_role(
        self,
        agent_id: str,
        role: AgentRole,
        granted_by: str,
    ) -> None:
        """Change the broad role for *agent_id* and re-derive capabilities.

        Persists the new role via an upsert and preserves any explicit
        per-capability overrides already stored in the ``capabilities`` JSONB
        column.  The Redis cache is invalidated so the next :meth:`get_capabilities`
        call reflects the new role.

        Args:
            agent_id: UUID string of the agent.
            role: The new :class:`~agent.permissions.roles.AgentRole` to
                assign.
            granted_by: UUID string of the account performing the role change.

        Raises:
            ValueError: If *agent_id* or *granted_by* are not valid UUIDs.
            Exception: Propagates unexpected DB errors after logging.
        """
        from src.database.repositories.agent_permission_repo import (  # noqa: PLC0415
            AgentPermissionNotFoundError,
            AgentPermissionRepository,
        )

        try:
            agent_uuid = UUID(agent_id)
            grantor_uuid = UUID(granted_by)
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"Invalid UUID for agent_id={agent_id!r} or granted_by={granted_by!r}"
            ) from exc

        session = await self._get_db_session()
        try:
            async with session.begin():
                repo = AgentPermissionRepository(session)

                # Preserve existing explicit overrides.
                try:
                    record = await repo.get_by_agent(agent_uuid)
                    current_caps: dict[str, Any] = dict(record.capabilities or {})
                except AgentPermissionNotFoundError:
                    current_caps = {}

                await repo.upsert(
                    agent_id=agent_uuid,
                    granted_by=grantor_uuid,
                    role=role.value,
                    capabilities=current_caps,
                )

            logger.info(
                "capability_manager.role_changed",
                agent_id=agent_id,
                new_role=role.value,
                granted_by=granted_by,
            )
        except (ValueError, TypeError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "capability_manager.set_role_error",
                agent_id=agent_id,
                role=role.value,
                error=str(exc),
            )
            raise
        finally:
            await self._invalidate_cache(agent_id)

    async def get_role(self, agent_id: str) -> AgentRole:
        """Return the current :class:`~agent.permissions.roles.AgentRole` for *agent_id*.

        Returns the ``default_agent_role`` from config if no permission record
        exists.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            The agent's current :class:`~agent.permissions.roles.AgentRole`.
        """
        from src.database.repositories.agent_permission_repo import (  # noqa: PLC0415
            AgentPermissionNotFoundError,
            AgentPermissionRepository,
        )

        from agent.permissions.roles import role_from_string  # noqa: PLC0415,F811

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError):
            return role_from_string(self._config.default_agent_role)

        session = await self._get_db_session()
        try:
            async with session as s:
                repo = AgentPermissionRepository(s)
                try:
                    record = await repo.get_by_agent(agent_uuid)
                    return role_from_string(record.role)
                except AgentPermissionNotFoundError:
                    return role_from_string(self._config.default_agent_role)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "capability_manager.get_role_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return role_from_string(self._config.default_agent_role)

