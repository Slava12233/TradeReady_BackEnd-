"""Tests for agent/strategies/rl/deploy.py :: PPODeployBridge, _weights_to_orders.

All platform API calls and SB3 model loading are mocked.  No running
platform or SB3 installation is required.

Test counts:
  TestOrderRecord            — 5
  TestWeightsToOrdersBuy     — 5
  TestWeightsToOrdersSell    — 4
  TestWeightsToOrdersEdge    — 7
  TestWeightsToOrdersFilter  — 4
  TestBuildReasoning         — 4
  TestPPODeployBridgeInit    — 3
  TestPPODeployBridgeModel   — 3

Total: 35
"""

from __future__ import annotations

from decimal import Decimal
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agent.strategies.rl.deploy import (
    _MIN_ORDER_VALUE_USDT,
    OrderRecord,
    PPODeployBridge,
    _build_reasoning,
    _weights_to_orders,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_deploy_config(**overrides: Any) -> MagicMock:
    """Minimal config mock for PPODeployBridge."""
    cfg = MagicMock()
    cfg.platform_api_key = "ak_live_test"
    cfg.platform_base_url = "http://localhost:8000"
    cfg.env_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    cfg.lookback_window = 30
    cfg.starting_balance = 10_000.0
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_positions(symbol_qty_price: list[tuple[str, float, float]]) -> list[dict[str, Any]]:
    """Build a platform-style positions list."""
    return [
        {"symbol": sym, "quantity": str(qty), "market_value": str(qty * price)}
        for sym, qty, price in symbol_qty_price
    ]


# ── TestOrderRecord ────────────────────────────────────────────────────────────


class TestOrderRecord:
    """OrderRecord is a frozen Pydantic model with string monetary fields."""

    def _valid_kwargs(self) -> dict[str, Any]:
        return {
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": "0.00042153",
            "value_usdt": "25.00",
            "price": "59305.00",
            "weight_before": 0.4,
            "weight_after": 0.5,
            "weight_delta": 0.1,
            "placed": True,
        }

    def test_valid_construction(self) -> None:
        rec = OrderRecord(**self._valid_kwargs())
        assert rec.symbol == "BTCUSDT"
        assert rec.side == "buy"
        assert rec.placed is True

    def test_is_frozen(self) -> None:
        rec = OrderRecord(**self._valid_kwargs())
        with pytest.raises(Exception):
            rec.placed = False  # type: ignore[misc]

    def test_error_defaults_none(self) -> None:
        rec = OrderRecord(**self._valid_kwargs())
        assert rec.error is None

    def test_quantity_is_string(self) -> None:
        rec = OrderRecord(**self._valid_kwargs())
        assert isinstance(rec.quantity, str)

    def test_value_usdt_is_string(self) -> None:
        rec = OrderRecord(**self._valid_kwargs())
        assert isinstance(rec.value_usdt, str)

    def test_price_is_string(self) -> None:
        rec = OrderRecord(**self._valid_kwargs())
        assert isinstance(rec.price, str)

    def test_json_round_trip(self) -> None:
        rec = OrderRecord(**self._valid_kwargs())
        restored = OrderRecord.model_validate_json(rec.model_dump_json())
        assert restored == rec


# ── TestWeightsToOrdersBuy ─────────────────────────────────────────────────────


class TestWeightsToOrdersBuy:
    """_weights_to_orders generates buy orders when target > current."""

    def test_buy_order_when_target_exceeds_current(self) -> None:
        """target=[0.5, 0.3, 0.2], current=[0.4, 0.4, 0.2] → buy asset0."""
        target_weights = np.array([0.5, 0.3, 0.2], dtype=np.float32)
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        prices = {
            "BTCUSDT": Decimal("60000"),
            "ETHUSDT": Decimal("3000"),
            "SOLUSDT": Decimal("150"),
        }
        # Current positions: BTC=40% of 10k, ETH=40% of 10k, SOL=20% of 10k
        equity = Decimal("10000")
        positions = [
            {"symbol": "BTCUSDT", "quantity": "0.06667", "market_value": "4000"},  # 40%
            {"symbol": "ETHUSDT", "quantity": "1.33333", "market_value": "4000"},  # 40%
            {"symbol": "SOLUSDT", "quantity": "13.33333", "market_value": "2000"},  # 20%
        ]
        balance_usdt = Decimal("0")  # fully invested

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        btc_order = next(o for o in orders if o.symbol == "BTCUSDT")
        # BTC needs to go 40% → 50%; delta = +10% of 10k = +1000 USDT worth
        # But balance_usdt=0, so buy_value=min(1000, 0)=0 → below_min_order_value
        assert btc_order.side == "buy"

    def test_buy_placed_true_when_sufficient_balance(self) -> None:
        """With enough cash and large delta, the buy order is placed=True."""
        target_weights = np.array([1.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("100")}
        equity = Decimal("1000")
        positions = []  # no existing positions
        balance_usdt = Decimal("1000")  # fully cash

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        assert len(orders) == 1
        assert orders[0].side == "buy"
        assert orders[0].placed is True

    def test_buy_quantity_uses_decimal(self) -> None:
        """Buy quantity in OrderRecord is a Decimal-precision string."""
        target_weights = np.array([1.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("100")}
        equity = Decimal("1000")
        positions = []
        balance_usdt = Decimal("1000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        qty_dec = Decimal(orders[0].quantity)
        # 1000 / 100 = 10 BTC; quantized to 8 decimal places
        assert qty_dec == Decimal("10.00000000")

    def test_buy_value_usdt_computed_correctly(self) -> None:
        """value_usdt = quantity * price, rounded to cents."""
        target_weights = np.array([1.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("100")}
        equity = Decimal("1000")
        positions = []
        balance_usdt = Decimal("1000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        value = Decimal(orders[0].value_usdt)
        # 10 BTC * 100 USDT = 1000.00
        assert value == Decimal("1000.00")

    def test_sell_then_buy_for_rebalance(self) -> None:
        """target=[0.5, 0.3, 0.2] with current=[0.4, 0.4, 0.2] → buy BTC, sell ETH."""
        target_weights = np.array([0.5, 0.3, 0.2], dtype=np.float32)
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        prices = {
            "BTCUSDT": Decimal("1000"),
            "ETHUSDT": Decimal("1000"),
            "SOLUSDT": Decimal("1000"),
        }
        equity = Decimal("10000")
        positions = [
            {"symbol": "BTCUSDT", "quantity": "4", "market_value": "4000"},  # 40%
            {"symbol": "ETHUSDT", "quantity": "4", "market_value": "4000"},  # 40%
            {"symbol": "SOLUSDT", "quantity": "2", "market_value": "2000"},  # 20%
        ]
        balance_usdt = Decimal("2000")  # available to buy BTC

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        by_symbol = {o.symbol: o for o in orders}
        assert by_symbol["BTCUSDT"].side == "buy"
        assert by_symbol["ETHUSDT"].side == "sell"
        # SOL delta = 0 → below threshold → not placed
        assert by_symbol["SOLUSDT"].placed is False


# ── TestWeightsToOrdersSell ────────────────────────────────────────────────────


class TestWeightsToOrdersSell:
    """_weights_to_orders generates sell orders when target < current."""

    def test_sell_order_generated(self) -> None:
        target_weights = np.array([0.0, 1.0], dtype=np.float32)
        symbols = ["BTCUSDT", "ETHUSDT"]
        prices = {"BTCUSDT": Decimal("1000"), "ETHUSDT": Decimal("1000")}
        equity = Decimal("10000")
        positions = [
            {"symbol": "BTCUSDT", "quantity": "5", "market_value": "5000"},
            {"symbol": "ETHUSDT", "quantity": "5", "market_value": "5000"},
        ]
        balance_usdt = Decimal("0")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        btc_order = next(o for o in orders if o.symbol == "BTCUSDT")
        assert btc_order.side == "sell"
        assert btc_order.placed is True

    def test_sell_quantity_capped_at_holding(self) -> None:
        """Sell quantity never exceeds current holding."""
        # Target wants 0% BTC but only has 2 BTC.  Should sell 2 BTC, not 5.
        target_weights = np.array([0.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("1000")}
        equity = Decimal("10000")
        positions = [{"symbol": "BTCUSDT", "quantity": "2", "market_value": "2000"}]
        balance_usdt = Decimal("8000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        qty = Decimal(orders[0].quantity)
        assert qty <= Decimal("2")

    def test_sell_placed_true_when_above_min_value(self) -> None:
        target_weights = np.array([0.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("1000")}
        equity = Decimal("10000")
        positions = [{"symbol": "BTCUSDT", "quantity": "5", "market_value": "5000"}]
        balance_usdt = Decimal("5000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        assert orders[0].placed is True

    def test_sell_price_stored_as_string(self) -> None:
        target_weights = np.array([0.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("59305.12345678")}
        equity = Decimal("10000")
        positions = [{"symbol": "BTCUSDT", "quantity": "1", "market_value": "59305"}]
        balance_usdt = Decimal("0")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        # Price must be preserved as a string — no float rounding
        assert orders[0].price == "59305.12345678"


# ── TestWeightsToOrdersEdge ────────────────────────────────────────────────────


class TestWeightsToOrdersEdge:
    """Edge cases: all-zero weights, single asset, over-unity weights, etc."""

    def test_all_weights_zero_go_to_cash(self) -> None:
        """When all target weights are 0, all existing positions get sell orders."""
        target_weights = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        prices = {
            "BTCUSDT": Decimal("1000"),
            "ETHUSDT": Decimal("1000"),
            "SOLUSDT": Decimal("1000"),
        }
        equity = Decimal("9000")
        positions = [
            {"symbol": "BTCUSDT", "quantity": "3", "market_value": "3000"},
            {"symbol": "ETHUSDT", "quantity": "3", "market_value": "3000"},
            {"symbol": "SOLUSDT", "quantity": "3", "market_value": "3000"},
        ]
        balance_usdt = Decimal("0")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        for order in orders:
            assert order.side == "sell", f"{order.symbol} should be a sell, got {order.side}"

    def test_single_asset_concentrate(self) -> None:
        """weight=[1.0] on a single asset buys everything available."""
        target_weights = np.array([1.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("100")}
        equity = Decimal("1000")
        positions = []
        balance_usdt = Decimal("1000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        assert len(orders) == 1
        assert orders[0].side == "buy"
        assert orders[0].placed is True

    def test_weights_sum_greater_than_one_normalised(self) -> None:
        """Weights summing > 1 are normalised; no order exceeds equity."""
        target_weights = np.array([0.8, 0.8], dtype=np.float32)  # sum = 1.6 > 1
        symbols = ["BTCUSDT", "ETHUSDT"]
        prices = {"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("100")}
        equity = Decimal("1000")
        positions = []
        balance_usdt = Decimal("1000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        # After normalisation each weight = 0.5; buy values sum to <= equity
        total_value = sum(Decimal(o.value_usdt) for o in orders if o.placed)
        assert total_value <= equity

    def test_zero_price_asset_skipped(self) -> None:
        """An asset with price=0 produces no order (division would be undefined)."""
        target_weights = np.array([0.5, 0.5], dtype=np.float32)
        symbols = ["BTCUSDT", "ZEROUSDT"]
        prices = {"BTCUSDT": Decimal("100"), "ZEROUSDT": Decimal("0")}
        equity = Decimal("1000")
        positions = []
        balance_usdt = Decimal("1000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        symbols_returned = {o.symbol for o in orders}
        assert "ZEROUSDT" not in symbols_returned

    def test_hold_when_delta_within_threshold(self) -> None:
        """When weight delta < threshold, placed=False with error='below_threshold'."""
        # threshold = 0.01 * 10000 = 100 USDT
        # target=0.501, current=0.5 → delta = 0.001 * 10000 = 10 USDT < 100
        target_weights = np.array([0.501], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("1000")}
        equity = Decimal("10000")
        positions = [{"symbol": "BTCUSDT", "quantity": "5", "market_value": "5000"}]
        balance_usdt = Decimal("5000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        assert len(orders) == 1
        assert orders[0].placed is False
        assert orders[0].error == "below_threshold"

    def test_weight_delta_populated_correctly(self) -> None:
        """weight_delta = weight_after - weight_before."""
        target_weights = np.array([0.6], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("1000")}
        equity = Decimal("10000")
        positions = [{"symbol": "BTCUSDT", "quantity": "4", "market_value": "4000"}]
        balance_usdt = Decimal("6000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        order = orders[0]
        # weight_before = 4000/10000 = 0.4; weight_after ≈ 0.6; delta ≈ 0.2
        delta = round(order.weight_after - order.weight_before, 6)
        assert abs(order.weight_delta - delta) < 1e-5

    def test_empty_positions_all_cash(self) -> None:
        """With no existing positions everything is treated as a buy."""
        target_weights = np.array([0.5, 0.5], dtype=np.float32)
        symbols = ["BTCUSDT", "ETHUSDT"]
        prices = {"BTCUSDT": Decimal("1000"), "ETHUSDT": Decimal("1000")}
        equity = Decimal("10000")
        positions = []
        balance_usdt = Decimal("10000")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
        )

        for order in orders:
            assert order.side == "buy"


# ── TestWeightsToOrdersFilter ──────────────────────────────────────────────────


class TestWeightsToOrdersFilter:
    """Orders below the minimum value threshold are skipped."""

    def test_buy_below_min_order_value_skipped(self) -> None:
        """A buy whose cash is < $1 is skipped with error='below_min_order_value'.

        Setup: equity=$1000, target weight=1.0 (100%), no current position,
        but balance is only $0.50.  delta > threshold but buy_value < $1.
        """
        # Equity large enough that delta exceeds threshold, but balance tiny.
        # threshold = 0.01 * 1000 = $10; delta = 1000 - 0 = $1000 > $10.
        # buy_value = min(1000, 0.50) = 0.50 < 1.00 → below_min_order_value.
        target_weights = np.array([1.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("1000")}
        equity = Decimal("1000")
        positions = []  # no existing position → current_value = 0
        balance_usdt = Decimal("0.50")  # only 50 cents available

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
            min_order_value=Decimal("1.00"),
        )

        # buy_value = min(1000, 0.50) = 0.50 < 1.00 → skipped
        order = orders[0]
        assert order.placed is False
        assert order.error == "below_min_order_value"

    def test_sell_below_min_order_value_skipped(self) -> None:
        """A sell whose value is < $1 is skipped with error='below_min_order_value'."""
        target_weights = np.array([0.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("10")}
        equity = Decimal("10")
        positions = [{"symbol": "BTCUSDT", "quantity": "0.05", "market_value": "0.50"}]
        balance_usdt = Decimal("9.50")

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
            min_order_value=Decimal("1.00"),
        )

        assert orders[0].placed is False
        assert orders[0].error == "below_min_order_value"

    def test_custom_min_order_value(self) -> None:
        """A higher min_order_value ($10) skips orders that default $1 would have placed."""
        target_weights = np.array([1.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("100")}
        equity = Decimal("100")
        positions = []
        balance_usdt = Decimal("5")  # only $5, below $10 threshold

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
            min_order_value=Decimal("10.00"),
        )

        assert orders[0].placed is False
        assert orders[0].error == "below_min_order_value"

    def test_order_placed_at_exactly_min_value(self) -> None:
        """An order at exactly the minimum value threshold is placed."""
        target_weights = np.array([1.0], dtype=np.float32)
        symbols = ["BTCUSDT"]
        prices = {"BTCUSDT": Decimal("100")}
        equity = Decimal("100")
        positions = []
        balance_usdt = Decimal("100")  # exactly $100 available

        orders = _weights_to_orders(
            target_weights=target_weights,
            symbols=symbols,
            prices=prices,
            positions=positions,
            equity=equity,
            balance_usdt=balance_usdt,
            min_order_value=Decimal("1.00"),
        )

        assert orders[0].placed is True


# ── TestBuildReasoning ─────────────────────────────────────────────────────────


class TestBuildReasoning:
    """_build_reasoning produces a human-readable summary string."""

    def _make_order(self, **kw: Any) -> OrderRecord:
        defaults = dict(
            symbol="BTCUSDT",
            side="buy",
            quantity="0.1",
            value_usdt="100.00",
            price="1000.00",
            weight_before=0.4,
            weight_after=0.5,
            weight_delta=0.1,
            placed=True,
        )
        defaults.update(kw)
        return OrderRecord(**defaults)

    def test_returns_string(self) -> None:
        reason = _build_reasoning(
            step=0,
            weights_before={"BTCUSDT": 0.4},
            weights_after={"BTCUSDT": 0.5},
            orders=[self._make_order()],
        )
        assert isinstance(reason, str)

    def test_contains_step_number(self) -> None:
        reason = _build_reasoning(
            step=5,
            weights_before={"BTCUSDT": 0.4},
            weights_after={"BTCUSDT": 0.5},
            orders=[],
        )
        assert "5" in reason

    def test_placed_order_count_in_output(self) -> None:
        orders = [self._make_order(placed=True), self._make_order(placed=True)]
        reason = _build_reasoning(
            step=0,
            weights_before={"BTCUSDT": 0.4},
            weights_after={"BTCUSDT": 0.5},
            orders=orders,
        )
        assert "2" in reason

    def test_no_orders_placed_message(self) -> None:
        skipped = self._make_order(
            placed=False, quantity="0", value_usdt="0", error="below_threshold"
        )
        reason = _build_reasoning(
            step=0,
            weights_before={"BTCUSDT": 0.4},
            weights_after={"BTCUSDT": 0.4},
            orders=[skipped],
        )
        assert "No orders placed" in reason


# ── TestPPODeployBridgeInit ────────────────────────────────────────────────────


class TestPPODeployBridgeInit:
    """PPODeployBridge constructor validates mode and stores attributes."""

    def test_valid_mode_backtest(self) -> None:
        cfg = _make_deploy_config()
        bridge = PPODeployBridge(model_path="/tmp/model.zip", config=cfg, mode="backtest")
        assert bridge._mode == "backtest"

    def test_valid_mode_live(self) -> None:
        cfg = _make_deploy_config()
        bridge = PPODeployBridge(model_path="/tmp/model.zip", config=cfg, mode="live")
        assert bridge._mode == "live"

    def test_invalid_mode_raises(self) -> None:
        cfg = _make_deploy_config()
        with pytest.raises(ValueError, match="mode"):
            PPODeployBridge(model_path="/tmp/model.zip", config=cfg, mode="paper")

    def test_model_not_loaded_at_init(self) -> None:
        """Model is loaded lazily; _model is None right after construction."""
        cfg = _make_deploy_config()
        bridge = PPODeployBridge(model_path="/tmp/model.zip", config=cfg)
        assert bridge._model is None

    def test_min_order_value_default(self) -> None:
        cfg = _make_deploy_config()
        bridge = PPODeployBridge(model_path="/tmp/model.zip", config=cfg)
        assert bridge._min_order_value == _MIN_ORDER_VALUE_USDT


# ── TestPPODeployBridgeModel ───────────────────────────────────────────────────


class TestPPODeployBridgeModel:
    """_load_model raises RuntimeError when SB3 is not installed."""

    def test_load_model_raises_when_sb3_missing(self) -> None:
        cfg = _make_deploy_config()
        bridge = PPODeployBridge(model_path="/tmp/model.zip", config=cfg)

        with patch.dict("sys.modules", {"stable_baselines3": None}):
            with pytest.raises(RuntimeError, match="stable-baselines3"):
                bridge._load_model()

    def test_load_model_calls_ppo_load(self) -> None:
        cfg = _make_deploy_config()
        bridge = PPODeployBridge(model_path="/fake/model.zip", config=cfg)

        mock_ppo_cls = MagicMock()
        mock_model = MagicMock()
        mock_ppo_cls.load.return_value = mock_model

        mock_sb3 = ModuleType("stable_baselines3")
        mock_sb3.PPO = mock_ppo_cls  # type: ignore[attr-defined]

        with patch.dict("sys.modules", {"stable_baselines3": mock_sb3}):
            bridge._load_model()

        mock_ppo_cls.load.assert_called_once_with("/fake/model.zip")
        assert bridge._model is mock_model

    def test_load_model_idempotent(self) -> None:
        """Calling _load_model twice does not reload the model."""
        cfg = _make_deploy_config()
        bridge = PPODeployBridge(model_path="/fake/model.zip", config=cfg)

        mock_ppo_cls = MagicMock()
        mock_model = MagicMock()
        mock_ppo_cls.load.return_value = mock_model

        mock_sb3 = ModuleType("stable_baselines3")
        mock_sb3.PPO = mock_ppo_cls  # type: ignore[attr-defined]

        with patch.dict("sys.modules", {"stable_baselines3": mock_sb3}):
            bridge._load_model()
            bridge._load_model()  # second call

        # PPO.load called only once
        mock_ppo_cls.load.assert_called_once()
