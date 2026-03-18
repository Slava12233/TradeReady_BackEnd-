"""Unit tests for StrategyService.

Tests: create, get, list, update, archive, create_version (auto-increment),
get_versions, deploy (valid/invalid), undeploy.
"""

from __future__ import annotations

from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.strategies.service import StrategyService
from src.utils.exceptions import (
    InputValidationError,
    PermissionDeniedError,
    StrategyInvalidStateError,
    StrategyNotFoundError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_DEFINITION = {
    "pairs": ["BTCUSDT"],
    "timeframe": "1h",
    "entry_conditions": {"rsi_below": 30},
    "exit_conditions": {"take_profit_pct": 5, "stop_loss_pct": 2},
    "position_size_pct": 10,
    "max_positions": 3,
}


def _make_strategy(
    *,
    account_id=None,
    strategy_id=None,
    status="draft",
    current_version=1,
    name="Test Strategy",
):
    """Create a mock Strategy ORM object."""
    s = MagicMock()
    s.id = strategy_id or uuid4()
    s.account_id = account_id or uuid4()
    s.name = name
    s.description = None
    s.current_version = current_version
    s.status = status
    s.deployed_at = None
    s.created_at = MagicMock()
    s.updated_at = MagicMock()
    return s


def _make_version(*, strategy_id=None, version=1, definition=None, status="draft"):
    """Create a mock StrategyVersion ORM object."""
    v = MagicMock()
    v.id = uuid4()
    v.strategy_id = strategy_id or uuid4()
    v.version = version
    v.definition = definition or VALID_DEFINITION
    v.change_notes = None
    v.parent_version = None
    v.status = status
    v.created_at = MagicMock()
    return v


def _make_service(repo=None):
    """Create a StrategyService with a mocked repository."""
    if repo is None:
        repo = AsyncMock()
    return StrategyService(repo)


# ---------------------------------------------------------------------------
# Tests: Create
# ---------------------------------------------------------------------------


async def test_create_strategy_success():
    """Creating a strategy validates definition and delegates to repo."""
    account_id = uuid4()
    repo = AsyncMock()
    strategy = _make_strategy(account_id=account_id)
    repo.create.return_value = strategy
    service = _make_service(repo)

    result = await service.create_strategy(account_id, "Test", "desc", VALID_DEFINITION)

    assert result == strategy
    repo.create.assert_called_once_with(account_id, "Test", "desc", VALID_DEFINITION)


async def test_create_strategy_invalid_definition():
    """Creating a strategy with invalid definition raises ValidationError."""
    from pydantic import ValidationError  # noqa: PLC0415

    service = _make_service()
    with pytest.raises(ValidationError):
        await service.create_strategy(uuid4(), "Test", None, {"pairs": []})


# ---------------------------------------------------------------------------
# Tests: Get
# ---------------------------------------------------------------------------


async def test_get_strategy_success():
    """Getting a strategy owned by the account succeeds."""
    account_id = uuid4()
    strategy = _make_strategy(account_id=account_id)
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    service = _make_service(repo)

    result = await service.get_strategy(account_id, strategy.id)
    assert result == strategy


async def test_get_strategy_not_owned():
    """Getting a strategy not owned by the account raises PermissionDeniedError."""
    account_id = uuid4()
    other_account_id = uuid4()
    strategy = _make_strategy(account_id=other_account_id)
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    service = _make_service(repo)

    with pytest.raises(PermissionDeniedError):
        await service.get_strategy(account_id, strategy.id)


# ---------------------------------------------------------------------------
# Tests: List
# ---------------------------------------------------------------------------


async def test_list_strategies():
    """Listing strategies delegates to repo with correct params."""
    account_id = uuid4()
    strategies = [_make_strategy(account_id=account_id) for _ in range(3)]
    repo = AsyncMock()
    repo.list_by_account.return_value = (strategies, 3)
    service = _make_service(repo)

    result, total = await service.list_strategies(account_id, status="draft", limit=10, offset=0)
    assert total == 3
    assert len(result) == 3
    repo.list_by_account.assert_called_once_with(account_id, status="draft", limit=10, offset=0)


# ---------------------------------------------------------------------------
# Tests: Update
# ---------------------------------------------------------------------------


async def test_update_strategy_success():
    """Updating a strategy with valid fields succeeds."""
    account_id = uuid4()
    strategy = _make_strategy(account_id=account_id)
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    updated = _make_strategy(account_id=account_id, name="Updated")
    repo.update.return_value = updated
    service = _make_service(repo)

    result = await service.update_strategy(account_id, strategy.id, name="Updated")
    assert result.name == "Updated"


async def test_update_strategy_no_fields():
    """Updating with no fields raises InputValidationError."""
    account_id = uuid4()
    strategy = _make_strategy(account_id=account_id)
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    service = _make_service(repo)

    with pytest.raises(InputValidationError):
        await service.update_strategy(account_id, strategy.id)


# ---------------------------------------------------------------------------
# Tests: Archive
# ---------------------------------------------------------------------------


async def test_archive_strategy_success():
    """Archiving a non-deployed strategy succeeds."""
    account_id = uuid4()
    strategy = _make_strategy(account_id=account_id, status="draft")
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    archived = _make_strategy(account_id=account_id, status="archived")
    repo.archive.return_value = archived
    service = _make_service(repo)

    result = await service.archive_strategy(account_id, strategy.id)
    assert result.status == "archived"


async def test_archive_deployed_strategy_fails():
    """Archiving a deployed strategy raises StrategyInvalidStateError."""
    account_id = uuid4()
    strategy = _make_strategy(account_id=account_id, status="deployed")
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    service = _make_service(repo)

    with pytest.raises(StrategyInvalidStateError):
        await service.archive_strategy(account_id, strategy.id)


# ---------------------------------------------------------------------------
# Tests: Version
# ---------------------------------------------------------------------------


async def test_create_version_auto_increment():
    """Creating a version auto-increments the version number."""
    account_id = uuid4()
    strategy_id = uuid4()
    strategy = _make_strategy(account_id=account_id, strategy_id=strategy_id)
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    repo.get_max_version.return_value = 3
    new_version = _make_version(strategy_id=strategy_id, version=4)
    repo.create_version.return_value = new_version
    repo.update.return_value = strategy
    service = _make_service(repo)

    result = await service.create_version(account_id, strategy_id, VALID_DEFINITION, "Update RSI")

    assert result.version == 4
    repo.create_version.assert_called_once()
    call_args = repo.create_version.call_args
    assert call_args.kwargs["version_num"] == 4
    assert call_args.kwargs["parent_version"] == 3


async def test_get_versions():
    """Getting versions delegates to repo with ownership check."""
    account_id = uuid4()
    strategy_id = uuid4()
    strategy = _make_strategy(account_id=account_id, strategy_id=strategy_id)
    versions = [_make_version(strategy_id=strategy_id, version=i) for i in range(1, 4)]
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    repo.list_versions.return_value = versions
    service = _make_service(repo)

    result = await service.get_versions(account_id, strategy_id)
    assert len(result) == 3


async def test_get_version_not_found():
    """Getting a non-existent version raises StrategyNotFoundError."""
    account_id = uuid4()
    strategy_id = uuid4()
    strategy = _make_strategy(account_id=account_id, strategy_id=strategy_id)
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    repo.get_version.return_value = None
    service = _make_service(repo)

    with pytest.raises(StrategyNotFoundError):
        await service.get_version(account_id, strategy_id, 99)


# ---------------------------------------------------------------------------
# Tests: Deploy / Undeploy
# ---------------------------------------------------------------------------


async def test_deploy_success():
    """Deploying a strategy with a valid version succeeds."""
    account_id = uuid4()
    strategy_id = uuid4()
    strategy = _make_strategy(account_id=account_id, strategy_id=strategy_id, status="draft")
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    version = _make_version(strategy_id=strategy_id, version=1, status="validated")
    repo.get_version.return_value = version
    deployed = _make_strategy(account_id=account_id, strategy_id=strategy_id, status="deployed")
    repo.deploy.return_value = deployed
    repo.update_version_status.return_value = version
    service = _make_service(repo)

    result = await service.deploy(account_id, strategy_id, 1)
    assert result.status == "deployed"
    repo.deploy.assert_called_once_with(strategy_id, 1)


async def test_deploy_version_not_found():
    """Deploying with a non-existent version raises StrategyNotFoundError."""
    account_id = uuid4()
    strategy_id = uuid4()
    strategy = _make_strategy(account_id=account_id, strategy_id=strategy_id)
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    repo.get_version.return_value = None
    service = _make_service(repo)

    with pytest.raises(StrategyNotFoundError):
        await service.deploy(account_id, strategy_id, 99)


async def test_undeploy_success():
    """Undeploying a deployed strategy succeeds."""
    account_id = uuid4()
    strategy_id = uuid4()
    strategy = _make_strategy(account_id=account_id, strategy_id=strategy_id, status="deployed")
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    undeployed = _make_strategy(account_id=account_id, strategy_id=strategy_id, status="validated")
    repo.undeploy.return_value = undeployed
    service = _make_service(repo)

    result = await service.undeploy(account_id, strategy_id)
    assert result.status == "validated"


async def test_undeploy_not_deployed():
    """Undeploying a non-deployed strategy raises StrategyInvalidStateError."""
    account_id = uuid4()
    strategy_id = uuid4()
    strategy = _make_strategy(account_id=account_id, strategy_id=strategy_id, status="draft")
    repo = AsyncMock()
    repo.get_by_id.return_value = strategy
    service = _make_service(repo)

    with pytest.raises(StrategyInvalidStateError):
        await service.undeploy(account_id, strategy_id)
