"""Slippage Calculation Model — Component 4.

Simulates realistic price impact based on order size relative to the 24-hour
trading volume for the pair.  Also applies the platform's simulated trading fee.

Formula::

    execution_price = reference_price * (1 + direction * slippage_factor
                                             * order_size_usd / avg_daily_volume_usd)

Where:

- ``direction``: ``+1`` for buy (price goes up), ``-1`` for sell (price goes down)
- ``slippage_factor``: base coefficient per pair (default ``0.1``, from config)
- ``order_size_usd``: ``quantity * reference_price``
- ``avg_daily_volume_usd``: ``ticker.volume * reference_price`` (24-h base volume
  from Redis ticker, converted to quote-asset terms)

Slippage magnitude examples (for ``slippage_factor = 0.1``):

- Small orders  (< 0.01 % of daily volume): negligible  (~0.01 %)
- Medium orders (0.01 – 0.1 % of daily volume): moderate (~0.05 – 0.10 %)
- Large orders  (> 0.1 % of daily volume): significant  (~0.10 – 0.50 %)

Trading fee: ``0.1 %`` of ``order_size_usd`` (simulates Binance standard taker fee).
Fee is charged in the quote asset (USDT for *USDT pairs).

When the ticker for a symbol is unavailable in Redis the calculator falls back to
a fixed minimum slippage so that orders can still proceed.

Example::

    calculator = SlippageCalculator(price_cache, default_factor=Decimal("0.1"))
    result = await calculator.calculate(
        symbol="BTCUSDT",
        side="buy",
        quantity=Decimal("0.5"),
        reference_price=Decimal("64000"),
    )
    print(result.execution_price)   # e.g. Decimal("64003.20")
    print(result.slippage_pct)      # e.g. Decimal("0.005000")
    print(result.fee)               # e.g. Decimal("32.00")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from src.cache.price_cache import PriceCache
from src.utils.exceptions import PriceNotAvailableError

logger = logging.getLogger(__name__)

# Minimum slippage used when no ticker volume is available.  Expressed as a
# fraction (0.0001 = 0.01 %).
_MIN_SLIPPAGE_FRACTION: Decimal = Decimal("0.0001")

# Fee expressed as a fraction (0.001 = 0.1 %).
_FEE_FRACTION: Decimal = Decimal("0.001")

# Quantisation precision for monetary output fields.
_PRICE_QUANT: Decimal = Decimal("0.00000001")   # 8 d.p.
_PCT_QUANT: Decimal = Decimal("0.000001")        # 6 d.p.
_FEE_QUANT: Decimal = Decimal("0.00000001")      # 8 d.p.


@dataclass(frozen=True, slots=True)
class SlippageResult:
    """Outcome of a single slippage calculation.

    All monetary values use ``Decimal`` for exact arithmetic.

    Attributes:
        execution_price: Adjusted price after slippage is applied.
        slippage_amount: Absolute difference between *execution_price* and
            *reference_price* (always positive).
        slippage_pct: Slippage expressed as a percentage of *reference_price*
            (always positive; direction is inferred from *side*).
        fee: Trading fee charged in the quote asset (USDT for *USDT pairs).
    """

    execution_price: Decimal
    slippage_amount: Decimal
    slippage_pct: Decimal
    fee: Decimal


class SlippageCalculator:
    """Size-proportional slippage model using Redis ticker volume.

    The calculator reads 24-hour volume data from :class:`~src.cache.price_cache.PriceCache`
    to scale slippage with order size.  When ticker data is unavailable it
    falls back to ``_MIN_SLIPPAGE_FRACTION`` so execution can still proceed.

    Args:
        price_cache: Live :class:`~src.cache.price_cache.PriceCache` instance.
        default_factor: Base slippage coefficient.  Defaults to ``Decimal("0.1")``,
            matching ``settings.default_slippage_factor``.

    Example::

        calculator = SlippageCalculator(price_cache, default_factor=Decimal("0.1"))
        result = await calculator.calculate(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.5"),
            reference_price=Decimal("64000"),
        )
    """

    def __init__(
        self,
        price_cache: PriceCache,
        default_factor: Decimal = Decimal("0.1"),
    ) -> None:
        self._price_cache = price_cache
        self._default_factor = default_factor

    async def calculate(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        reference_price: Decimal,
    ) -> SlippageResult:
        """Compute execution price, slippage, and fee for an order.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.
            side: ``"buy"`` or ``"sell"`` (case-insensitive).
            quantity: Amount of the *base* asset being traded.
            reference_price: Current mid-market price from Redis (``Decimal``).

        Returns:
            A :class:`SlippageResult` with adjusted price, slippage, and fee.

        Raises:
            PriceNotAvailableError: If *reference_price* is zero or negative,
                which would make the formula undefined.
            ValueError: If *side* is not ``"buy"`` or ``"sell"``.

        Example::

            result = await calculator.calculate("BTCUSDT", "buy", Decimal("1"), Decimal("60000"))
        """
        side_lower = side.lower()
        if side_lower not in {"buy", "sell"}:
            raise ValueError(f"Invalid order side: {side!r}. Must be 'buy' or 'sell'.")

        if reference_price <= Decimal("0"):
            raise PriceNotAvailableError(
                message=f"Reference price for {symbol} must be positive; got {reference_price}",
                symbol=symbol,
            )

        direction = Decimal("1") if side_lower == "buy" else Decimal("-1")
        order_size_usd: Decimal = quantity * reference_price

        slippage_fraction = await self._compute_slippage_fraction(
            symbol=symbol,
            order_size_usd=order_size_usd,
            reference_price=reference_price,
        )

        execution_price: Decimal = reference_price * (
            Decimal("1") + direction * slippage_fraction
        )
        execution_price = execution_price.quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)

        slippage_amount = abs(execution_price - reference_price).quantize(
            _PRICE_QUANT, rounding=ROUND_HALF_UP
        )
        slippage_pct = (slippage_fraction * Decimal("100")).quantize(
            _PCT_QUANT, rounding=ROUND_HALF_UP
        )
        fee = (order_size_usd * _FEE_FRACTION).quantize(_FEE_QUANT, rounding=ROUND_HALF_UP)

        logger.debug(
            "Slippage calculated",
            extra={
                "symbol": symbol,
                "side": side_lower,
                "quantity": str(quantity),
                "reference_price": str(reference_price),
                "execution_price": str(execution_price),
                "slippage_pct": str(slippage_pct),
                "fee": str(fee),
            },
        )

        return SlippageResult(
            execution_price=execution_price,
            slippage_amount=slippage_amount,
            slippage_pct=slippage_pct,
            fee=fee,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _compute_slippage_fraction(
        self,
        symbol: str,
        order_size_usd: Decimal,
        reference_price: Decimal,
    ) -> Decimal:
        """Return the raw slippage fraction (unsigned) for the order.

        Attempts to read 24-h volume from the Redis ticker.  Falls back to
        ``_MIN_SLIPPAGE_FRACTION`` when no ticker data is present so execution
        is never blocked by missing volume data.

        Args:
            symbol: Uppercase trading pair.
            order_size_usd: Order value in the quote asset (USDT).
            reference_price: Current mid-market price; used to convert base-asset
                volume to USD-denominated volume.

        Returns:
            Unsigned slippage fraction (e.g. ``Decimal("0.0005")`` for 0.05 %).
        """
        ticker = await self._price_cache.get_ticker(symbol)

        if ticker is None or ticker.volume <= Decimal("0"):
            logger.warning(
                "No ticker volume available for %s; using minimum slippage.", symbol
            )
            return _MIN_SLIPPAGE_FRACTION

        # Convert the 24-h base-asset volume to USD-denominated volume.
        avg_daily_volume_usd = ticker.volume * reference_price

        if avg_daily_volume_usd <= Decimal("0"):
            logger.warning(
                "Computed zero daily volume for %s; using minimum slippage.", symbol
            )
            return _MIN_SLIPPAGE_FRACTION

        # Core formula: slippage_fraction = factor * order_size / daily_volume
        slippage_fraction = self._default_factor * order_size_usd / avg_daily_volume_usd

        # Clamp to minimum so even tiny orders pay at least _MIN_SLIPPAGE_FRACTION.
        return max(slippage_fraction, _MIN_SLIPPAGE_FRACTION)
