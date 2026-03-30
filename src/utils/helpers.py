"""Shared utility functions for the AI Agent Crypto Trading Platform.

Provides lightweight helpers used across multiple components:

- :func:`utc_now` — timezone-aware UTC datetime (replaces ``datetime.utcnow()``)
- :func:`parse_period` — convert period strings like ``"30d"`` to ``timedelta``
- :func:`paginate` — apply ``LIMIT`` / ``OFFSET`` to a SQLAlchemy ``Select``
- :func:`format_decimal` — round a ``Decimal`` to *n* places and return as ``str``
- :func:`symbol_to_base_quote` — split ``"BTCUSDT"`` → ``("BTC", "USDT")``
- :func:`clamp` — restrict a ``Decimal`` value to ``[lo, hi]``

Example::

    from src.utils.helpers import utc_now, parse_period

    now = utc_now()
    window = parse_period("7d")
    since = now - window
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from sqlalchemy import Select


# ---------------------------------------------------------------------------
# Type variables
# ---------------------------------------------------------------------------

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# Period mapping: label → calendar days
# ---------------------------------------------------------------------------

#: Supported bounded period labels and their equivalent number of calendar days.
#: ``"all"`` is handled explicitly in :func:`parse_period` — it is NOT in this dict
#: so that unknown inputs can be detected and rejected rather than silently
#: falling through to ``dict.get()``'s default ``None`` return.
_PERIOD_DAYS: dict[str, int] = {
    "1d": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
}

# ---------------------------------------------------------------------------
# Module-level constants (D2-1: avoid re-allocating on every call)
# ---------------------------------------------------------------------------

#: Known quote-currency suffixes for Binance symbol splitting, ordered longest-first
#: so that e.g. ``"BUSD"`` is matched before ``"USD"``.
_KNOWN_QUOTES: tuple[str, ...] = ("USDT", "BUSD", "USDC", "TUSD", "BTC", "ETH", "BNB", "DAI", "PAX")

#: Human-readable candle interval labels and their equivalent durations in seconds.
#: Used by :func:`parse_interval` to accept both ``"1h"`` and ``3600`` forms.
_INTERVAL_LABEL_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware :class:`~datetime.datetime`.

    Prefer this over ``datetime.utcnow()`` (which returns a naïve datetime) or
    ``datetime.now()`` (which uses the local timezone).  All timestamps stored
    in the database and returned via the API should be UTC-aware.

    Returns:
        Current UTC datetime with ``tzinfo=timezone.utc``.

    Example::

        ts = utc_now()
        assert ts.tzinfo is not None
    """
    return datetime.now(tz=UTC)


def parse_period(period: str) -> timedelta | None:
    """Convert a period label string to a :class:`~datetime.timedelta`.

    Recognised labels: ``"1d"``, ``"7d"``, ``"30d"``, ``"90d"``, ``"all"``.
    Returns ``None`` for ``"all"`` to indicate *no lower time bound*.
    Raises :exc:`~src.utils.exceptions.InputValidationError` for any
    unrecognised value so callers receive a clean 422 instead of silently
    querying all-time data.

    Args:
        period: Period label, e.g. ``"30d"`` or ``"all"``.

    Returns:
        A :class:`~datetime.timedelta` for recognised bounded periods, or
        ``None`` for ``"all"``.

    Raises:
        :exc:`~src.utils.exceptions.InputValidationError`: If *period* is not a
            recognised label.

    Example::

        delta = parse_period("7d")
        assert delta == timedelta(days=7)

        assert parse_period("all") is None
    """
    # Explicit sentinel for "all time" — keeps _PERIOD_DAYS unambiguous.
    if period == "all":
        return None
    if period not in _PERIOD_DAYS:
        from src.utils.exceptions import InputValidationError  # lazy: avoids any future circular-import risk

        supported = list(_PERIOD_DAYS) + ["all"]
        raise InputValidationError(
            f"Invalid period '{period}'. Supported values: {supported}",
            field="period",
        )
    return timedelta(days=_PERIOD_DAYS[period])


