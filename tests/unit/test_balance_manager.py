"""Unit tests for src.accounts.balance_manager.BalanceManager.

Tests cover:
- credit() — positive amounts, zero-amount rejection
- debit() — positive amounts, zero-amount rejection
- lock() — moves available → locked
- unlock() — moves locked → available
- has_sufficient_balance() — returns True/False correctly
- execute_trade() — atomic buy and sell settlement
- fee deduction in execute_trade
- InsufficientBalanceError propagation
- ValidationError on invalid inputs
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.accounts.balance_manager import BalanceManager, TradeSettlement
from src.config import Settings
from src.database.models import Balance
from src.utils.exceptions import InsufficientBalanceError, ValidationError


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_balance(
    account_id=None,
    asset: str = "USDT",
    available: str = "10000",
    locked: str = "0",
) -> Balance:
    """Build a mock Balance ORM object."""
    bal = MagicMock(spec=Balance)
    bal.account_id = account_id or uuid4()
    bal.asset = asset
    bal.available = Decimal(available)
    bal.locked = Decimal(locked)
    return bal


def _make_settings(fee_pct: str = "0.1") -> MagicMock:
    s = MagicMock(spec=Settings)
    s.trading_fee_pct = Decimal(fee_pct)
    return s


def _make_repo(
    get_result: Balance | None = None,
    get_all_result=None,
    update_result: Balance | None = None,
    atomic_buy_result=None,
    atomic_sell_result=None,
    lock_result: Balance | None = None,
    unlock_result: Balance | None = None,
) -> AsyncMock:
    """Return a mock BalanceRepository wired with given return values."""
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=get_result)
    repo.get_all = AsyncMock(return_value=get_all_result or [])
    repo.create = AsyncMock(side_effect=lambda b: b)
    repo.update_available = AsyncMock(return_value=update_result)
    repo.atomic_lock_funds = AsyncMock(return_value=lock_result)
    repo.atomic_unlock_funds = AsyncMock(return_value=unlock_result)
    repo.atomic_execute_buy = AsyncMock(return_value=atomic_buy_result or (None, None))
    repo.atomic_execute_sell = AsyncMock(return_value=atomic_sell_result or (None, None))
    return repo


def _make_manager(
    repo: AsyncMock | None = None,
    settings: MagicMock | None = None,
) -> tuple[BalanceManager, AsyncMock]:
    """Create a BalanceManager with injected mock repo and session."""
    session = AsyncMock()
    mgr = BalanceManager(session, settings or _make_settings())
    if repo is not None:
        mgr._repo = repo
    return mgr, session


# ---------------------------------------------------------------------------
# credit()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credit_calls_repo_update_available():
    """credit() calls repo.update_available with a positive delta."""
    account_id = uuid4()
    returned_bal = _make_balance(account_id, available="10500")
    repo = _make_repo(update_result=returned_bal)
    mgr, _ = _make_manager(repo)

    result = await mgr.credit(account_id, asset="USDT", amount=Decimal("500"))

    repo.update_available.assert_awaited_once_with(account_id, "USDT", Decimal("500"))
    assert result is returned_bal


@pytest.mark.asyncio
async def test_credit_zero_raises_validation_error():
    """credit(0) raises ValidationError."""
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError):
        await mgr.credit(uuid4(), asset="USDT", amount=Decimal("0"))


@pytest.mark.asyncio
async def test_credit_negative_raises_validation_error():
    """credit(-1) raises ValidationError."""
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError):
        await mgr.credit(uuid4(), asset="USDT", amount=Decimal("-1"))


# ---------------------------------------------------------------------------
# debit()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debit_calls_repo_with_negative_delta():
    """debit() calls repo.update_available with a negative delta."""
    account_id = uuid4()
    returned_bal = _make_balance(account_id, available="9500")
    repo = _make_repo(update_result=returned_bal)
    mgr, _ = _make_manager(repo)

    result = await mgr.debit(account_id, asset="USDT", amount=Decimal("500"))

    repo.update_available.assert_awaited_once_with(account_id, "USDT", Decimal("-500"))
    assert result is returned_bal


@pytest.mark.asyncio
async def test_debit_zero_raises_validation_error():
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError):
        await mgr.debit(uuid4(), asset="USDT", amount=Decimal("0"))


# ---------------------------------------------------------------------------
# lock()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_calls_atomic_lock_funds():
    """lock() delegates to repo.atomic_lock_funds."""
    account_id = uuid4()
    returned_bal = _make_balance(account_id, available="9500", locked="500")
    repo = _make_repo(lock_result=returned_bal)
    mgr, _ = _make_manager(repo)

    result = await mgr.lock(account_id, asset="USDT", amount=Decimal("500"))

    repo.atomic_lock_funds.assert_awaited_once_with(account_id, "USDT", Decimal("500"))
    assert result is returned_bal


@pytest.mark.asyncio
async def test_lock_zero_raises_validation_error():
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError):
        await mgr.lock(uuid4(), asset="USDT", amount=Decimal("0"))


# ---------------------------------------------------------------------------
# unlock()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlock_calls_atomic_unlock_funds():
    """unlock() delegates to repo.atomic_unlock_funds."""
    account_id = uuid4()
    returned_bal = _make_balance(account_id, available="10000", locked="0")
    repo = _make_repo(unlock_result=returned_bal)
    mgr, _ = _make_manager(repo)

    result = await mgr.unlock(account_id, asset="USDT", amount=Decimal("500"))

    repo.atomic_unlock_funds.assert_awaited_once_with(account_id, "USDT", Decimal("500"))
    assert result is returned_bal


@pytest.mark.asyncio
async def test_unlock_zero_raises_validation_error():
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError):
        await mgr.unlock(uuid4(), asset="USDT", amount=Decimal("0"))


# ---------------------------------------------------------------------------
# has_sufficient_balance()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_sufficient_balance_true_when_enough():
    account_id = uuid4()
    repo = _make_repo(get_result=_make_balance(account_id, available="5000"))
    mgr, _ = _make_manager(repo)

    result = await mgr.has_sufficient_balance(account_id, asset="USDT", amount=Decimal("3000"))
    assert result is True


@pytest.mark.asyncio
async def test_has_sufficient_balance_false_when_not_enough():
    account_id = uuid4()
    repo = _make_repo(get_result=_make_balance(account_id, available="100"))
    mgr, _ = _make_manager(repo)

    result = await mgr.has_sufficient_balance(account_id, asset="USDT", amount=Decimal("500"))
    assert result is False


@pytest.mark.asyncio
async def test_has_sufficient_balance_false_when_no_row():
    """Returns False when there is no balance row at all."""
    repo = _make_repo(get_result=None)
    mgr, _ = _make_manager(repo)

    result = await mgr.has_sufficient_balance(uuid4(), asset="BTC", amount=Decimal("1"))
    assert result is False


@pytest.mark.asyncio
async def test_has_sufficient_balance_use_locked():
    """use_locked=True checks locked pool."""
    account_id = uuid4()
    repo = _make_repo(get_result=_make_balance(account_id, available="0", locked="500"))
    mgr, _ = _make_manager(repo)

    assert await mgr.has_sufficient_balance(
        account_id, asset="USDT", amount=Decimal("500"), use_locked=True
    )
    assert not await mgr.has_sufficient_balance(
        account_id, asset="USDT", amount=Decimal("501"), use_locked=True
    )


@pytest.mark.asyncio
async def test_has_sufficient_balance_zero_amount_raises():
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError):
        await mgr.has_sufficient_balance(uuid4(), asset="USDT", amount=Decimal("0"))


# ---------------------------------------------------------------------------
# execute_trade() — buy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_buy_returns_trade_settlement():
    """execute_trade('buy') returns a TradeSettlement with correct fee."""
    account_id = uuid4()
    quote_bal = _make_balance(account_id, "USDT", available="0")
    base_bal = _make_balance(account_id, "BTC", available="1")

    repo = _make_repo(atomic_buy_result=(quote_bal, base_bal))
    mgr, _ = _make_manager(repo)

    settlement = await mgr.execute_trade(
        account_id,
        symbol="BTCUSDT",
        side="buy",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        execution_price=Decimal("50000"),
        from_locked=False,
    )

    assert isinstance(settlement, TradeSettlement)
    assert settlement.quote_balance is quote_bal
    assert settlement.base_balance is base_bal
    # fee = 50000 * 0.001 = 50
    assert settlement.fee_charged == Decimal("50.00000000")
    assert settlement.quote_amount == Decimal("50000.00000000")
    assert settlement.execution_price == Decimal("50000")


@pytest.mark.asyncio
async def test_execute_buy_calls_repo_with_correct_amounts():
    """repo.atomic_execute_buy receives (quote_spent, base_received) correctly."""
    account_id = uuid4()
    quote_bal = _make_balance(account_id, "USDT")
    base_bal = _make_balance(account_id, "BTC")
    repo = _make_repo(atomic_buy_result=(quote_bal, base_bal))
    mgr, _ = _make_manager(repo)

    await mgr.execute_trade(
        account_id,
        symbol="BTCUSDT",
        side="buy",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("2"),
        execution_price=Decimal("1000"),
        from_locked=False,
    )

    # gross_cost = 2 * 1000 = 2000
    # fee = 2000 * 0.001 = 2
    # quote_spent = 2002
    call_kwargs = repo.atomic_execute_buy.call_args
    assert call_kwargs.kwargs["quote_spent"] == Decimal("2002.00000000")
    assert call_kwargs.kwargs["base_received"] == Decimal("2")
    assert call_kwargs.kwargs["from_locked"] is False


# ---------------------------------------------------------------------------
# execute_trade() — sell
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_sell_returns_trade_settlement():
    """execute_trade('sell') returns correct net quote (proceeds - fee)."""
    account_id = uuid4()
    quote_bal = _make_balance(account_id, "USDT", available="990")
    base_bal = _make_balance(account_id, "BTC", available="0")
    repo = _make_repo(atomic_sell_result=(quote_bal, base_bal))
    mgr, _ = _make_manager(repo)

    settlement = await mgr.execute_trade(
        account_id,
        symbol="BTCUSDT",
        side="sell",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("1"),
        execution_price=Decimal("1000"),
        from_locked=False,
    )

    # gross_proceeds = 1000; fee = 1; net = 999
    assert settlement.fee_charged == Decimal("1.00000000")
    assert settlement.quote_amount == Decimal("1000.00000000")


@pytest.mark.asyncio
async def test_execute_sell_calls_repo_with_net_quote():
    """repo.atomic_execute_sell receives net (proceeds - fee)."""
    account_id = uuid4()
    quote_bal = _make_balance(account_id, "USDT")
    base_bal = _make_balance(account_id, "BTC")
    repo = _make_repo(atomic_sell_result=(quote_bal, base_bal))
    mgr, _ = _make_manager(repo)

    await mgr.execute_trade(
        account_id,
        symbol="BTCUSDT",
        side="sell",
        base_asset="BTC",
        quote_asset="USDT",
        quantity=Decimal("3"),
        execution_price=Decimal("2000"),
        from_locked=True,
    )

    # gross = 6000; fee = 6; net_quote = 5994
    call_kwargs = repo.atomic_execute_sell.call_args
    assert call_kwargs.kwargs["quote_received"] == Decimal("5994.00000000")
    assert call_kwargs.kwargs["base_spent"] == Decimal("3")
    assert call_kwargs.kwargs["from_locked"] is True


# ---------------------------------------------------------------------------
# execute_trade() — invalid inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_trade_invalid_side_raises_validation_error():
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError, match="side"):
        await mgr.execute_trade(
            uuid4(),
            symbol="BTCUSDT",
            side="hold",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("1"),
            execution_price=Decimal("1000"),
        )


@pytest.mark.asyncio
async def test_execute_trade_zero_quantity_raises_validation_error():
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError, match="quantity"):
        await mgr.execute_trade(
            uuid4(),
            symbol="BTCUSDT",
            side="buy",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("0"),
            execution_price=Decimal("1000"),
        )


@pytest.mark.asyncio
async def test_execute_trade_zero_price_raises_validation_error():
    mgr, _ = _make_manager()

    with pytest.raises(ValidationError, match="execution_price"):
        await mgr.execute_trade(
            uuid4(),
            symbol="BTCUSDT",
            side="buy",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("1"),
            execution_price=Decimal("0"),
        )


# ---------------------------------------------------------------------------
# get_balance / get_all_balances
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_balance_delegates_to_repo():
    account_id = uuid4()
    bal = _make_balance(account_id, "BTC", available="0.5")
    repo = _make_repo(get_result=bal)
    mgr, _ = _make_manager(repo)

    result = await mgr.get_balance(account_id, "BTC")
    assert result is bal
    repo.get.assert_awaited_once_with(account_id, "BTC")


@pytest.mark.asyncio
async def test_get_all_balances_delegates_to_repo():
    account_id = uuid4()
    balances = [
        _make_balance(account_id, "USDT"),
        _make_balance(account_id, "BTC"),
    ]
    repo = _make_repo(get_all_result=balances)
    mgr, _ = _make_manager(repo)

    result = await mgr.get_all_balances(account_id)
    assert result is balances
    repo.get_all.assert_awaited_once_with(account_id)
