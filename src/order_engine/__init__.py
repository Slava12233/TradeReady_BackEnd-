"""Order Execution Engine — Component 4.

Handles order placement, slippage simulation, limit order matching,
and order validation for the AI Agent Crypto Trading Platform.

Public surface
--------------
- :class:`~src.order_engine.engine.OrderEngine`       — central order coordinator
- :class:`~src.order_engine.engine.OrderResult`       — result of any order operation
- :class:`~src.order_engine.validators.OrderRequest`  — lightweight order descriptor
- :class:`~src.order_engine.validators.OrderValidator`— pre-flight validation
- :class:`~src.order_engine.slippage.SlippageCalculator` — price-impact model
- :class:`~src.order_engine.matching.LimitOrderMatcher`  — background sweep runner
"""

from src.order_engine.engine import OrderEngine, OrderResult
from src.order_engine.matching import LimitOrderMatcher
from src.order_engine.slippage import SlippageCalculator
from src.order_engine.validators import OrderRequest, OrderValidator

__all__ = [
    "OrderEngine",
    "OrderResult",
    "OrderRequest",
    "OrderValidator",
    "SlippageCalculator",
    "LimitOrderMatcher",
]
