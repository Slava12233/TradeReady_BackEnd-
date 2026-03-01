"""Database repository layer for the AI Agent Crypto Trading Platform.

Each repository class wraps a specific ORM model and provides typed async
CRUD methods.  All DB access goes through these classes — never call
``session.execute`` directly from service or route code.
"""

from src.database.repositories.account_repo import AccountRepository
from src.database.repositories.balance_repo import BalanceRepository
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.snapshot_repo import SnapshotRepository
from src.database.repositories.tick_repo import TickRepository
from src.database.repositories.trade_repo import TradeRepository

__all__ = [
    "AccountRepository",
    "BalanceRepository",
    "OrderRepository",
    "SnapshotRepository",
    "TickRepository",
    "TradeRepository",
]
