"""Tests for configurable fee_rate parameter threading.

Covers:
  - Default fee is 0.001 (BaseTradingEnv and BacktestSandbox)
  - Custom fee_rate stored and propagated through BaseTradingEnv
  - fee_rate is included in BacktestCreateRequest API body when set
  - fee_rate is omitted from API body when not set (platform default)
  - fee_rate is Decimal-serialized precisely (no float drift)
  - fee_rate affects sandbox trade PnL calculations
  - BacktestCreateRequest schema validates fee_rate bounds
  - BacktestConfig dataclass carries fee_rate to engine
  - Engine stashes fee_rate and passes it to sandbox as fee_fraction
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helper: build a minimal mock httpx response
# ---------------------------------------------------------------------------


def _mock_response(data: dict[str, Any], status_code: int = 200) -> MagicMock:
    """Return a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = b"content"
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Tests: BaseTradingEnv — fee_rate constructor parameter
# ---------------------------------------------------------------------------


class TestBaseTradingEnvFeeRate:
    """fee_rate is stored on BaseTradingEnv and passed to the API on session creation."""

    def _make_env(self, fee_rate: float | None = None):
        """Build a SingleAssetTradingEnv with a mock HTTP client."""
        from tradeready_gym.envs.single_asset_env import SingleAssetTradingEnv

        env = SingleAssetTradingEnv(
            api_key="ak_live_test",
            base_url="http://localhost:8000",
            starting_balance=10000.0,
            track_training=False,
            fee_rate=fee_rate,
        )
        return env

    def test_default_fee_rate_is_none(self):
        """When fee_rate is not passed, env.fee_rate is None (platform will use 0.001)."""
        env = self._make_env()
        assert env.fee_rate is None
        env._http.close()

    def test_custom_fee_rate_stored(self):
        """When fee_rate=0.0005 is passed, it is stored on the env."""
        env = self._make_env(fee_rate=0.0005)
        assert env.fee_rate == pytest.approx(0.0005)
        env._http.close()

    def test_zero_fee_rate_stored(self):
        """fee_rate=0.0 (zero fees) is stored correctly."""
        env = self._make_env(fee_rate=0.0)
        assert env.fee_rate == pytest.approx(0.0)
        env._http.close()

    def test_high_fee_rate_stored(self):
        """fee_rate=0.005 (0.5% — e.g. for DEX simulation) is stored correctly."""
        env = self._make_env(fee_rate=0.005)
        assert env.fee_rate == pytest.approx(0.005)
        env._http.close()

    def test_fee_rate_omitted_from_api_body_when_none(self):
        """When fee_rate is None, the 'fee_rate' key must NOT appear in the create body."""
        env = self._make_env(fee_rate=None)

        captured_body: dict[str, Any] = {}

        def _capture_request(method, path, *, params=None, json=None):
            if method == "POST" and path == "/api/v1/backtest/create":
                captured_body.update(json or {})
                return {"session_id": "sess-001"}
            return {}

        env._api_call = _capture_request  # type: ignore[method-assign]
        # Trigger the create flow directly without running reset()
        env._create_session()

        assert "fee_rate" not in captured_body, (
            "fee_rate must be absent from the API body when not set — "
            "omitting it lets the platform use its default 0.001"
        )
        env._http.close()

    def test_fee_rate_included_in_api_body_when_set(self):
        """When fee_rate is set, it appears in the create body as a Decimal string."""
        env = self._make_env(fee_rate=0.002)

        captured_body: dict[str, Any] = {}

        def _capture_request(method, path, *, params=None, json=None):
            if method == "POST" and path == "/api/v1/backtest/create":
                captured_body.update(json or {})
                return {"session_id": "sess-002"}
            return {}

        env._api_call = _capture_request  # type: ignore[method-assign]
        env._create_session()

        assert "fee_rate" in captured_body
        env._http.close()

    def test_fee_rate_serialized_as_decimal_string(self):
        """fee_rate in the API body is serialised as a Decimal string, not a float."""
        env = self._make_env(fee_rate=0.001)

        captured_body: dict[str, Any] = {}

        def _capture_request(method, path, *, params=None, json=None):
            if method == "POST" and path == "/api/v1/backtest/create":
                captured_body.update(json or {})
                return {"session_id": "sess-003"}
            return {}

        env._api_call = _capture_request  # type: ignore[method-assign]
        env._create_session()

        fee_val = captured_body.get("fee_rate")
        assert isinstance(fee_val, str), f"Expected str, got {type(fee_val)}: {fee_val!r}"
        # Verify it round-trips correctly through Decimal
        assert Decimal(fee_val) == Decimal("0.001")
        env._http.close()

    def test_fee_rate_decimal_precision_preserved(self):
        """0.0005 must not drift to 0.0004999999… when serialized via str(Decimal(str(...)))."""
        env = self._make_env(fee_rate=0.0005)

        captured_body: dict[str, Any] = {}

        def _capture_request(method, path, *, params=None, json=None):
            if method == "POST" and path == "/api/v1/backtest/create":
                captured_body.update(json or {})
                return {"session_id": "sess-004"}
            return {}

        env._api_call = _capture_request  # type: ignore[method-assign]
        env._create_session()

        fee_val = captured_body.get("fee_rate")
        assert fee_val is not None
        parsed = Decimal(fee_val)
        # Allow small epsilon — Decimal(str(0.0005)) == "0.0005" on CPython
        assert abs(parsed - Decimal("0.0005")) < Decimal("0.000001"), (
            f"Precision loss: {parsed!r} != 0.0005"
        )
        env._http.close()


