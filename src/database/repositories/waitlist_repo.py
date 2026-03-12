"""Repository for WaitlistEntry CRUD operations.

All database access for :class:`~src.database.models.WaitlistEntry` rows goes
through :class:`WaitlistRepository`.

Dependency direction:
    Routes → WaitlistRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import WaitlistEntry
from src.utils.exceptions import DatabaseError, DuplicateAccountError

logger = structlog.get_logger(__name__)


class WaitlistRepository:
    """Async repository for the ``waitlist_entries`` table.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, email: str, source: str = "landing") -> WaitlistEntry:
        """Add an email to the waitlist.

        Args:
            email: The email address to add.
            source: Which form submitted the entry (e.g. ``"hero"``, ``"cta"``).

        Returns:
            The persisted :class:`WaitlistEntry` with server-generated columns.

        Raises:
            DuplicateAccountError: If the email is already on the waitlist.
            DatabaseError: On any other database error.
        """
        entry = WaitlistEntry(email=email, source=source)
        try:
            self._session.add(entry)
            await self._session.flush()
            await self._session.refresh(entry)
            logger.info("waitlist.created", email=email, source=source)
            return entry
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateAccountError("This email is already on the waitlist.", email=email) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("waitlist.create.db_error", error=str(exc))
            raise DatabaseError("Failed to add email to waitlist.") from exc
