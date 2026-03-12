"""Backtesting engine for historical strategy simulation.

Public API:
    BacktestEngine   — orchestrator: create, step, complete backtests
    TimeSimulator    — virtual clock that advances through a time range
    DataReplayer     — replays historical prices from TimescaleDB
    BacktestSandbox  — in-memory order execution sandbox
"""

from src.backtesting.data_replayer import DataReplayer
from src.backtesting.engine import BacktestEngine
from src.backtesting.sandbox import BacktestSandbox
from src.backtesting.time_simulator import TimeSimulator

__all__ = [
    "BacktestEngine",
    "TimeSimulator",
    "DataReplayer",
    "BacktestSandbox",
]