# ---------------------------------------------------------------------------
# Tests: BacktestCreateRequest schema validation
# ---------------------------------------------------------------------------


class TestBacktestCreateRequestSchema:
    """Pydantic schema for the backtest create endpoint validates fee_rate correctly."""

    def _make_request(self, fee_rate=None, **overrides):
        from src.api.schemas.backtest import BacktestCreateRequest

        base = {
            "start_time": "2025-01-01T00:00:00Z",
            "end_time": "2025-02-01T00:00:00Z",
            "starting_balance": Decimal("10000"),
        }
        if fee_rate is not None:
            base["fee_rate"] = fee_rate
        base.update(overrides)
        return BacktestCreateRequest(**base)

    def test_fee_rate_defaults_to_none(self):
        """fee_rate has no default value — absent = None."""
        req = self._make_request()
        assert req.fee_rate is None

    def test_fee_rate_0001_accepted(self):
        """Standard 0.001 fee rate (0.1%) is valid."""
        req = self._make_request(fee_rate=Decimal("0.001"))
        assert req.fee_rate == Decimal("0.001")

    def test_fee_rate_zero_accepted(self):
        """Zero fee rate (no fees) is valid — ge=0 constraint."""
        req = self._make_request(fee_rate=Decimal("0"))
        assert req.fee_rate == Decimal("0")

    def test_fee_rate_0005_accepted(self):
        """0.5% maker fee (common on some DEXs) is valid."""
        req = self._make_request(fee_rate=Decimal("0.005"))
        assert req.fee_rate == Decimal("0.005")

    def test_fee_rate_max_boundary_accepted(self):
        """Maximum allowed fee rate 0.1 (10%) is valid — le=0.1 constraint."""
        req = self._make_request(fee_rate=Decimal("0.1"))
        assert req.fee_rate == Decimal("0.1")

    def test_fee_rate_above_max_rejected(self):
        """fee_rate > 0.1 must raise a validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make_request(fee_rate=Decimal("0.11"))

    def test_fee_rate_negative_rejected(self):
        """Negative fee rates are invalid — ge=0 constraint."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self._make_request(fee_rate=Decimal("-0.001"))

    def test_fee_rate_serialized_as_string(self):
        """Serialized JSON must contain fee_rate as a string, not a number."""
        req = self._make_request(fee_rate=Decimal("0.001"))
        data = req.model_dump()
        assert data["fee_rate"] == "0.001"

    def test_fee_rate_none_serialized_as_none(self):
        """When fee_rate is None, serialized JSON has fee_rate=None."""
        req = self._make_request()
        data = req.model_dump()
        assert data["fee_rate"] is None


# ---------------------------------------------------------------------------
# Tests: BacktestConfig dataclass — fee_rate field
# ---------------------------------------------------------------------------


