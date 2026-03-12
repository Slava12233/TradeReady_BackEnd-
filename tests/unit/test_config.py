"""Unit tests for src/config.py — Settings validation."""

from __future__ import annotations

from decimal import Decimal

from pydantic import ValidationError
import pytest

from src.config import Settings

# Minimal valid kwargs for constructing Settings without .env
_VALID = {
    "jwt_secret": "a" * 32,
    "database_url": "postgresql+asyncpg://u:p@localhost/db",
    "redis_url": "redis://localhost:6379/0",
}


class TestSettingsValidation:
    def test_valid_minimal(self):
        s = Settings(**_VALID)
        assert s.jwt_secret == "a" * 32

    def test_jwt_secret_too_short_raises(self):
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(**{**_VALID, "jwt_secret": "short"})

    def test_jwt_secret_exact_32_passes(self):
        s = Settings(**{**_VALID, "jwt_secret": "x" * 32})
        assert len(s.jwt_secret) == 32

    def test_database_url_must_use_asyncpg(self):
        with pytest.raises(ValidationError, match="asyncpg"):
            Settings(**{**_VALID, "database_url": "postgresql://u:p@localhost/db"})

    def test_database_url_asyncpg_passes(self):
        s = Settings(**_VALID)
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_default_values(self):
        s = Settings(**_VALID)
        assert s.default_starting_balance == Decimal("10000")
        assert s.trading_fee_pct == Decimal("0.1")
        assert s.default_slippage_factor == Decimal("0.1")
        assert s.tick_flush_interval == 1.0
        assert s.tick_buffer_max_size == 5000
        assert s.jwt_expiry_hours == 1

    def test_tick_flush_interval_too_low(self):
        with pytest.raises(ValidationError):
            Settings(**{**_VALID, "tick_flush_interval": 0.01})

    def test_tick_buffer_max_size_too_small(self):
        with pytest.raises(ValidationError):
            Settings(**{**_VALID, "tick_buffer_max_size": 10})
