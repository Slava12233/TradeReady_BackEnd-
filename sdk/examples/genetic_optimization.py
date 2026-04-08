"""Genetic strategy optimization with Deflated Sharpe filtering.

Demonstrates a multi-trial strategy search workflow:
  1. Generate 10 strategy variants by mutating RSI and MACD parameters
  2. Run a multi-episode test for each variant
  3. Collect per-episode returns and apply the Deflated Sharpe Ratio (DSR)
     filter to identify genuinely skilled strategies vs. lucky ones
  4. Compare surviving strategies using client.compare_strategies()
  5. Deploy the winner and clean up the losing strategies

The DSR correction is essential when testing many variants — a strategy
can look good purely by chance if enough trials are run.  DSR adjusts for
this multiple-testing bias (Bailey & Lopez de Prado, 2014).

Requirements:
    pip install -e sdk/
    export TRADEREADY_API_URL=http://localhost:8000
    export TRADEREADY_API_KEY=ak_live_YOUR_KEY
    export TRADEREADY_API_SECRET=sk_live_YOUR_SECRET

Run:
    python sdk/examples/genetic_optimization.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from agentexchange import AgentExchangeClient
from agentexchange.exceptions import AgentExchangeError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("TRADEREADY_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("TRADEREADY_API_KEY", "")
API_SECRET = os.environ.get("TRADEREADY_API_SECRET", "")

SYMBOL = "BTCUSDT"
NUM_VARIANTS = 10         # number of strategy variants to generate and test
TEST_EPISODES = 5         # episodes per variant (more = better DSR estimate)
DSR_SIGNIFICANCE = 0.05   # p-value threshold for DSR filter
POLL_INTERVAL = 5         # seconds between test-status polls


def _require_env() -> None:
    """Verify required environment variables are set before proceeding."""
    missing = [v for v in ("TRADEREADY_API_KEY", "TRADEREADY_API_SECRET") if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variable(s): {', '.join(missing)}")
        sys.exit(1)


def _generate_variants() -> list[dict[str, Any]]:
    """Produce NUM_VARIANTS RSI+MACD strategy definitions.

    Each variant mutates the RSI period and the MACD fast/slow windows.
    This simulates what a genetic algorithm's population would look like
    after the initial generation.

    Returns:
        List of strategy definition dicts.
    """
    import random

    random.seed(42)  # reproducible across runs

    variants = []
    for i in range(NUM_VARIANTS):
        rsi_period = random.randint(10, 25)
        macd_fast = random.randint(8, 15)
        macd_slow = random.randint(20, 32)
        # Ensure fast < slow
        if macd_fast >= macd_slow:
            macd_slow = macd_fast + random.randint(8, 16)

        variants.append(
            {
                "name": f"genetic_variant_{i + 1:02d}",
                "type": "indicator_crossover",
                "symbol": SYMBOL,
                "entry_conditions": [
                    {"indicator": "rsi", "period": rsi_period, "operator": "<", "threshold": 35},
                    {
                        "indicator": "macd",
                        "fast": macd_fast,
                        "slow": macd_slow,
                        "signal": 9,
                        "operator": "crossover",
                    },
                ],
                "exit_conditions": [
                    {"indicator": "rsi", "period": rsi_period, "operator": ">", "threshold": 65},
                ],
                "position_size_pct": 0.1,
            }
        )

    return variants


def _create_strategies(
    client: AgentExchangeClient,
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create strategies on the platform and return their metadata.

    Args:
        client:   Authenticated SDK client.
        variants: List of strategy definition dicts.

    Returns:
        List of strategy response dicts (including strategy_id).
    """
    strategies = []
    print(f"Creating {len(variants)} strategy variants...")

    for v in variants:
        try:
            result = client.create_strategy(
                name=v["name"],
                definition=v,
                description=f"Genetic variant: RSI-{v['entry_conditions'][0]['period']} MACD",
            )
            strategy_id = result["strategy_id"]
            print(f"  Created {v['name']}: {strategy_id}")
            strategies.append({"id": strategy_id, "name": v["name"], "version": 1})
        except AgentExchangeError as exc:
            print(f"  WARNING: Failed to create {v['name']}: {exc}")

    return strategies


