"""Unit tests for src.api.schemas.backtest — request validation.

Covers the validators added in the backtest bug-fix sprint:
- validate_date_range (end > start)
- validate_interval (whitelist 60/300/3600/86400)
- validate_pairs (pattern [A-Z]{2,10}USDT)
- starting_balance cap at 10 M
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from src.api.schemas.backtest import BacktestCreateRequest

# ── Helpers ──────────────────────────────────────────────────────────────────

_START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
_END = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)


def _req(**overrides):
    """Build a minimal valid BacktestCreateRequest, with optional overrides."""
    defaults = {
        "start_time": _START,
        "end_time": _END,
        "starting_balance": "1000",
        "candle_interval": 60,
    }
    defaults.update(overrides)
    return BacktestCreateRequest(**defaults)


# ── Date-range validation ─────────────────────────────────────────────────────


def test_reject_end_before_start() -> None:
    """end_time before start_time must raise ValidationError."""
    with pytest.raises(ValidationError):
        _req(
            start_time=datetime(2026, 1, 10, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_reject_equal_dates() -> None:
    """end_time equal to start_time must raise ValidationError."""
    same = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        _req(start_time=same, end_time=same)


def test_valid_date_range_accepted() -> None:
    """A normal date range (end > start) must be accepted."""
    req = _req(
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 31, tzinfo=UTC),
    )
    assert req.end_time > req.start_time


# ── Candle-interval whitelist ─────────────────────────────────────────────────


def test_reject_invalid_candle_interval() -> None:
    """An interval not in the whitelist (e.g. 999) must raise ValidationError."""
    with pytest.raises(ValidationError):
        _req(candle_interval=999)


def test_valid_candle_intervals() -> None:
    """All four whitelisted intervals must be accepted."""
    for interval in (60, 300, 3600, 86400):
        req = _req(candle_interval=interval)
        assert req.candle_interval == interval


# ── Symbol format validation ──────────────────────────────────────────────────


def test_reject_invalid_symbol_format() -> None:
    """Lowercase symbols or those without the USDT suffix must raise ValidationError."""
    with pytest.raises(ValidationError):
        _req(pairs=["btcusdt"])  # lowercase — fails pattern


def test_reject_symbol_without_usdt_suffix() -> None:
    """Symbols missing the USDT suffix must raise ValidationError."""
    with pytest.raises(ValidationError):
        _req(pairs=["BTCETH"])  # no USDT suffix


def test_valid_symbols_accepted() -> None:
    """Well-formed symbols like BTCUSDT and ETHUSDT must be accepted."""
    req = _req(pairs=["BTCUSDT", "ETHUSDT"])
    assert req.pairs == ["BTCUSDT", "ETHUSDT"]


# ── Balance cap ───────────────────────────────────────────────────────────────


def test_reject_excessive_balance() -> None:
    """A balance above 10 M (e.g. 10 B) must raise ValidationError."""
    with pytest.raises(ValidationError):
        _req(starting_balance="10000000000")  # 10 billion


def test_max_valid_balance() -> None:
    """Exactly 10 M must be accepted (it is the upper bound)."""
    req = _req(starting_balance="10000000")
    from decimal import Decimal

    assert req.starting_balance == Decimal("10000000")
