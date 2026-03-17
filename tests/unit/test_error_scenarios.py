"""Unit tests for cross-cutting error scenarios.

Tests error handling across services: stale prices, concurrent operations,
DB write failures, missing agents, and missing prices.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.utils.exceptions import (
    AccountNotFoundError,
    DatabaseError,
    InsufficientBalanceError,
    OrderNotCancellableError,
    OrderNotFoundError,
    OrderRejectedError,
    PriceNotAvailableError,
    TradeNotFoundError,
)


class TestExceptionHierarchy:
    def test_all_exceptions_have_to_dict(self) -> None:
        """All platform exceptions support to_dict() serialization."""
        exceptions = [
            AccountNotFoundError(account_id=uuid4()),
            DatabaseError("db failed"),
            InsufficientBalanceError(asset="USDT", required=Decimal("500")),
            OrderNotFoundError(order_id=uuid4()),
            OrderNotCancellableError(order_id=uuid4(), current_status="filled"),
            OrderRejectedError("Too small", reason="min_order_size"),
            PriceNotAvailableError(symbol="BTCUSDT"),
            TradeNotFoundError(trade_id=uuid4()),
        ]

        for exc in exceptions:
            result = exc.to_dict()
            assert "error" in result
            assert "code" in result["error"]
            assert "message" in result["error"]

    def test_insufficient_balance_includes_details(self) -> None:
        """InsufficientBalanceError includes asset, required, available details."""
        exc = InsufficientBalanceError(
            asset="USDT",
            required=Decimal("5000"),
            available=Decimal("3241.50"),
        )

        details = exc.to_dict()["error"]["details"]
        assert details["asset"] == "USDT"
        assert details["required"] == "5000"
        assert details["available"] == "3241.50"

    def test_order_not_cancellable_includes_status(self) -> None:
        """OrderNotCancellableError includes order_id and current_status."""
        order_id = uuid4()
        exc = OrderNotCancellableError(order_id=order_id, current_status="filled")

        details = exc.to_dict()["error"]["details"]
        assert details["order_id"] == str(order_id)
        assert details["current_status"] == "filled"

    def test_price_not_available_includes_symbol(self) -> None:
        """PriceNotAvailableError includes symbol in details."""
        exc = PriceNotAvailableError(symbol="BTCUSDT")

        details = exc.to_dict()["error"]["details"]
        assert details["symbol"] == "BTCUSDT"

    def test_http_status_codes_correct(self) -> None:
        """Each exception has the expected HTTP status code."""
        assert AccountNotFoundError().http_status == 404
        assert DatabaseError().http_status == 500
        assert InsufficientBalanceError().http_status == 400
        assert OrderNotFoundError().http_status == 404
        assert OrderNotCancellableError().http_status == 400
        assert OrderRejectedError().http_status == 400
        assert PriceNotAvailableError().http_status == 503
        assert TradeNotFoundError().http_status == 404


class TestOrderEngineErrorScenarios:
    async def test_order_repo_not_found_raises(self) -> None:
        """OrderRepository.get_by_id raises OrderNotFoundError for missing order."""
        from src.database.repositories.order_repo import OrderRepository

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute.return_value = mock_result

        repo = OrderRepository(session)
        with pytest.raises(OrderNotFoundError):
            await repo.get_by_id(uuid4())


class TestBalanceErrorScenarios:
    async def test_balance_repo_debit_insufficient_raises(self) -> None:
        """BalanceRepository raises InsufficientBalanceError on negative balance."""
        from sqlalchemy.exc import IntegrityError

        from src.database.repositories.balance_repo import BalanceRepository

        session = AsyncMock()
        session.rollback = AsyncMock()
        orig = Exception("check constraint violated")
        session.execute.side_effect = IntegrityError("", {}, orig)

        repo = BalanceRepository(session)
        with pytest.raises(InsufficientBalanceError):
            await repo.update_available(uuid4(), "USDT", Decimal("-99999"))

    async def test_atomic_lock_rejects_zero_amount(self) -> None:
        """atomic_lock_funds raises ValueError for zero amount."""
        from src.database.repositories.balance_repo import BalanceRepository

        session = AsyncMock()
        repo = BalanceRepository(session)

        with pytest.raises(ValueError, match="must be positive"):
            await repo.atomic_lock_funds(uuid4(), "USDT", Decimal("0"))

    async def test_atomic_lock_rejects_negative_amount(self) -> None:
        """atomic_lock_funds raises ValueError for negative amount."""
        from src.database.repositories.balance_repo import BalanceRepository

        session = AsyncMock()
        repo = BalanceRepository(session)

        with pytest.raises(ValueError, match="must be positive"):
            await repo.atomic_lock_funds(uuid4(), "USDT", Decimal("-100"))


class TestTradeRepoErrorScenarios:
    async def test_trade_not_found_raises(self) -> None:
        """TradeRepository.get_by_id raises TradeNotFoundError for missing trade."""
        from src.database.repositories.trade_repo import TradeRepository

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute.return_value = mock_result

        repo = TradeRepository(session)
        with pytest.raises(TradeNotFoundError):
            await repo.get_by_id(uuid4())


class TestAccountRepoErrorScenarios:
    async def test_account_not_found_by_id(self) -> None:
        """AccountRepository.get_by_id raises AccountNotFoundError."""
        from src.database.repositories.account_repo import AccountRepository

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute.return_value = mock_result

        repo = AccountRepository(session)
        with pytest.raises(AccountNotFoundError):
            await repo.get_by_id(uuid4())

    async def test_account_not_found_by_api_key(self) -> None:
        """AccountRepository.get_by_api_key raises AccountNotFoundError."""
        from src.database.repositories.account_repo import AccountRepository

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        session.execute.return_value = mock_result

        repo = AccountRepository(session)
        with pytest.raises(AccountNotFoundError):
            await repo.get_by_api_key("ak_live_nonexistent")
