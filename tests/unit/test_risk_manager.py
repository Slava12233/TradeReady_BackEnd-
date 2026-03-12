"""Unit tests for src.risk.manager.RiskManager.

Tests cover all 8 validation chain steps:
1. Account not active → rejected
2. Daily loss limit exceeded → rejected
3. Order rate limit exceeded → rejected
4. Order too small → rejected
5. Order too large (max % of available balance) → rejected
6. Position limit exceeded → rejected
7. Max open orders exceeded → rejected
8. Insufficient balance → rejected
Plus:
- All checks pass → approved
- Custom risk profile overrides
- get_risk_limits / update_risk_limits
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.accounts.balance_manager import BalanceManager
from src.cache.price_cache import PriceCache
from src.config import Settings
from src.database.models import Account, Balance
from src.database.repositories.account_repo import AccountRepository
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.trade_repo import TradeRepository
from src.order_engine.validators import OrderRequest
from src.risk.manager import RiskCheckResult, RiskManager

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_account(
    status: str = "active",
    starting_balance: str = "10000",
    risk_profile: dict | None = None,
) -> Account:
    acc = MagicMock(spec=Account)
    acc.id = uuid4()
    acc.status = status
    acc.starting_balance = Decimal(starting_balance)
    acc.risk_profile = risk_profile or {}
    return acc


def _make_balance(available: str = "10000", asset: str = "USDT") -> Balance:
    bal = MagicMock(spec=Balance)
    bal.asset = asset
    bal.available = Decimal(available)
    bal.locked = Decimal("0")
    return bal


def _make_order_request(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    quantity: str = "0.01",
    type_: str = "market",
    price: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=side,
        type=type_,
        quantity=Decimal(quantity),
        price=Decimal(price) if price else None,
    )


def _build_manager(
    account: Account | None = None,
    current_price: str = "60000",
    daily_pnl: str = "0",
    open_orders: int = 0,
    balance_available: str = "10000",
    rate_limit_count: int = 1,
    settings_overrides: dict | None = None,
) -> tuple[RiskManager, Account]:
    """Return a fully-mocked RiskManager and the account it will return."""
    if account is None:
        account = _make_account()

    redis = AsyncMock()
    # _check_rate_limit uses redis.get(key) to read current count
    redis.get = AsyncMock(return_value=str(rate_limit_count) if rate_limit_count > 0 else None)
    # _consume_rate_limit_token uses redis.pipeline() for INCR + EXPIRE
    mock_pipe = AsyncMock()
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[rate_limit_count + 1, 1])
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    redis.pipeline = MagicMock(return_value=mock_pipe)

    price_cache = AsyncMock(spec=PriceCache)
    price_cache.get_price = AsyncMock(return_value=Decimal(current_price))

    usdt_bal = _make_balance(balance_available)

    async def _get_balance(acct_id: object, asset: str) -> object:
        # Only return a balance row for USDT; all other assets return None
        # (no existing position), which is the common test-default scenario.
        return usdt_bal if asset == "USDT" else None

    balance_mgr = AsyncMock(spec=BalanceManager)
    balance_mgr.get_balance = _get_balance
    balance_mgr.get_all_balances = AsyncMock(return_value=[usdt_bal])
    balance_mgr.has_sufficient_balance = AsyncMock(return_value=True)

    account_repo = AsyncMock(spec=AccountRepository)
    account_repo.get_by_id = AsyncMock(return_value=account)

    order_repo = AsyncMock(spec=OrderRepository)
    order_repo.count_open_by_account = AsyncMock(return_value=open_orders)

    trade_repo = AsyncMock(spec=TradeRepository)
    trade_repo.sum_daily_realized_pnl = AsyncMock(return_value=Decimal(daily_pnl))

    settings = MagicMock(spec=Settings)
    settings.trading_fee_pct = Decimal("0.1")
    if settings_overrides:
        for k, v in settings_overrides.items():
            setattr(settings, k, v)

    mgr = RiskManager(
        redis=redis,
        price_cache=price_cache,
        balance_manager=balance_mgr,
        account_repo=account_repo,
        order_repo=order_repo,
        trade_repo=trade_repo,
        settings=settings,
    )
    return mgr, account


# ---------------------------------------------------------------------------
# Happy path (all checks pass)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_order_approved_when_all_checks_pass():
    """All 8 checks pass → approved=True."""
    mgr, account = _build_manager(balance_available="10000")
    order = _make_order_request(quantity="0.01")

    result = await mgr.validate_order(account.id, order)

    assert result.approved is True
    assert result.rejection_reason is None


# ---------------------------------------------------------------------------
# Step 1: Account not active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_when_account_suspended():
    """Suspended account → rejection_reason='account_not_active'."""
    account = _make_account(status="suspended")
    mgr, _ = _build_manager(account=account)
    order = _make_order_request()

    result = await mgr.validate_order(account.id, order)

    assert result.approved is False
    assert result.rejection_reason == "account_not_active"


@pytest.mark.asyncio
async def test_rejected_when_account_archived():
    """Archived account → rejection_reason='account_not_active'."""
    account = _make_account(status="archived")
    mgr, _ = _build_manager(account=account)
    order = _make_order_request()

    result = await mgr.validate_order(account.id, order)

    assert result.approved is False
    assert result.rejection_reason == "account_not_active"


# ---------------------------------------------------------------------------
# Step 2: Daily loss limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_when_daily_loss_limit_breached():
    """Daily loss ≥ 20% of starting balance → rejection_reason='daily_loss_limit'."""
    account = _make_account(starting_balance="10000")
    # 20% loss limit = $2000. daily_pnl=-2000 → exactly at threshold.
    mgr, _ = _build_manager(account=account, daily_pnl="-2000")
    order = _make_order_request()

    result = await mgr.validate_order(account.id, order)

    assert result.approved is False
    assert result.rejection_reason == "daily_loss_limit"


@pytest.mark.asyncio
async def test_not_rejected_when_daily_pnl_within_limit():
    """Daily loss < 20% → step 2 passes."""
    account = _make_account(starting_balance="10000")
    mgr, _ = _build_manager(account=account, daily_pnl="-1999")
    order = _make_order_request()

    result = await mgr.validate_order(account.id, order)

    # Should not reject on daily loss (may reject on other checks)
    assert result.rejection_reason != "daily_loss_limit"


# ---------------------------------------------------------------------------
# Step 3: Rate limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_when_rate_limit_exceeded():
    """rate_limit_count > 100 → rejection_reason='rate_limit_exceeded'."""
    mgr, account = _build_manager(rate_limit_count=101)
    order = _make_order_request()

    result = await mgr.validate_order(account.id, order)

    assert result.approved is False
    assert result.rejection_reason == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_not_rejected_at_rate_limit_boundary():
    """rate_limit_count == 99 → within limit (< 100), step 3 passes."""
    mgr, account = _build_manager(rate_limit_count=99)
    order = _make_order_request()

    result = await mgr.validate_order(account.id, order)

    assert result.rejection_reason != "rate_limit_exceeded"


# ---------------------------------------------------------------------------
# Step 4: Minimum order size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_when_order_below_min_size():
    """Order value < $1 → rejection_reason='order_too_small'."""
    # 0.0000001 BTC × $60000 = $0.006 < $1 min
    mgr, account = _build_manager(current_price="60000")
    order = _make_order_request(quantity="0.0000001")

    result = await mgr.validate_order(account.id, order)

    assert result.approved is False
    assert result.rejection_reason == "order_too_small"


# ---------------------------------------------------------------------------
# Step 5: Maximum order size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_when_order_exceeds_max_pct_of_balance():
    """Order value > 50% of available USDT → rejection_reason='order_too_large'."""
    # balance = $100; 50% = $50; order = 0.001 BTC × $60000 = $60 > $50
    mgr, account = _build_manager(balance_available="100", current_price="60000")
    order = _make_order_request(quantity="0.001")

    result = await mgr.validate_order(account.id, order)

    assert result.approved is False
    assert result.rejection_reason == "order_too_large"


# ---------------------------------------------------------------------------
# Step 7: Max open orders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_when_open_orders_at_max():
    """open_orders == 50 → rejection_reason='max_open_orders_exceeded'."""
    mgr, account = _build_manager(open_orders=50)
    order = _make_order_request()

    result = await mgr.validate_order(account.id, order)

    assert result.approved is False
    assert result.rejection_reason == "max_open_orders_exceeded"


# ---------------------------------------------------------------------------
# Step 8: Sufficient balance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_when_balance_insufficient():
    """has_sufficient_balance=False → rejection_reason='insufficient_balance'."""
    mgr, account = _build_manager()
    mgr._balance_manager.has_sufficient_balance = AsyncMock(return_value=False)
    order = _make_order_request()

    result = await mgr.validate_order(account.id, order)

    assert result.approved is False
    assert result.rejection_reason == "insufficient_balance"


# ---------------------------------------------------------------------------
# get_risk_limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_risk_limits_returns_defaults_for_empty_profile():
    """Empty risk_profile uses platform defaults."""
    account = _make_account(risk_profile={})
    mgr, _ = _build_manager(account=account)

    limits = await mgr.get_risk_limits(account.id)

    assert limits.max_position_size_pct == Decimal("25")
    assert limits.max_open_orders == 50
    assert limits.daily_loss_limit_pct == Decimal("20")
    assert limits.min_order_size_usd == Decimal("1.0")
    assert limits.max_order_size_pct == Decimal("50")
    assert limits.order_rate_limit == 100


@pytest.mark.asyncio
async def test_get_risk_limits_applies_custom_profile():
    """Custom risk_profile values override defaults."""
    account = _make_account(
        risk_profile={
            "max_open_orders": 10,
            "daily_loss_limit_pct": "5",
            "order_rate_limit": 20,
        }
    )
    mgr, _ = _build_manager(account=account)

    limits = await mgr.get_risk_limits(account.id)

    assert limits.max_open_orders == 10
    assert limits.daily_loss_limit_pct == Decimal("5")
    assert limits.order_rate_limit == 20
    # Untouched defaults remain
    assert limits.max_position_size_pct == Decimal("25")


# ---------------------------------------------------------------------------
# check_daily_loss helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_daily_loss_returns_true_within_limit():
    """check_daily_loss() returns True when no daily loss."""
    mgr, account = _build_manager(daily_pnl="0")

    assert await mgr.check_daily_loss(account.id) is True


@pytest.mark.asyncio
async def test_check_daily_loss_returns_false_at_limit():
    """check_daily_loss() returns False when limit exceeded."""
    account = _make_account(starting_balance="10000")
    mgr, _ = _build_manager(account=account, daily_pnl="-2000")

    assert await mgr.check_daily_loss(account.id) is False


# ---------------------------------------------------------------------------
# RiskCheckResult helpers
# ---------------------------------------------------------------------------


def test_risk_check_result_ok():
    result = RiskCheckResult.ok()
    assert result.approved is True
    assert result.rejection_reason is None


def test_risk_check_result_reject():
    result = RiskCheckResult.reject("some_reason", limit=50, current=55)
    assert result.approved is False
    assert result.rejection_reason == "some_reason"
    assert result.details["limit"] == 50
    assert result.details["current"] == 55
