# agent/strategies/evolutionary/ — Genetic Algorithm Strategy Optimisation

<!-- last-updated: 2026-03-20 -->

> Evolves trading strategy parameters using a genetic algorithm whose fitness function is evaluated through the platform's historical battle system.

## What This Module Does

The `evolutionary/` sub-package implements a genetic algorithm (GA) that optimises `StrategyGenome` parameter vectors — fixed-length numpy float64 arrays encoding RSI, MACD, stop-loss, take-profit, and position-size parameters. Each generation evaluates fitness by provisioning agents on the platform, assigning evolved strategies via `POST /api/v1/strategies`, running a historical battle, and extracting per-agent performance metrics. The fitness formula `sharpe - 0.5 * max_drawdown` selects for profitable strategies that do not blow up.

155 unit tests cover all components.

## Key Files

| File | Purpose |
|------|---------|
| `genome.py` | `StrategyGenome` — 12-parameter strategy encoded as a numpy float64 vector; `to_strategy_definition()` produces the platform API dict. |
| `operators.py` | `tournament_select`, `crossover`, `mutate`, `clip_genome` — standard GA operators. |
| `population.py` | `Population`, `PopulationStats` — manages one generation; `initialize()`, `evolve(scores)`, `stats(scores)`. |
| `battle_runner.py` | `BattleRunner` — provisions agents, assigns strategies, runs historical battles, extracts per-agent fitness. |
| `evolve.py` | CLI script — full evolution loop with convergence detection; writes `evolution_log.json`. |
| `analyze.py` | CLI script — post-run analysis from `evolution_log.json`: fitness curve, parameter convergence charts. |
| `config.py` | `EvolutionConfig` — Pydantic-settings for GA parameters. Env prefix `EVO_`. |
| `results/` | Output directory for `evolution_log.json` and analysis artifacts. |

## Public API

```python
from agent.strategies.evolutionary.genome import StrategyGenome
from agent.strategies.evolutionary.operators import tournament_select, crossover, mutate, clip_genome
from agent.strategies.evolutionary.population import Population, PopulationStats
from agent.strategies.evolutionary.battle_runner import BattleRunner
from agent.strategies.evolutionary.config import EvolutionConfig
```

### `StrategyGenome` (`genome.py`)

Encodes a strategy as a fixed-length float64 numpy vector. The 12 parameters:

| Parameter | Range | Description |
|-----------|-------|-------------|
| `rsi_oversold` | [20, 40] | RSI level triggering a buy signal |
| `rsi_overbought` | [60, 80] | RSI level triggering a sell signal |
| `adx_threshold` | [15, 35] | Minimum ADX required for trend entries |
| `stop_loss_pct` | [0.01, 0.05] | Stop-loss distance (1–5%) |
| `take_profit_pct` | [0.02, 0.10] | Take-profit target (2–10%) |
| `trailing_stop_pct` | [0.005, 0.03] | Trailing stop distance |
| `position_size_pct` | [0.03, 0.20] | Fraction of portfolio per trade |
| `macd_fast` | [8, 15] (int) | MACD fast EMA period |
| `macd_slow` | [20, 30] (int) | MACD slow EMA period |
| `max_hold_candles` | [10, 200] (int) | Max candles to hold a position |
| `max_positions` | [1, 5] (int) | Maximum concurrent positions |
| `pair_bitmask` | [0, 63] (int) | 6-bit mask selecting active USDT pairs |

`to_strategy_definition()` converts the vector to a JSONB-compatible dict for `POST /api/v1/strategies`.

### `Population` (`population.py`)

| Method | Description |
|--------|-------------|
| `initialize(size)` | Randomly initialise `size` genomes |
| `evolve(scores: list[float])` | Apply tournament selection + crossover + mutation in one call; returns new generation |
| `stats(scores)` | Return `PopulationStats` with mean, max, std fitness |

### `BattleRunner` (`battle_runner.py`)

Orchestrates fitness evaluation for one generation.

| Method | Description |
|--------|-------------|
| `setup_agents(n)` | Provision `n` agents on the platform (creates accounts + API keys) |
| `reset_agents()` | Reset balances and positions for a fresh generation |
| `assign_strategies(genomes)` | Create strategies from genome dicts and deploy to agents |
| `run_battle()` | Start a historical battle and wait for it to complete |
| `get_fitness()` | Extract per-agent fitness: `sharpe - 0.5 * max_drawdown` |

Agents with missing results receive `FAILURE_FITNESS = -999.0`.

**Important:** `BattleRunner` authenticates via JWT (not API key) because `POST /api/v1/battles` requires `Authorization: Bearer`. The runner calls `POST /api/v1/auth/login` on construction.

## CLI Commands

```bash
# Full evolution run (30 generations, population size 12)
python -m agent.strategies.evolutionary.evolve \
    --generations 30 \
    --pop-size 12 \
    --base-url http://localhost:8000 \
    --api-key ak_live_...

# Quick smoke test (2 generations, pop size 4)
python -m agent.strategies.evolutionary.evolve \
    --generations 2 --pop-size 4 --seed 42

# Analyse results after a completed run
python -m agent.strategies.evolutionary.analyze \
    --log-path agent/strategies/evolutionary/results/evolution_log.json
```

## Patterns

- **Fitness is always a scalar float** — multi-metric results are reduced so the population/GA logic stays algorithm-agnostic.
- **Genome vector enables standard numpy operators** — no marshalling overhead; crossover and mutation operate directly on the float64 array.
- **Non-crashing BattleRunner** — catches all exceptions per generation; callers always receive a valid fitness array (failures get `FAILURE_FITNESS = -999.0`).

## Gotchas

- **`BattleRunner` requires JWT auth.** The battle endpoint requires `Authorization: Bearer`. The runner handles this by calling `POST /api/v1/auth/login` on construction using credentials from `AgentConfig`.
- **`evolution_log.json` contains strategy parameters.** If the results directory is world-readable, strategy configurations (including position size parameters) are visible. Restrict permissions in production environments.
- **`pair_bitmask` selects active pairs.** A genome with all-zero bitmask (`pair_bitmask=0`) will have no trading pairs — the strategy will be registered but never trade. This is a valid (but useless) individual that receives `FAILURE_FITNESS`.
- **Battle completion polling** — `run_battle()` polls the battle status endpoint until it reaches a terminal state. If the platform is slow or a battle is stuck, this can block indefinitely. Use `--timeout` flag (CLI) or set `EVO_BATTLE_TIMEOUT_SECONDS` in the config.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
