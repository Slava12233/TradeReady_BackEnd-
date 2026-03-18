"""Celery tasks for strategy test episode execution and result aggregation.

Tasks:
- ``run_strategy_episode`` — runs a single backtest episode for a strategy test
- ``aggregate_test_results`` — aggregates results from all episodes

Both tasks bridge to async via ``asyncio.run()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    name="src.tasks.strategy_tasks.run_strategy_episode",
    soft_time_limit=300,
    time_limit=360,
    max_retries=0,
)
def run_strategy_episode(
    test_run_id: str,
    episode_number: int,
    strategy_definition: dict[str, Any],
    backtest_config: dict[str, Any],
) -> dict[str, Any]:
    """Run a single strategy test episode as a backtest.

    Args:
        test_run_id: UUID of the test run.
        episode_number: Episode number within the test run.
        strategy_definition: Strategy definition dict.
        backtest_config: Backtest configuration dict.

    Returns:
        Episode metrics dict.
    """
    return asyncio.run(
        _run_episode_async(test_run_id, episode_number, strategy_definition, backtest_config),
    )


async def _run_episode_async(
    test_run_id: str,
    episode_number: int,
    strategy_definition: dict[str, Any],
    backtest_config: dict[str, Any],
) -> dict[str, Any]:
    """Async implementation of a single test episode."""
    from datetime import datetime  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from src.backtesting.engine import BacktestConfig, BacktestEngine  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415
    from src.strategies.executor import StrategyExecutor  # noqa: PLC0415
    from src.strategies.indicators import IndicatorEngine  # noqa: PLC0415

    session_factory = get_session_factory()
    engine = BacktestEngine(session_factory)
    indicator_engine = IndicatorEngine()
    executor = StrategyExecutor(strategy_definition, indicator_engine)

    metrics: dict[str, Any] = {
        "episode_number": episode_number,
        "status": "failed",
    }

    try:
        async with session_factory() as db:
            # Create backtest config
            config = BacktestConfig(
                start_time=datetime.fromisoformat(backtest_config["start_time"]),
                end_time=datetime.fromisoformat(backtest_config["end_time"]),
                starting_balance=Decimal(str(backtest_config.get("starting_balance", "10000"))),
                candle_interval=backtest_config.get("candle_interval", 60),
                pairs=strategy_definition.get("pairs"),
                strategy_label=f"test_ep_{episode_number}",
                agent_id=UUID(backtest_config["agent_id"]) if backtest_config.get("agent_id") else None,
            )

            # Create and start backtest session
            session = await engine.create_session(
                account_id=UUID(backtest_config["account_id"]),
                config=config,
                db=db,
            )
            session_id = str(session.id)
            await db.commit()

        async with session_factory() as db:
            await engine.start(session_id, db)
            await db.commit()

        # Step loop
        while engine.is_active(session_id):
            async with session_factory() as db:
                step_result = await engine.step(session_id, db)
                await db.commit()

            if step_result.is_complete:
                break

            # Let executor decide on orders
            step_dict = {
                "prices": {s: str(p) for s, p in step_result.prices.items()},
                "portfolio": {
                    "total_equity": str(step_result.portfolio.total_equity),
                },
                "positions": [
                    {
                        "symbol": p.symbol,
                        "quantity": str(p.quantity),
                        "avg_entry_price": str(p.avg_entry_price),
                    }
                    for p in step_result.portfolio.positions
                ],
                "step": step_result.step,
            }

            orders = executor.decide(step_dict)
            for order in orders:
                try:
                    async with session_factory() as db:
                        await engine.execute_order(
                            session_id,
                            symbol=order["symbol"],
                            side=order["side"],
                            order_type=order["type"],
                            quantity=order["quantity"],
                            price=None,
                        )
                        await db.commit()
                except Exception:  # noqa: BLE001
                    logger.debug("Order failed in episode %d: %s", episode_number, order)

        # Complete if still active
        if engine.is_active(session_id):
            async with session_factory() as db:
                result = await engine.complete(session_id, db)
                await db.commit()
        else:
            result = None

        # Extract metrics
        if result is not None:
            metrics = {
                "episode_number": episode_number,
                "status": "completed",
                "session_id": result.session_id,
                "roi_pct": float(result.roi_pct),
                "total_trades": result.total_trades,
                "total_fees": float(result.total_fees),
                "final_equity": float(result.final_equity),
                "sharpe_ratio": float(result.metrics.sharpe_ratio) if result.metrics else None,
                "max_drawdown_pct": float(result.metrics.max_drawdown_pct) if result.metrics else None,
                "win_rate": float(result.metrics.win_rate) if result.metrics else None,
            }

        # Save episode to DB
        async with session_factory() as db:
            from src.database.repositories.strategy_repo import StrategyRepository  # noqa: PLC0415

            repo = StrategyRepository(db)
            await repo.save_episode(
                test_run_id=UUID(test_run_id),
                episode_number=episode_number,
                backtest_session_id=UUID(result.session_id) if result else None,
                metrics=metrics,
            )
            await repo.increment_completed(UUID(test_run_id))
            await db.commit()

    except Exception:
        logger.exception("Episode %d failed for test run %s", episode_number, test_run_id)
        metrics["status"] = "failed"

    return metrics


@app.task(
    name="src.tasks.strategy_tasks.aggregate_test_results",
    soft_time_limit=60,
    time_limit=90,
    max_retries=0,
)
def aggregate_test_results(
    test_run_id: str,
    strategy_definition: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate results from all episodes and save to the test run.

    Args:
        test_run_id: UUID of the test run.
        strategy_definition: Strategy definition for recommendation generation.

    Returns:
        Aggregated results dict.
    """
    return asyncio.run(_aggregate_async(test_run_id, strategy_definition))