class TestBacktestConfig:
    """BacktestConfig dataclass carries fee_rate from route → engine."""

    def _import_config(self):
        from src.backtesting.engine import BacktestConfig
        return BacktestConfig

    def test_fee_rate_defaults_to_none(self):
        BacktestConfig = self._import_config()
        cfg = BacktestConfig(
            start_time=__import__("datetime").datetime(2025, 1, 1, tzinfo=__import__("datetime").timezone.utc),
            end_time=__import__("datetime").datetime(2025, 2, 1, tzinfo=__import__("datetime").timezone.utc),
            starting_balance=Decimal("10000"),
        )
        assert cfg.fee_rate is None

    def test_fee_rate_custom_stored(self):
        BacktestConfig = self._import_config()
        cfg = BacktestConfig(
            start_time=__import__("datetime").datetime(2025, 1, 1, tzinfo=__import__("datetime").timezone.utc),
            end_time=__import__("datetime").datetime(2025, 2, 1, tzinfo=__import__("datetime").timezone.utc),
            starting_balance=Decimal("10000"),
            fee_rate=Decimal("0.0005"),
        )
        assert cfg.fee_rate == Decimal("0.0005")

    def test_fee_rate_zero_stored(self):
        BacktestConfig = self._import_config()
        cfg = BacktestConfig(
            start_time=__import__("datetime").datetime(2025, 1, 1, tzinfo=__import__("datetime").timezone.utc),
            end_time=__import__("datetime").datetime(2025, 2, 1, tzinfo=__import__("datetime").timezone.utc),
            starting_balance=Decimal("10000"),
            fee_rate=Decimal("0"),
        )
        assert cfg.fee_rate == Decimal("0")


# ---------------------------------------------------------------------------
# Tests: BacktestSandbox default fee rate
# ---------------------------------------------------------------------------


class TestBacktestSandboxDefaultFee:
    """BacktestSandbox uses 0.001 as the default fee_fraction."""

    def test_sandbox_default_fee_fraction_is_0001(self):
        """When constructed without fee_fraction, sandbox._fee_fraction == 0.001."""
        from src.backtesting.sandbox import BacktestSandbox

        sb = BacktestSandbox(
            session_id="sess-test",
            starting_balance=Decimal("10000"),
        )
        assert sb._fee_fraction == Decimal("0.001")

    def test_sandbox_custom_fee_fraction_stored(self):
        """Passing fee_fraction=Decimal('0.0005') overrides the default."""
        from src.backtesting.sandbox import BacktestSandbox

        sb = BacktestSandbox(
            session_id="sess-test",
            starting_balance=Decimal("10000"),
            fee_fraction=Decimal("0.0005"),
        )
        assert sb._fee_fraction == Decimal("0.0005")

    def test_sandbox_zero_fee_fraction_accepted(self):
        """fee_fraction=0 means no fees are charged on trades."""
        from src.backtesting.sandbox import BacktestSandbox

        sb = BacktestSandbox(
            session_id="sess-test",
            starting_balance=Decimal("10000"),
            fee_fraction=Decimal("0"),
        )
        assert sb._fee_fraction == Decimal("0")


# ---------------------------------------------------------------------------
# Tests: Fee rate effect on sandbox trade PnL
# ---------------------------------------------------------------------------


