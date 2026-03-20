"""agent/strategies/rl — PPO reinforcement learning training pipeline.

Public API:
    RLConfig             - All hyperparameters for PPO training (Pydantic settings)
    train                - Run the full training loop; returns the saved model path
    TrainingRunner       - Orchestrator: validate -> train -> evaluate -> tune
    SeedMetrics          - Per-seed training and evaluation result model
    MultiSeedComparison  - Aggregated comparison across all trained seeds
    ModelEvaluator       - Evaluate trained models against benchmarks on the test split
    EvaluationReport     - JSON-serialisable evaluation report (PPO + benchmarks)
    StrategyMetrics      - Per-strategy metrics (Sharpe, ROI, drawdown, win rate)
    PPODeployBridge      - Connect a trained model to the platform (backtest or live)
    DeployLog            - Full deployment session log with per-step order records
    StepRecord           - Per-step decision log entry
    OrderRecord          - Individual order record (placed or skipped)
"""

from agent.strategies.rl.config import RLConfig
from agent.strategies.rl.deploy import DeployLog, OrderRecord, PPODeployBridge, StepRecord
from agent.strategies.rl.evaluate import EvaluationReport, ModelEvaluator, StrategyMetrics
from agent.strategies.rl.runner import MultiSeedComparison, SeedMetrics, TrainingRunner

__all__ = [
    "RLConfig",
    "TrainingRunner",
    "SeedMetrics",
    "MultiSeedComparison",
    "ModelEvaluator",
    "EvaluationReport",
    "StrategyMetrics",
    "PPODeployBridge",
    "DeployLog",
    "StepRecord",
    "OrderRecord",
]
