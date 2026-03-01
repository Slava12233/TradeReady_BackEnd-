"""Risk Management Engine — Component 7.

Enforces trading limits and circuit-breaker logic to prevent agents
from unrealistic or destructive trading behaviour.

Modules
-------
- :mod:`src.risk.manager`         — RiskManager: 8-step validate_order chain
- :mod:`src.risk.circuit_breaker` — CircuitBreaker: daily PnL tracking + halt
"""

from src.risk.circuit_breaker import CircuitBreaker
from src.risk.manager import RiskCheckResult, RiskLimits, RiskManager

__all__ = [
    "CircuitBreaker",
    "RiskCheckResult",
    "RiskLimits",
    "RiskManager",
]