def period_to_since(period: str) -> datetime | None:
    """Convert a period label to an absolute UTC *since* datetime.

    Convenience wrapper around :func:`utc_now` + :func:`parse_period` that
    returns the start-of-window datetime for the given *period*.

    Args:
        period: Period label, e.g. ``"30d"`` or ``"all"``.

    Returns:
        A timezone-aware UTC :class:`~datetime.datetime` representing the
        earliest timestamp included in the window, or ``None`` for ``"all"``.

    Raises:
        :exc:`~src.utils.exceptions.InputValidationError`: If *period* is not a
            recognised label.

    Example::

        since = period_to_since("7d")
        assert since is not None
        assert since < utc_now()

        assert period_to_since("all") is None
    """
    delta = parse_period(period)
    if delta is None:
        return None
    return utc_now() - delta


def paginate(stmt: Select[tuple[_T]], *, limit: int, offset: int) -> Select[tuple[_T]]:
    """Apply ``LIMIT`` / ``OFFSET`` pagination to a SQLAlchemy ``Select`` statement.

    This is a thin helper that centralises the pagination pattern used in
    repository methods so call sites stay clean.

    Args:
        stmt:   A SQLAlchemy v2 :class:`~sqlalchemy.sql.selectable.Select`
                statement (already filtered and ordered).
        limit:  Maximum number of rows to return.  Must be ≥ 1.
        offset: Number of rows to skip before returning results.  Must be ≥ 0.

    Returns:
        The same ``stmt`` with ``.limit()`` and ``.offset()`` applied.

    Raises:
        :exc:`~src.utils.exceptions.InputValidationError`: If *limit* < 1 or *offset* < 0.

    Example::

        from sqlalchemy import select
        from src.database.models import Order

        stmt = select(Order).where(Order.account_id == account_id)
        paginated = paginate(stmt, limit=50, offset=100)
    """
    from src.utils.exceptions import InputValidationError  # lazy: same package, safe

    if limit < 1:
        raise InputValidationError(f"limit must be ≥ 1, got {limit!r}", field="limit")
    if offset < 0:
        raise InputValidationError(f"offset must be ≥ 0, got {offset!r}", field="offset")
    return stmt.limit(limit).offset(offset)


def format_decimal(value: Decimal, places: int = 8) -> str:
    """Round *value* to *places* decimal places and return as a plain string.

    Uses ``ROUND_HALF_UP`` (standard financial rounding).  Useful for
    building JSON response strings from ``Decimal`` fields without scientific
    notation or trailing zeros beyond the requested precision.

    Args:
        value:  The :class:`~decimal.Decimal` to format.
        places: Number of decimal places (default 8, matching DB ``NUMERIC(20,8)``).

    Returns:
        String representation, e.g. ``"12345.67890000"``.

    Raises:
        :exc:`ValueError`: If *places* is negative.
        :exc:`decimal.InvalidOperation`: If *value* cannot be rounded.

    Example::

        assert format_decimal(Decimal("1.23456789012"), 8) == "1.23456789"
        assert format_decimal(Decimal("100"), 2) == "100.00"
    """
    if places < 0:
        raise ValueError(f"places must be ≥ 0, got {places!r}")
    quantizer = Decimal("0." + "0" * places) if places > 0 else Decimal("1")
    try:
        rounded = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise InvalidOperation(f"Cannot round {value!r} to {places} decimal places") from exc
    return str(rounded)


