"""Unit tests for strategy comparison — StrategyService.compare_strategies() and helpers.

Covers:
- Ranking by sharpe_ratio (default)
- Ranking by win_rate and roi_pct
- 2-strategy comparison
- 10-strategy comparison
- Invalid strategy ID raises StrategyNotFoundError
- DSR included when available in test results
- DSR omitted when not available or malformed
- Recommendation text content and format
- Strategies with no test results ranked last
- max_drawdown_pct lower-is-better ordering
- _build_recommendation helper directly
- StrategyComparisonRequest schema validation (< 2 strategies, invalid metric)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from pydantic import ValidationError
import pytest

from src.api.schemas.strategies import StrategyComparisonRequest
from src.strategies.service import StrategyService, _build_recommendation
from src.utils.exceptions import StrategyNotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strategy(*, strategy_id=None, account_id=None, name="Test Strategy", status="validated", version=1):
    """Build a minimal mock Strategy ORM object."""
    s = MagicMock()
    s.id = strategy_id or uuid4()
    s.account_id = account_id or uuid4()
    s.name = name
    s.current_version = version
    s.status = status
    s.deployed_at = None
    s.created_at = MagicMock()
    s.updated_at = MagicMock()
    return s


def _make_test_run(results: dict | None):
    """Build a mock StrategyTestRun with the given results dict."""
    run = MagicMock()
    run.results = results
    return run


def _make_repo_for_strategies(strategies_and_runs: list[tuple]) -> AsyncMock:
    """Build a mocked StrategyRepository from (strategy, test_run | None) pairs.

    ``get_by_id`` is wired to return the matching strategy, and
    ``get_latest_results`` is wired to return the paired test run (or None).
    """
    repo = AsyncMock()

    by_id: dict = {}
    latest_results: dict = {}

    for strategy, test_run in strategies_and_runs:
        by_id[strategy.id] = strategy
        latest_results[strategy.id] = test_run

    async def _get_by_id(sid):
        if sid not in by_id:
            raise StrategyNotFoundError(
                message=f"Strategy {sid} not found.",
                strategy_id=sid,
            )
        return by_id[sid]

    async def _get_latest_results(sid):
        return latest_results.get(sid)

    repo.get_by_id.side_effect = _get_by_id
    repo.get_latest_results.side_effect = _get_latest_results
    return repo


def _make_service(repo: AsyncMock) -> StrategyService:
    return StrategyService(repo)


# ---------------------------------------------------------------------------
# Tests: ranking by sharpe_ratio (default)
# ---------------------------------------------------------------------------


class TestRankingBySharpeRatio:
    """Strategies are ranked by sharpe_ratio descending when using the default metric."""

    async def test_two_strategies_ranked_correctly(self):
        """Strategy with higher sharpe_ratio gets rank=1."""
        s1 = _make_strategy(name="Alpha")
        s2 = _make_strategy(name="Beta")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 1.2, "roi_pct": 10.0})),
                (s2, _make_test_run({"sharpe_ratio": 2.5, "roi_pct": 20.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id], ranking_metric="sharpe_ratio")

        entries = result["strategies"]
        assert len(entries) == 2
        # Higher sharpe_ratio = lower rank number (better)
        assert entries[0]["name"] == "Beta"
        assert entries[0]["rank"] == 1
        assert entries[1]["name"] == "Alpha"
        assert entries[1]["rank"] == 2

    async def test_winner_id_matches_best_strategy(self):
        """winner_id is the UUID of the strategy ranked first."""
        s1 = _make_strategy(name="Alpha")
        s2 = _make_strategy(name="Beta")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 0.5})),
                (s2, _make_test_run({"sharpe_ratio": 3.1})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert result["winner_id"] == str(s2.id)

    async def test_ranking_metric_echoed_in_response(self):
        """The ranking_metric key in the response matches the requested metric."""
        s1 = _make_strategy()
        s2 = _make_strategy()
        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 1.0})),
                (s2, _make_test_run({"sharpe_ratio": 2.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id], ranking_metric="sharpe_ratio")

        assert result["ranking_metric"] == "sharpe_ratio"


# ---------------------------------------------------------------------------
# Tests: ranking by other metrics
# ---------------------------------------------------------------------------


class TestRankingByOtherMetrics:
    """Strategies can be ranked by win_rate, roi_pct, sortino_ratio, profit_factor."""

    async def test_ranking_by_win_rate(self):
        """Strategies are sorted by win_rate descending when ranking_metric='win_rate'."""
        s1 = _make_strategy(name="LowWin")
        s2 = _make_strategy(name="HighWin")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"win_rate": 0.40, "sharpe_ratio": 1.5})),
                (s2, _make_test_run({"win_rate": 0.72, "sharpe_ratio": 0.8})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id], ranking_metric="win_rate")

        entries = result["strategies"]
        assert entries[0]["name"] == "HighWin"
        assert entries[0]["rank"] == 1
        assert result["ranking_metric"] == "win_rate"

    async def test_ranking_by_roi_pct(self):
        """Strategies are sorted by roi_pct descending when ranking_metric='roi_pct'."""
        s1 = _make_strategy(name="Low ROI")
        s2 = _make_strategy(name="High ROI")
        s3 = _make_strategy(name="Mid ROI")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"roi_pct": 5.0})),
                (s2, _make_test_run({"roi_pct": 42.0})),
                (s3, _make_test_run({"roi_pct": 18.5})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id, s3.id], ranking_metric="roi_pct")

        entries = result["strategies"]
        assert entries[0]["name"] == "High ROI"
        assert entries[1]["name"] == "Mid ROI"
        assert entries[2]["name"] == "Low ROI"

    async def test_ranking_by_max_drawdown_lower_is_better(self):
        """max_drawdown_pct is lower-is-better: smallest drawdown gets rank=1."""
        s1 = _make_strategy(name="BadDrawdown")
        s2 = _make_strategy(name="GoodDrawdown")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"max_drawdown_pct": 35.0})),
                (s2, _make_test_run({"max_drawdown_pct": 8.5})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id], ranking_metric="max_drawdown_pct")

        entries = result["strategies"]
        assert entries[0]["name"] == "GoodDrawdown"
        assert entries[0]["rank"] == 1

    async def test_ranking_by_profit_factor(self):
        """Strategies are sorted by profit_factor descending."""
        s1 = _make_strategy(name="Low PF")
        s2 = _make_strategy(name="High PF")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"profit_factor": 1.2})),
                (s2, _make_test_run({"profit_factor": 2.8})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id], ranking_metric="profit_factor")

        assert result["strategies"][0]["name"] == "High PF"


# ---------------------------------------------------------------------------
# Tests: 2-strategy comparison
# ---------------------------------------------------------------------------


class TestTwoStrategyComparison:
    """Minimum valid comparison with exactly 2 strategies."""

    async def test_returns_two_entries(self):
        """Response contains exactly 2 strategy entries."""
        s1 = _make_strategy(name="A")
        s2 = _make_strategy(name="B")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 1.0})),
                (s2, _make_test_run({"sharpe_ratio": 2.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert len(result["strategies"]) == 2

    async def test_ranks_are_1_and_2(self):
        """Ranks are exactly 1 and 2 with no gaps or duplicates."""
        s1 = _make_strategy(name="X")
        s2 = _make_strategy(name="Y")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 0.5})),
                (s2, _make_test_run({"sharpe_ratio": 1.5})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        ranks = {e["rank"] for e in result["strategies"]}
        assert ranks == {1, 2}

    async def test_has_test_results_flag_set_correctly(self):
        """has_test_results is True for strategies with a test run."""
        s1 = _make_strategy()
        s2 = _make_strategy()

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 1.0})),
                (s2, _make_test_run({"sharpe_ratio": 2.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        for entry in result["strategies"]:
            assert entry["has_test_results"] is True


# ---------------------------------------------------------------------------
# Tests: 10-strategy comparison
# ---------------------------------------------------------------------------


class TestTenStrategyComparison:
    """Maximum valid comparison with exactly 10 strategies."""

    async def test_ranks_are_1_through_10(self):
        """Ranks for 10 strategies are exactly 1 through 10, all distinct."""
        strategies = [_make_strategy(name=f"S{i}") for i in range(10)]
        pairs = [
            (s, _make_test_run({"sharpe_ratio": float(i) * 0.5}))
            for i, s in enumerate(strategies)
        ]
        repo = _make_repo_for_strategies(pairs)
        service = _make_service(repo)

        result = await service.compare_strategies(
            [s.id for s in strategies], ranking_metric="sharpe_ratio"
        )

        ranks = [e["rank"] for e in result["strategies"]]
        assert sorted(ranks) == list(range(1, 11))

    async def test_best_sharpe_is_rank_1(self):
        """The strategy with the highest sharpe_ratio is ranked first among 10."""
        strategies = [_make_strategy(name=f"S{i}") for i in range(10)]
        # Strategy at index 7 has the highest sharpe_ratio
        sharpe_values = [0.1, 0.3, 0.5, 0.7, 0.9, 1.1, 1.3, 9.9, 0.2, 0.4]
        pairs = [
            (s, _make_test_run({"sharpe_ratio": sharpe_values[i]}))
            for i, s in enumerate(strategies)
        ]
        repo = _make_repo_for_strategies(pairs)
        service = _make_service(repo)

        result = await service.compare_strategies(
            [s.id for s in strategies], ranking_metric="sharpe_ratio"
        )

        assert result["strategies"][0]["name"] == "S7"
        assert result["winner_id"] == str(strategies[7].id)

    async def test_all_entries_present_with_metrics(self):
        """All 10 entries appear in the response with populated metrics dicts."""
        strategies = [_make_strategy(name=f"S{i}") for i in range(10)]
        pairs = [
            (s, _make_test_run({"sharpe_ratio": float(i), "roi_pct": float(i * 2)}))
            for i, s in enumerate(strategies)
        ]
        repo = _make_repo_for_strategies(pairs)
        service = _make_service(repo)

        result = await service.compare_strategies([s.id for s in strategies])

        assert len(result["strategies"]) == 10
        for entry in result["strategies"]:
            assert "metrics" in entry
            assert "sharpe_ratio" in entry["metrics"]


# ---------------------------------------------------------------------------
# Tests: invalid strategy ID raises StrategyNotFoundError
# ---------------------------------------------------------------------------


class TestInvalidStrategyId:
    """compare_strategies propagates StrategyNotFoundError for unknown IDs."""

    async def test_unknown_id_raises_not_found(self):
        """Passing a strategy ID that doesn't exist raises StrategyNotFoundError."""
        s1 = _make_strategy(name="Known")
        unknown_id = uuid4()

        repo = _make_repo_for_strategies(
            [(s1, _make_test_run({"sharpe_ratio": 1.0}))]
        )
        service = _make_service(repo)

        with pytest.raises(StrategyNotFoundError):
            await service.compare_strategies([s1.id, unknown_id])

    async def test_error_message_contains_strategy_id(self):
        """StrategyNotFoundError carries the unknown strategy_id."""
        unknown_id = uuid4()
        s1 = _make_strategy()

        repo = _make_repo_for_strategies(
            [(s1, _make_test_run({"sharpe_ratio": 1.0}))]
        )
        service = _make_service(repo)

        with pytest.raises(StrategyNotFoundError) as exc_info:
            await service.compare_strategies([s1.id, unknown_id])

        # The exception should reference the missing strategy
        assert exc_info.value.http_status == 404


