"""In-memory order execution sandbox for backtesting.

``BacktestSandbox`` replicates the live order engine's business logic (fees,
slippage, position tracking) entirely in memory.  No database or Redis calls
are made — all state lives in dicts and lists, then exported at completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
import uuid

from src.utils.exceptions import InsufficientBalanceError

# ── Constants (match live order engine) ──────────────────────────────────────

_FEE_FRACTION: Decimal = Decimal("0.001")  # 0.1 %
_MIN_SLIPPAGE: Decimal = Decimal("0.0001")  # 0.01 %
_MAX_SLIPPAGE: Decimal = Decimal("0.10")  # 10 %
_QUANT8: Decimal = Decimal("0.00000001")
_QUANT6: Decimal = Decimal("0.000001")


# ── Data containers ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class SandboxBalance:
    """Per-asset balance within the sandbox."""

    asset: str
    available: Decimal = Decimal("0")
    locked: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.available + self.locked


@dataclass(slots=True)
class SandboxPosition:
    """Aggregated holding for one symbol."""

    symbol: str
    quantity: Decimal = Decimal("0")
    avg_entry_price: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class SandboxOrder:
    """An order within the sandbox."""

    id: str
    symbol: str
    side: str
    type: str
    quantity: Decimal
    price: Decimal | None
    status: str
    created_at: datetime
    filled_at: datetime | None = None
    executed_price: Decimal | None = None
    executed_qty: Decimal | None = None
    slippage_pct: Decimal | None = None
    fee: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SandboxTrade:
    """A fill record within the sandbox."""

    id: str
    symbol: str
    side: str
    type: str
    quantity: Decimal
    price: Decimal
    quote_amount: Decimal
    fee: Decimal
    slippage_pct: Decimal
    realized_pnl: Decimal | None
    simulated_at: datetime


@dataclass(frozen=True, slots=True)
class SandboxSnapshot:
    """A point-in-time equity snapshot."""

    simulated_at: datetime
    total_equity: Decimal
    available_cash: Decimal
    position_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    positions: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OrderResult:
    """Result of placing or matching an order."""

    order_id: str
    status: str
    executed_price: Decimal | None = None
    executed_qty: Decimal | None = None
    slippage_pct: Decimal | None = None
    fee: Decimal | None = None
    realized_pnl: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    """Current portfolio state."""

    total_equity: Decimal
    available_cash: Decimal
    position_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    positions: list[dict[str, Any]]


# ── Sandbox ──────────────────────────────────────────────────────────────────


class BacktestSandbox:
    """In-memory order execution sandbox with identical fee/slippage logic.

    Args:
        session_id: UUID of the owning backtest session.
        starting_balance: Initial virtual USDT balance.
        slippage_factor: Base slippage coefficient (default 0.1).
        fee_fraction: Trading fee fraction (default 0.001 = 0.1%).
        risk_limits: Optional dict of agent risk profile overrides.
            Supported keys: ``max_position_size_pct``, ``max_order_size_pct``,
            ``daily_loss_limit_pct``.
    """

    def __init__(
        self,
        session_id: str,
        starting_balance: Decimal,
        slippage_factor: Decimal = Decimal("0.1"),
        fee_fraction: Decimal = _FEE_FRACTION,
        risk_limits: dict[str, Any] | None = None,
    ) -> None:
        self._session_id = session_id
        self._starting_balance = starting_balance
        self._slippage_factor = slippage_factor
        self._fee_fraction = fee_fraction
        self._risk_limits = risk_limits

        # State
        self._balances: dict[str, SandboxBalance] = {
            "USDT": SandboxBalance(asset="USDT", available=starting_balance),
        }
        self._positions: dict[str, SandboxPosition] = {}
        self._orders: list[SandboxOrder] = []
        self._pending_orders: dict[str, SandboxOrder] = {}
        self._trades: list[SandboxTrade] = []
        self._snapshots: list[SandboxSnapshot] = []
        self._cumulative_realized_pnl = Decimal("0")
        self._cumulative_fees = Decimal("0")
        self._daily_realized_pnl: dict[str, Decimal] = {}  # date-string → daily PnL

    # ── Order placement ──────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None,
        current_prices: dict[str, Decimal],
        virtual_time: datetime,
    ) -> OrderResult:
        """Place an order in the sandbox.

        Market orders fill immediately.  Limit/stop/take-profit orders are
        queued and checked on each step via ``check_pending_orders``.

        Args:
            symbol:         Trading pair.
            side:           ``"buy"`` or ``"sell"``.
            order_type:     ``"market"``, ``"limit"``, ``"stop_loss"``, ``"take_profit"``.
            quantity:       Base-asset quantity.
            price:          Target price for non-market orders.
            current_prices: Dict of symbol → current price.
            virtual_time:   Current simulated time.

        Returns:
            :class:`OrderResult` with fill details (market) or pending status.
        """
        order_id = str(uuid.uuid4())
        ref_price = current_prices.get(symbol)

        if ref_price is None:
            order = SandboxOrder(
                id=order_id,
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                status="rejected",
                created_at=virtual_time,
            )
            self._orders.append(order)
            return OrderResult(order_id=order_id, status="rejected")

        # Risk limit checks (when risk_limits configured)
        rejection = self._check_risk_limits(symbol, side, quantity, ref_price, current_prices, virtual_time)
        if rejection is not None:
            order = SandboxOrder(
                id=order_id,
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                status="rejected",
                created_at=virtual_time,
            )
            self._orders.append(order)
            return OrderResult(order_id=order_id, status="rejected")

        if order_type == "market":
            return self._execute_market_order(order_id, symbol, side, order_type, quantity, ref_price, virtual_time)

        # Non-market: validate balance and queue
        self._validate_balance_for_order(symbol, side, quantity, ref_price)
        if side == "buy":
            cost = quantity * ref_price
            self._lock_balance("USDT", cost)
        else:
            self._lock_balance(symbol.replace("USDT", ""), quantity)

        order = SandboxOrder(
            id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            status="pending",
            created_at=virtual_time,
        )
        self._orders.append(order)
        self._pending_orders[order_id] = order
        return OrderResult(order_id=order_id, status="pending")

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order and unlock reserved funds.

        Returns:
            ``True`` if the order was cancelled, ``False`` if not found or not pending.
        """
        order = self._pending_orders.pop(order_id, None)
        if order is None:
            return False

        # Unlock funds
        if order.side == "buy" and order.price is not None:
            cost = order.quantity * order.price
            self._unlock_balance("USDT", cost)
        elif order.side == "sell":
            base_asset = order.symbol.replace("USDT", "")
            self._unlock_balance(base_asset, order.quantity)

        # Update order status in list
        for i, o in enumerate(self._orders):
            if o.id == order_id:
                self._orders[i] = SandboxOrder(
                    id=o.id,
                    symbol=o.symbol,
                    side=o.side,
                    type=o.type,
                    quantity=o.quantity,
                    price=o.price,
                    status="cancelled",
                    created_at=o.created_at,
                )
                break
        return True

    def check_pending_orders(self, current_prices: dict[str, Decimal], virtual_time: datetime) -> list[OrderResult]:
        """Check all pending orders against current prices and fill triggered ones.

        Returns:
            List of :class:`OrderResult` for orders that were filled.
        """
        filled: list[OrderResult] = []
        to_remove: list[str] = []

        for order_id, order in self._pending_orders.items():
            ref_price = current_prices.get(order.symbol)
            if ref_price is None:
                continue

            triggered = False
            if order.type == "limit":
                if order.side == "buy" and order.price is not None and ref_price <= order.price:
                    triggered = True
                elif order.side == "sell" and order.price is not None and ref_price >= order.price:
                    triggered = True
            elif order.type == "stop_loss":
                if order.side == "sell" and order.price is not None and ref_price <= order.price:
                    triggered = True
                elif order.side == "buy" and order.price is not None and ref_price >= order.price:
                    triggered = True
            elif order.type == "take_profit":
                if order.side == "sell" and order.price is not None and ref_price >= order.price:
                    triggered = True
                elif order.side == "buy" and order.price is not None and ref_price <= order.price:
                    triggered = True

            if triggered:
                # Unlock previously locked funds before execution
                if order.side == "buy" and order.price is not None:
                    cost = order.quantity * order.price
                    self._unlock_balance("USDT", cost)
                elif order.side == "sell":
                    base_asset = order.symbol.replace("USDT", "")
                    self._unlock_balance(base_asset, order.quantity)

                result = self._execute_market_order(
                    order.id,
                    order.symbol,
                    order.side,
                    order.type,
                    order.quantity,
                    ref_price,
                    virtual_time,
                )
                filled.append(result)
                to_remove.append(order_id)

        for oid in to_remove:
            self._pending_orders.pop(oid, None)

        return filled

    # ── Query methods ────────────────────────────────────────────────────

    def get_balance(self) -> list[SandboxBalance]:
        """Return all non-zero balances."""
        return [b for b in self._balances.values() if b.total > 0]

    def get_positions(self) -> list[SandboxPosition]:
        """Return all open positions (quantity > 0)."""
        return [p for p in self._positions.values() if p.quantity > 0]

    def get_portfolio(self, current_prices: dict[str, Decimal]) -> PortfolioSummary:
        """Compute portfolio summary at current prices."""
        cash = self._balances.get("USDT", SandboxBalance(asset="USDT"))
        available_cash = cash.available + cash.locked

        position_value = Decimal("0")
        unrealized_pnl = Decimal("0")
        positions_list: list[dict[str, Any]] = []

        for pos in self._positions.values():
            if pos.quantity <= 0:
                continue
            price = current_prices.get(pos.symbol, Decimal("0"))
            market_value = pos.quantity * price
            unreal = market_value - pos.total_cost
            position_value += market_value
            unrealized_pnl += unreal
            positions_list.append(
                {
                    "symbol": pos.symbol,
                    "quantity": str(pos.quantity),
                    "avg_entry_price": str(pos.avg_entry_price),
                    "current_price": str(price),
                    "market_value": str(market_value),
                    "unrealized_pnl": str(unreal),
                }
            )

        total_equity = available_cash + position_value

        return PortfolioSummary(
            total_equity=total_equity,
            available_cash=available_cash,
            position_value=position_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=self._cumulative_realized_pnl,
            positions=positions_list,
        )

    def get_orders(self, status: str | None = None) -> list[SandboxOrder]:
        """Return orders, optionally filtered by status."""
        if status is None:
            return list(self._orders)
        return [o for o in self._orders if o.status == status]

    def get_trades(self) -> list[SandboxTrade]:
        """Return all executed trades."""
        return list(self._trades)

    def capture_snapshot(self, current_prices: dict[str, Decimal], virtual_time: datetime) -> SandboxSnapshot:
        """Record an equity snapshot at the current virtual time."""
        portfolio = self.get_portfolio(current_prices)
        snapshot = SandboxSnapshot(
            simulated_at=virtual_time,
            total_equity=portfolio.total_equity,
            available_cash=portfolio.available_cash,
            position_value=portfolio.position_value,
            unrealized_pnl=portfolio.unrealized_pnl,
            realized_pnl=portfolio.realized_pnl,
            positions={p["symbol"]: p for p in portfolio.positions},
        )
        self._snapshots.append(snapshot)
        return snapshot

    def close_all_positions(self, current_prices: dict[str, Decimal], virtual_time: datetime) -> list[SandboxTrade]:
        """Close all open positions at current prices.

        Returns:
            List of trades generated by closing each position.
        """
        closing_trades: list[SandboxTrade] = []
        for pos in list(self._positions.values()):
            if pos.quantity <= 0:
                continue
            ref_price = current_prices.get(pos.symbol)
            if ref_price is None:
                continue
            result = self._execute_market_order(
                str(uuid.uuid4()),
                pos.symbol,
                "sell",
                "market",
                pos.quantity,
                ref_price,
                virtual_time,
            )
            if result.status == "filled":
                closing_trades.append(self._trades[-1])
        return closing_trades

    def export_results(self) -> dict[str, Any]:
        """Export full sandbox state for DB persistence."""
        return {
            "trades": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "type": t.type,
                    "quantity": str(t.quantity),
                    "price": str(t.price),
                    "quote_amount": str(t.quote_amount),
                    "fee": str(t.fee),
                    "slippage_pct": str(t.slippage_pct),
                    "realized_pnl": str(t.realized_pnl) if t.realized_pnl is not None else None,
                    "simulated_at": t.simulated_at.isoformat(),
                }
                for t in self._trades
            ],
            "snapshots": [
                {
                    "simulated_at": s.simulated_at.isoformat(),
                    "total_equity": str(s.total_equity),
                    "available_cash": str(s.available_cash),
                    "position_value": str(s.position_value),
                    "unrealized_pnl": str(s.unrealized_pnl),
                    "realized_pnl": str(s.realized_pnl),
                    "positions": s.positions,
                }
                for s in self._snapshots
            ],
            "total_trades": len(self._trades),
            "total_fees": str(self._cumulative_fees),
            "realized_pnl": str(self._cumulative_realized_pnl),
            "starting_balance": str(self._starting_balance),
        }

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def total_trades(self) -> int:
        return len(self._trades)

    @property
    def total_fees(self) -> Decimal:
        return self._cumulative_fees

    @property
    def realized_pnl(self) -> Decimal:
        return self._cumulative_realized_pnl

    @property
    def snapshots(self) -> list[SandboxSnapshot]:
        return list(self._snapshots)

    @property
    def trades(self) -> list[SandboxTrade]:
        return list(self._trades)

    # ── Risk limit checks ────────────────────────────────────────────────

    def _check_risk_limits(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        ref_price: Decimal,
        current_prices: dict[str, Decimal],
        virtual_time: datetime,
    ) -> str | None:
        """Check agent risk limits. Returns rejection reason or None if OK."""
        if not self._risk_limits:
            return None

        portfolio = self.get_portfolio(current_prices)
        equity = portfolio.total_equity

        if equity <= 0:
            return None

        order_value = quantity * ref_price

        # Max order size check
        max_order_pct = self._risk_limits.get("max_order_size_pct")
        if max_order_pct is not None:
            max_order_value = equity * Decimal(str(max_order_pct)) / Decimal("100")
            if order_value > max_order_value:
                return f"Order value {order_value} exceeds max_order_size_pct ({max_order_pct}%)"

        # Max position size check (only for buys — sells reduce position)
        max_pos_pct = self._risk_limits.get("max_position_size_pct")
        if max_pos_pct is not None and side == "buy":
            existing_pos = self._positions.get(symbol)
            existing_value = Decimal("0")
            if existing_pos and existing_pos.quantity > 0:
                existing_value = existing_pos.quantity * ref_price
            resulting_value = existing_value + order_value
            max_pos_value = equity * Decimal(str(max_pos_pct)) / Decimal("100")
            if resulting_value > max_pos_value:
                return f"Position value {resulting_value} would exceed max_position_size_pct ({max_pos_pct}%)"

        # Daily loss limit check
        daily_loss_pct = self._risk_limits.get("daily_loss_limit_pct")
        if daily_loss_pct is not None:
            date_key = virtual_time.strftime("%Y-%m-%d")
            daily_pnl = self._daily_realized_pnl.get(date_key, Decimal("0"))
            max_loss = self._starting_balance * Decimal(str(daily_loss_pct)) / Decimal("100")
            if daily_pnl < Decimal("0") and abs(daily_pnl) >= max_loss:
                return f"Daily loss {abs(daily_pnl)} exceeds daily_loss_limit_pct ({daily_loss_pct}%)"

        return None

    def _track_daily_pnl(self, realized_pnl: Decimal, virtual_time: datetime) -> None:
        """Track realized PnL per day for daily loss limit enforcement."""
        date_key = virtual_time.strftime("%Y-%m-%d")
        self._daily_realized_pnl[date_key] = self._daily_realized_pnl.get(date_key, Decimal("0")) + realized_pnl

    # ── Internal helpers ─────────────────────────────────────────────────

    def _execute_market_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        ref_price: Decimal,
        virtual_time: datetime,
    ) -> OrderResult:
        """Execute a market-like fill with slippage and fees."""
        # Calculate slippage (simplified — no volume data in backtest)
        slippage_fraction = min(
            max(self._slippage_factor * Decimal("0.001"), _MIN_SLIPPAGE),
            _MAX_SLIPPAGE,
        )

        direction = Decimal("1") if side == "buy" else Decimal("-1")
        exec_price = ref_price * (Decimal("1") + direction * slippage_fraction)
        exec_price = exec_price.quantize(_QUANT8, rounding=ROUND_HALF_UP)

        quote_amount = (quantity * exec_price).quantize(_QUANT8, rounding=ROUND_HALF_UP)
        fee = (quote_amount * self._fee_fraction).quantize(_QUANT8, rounding=ROUND_HALF_UP)
        slippage_pct = (slippage_fraction * Decimal("100")).quantize(_QUANT6, rounding=ROUND_HALF_UP)

        # Validate balance
        base_asset = symbol.replace("USDT", "")
        if side == "buy":
            total_cost = quote_amount + fee
            usdt = self._balances.get("USDT", SandboxBalance(asset="USDT"))
            if usdt.available < total_cost:
                raise InsufficientBalanceError(asset="USDT", required=total_cost, available=usdt.available)
        else:
            pos = self._positions.get(symbol)
            base_bal = self._balances.get(base_asset, SandboxBalance(asset=base_asset))
            available_qty = base_bal.available
            if pos and pos.quantity < quantity and available_qty < quantity:
                raise InsufficientBalanceError(asset=base_asset, required=quantity, available=available_qty)

        # Execute balance changes
        realized_pnl: Decimal | None = None
        if side == "buy":
            self._debit_balance("USDT", quote_amount + fee)
            self._credit_balance(base_asset, quantity)
            self._update_position_buy(symbol, quantity, exec_price)
        else:
            realized_pnl = self._update_position_sell(symbol, quantity, exec_price)
            self._debit_balance(base_asset, quantity)
            self._credit_balance("USDT", quote_amount - fee)
            if realized_pnl is not None:
                self._cumulative_realized_pnl += realized_pnl
                self._track_daily_pnl(realized_pnl, virtual_time)

        self._cumulative_fees += fee

        # Record trade
        trade = SandboxTrade(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=exec_price,
            quote_amount=quote_amount,
            fee=fee,
            slippage_pct=slippage_pct,
            realized_pnl=realized_pnl,
            simulated_at=virtual_time,
        )
        self._trades.append(trade)

        # Update order record
        filled_order = SandboxOrder(
            id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=None,
            status="filled",
            created_at=virtual_time,
            filled_at=virtual_time,
            executed_price=exec_price,
            executed_qty=quantity,
            slippage_pct=slippage_pct,
            fee=fee,
        )
        # Replace existing order if present, or append new
        replaced = False
        for i, o in enumerate(self._orders):
            if o.id == order_id:
                self._orders[i] = filled_order
                replaced = True
                break
        if not replaced:
            self._orders.append(filled_order)

        return OrderResult(
            order_id=order_id,
            status="filled",
            executed_price=exec_price,
            executed_qty=quantity,
            slippage_pct=slippage_pct,
            fee=fee,
            realized_pnl=realized_pnl,
        )

    def _validate_balance_for_order(self, symbol: str, side: str, quantity: Decimal, ref_price: Decimal) -> None:
        """Raise if insufficient balance for the order."""
        if side == "buy":
            cost = quantity * ref_price
            usdt = self._balances.get("USDT", SandboxBalance(asset="USDT"))
            if usdt.available < cost:
                raise InsufficientBalanceError(asset="USDT", required=cost, available=usdt.available)
        else:
            base_asset = symbol.replace("USDT", "")
            bal = self._balances.get(base_asset, SandboxBalance(asset=base_asset))
            if bal.available < quantity:
                raise InsufficientBalanceError(asset=base_asset, required=quantity, available=bal.available)

    def _credit_balance(self, asset: str, amount: Decimal) -> None:
        if asset not in self._balances:
            self._balances[asset] = SandboxBalance(asset=asset)
        self._balances[asset].available += amount

    def _debit_balance(self, asset: str, amount: Decimal) -> None:
        if asset not in self._balances:
            self._balances[asset] = SandboxBalance(asset=asset)
        self._balances[asset].available -= amount

    def _lock_balance(self, asset: str, amount: Decimal) -> None:
        if asset not in self._balances:
            self._balances[asset] = SandboxBalance(asset=asset)
        bal = self._balances[asset]
        bal.available -= amount
        bal.locked += amount

    def _unlock_balance(self, asset: str, amount: Decimal) -> None:
        if asset not in self._balances:
            return
        bal = self._balances[asset]
        bal.locked -= amount
        bal.available += amount

    def _update_position_buy(self, symbol: str, quantity: Decimal, price: Decimal) -> None:
        """Add to or create a long position."""
        pos = self._positions.get(symbol)
        if pos is None or pos.quantity <= 0:
            self._positions[symbol] = SandboxPosition(
                symbol=symbol,
                quantity=quantity,
                avg_entry_price=price,
                total_cost=quantity * price,
            )
        else:
            new_qty = pos.quantity + quantity
            new_cost = pos.total_cost + quantity * price
            pos.quantity = new_qty
            pos.total_cost = new_cost
            pos.avg_entry_price = (new_cost / new_qty).quantize(_QUANT8, rounding=ROUND_HALF_UP)

    def _update_position_sell(self, symbol: str, quantity: Decimal, price: Decimal) -> Decimal | None:
        """Reduce a position and compute realized PnL."""
        pos = self._positions.get(symbol)
        if pos is None or pos.quantity <= 0:
            return None

        sell_qty = min(quantity, pos.quantity)
        realized = sell_qty * (price - pos.avg_entry_price)
        realized = realized.quantize(_QUANT8, rounding=ROUND_HALF_UP)

        pos.quantity -= sell_qty
        pos.total_cost = pos.quantity * pos.avg_entry_price
        pos.realized_pnl += realized

        return realized
