"""Bidirectional symbol translation between platform and CCXT formats.

Platform format: ``"BTCUSDT"`` (uppercase, concatenated, no separator).
CCXT format:     ``"BTC/USDT"`` (uppercase, slash-separated base/quote).

The mapper can operate in two modes:

1. **With market data** (preferred): Uses the exchange's market definitions to
   split symbols accurately.  Call :meth:`load_markets` after constructing
   the adapter to populate the lookup tables.

2. **Heuristic fallback**: When market data is unavailable, strips known quote
   assets (``USDT``, ``BUSD``, ``BTC``, ``ETH``, ``BNB``) from the right side
   of the symbol.  This handles 99%+ of cases but may fail for exotic pairs.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

# Quote assets to try stripping (longest first to avoid greedy partial matches).
_KNOWN_QUOTES: tuple[str, ...] = ("USDT", "BUSD", "USDC", "TUSD", "BTC", "ETH", "BNB")


class SymbolMapper:
    """Converts between platform symbols (``BTCUSDT``) and CCXT symbols (``BTC/USDT``)."""

    def __init__(self) -> None:
        # Populated by load_markets() for accurate mapping.
        self._platform_to_ccxt: dict[str, str] = {}
        self._ccxt_to_platform: dict[str, str] = {}

    def load_markets(self, markets: dict) -> None:  # type: ignore[type-arg]
        """Build lookup tables from CCXT's ``exchange.markets`` dict.

        Args:
            markets: The ``exchange.markets`` dict returned by
                ``await exchange.load_markets()``.  Keys are CCXT symbols
                (``"BTC/USDT"``), values are market info dicts with ``base``
                and ``quote`` fields.
        """
        self._platform_to_ccxt.clear()
        self._ccxt_to_platform.clear()

        for ccxt_symbol, market_info in markets.items():
            base = market_info.get("base", "")
            quote = market_info.get("quote", "")
            platform_symbol = f"{base}{quote}".upper()

            self._platform_to_ccxt[platform_symbol] = ccxt_symbol
            self._ccxt_to_platform[ccxt_symbol] = platform_symbol

        log.info(
            "Symbol mapper loaded",
            pair_count=len(self._platform_to_ccxt),
        )

    def to_ccxt(self, platform_symbol: str) -> str:
        """Convert platform symbol to CCXT format.

        Args:
            platform_symbol: e.g. ``"BTCUSDT"``.

        Returns:
            CCXT symbol, e.g. ``"BTC/USDT"``.
        """
        cached = self._platform_to_ccxt.get(platform_symbol)
        if cached is not None:
            return cached
        return self._heuristic_to_ccxt(platform_symbol)

    def from_ccxt(self, ccxt_symbol: str) -> str:
        """Convert CCXT symbol to platform format.

        Args:
            ccxt_symbol: e.g. ``"BTC/USDT"``.

        Returns:
            Platform symbol, e.g. ``"BTCUSDT"``.
        """
        cached = self._ccxt_to_platform.get(ccxt_symbol)
        if cached is not None:
            return cached
        # Simple fallback: remove the slash.
        return ccxt_symbol.replace("/", "").replace("-", "").upper()

    @staticmethod
    def _heuristic_to_ccxt(platform_symbol: str) -> str:
        """Best-effort conversion when market data is unavailable."""
        upper = platform_symbol.upper()
        for quote in _KNOWN_QUOTES:
            if upper.endswith(quote) and len(upper) > len(quote):
                base = upper[: -len(quote)]
                return f"{base}/{quote}"
        # Last resort: assume last 4 chars are the quote.
        if len(upper) > 4:
            return f"{upper[:-4]}/{upper[-4:]}"
        return upper
