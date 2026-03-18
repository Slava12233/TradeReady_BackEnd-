"""Strategy management routes for the AI Agent Crypto Trading Platform.

Implements 10 strategy endpoints:

- ``POST   /api/v1/strategies``                              — create strategy
- ``GET    /api/v1/strategies``                               — list strategies
- ``GET    /api/v1/strategies/{strategy_id}``                 — get strategy detail
- ``PUT    /api/v1/strategies/{strategy_id}``                 — update metadata
- ``DELETE /api/v1/strategies/{strategy_id}``                 — archive strategy
- ``POST   /api/v1/strategies/{strategy_id}/versions``        — create version
- ``GET    /api/v1/strategies/{strategy_id}/versions``        — list versions
- ``GET    /api/v1/strategies/{strategy_id}/versions/{ver}``  — get version
- ``POST   /api/v1/strategies/{strategy_id}/deploy``          — deploy to live
- ``POST   /api/v1/strategies/{strategy_id}/undeploy``        — stop live

All endpoints require authentication (API key or JWT).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Query, status

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.strategies import (
    CreateStrategyRequest,
    CreateVersionRequest,
    DeployRequest,
    StrategyDetailResponse,
    StrategyListResponse,
    StrategyResponse,
    StrategyVersionResponse,
    UpdateStrategyRequest,
)
from src.database.models import Strategy, StrategyVersion
from src.dependencies import StrategyServiceDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strategy_to_response(s: Strategy) -> StrategyResponse:
    """Convert an ORM Strategy to a response schema."""
    return StrategyResponse(
        strategy_id=str(s.id),
        name=s.name,
        description=s.description,
        current_version=s.current_version,
        status=s.status,
        deployed_at=s.deployed_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _version_to_response(v: StrategyVersion) -> StrategyVersionResponse:
    """Convert an ORM StrategyVersion to a response schema."""
    return StrategyVersionResponse(
        version_id=str(v.id),
        strategy_id=str(v.strategy_id),
        version=v.version,
        definition=v.definition,
        change_notes=v.change_notes,
        parent_version=v.parent_version,
        status=v.status,
        created_at=v.created_at,
    )


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    body: CreateStrategyRequest,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> StrategyResponse:
    """Create a new trading strategy."""
    strategy = await service.create_strategy(
        account_id=account.id,
        name=body.name,
        description=body.description,
        definition=body.definition,
    )
    return _strategy_to_response(strategy)


@router.get("", response_model=StrategyListResponse)
async def list_strategies(
    account: CurrentAccountDep,
    service: StrategyServiceDep,
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> StrategyListResponse:
    """List all strategies for the authenticated account."""
    strategies, total = await service.list_strategies(
        account.id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return StrategyListResponse(
        strategies=[_strategy_to_response(s) for s in strategies],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy(
    strategy_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> StrategyDetailResponse:
    """Get strategy detail including current definition and latest test results."""
    strategy = await service.get_strategy(account.id, strategy_id)

    # Get current version definition
    current_def = None
    try:
        version = await service.get_version(account.id, strategy_id, strategy.current_version)
        current_def = version.definition
    except Exception:  # noqa: BLE001
        logger.debug("Could not load current version definition for strategy %s", strategy_id)

    # Get latest test results
    latest_results = None
    try:
        latest_results = await service.get_latest_test_results(strategy_id)
    except Exception:  # noqa: BLE001
        logger.debug("Could not load latest test results for strategy %s", strategy_id)

    return StrategyDetailResponse(
        strategy_id=str(strategy.id),
        name=strategy.name,
        description=strategy.description,
        current_version=strategy.current_version,
        status=strategy.status,
        deployed_at=strategy.deployed_at,
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
        current_definition=current_def,
        latest_test_results=latest_results,
    )


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: UUID,
    body: UpdateStrategyRequest,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> StrategyResponse:
    """Update strategy metadata (name, description)."""
    strategy = await service.update_strategy(
        account.id,
        strategy_id,
        name=body.name,
        description=body.description,
    )
    return _strategy_to_response(strategy)


@router.delete("/{strategy_id}", status_code=status.HTTP_200_OK, response_model=StrategyResponse)
async def archive_strategy(
    strategy_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> StrategyResponse:
    """Archive (soft-delete) a strategy."""
    strategy = await service.archive_strategy(account.id, strategy_id)
    return _strategy_to_response(strategy)


# ---------------------------------------------------------------------------
# Version endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{strategy_id}/versions",
    response_model=StrategyVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    strategy_id: UUID,
    body: CreateVersionRequest,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> StrategyVersionResponse:
    """Create a new version of a strategy."""
    version = await service.create_version(
        account.id,
        strategy_id,
        definition=body.definition,
        change_notes=body.change_notes,
    )
    return _version_to_response(version)


@router.get("/{strategy_id}/versions", response_model=list[StrategyVersionResponse])
async def list_versions(
    strategy_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> list[StrategyVersionResponse]:
    """List all versions of a strategy."""
    versions = await service.get_versions(account.id, strategy_id)
    return [_version_to_response(v) for v in versions]


@router.get("/{strategy_id}/versions/{version}", response_model=StrategyVersionResponse)
async def get_version(
    strategy_id: UUID,
    version: int,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> StrategyVersionResponse:
    """Get a specific version of a strategy."""
    ver = await service.get_version(account.id, strategy_id, version)
    return _version_to_response(ver)


# ---------------------------------------------------------------------------
# Deploy / Undeploy
# ---------------------------------------------------------------------------


@router.post("/{strategy_id}/deploy", response_model=StrategyResponse)
async def deploy_strategy(
    strategy_id: UUID,
    body: DeployRequest,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> StrategyResponse:
    """Deploy a strategy version to live trading."""
    strategy = await service.deploy(account.id, strategy_id, body.version)
    return _strategy_to_response(strategy)


@router.post("/{strategy_id}/undeploy", response_model=StrategyResponse)
async def undeploy_strategy(
    strategy_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> StrategyResponse:
    """Stop a deployed strategy."""
    strategy = await service.undeploy(account.id, strategy_id)
    return _strategy_to_response(strategy)