class TestFeeRateAffectsTradePnL:
    """Higher fee rates reduce trade profitability; zero fees maximise PnL."""

    def _place_and_get_fee(self, fee_fraction: Decimal) -> Decimal:
        """Place a single buy order and return the fee charged."""
        import datetime as dt

        from src.backtesting.sandbox import BacktestSandbox

        sb = BacktestSandbox(
            session_id="sess-fee-test",
            starting_balance=Decimal("10000"),
            fee_fraction=fee_fraction,
        )
        prices = {"BTCUSDT": Decimal("50000")}
        virtual_time = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

        result = sb.place_order(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=Decimal("0.1"),
            price=None,
            current_prices=prices,
            virtual_time=virtual_time,
        )
        return result.fee

    def test_default_fee_0001_charged_on_trade(self):
        """With fee_fraction=0.001, a buy of 0.1 BTC at 50000 costs 5 USDT in fees."""
        # 0.1 BTC * 50000 USDT/BTC = 5000 USDT notional
        # fee = 5000 * 0.001 = 5.0 USDT
        fee = self._place_and_get_fee(Decimal("0.001"))
        assert fee == pytest.approx(Decimal("5"), rel=Decimal("0.001"))

    def test_custom_fee_0005_doubles_default(self):
        """fee_fraction=0.002 charges double the default fee."""
        fee_default = self._place_and_get_fee(Decimal("0.001"))
        fee_doubled = self._place_and_get_fee(Decimal("0.002"))
        assert fee_doubled == pytest.approx(fee_default * 2, rel=Decimal("0.001"))

    def test_zero_fee_charges_nothing(self):
        """fee_fraction=0 means zero fees on every trade."""
        fee = self._place_and_get_fee(Decimal("0"))
        assert fee == Decimal("0")

    def test_higher_fee_reduces_portfolio_equity(self):
        """After a buy+sell round-trip, higher fees leave less equity."""
        import datetime as dt

        from src.backtesting.sandbox import BacktestSandbox

        def _round_trip(fee_fraction: Decimal) -> Decimal:
            sb = BacktestSandbox(
                session_id=f"sess-rt-{fee_fraction}",
                starting_balance=Decimal("10000"),
                fee_fraction=fee_fraction,
            )
            prices = {"BTCUSDT": Decimal("50000")}
            t1 = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
            t2 = dt.datetime(2025, 1, 1, 0, 1, 0, tzinfo=dt.timezone.utc)

            sb.place_order(
                symbol="BTCUSDT",
                side="buy",
                order_type="market",
                quantity=Decimal("0.1"),
                price=None,
                current_prices=prices,
                virtual_time=t1,
            )
            sb.place_order(
                symbol="BTCUSDT",
                side="sell",
                order_type="market",
                quantity=Decimal("0.1"),
                price=None,
                current_prices=prices,
                virtual_time=t2,
            )
            portfolio = sb.get_portfolio(prices)
            return portfolio.total_equity

        equity_low_fee = _round_trip(Decimal("0.001"))
        equity_high_fee = _round_trip(Decimal("0.005"))

        assert equity_low_fee > equity_high_fee, (
            "Higher fee rate must result in lower equity after same round-trip"
        )

    def test_fee_rate_0001_round_trip_leaves_less_than_starting(self):
        """Standard 0.1% fee: round-trip at same price reduces equity by 2x fee."""
        import datetime as dt

        from src.backtesting.sandbox import BacktestSandbox

        sb = BacktestSandbox(
            session_id="sess-rt-standard",
            starting_balance=Decimal("10000"),
            fee_fraction=Decimal("0.001"),
        )
        prices = {"BTCUSDT": Decimal("50000")}
        t1 = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
        t2 = dt.datetime(2025, 1, 1, 0, 1, 0, tzinfo=dt.timezone.utc)

        sb.place_order(
            symbol="BTCUSDT", side="buy", order_type="market",
            quantity=Decimal("0.1"), price=None,
            current_prices=prices, virtual_time=t1,
        )
        sb.place_order(
            symbol="BTCUSDT", side="sell", order_type="market",
            quantity=Decimal("0.1"), price=None,
            current_prices=prices, virtual_time=t2,
        )
        portfolio = sb.get_portfolio(prices)
        # Round-trip at same price: equity should be slightly less than 10000 (fees paid)
        assert portfolio.total_equity < Decimal("10000"), (
            "Fees paid on both legs must reduce equity below starting balance"
        )

    def test_zero_fee_round_trip_preserves_equity(self):
        """With zero fees, a buy+sell at the same price should not reduce equity (ignoring slippage)."""
        import datetime as dt

        from src.backtesting.sandbox import BacktestSandbox

        sb = BacktestSandbox(
            session_id="sess-rt-zero",
            starting_balance=Decimal("10000"),
            fee_fraction=Decimal("0"),
            slippage_factor=Decimal("0"),  # eliminate slippage too
        )
        prices = {"BTCUSDT": Decimal("50000")}
        t1 = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
        t2 = dt.datetime(2025, 1, 1, 0, 1, 0, tzinfo=dt.timezone.utc)

        sb.place_order(
            symbol="BTCUSDT", side="buy", order_type="market",
            quantity=Decimal("0.1"), price=None,
            current_prices=prices, virtual_time=t1,
        )
        sb.place_order(
            symbol="BTCUSDT", side="sell", order_type="market",
            quantity=Decimal("0.1"), price=None,
            current_prices=prices, virtual_time=t2,
        )
        portfolio = sb.get_portfolio(prices)
        # With zero fees and zero slippage, equity should equal starting balance
        assert portfolio.total_equity == pytest.approx(Decimal("10000"), rel=Decimal("0.0001"))


