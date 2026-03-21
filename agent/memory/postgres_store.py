"""PostgreSQL-backed implementation of :class:`~agent.memory.store.MemoryStore`.

All database operations are delegated to
:class:`~src.database.repositories.agent_learning_repo.AgentLearningRepository`
— this module never accesses the SQLAlchemy session directly.

Dependency direction:
    PostgresMemoryStore → AgentLearningRepository → AsyncSession → TimescaleDB

Usage::

    from sqlalchemy.ext.asyncio import AsyncSession
    from src.database.repositories.agent_learning_repo import AgentLearningRepository
    from agent.memory.postgres_store import PostgresMemoryStore

    store = PostgresMemoryStore(repo=AgentLearningRepository(session), config=config)
    memory_id = await store.save(memory)
    mem = await store.get(memory_id)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import structlog
from src.database.models import AgentLearning
from src.database.repositories.agent_learning_repo import (
    AgentLearningNotFoundError,
    AgentLearningRepository,
)
from src.utils.exceptions import DatabaseError

from agent.config import AgentConfig
from agent.memory.store import Memory, MemoryNotFoundError, MemoryStore, MemoryType

logger = structlog.get_logger(__name__)


def _orm_to_memory(row: AgentLearning) -> Memory:
    """Convert an :class:`~src.database.models.AgentLearning` ORM row to a
    :class:`~agent.memory.store.Memory` Pydantic model.

    ``confidence`` defaults to ``Decimal("1.0000")`` when the DB column is
    ``NULL`` (the column is nullable in the schema).

    ``last_accessed_at`` falls back to ``created_at`` when ``NULL`` (e.g.
    for newly created rows that have not yet been retrieved).

    Args:
        row: A hydrated SQLAlchemy ``AgentLearning`` instance.

    Returns:
        A fully-populated :class:`Memory` model.
    """
    confidence = Decimal(str(row.confidence)) if row.confidence is not None else Decimal("1.0000")
    last_accessed = row.last_accessed_at if row.last_accessed_at is not None else row.created_at
    source = row.source if row.source is not None else ""

    return Memory(
        id=str(row.id),
        agent_id=str(row.agent_id),
        memory_type=MemoryType(row.memory_type),
        content=row.content,
        source=source,
        confidence=confidence,
        times_reinforced=row.times_reinforced,
        created_at=row.created_at,
        last_accessed_at=last_accessed,
    )


class PostgresMemoryStore(MemoryStore):
    """Postgres-backed long-term memory store for an agent.

    Wraps :class:`~src.database.repositories.agent_learning_repo.AgentLearningRepository`
    to provide the full :class:`~agent.memory.store.MemoryStore` interface.
    All search, ranking, and expiry logic is implemented inside the repository;
    this class is responsible for:

    - Constructing :class:`~src.database.models.AgentLearning` ORM objects
      from :class:`~agent.memory.store.Memory` Pydantic models before writes.
    - Converting ORM rows back to :class:`~agent.memory.store.Memory` after
      reads.
    - Mapping repository-level exceptions to :class:`MemoryNotFoundError` or
      :class:`~src.utils.exceptions.DatabaseError`.
    - Respecting config-driven limits (``memory_search_limit``).

    The caller is responsible for committing the database session after
    successful mutations — this class never calls ``session.commit()``.

    Args:
        repo: An open :class:`AgentLearningRepository` instance backed by a
            live :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        config: The agent configuration; used for ``memory_search_limit`` and
            ``memory_cleanup_confidence_threshold``.

    Example::

        store = PostgresMemoryStore(
            repo=AgentLearningRepository(session),
            config=AgentConfig(),
        )
        memory_id = await store.save(memory)
    """

    def __init__(self, repo: AgentLearningRepository, config: AgentConfig) -> None:
        self._repo = repo
        self._config = config

    # ------------------------------------------------------------------
    # MemoryStore interface
    # ------------------------------------------------------------------

    async def save(self, memory: Memory) -> str:
        """Persist a new memory record and return the server-assigned ID.

        Constructs an :class:`~src.database.models.AgentLearning` ORM object
        from the :class:`~agent.memory.store.Memory` model, adds it to the
        session via :meth:`AgentLearningRepository.create`, and returns the
        server-generated UUID string.

        Args:
            memory: The fully-populated memory to persist.  The ``id`` field
                on ``memory`` is ignored; the database generates a new UUID.

        Returns:
            The server-assigned UUID string for the persisted memory.

        Raises:
            DatabaseError: On any persistence failure.
        """
        orm_row = AgentLearning(
            agent_id=UUID(memory.agent_id),
            memory_type=memory.memory_type.value,
            content=memory.content,
            source=memory.source if memory.source else None,
            confidence=memory.confidence,
            times_reinforced=memory.times_reinforced,
            last_accessed_at=memory.last_accessed_at,
            # expires_at is not set here; callers use forget() for soft-deletion.
        )
        try:
            saved = await self._repo.create(orm_row)
            logger.info(
                "memory.saved",
                memory_id=str(saved.id),
                agent_id=memory.agent_id,
                memory_type=memory.memory_type.value,
            )
            return str(saved.id)
        except DatabaseError:
            raise
        except Exception as exc:
            logger.exception("memory.save.unexpected_error", agent_id=memory.agent_id, error=str(exc))
            raise DatabaseError("Failed to save memory.") from exc

    async def get(self, memory_id: str) -> Memory | None:
        """Retrieve a single memory by its UUID and touch ``last_accessed_at``.

        Returns ``None`` when no record exists with the given ID rather than
        raising an exception; this is more ergonomic for optional-fetch
        patterns.

        Side-effect: calls :meth:`AgentLearningRepository.touch` to record
        that the memory was accessed.

        Args:
            memory_id: String UUID of the memory to retrieve.

        Returns:
            The matching :class:`Memory` or ``None`` if not found.

        Raises:
            DatabaseError: On any persistence failure.
        """
        try:
            row = await self._repo.get_by_id(UUID(memory_id))
        except AgentLearningNotFoundError:
            return None
        except DatabaseError:
            raise
        except Exception as exc:
            logger.exception("memory.get.unexpected_error", memory_id=memory_id, error=str(exc))
            raise DatabaseError("Failed to retrieve memory.") from exc

        # Touch last_accessed_at as a background side-effect; ignore failures.
        try:
            await self._repo.touch(UUID(memory_id))
        except DatabaseError as exc:
            logger.warning("memory.get.touch_failed", memory_id=memory_id, error=str(exc))

        return _orm_to_memory(row)

    async def search(
        self,
        agent_id: str,
        query: str,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Search memories by keyword with recency-weighted ranking.

        Delegates to :meth:`AgentLearningRepository.search` which performs
        a case-insensitive substring match on ``content`` and applies a
        Python-side relevance score combining reinforcement count and recency
        boost (+5 for last 7 days, +2 for last 30 days).

        The effective ``limit`` is capped at ``config.memory_search_limit``
        when the caller passes a higher value, preventing unbounded result
        sets.

        Args:
            agent_id: UUID string of the owning agent.
            query: Keyword or phrase to match against memory content.
            memory_type: If provided, restrict results to this type.
            limit: Maximum results; capped at ``config.memory_search_limit``.

        Returns:
            A list of up to ``limit`` :class:`Memory` objects, best first.

        Raises:
            DatabaseError: On any persistence failure.
        """
        effective_limit = min(limit, self._config.memory_search_limit)
        mt_str = memory_type.value if memory_type is not None else None

        try:
            rows = await self._repo.search(
                agent_id=UUID(agent_id),
                keyword=query,
                memory_type=mt_str,
                exclude_expired=True,
                limit=effective_limit,
            )
        except DatabaseError:
            raise
        except Exception as exc:
            logger.exception("memory.search.unexpected_error", agent_id=agent_id, error=str(exc))
            raise DatabaseError("Failed to search memories.") from exc

        return [_orm_to_memory(row) for row in rows]

    async def reinforce(self, memory_id: str) -> None:
        """Atomically increment the reinforcement counter for a memory.

        Calls :meth:`AgentLearningRepository.reinforce` which issues a single
        ``UPDATE ... SET times_reinforced = times_reinforced + 1, last_accessed_at = now()``
        statement.

        Args:
            memory_id: String UUID of the memory to reinforce.

        Raises:
            MemoryNotFoundError: If no memory with ``memory_id`` exists.
            DatabaseError: On any persistence failure.
        """
        try:
            await self._repo.reinforce(UUID(memory_id))
            logger.info("memory.reinforced", memory_id=memory_id)
        except AgentLearningNotFoundError:
            raise MemoryNotFoundError(
                f"Cannot reinforce: memory {memory_id!r} not found.",
                memory_id=memory_id,
            )
        except DatabaseError:
            raise
        except Exception as exc:
            logger.exception("memory.reinforce.unexpected_error", memory_id=memory_id, error=str(exc))
            raise DatabaseError("Failed to reinforce memory.") from exc

    async def forget(self, memory_id: str) -> None:
        """Soft-delete a memory by setting ``expires_at`` to the current UTC time.

        The memory is not physically removed; it is excluded from all future
        searches and :meth:`get_recent` calls.  Physical cleanup is performed
        by :meth:`AgentLearningRepository.prune_expired` (typically scheduled
        as a periodic maintenance task).

        Implemented via a direct ``UPDATE`` using the repository's update
        path: fetches the row first to confirm existence, then sets
        ``expires_at = now()``.

        Args:
            memory_id: String UUID of the memory to forget.

        Raises:
            MemoryNotFoundError: If no memory with ``memory_id`` exists.
            DatabaseError: On any persistence failure.
        """
        try:
            row = await self._repo.get_by_id(UUID(memory_id))
        except AgentLearningNotFoundError:
            raise MemoryNotFoundError(
                f"Cannot forget: memory {memory_id!r} not found.",
                memory_id=memory_id,
            )
        except DatabaseError:
            raise
        except Exception as exc:
            logger.exception("memory.forget.get_error", memory_id=memory_id, error=str(exc))
            raise DatabaseError("Failed to forget memory.") from exc

        # Set expires_at to now to trigger soft-delete semantics.
        try:
            row.expires_at = datetime.now(tz=UTC)
            self._repo._session.add(row)
            await self._repo._session.flush()
            logger.info("memory.forgotten", memory_id=memory_id)
        except Exception as exc:
            await self._repo._session.rollback()
            logger.exception("memory.forget.update_error", memory_id=memory_id, error=str(exc))
            raise DatabaseError("Failed to set expiry on memory.") from exc

    async def get_recent(
        self,
        agent_id: str,
        memory_type: MemoryType | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """Return the most recently accessed memories for an agent.

        Delegates to :meth:`AgentLearningRepository.search_by_type` ordered
        by ``times_reinforced`` descending then ``created_at`` descending.
        When ``memory_type`` is ``None`` all types are fetched via three
        separate type queries and merged, preserving the per-type ordering
        before interleaving by ``last_accessed_at``.

        Expired memories are excluded.

        Args:
            agent_id: UUID string of the owning agent.
            memory_type: If provided, restrict results to this type.
            limit: Maximum number of memories to return.

        Returns:
            A list of up to ``limit`` :class:`Memory` objects, newest first.

        Raises:
            DatabaseError: On any persistence failure.
        """
        try:
            if memory_type is not None:
                rows = await self._repo.search_by_type(
                    agent_id=UUID(agent_id),
                    memory_type=memory_type.value,
                    exclude_expired=True,
                    limit=limit,
                    offset=0,
                )
                memories = [_orm_to_memory(r) for r in rows]
            else:
                # Fetch all three types and merge by last_accessed_at.
                all_rows: list[AgentLearning] = []
                for mt in MemoryType:
                    rows = await self._repo.search_by_type(
                        agent_id=UUID(agent_id),
                        memory_type=mt.value,
                        exclude_expired=True,
                        limit=limit,
                        offset=0,
                    )
                    all_rows.extend(rows)

                # Sort combined list by last_accessed_at descending, then trim.
                all_rows.sort(
                    key=lambda r: r.last_accessed_at or r.created_at,
                    reverse=True,
                )
                memories = [_orm_to_memory(r) for r in all_rows[:limit]]
        except DatabaseError:
            raise
        except Exception as exc:
            logger.exception("memory.get_recent.unexpected_error", agent_id=agent_id, error=str(exc))
            raise DatabaseError("Failed to retrieve recent memories.") from exc

        return memories
