"""Meta-learner weight optimizer via backtests.

Systematically evaluates 12 weight configurations (4 fixed + 8 seeded-random)
for the MetaLearner ensemble by running a backtest for each configuration and
measuring Sharpe ratio, ROI, and max drawdown.

The optimizer drives the platform's backtest API directly using a lightweight
async HTTP client — no LLM is involved.  Signal generation uses a
deterministic MA-crossover rule so results are reproducible given the same
seed and data range.

Algorithm
---------
For each weight configuration:

1. Create and start a backtest session (BTC + ETH, 1-min candles, 7-day window).
2. Run up to ``max_iterations`` iterations of the trading loop:
   a. Fetch recent candles for each symbol.
   b. Generate a ``WeightedSignal`` per source with proportional confidence.
   c. Pass all signals through ``MetaLearner(weights=config_weights).combine()``.
   d. Act on the ``ConsensusSignal`` action (BUY/SELL/HOLD).
   e. Advance ``batch_size`` candles.
3. Collect ``sharpe_ratio``, ``roi_pct``, ``max_drawdown_pct`` from results.
4. Rank all results by Sharpe ratio (descending).
5. Run out-of-sample validation on the optimal weights.
6. Validate that the optimal configuration beats the equal-weight baseline.
7. Save ranked results and optimal weights to JSON.
8. Write a compact ``optimal_weights.json`` compatible with ``EnsembleConfig.weights``.

CLI
---
    python -m agent.strategies.ensemble.optimize_weights \\
        --base-url http://localhost:8000 \\
        [--seed 42] \\
        [--output-dir agent/reports] \\
        [--oos-days 7] \\
        [--max-iterations 20] \\
        [--batch-size 5]

Compact weights file
--------------------
After optimization, a ``optimal_weights.json`` file is written alongside the
full report.  Its format is compatible with ``EnsembleConfig.weights``::

    {
        "rl": 0.450000,
        "evolved": 0.300000,
        "regime": 0.250000
    }

Load it at runtime with :func:`load_optimal_weights` and apply with
:func:`apply_optimal_weights`::

    weights = load_optimal_weights(Path("agent/strategies/ensemble/optimal_weights.json"))
    config = apply_optimal_weights(EnsembleConfig(), weights)
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent.strategies.ensemble.config import EnsembleConfig
from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.signals import (
    ConsensusSignal,
    SignalSource,
    TradeAction,
    WeightedSignal,
)

log = structlog.get_logger(__name__)


# ── Lightweight REST client ────────────────────────────────────────────────────


class _BacktestClient:
    """Minimal async HTTP client for backtest and market-data endpoints.

    This is a standalone alternative to ``PlatformRESTClient`` that does not
    require ``AgentConfig`` or ``pydantic-settings``.  It implements exactly the
    methods needed by ``WeightOptimizer``.

    Args:
        base_url: Platform REST API base URL.
        api_key: Platform API key (``ak_live_...``).
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-API-Key": api_key},
            timeout=30.0,
        )

    async def __aenter__(self) -> _BacktestClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self._client.post(path, json=body)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()  # type: ignore[no-any-return]

    async def create_backtest(
        self,
        start_time: str,
        end_time: str,
        symbols: list[str],
        interval: int = 60,
        starting_balance: str = "10000",
        strategy_label: str = "default",
    ) -> dict[str, Any]:
        """Create a new backtest session."""
        return await self._post(
            "/api/v1/backtest/create",
            {
                "start_time": start_time,
                "end_time": end_time,
                "pairs": symbols if symbols else None,
                "candle_interval": interval,
                "starting_balance": starting_balance,
                "strategy_label": strategy_label,
            },
        )

    async def start_backtest(self, session_id: str) -> dict[str, Any]:
        """Start a created backtest session."""
        return await self._post(f"/api/v1/backtest/{session_id}/start")

    async def step_backtest_batch(self, session_id: str, steps: int) -> dict[str, Any]:
        """Advance the backtest sandbox by N candle steps."""
        return await self._post(
            f"/api/v1/backtest/{session_id}/step/batch",
            {"steps": steps},
        )

    async def backtest_trade(
        self,
        session_id: str,
        symbol: str,
        side: str,
        quantity: str,
        order_type: str = "market",
    ) -> dict[str, Any]:
        """Place a market order inside the backtest sandbox."""
        return await self._post(
            f"/api/v1/backtest/{session_id}/trade/order",
            {"symbol": symbol, "side": side, "type": order_type, "quantity": quantity},
        )

    async def get_backtest_results(self, session_id: str) -> dict[str, Any]:
        """Retrieve full results for a completed backtest session."""
        return await self._get(f"/api/v1/backtest/{session_id}/results")

    async def get_backtest_candles(
        self,
        session_id: str,
        symbol: str,
        interval: int = 60,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get OHLCV candles up to the current virtual clock time."""
        return await self._get(
            f"/api/v1/backtest/{session_id}/market/candles/{symbol}",
            params={"interval": interval, "limit": limit},
        )


# ── Constants ─────────────────────────────────────────────────────────────────

# Default number of seeded-random weight configurations to generate in addition
# to the 4 fixed configurations.  Total = 4 + _N_RANDOM_CONFIGS = 12.
_N_RANDOM_CONFIGS: int = 8

# Moving-average window sizes used in the synthetic signal generator.
# These mirror the backtest workflow's MA-crossover parameters.
_MA_FAST: int = 5
_MA_SLOW: int = 20

# Symbols included in every backtest run.  Limited to two to keep run times
# short; add more to increase signal diversity at the cost of runtime.
_BACKTEST_SYMBOLS: list[str] = ["BTCUSDT", "ETHUSDT"]

# Candle interval in seconds for all backtest sessions.
_CANDLE_INTERVAL: int = 60  # 1-minute candles

# Starting virtual USDT balance for every backtest session.
_STARTING_BALANCE: str = "10000"

# Per-symbol order quantities — small test sizes that stay inside risk limits.
_ORDER_QTY: dict[str, str] = {
    "BTCUSDT": "0.0001",
    "ETHUSDT": "0.001",
}
_DEFAULT_QTY: str = "0.001"

# Fallback date range used when the platform data-range endpoint returns no data.
_FALLBACK_END = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)
_FALLBACK_DAYS: int = 7  # in-sample window length

# ── Pydantic models ───────────────────────────────────────────────────────────


class WeightConfig(BaseModel):
    """A single weight configuration to evaluate.

    Args:
        name: Short human-readable label (e.g. ``"rl_heavy"``).
        description: Longer description explaining the configuration intent.
        weights: Per-source weight mapping.  Keys must be ``SignalSource``
            values.  Raw weights (not normalised) — the MetaLearner normalises
            them to sum to 1.0 internally.

    Note:
        Weights are stored as-supplied and normalised by MetaLearner at
        combine-time.  The ``[rl, evolved, regime]`` convention used in
        docstrings refers to the order ``[SignalSource.RL, SignalSource.EVOLVED,
        SignalSource.REGIME]``.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    weights: dict[SignalSource, float] = Field(
        description=(
            "Raw per-source weights.  MetaLearner normalises these to sum to 1.0."
        )
    )


class ConfigResult(BaseModel):
    """Backtest outcome for one weight configuration.

    Args:
        config_name: Human-readable label from the corresponding ``WeightConfig``.
        weights: Normalised weights used (each value ÷ sum of all values).
        sharpe_ratio: Sharpe ratio from the backtest results.  ``None`` when
            insufficient trades occurred.
        roi_pct: Return on investment as a percentage.  ``None`` when not
            available.
        max_drawdown_pct: Maximum portfolio drawdown as a percentage.  ``None``
            when not available.
        total_trades: Number of trades executed during the backtest.
        session_id: Platform backtest session UUID for traceability.
        error: Non-empty string if the backtest failed at the API level.
    """

    model_config = ConfigDict(frozen=False)

    config_name: str
    weights: dict[str, float]  # str keys for JSON serialisability
    sharpe_ratio: float | None = None
    roi_pct: float | None = None
    max_drawdown_pct: float | None = None
    total_trades: int = 0
    session_id: str | None = None
    error: str | None = None


class OptimizationResult(BaseModel):
    """Complete output of a weight optimisation run.

    Args:
        timestamp: ISO-8601 UTC timestamp at the moment the run completes.
        seed: Random seed used to generate the random weight configurations.
        data_period: Human-readable description of the in-sample backtest date range.
        oos_period: Human-readable description of the out-of-sample date range.
        results: Per-configuration results sorted by Sharpe ratio (best first).
        optimal_config_name: Name of the configuration with the highest Sharpe ratio.
        optimal_weights: Normalised weights from the best configuration.
        oos_result: Out-of-sample validation result for the optimal weights.
        comparison_table: Markdown-formatted table of all configurations for display.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: str
    seed: int
    data_period: str
    oos_period: str
    results: list[ConfigResult]
    optimal_config_name: str
    optimal_weights: dict[str, float]
    oos_result: ConfigResult | None = None
    comparison_table: str


# ── Helper functions ──────────────────────────────────────────────────────────


def _sma(closes: list[float], window: int) -> float | None:
    """Return the simple moving average of the last *window* close prices.

    Args:
        closes: Chronologically ordered list of close prices.
        window: Number of most-recent candles to average.

    Returns:
        SMA value, or ``None`` when fewer than *window* values are available.
    """
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _ma_signal(closes: list[float]) -> str:
    """Return ``"buy"``, ``"sell"``, or ``"hold"`` from a dual-SMA crossover.

    Args:
        closes: Chronologically ordered close prices.

    Returns:
        One of ``"buy"``, ``"sell"``, or ``"hold"``.
    """
    fast = _sma(closes, _MA_FAST)
    slow = _sma(closes, _MA_SLOW)
    if fast is None or slow is None:
        return "hold"
    if fast > slow:
        return "buy"
    if fast < slow:
        return "sell"
    return "hold"


def _extract_closes(candles_response: dict[str, Any]) -> list[float]:
    """Extract close prices from a ``get_backtest_candles`` response.

    Args:
        candles_response: Raw API response dict.

    Returns:
        Chronologically ordered list of close prices.  Empty list on error.
    """
    closes: list[float] = []
    for c in candles_response.get("candles", []):
        raw = c.get("close")
        if raw is not None:
            try:
                closes.append(float(raw))
            except (ValueError, TypeError):
                pass
    return closes


def _safe_float(value: Any, default: float = 0.0) -> float:  # noqa: ANN401
    """Convert *value* to float, returning *default* on failure.

    Args:
        value: Any value to convert.
        default: Fallback value.

    Returns:
        Float representation or *default*.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _build_synthetic_signals(
    closes_by_symbol: dict[str, list[float]],
    weights: dict[SignalSource, float],
) -> list[WeightedSignal]:
    """Build synthetic WeightedSignals from MA-crossover closes for all three sources.

    Each symbol produces three WeightedSignals (one per SignalSource).  All three
    sources agree with the MA-crossover direction but their confidence is scaled by
    the MA spread, making the ensemble weight the primary variable under test.

    The confidence for each signal is the normalised absolute spread between the
    fast and slow MA, clamped to [0, 1].  This ensures non-trivial confidence
    values that respond to the weight configuration being tested.

    Args:
        closes_by_symbol: Symbol → ordered close price list.
        weights: Current weight configuration (used only to confirm all three
            sources emit signals; the MetaLearner normalises them itself).

    Returns:
        List of WeightedSignals, three per symbol.
    """
    signals: list[WeightedSignal] = []

    for symbol, closes in closes_by_symbol.items():
        ma_dir = _ma_signal(closes)
        action = (
            TradeAction.BUY if ma_dir == "buy"
            else TradeAction.SELL if ma_dir == "sell"
            else TradeAction.HOLD
        )

        # Confidence = normalised |fast - slow| / slow, clamped to [0, 1].
        # A non-zero confidence only when the MA spread is meaningful.
        fast = _sma(closes, _MA_FAST)
        slow = _sma(closes, _MA_SLOW)
        confidence: float = 0.0
        if fast is not None and slow is not None and slow > 0:
            confidence = min(abs(fast - slow) / slow, 1.0)

        for source in SignalSource:
            signals.append(
                WeightedSignal(
                    source=source,
                    symbol=symbol,
                    action=action,
                    confidence=confidence,
                    metadata={
                        "fast_ma": round(fast, 4) if fast is not None else None,
                        "slow_ma": round(slow, 4) if slow is not None else None,
                    },
                )
            )

    return signals


def _generate_weight_configs(seed: int) -> list[WeightConfig]:
    """Generate 12 weight configurations: 4 fixed + 8 seeded-random.

    Fixed configurations
    --------------------
    - ``equal``         — [0.33, 0.33, 0.33] equal contribution from all sources
    - ``rl_heavy``      — [0.50, 0.25, 0.25] RL dominates
    - ``evolved_heavy`` — [0.25, 0.50, 0.25] EVOLVED (genetic) dominates
    - ``regime_heavy``  — [0.25, 0.25, 0.50] REGIME classifier dominates

    Random configurations
    ---------------------
    Eight additional configurations are drawn from Dirichlet(alpha=[1,1,1]) so
    that weights are uniformly distributed over the 3-simplex.  The seed
    ensures reproducibility.

    Args:
        seed: Integer seed for the random weight generator.

    Returns:
        List of 12 ``WeightConfig`` instances.
    """
    fixed: list[WeightConfig] = [
        WeightConfig(
            name="equal",
            description="Equal contribution: [0.33, 0.33, 0.33] across RL, EVOLVED, REGIME.",
            weights={
                SignalSource.RL: 0.333,
                SignalSource.EVOLVED: 0.333,
                SignalSource.REGIME: 0.334,
            },
        ),
        WeightConfig(
            name="rl_heavy",
            description="RL dominates at 0.50; EVOLVED and REGIME each at 0.25.",
            weights={
                SignalSource.RL: 0.50,
                SignalSource.EVOLVED: 0.25,
                SignalSource.REGIME: 0.25,
            },
        ),
        WeightConfig(
            name="evolved_heavy",
            description="Genetic-algorithm EVOLVED dominates at 0.50; RL and REGIME each at 0.25.",
            weights={
                SignalSource.RL: 0.25,
                SignalSource.EVOLVED: 0.50,
                SignalSource.REGIME: 0.25,
            },
        ),
        WeightConfig(
            name="regime_heavy",
            description="REGIME classifier dominates at 0.50; RL and EVOLVED each at 0.25.",
            weights={
                SignalSource.RL: 0.25,
                SignalSource.EVOLVED: 0.25,
                SignalSource.REGIME: 0.50,
            },
        ),
    ]

    rng = random.Random(seed)  # noqa: S311 — not used for cryptography

    random_configs: list[WeightConfig] = []
    for idx in range(_N_RANDOM_CONFIGS):
        # Draw three uniform values then normalise to get a simplex point.
        raw = [rng.random() for _ in range(3)]
        total = sum(raw)
        w_rl, w_ev, w_re = (v / total for v in raw)
        random_configs.append(
            WeightConfig(
                name=f"random_{idx + 1:02d}",
                description=(
                    f"Random simplex point #{idx + 1} (seed={seed}): "
                    f"rl={w_rl:.3f}, evolved={w_ev:.3f}, regime={w_re:.3f}."
                ),
                weights={
                    SignalSource.RL: w_rl,
                    SignalSource.EVOLVED: w_ev,
                    SignalSource.REGIME: w_re,
                },
            )
        )

    return fixed + random_configs


def _normalise_weights(weights: dict[SignalSource, float]) -> dict[str, float]:
    """Normalise a raw weight dict so values sum to 1.0.

    Returns a JSON-serialisable dict with string keys.

    Args:
        weights: Raw per-source weight mapping.

    Returns:
        Dict with ``SignalSource.value`` string keys and normalised float values.
    """
    total = sum(weights.values())
    if total <= 0:
        equal = 1.0 / len(weights)
        return {s.value: equal for s in weights}
    return {s.value: round(w / total, 6) for s, w in weights.items()}


def _build_comparison_table(results: list[ConfigResult]) -> str:
    """Build a Markdown comparison table sorted by Sharpe ratio (best first).

    Args:
        results: All configuration results (may include errors).

    Returns:
        Markdown table string.
    """
    header = (
        "| Rank | Config | RL | EVOLVED | REGIME | Sharpe | ROI% | MaxDD% | Trades |\n"
        "|------|--------|----|---------|--------|--------|------|--------|--------|\n"
    )
    rows: list[str] = []
    for rank, result in enumerate(results, start=1):
        w = result.weights
        rl_w = f"{w.get(SignalSource.RL.value, 0.0):.3f}"
        ev_w = f"{w.get(SignalSource.EVOLVED.value, 0.0):.3f}"
        re_w = f"{w.get(SignalSource.REGIME.value, 0.0):.3f}"
        sharpe = f"{result.sharpe_ratio:.4f}" if result.sharpe_ratio is not None else "N/A"
        roi = f"{result.roi_pct:.2f}" if result.roi_pct is not None else "N/A"
        dd = f"{result.max_drawdown_pct:.2f}" if result.max_drawdown_pct is not None else "N/A"
        rows.append(
            f"| {rank} | {result.config_name} | {rl_w} | {ev_w} | {re_w} "
            f"| {sharpe} | {roi} | {dd} | {result.total_trades} |"
        )
    return header + "\n".join(rows)


# ── Public weight utilities ───────────────────────────────────────────────────


def save_optimal_weights_json(
    weights: dict[str, float],
    path: Path,
) -> None:
    """Write a compact ``optimal_weights.json`` compatible with ``EnsembleConfig.weights``.

    The file format is a flat JSON object mapping signal-source names to
    normalised floats.  It can be loaded directly as the ``weights`` field in
    ``EnsembleConfig``::

        {"rl": 0.45, "evolved": 0.30, "regime": 0.25}

    Args:
        weights: Dict mapping signal-source string keys to normalised floats.
            Keys must match :class:`~agent.strategies.ensemble.signals.SignalSource`
            values (``"rl"``, ``"evolved"``, ``"regime"``).
        path: Destination file path.  Parent directories are created if needed.

    Raises:
        ValueError: If any weight is negative or if the keys do not include
            all expected signal sources.
    """
    expected_keys = {s.value for s in SignalSource}
    provided_keys = set(weights.keys())
    if provided_keys != expected_keys:
        raise ValueError(
            f"weights keys {provided_keys!r} do not match expected "
            f"SignalSource values {expected_keys!r}."
        )
    if any(w < 0 for w in weights.values()):
        raise ValueError("All weights must be non-negative.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(weights, indent=4), encoding="utf-8")
    log.info(
        "agent.strategy.ensemble.optimize_weights.optimal_weights_json_saved",
        path=str(path),
        weights=weights,
    )


def load_optimal_weights(path: Path) -> dict[str, float]:
    """Load a compact ``optimal_weights.json`` written by :func:`save_optimal_weights_json`.

    Args:
        path: Path to the JSON file.

    Returns:
        Dict mapping signal-source names to floats.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file contents are not a valid weight dict.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"optimal_weights.json not found at {path}. "
            "Run optimize_weights.py first to generate it."
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"Expected a JSON object in {path}, got {type(raw).__name__}."
        )

    weights: dict[str, float] = {}
    for key, value in raw.items():
        try:
            weights[key] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Non-numeric weight value for key {key!r} in {path}: {value!r}"
            ) from exc

    expected_keys = {s.value for s in SignalSource}
    missing = expected_keys - set(weights.keys())
    if missing:
        raise ValueError(
            f"optimal_weights.json is missing keys {missing!r}. "
            "Re-run optimize_weights.py to regenerate."
        )

    return weights


def apply_optimal_weights(
    config: EnsembleConfig,
    weights: dict[str, float],
) -> EnsembleConfig:
    """Return a copy of *config* with the given optimal weights applied.

    This is the bridge between the optimizer output and the live
    ``EnsembleConfig``.  Typical usage after training completes::

        from agent.strategies.ensemble.optimize_weights import load_optimal_weights, apply_optimal_weights
        from agent.strategies.ensemble.config import EnsembleConfig

        weights = load_optimal_weights(Path("agent/strategies/ensemble/optimal_weights.json"))
        config = apply_optimal_weights(EnsembleConfig(), weights)

    Args:
        config: Existing :class:`~agent.strategies.ensemble.config.EnsembleConfig`
            instance.  Not mutated.
        weights: Normalised weight dict (string keys matching ``SignalSource``
            values) as returned by :func:`load_optimal_weights`.

    Returns:
        A new ``EnsembleConfig`` instance with ``weights`` replaced.

    Raises:
        ValueError: If *weights* contains invalid keys or negative values.
    """
    expected_keys = {s.value for s in SignalSource}
    provided_keys = set(weights.keys())
    if not expected_keys.issubset(provided_keys):
        missing = expected_keys - provided_keys
        raise ValueError(
            f"weights is missing required keys {missing!r}. "
            "Ensure the file was written by save_optimal_weights_json()."
        )
    if any(w < 0 for w in weights.values()):
        raise ValueError("All weights must be non-negative.")

    return config.model_copy(update={"weights": {k: v for k, v in weights.items() if k in expected_keys}})


def validate_ensemble_beats_baseline(
    optimal_result: ConfigResult,
    equal_weight_result: ConfigResult | None,
) -> tuple[bool, str]:
    """Check that the optimal configuration beats the equal-weight baseline.

    This is a post-optimisation sanity check.  A failure does not block saving
    the results — it is surfaced as a warning so operators can decide whether
    to use the optimised weights.

    Args:
        optimal_result: Best-ranked :class:`ConfigResult` from
            :meth:`WeightOptimizer.rank_results`.
        equal_weight_result: The equal-weight configuration result (config
            name ``"equal"``).  May be ``None`` if the equal-weight run failed.

    Returns:
        ``(passed: bool, message: str)`` where *passed* is ``True`` when the
        optimal weights beat the baseline, and *message* describes the outcome.
    """
    if optimal_result.error:
        return (
            False,
            f"Optimal configuration '{optimal_result.config_name}' has an error: {optimal_result.error}",
        )

    optimal_sharpe = optimal_result.sharpe_ratio
    if optimal_sharpe is None:
        return (
            False,
            f"Optimal configuration '{optimal_result.config_name}' has no Sharpe ratio "
            "(insufficient trades).  Cannot validate improvement.",
        )

    if equal_weight_result is None or equal_weight_result.error or equal_weight_result.sharpe_ratio is None:
        return (
            True,
            f"Equal-weight baseline unavailable; skipping comparison.  "
            f"Optimal Sharpe: {optimal_sharpe:.4f}.",
        )

    baseline_sharpe = equal_weight_result.sharpe_ratio
    if optimal_sharpe > baseline_sharpe:
        return (
            True,
            f"Optimal config '{optimal_result.config_name}' (Sharpe={optimal_sharpe:.4f}) "
            f"beats equal-weight baseline (Sharpe={baseline_sharpe:.4f}) "
            f"by {optimal_sharpe - baseline_sharpe:.4f}.",
        )
    else:
        return (
            False,
            f"Optimal config '{optimal_result.config_name}' (Sharpe={optimal_sharpe:.4f}) "
            f"does NOT beat equal-weight baseline (Sharpe={baseline_sharpe:.4f}).  "
            "Using optimised weights may not improve performance; review manually.",
        )


# ── WeightOptimizer ───────────────────────────────────────────────────────────


class WeightOptimizer:
    """Runs backtests for multiple weight configurations and ranks them by Sharpe.

    Args:
        base_url: Platform REST API base URL (e.g. ``"http://localhost:8000"``).
        api_key: Platform API key (``ak_live_...``).
        seed: Integer seed for reproducible random weight generation.
            Default ``42``.
        max_iterations: Maximum trade-decision loop iterations per backtest.
            Each iteration fetches candles, generates signals, optionally places
            an order, then advances ``batch_size`` candles.  Default ``20``.
        batch_size: Number of candle steps to advance per iteration.
            Default ``5``.
        backtest_days: Length of the in-sample backtest window in calendar days.
            Default ``7``.
        oos_days: Length of the out-of-sample validation window in calendar
            days (measured immediately before the in-sample window).  Default ``7``.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        seed: int = 42,
        max_iterations: int = 20,
        batch_size: int = 5,
        backtest_days: int = 7,
        oos_days: int = 7,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._seed = seed
        self._max_iterations = max_iterations
        self._batch_size = batch_size
        self._backtest_days = backtest_days
        self._oos_days = oos_days
        self._configs: list[WeightConfig] = _generate_weight_configs(seed)
        self._results: list[ConfigResult] = []

    # ── Public entry point ────────────────────────────────────────────────────

    async def run_optimization(self) -> list[ConfigResult]:
        """Run a backtest for every weight configuration and collect results.

        Returns:
            List of :class:`ConfigResult` in the same order as the generated
            configurations (not yet ranked).  Call :meth:`rank_results` to
            get them sorted by Sharpe ratio.
        """
        log.info(
            "agent.strategy.ensemble.optimize_weights.start",
            configs=len(self._configs),
            seed=self._seed,
            backtest_days=self._backtest_days,
        )

        async with _BacktestClient(self._base_url, self._api_key) as client:
            # Discover data range once; re-use for all configurations.
            start_iso, end_iso = await self._resolve_date_range(client, self._backtest_days)
            log.info(
                "agent.strategy.ensemble.optimize_weights.date_range",
                start=start_iso,
                end=end_iso,
            )

            for cfg in self._configs:
                log.info("agent.strategy.ensemble.optimize_weights.evaluating", config=cfg.name)
                result = await self._run_single_backtest(client, cfg, start_iso, end_iso)
                self._results.append(result)
                log.info(
                    "agent.strategy.ensemble.optimize_weights.evaluated",
                    config=cfg.name,
                    sharpe=result.sharpe_ratio,
                    roi=result.roi_pct,
                    trades=result.total_trades,
                    error=result.error,
                )

        return self._results

    def rank_results(self) -> list[ConfigResult]:
        """Return results sorted by Sharpe ratio (best first).

        Configurations with no Sharpe (due to insufficient trades or errors) are
        ranked last.  Among those with no Sharpe, they are sorted by ROI then by
        trade count.

        Returns:
            Sorted copy of :attr:`_results`.  The original list is unchanged.
        """
        def sort_key(r: ConfigResult) -> tuple[float, float, int]:
            sharpe = r.sharpe_ratio if r.sharpe_ratio is not None else -1e9
            roi = r.roi_pct if r.roi_pct is not None else -1e9
            return (sharpe, roi, r.total_trades)

        return sorted(self._results, key=sort_key, reverse=True)

    async def validate_oos(
        self,
        optimal_config: WeightConfig,
    ) -> ConfigResult:
        """Run the optimal weight configuration on the out-of-sample period.

        The OOS period is ``oos_days`` immediately before the in-sample window.
        This prevents data leakage from the tuning process.

        Args:
            optimal_config: The best-ranked :class:`WeightConfig` from
                :meth:`rank_results`.

        Returns:
            A :class:`ConfigResult` for the OOS evaluation period.
        """
        log.info(
            "agent.strategy.ensemble.optimize_weights.oos_validation",
            config=optimal_config.name,
            oos_days=self._oos_days,
        )

        async with _BacktestClient(self._base_url, self._api_key) as client:
            # Resolve the in-sample end date, then step back by backtest_days
            # to get the OOS period end.
            is_start_iso, is_end_iso = await self._resolve_date_range(client, self._backtest_days)

            # Parse in-sample start as OOS end
            is_start_dt = datetime.fromisoformat(is_start_iso.replace("Z", "+00:00"))
            oos_end_dt = is_start_dt
            oos_start_dt = oos_end_dt - timedelta(days=self._oos_days)

            oos_start_iso = oos_start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            oos_end_iso = oos_end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            log.info(
                "agent.strategy.ensemble.optimize_weights.oos_period",
                oos_start=oos_start_iso,
                oos_end=oos_end_iso,
            )

            oos_config = WeightConfig(
                name=f"{optimal_config.name}_oos",
                description=f"OOS validation of {optimal_config.name}.",
                weights=optimal_config.weights,
            )

            result = await self._run_single_backtest(client, oos_config, oos_start_iso, oos_end_iso)

        log.info(
            "agent.strategy.ensemble.optimize_weights.oos_complete",
            sharpe=result.sharpe_ratio,
            roi=result.roi_pct,
        )
        return result

    def save_results(
        self,
        path: Path,
        oos_result: ConfigResult | None = None,
        data_period: str = "",
        oos_period: str = "",
    ) -> OptimizationResult:
        """Build an ``OptimizationResult``, persist it to *path*, and return it.

        Args:
            path: File path for the JSON output (e.g.
                ``Path("agent/reports/weight-optimization-20260320_120000.json")``).
                Parent directories are created automatically.
            oos_result: Out-of-sample validation result from
                :meth:`validate_oos`.  Can be ``None`` if validation was skipped.
            data_period: Human-readable in-sample period description.
            oos_period: Human-readable OOS period description.

        Returns:
            The fully populated :class:`OptimizationResult`.
        """
        ranked = self.rank_results()
        optimal = ranked[0]

        comparison_table = _build_comparison_table(ranked)

        result = OptimizationResult(
            timestamp=datetime.now(UTC).isoformat(),
            seed=self._seed,
            data_period=data_period or f"in-sample ({self._backtest_days} days)",
            oos_period=oos_period or f"oos ({self._oos_days} days before in-sample)",
            results=ranked,
            optimal_config_name=optimal.config_name,
            optimal_weights=optimal.weights,
            oos_result=oos_result,
            comparison_table=comparison_table,
        )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        log.info("agent.strategy.ensemble.optimize_weights.saved", path=str(path))
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _resolve_date_range(
        self,
        client: _BacktestClient,
        days: int,
    ) -> tuple[str, str]:
        """Resolve the in-sample date range from the platform or use fallback.

        Args:
            client: Open ``_BacktestClient`` instance.
            days: Number of days for the backtest window.

        Returns:
            Tuple of ``(start_iso, end_iso)`` strings.
        """
        try:
            data_range = await client._get("/api/v1/market/data-range")
            latest_str: str | None = data_range.get("latest")
            if latest_str:
                latest_str = latest_str.replace("Z", "+00:00")
                end_dt = datetime.fromisoformat(latest_str).astimezone(UTC)
                start_dt = end_dt - timedelta(days=days)
                return (
                    start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            log.warning("agent.strategy.ensemble.optimize_weights.data_range_failed", error=str(exc))

        # Fallback
        end_dt = _FALLBACK_END
        start_dt = end_dt - timedelta(days=days)
        return (
            start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    async def _run_single_backtest(
        self,
        client: _BacktestClient,
        cfg: WeightConfig,
        start_iso: str,
        end_iso: str,
    ) -> ConfigResult:
        """Run one complete backtest for a single weight configuration.

        Args:
            client: Open ``_BacktestClient`` instance.
            cfg: The weight configuration to evaluate.
            start_iso: ISO-8601 backtest start date.
            end_iso: ISO-8601 backtest end date.

        Returns:
            Populated :class:`ConfigResult`.  On API-level errors, the
            ``error`` field is set and metric fields remain ``None``.
        """
        normalised_weights = _normalise_weights(cfg.weights)
        meta = MetaLearner(weights=cfg.weights)

        # ── Create session ────────────────────────────────────────────────────
        try:
            create_resp = await client.create_backtest(
                start_time=start_iso,
                end_time=end_iso,
                symbols=_BACKTEST_SYMBOLS,
                interval=_CANDLE_INTERVAL,
                starting_balance=_STARTING_BALANCE,
                strategy_label=f"weight_opt_{cfg.name}",
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return ConfigResult(
                config_name=cfg.name,
                weights=normalised_weights,
                error=f"create_backtest failed: {exc}",
            )

        session_id: str | None = create_resp.get("session_id")
        if not session_id:
            return ConfigResult(
                config_name=cfg.name,
                weights=normalised_weights,
                error=f"create_backtest returned no session_id: {create_resp}",
            )

        # ── Start session ─────────────────────────────────────────────────────
        try:
            start_resp = await client.start_backtest(session_id)
            if start_resp.get("status") != "running":
                return ConfigResult(
                    config_name=cfg.name,
                    weights=normalised_weights,
                    session_id=session_id,
                    error=f"start_backtest unexpected status: {start_resp}",
                )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return ConfigResult(
                config_name=cfg.name,
                weights=normalised_weights,
                session_id=session_id,
                error=f"start_backtest failed: {exc}",
            )

        # ── Trading loop ──────────────────────────────────────────────────────
        trades_placed = 0
        open_positions: dict[str, str] = {}  # symbol → side
        loop_complete = False

        for _iteration in range(self._max_iterations):
            closes_by_symbol: dict[str, list[float]] = {}

            for symbol in _BACKTEST_SYMBOLS:
                try:
                    candles_resp = await client.get_backtest_candles(
                        session_id=session_id,
                        symbol=symbol,
                        interval=_CANDLE_INTERVAL,
                        limit=max(_MA_SLOW + 5, 30),
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (404, 409, 410):
                        loop_complete = True
                        break
                    continue
                except httpx.RequestError:
                    continue

                closes_by_symbol[symbol] = _extract_closes(candles_resp)

            if loop_complete:
                break

            # Build synthetic signals for all symbols × all sources
            all_signals = _build_synthetic_signals(closes_by_symbol, cfg.weights)

            # Group signals by symbol and combine via MetaLearner
            signals_by_symbol: dict[str, list[WeightedSignal]] = {}
            for sig in all_signals:
                signals_by_symbol.setdefault(sig.symbol, []).append(sig)

            consensus_signals: list[ConsensusSignal] = []
            for symbol, sigs in signals_by_symbol.items():
                try:
                    consensus_signals.append(meta.combine(sigs))
                except ValueError:
                    pass

            # Act on consensus signals
            for consensus in consensus_signals:
                symbol = consensus.symbol
                action = consensus.action

                if action == TradeAction.HOLD:
                    continue

                side = action.value  # "buy" or "sell"

                # Avoid stacking same-direction positions
                if open_positions.get(symbol) == side:
                    continue
                # Avoid flipping open positions (keep the loop simple)
                if symbol in open_positions and open_positions[symbol] != side:
                    continue

                qty = _ORDER_QTY.get(symbol, _DEFAULT_QTY)
                try:
                    order_resp = await client.backtest_trade(
                        session_id=session_id,
                        symbol=symbol,
                        side=side,
                        quantity=qty,
                        order_type="market",
                    )
                    if order_resp.get("status") not in (None,):
                        open_positions[symbol] = side
                        trades_placed += 1
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (404, 409, 410):
                        loop_complete = True
                        break
                except httpx.RequestError:
                    pass

            if loop_complete:
                break

            # Advance candles
            try:
                step_resp = await client.step_backtest_batch(
                    session_id=session_id,
                    steps=self._batch_size,
                )
                if step_resp.get("is_complete"):
                    loop_complete = True
                    break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 409, 410):
                    loop_complete = True
                break
            except httpx.RequestError:
                break

        # ── Fetch results ─────────────────────────────────────────────────────
        try:
            results_resp = await client.get_backtest_results(session_id)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return ConfigResult(
                config_name=cfg.name,
                weights=normalised_weights,
                session_id=session_id,
                total_trades=trades_placed,
                error=f"get_backtest_results failed: {exc}",
            )

        summary = results_resp.get("summary") or {}
        bt_metrics = results_resp.get("metrics") or {}

        return ConfigResult(
            config_name=cfg.name,
            weights=normalised_weights,
            session_id=session_id,
            sharpe_ratio=_safe_float(bt_metrics.get("sharpe_ratio")) or None,
            roi_pct=_safe_float(summary.get("roi_pct")) or None,
            max_drawdown_pct=_safe_float(bt_metrics.get("max_drawdown_pct")) or None,
            total_trades=int(_safe_float(summary.get("total_trades"), 0)),
        )


# ── CLI entry point ───────────────────────────────────────────────────────────


async def _cli_main(
    base_url: str,
    api_key: str,
    seed: int,
    output_dir: Path,
    oos_days: int,
    max_iterations: int,
    batch_size: int,
) -> None:
    """Async implementation of the CLI entry point.

    Args:
        base_url: Platform REST API base URL.
        api_key: Platform API key.
        seed: Random seed for weight generation.
        output_dir: Directory to write the JSON report.
        oos_days: Out-of-sample validation window length in days.
        max_iterations: Max iterations per backtest trading loop.
        batch_size: Candle steps per iteration.
    """
    from agent.logging import configure_agent_logging  # noqa: PLC0415

    configure_agent_logging()

    optimizer = WeightOptimizer(
        base_url=base_url,
        api_key=api_key,
        seed=seed,
        max_iterations=max_iterations,
        batch_size=batch_size,
        oos_days=oos_days,
    )

    log.info("agent.strategy.ensemble.optimize_weights.cli.start", base_url=base_url, seed=seed)

    # Run all 12 configurations
    await optimizer.run_optimization()

    # Rank and identify optimal
    ranked = optimizer.rank_results()
    optimal = ranked[0]
    log.info(
        "agent.strategy.ensemble.optimize_weights.cli.optimal",
        config=optimal.config_name,
        sharpe=optimal.sharpe_ratio,
        roi=optimal.roi_pct,
    )

    # Resolve in-sample period description for the report
    async with _BacktestClient(base_url, api_key) as client:
        is_start, is_end = await optimizer._resolve_date_range(client, optimizer._backtest_days)
    data_period = f"{is_start} → {is_end}"

    # Out-of-sample validation on the optimal configuration
    optimal_cfg = next(c for c in optimizer._configs if c.name == optimal.config_name)
    oos_result = await optimizer.validate_oos(optimal_cfg)

    # Resolve OOS period description
    is_start_dt = datetime.fromisoformat(is_start.replace("Z", "+00:00"))
    oos_end_dt = is_start_dt
    oos_start_dt = oos_end_dt - timedelta(days=oos_days)
    oos_period = f"{oos_start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')} → {oos_end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}"

    # Save full results
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"weight-optimization-{timestamp}.json"
    final_result = optimizer.save_results(
        path=output_path,
        oos_result=oos_result,
        data_period=data_period,
        oos_period=oos_period,
    )

    # ── Validation gate: ensemble must beat equal-weight baseline ─────────────
    equal_weight_result: ConfigResult | None = next(
        (r for r in ranked if r.config_name == "equal"),
        None,
    )
    passed, validation_message = validate_ensemble_beats_baseline(optimal, equal_weight_result)
    if passed:
        log.info(
            "agent.strategy.ensemble.optimize_weights.validation.passed",
            message=validation_message,
        )
    else:
        log.warning(
            "agent.strategy.ensemble.optimize_weights.validation.failed",
            message=validation_message,
        )

    # ── Write compact optimal_weights.json ────────────────────────────────────
    optimal_weights_path = output_dir / "optimal_weights.json"
    try:
        save_optimal_weights_json(final_result.optimal_weights, optimal_weights_path)
    except ValueError as exc:
        log.error(
            "agent.strategy.ensemble.optimize_weights.optimal_weights_save_failed",
            error=str(exc),
        )

    # Log optimization summary.
    log.info(
        "agent.strategy.ensemble.optimize_weights.complete",
        configs_evaluated=len(ranked),
        optimal_config=final_result.optimal_config_name,
        optimal_weights=final_result.optimal_weights,
        oos_sharpe=str(oos_result.sharpe_ratio) if oos_result else None,
        oos_roi_pct=str(oos_result.roi_pct) if oos_result else None,
        oos_trades=oos_result.total_trades if oos_result else None,
        output_path=str(output_path),
        optimal_weights_path=str(optimal_weights_path),
        validation_passed=passed,
        validation_message=validation_message,
    )


def main() -> None:
    """Parse CLI arguments and run the weight optimizer.

    Usage::

        python -m agent.strategies.ensemble.optimize_weights \\
            --base-url http://localhost:8000 \\
            [--seed 42] \\
            [--output-dir agent/reports] \\
            [--oos-days 7] \\
            [--max-iterations 20] \\
            [--batch-size 5]
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="optimize_weights",
        description="Meta-learner weight optimizer via backtests.",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Platform REST API base URL (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for weight generation (default: 42).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent.parent / "reports",
        help="Output directory for the JSON report (default: agent/reports/).",
    )
    parser.add_argument(
        "--oos-days",
        type=int,
        default=7,
        help="Out-of-sample validation window in calendar days (default: 7).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        help="Maximum trading loop iterations per backtest (default: 20).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Candle steps to advance per iteration (default: 5).",
    )

    args = parser.parse_args()

    import os  # noqa: PLC0415

    api_key = os.environ.get("ENSEMBLE_PLATFORM_API_KEY", "") or os.environ.get("PLATFORM_API_KEY", "")
    if not api_key:
        parser.error(
            "Platform API key not set. "
            "Set ENSEMBLE_PLATFORM_API_KEY or PLATFORM_API_KEY in agent/.env or as environment variable."
        )

    asyncio.run(
        _cli_main(
            base_url=args.base_url,
            api_key=api_key,
            seed=args.seed,
            output_dir=args.output_dir,
            oos_days=args.oos_days,
            max_iterations=args.max_iterations,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    main()