async def _aggregate_async(
    test_run_id: str,
    strategy_definition: dict[str, Any],
) -> dict[str, Any]:
    """Async implementation of result aggregation."""
    from uuid import UUID  # noqa: PLC0415

    from src.database.session import get_session_factory  # noqa: PLC0415
    from src.strategies.recommendation_engine import generate_recommendations  # noqa: PLC0415
    from src.strategies.test_aggregator import TestAggregator  # noqa: PLC0415

    session_factory = get_session_factory()

    try:
        async with session_factory() as db:
            from src.database.repositories.strategy_repo import StrategyRepository  # noqa: PLC0415

            repo = StrategyRepository(db)

            # Get all episodes for this test run
            test_run = await repo.get_test_run(UUID(test_run_id))
            if test_run is None:
                return {"error": "Test run not found"}

            # Collect episode metrics from the test_run's episodes
            from sqlalchemy import select  # noqa: PLC0415

            from src.database.models import StrategyTestEpisode  # noqa: PLC0415

            stmt = (
                select(StrategyTestEpisode)
                .where(StrategyTestEpisode.test_run_id == UUID(test_run_id))
                .order_by(StrategyTestEpisode.episode_number)
            )
            result = await db.execute(stmt)
            episodes_rows = result.scalars().all()

            episode_metrics = [ep.metrics for ep in episodes_rows if ep.metrics]

            # Aggregate
            aggregated = TestAggregator.aggregate(episode_metrics)
            by_pair = aggregated.get("by_pair", {})

            # Generate recommendations
            recommendations = generate_recommendations(aggregated, by_pair, strategy_definition)

            # Save results
            await repo.save_results(UUID(test_run_id), aggregated, recommendations)

            # Update strategy status to validated
            if test_run.strategy_id:
                await repo.update(test_run.strategy_id, status="validated")

            await db.commit()

            return aggregated

    except Exception:
        logger.exception("Failed to aggregate results for test run %s", test_run_id)
        return {"error": "Aggregation failed"}
