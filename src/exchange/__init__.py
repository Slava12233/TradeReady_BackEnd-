"""Exchange abstraction layer — CCXT-powered multi-exchange connectivity.

Re-exports public symbols so downstream code can do::

    from src.exchange import ExchangeAdapter, CCXTAdapter, SymbolMapper
    from src.exchange import is_valid_symbol_cached
"""

from src.exchange.adapter import ExchangeAdapter
from src.exchange.ccxt_adapter import CCXTAdapter
from src.exchange.symbol_mapper import SymbolMapper
from src.exchange.symbol_validation import is_valid_symbol_cached
from src.exchange.types import ExchangeCandle, ExchangeMarket, ExchangeTick

__all__ = [
    "CCXTAdapter",
    "ExchangeAdapter",
    "ExchangeCandle",
    "ExchangeMarket",
    "ExchangeTick",
    "SymbolMapper",
    "is_valid_symbol_cached",
]
