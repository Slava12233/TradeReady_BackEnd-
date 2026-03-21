"""Abstract interface for the agent long-term memory store.

Defines the :class:`MemoryType` enum, the :class:`Memory` Pydantic model, and
the :class:`MemoryStore` abstract base class that all concrete implementations
must satisfy.

Dependency direction:
    MemoryStore (interface) ← PostgresMemoryStore (implementation)

No I/O is performed in this module — it is pure Python types and contracts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MemoryType(str, Enum):
    """Classification of an agent memory record.

    Mirrors the ``memory_type`` CHECK constraint on the ``agent_learnings``
    database table.

    Attributes:
        EPISODIC: A memory tied to a specific event or experience (e.g. a
            particular trade that went wrong).
        SEMANTIC: A general factual belief about the world (e.g. "BTC tends
            to recover after 20 % drawdowns").
        PROCEDURAL: A learned rule or procedure (e.g. "always check the
            regime before increasing position size").
    """

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class Memory(BaseModel):
    """A single agent memory record.

    Represents one row from the ``agent_learnings`` table, converted to a
    clean Pydantic model that callers outside the database layer can consume
    without depending on SQLAlchemy ORM objects.

    All monetary/confidence values use :class:`~decimal.Decimal` to avoid
    floating-point precision loss.  ``id`` and ``agent_id`` are ``str``
    representations of UUIDs so the model can be used across process
    boundaries (e.g. serialised to JSON) without a ``uuid`` dependency.

    Attributes:
        id: UUID primary key of the memory record (string form).
        agent_id: UUID of the owning agent (string form).
        memory_type: Classification — episodic, semantic, or procedural.
        content: The memory expressed in plain text.
        source: Where this memory originated (e.g. session ID, journal
            entry reference, or tool name).
        confidence: Certainty score in ``[0, 1]``.
        times_reinforced: Number of times this memory was reaffirmed.
        created_at: UTC timestamp when the memory was first recorded.
        last_accessed_at: UTC timestamp of the most recent retrieval.

    Example::

        mem = Memory(
            id="550e8400-e29b-41d4-a716-446655440000",
            agent_id="123e4567-e89b-12d3-a456-426614174000",
            memory_type=MemoryType.PROCEDURAL,
            content="Always confirm regime before increasing position size.",
            source="trade_reflection_2026-03-20",
            confidence=Decimal("0.8500"),
            times_reinforced=3,
            created_at=datetime(2026, 3, 20, 12, 0, 0),
            last_accessed_at=datetime(2026, 3, 20, 14, 0, 0),
        )
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="UUID primary key of the memory record.")
    agent_id: str = Field(..., description="UUID of the owning agent.")
    memory_type: MemoryType = Field(
        ...,
        description="Classification: episodic, semantic, or procedural.",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="The memory expressed in plain text.",
    )
    source: str = Field(
        default="",
        description="Origin of this memory (session ID, journal ref, tool name).",
    )
    confidence: Decimal = Field(
        default=Decimal("1.0000"),
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Certainty score in [0, 1].",
    )
    times_reinforced: int = Field(
        default=1,
        ge=1,
        description="Number of times this memory was reaffirmed.",
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when the memory was first recorded.",
    )
    last_accessed_at: datetime = Field(
        ...,
        description="UTC timestamp of the most recent retrieval.",
    )


class MemoryStore(ABC):
    """Abstract interface for the agent long-term memory persistence layer.

    All concrete implementations must provide async implementations of every
    method defined here.  The contract is:

    - :meth:`save` — persist a new memory and return its assigned ID.
    - :meth:`get` — retrieve a single memory by ID (returns ``None`` if not
      found).
    - :meth:`search` — keyword-based search with optional type filtering,
      ordered by relevance (recency + reinforcement score).
    - :meth:`reinforce` — atomically increment the reinforcement counter and
      update ``last_accessed_at``.
    - :meth:`forget` — soft-delete by setting ``expires_at`` to now so the
      memory is excluded from future searches.
    - :meth:`get_recent` — return the most recently accessed memories for an
      agent, optionally filtered by type.

    Implementations must **not** commit the database session — the caller owns
    the transaction boundary (consistent with the project's repository pattern).

    Raises:
        Any ``MemoryStore`` method may raise ``DatabaseError`` (from
        ``src.utils.exceptions``) on unrecoverable persistence failures.
        ``MemoryNotFoundError`` is raised by :meth:`get` when the requested
        record does not exist (implementations may also raise it from
        :meth:`reinforce`).
    """

    @abstractmethod
    async def save(self, memory: Memory) -> str:
        """Persist a new memory record.

        Args:
            memory: The fully-populated memory to persist.  The ``id`` field
                is ignored by the Postgres implementation (the server generates
                a UUID); callers should treat the returned ID as authoritative.

        Returns:
            The server-assigned UUID string for the persisted memory.

        Raises:
            DatabaseError: On any persistence failure.
        """
        ...

    @abstractmethod
    async def get(self, memory_id: str) -> Memory | None:
        """Retrieve a single memory by its primary key.

        Touching the ``last_accessed_at`` timestamp is at the discretion of
        each implementation; the Postgres implementation calls
        ``AgentLearningRepository.touch()`` as a side-effect.

        Args:
            memory_id: String UUID of the memory to retrieve.

        Returns:
            The matching :class:`Memory` or ``None`` if no record exists with
            that ID.

        Raises:
            DatabaseError: On any persistence failure.
        """
        ...

    @abstractmethod
    async def search(
        self,
        agent_id: str,
        query: str,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[Memory]:
        """Search memories by keyword with recency-weighted ranking.

        Returns memories whose ``content`` contains ``query`` (case-insensitive
        substring match), ranked by a composite score of reinforcement count
        and recency of last access.

        Args:
            agent_id: UUID string of the owning agent.
            query: Keyword or phrase to search for in memory content.
            memory_type: If provided, restrict results to this memory type.
            limit: Maximum number of memories to return.

        Returns:
            A list of up to ``limit`` :class:`Memory` objects ordered by
            relevance (highest score first).

        Raises:
            DatabaseError: On any persistence failure.
        """
        ...

    @abstractmethod
    async def reinforce(self, memory_id: str) -> None:
        """Atomically increment the reinforcement counter for a memory.

        Increments ``times_reinforced`` and updates ``last_accessed_at`` to
        now in a single UPDATE statement.  Should be called when the agent
        encounters evidence that confirms an existing memory rather than
        creating a duplicate.

        Args:
            memory_id: String UUID of the memory to reinforce.

        Raises:
            MemoryNotFoundError: If no memory with ``memory_id`` exists.
            DatabaseError: On any persistence failure.
        """
        ...

    @abstractmethod
    async def forget(self, memory_id: str) -> None:
        """Soft-delete a memory by setting its expiry to now.

        The memory is not physically removed from the database; it is excluded
        from all future :meth:`search` and :meth:`get_recent` calls by setting
        ``expires_at = now()``.  Physical cleanup happens via the
        ``AgentLearningRepository.prune_expired()`` maintenance task.

        Args:
            memory_id: String UUID of the memory to forget.

        Raises:
            MemoryNotFoundError: If no memory with ``memory_id`` exists.
            DatabaseError: On any persistence failure.
        """
        ...

    @abstractmethod
    async def get_recent(
        self,
        agent_id: str,
        memory_type: MemoryType | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """Return the most recently accessed memories for an agent.

        Ordered by ``last_accessed_at`` descending (most recent first).
        Expired memories are excluded.

        Args:
            agent_id: UUID string of the owning agent.
            memory_type: If provided, restrict results to this memory type.
            limit: Maximum number of memories to return.

        Returns:
            A list of up to ``limit`` :class:`Memory` objects, newest first.

        Raises:
            DatabaseError: On any persistence failure.
        """
        ...


class MemoryNotFoundError(Exception):
    """Raised when a requested memory record does not exist.

    Attributes:
        memory_id: The ID that was not found (may be ``None`` for non-ID
            lookups).
    """

    def __init__(
        self,
        message: str = "Memory record not found.",
        *,
        memory_id: str | UUID | None = None,
    ) -> None:
        self.memory_id = memory_id
        super().__init__(message)
