"""agent.trading — main trading loop, signal generator, executor, monitor, and strategy manager.

Exports:
    TradingLoop: Autonomous observe → analyse → decide → check → execute → record loop.
    SignalGenerator: Combines all 5 strategies into actionable TradingSignal objects.
    TradingSignal: Per-symbol signal produced by the signal generator.
    StrategyManager: Rolling performance monitoring, degradation detection, and adjustments.
    LoopStoppedError: Raised when :meth:`TradingLoop.tick` is called after the loop stops.
    TradeExecutor: Executes TradeDecision objects via the SDK with retry, idempotency,
        persistence, and budget counter updates.
    PositionMonitor: Evaluates open positions against stop-loss/take-profit/age thresholds
        and executes exit orders via TradeExecutor.
    TradingJournal: Records every decision with full context and generates LLM-powered
        reflections, daily summaries, and weekly reviews.
    ABTestRunner: A/B testing framework for running two strategy variants in parallel.
    ABTest: State object for a single A/B test between two strategy parameter variants.
    ABTestError: Base exception for A/B testing errors.
    ABTestNotFoundError: Raised when a test ID does not exist.
    ABTestInactiveError: Raised when an operation requires an active test.
    DuplicateABTestError: Raised when creating a second active test for the same strategy.
    InsufficientDataError: Raised when evaluate() is called before min_trades are reached.
    PairSelector: Dynamically selects top tradeable pairs by volume and momentum.
    SelectedPairs: Result container for a PairSelector refresh cycle.
    PairInfo: Single-pair market snapshot (volume, change_pct, spread, close).
"""

from agent.trading.ab_testing import (
    ABTest,
    ABTestError,
    ABTestInactiveError,
    ABTestNotFoundError,
    ABTestRunner,
    DuplicateABTestError,
    InsufficientDataError,
)
from agent.trading.execution import TradeExecutor
from agent.trading.journal import TradingJournal
from agent.trading.loop import LoopStoppedError, TradingLoop
from agent.trading.monitor import PositionMonitor
from agent.trading.pair_selector import PairInfo, PairSelector, SelectedPairs
from agent.trading.signal_generator import SignalGenerator, TradingSignal
from agent.trading.strategy_manager import StrategyManager

__all__ = [
    "TradingLoop",
    "SignalGenerator",
    "TradingSignal",
    "StrategyManager",
    "LoopStoppedError",
    "TradeExecutor",
    "PositionMonitor",
    "TradingJournal",
    "ABTestRunner",
    "ABTest",
    "ABTestError",
    "ABTestNotFoundError",
    "ABTestInactiveError",
    "DuplicateABTestError",
    "InsufficientDataError",
    "PairSelector",
    "SelectedPairs",
    "PairInfo",
]
