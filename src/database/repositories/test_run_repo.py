"""Repository for Strategy Test Run operations.

Thin wrapper around :class:`StrategyRepository` test-run methods,
providing a focused interface for the test orchestrator and Celery tasks.
The underlying implementations are in ``strategy_repo.py``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.repositories.strategy_repo import StrategyRepository


class TestRunRepository(StrategyRepository):
    """Repository focused on test run operations.

    Inherits all methods from :class:`StrategyRepository` and provides
    a dedicated class for dependency injection in test-related code.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
