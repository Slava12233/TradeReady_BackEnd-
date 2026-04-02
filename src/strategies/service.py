"""Strategy service — business logic for strategy CRUD, versioning, and deployment.

Thin orchestration layer over :class:`StrategyRepository`. Enforces business rules
like version auto-increment, deploy validation, and tenant isolation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import ValidationError
import structlog

from src.database.models import Strategy, StrategyTestRun, StrategyVersion
from src.database.repositories.strategy_repo import StrategyRepository
from src.strategies.models import StrategyDefinition
from src.utils.exceptions import (
    InputValidationError,
    PermissionDeniedError,
    StrategyInvalidStateError,
    StrategyNotFoundError,
)

_DEPLOYABLE_STATUSES = {"draft", "validated", "tested"}

logger = structlog.get_logger(__name__)


class StrategyService:
    """Business logic for strategy management.

    Args:
        repo: A :class:`StrategyRepository` wired to the current session.
    """

    def __init__(self, repo: StrategyRepository) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_strategy(
        self,
        account_id: UUID,
        name: str,
        description: str | None,
        definition: dict[str, Any],
    ) -> Strategy:
        """Create a new strategy with validation.

        Args:
            account_id: Owner account.
            name: Strategy name.
            description: Optional description.
            definition: Strategy definition dict (validated against StrategyDefinition).

        Returns:
            The created Strategy.
        """
        # Validate definition against the strategy schema before persisting
        try:
            StrategyDefinition(**definition)
        except ValidationError as exc:
            logger.warning(
                "strategy.create.invalid_definition",
                account_id=str(account_id),
                error_count=exc.error_count(),
            )
            raise InputValidationError(
                f"Invalid strategy definition: {exc.error_count()} validation error(s)",
                details={"errors": exc.errors()},
            ) from exc
        return await self._repo.create(account_id, name, description, definition)

    async def get_strategy(self, account_id: UUID, strategy_id: UUID) -> Strategy:
        """Get a strategy with ownership check.

        Args:
            account_id: Requesting account.
            strategy_id: Strategy to fetch.

        Returns:
            The Strategy if owned by the account.

        Raises:
            StrategyNotFoundError: If not found.
            PermissionDeniedError: If not owned by account.
        """
        strategy = await self._repo.get_by_id(strategy_id)
        if strategy.account_id != account_id:
            raise PermissionDeniedError("You do not own this strategy.")
        return strategy

    async def list_strategies(
        self,
        account_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Strategy], int]:
        """List strategies for an account.

        Returns:
            Tuple of (strategies, total_count).
        """
        return await self._repo.list_by_account(account_id, status=status, limit=limit, offset=offset)

    async def update_strategy(
        self,
        account_id: UUID,
        strategy_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Strategy:
        """Update strategy metadata (name, description).

        Args:
            account_id: Requesting account.
            strategy_id: Strategy to update.
            name: New name (optional).
            description: New description (optional).

        Returns:
            The updated Strategy.
        """
        await self.get_strategy(account_id, strategy_id)  # ownership check
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if not updates:
            raise InputValidationError("No fields to update.", field="body")
        return await self._repo.update(strategy_id, **updates)

    async def archive_strategy(self, account_id: UUID, strategy_id: UUID) -> Strategy:
        """Archive (soft-delete) a strategy.

        Args:
            account_id: Requesting account.
            strategy_id: Strategy to archive.

        Returns:
            The archived Strategy.
        """
        strategy = await self.get_strategy(account_id, strategy_id)
        if strategy.status == "deployed":
            raise StrategyInvalidStateError(
                "Cannot archive a deployed strategy. Undeploy it first.",
                current_status="deployed",
            )
        return await self._repo.archive(strategy_id)

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    async def create_version(
        self,
        account_id: UUID,
        strategy_id: UUID,
        definition: dict[str, Any],
        change_notes: str | None = None,
    ) -> StrategyVersion:
        """Create a new version with auto-incremented version number.

        Args:
            account_id: Requesting account.
            strategy_id: Strategy to version.
            definition: New strategy definition.
            change_notes: Optional change notes.

        Returns:
            The new StrategyVersion.
        """
        await self.get_strategy(account_id, strategy_id)  # ownership check
        # Validate definition against the strategy schema before persisting
        try:
            StrategyDefinition(**definition)
        except ValidationError as exc:
            logger.warning(
                "strategy.version.invalid_definition",
                account_id=str(account_id),
                strategy_id=str(strategy_id),
                error_count=exc.error_count(),
            )
            raise InputValidationError(
                f"Invalid strategy definition: {exc.error_count()} validation error(s)",
                details={"errors": exc.errors()},
            ) from exc

        max_version = await self._repo.get_max_version(strategy_id)
        new_version = max_version + 1
        version = await self._repo.create_version(
            strategy_id=strategy_id,
            version_num=new_version,
            definition=definition,
            change_notes=change_notes,
            parent_version=max_version if max_version > 0 else None,
        )
        # Update current_version on strategy
        await self._repo.update(strategy_id, current_version=new_version)
        return version

    async def get_versions(self, account_id: UUID, strategy_id: UUID) -> Sequence[StrategyVersion]:
        """List all versions of a strategy.

        Args:
            account_id: Requesting account.
            strategy_id: Strategy to query.

        Returns:
            List of StrategyVersion objects.
        """
        await self.get_strategy(account_id, strategy_id)  # ownership check
        return await self._repo.list_versions(strategy_id)

    async def get_version(self, account_id: UUID, strategy_id: UUID, version: int) -> StrategyVersion:
        """Get a specific version of a strategy.

        Args:
            account_id: Requesting account.
            strategy_id: Strategy to query.
            version: Version number.

        Returns:
            The StrategyVersion.

        Raises:
            StrategyNotFoundError: If version not found.
        """
        await self.get_strategy(account_id, strategy_id)  # ownership check
        ver = await self._repo.get_version(strategy_id, version)
        if ver is None:
            raise StrategyNotFoundError(
                message=f"Version {version} not found for strategy '{strategy_id}'.",
                strategy_id=strategy_id,
            )
        return ver

    # ------------------------------------------------------------------
    # Deploy / Undeploy
    # ------------------------------------------------------------------

    async def deploy(self, account_id: UUID, strategy_id: UUID, version: int) -> Strategy:
        """Deploy a strategy version to live trading.

        The version must have 'validated' or 'tested' status (or 'draft' for now).

        Args:
            account_id: Requesting account.
            strategy_id: Strategy to deploy.
            version: Version number to deploy.

        Returns:
            The updated Strategy.
        """
        await self.get_strategy(account_id, strategy_id)  # ownership check
        ver = await self._repo.get_version(strategy_id, version)
        if ver is None:
            raise StrategyNotFoundError(
                message=f"Version {version} not found.",
                strategy_id=strategy_id,
            )
        if ver.status not in _DEPLOYABLE_STATUSES:
            raise StrategyInvalidStateError(
                f"Version {version} cannot be deployed from status '{ver.status}'.",
                current_status=ver.status,
                required_status="validated",
            )
        # Update version status to deployed
        await self._repo.update_version_status(strategy_id, version, "deployed")
        return await self._repo.deploy(strategy_id, version)

    async def list_test_runs(
        self,
        account_id: UUID,
        strategy_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[Any]:
        """List test runs for a strategy with ownership check."""
        await self.get_strategy(account_id, strategy_id)
        return await self._repo.list_test_runs(strategy_id, limit=limit, offset=offset)

    async def get_test_run(
        self,
        account_id: UUID,
        strategy_id: UUID,
        test_run_id: UUID,
    ) -> StrategyTestRun:
        """Get a test run with ownership check."""
        await self.get_strategy(account_id, strategy_id)
        test_run = await self._repo.get_test_run(test_run_id)
        if test_run is None:
            raise StrategyNotFoundError(message="Test run not found.", strategy_id=strategy_id)
        return test_run

    async def get_latest_completed_test(self, account_id: UUID, strategy_id: UUID) -> StrategyTestRun:
        """Get the latest completed test run with ownership check."""
        await self.get_strategy(account_id, strategy_id)
        test_run = await self._repo.get_latest_results(strategy_id)
        if test_run is None:
            raise StrategyNotFoundError(
                message="No completed test results found.",
                strategy_id=strategy_id,
            )
        return test_run

    async def get_latest_test_results(self, strategy_id: UUID) -> dict[str, Any] | None:
        """Get the latest completed test results for a strategy.

        Args:
            strategy_id: Strategy to query.

        Returns:
            Aggregated results dict, or None if no completed test runs.
        """
        run = await self._repo.get_latest_results(strategy_id)
        return run.results if run is not None else None

    async def undeploy(self, account_id: UUID, strategy_id: UUID) -> Strategy:
        """Stop a deployed strategy.

        Args:
            account_id: Requesting account.
            strategy_id: Strategy to undeploy.

        Returns:
            The updated Strategy.
        """
        strategy = await self.get_strategy(account_id, strategy_id)
        if strategy.status != "deployed":
            raise StrategyInvalidStateError(
                "Strategy is not deployed.",
                current_status=strategy.status,
            )
        return await self._repo.undeploy(strategy_id)
