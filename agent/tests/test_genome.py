"""Tests for agent/strategies/evolutionary/genome.py :: StrategyGenome."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest
from pydantic import ValidationError

from agent.strategies.evolutionary.genome import (
    _INT_LEN,
    _PAIRS_LEN,
    _SCALAR_LEN,
    AVAILABLE_PAIRS,
    INT_BOUNDS,
    SCALAR_BOUNDS,
    VECTOR_LEN,
    StrategyGenome,
)

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

# All 12 named genome parameters (7 scalar + 4 int + 1 list) — used to verify
# round-trip completeness.
ALL_SCALAR_PARAMS = list(SCALAR_BOUNDS.keys())   # 7
ALL_INT_PARAMS = list(INT_BOUNDS.keys())          # 4


# ---------------------------------------------------------------------------
# TestStrategyGenomeDefaults
# ---------------------------------------------------------------------------


class TestStrategyGenomeDefaults:
    """Verify that default construction produces a valid genome."""

    def test_default_construction_succeeds(self) -> None:
        """StrategyGenome() constructs without error using default field values."""
        g = StrategyGenome()
        assert g is not None

    def test_default_pairs_are_valid(self) -> None:
        """Default pairs list is a non-empty subset of AVAILABLE_PAIRS."""
        g = StrategyGenome()
        assert len(g.pairs) >= 1
        for p in g.pairs:
            assert p in AVAILABLE_PAIRS

    def test_default_scalar_params_within_bounds(self) -> None:
        """All scalar default values fall within their declared bounds."""
        g = StrategyGenome()
        for key, (lo, hi) in SCALAR_BOUNDS.items():
            val = getattr(g, key)
            assert lo <= val <= hi, f"{key}={val} not in [{lo}, {hi}]"

    def test_default_int_params_within_bounds(self) -> None:
        """All integer default values fall within their declared bounds."""
        g = StrategyGenome()
        for key, (lo, hi) in INT_BOUNDS.items():
            val = getattr(g, key)
            assert lo <= val <= hi, f"{key}={val} not in [{lo}, {hi}]"


# ---------------------------------------------------------------------------
# TestFromRandom
# ---------------------------------------------------------------------------


class TestFromRandom:
    """Tests for StrategyGenome.from_random()."""

    def test_random_genome_is_within_scalar_bounds(self) -> None:
        """from_random() produces scalar parameters within declared bounds."""
        g = StrategyGenome.from_random(seed=0)
        for key, (lo, hi) in SCALAR_BOUNDS.items():
            val = getattr(g, key)
            assert lo <= val <= hi, f"{key}={val} not in [{lo}, {hi}]"

    def test_random_genome_is_within_int_bounds(self) -> None:
        """from_random() produces integer parameters within declared bounds."""
        g = StrategyGenome.from_random(seed=0)
        for key, (lo, hi) in INT_BOUNDS.items():
            val = getattr(g, key)
            assert lo <= val <= hi, f"{key}={val} not in [{lo}, {hi}]"
            assert isinstance(val, int), f"{key} should be int, got {type(val)}"

    def test_random_genome_has_nonempty_pairs(self) -> None:
        """from_random() always produces at least one active trading pair."""
        for seed in range(20):
            g = StrategyGenome.from_random(seed=seed)
            assert len(g.pairs) >= 1, f"seed={seed} produced empty pairs list"

    def test_random_genome_pairs_are_valid(self) -> None:
        """from_random() only selects pairs from AVAILABLE_PAIRS."""
        g = StrategyGenome.from_random(seed=42)
        for p in g.pairs:
            assert p in AVAILABLE_PAIRS, f"Unknown pair: {p}"

    def test_seeded_random_is_reproducible(self) -> None:
        """Two calls with the same seed produce identical genomes."""
        g1 = StrategyGenome.from_random(seed=99)
        g2 = StrategyGenome.from_random(seed=99)
        assert g1 == g2

    def test_different_seeds_produce_different_genomes(self) -> None:
        """Different seeds generally produce different genomes (statistical check)."""
        genomes = [StrategyGenome.from_random(seed=i) for i in range(10)]
        vectors = [g.to_vector().tolist() for g in genomes]
        # At least half of adjacent pairs should differ
        diffs = sum(1 for i in range(len(vectors) - 1) if vectors[i] != vectors[i + 1])
        assert diffs >= 5, "Too many identical adjacent genomes from different seeds"

    def test_all_12_plus_params_populated(self) -> None:
        """from_random() populates all 7 scalar + 4 int + 1 pairs list fields."""
        g = StrategyGenome.from_random(seed=7)
        # Scalar fields
        for key in ALL_SCALAR_PARAMS:
            assert hasattr(g, key)
            assert getattr(g, key) is not None
        # Integer fields
        for key in ALL_INT_PARAMS:
            assert hasattr(g, key)
            assert getattr(g, key) is not None
        # Pairs list
        assert isinstance(g.pairs, list)
        assert len(g.pairs) >= 1


# ---------------------------------------------------------------------------
# TestVectorRoundTrip
# ---------------------------------------------------------------------------


class TestVectorRoundTrip:
    """Tests for StrategyGenome.to_vector() / from_vector() round-trip."""

    def test_to_vector_length(self) -> None:
        """to_vector() returns a 1-D array of length VECTOR_LEN (17)."""
        g = StrategyGenome.from_random(seed=1)
        vec = g.to_vector()
        assert vec.shape == (VECTOR_LEN,)
        assert vec.dtype == np.float64

    def test_vector_len_is_17(self) -> None:
        """VECTOR_LEN must equal 7 scalars + 4 ints + 6 pair bits = 17."""
        assert VECTOR_LEN == 17
        assert _SCALAR_LEN == 7
        assert _INT_LEN == 4
        assert _PAIRS_LEN == 6

    def test_round_trip_scalar_params(self) -> None:
        """All 7 scalar parameters survive a to_vector → from_vector cycle."""
        g = StrategyGenome.from_random(seed=2)
        vec = g.to_vector()
        g2 = StrategyGenome.from_vector(vec)
        for key in ALL_SCALAR_PARAMS:
            original = getattr(g, key)
            restored = getattr(g2, key)
            assert abs(original - restored) < 1e-9, (
                f"{key}: {original} != {restored}"
            )

    def test_round_trip_int_params(self) -> None:
        """All 4 integer parameters survive a to_vector → from_vector cycle."""
        g = StrategyGenome.from_random(seed=3)
        vec = g.to_vector()
        g2 = StrategyGenome.from_vector(vec)
        for key in ALL_INT_PARAMS:
            assert getattr(g, key) == getattr(g2, key), (
                f"{key}: {getattr(g, key)} != {getattr(g2, key)}"
            )

    def test_round_trip_pairs(self) -> None:
        """Active trading pairs survive a to_vector → from_vector cycle."""
        g = StrategyGenome.from_random(seed=4)
        vec = g.to_vector()
        g2 = StrategyGenome.from_vector(vec)
        assert set(g.pairs) == set(g2.pairs)

    def test_round_trip_all_seeds(self) -> None:
        """Round-trip holds for 15 different seeds — all 12+ parameters checked."""
        for seed in range(15):
            g = StrategyGenome.from_random(seed=seed)
            vec = g.to_vector()
            g2 = StrategyGenome.from_vector(vec)

            # Scalars
            for key in ALL_SCALAR_PARAMS:
                assert abs(getattr(g, key) - getattr(g2, key)) < 1e-9, (
                    f"seed={seed}, {key}: {getattr(g, key)} != {getattr(g2, key)}"
                )
            # Integers
            for key in ALL_INT_PARAMS:
                assert getattr(g, key) == getattr(g2, key), (
                    f"seed={seed}, {key}: {getattr(g, key)} != {getattr(g2, key)}"
                )
            # Pairs
            assert set(g.pairs) == set(g2.pairs), f"seed={seed}: pairs differ"

    def test_pair_mask_encoding(self) -> None:
        """Pair presence mask encodes 1.0 for active pairs, 0.0 for inactive."""
        g = StrategyGenome(pairs=["BTCUSDT"])
        vec = g.to_vector()
        pair_offset = _SCALAR_LEN + _INT_LEN
        btc_idx = AVAILABLE_PAIRS.index("BTCUSDT")
        assert vec[pair_offset + btc_idx] == 1.0
        for k, pair in enumerate(AVAILABLE_PAIRS):
            if pair != "BTCUSDT":
                assert vec[pair_offset + k] == 0.0, f"{pair} should be 0.0"

    def test_from_vector_wrong_length_raises(self) -> None:
        """from_vector() raises ValueError when the vector length is wrong."""
        with pytest.raises(ValueError, match=str(VECTOR_LEN)):
            StrategyGenome.from_vector(np.zeros(10))

    def test_from_vector_too_long_raises(self) -> None:
        """from_vector() raises ValueError for an over-length vector."""
        with pytest.raises(ValueError, match=str(VECTOR_LEN)):
            StrategyGenome.from_vector(np.zeros(VECTOR_LEN + 1))

    def test_from_vector_clips_out_of_bounds_scalars(self) -> None:
        """from_vector() clips scalar values that exceed bounds."""
        vec = StrategyGenome.from_random(seed=0).to_vector()
        # Force rsi_oversold (index 0) way out of its [20, 40] bounds
        vec[0] = 999.0
        g = StrategyGenome.from_vector(vec)
        lo, hi = SCALAR_BOUNDS["rsi_oversold"]
        assert lo <= g.rsi_oversold <= hi

    def test_from_vector_clips_out_of_bounds_ints(self) -> None:
        """from_vector() clips integer values that exceed bounds."""
        vec = StrategyGenome.from_random(seed=0).to_vector()
        # Force macd_fast (index 7) way below its [8, 15] bounds
        vec[_SCALAR_LEN + 0] = -100.0
        g = StrategyGenome.from_vector(vec)
        lo, hi = INT_BOUNDS["macd_fast"]
        assert lo <= g.macd_fast <= hi

    def test_from_vector_all_zeros_pair_mask_falls_back(self) -> None:
        """from_vector() falls back to first pair when pair mask is all zero."""
        vec = StrategyGenome.from_random(seed=0).to_vector()
        pair_offset = _SCALAR_LEN + _INT_LEN
        for k in range(_PAIRS_LEN):
            vec[pair_offset + k] = 0.0
        g = StrategyGenome.from_vector(vec)
        assert len(g.pairs) >= 1
        assert g.pairs[0] == AVAILABLE_PAIRS[0]


# ---------------------------------------------------------------------------
# TestToStrategyDefinition
# ---------------------------------------------------------------------------


class TestToStrategyDefinition:
    """Tests for StrategyGenome.to_strategy_definition()."""

    def test_returns_dict(self) -> None:
        """to_strategy_definition() returns a dict."""
        g = StrategyGenome.from_random(seed=5)
        result = g.to_strategy_definition()
        assert isinstance(result, dict)

    def test_required_top_level_keys_present(self) -> None:
        """All required top-level keys are present in the strategy definition."""
        g = StrategyGenome.from_random(seed=5)
        result = g.to_strategy_definition()
        required_keys = {
            "pairs",
            "timeframe",
            "entry_conditions",
            "exit_conditions",
            "position_size_pct",
            "max_positions",
            "filters",
            "model_type",
        }
        assert required_keys.issubset(result.keys())

    def test_timeframe_is_1h(self) -> None:
        """timeframe is always '1h'."""
        g = StrategyGenome.from_random(seed=5)
        assert g.to_strategy_definition()["timeframe"] == "1h"

    def test_model_type_is_rule_based(self) -> None:
        """model_type is always 'rule_based'."""
        g = StrategyGenome.from_random(seed=5)
        assert g.to_strategy_definition()["model_type"] == "rule_based"

    def test_pairs_round_trip(self) -> None:
        """pairs in the strategy definition matches the genome's pairs list."""
        g = StrategyGenome(pairs=["BTCUSDT", "ETHUSDT"])
        defn = g.to_strategy_definition()
        assert defn["pairs"] == ["BTCUSDT", "ETHUSDT"]

    def test_entry_conditions_keys(self) -> None:
        """entry_conditions contains rsi_below, macd_cross_above, adx_above."""
        g = StrategyGenome.from_random(seed=6)
        ec = g.to_strategy_definition()["entry_conditions"]
        assert "rsi_below" in ec
        assert "macd_cross_above" in ec
        assert "adx_above" in ec

    def test_exit_conditions_keys(self) -> None:
        """exit_conditions contains stop_loss, take_profit, trailing_stop, hold limit."""
        g = StrategyGenome.from_random(seed=6)
        xc = g.to_strategy_definition()["exit_conditions"]
        assert "rsi_above" in xc
        assert "stop_loss_pct" in xc
        assert "take_profit_pct" in xc
        assert "trailing_stop_pct" in xc
        assert "max_hold_candles" in xc

    def test_filters_contain_macd_periods(self) -> None:
        """filters contains macd_fast and macd_slow."""
        g = StrategyGenome.from_random(seed=6)
        filters = g.to_strategy_definition()["filters"]
        assert "macd_fast" in filters
        assert "macd_slow" in filters

    def test_position_size_pct_is_string_decimal(self) -> None:
        """position_size_pct in the definition is a string representing a Decimal."""
        g = StrategyGenome(position_size_pct=0.10)
        defn = g.to_strategy_definition()
        psp = defn["position_size_pct"]
        assert isinstance(psp, str)
        # Should be parseable as a Decimal
        Decimal(psp)

    def test_position_size_conversion_10_pct(self) -> None:
        """position_size_pct=0.10 converts to '10' in the definition."""
        g = StrategyGenome(position_size_pct=0.10)
        defn = g.to_strategy_definition()
        assert Decimal(defn["position_size_pct"]) == Decimal("10")

    def test_position_size_conversion_5_pct(self) -> None:
        """position_size_pct=0.05 converts to '5' in the definition."""
        g = StrategyGenome(position_size_pct=0.05)
        defn = g.to_strategy_definition()
        assert Decimal(defn["position_size_pct"]) == Decimal("5")

    def test_stop_loss_converted_to_percentage(self) -> None:
        """stop_loss_pct=0.02 (2% ratio) becomes 2.0 in exit_conditions."""
        g = StrategyGenome(stop_loss_pct=0.02)
        xc = g.to_strategy_definition()["exit_conditions"]
        assert abs(xc["stop_loss_pct"] - 2.0) < 1e-9

    def test_take_profit_converted_to_percentage(self) -> None:
        """take_profit_pct=0.04 (4% ratio) becomes 4.0 in exit_conditions."""
        g = StrategyGenome(take_profit_pct=0.04)
        xc = g.to_strategy_definition()["exit_conditions"]
        assert abs(xc["take_profit_pct"] - 4.0) < 1e-9

    def test_rsi_oversold_maps_to_entry_rsi_below(self) -> None:
        """rsi_oversold is mapped to entry_conditions.rsi_below."""
        g = StrategyGenome(rsi_oversold=28.0)
        ec = g.to_strategy_definition()["entry_conditions"]
        assert abs(ec["rsi_below"] - 28.0) < 1e-9

    def test_rsi_overbought_maps_to_exit_rsi_above(self) -> None:
        """rsi_overbought is mapped to exit_conditions.rsi_above."""
        g = StrategyGenome(rsi_overbought=75.0)
        xc = g.to_strategy_definition()["exit_conditions"]
        assert abs(xc["rsi_above"] - 75.0) < 1e-9

    def test_max_positions_preserved(self) -> None:
        """max_positions is preserved as-is in the strategy definition."""
        for val in (1, 3, 5):
            g = StrategyGenome(max_positions=val)
            assert g.to_strategy_definition()["max_positions"] == val

    def test_strategy_definition_genome_round_trip(self) -> None:
        """to_strategy_definition round-trips correctly for random seeds."""
        for seed in range(10):
            g = StrategyGenome.from_random(seed=seed)
            defn = g.to_strategy_definition()
            # Verify all expected fields are present and non-null
            assert defn["pairs"]
            assert defn["entry_conditions"]["rsi_below"] is not None
            assert defn["exit_conditions"]["stop_loss_pct"] is not None
            assert defn["filters"]["macd_fast"] is not None


