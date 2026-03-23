"""PPO training pipeline for the TradeReady portfolio trading agent.

Usage:
    python -m agent.strategies.rl.train                          # full run
    python -m agent.strategies.rl.train --timesteps 1000 --no-track  # smoke
    python -m agent.strategies.rl.train --help
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np
import structlog

log = structlog.get_logger(__name__)


def _build_reward(config: Any) -> Any:
    """Instantiate the reward function specified by config.reward_type."""
    from tradeready_gym.rewards.composite import CompositeReward
    from tradeready_gym.rewards.drawdown_penalty_reward import DrawdownPenaltyReward
    from tradeready_gym.rewards.pnl_reward import PnLReward
    from tradeready_gym.rewards.sharpe_reward import SharpeReward
    from tradeready_gym.rewards.sortino_reward import SortinoReward

    match config.reward_type:
        case "pnl":
            return PnLReward()
        case "sharpe":
            return SharpeReward(window=config.sharpe_window)
        case "sortino":
            return SortinoReward(window=config.sharpe_window)
        case "drawdown":
            return DrawdownPenaltyReward(penalty_coeff=config.drawdown_penalty_coeff)
        case "composite":
            return CompositeReward(
                sortino_weight=config.composite_sortino_weight,
                pnl_weight=config.composite_pnl_weight,
                activity_weight=config.composite_activity_weight,
                drawdown_weight=config.composite_drawdown_weight,
                sortino_window=config.sharpe_window,
                activity_bonus=config.composite_activity_bonus,
                starting_balance=config.starting_balance,
            )
        case _:
            raise ValueError(f"Unknown reward_type: {config.reward_type!r}")


def _env_factory(config: Any, start: str, end: str) -> Any:
    """Return a no-arg callable producing one wrapped environment.

    Wrapper stack: FeatureEngineeringWrapper(periods=[5,10,20]) -> NormalizationWrapper.
    """
    def _make() -> Any:
        import gymnasium as gym
        import tradeready_gym  # noqa: F401  registers all envs as side-effect
        from tradeready_gym.wrappers.feature_engineering import FeatureEngineeringWrapper
        from tradeready_gym.wrappers.normalization import NormalizationWrapper

        env = gym.make(
            "TradeReady-Portfolio-v0",
            api_key=config.platform_api_key,
            base_url=config.platform_base_url,
            symbols=config.env_symbols,
            timeframe=config.timeframe,
            lookback_window=config.lookback_window,
            starting_balance=config.starting_balance,
            start_time=start,
            end_time=end,
            reward_function=_build_reward(config),
            track_training=config.track_training,
            strategy_label="rl_ppo_portfolio",
        )
        env = FeatureEngineeringWrapper(env, periods=[5, 10, 20])
        return NormalizationWrapper(env)

    return _make


def _make_vec_env(config: Any, start: str, end: str) -> Any:
    """SubprocVecEnv when n_envs > 1; DummyVecEnv as fallback."""
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

    factories = [_env_factory(config, start, end) for _ in range(config.n_envs)]
    if config.n_envs == 1:
        return DummyVecEnv(factories)
    try:
        return SubprocVecEnv(factories)
    except Exception as exc:
        log.warning("agent.strategy.rl.train.vec_env_subproc_failed", error=str(exc), fallback="DummyVecEnv")
        return DummyVecEnv(factories)


def train(config: Any) -> Path:
    """Run PPO training; return the path to the saved final model (.zip).

    Steps: seed RNG -> create envs -> init PPO (2x256 MlpPolicy) ->
    attach CheckpointCallback + EvalCallback -> model.learn() -> save.

    Args:
        config: RLConfig instance with all hyperparameters.

    Returns:
        Path to the saved ``.zip`` model file.
    """
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import CallbackList, CheckpointCallback, EvalCallback

    random.seed(config.seed)
    np.random.seed(config.seed)
    try:
        import torch; torch.manual_seed(config.seed)  # noqa: E702
    except ImportError:
        pass

    log.info("agent.strategy.rl.train.start", timesteps=config.total_timesteps, n_envs=config.n_envs,
             seed=config.seed, reward=config.reward_type)

    config.models_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    train_env = _make_vec_env(config, config.train_start, config.train_end)
    eval_env = _env_factory(config, config.val_start, config.val_end)()

    model = PPO(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=config.learning_rate,
        n_steps=config.n_steps,
        batch_size=config.batch_size,
        n_epochs=config.n_epochs,
        gamma=config.gamma,
        gae_lambda=config.gae_lambda,
        clip_range=config.clip_range,
        ent_coef=config.ent_coef,
        vf_coef=config.vf_coef,
        max_grad_norm=config.max_grad_norm,
        policy_kwargs={"net_arch": {"pi": config.net_arch_pi, "vf": config.net_arch_vf}},
        tensorboard_log=str(config.log_dir),
        seed=config.seed,
        verbose=0,
    )
    log.info("agent.strategy.rl.train.model_initialised", pi=config.net_arch_pi, vf=config.net_arch_vf,
             lr=config.learning_rate)

    checkpoint_cb = CheckpointCallback(
        save_freq=max(config.save_freq // config.n_envs, 1),
        save_path=str(config.models_dir / "checkpoint"),
        name_prefix="ppo_portfolio",
        verbose=0,
    )
    eval_cb = EvalCallback(
        eval_env=eval_env,
        best_model_save_path=str(config.models_dir / "best_model"),
        log_path=str(config.log_dir / "eval"),
        eval_freq=max(config.eval_freq // config.n_envs, 1),
        n_eval_episodes=config.n_eval_episodes,
        deterministic=True,
        render=False,
        verbose=0,
    )

    try:
        model.learn(
            total_timesteps=config.total_timesteps,
            callback=CallbackList([checkpoint_cb, eval_cb]),
            progress_bar=False,
        )
    finally:
        train_env.close()
        eval_env.close()
        log.info("agent.strategy.rl.train.env_closed")

    final = config.models_dir / "ppo_portfolio_final"
    model.save(str(final))
    saved = Path(str(final) + ".zip")
    log.info("agent.strategy.rl.train.model_saved", path=str(saved))
    return saved


def main() -> None:
    """CLI entry point."""
    from agent.logging import configure_agent_logging  # noqa: PLC0415

    configure_agent_logging()

    p = argparse.ArgumentParser(
        prog="python -m agent.strategies.rl.train",
        description="Train a PPO agent on the TradeReady portfolio trading environment.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--timesteps", type=int, default=None, metavar="N",
                   help="Total training timesteps (default: 500 000).")
    p.add_argument("--seed", type=int, default=None, metavar="S",
                   help="Random seed (default: 42).")
    p.add_argument("--n-envs", type=int, default=None, metavar="N",
                   help="Parallel training environments (default: 4).")
    p.add_argument("--reward", choices=["pnl", "sharpe", "sortino", "drawdown", "composite"], default=None,
                   help="Reward function (default: sharpe).")
    p.add_argument("--base-url", type=str, default=None, metavar="URL",
                   help="Platform REST API base URL.")
    p.add_argument("--log-dir", type=Path, default=None, metavar="DIR",
                   help="TensorBoard log directory.")
    p.add_argument("--no-track", action="store_true",
                   help="Disable platform training-run tracking.")
    args = p.parse_args()

    from agent.strategies.rl.config import RLConfig
    config = RLConfig()
    overrides: dict[str, Any] = {
        k: v for k, v in {
            "total_timesteps": args.timesteps,
            "seed": args.seed,
            "n_envs": args.n_envs,
            "reward_type": args.reward,
            "platform_base_url": args.base_url,
            "log_dir": args.log_dir,
            **({"track_training": False} if args.no_track else {}),
        }.items() if v is not None
    }
    if overrides:
        config = config.model_copy(update=overrides)

    if not config.platform_api_key:
        log.error("agent.strategy.rl.train.config_missing_api_key",
                  hint="Set RL_PLATFORM_API_KEY in agent/.env or as environment variable")
        sys.exit(1)

    try:
        saved = train(config)
        log.info("agent.strategy.rl.train.complete", model=str(saved))
    except KeyboardInterrupt:
        log.info("agent.strategy.rl.train.interrupted")
    except Exception as exc:
        log.exception("agent.strategy.rl.train.failed", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