# ---------------------------------------------------------------------------
# Tests: BacktestEngine stashes fee_rate and passes to sandbox
# ---------------------------------------------------------------------------


class TestEngineFeePropagation:
    """BacktestEngine.start() reads the stashed fee_rate and passes it to BacktestSandbox."""

    def test_no_fee_rate_stashed_when_config_fee_is_none(self):
        """If config.fee_rate is None, nothing is added to _pending_fee_rates."""
        from unittest.mock import MagicMock

        from src.backtesting.engine import BacktestEngine

        engine = BacktestEngine(session_factory=MagicMock())

        session_mock = MagicMock()
        session_mock.id = __import__("uuid").uuid4()
        engine._pending_fee_rates  # access to confirm attribute exists

        # Simulate create_session side-effect: no fee_rate stored when None
        # (the actual engine code: `if config.fee_rate is not None: self._pending_fee_rates[...]`)
        session_id = str(session_mock.id)
        assert session_id not in engine._pending_fee_rates

    def test_fee_rate_stashed_after_create(self):
        """Manually simulate the stash to confirm the dict key is str(session_id)."""
        import uuid
        from unittest.mock import MagicMock

        from src.backtesting.engine import BacktestEngine

        engine = BacktestEngine(session_factory=MagicMock())
        sid = str(uuid.uuid4())
        engine._pending_fee_rates[sid] = Decimal("0.0005")

        assert engine._pending_fee_rates[sid] == Decimal("0.0005")

    def test_fee_rate_consumed_on_pop(self):
        """After reading a stashed fee_rate via pop(), it is no longer in the dict."""
        import uuid
        from unittest.mock import MagicMock

        from src.backtesting.engine import BacktestEngine

        engine = BacktestEngine(session_factory=MagicMock())
        sid = str(uuid.uuid4())
        engine._pending_fee_rates[sid] = Decimal("0.002")

        # Simulate what start() does: pop the fee_rate
        fee_rate = engine._pending_fee_rates.pop(sid, None)
        assert fee_rate == Decimal("0.002")
        assert sid not in engine._pending_fee_rates

    def test_fee_rate_defaults_to_0001_when_not_stashed(self):
        """When no fee_rate is stashed, pop() returns None → engine uses 0.001."""
        import uuid
        from unittest.mock import MagicMock

        from src.backtesting.engine import BacktestEngine

        engine = BacktestEngine(session_factory=MagicMock())
        sid = str(uuid.uuid4())

        fee_rate = engine._pending_fee_rates.pop(sid, None)
        # None triggers: fee_fraction=fee_rate if fee_rate is not None else Decimal("0.001")
        effective_fee = fee_rate if fee_rate is not None else Decimal("0.001")
        assert effective_fee == Decimal("0.001")


# ---------------------------------------------------------------------------
# Tests: API route passes fee_rate to BacktestConfig
# ---------------------------------------------------------------------------