# ---------------------------------------------------------------------------
# TestInvalidBounds
# ---------------------------------------------------------------------------


class TestInvalidBounds:
    """Tests that out-of-bound values raise validation errors."""

    def test_rsi_oversold_below_min_raises(self) -> None:
        """rsi_oversold < 20 is rejected by Pydantic validation."""
        with pytest.raises(ValidationError):
            StrategyGenome(rsi_oversold=19.9)

    def test_rsi_oversold_above_max_raises(self) -> None:
        """rsi_oversold > 40 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(rsi_oversold=40.1)

    def test_rsi_overbought_below_min_raises(self) -> None:
        """rsi_overbought < 60 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(rsi_overbought=59.9)

    def test_rsi_overbought_above_max_raises(self) -> None:
        """rsi_overbought > 80 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(rsi_overbought=80.1)

    def test_macd_fast_below_min_raises(self) -> None:
        """macd_fast < 8 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(macd_fast=7)

    def test_macd_fast_above_max_raises(self) -> None:
        """macd_fast > 15 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(macd_fast=16)

    def test_macd_slow_below_min_raises(self) -> None:
        """macd_slow < 20 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(macd_slow=19)

    def test_macd_slow_above_max_raises(self) -> None:
        """macd_slow > 30 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(macd_slow=31)

    def test_stop_loss_below_min_raises(self) -> None:
        """stop_loss_pct < 0.01 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(stop_loss_pct=0.009)

    def test_stop_loss_above_max_raises(self) -> None:
        """stop_loss_pct > 0.05 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(stop_loss_pct=0.051)

    def test_take_profit_below_min_raises(self) -> None:
        """take_profit_pct < 0.02 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(take_profit_pct=0.019)

    def test_take_profit_above_max_raises(self) -> None:
        """take_profit_pct > 0.10 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(take_profit_pct=0.101)

    def test_position_size_below_min_raises(self) -> None:
        """position_size_pct < 0.03 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(position_size_pct=0.029)

    def test_position_size_above_max_raises(self) -> None:
        """position_size_pct > 0.20 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(position_size_pct=0.201)

    def test_max_hold_candles_below_min_raises(self) -> None:
        """max_hold_candles < 10 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(max_hold_candles=9)

    def test_max_hold_candles_above_max_raises(self) -> None:
        """max_hold_candles > 200 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(max_hold_candles=201)

    def test_max_positions_below_min_raises(self) -> None:
        """max_positions < 1 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(max_positions=0)

    def test_max_positions_above_max_raises(self) -> None:
        """max_positions > 5 is rejected."""
        with pytest.raises(ValidationError):
            StrategyGenome(max_positions=6)

    def test_empty_pairs_rejected_by_field_constraint(self) -> None:
        """An empty pairs list is rejected by Pydantic's min_length=1 constraint.

        The _validate_pairs fallback only applies after field validation; an
        empty list never reaches the validator because min_length=1 fires first.
        """
        with pytest.raises(ValidationError):
            StrategyGenome(pairs=[])

    def test_invalid_pair_names_are_filtered(self) -> None:
        """Unrecognised pair names are silently filtered out."""
        g = StrategyGenome(pairs=["FAKECOIN", "BTCUSDT"])
        assert "FAKECOIN" not in g.pairs
        assert "BTCUSDT" in g.pairs

    def test_all_invalid_pairs_fall_back(self) -> None:
        """If all supplied pairs are invalid, fallback to first AVAILABLE_PAIRS."""
        g = StrategyGenome(pairs=["INVALID1", "INVALID2"])
        assert g.pairs == [AVAILABLE_PAIRS[0]]

    def test_duplicate_pairs_deduplicated(self) -> None:
        """Duplicate pair entries are removed."""
        g = StrategyGenome(pairs=["BTCUSDT", "BTCUSDT", "ETHUSDT"])
        assert g.pairs.count("BTCUSDT") == 1