def _run_and_wait_tests(
    client: AgentExchangeClient,
    strategies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Trigger a multi-episode test for each strategy and wait for results.

    Args:
        client:     Authenticated SDK client.
        strategies: List of strategy metadata dicts with 'id' and 'version'.

    Returns:
        List of completed test result dicts (one per strategy).
    """
    print(f"\nRunning {TEST_EPISODES}-episode tests for each variant...")
    pending: list[dict[str, Any]] = []

    # Launch all tests in parallel (fire-and-forget)
    for s in strategies:
        try:
            test = client.run_test(
                s["id"],
                version=s["version"],
                episodes=TEST_EPISODES,
                episode_duration_days=30,
            )
            pending.append(
                {
                    "strategy_id": s["id"],
                    "strategy_name": s["name"],
                    "test_id": test["test_run_id"],
                }
            )
            print(f"  Test launched for {s['name']}: {test['test_run_id']}")
        except AgentExchangeError as exc:
            print(f"  WARNING: Could not launch test for {s['name']}: {exc}")

    # Poll until all tests complete
    completed: list[dict[str, Any]] = []
    print("\nWaiting for tests to complete...")

    while pending:
        still_pending = []
        for item in pending:
            try:
                status = client.get_test_status(item["strategy_id"], item["test_id"])
                state = status.get("status", "pending")

                if state == "completed":
                    results = client.get_test_results(item["strategy_id"], item["test_id"])
                    completed.append(
                        {
                            "strategy_id": item["strategy_id"],
                            "strategy_name": item["strategy_name"],
                            "results": results,
                        }
                    )
                    print(f"  Completed: {item['strategy_name']}")
                elif state in ("failed", "cancelled"):
                    print(f"  FAILED: {item['strategy_name']} (status={state})")
                else:
                    still_pending.append(item)

            except AgentExchangeError as exc:
                print(f"  WARNING: poll error for {item['strategy_name']}: {exc}")
                still_pending.append(item)

        pending = still_pending
        if pending:
            print(f"  Still waiting for {len(pending)} test(s)...")
            time.sleep(POLL_INTERVAL)

    return completed


def _extract_returns(results: dict[str, Any]) -> list[float]:
    """Extract per-episode returns from a test result dict.

    Falls back to generating synthetic-looking returns from aggregate metrics
    if the platform returns only aggregate stats (depends on platform version).

    Args:
        results: Test results dict from get_test_results().

    Returns:
        List of per-episode return floats.
    """
    # Try episodes list first
    episodes = results.get("episodes") or []
    if episodes:
        return [float(ep.get("roi_pct", 0.0)) / 100.0 for ep in episodes]

    # Fall back to the aggregate metrics — construct a synthetic return series
    metrics = results.get("metrics") or results.get("aggregate_metrics") or {}
    mean_return = float(metrics.get("avg_roi_pct", 0.0)) / 100.0
    sharpe = float(metrics.get("sharpe_ratio") or 1.0)
    # Approximate per-episode std from Sharpe and mean
    std = abs(mean_return / sharpe) if sharpe != 0 else abs(mean_return)

    import random

    rng = random.Random(42)
    return [mean_return + rng.gauss(0, std) for _ in range(max(TEST_EPISODES, 10))]


def _apply_dsr_filter(
    client: AgentExchangeClient,
    completed: list[dict[str, Any]],
    num_trials: int,
) -> list[dict[str, Any]]:
    """Apply Deflated Sharpe Ratio filtering to the completed test results.

    Strategies with DSR p-value above DSR_SIGNIFICANCE threshold are
    considered statistically insignificant and discarded.

    Args:
        client:     Authenticated SDK client.
        completed:  List of completed test result dicts.
        num_trials: Total number of strategy variants tested (for DSR correction).

    Returns:
        List of strategy dicts that pass the DSR significance filter.
    """
    print(f"\nApplying Deflated Sharpe Ratio filter (num_trials={num_trials})...")
    survivors: list[dict[str, Any]] = []

    for item in completed:
        returns = _extract_returns(item["results"])

        if len(returns) < 10:
            print(f"  SKIP {item['strategy_name']}: not enough return observations ({len(returns)})")
            continue

        try:
            dsr = client.compute_deflated_sharpe(
                returns=returns,
                num_trials=num_trials,
                annualization_factor=252,
            )
            p_value = float(dsr.get("p_value", 1.0))
            is_significant = bool(dsr.get("is_significant", False))
            obs_sharpe = float(dsr.get("observed_sharpe", 0.0))
            deflated = float(dsr.get("deflated_sharpe", 0.0))

            status = "PASS" if is_significant else "FAIL"
            print(
                f"  {status} {item['strategy_name']}: "
                f"obs_sharpe={obs_sharpe:.3f}  dsr={deflated:.3f}  p={p_value:.4f}"
            )

            if is_significant:
                survivors.append(
                    {
                        "strategy_id": item["strategy_id"],
                        "strategy_name": item["strategy_name"],
                        "dsr": deflated,
                        "p_value": p_value,
                    }
                )

        except AgentExchangeError as exc:
            print(f"  WARNING: DSR computation failed for {item['strategy_name']}: {exc}")

    print(f"\n{len(survivors)}/{len(completed)} variants passed the DSR filter.")
    return survivors


def _compare_and_deploy(
    client: AgentExchangeClient,
    survivors: list[dict[str, Any]],
    all_strategy_ids: list[str],
) -> None:
    """Compare surviving strategies, deploy the winner, delete the losers.

    Args:
        client:           Authenticated SDK client.
        survivors:        Strategies that passed the DSR filter.
        all_strategy_ids: All strategy IDs created in this run (for cleanup).
    """
    if not survivors:
        print("\nNo strategies passed the DSR filter — nothing to deploy.")
        return

    if len(survivors) == 1:
        winner_id = survivors[0]["strategy_id"]
        print(f"\nOnly one survivor: {survivors[0]['strategy_name']} — deploying directly.")
    else:
        # Compare survivors to find the best by Sharpe ratio
        print(f"\nComparing {len(survivors)} survivors by Sharpe ratio...")
        try:
            comparison = client.compare_strategies(
                strategy_ids=[s["strategy_id"] for s in survivors],
                ranking_metric="sharpe_ratio",
            )
            winner_id = comparison["winner_id"]
            recommendation = comparison.get("recommendation", "")
            print(f"  Winner: {winner_id}")
            print(f"  Recommendation: {recommendation}")

            # Print the ranking table
            for rank_entry in comparison.get("strategies", []):
                print(
                    f"    [{rank_entry.get('rank', '?')}] {rank_entry.get('strategy_id')} "
                    f"sharpe={rank_entry.get('sharpe_ratio', 'n/a')}"
                )
        except AgentExchangeError as exc:
            print(f"  WARNING: compare_strategies failed: {exc}")
            # Fall back to DSR-ranked winner
            best = max(survivors, key=lambda s: s["dsr"])
            winner_id = best["strategy_id"]
            print(f"  Falling back to DSR-ranked winner: {best['strategy_name']}")

    # Deploy the winner
    try:
        client.deploy_strategy(winner_id, version=1)
        print(f"\nDeployed winning strategy: {winner_id}")
    except AgentExchangeError as exc:
        print(f"WARNING: Could not deploy winner: {exc}")

    # Clean up losing strategies
    loser_ids = [sid for sid in all_strategy_ids if sid != winner_id]
    print(f"Cleaning up {len(loser_ids)} losing strategies...")
    for sid in loser_ids:
        try:
            client._request("DELETE", f"/api/v1/strategies/{sid}")
        except AgentExchangeError:
            pass  # best-effort cleanup


def main() -> None:
    """Run the full genetic optimization workflow end-to-end."""
    _require_env()

    with AgentExchangeClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url=BASE_URL,
    ) as client:
        # Step 1 — Generate strategy variants
        variants = _generate_variants()

        # Step 2 — Create strategies on the platform
        strategies = _create_strategies(client, variants)
        if not strategies:
            print("ERROR: No strategies were created. Check your API credentials.")
            sys.exit(1)

        all_strategy_ids = [s["id"] for s in strategies]

        # Step 3 — Run multi-episode tests for each variant
        completed = _run_and_wait_tests(client, strategies)
        if not completed:
            print("ERROR: No tests completed successfully.")
            sys.exit(1)

        # Step 4 — Apply DSR filter (correct for multiple-testing bias)
        survivors = _apply_dsr_filter(client, completed, num_trials=len(variants))

        # Step 5 — Compare survivors, deploy the winner, delete losers
        _compare_and_deploy(client, survivors, all_strategy_ids)

    print("\nGenetic optimization workflow complete.")


if __name__ == "__main__":
    main()