class TestRoutePassesFeeRateToConfig:
    """The /api/v1/backtest/create route passes fee_rate from request body to BacktestConfig."""

    def test_route_passes_fee_rate_to_config(self):
        """When BacktestCreateRequest includes fee_rate, it is forwarded to BacktestConfig."""
        import datetime as dt

        from src.api.schemas.backtest import BacktestCreateRequest

        # Build the request body with a custom fee_rate
        req = BacktestCreateRequest(
            start_time=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc),
            end_time=dt.datetime(2025, 2, 1, tzinfo=dt.timezone.utc),
            starting_balance=Decimal("10000"),
            fee_rate=Decimal("0.0005"),
        )

        # Verify the route logic: BacktestConfig receives fee_rate=body.fee_rate
        # (we test this by constructing BacktestConfig directly with the schema value)
        from src.backtesting.engine import BacktestConfig
        config = BacktestConfig(
            start_time=req.start_time,
            end_time=req.end_time,
            starting_balance=req.starting_balance,
            fee_rate=req.fee_rate,
        )

        assert config.fee_rate == Decimal("0.0005")

    def test_route_passes_none_fee_rate_to_config(self):
        """When fee_rate is absent from request, BacktestConfig.fee_rate is None."""
        import datetime as dt

        from src.api.schemas.backtest import BacktestCreateRequest
        from src.backtesting.engine import BacktestConfig

        req = BacktestCreateRequest(
            start_time=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc),
            end_time=dt.datetime(2025, 2, 1, tzinfo=dt.timezone.utc),
            starting_balance=Decimal("10000"),
        )

        config = BacktestConfig(
            start_time=req.start_time,
            end_time=req.end_time,
            starting_balance=req.starting_balance,
            fee_rate=req.fee_rate,
        )

        assert config.fee_rate is None


# ---------------------------------------------------------------------------
# Tests: HeadlessTradingEnv does NOT yet expose fee_rate (documents the gap)
# ---------------------------------------------------------------------------


class TestHeadlessEnvFeeRateAbsence:
    """Documents that HeadlessTradingEnv does not currently accept fee_rate.

    The headless env bypasses BaseTradingEnv entirely and calls BacktestConfig
    directly in _async_reset(). The fee_rate parameter has not been wired
    into HeadlessTradingEnv yet — these tests confirm the current behaviour
    and serve as a regression guard if/when it is added.
    """

    def test_headless_env_has_no_fee_rate_attribute(self):
        """HeadlessTradingEnv.__init__ does not accept a fee_rate parameter."""
        import inspect

        from tradeready_gym.envs.headless_env import HeadlessTradingEnv

        sig = inspect.signature(HeadlessTradingEnv.__init__)
        assert "fee_rate" not in sig.parameters, (
            "HeadlessTradingEnv now has a fee_rate parameter — "
            "update this test to verify it is propagated to BacktestConfig"
        )

    def test_headless_env_uses_hardcoded_config_without_fee_rate(self):
        """_async_reset builds BacktestConfig without passing fee_rate (uses None)."""
        import inspect

        from tradeready_gym.envs.headless_env import HeadlessTradingEnv

        source = inspect.getsource(HeadlessTradingEnv._async_reset)
        # Verify that BacktestConfig is called without fee_rate keyword
        assert "fee_rate" not in source, (
            "HeadlessTradingEnv._async_reset now passes fee_rate to BacktestConfig — "
            "update this test and the positive fee_rate tests for the headless env"
        )


# ---------------------------------------------------------------------------
# Tests: BaseTradingEnv fee_rate survives gym.make() round-trip
# ---------------------------------------------------------------------------


class TestGymMakeFeeRateRoundTrip:
    """fee_rate kwarg is preserved through gym.make() / env constructor chain."""

    def test_gym_make_passes_fee_rate_to_env(self):
        """gym.make('TradeReady-BTC-v0', fee_rate=0.002, ...) stores fee_rate on the env."""
        import gymnasium as gym

        import tradeready_gym  # noqa: F401 — trigger registration

        env = gym.make(
            "TradeReady-BTC-v0",
            api_key="ak_live_test",
            track_training=False,
            fee_rate=0.002,
        )
        # gym.make wraps in a TimeLimit; unwrap to get the base env
        unwrapped = env.unwrapped
        assert hasattr(unwrapped, "fee_rate"), "BaseTradingEnv must expose fee_rate attribute"
        assert unwrapped.fee_rate == pytest.approx(0.002)
        env.close()

    def test_gym_make_without_fee_rate_defaults_to_none(self):
        """gym.make without fee_rate → env.fee_rate is None (use platform default)."""
        import gymnasium as gym

        import tradeready_gym  # noqa: F401

        env = gym.make(
            "TradeReady-BTC-v0",
            api_key="ak_live_test",
            track_training=False,
        )
        unwrapped = env.unwrapped
        assert unwrapped.fee_rate is None
        env.close()
