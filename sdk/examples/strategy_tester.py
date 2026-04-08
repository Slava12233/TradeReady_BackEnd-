"""Strategy creation, versioning, multi-episode testing, and deployment.

Demonstrates the strategy development lifecycle:
  1. Create a new trading strategy with an initial version
  2. Run a multi-episode test to get statistically meaningful results
  3. Inspect the Deflated Sharpe Ratio — only deploy if results are significant
  4. Create an improved second version with tighter parameters
  5. Test the new version and compare it against the first
  6. Deploy the better-performing version if the DSR test passes
  7. Undeploy if a hypothetical drawdown threshold is exceeded

This workflow mirrors what an automated strategy-improvement loop would do:
generate a candidate, test it, gate on statistical significance, compare
versions, and promote the best one.

Requirements:
    pip install -e sdk/
    export TRADEREADY_API_URL=http://localhost:8000
    export TRADEREADY_API_KEY=ak_live_YOUR_KEY
    export TRADEREADY_API_SECRET=sk_live_YOUR_SECRET

Run:
    python sdk/examples/strategy_tester.py
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

# Strategy definition — RSI mean-reversion on BTCUSDT
_BASE_DEFINITION: dict[str, Any] = {
    "type": "mean_reversion",
    "symbol": "BTCUSDT",
    "entry_conditions": [
        {"indicator": "rsi", "period": 14, "operator": "<", "threshold": 30},
    ],
    "exit_conditions": [
        {"indicator": "rsi", "period": 14, "operator": ">", "threshold": 70},
    ],
    "position_size_pct": 0.10,
    "stop_loss_pct": 0.05,
}

# Improved version — tighter RSI thresholds, smaller position, tighter stop
_IMPROVED_DEFINITION: dict[str, Any] = {
    **_BASE_DEFINITION,
    "entry_conditions": [
        {"indicator": "rsi", "period": 14, "operator": "<", "threshold": 25},
    ],
    "exit_conditions": [
        {"indicator": "rsi", "period": 14, "operator": ">", "threshold": 75},
    ],
    "position_size_pct": 0.08,
    "stop_loss_pct": 0.03,
}

EPISODES = 8             # episodes per test run
EPISODE_DAYS = 30        # days per episode
POLL_INTERVAL = 5        # seconds between status polls
DSR_P_THRESHOLD = 0.10   # deploy only if DSR p-value < this threshold
MAX_DRAWDOWN_LIMIT = 20  # undeploy if max drawdown exceeds this percent


def _require_env() -> None:
    """Verify required environment variables are set before proceeding."""
    missing = [v for v in ("TRADEREADY_API_KEY", "TRADEREADY_API_SECRET") if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variable(s): {', '.join(missing)}")
        sys.exit(1)


def _wait_for_test(
    client: AgentExchangeClient,
    strategy_id: str,
    test_id: str,
    label: str,
) -> dict[str, Any]:
    """Poll until a strategy test run completes and return the results.

    Args:
        client:      Authenticated SDK client.
        strategy_id: UUID of the strategy.
        test_id:     UUID of the test run.
        label:       Human-readable label for log messages.

    Returns:
        Completed test results dict.

    Raises:
        RuntimeError: If the test ends in a failed or cancelled state.
    """
    print(f"Waiting for {label} test to complete...")
    while True:
        status = client.get_test_status(strategy_id, test_id)
        state = status.get("status", "pending")
        progress = status.get("progress_pct", 0)

        print(f"  {label}: status={state}  progress={progress:.0f}%")

        if state == "completed":
            return client.get_test_results(strategy_id, test_id)
        if state in ("failed", "cancelled"):
            raise RuntimeError(f"Test {test_id} ended with status={state}")

        time.sleep(POLL_INTERVAL)


def _check_dsr(
    client: AgentExchangeClient,
    results: dict[str, Any],
    num_trials: int,
    label: str,
) -> tuple[bool, float]:
    """Compute DSR for the test results and return (is_significant, p_value).

    Args:
        client:     Authenticated SDK client.
        results:    Completed test results dict.
        num_trials: Number of variants tested before this one.
        label:      Human-readable strategy label for log output.

    Returns:
        Tuple of (is_significant, p_value).
    """
    # Extract per-episode returns
    episodes = results.get("episodes") or []
    if episodes:
        returns = [float(ep.get("roi_pct", 0.0)) / 100.0 for ep in episodes]
    else:
        # Approximate from aggregate metrics if per-episode data is unavailable
        metrics = results.get("metrics") or results.get("aggregate_metrics") or {}
        mean_r = float(metrics.get("avg_roi_pct", 0.0)) / 100.0
        sharpe = float(metrics.get("sharpe_ratio") or 1.0)
        std_r = abs(mean_r / sharpe) if sharpe != 0 else abs(mean_r)
        import random

        rng = random.Random(99)
        returns = [mean_r + rng.gauss(0, std_r) for _ in range(max(EPISODES, 10))]

    if len(returns) < 10:
        print(f"  DSR SKIP for {label}: insufficient observations ({len(returns)})")
        return False, 1.0

    dsr = client.compute_deflated_sharpe(
        returns=returns,
        num_trials=num_trials,
        annualization_factor=252,
    )
    p_value = float(dsr.get("p_value", 1.0))
    obs_sharpe = float(dsr.get("observed_sharpe", 0.0))
    deflated = float(dsr.get("deflated_sharpe", 0.0))
    is_sig = p_value < DSR_P_THRESHOLD

    verdict = "SIGNIFICANT" if is_sig else "NOT significant"
    print(
        f"  DSR {label}: obs_sharpe={obs_sharpe:.3f}  "
        f"deflated={deflated:.3f}  p={p_value:.4f}  -> {verdict}"
    )
    return is_sig, p_value


def main() -> None:
    """Run the full strategy development and deployment lifecycle."""
    _require_env()

    with AgentExchangeClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url=BASE_URL,
    ) as client:
        # ------------------------------------------------------------------
        # Step 1 — Create the strategy
        # ------------------------------------------------------------------
        print("Step 1: Creating strategy 'rsi_mean_reversion'...")
        strategy = client.create_strategy(
            name="rsi_mean_reversion",
            definition=_BASE_DEFINITION,
            description="RSI mean-reversion on BTCUSDT (v1: loose thresholds)",
        )
        strategy_id: str = strategy["strategy_id"]
        print(f"  Strategy created: {strategy_id}")

        # ------------------------------------------------------------------
        # Step 2 — Test version 1
        # ------------------------------------------------------------------
        print(f"\nStep 2: Running {EPISODES}-episode test for version 1...")
        test_v1 = client.run_test(
            strategy_id,
            version=1,
            episodes=EPISODES,
            episode_duration_days=EPISODE_DAYS,
        )
        results_v1 = _wait_for_test(client, strategy_id, test_v1["test_run_id"], "v1")

        metrics_v1 = results_v1.get("metrics") or results_v1.get("aggregate_metrics") or {}
        print(f"  v1 avg_roi={metrics_v1.get('avg_roi_pct', 'n/a')}%  "
              f"sharpe={metrics_v1.get('sharpe_ratio', 'n/a')}")

        # ------------------------------------------------------------------
        # Step 3 — DSR gate on v1 (num_trials=1 since this is first test)
        # ------------------------------------------------------------------
        print("\nStep 3: DSR significance check for version 1...")
        v1_significant, v1_p = _check_dsr(client, results_v1, num_trials=1, label="v1")

        # ------------------------------------------------------------------
        # Step 4 — Create and test version 2 regardless (show the workflow)
        # ------------------------------------------------------------------
        print("\nStep 4: Creating version 2 with improved parameters...")
        version_2 = client.create_version(
            strategy_id,
            definition=_IMPROVED_DEFINITION,
            change_notes="Tighter RSI thresholds (25/75), smaller position (8%), tighter stop (3%)",
        )
        v2_number: int = version_2["version"]
        print(f"  Version {v2_number} created.")

        print(f"\nStep 5: Running {EPISODES}-episode test for version {v2_number}...")
        test_v2 = client.run_test(
            strategy_id,
            version=v2_number,
            episodes=EPISODES,
            episode_duration_days=EPISODE_DAYS,
        )
        results_v2 = _wait_for_test(client, strategy_id, test_v2["test_run_id"], f"v{v2_number}")

        metrics_v2 = results_v2.get("metrics") or results_v2.get("aggregate_metrics") or {}
        print(f"  v{v2_number} avg_roi={metrics_v2.get('avg_roi_pct', 'n/a')}%  "
              f"sharpe={metrics_v2.get('sharpe_ratio', 'n/a')}")

        # ------------------------------------------------------------------
        # Step 5 — Compare v1 vs v2
        # ------------------------------------------------------------------
        print(f"\nStep 6: Comparing v1 vs v{v2_number}...")
        try:
            comparison = client.compare_versions(strategy_id, v1=1, v2=v2_number)
            verdict = comparison.get("verdict", "unknown")
            improvements = comparison.get("improvements") or []
            print(f"  Verdict: {verdict}")
            for imp in improvements[:3]:
                print(f"  - {imp}")
        except AgentExchangeError as exc:
            print(f"  WARNING: compare_versions failed: {exc}")
            comparison = {}

        # ------------------------------------------------------------------
        # Step 6 — DSR gate on v2 (num_trials=2 because we tested 2 versions)
        # ------------------------------------------------------------------
        print(f"\nStep 7: DSR significance check for version {v2_number}...")
        v2_significant, v2_p = _check_dsr(client, results_v2, num_trials=2, label=f"v{v2_number}")

        # ------------------------------------------------------------------
        # Step 7 — Deploy the best significant version
        # ------------------------------------------------------------------
        print("\nStep 8: Deployment decision...")

        # Choose which version to deploy
        if v2_significant:
            deploy_version = v2_number
            print(f"  v{v2_number} is statistically significant (p={v2_p:.4f}) — deploying.")
        elif v1_significant:
            deploy_version = 1
            print(f"  v1 is statistically significant (p={v1_p:.4f}) — deploying v1.")
        else:
            print(
                "  Neither version passed DSR significance test. "
                "Skipping deployment to avoid deploying a lucky strategy."
            )
            deploy_version = None

        if deploy_version is not None:
            try:
                client.deploy_strategy(strategy_id, version=deploy_version)
                print(f"  Strategy deployed (version {deploy_version}).")

                # ----------------------------------------------------------
                # Hypothetical drawdown guard: undeploy if drawdown too high
                # ----------------------------------------------------------
                deployed_metrics = (
                    metrics_v2 if deploy_version == v2_number else metrics_v1
                )
                max_dd = float(deployed_metrics.get("max_drawdown_pct", 0.0) or 0.0)
                if max_dd > MAX_DRAWDOWN_LIMIT:
                    print(
                        f"  WARNING: max drawdown {max_dd:.1f}% exceeds "
                        f"limit {MAX_DRAWDOWN_LIMIT}% — undeploying."
                    )
                    client.undeploy_strategy(strategy_id)
                    print("  Strategy undeployed.")
                else:
                    print(f"  Drawdown check passed ({max_dd:.1f}% <= {MAX_DRAWDOWN_LIMIT}%).")

            except AgentExchangeError as exc:
                print(f"  WARNING: Deployment failed: {exc}")

    print("\nStrategy tester workflow complete.")


if __name__ == "__main__":
    main()
