"""Strategy executor — evaluates entry/exit conditions and generates orders.

Given a strategy definition and indicator engine, the executor decides
which orders to place at each step of a backtest or live trading session.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.strategies.indicators import IndicatorEngine


class StrategyExecutor:
    """Evaluates a strategy definition against live indicators to produce orders.

    Args:
        definition: Strategy definition dict (validated ``StrategyDefinition``).
        indicator_engine: An ``IndicatorEngine`` instance with data loaded.
    """

    def __init__(self, definition: dict[str, Any], indicator_engine: IndicatorEngine) -> None:
        self._definition = definition
        self._indicators = indicator_engine
        self._pairs: list[str] = definition.get("pairs", [])
        self._entry_conditions: dict[str, Any] = definition.get("entry_conditions", {})
        self._exit_conditions: dict[str, Any] = definition.get("exit_conditions", {})
        self._position_size_pct = Decimal(str(definition.get("position_size_pct", 10)))
        self._max_positions: int = definition.get("max_positions", 3)
        # Tracking state
        self._peak_prices: dict[str, float] = {}
        self._entry_candles: dict[str, int] = {}
        self._step_count: int = 0

    def decide(self, step_result: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate conditions and return a list of orders to place.

        Args:
            step_result: Dict with keys ``prices``, ``portfolio``, ``positions``,
                         ``virtual_time``, ``step``.

        Returns:
            List of order dicts with keys: ``symbol``, ``side``, ``type``,
            ``quantity``.
        """
        self._step_count += 1
        orders: list[dict[str, Any]] = []
        prices = step_result.get("prices", {})
        positions = step_result.get("positions", [])
        portfolio = step_result.get("portfolio", {})

        # Update indicators for each pair
        for symbol in self._pairs:
            price_str = prices.get(symbol)
            if price_str is None:
                continue
            price = float(str(price_str))
            self._indicators.update(symbol, {
                "close": price,
                "high": price,
                "low": price,
                "volume": 0,
            })

        # Check exits first (priority: stop_loss → take_profit → trailing_stop → max_hold → indicators)
        for pos in positions:
            symbol = pos.get("symbol", "")
            if symbol not in self._pairs:
                continue
            exit_orders = self._check_exits(symbol, pos, prices)
            orders.extend(exit_orders)

        # Check entries
        open_position_symbols = {p.get("symbol", "") for p in positions}
        current_position_count = len(positions)

        for symbol in self._pairs:
            if symbol in open_position_symbols:
                continue
            if current_position_count >= self._max_positions:
                break
            if not self._indicators.has_data(symbol):
                continue
            if self._should_enter(symbol):
                qty = self._calculate_quantity(symbol, prices, portfolio)
                if qty > Decimal("0"):
                    orders.append({
                        "symbol": symbol,
                        "side": "buy",
                        "type": "market",
                        "quantity": qty,
                    })
                    self._entry_candles[symbol] = self._step_count
                    price_str = prices.get(symbol)
                    if price_str is not None:
                        self._peak_prices[symbol] = float(str(price_str))
                    current_position_count += 1

        return orders

    def _should_enter(self, symbol: str) -> bool:
        """Check if ALL entry conditions pass for a symbol."""
        indicators = self._indicators.compute(symbol)
        active_conditions = {k: v for k, v in self._entry_conditions.items() if v is not None}
        if not active_conditions:
            return False
        return all(
            self._evaluate_entry_condition(key, value, indicators)
            for key, value in active_conditions.items()
        )

    def _check_exits(
        self,
        symbol: str,
        position: dict[str, Any],
        prices: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Check exit conditions for a position. ANY condition triggers exit."""
        orders: list[dict[str, Any]] = []
        price_str = prices.get(symbol)
        if price_str is None:
            return orders

        current_price = float(str(price_str))
        entry_price = float(str(position.get("avg_entry_price", position.get("entry_price", current_price))))
        quantity = Decimal(str(position.get("quantity", position.get("size", "0"))))

        if quantity <= Decimal("0"):
            return orders

        # Update peak price tracking for trailing stop
        if symbol in self._peak_prices:
            self._peak_prices[symbol] = max(self._peak_prices[symbol], current_price)
        else:
            self._peak_prices[symbol] = current_price

        should_exit = False

        # 1. Stop loss
        stop_loss_pct = self._exit_conditions.get("stop_loss_pct")
        if stop_loss_pct is not None and entry_price > 0:
            loss_pct = (entry_price - current_price) / entry_price * 100
            if loss_pct >= float(stop_loss_pct):
                should_exit = True

        # 2. Take profit
        take_profit_pct = self._exit_conditions.get("take_profit_pct")
        if not should_exit and take_profit_pct is not None and entry_price > 0:
            gain_pct = (current_price - entry_price) / entry_price * 100
            if gain_pct >= float(take_profit_pct):
                should_exit = True

        # 3. Trailing stop
        trailing_stop_pct = self._exit_conditions.get("trailing_stop_pct")
        if not should_exit and trailing_stop_pct is not None:
            peak = self._peak_prices.get(symbol, current_price)
            if peak > 0:
                drop_pct = (peak - current_price) / peak * 100
                if drop_pct >= float(trailing_stop_pct):
                    should_exit = True

        # 4. Max hold candles
        max_hold = self._exit_conditions.get("max_hold_candles")
        if not should_exit and max_hold is not None:
            entry_step = self._entry_candles.get(symbol, 0)
            if self._step_count - entry_step >= int(max_hold):
                should_exit = True

        # 5. Indicator-based exits
        if not should_exit:
            indicators = self._indicators.compute(symbol)
            should_exit = self._should_exit_indicators(indicators)

        if should_exit:
            orders.append({
                "symbol": symbol,
                "side": "sell",
                "type": "market",
                "quantity": quantity,
            })
            self._peak_prices.pop(symbol, None)
            self._entry_candles.pop(symbol, None)

        return orders

    def _should_exit_indicators(self, indicators: dict[str, float | None]) -> bool:
        """Check indicator-based exit conditions. ANY triggers exit."""
        rsi_above = self._exit_conditions.get("rsi_above")
        if rsi_above is not None and indicators.get("rsi_14") is not None:
            if indicators["rsi_14"] > float(rsi_above):  # type: ignore[operator]
                return True

        rsi_below = self._exit_conditions.get("rsi_below")
        if rsi_below is not None and indicators.get("rsi_14") is not None:
            if indicators["rsi_14"] < float(rsi_below):  # type: ignore[operator]
                return True

        macd_cross_below = self._exit_conditions.get("macd_cross_below")
        if macd_cross_below and indicators.get("macd_line") is not None and indicators.get("macd_signal") is not None:
            if indicators["macd_line"] < indicators["macd_signal"]:  # type: ignore[operator]
                return True

        return False

    def _evaluate_entry_condition(
        self,
        key: str,
        value: Any,  # noqa: ANN401
        indicators: dict[str, float | None],
    ) -> bool:
        """Evaluate a single entry condition."""
        if key == "rsi_below":
            rsi = indicators.get("rsi_14")
            return rsi is not None and rsi < float(value)
        if key == "rsi_above":
            rsi = indicators.get("rsi_14")
            return rsi is not None and rsi > float(value)
        if key == "macd_cross_above":
            ml, ms = indicators.get("macd_line"), indicators.get("macd_signal")
            return ml is not None and ms is not None and ml > ms
        if key == "macd_cross_below":
            ml, ms = indicators.get("macd_line"), indicators.get("macd_signal")
            return ml is not None and ms is not None and ml < ms
        if key == "price_above_sma":
            sma = indicators.get(f"sma_{value}") or indicators.get("sma_20")
            price = indicators.get("current_price")
            return sma is not None and price is not None and price > sma
        if key == "price_below_sma":
            sma = indicators.get(f"sma_{value}") or indicators.get("sma_20")
            price = indicators.get("current_price")
            return sma is not None and price is not None and price < sma
        if key == "price_above_ema":
            ema = indicators.get(f"ema_{value}") or indicators.get("ema_12")
            price = indicators.get("current_price")
            return ema is not None and price is not None and price > ema
        if key == "price_below_ema":
            ema = indicators.get(f"ema_{value}") or indicators.get("ema_12")
            price = indicators.get("current_price")
            return ema is not None and price is not None and price < ema
        if key == "bb_below_lower":
            bb_lower = indicators.get("bb_lower")
            price = indicators.get("current_price")
            return bb_lower is not None and price is not None and price < bb_lower
        if key == "bb_above_upper":
            bb_upper = indicators.get("bb_upper")
            price = indicators.get("current_price")
            return bb_upper is not None and price is not None and price > bb_upper
        if key == "adx_above":
            adx = indicators.get("adx")
            return adx is not None and adx > float(value)
        if key == "volume_above_ma":
            vol = indicators.get("current_volume")
            vol_ma = indicators.get("volume_ma_20")
            return vol is not None and vol_ma is not None and vol_ma > 0 and vol > vol_ma * float(value)
        return False

    def _calculate_quantity(
        self,
        symbol: str,
        prices: dict[str, Any],
        portfolio: dict[str, Any],
    ) -> Decimal:
        """Calculate order quantity based on position_size_pct of equity."""
        price_str = prices.get(symbol)
        if price_str is None:
            return Decimal("0")
        price = Decimal(str(price_str))
        if price <= Decimal("0"):
            return Decimal("0")

        equity = Decimal(str(portfolio.get("total_equity", portfolio.get("equity", "0"))))
        if equity <= Decimal("0"):
            return Decimal("0")

        position_value = equity * self._position_size_pct / Decimal("100")
        quantity = position_value / price
        return quantity.quantize(Decimal("0.00000001"))

    @staticmethod
    def _has_position(symbol: str, positions: list[dict[str, Any]]) -> bool:
        """Check if there is an open position for a symbol."""
        return any(p.get("symbol") == symbol for p in positions)
