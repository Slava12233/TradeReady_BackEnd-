"""Database repository layer for the AI Agent Crypto Trading Platform.

Each repository class wraps a specific ORM model and provides typed async
CRUD methods.  All DB access goes through these classes — never call
``session.execute`` directly from service or route code.
"""

from src.database.repositories.account_repo import AccountRepository
from src.database.repositories.agent_budget_repo import AgentBudgetNotFoundError, AgentBudgetRepository
from src.database.repositories.agent_decision_repo import AgentDecisionNotFoundError, AgentDecisionRepository
from src.database.repositories.agent_feedback_repo import AgentFeedbackNotFoundError, AgentFeedbackRepository
from src.database.repositories.agent_journal_repo import AgentJournalNotFoundError, AgentJournalRepository
from src.database.repositories.agent_learning_repo import AgentLearningNotFoundError, AgentLearningRepository
from src.database.repositories.agent_message_repo import AgentMessageNotFoundError, AgentMessageRepository
from src.database.repositories.agent_observation_repo import AgentObservationRepository
from src.database.repositories.agent_performance_repo import AgentPerformanceNotFoundError, AgentPerformanceRepository
from src.database.repositories.agent_permission_repo import AgentPermissionNotFoundError, AgentPermissionRepository
from src.database.repositories.agent_session_repo import AgentSessionNotFoundError, AgentSessionRepository
from src.database.repositories.balance_repo import BalanceRepository
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.snapshot_repo import SnapshotRepository
from src.database.repositories.tick_repo import TickRepository
from src.database.repositories.trade_repo import TradeRepository

__all__ = [
    # Original repositories
    "AccountRepository",
    "BalanceRepository",
    "OrderRepository",
    "SnapshotRepository",
    "TickRepository",
    "TradeRepository",
    # Agent ecosystem repositories
    "AgentSessionRepository",
    "AgentSessionNotFoundError",
    "AgentMessageRepository",
    "AgentMessageNotFoundError",
    "AgentDecisionRepository",
    "AgentDecisionNotFoundError",
    "AgentJournalRepository",
    "AgentJournalNotFoundError",
    "AgentLearningRepository",
    "AgentLearningNotFoundError",
    "AgentFeedbackRepository",
    "AgentFeedbackNotFoundError",
    "AgentPermissionRepository",
    "AgentPermissionNotFoundError",
    "AgentBudgetRepository",
    "AgentBudgetNotFoundError",
    "AgentPerformanceRepository",
    "AgentPerformanceNotFoundError",
    "AgentObservationRepository",
]