def symbol_to_base_quote(symbol: str) -> tuple[str, str]:
    """Split a Binance-style trading pair symbol into base and quote assets.

    Attempts to identify common quote currencies (USDT, BTC, ETH, BNB, BUSD,
    USDC, TUSD, PAX, DAI) as suffixes.  Falls back to a 50/50 split when no
    recognised quote suffix is found.

    Args:
        symbol: Upper-case pair symbol, e.g. ``"BTCUSDT"``, ``"ETHBTC"``.

    Returns:
        A two-tuple ``(base, quote)``, e.g. ``("BTC", "USDT")``.

    Example::

        assert symbol_to_base_quote("BTCUSDT") == ("BTC", "USDT")
        assert symbol_to_base_quote("ETHBTC")  == ("ETH", "BTC")
    """
    symbol = symbol.upper()
    for quote in _KNOWN_QUOTES:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            base = symbol[: -len(quote)]
            return base, quote
    # Fallback: split at midpoint.
    mid = len(symbol) // 2
    return symbol[:mid], symbol[mid:]


def parse_interval(interval: str | int) -> int:
    """Convert a candle interval to its duration in seconds.

    Accepts either a human-readable interval string (``"1m"``, ``"5m"``,
    ``"1h"``, ``"1d"``) or an integer / integer-string representing seconds
    directly (e.g. ``3600`` or ``"3600"``).  This allows API endpoints to
    accept both formats interchangeably.

    Supported string labels and their second equivalents:

    * ``"1m"``  → 60
    * ``"5m"``  → 300
    * ``"15m"`` → 900
    * ``"1h"``  → 3600
    * ``"4h"``  → 14400
    * ``"1d"``  → 86400

    Args:
        interval: Interval as a human-readable string (e.g. ``"1h"``) or as
                  an integer number of seconds (e.g. ``3600``).  Numeric
                  strings (e.g. ``"3600"``) are coerced to ``int``.

    Returns:
        Duration in seconds as a plain :class:`int`.

    Raises:
        :exc:`~src.utils.exceptions.InputValidationError`: If *interval* is
            not a recognised label and cannot be parsed as a positive integer.

    Example::

        assert parse_interval("1h")   == 3600
        assert parse_interval(3600)   == 3600
        assert parse_interval("3600") == 3600
        assert parse_interval("5m")   == 300
    """
    if isinstance(interval, int):
        if interval <= 0:
            from src.utils.exceptions import InputValidationError  # noqa: PLC0415

            raise InputValidationError(
                f"interval must be a positive integer, got {interval!r}",
                field="interval",
            )
        return interval

    # str path: try the human-readable label table first.
    label = str(interval).strip()
    if label in _INTERVAL_LABEL_SECONDS:
        return _INTERVAL_LABEL_SECONDS[label]

    # Fall back to parsing as a plain integer (e.g. "3600").
    try:
        seconds = int(label)
    except ValueError as exc:
        from src.utils.exceptions import InputValidationError  # noqa: PLC0415

        supported = list(_INTERVAL_LABEL_SECONDS)
        raise InputValidationError(
            f"Unrecognised interval {interval!r}. Use one of {supported} or a positive integer number of seconds.",
            field="interval",
        ) from exc

    if seconds <= 0:
        from src.utils.exceptions import InputValidationError  # noqa: PLC0415

        raise InputValidationError(
            f"interval must be a positive integer, got {seconds!r}",
            field="interval",
        )
    return seconds


def clamp(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    """Restrict *value* to the closed interval ``[lo, hi]``.

    Args:
        value: The :class:`~decimal.Decimal` to clamp.
        lo:    Lower bound (inclusive).
        hi:    Upper bound (inclusive).

    Returns:
        *lo* if ``value < lo``, *hi* if ``value > hi``, otherwise *value*.

    Raises:
        :exc:`~src.utils.exceptions.InputValidationError`: If ``lo > hi``.

    Example::

        assert clamp(Decimal("5"), Decimal("1"), Decimal("10")) == Decimal("5")
        assert clamp(Decimal("0"), Decimal("1"), Decimal("10")) == Decimal("1")
        assert clamp(Decimal("99"), Decimal("1"), Decimal("10")) == Decimal("10")
    """
    if lo > hi:
        from src.utils.exceptions import InputValidationError  # lazy: same package, safe

        raise InputValidationError(f"lo ({lo}) must be ≤ hi ({hi})")
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
