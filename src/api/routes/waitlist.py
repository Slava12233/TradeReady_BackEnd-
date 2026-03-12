"""REST route for landing-page waitlist email collection.

Public endpoint — no authentication required.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
import structlog

from src.api.schemas.waitlist import WaitlistRequest, WaitlistResponse
from src.database.repositories.waitlist_repo import WaitlistRepository
from src.dependencies import DbSessionDep

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/waitlist", tags=["waitlist"])


async def _get_waitlist_repo(db: DbSessionDep) -> WaitlistRepository:
    """Provide a ``WaitlistRepository`` wired to the current session."""
    return WaitlistRepository(db)


@router.post(
    "/subscribe",
    response_model=WaitlistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Join the waitlist",
    description="Add an email address to the launch waitlist. No authentication required.",
)
async def subscribe(
    body: WaitlistRequest,
    repo: WaitlistRepository = Depends(_get_waitlist_repo),  # noqa: B008
) -> WaitlistResponse:
    """Add an email to the waitlist."""
    await repo.create(email=body.email, source=body.source)
    return WaitlistResponse()