# ---------------------------------------------------------------------------
# Tests: strategies with no test results
# ---------------------------------------------------------------------------


class TestNoTestResults:
    """Strategies without completed test runs are included but ranked last."""

    async def test_strategy_without_results_ranked_last(self):
        """A strategy with no test run is ranked below one with results."""
        s_with = _make_strategy(name="HasResults")
        s_without = _make_strategy(name="NoResults")

        repo = _make_repo_for_strategies(
            [
                (s_with, _make_test_run({"sharpe_ratio": 1.5})),
                (s_without, None),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s_with.id, s_without.id])

        entries = result["strategies"]
        # HasResults must come before NoResults
        names_in_order = [e["name"] for e in entries]
        assert names_in_order.index("HasResults") < names_in_order.index("NoResults")

    async def test_strategy_without_results_has_flag_false(self):
        """has_test_results=False when no test run exists for a strategy."""
        s_with = _make_strategy(name="HasResults")
        s_without = _make_strategy(name="NoResults")

        repo = _make_repo_for_strategies(
            [
                (s_with, _make_test_run({"sharpe_ratio": 2.0})),
                (s_without, None),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s_with.id, s_without.id])

        no_result_entry = next(e for e in result["strategies"] if e["name"] == "NoResults")
        assert no_result_entry["has_test_results"] is False

    async def test_winner_id_none_when_all_lack_results(self):
        """winner_id is None when every strategy in the comparison has no test run."""
        s1 = _make_strategy(name="A")
        s2 = _make_strategy(name="B")

        repo = _make_repo_for_strategies(
            [(s1, None), (s2, None)]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert result["winner_id"] is None

    async def test_both_strategies_without_results_still_ranked(self):
        """Both strategies without results receive distinct ranks (no winner)."""
        s1 = _make_strategy(name="A")
        s2 = _make_strategy(name="B")

        repo = _make_repo_for_strategies(
            [(s1, None), (s2, None)]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        ranks = {e["rank"] for e in result["strategies"]}
        assert ranks == {1, 2}


# ---------------------------------------------------------------------------
# Tests: DSR included when available
# ---------------------------------------------------------------------------


class TestDSRIncluded:
    """deflated_sharpe data is populated when valid DSR fields are in test results."""

    async def test_dsr_fields_populated(self):
        """All DSR fields are present and correctly extracted."""
        s = _make_strategy()
        repo = _make_repo_for_strategies(
            [
                (
                    s,
                    _make_test_run(
                        {
                            "sharpe_ratio": 1.8,
                            "deflated_sharpe": {
                                "p_value": 0.97,
                                "is_significant": True,
                                "observed_sharpe": 1.8,
                                "deflated_sharpe": 1.62,
                                "num_trials": 50,
                            },
                        }
                    ),
                )
            ]
        )
        s2 = _make_strategy(name="Other")
        repo.get_by_id.side_effect = None
        # Re-build repo to include a second strategy so min 2 IDs are passed
        repo2 = _make_repo_for_strategies(
            [
                (
                    s,
                    _make_test_run(
                        {
                            "sharpe_ratio": 1.8,
                            "deflated_sharpe": {
                                "p_value": 0.97,
                                "is_significant": True,
                                "observed_sharpe": 1.8,
                                "deflated_sharpe": 1.62,
                                "num_trials": 50,
                            },
                        }
                    ),
                ),
                (s2, _make_test_run({"sharpe_ratio": 0.5})),
            ]
        )
        service = _make_service(repo2)

        result = await service.compare_strategies([s.id, s2.id])

        winner_entry = next(e for e in result["strategies"] if e["strategy_id"] == str(s.id))
        dsr = winner_entry["deflated_sharpe"]
        assert dsr is not None
        assert dsr["p_value"] == pytest.approx(0.97)
        assert dsr["is_significant"] is True
        assert dsr["observed_sharpe"] == pytest.approx(1.8)
        assert dsr["deflated_sharpe"] == pytest.approx(1.62)
        assert dsr["num_trials"] == 50

    async def test_dsr_significant_true_included_in_recommendation(self):
        """Recommendation text mentions 'passes the Deflated Sharpe test' for significant DSR."""
        s1 = _make_strategy(name="TopStrategy")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (
                    s1,
                    _make_test_run(
                        {
                            "sharpe_ratio": 2.5,
                            "deflated_sharpe": {
                                "p_value": 0.96,
                                "is_significant": True,
                                "observed_sharpe": 2.5,
                                "deflated_sharpe": 2.1,
                                "num_trials": 30,
                            },
                        }
                    ),
                ),
                (s2, _make_test_run({"sharpe_ratio": 1.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert "passes" in result["recommendation"]
        assert "Deflated Sharpe" in result["recommendation"]

    async def test_dsr_not_significant_reflected_in_recommendation(self):
        """Recommendation text mentions 'fails the Deflated Sharpe test' for non-significant DSR."""
        s1 = _make_strategy(name="TopStrategy")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (
                    s1,
                    _make_test_run(
                        {
                            "sharpe_ratio": 2.0,
                            "deflated_sharpe": {
                                "p_value": 0.60,
                                "is_significant": False,
                                "observed_sharpe": 2.0,
                                "deflated_sharpe": 1.4,
                                "num_trials": 100,
                            },
                        }
                    ),
                ),
                (s2, _make_test_run({"sharpe_ratio": 0.8})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert "fails" in result["recommendation"]


# ---------------------------------------------------------------------------
# Tests: DSR omitted when not available or malformed
# ---------------------------------------------------------------------------


class TestDSROmitted:
    """deflated_sharpe is None when not present in results or when data is malformed."""

    async def test_dsr_none_when_not_in_results(self):
        """deflated_sharpe is None when the test run has no 'deflated_sharpe' key."""
        s1 = _make_strategy(name="NoDSR")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 1.5, "roi_pct": 10.0})),
                (s2, _make_test_run({"sharpe_ratio": 0.5})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        no_dsr_entry = next(e for e in result["strategies"] if e["strategy_id"] == str(s1.id))
        assert no_dsr_entry["deflated_sharpe"] is None

    async def test_dsr_none_when_malformed_missing_key(self):
        """deflated_sharpe is None when required DSR fields (e.g. p_value) are absent."""
        s1 = _make_strategy(name="MalformedDSR")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (
                    s1,
                    _make_test_run(
                        {
                            "sharpe_ratio": 1.5,
                            "deflated_sharpe": {
                                # Missing 'p_value', 'is_significant', etc.
                                "observed_sharpe": 1.5,
                            },
                        }
                    ),
                ),
                (s2, _make_test_run({"sharpe_ratio": 0.5})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        malformed_entry = next(e for e in result["strategies"] if e["strategy_id"] == str(s1.id))
        assert malformed_entry["deflated_sharpe"] is None

    async def test_dsr_none_when_not_a_dict(self):
        """deflated_sharpe is None when the value is a non-dict type (e.g. a string)."""
        s1 = _make_strategy(name="BadDSRType")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (
                    s1,
                    _make_test_run({"sharpe_ratio": 1.5, "deflated_sharpe": "not_a_dict"}),
                ),
                (s2, _make_test_run({"sharpe_ratio": 0.5})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        bad_entry = next(e for e in result["strategies"] if e["strategy_id"] == str(s1.id))
        assert bad_entry["deflated_sharpe"] is None

    async def test_recommendation_contains_no_dsr_clause_when_absent(self):
        """Recommendation says 'has no Deflated Sharpe data' when DSR is absent."""
        s1 = _make_strategy(name="Winner")
        s2 = _make_strategy(name="Loser")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 3.0})),
                (s2, _make_test_run({"sharpe_ratio": 1.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert "no Deflated Sharpe data" in result["recommendation"]


# ---------------------------------------------------------------------------
# Tests: recommendation text format
# ---------------------------------------------------------------------------


class TestRecommendationTextFormat:
    """Recommendation string structure is correct in all cases."""

    async def test_recommendation_names_winner(self):
        """Recommendation includes the winner strategy's name."""
        s1 = _make_strategy(name="MySuperStrategy")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 5.0})),
                (s2, _make_test_run({"sharpe_ratio": 1.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert "MySuperStrategy" in result["recommendation"]

    async def test_recommendation_mentions_metric_name(self):
        """Recommendation text includes the name of the ranking metric."""
        s1 = _make_strategy(name="A")
        s2 = _make_strategy(name="B")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"roi_pct": 50.0})),
                (s2, _make_test_run({"roi_pct": 20.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id], ranking_metric="roi_pct")

        assert "roi_pct" in result["recommendation"]

    async def test_recommendation_includes_metric_value(self):
        """Recommendation text includes the formatted metric value of the winner."""
        s1 = _make_strategy(name="A")
        s2 = _make_strategy(name="B")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 2.1234})),
                (s2, _make_test_run({"sharpe_ratio": 1.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        # Value is formatted to 4 decimal places
        assert "2.1234" in result["recommendation"]

    async def test_recommendation_ends_with_consider_deploying(self):
        """Recommendation ends with 'Consider deploying.' when a winner exists."""
        s1 = _make_strategy(name="A")
        s2 = _make_strategy(name="B")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 3.0})),
                (s2, _make_test_run({"sharpe_ratio": 1.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert result["recommendation"].endswith("Consider deploying.")

    async def test_recommendation_when_no_results(self):
        """Recommendation asks user to run tests when no strategies have results."""
        s1 = _make_strategy()
        s2 = _make_strategy()

        repo = _make_repo_for_strategies(
            [(s1, None), (s2, None)]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        assert "Run tests before comparing" in result["recommendation"]


# ---------------------------------------------------------------------------
# Tests: _build_recommendation helper (unit tests for the function directly)
# ---------------------------------------------------------------------------


class TestBuildRecommendation:
    """Direct unit tests for the _build_recommendation module-level helper."""

    def test_no_winner_returns_fallback_message(self):
        """None winner_entry returns the 'no results' fallback message."""
        recommendation = _build_recommendation(winner_entry=None, ranking_metric="sharpe_ratio")
        assert "No strategies have completed test results" in recommendation
        assert "Run tests before comparing" in recommendation

    def test_winner_with_dsr_passes(self):
        """Winner with significant DSR produces 'passes' recommendation."""
        winner = {
            "name": "MyStrategy",
            "metrics": {"sharpe_ratio": 2.5},
            "deflated_sharpe": {
                "is_significant": True,
                "p_value": 0.97,
            },
        }
        rec = _build_recommendation(winner_entry=winner, ranking_metric="sharpe_ratio")
        assert "MyStrategy" in rec
        assert "sharpe_ratio" in rec
        assert "2.5000" in rec
        assert "passes" in rec
        assert "p=0.9700" in rec

    def test_winner_with_dsr_fails(self):
        """Winner with non-significant DSR produces 'fails' recommendation."""
        winner = {
            "name": "MyStrategy",
            "metrics": {"sharpe_ratio": 1.8},
            "deflated_sharpe": {
                "is_significant": False,
                "p_value": 0.55,
            },
        }
        rec = _build_recommendation(winner_entry=winner, ranking_metric="sharpe_ratio")
        assert "fails" in rec
        assert "p=0.5500" in rec

    def test_winner_without_dsr(self):
        """Winner with no DSR produces 'has no Deflated Sharpe data' clause."""
        winner = {
            "name": "MyStrategy",
            "metrics": {"sharpe_ratio": 1.8},
            "deflated_sharpe": None,
        }
        rec = _build_recommendation(winner_entry=winner, ranking_metric="sharpe_ratio")
        assert "has no Deflated Sharpe data" in rec
        assert "Consider deploying." in rec

    def test_winner_with_none_metric_value(self):
        """Winner with None metric value shows 'N/A' in recommendation."""
        winner = {
            "name": "NoSharpe",
            "metrics": {"roi_pct": None},
            "deflated_sharpe": None,
        }
        rec = _build_recommendation(winner_entry=winner, ranking_metric="roi_pct")
        assert "N/A" in rec


# ---------------------------------------------------------------------------
# Tests: StrategyComparisonRequest schema validation (< 2 strategies, invalid metric)
# ---------------------------------------------------------------------------


class TestStrategyComparisonRequestSchema:
    """Pydantic schema-level validation for StrategyComparisonRequest."""

    def test_fewer_than_two_strategy_ids_raises_validation_error(self):
        """Providing only 1 strategy_id raises a Pydantic ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            StrategyComparisonRequest(
                strategy_ids=[uuid4()],
                ranking_metric="sharpe_ratio",
            )
        errors = exc_info.value.errors()
        # Should have at least one error on strategy_ids
        assert any(err["loc"][0] == "strategy_ids" for err in errors)

    def test_zero_strategy_ids_raises_validation_error(self):
        """Empty strategy_ids list raises a Pydantic ValidationError."""
        with pytest.raises(ValidationError):
            StrategyComparisonRequest(
                strategy_ids=[],
                ranking_metric="sharpe_ratio",
            )

    def test_more_than_ten_strategy_ids_raises_validation_error(self):
        """Providing 11 strategy_ids exceeds the max_length=10 constraint."""
        with pytest.raises(ValidationError) as exc_info:
            StrategyComparisonRequest(
                strategy_ids=[uuid4() for _ in range(11)],
                ranking_metric="sharpe_ratio",
            )
        errors = exc_info.value.errors()
        assert any(err["loc"][0] == "strategy_ids" for err in errors)

    def test_invalid_ranking_metric_raises_validation_error(self):
        """An unsupported ranking_metric raises a Pydantic ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            StrategyComparisonRequest(
                strategy_ids=[uuid4(), uuid4()],
                ranking_metric="invalid_metric",
            )

    def test_valid_request_with_two_ids(self):
        """Valid request with 2 strategy_ids and default metric constructs successfully."""
        req = StrategyComparisonRequest(
            strategy_ids=[uuid4(), uuid4()],
        )
        assert req.ranking_metric == "sharpe_ratio"
        assert len(req.strategy_ids) == 2

    def test_valid_request_with_all_supported_metrics(self):
        """All documented ranking metrics are accepted by the schema."""
        valid_metrics = [
            "sharpe_ratio",
            "max_drawdown_pct",
            "win_rate",
            "roi_pct",
            "sortino_ratio",
            "profit_factor",
        ]
        for metric in valid_metrics:
            req = StrategyComparisonRequest(
                strategy_ids=[uuid4(), uuid4()],
                ranking_metric=metric,
            )
            assert req.ranking_metric == metric

    def test_valid_request_with_ten_ids(self):
        """Exactly 10 strategy_ids is accepted (the maximum)."""
        req = StrategyComparisonRequest(
            strategy_ids=[uuid4() for _ in range(10)],
            ranking_metric="roi_pct",
        )
        assert len(req.strategy_ids) == 10


# ---------------------------------------------------------------------------
# Tests: metrics extraction from results dict
# ---------------------------------------------------------------------------


class TestMetricsExtraction:
    """Metrics are correctly extracted from the test run results JSONB blob."""

    async def test_all_metrics_populated_from_results(self):
        """All metric fields are populated when the test run contains them."""
        s1 = _make_strategy(name="Full")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (
                    s1,
                    _make_test_run(
                        {
                            "sharpe_ratio": 1.5,
                            "sortino_ratio": 2.1,
                            "max_drawdown_pct": 12.5,
                            "win_rate": 0.65,
                            "roi_pct": 35.0,
                            "profit_factor": 1.8,
                            "total_trades": 120,
                        }
                    ),
                ),
                (s2, _make_test_run({"sharpe_ratio": 0.5})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        full_entry = next(e for e in result["strategies"] if e["strategy_id"] == str(s1.id))
        m = full_entry["metrics"]
        assert m["sharpe_ratio"] == pytest.approx(1.5)
        assert m["sortino_ratio"] == pytest.approx(2.1)
        assert m["max_drawdown_pct"] == pytest.approx(12.5)
        assert m["win_rate"] == pytest.approx(0.65)
        assert m["roi_pct"] == pytest.approx(35.0)
        assert m["profit_factor"] == pytest.approx(1.8)
        assert m["total_trades"] == 120

    async def test_missing_metrics_are_none(self):
        """Metrics not in the test run results are None rather than raising an error."""
        s1 = _make_strategy(name="Partial")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": 1.0})),
                (s2, _make_test_run({"sharpe_ratio": 0.5})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        partial_entry = next(e for e in result["strategies"] if e["strategy_id"] == str(s1.id))
        m = partial_entry["metrics"]
        assert m["sortino_ratio"] is None
        assert m["max_drawdown_pct"] is None
        assert m["win_rate"] is None
        assert m["roi_pct"] is None
        assert m["profit_factor"] is None
        assert m["total_trades"] is None

    async def test_non_numeric_metric_value_becomes_none(self):
        """Non-numeric values in the results blob are safely coerced to None."""
        s1 = _make_strategy(name="BadData")
        s2 = _make_strategy(name="Other")

        repo = _make_repo_for_strategies(
            [
                (s1, _make_test_run({"sharpe_ratio": "not_a_float"})),
                (s2, _make_test_run({"sharpe_ratio": 1.0})),
            ]
        )
        service = _make_service(repo)

        result = await service.compare_strategies([s1.id, s2.id])

        bad_entry = next(e for e in result["strategies"] if e["strategy_id"] == str(s1.id))
        assert bad_entry["metrics"]["sharpe_ratio"] is None
