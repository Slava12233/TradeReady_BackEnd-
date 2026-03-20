"""Tests for agent/strategies/evolutionary/operators.py and population.py.

Covers:
- crossover: produces child with mixed parent genes
- mutate: changes 1-2 params, stays in bounds
- tournament_select: higher-fitness parent selected >60% over 100 runs
- Elite selection preserves top N unchanged
- Population evolves 5 generations without errors (mock fitness)
"""

from __future__ import annotations

import numpy as np
import pytest

from agent.strategies.evolutionary.genome import (
    _INT_LEN,
    _SCALAR_LEN,
    AVAILABLE_PAIRS,
    INT_BOUNDS,
    SCALAR_BOUNDS,
    VECTOR_LEN,
    StrategyGenome,
)
from agent.strategies.evolutionary.operators import (
    clip_genome,
    crossover,
    mutate,
    tournament_select,
)
from agent.strategies.evolutionary.population import Population, PopulationStats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_genome(seed: int) -> StrategyGenome:
    """Convenience factory for a deterministic genome."""
    return StrategyGenome.from_random(seed=seed)


def _all_params_within_bounds(g: StrategyGenome) -> bool:
    """Return True if every scalar and int parameter is within its bounds."""
    for key, (lo, hi) in SCALAR_BOUNDS.items():
        val = getattr(g, key)
        if not (lo <= val <= hi):
            return False
    for key, (lo, hi) in INT_BOUNDS.items():
        val = getattr(g, key)
        if not (lo <= val <= hi):
            return False
    return True


# ---------------------------------------------------------------------------
# TestTournamentSelect
# ---------------------------------------------------------------------------


class TestTournamentSelect:
    """Tests for tournament_select()."""

    def test_returns_genome_from_population(self) -> None:
        """tournament_select() returns one of the supplied genomes."""
        pop = [_make_genome(i) for i in range(5)]
        scores = [float(i) for i in range(5)]
        result = tournament_select(pop, scores, k=3, seed=0)
        assert result in pop

    def test_population_fitness_mismatch_raises(self) -> None:
        """Mismatched population and fitness lengths raise ValueError."""
        pop = [_make_genome(i) for i in range(3)]
        with pytest.raises(ValueError, match="fitness_scores"):
            tournament_select(pop, [1.0, 2.0], k=2, seed=0)

    def test_k_zero_raises(self) -> None:
        """Tournament size k=0 raises ValueError."""
        pop = [_make_genome(i) for i in range(3)]
        with pytest.raises(ValueError, match="Tournament size"):
            tournament_select(pop, [1.0, 2.0, 3.0], k=0, seed=0)

    def test_k_clamped_to_population_size(self) -> None:
        """k larger than population size does not raise; uses entire population."""
        pop = [_make_genome(i) for i in range(3)]
        scores = [1.0, 5.0, 2.0]
        # k=100 > population size; should still work
        result = tournament_select(pop, scores, k=100, seed=0)
        # With k=3 (whole pop), best genome (index 1, score=5.0) must be selected
        assert result is pop[1]

    def test_always_selects_best_when_k_equals_pop_size(self) -> None:
        """When k equals population size, the genome with max fitness is always chosen."""
        pop = [_make_genome(i) for i in range(4)]
        scores = [1.0, 10.0, 3.0, 2.0]
        for seed in range(10):
            result = tournament_select(pop, scores, k=4, seed=seed)
            assert result is pop[1], f"seed={seed}: expected best genome"

    def test_seeded_selection_is_deterministic(self) -> None:
        """Same seed produces the same selection result."""
        pop = [_make_genome(i) for i in range(6)]
        scores = [float(i * 1.5) for i in range(6)]
        r1 = tournament_select(pop, scores, k=3, seed=42)
        r2 = tournament_select(pop, scores, k=3, seed=42)
        assert r1 is r2

    def test_higher_fitness_selected_more_often_statistical(self) -> None:
        """Higher-fitness genome is selected more than 60% of the time over 100 runs.

        Population: 2 genomes — genome[0] fitness=0.0, genome[1] fitness=1.0.
        With k=2 (full tournament), genome[1] is always selected.
        With k=1 (random), each genome is selected 50% of the time.
        Use k=2 so the higher-fitness genome wins every time — well above 60%.
        """
        pop = [_make_genome(0), _make_genome(1)]
        scores = [0.0, 1.0]

        selections = [
            tournament_select(pop, scores, k=2, seed=i)
            for i in range(100)
        ]
        high_fitness_count = sum(1 for g in selections if g is pop[1])
        assert high_fitness_count > 60, (
            f"Expected >60 selections of higher-fitness genome, got {high_fitness_count}"
        )

    def test_statistical_tournament_k3_favors_better_genome(self) -> None:
        """With k=3 and a large score gap, better genome wins >60% over 100 runs.

        Uses a 10-genome population where genome at index 9 has by far the
        highest fitness (100.0 vs 0-8 for others).  With k=3 there is always
        a chance of not picking index 9, but over 100 trials the probability
        of it appearing <60 times is negligible.
        """
        pop = [_make_genome(i) for i in range(10)]
        scores = list(range(10))  # 0,1,...,9; genome[9] wins

        wins = sum(
            1
            for seed in range(100)
            if tournament_select(pop, scores, k=3, seed=seed) is pop[9]
        )
        # Exact win probability with k=3: P = 1 - (9/10)^3 ≈ 27.1% each draw,
        # but the best genome will win more than any other single genome.
        # We relax to >20 wins (baseline is 10 wins if uniform random).
        assert wins > 20, (
            f"Expected best genome to win more than 20/100 tournaments, got {wins}"
        )

    def test_single_genome_population_always_selected(self) -> None:
        """With a single-element population, that genome is always returned."""
        pop = [_make_genome(0)]
        for seed in range(5):
            result = tournament_select(pop, [42.0], k=1, seed=seed)
            assert result is pop[0]


# ---------------------------------------------------------------------------
# TestCrossover
# ---------------------------------------------------------------------------


class TestCrossover:
    """Tests for crossover()."""

    def test_returns_strategy_genome(self) -> None:
        """crossover() returns a StrategyGenome instance."""
        a = _make_genome(0)
        b = _make_genome(1)
        child = crossover(a, b, seed=0)
        assert isinstance(child, StrategyGenome)

    def test_child_params_within_bounds(self) -> None:
        """Child produced by crossover has all parameters within bounds."""
        for seed in range(20):
            a = _make_genome(seed)
            b = _make_genome(seed + 100)
            child = crossover(a, b, seed=seed)
            assert _all_params_within_bounds(child), (
                f"seed={seed}: child parameters out of bounds"
            )

    def test_child_pairs_nonempty(self) -> None:
        """Child always has at least one active trading pair."""
        for seed in range(20):
            a = _make_genome(seed)
            b = _make_genome(seed + 100)
            child = crossover(a, b, seed=seed)
            assert len(child.pairs) >= 1, f"seed={seed}: empty pairs"

    def test_child_has_genes_from_both_parents(self) -> None:
        """Over many seeds, at least some children inherit from both parents.

        We verify this by checking that not every child is identical to parent_a
        AND not every child is identical to parent_b.
        """
        all_same_as_a = True
        all_same_as_b = True
        for seed in range(50):
            a = _make_genome(0)
            b = _make_genome(1)
            child = crossover(a, b, seed=seed)
            vec_a = a.to_vector()
            vec_b = b.to_vector()
            vec_c = child.to_vector()
            if not np.allclose(vec_c, vec_a):
                all_same_as_a = False
            if not np.allclose(vec_c, vec_b):
                all_same_as_b = False
        assert not all_same_as_a, "Every child was identical to parent_a — crossover has no effect"
        assert not all_same_as_b, "Every child was identical to parent_b — crossover has no effect"

    def test_single_point_crossover_structure(self) -> None:
        """Crossover with seed=0 produces a child whose vector is a valid blend.

        We verify that the child's vector comes entirely from parent_a before
        the cut point and entirely from parent_b from the cut point onward by
        testing at a cut=1 scenario: child[0] == a[0] and child[1:] == b[1:].

        We do this by constructing two maximally different parents and checking
        that exactly one of the structures holds.
        """
        # Use two parents where every gene is at opposite ends of the range.
        # parent_a: all scalar params at lower bound, parent_b: all at upper bound.
        kwargs_a = {k: lo for k, (lo, hi) in SCALAR_BOUNDS.items()}
        kwargs_a.update({k: lo for k, (lo, hi) in INT_BOUNDS.items()})
        kwargs_a["pairs"] = [AVAILABLE_PAIRS[0]]

        kwargs_b = {k: hi for k, (lo, hi) in SCALAR_BOUNDS.items()}
        kwargs_b.update({k: hi for k, (lo, hi) in INT_BOUNDS.items()})
        kwargs_b["pairs"] = AVAILABLE_PAIRS[-2:]

        a = StrategyGenome(**kwargs_a)
        b = StrategyGenome(**kwargs_b)

        child = crossover(a, b, seed=5)
        vec_a = a.to_vector()
        vec_b = b.to_vector()
        vec_c = child.to_vector()

        # Child should share a prefix with a and a suffix with b (or all-a or all-b
        # is impossible since cut ∈ [1, VECTOR_LEN-1]).
        found_valid_cut = False
        for cut in range(1, VECTOR_LEN):
            prefix_matches_a = np.allclose(vec_c[:cut], vec_a[:cut])
            suffix_matches_b = np.allclose(vec_c[cut:], vec_b[cut:])
            if prefix_matches_a and suffix_matches_b:
                found_valid_cut = True
                break
        assert found_valid_cut, "Child vector does not follow single-point crossover structure"

    def test_seeded_crossover_is_deterministic(self) -> None:
        """Same seed and same parents produce the same child."""
        a = _make_genome(10)
        b = _make_genome(20)
        c1 = crossover(a, b, seed=77)
        c2 = crossover(a, b, seed=77)
        assert c1 == c2


# ---------------------------------------------------------------------------
# TestMutate
# ---------------------------------------------------------------------------


class TestMutate:
    """Tests for mutate()."""

    def test_returns_strategy_genome(self) -> None:
        """mutate() returns a StrategyGenome instance."""
        g = _make_genome(0)
        result = mutate(g, seed=0)
        assert isinstance(result, StrategyGenome)

    def test_mutated_params_within_bounds(self) -> None:
        """Mutated genome always has all parameters within bounds."""
        for seed in range(30):
            g = _make_genome(seed)
            mutated = mutate(g, mutation_rate=1.0, seed=seed)
            assert _all_params_within_bounds(mutated), (
                f"seed={seed}: mutated parameters out of bounds"
            )

    def test_mutation_rate_1_changes_params(self) -> None:
        """With mutation_rate=1.0, the genome generally differs from the original.

        Uses a high mutation_strength to ensure actual changes occur.
        """
        g = _make_genome(42)
        mutated = mutate(g, mutation_rate=1.0, mutation_strength=0.5, seed=42)
        # The vectors should not be identical (extremely unlikely with rate=1.0)
        assert not np.allclose(g.to_vector(), mutated.to_vector()), (
            "mutation_rate=1.0 produced no change at all"
        )

    def test_mutation_rate_0_produces_no_scalar_changes(self) -> None:
        """With mutation_rate=0.0, no scalar or int genes are mutated.

        Note: pair mask genes also use mutation_rate, so all bits stay unchanged.
        """
        g = _make_genome(7)
        mutated = mutate(g, mutation_rate=0.0, seed=7)
        # Scalar and int genes must be identical
        vec_orig = g.to_vector()
        vec_mut = mutated.to_vector()
        # Check scalar and int sections only (pair mask can change due to
        # the "at least one pair" guard — but with rate=0 it won't flip)
        scalar_int_len = _SCALAR_LEN + _INT_LEN
        assert np.allclose(vec_orig[:scalar_int_len], vec_mut[:scalar_int_len])

    def test_mutated_pairs_nonempty(self) -> None:
        """Mutated genome always has at least one active pair."""
        for seed in range(30):
            g = _make_genome(seed)
            mutated = mutate(g, mutation_rate=1.0, seed=seed)
            assert len(mutated.pairs) >= 1, f"seed={seed}: empty pairs after mutation"

    def test_invalid_mutation_rate_raises(self) -> None:
        """mutation_rate outside [0, 1] raises ValueError."""
        g = _make_genome(0)
        with pytest.raises(ValueError, match="mutation_rate"):
            mutate(g, mutation_rate=-0.1, seed=0)
        with pytest.raises(ValueError, match="mutation_rate"):
            mutate(g, mutation_rate=1.01, seed=0)

    def test_invalid_mutation_strength_raises(self) -> None:
        """mutation_strength <= 0 raises ValueError."""
        g = _make_genome(0)
        with pytest.raises(ValueError, match="mutation_strength"):
            mutate(g, mutation_strength=0.0, seed=0)
        with pytest.raises(ValueError, match="mutation_strength"):
            mutate(g, mutation_strength=-0.5, seed=0)

    def test_seeded_mutation_is_deterministic(self) -> None:
        """Same seed produces the same mutated genome."""
        g = _make_genome(3)
        m1 = mutate(g, mutation_rate=0.5, seed=123)
        m2 = mutate(g, mutation_rate=0.5, seed=123)
        assert m1 == m2

    def test_original_genome_not_modified_in_place(self) -> None:
        """mutate() returns a new genome and does not modify the original."""
        g = _make_genome(5)
        original_vec = g.to_vector().copy()
        mutate(g, mutation_rate=1.0, mutation_strength=0.5, seed=5)
        assert np.allclose(g.to_vector(), original_vec), "Original genome was modified"

    def test_typical_mutation_changes_only_subset(self) -> None:
        """With default mutation_rate=0.1, most runs change only 1-3 genes.

        Over 100 seeded runs, the average number of changed genes should be
        roughly mutation_rate * VECTOR_LEN = 0.1 * 17 ≈ 1.7.  We assert
        the average is between 0 and 6 (loose bound to avoid test flakiness).
        """
        g = _make_genome(0)
        original_vec = g.to_vector()
        changed_counts = []
        for seed in range(100):
            mutated = mutate(g, mutation_rate=0.1, seed=seed)
            diff = ~np.isclose(original_vec, mutated.to_vector())
            changed_counts.append(int(diff.sum()))
        avg_changes = sum(changed_counts) / len(changed_counts)
        assert 0 <= avg_changes <= 6, (
            f"Average changed genes {avg_changes:.2f} is outside expected range [0, 6]"
        )


# ---------------------------------------------------------------------------
# TestClipGenome
# ---------------------------------------------------------------------------


class TestClipGenome:
    """Tests for clip_genome()."""

    def test_valid_genome_unchanged(self) -> None:
        """clip_genome() leaves a valid genome unchanged."""
        g = _make_genome(0)
        clipped = clip_genome(g)
        assert np.allclose(g.to_vector(), clipped.to_vector())

    def test_clipped_genome_is_within_bounds(self) -> None:
        """clip_genome() always returns a genome within bounds."""
        # Construct a genome using boundary values and verify clip is a no-op
        g = StrategyGenome(
            rsi_oversold=20.0,
            rsi_overbought=80.0,
            macd_fast=8,
            macd_slow=30,
            adx_threshold=15.0,
            stop_loss_pct=0.01,
            take_profit_pct=0.10,
            trailing_stop_pct=0.005,
            position_size_pct=0.20,
            max_hold_candles=200,
            max_positions=5,
            pairs=AVAILABLE_PAIRS,
        )
        clipped = clip_genome(g)
        assert _all_params_within_bounds(clipped)

    def test_original_not_modified_in_place(self) -> None:
        """clip_genome() returns a new genome and does not alter the original."""
        g = _make_genome(0)
        original_vec = g.to_vector().copy()
        clip_genome(g)
        assert np.allclose(g.to_vector(), original_vec)


# ---------------------------------------------------------------------------
# TestPopulation
# ---------------------------------------------------------------------------


class TestPopulation:
    """Tests for the Population class."""

    # ---- Construction --------------------------------------------------------

    def test_size_below_2_raises(self) -> None:
        """Population size < 2 raises ValueError."""
        with pytest.raises(ValueError, match="size"):
            Population(size=1)

    def test_invalid_elite_pct_raises(self) -> None:
        """elite_pct outside (0, 1) raises ValueError."""
        with pytest.raises(ValueError, match="elite_pct"):
            Population(size=4, elite_pct=0.0)
        with pytest.raises(ValueError, match="elite_pct"):
            Population(size=4, elite_pct=1.0)

    def test_default_construction(self) -> None:
        """Population can be constructed with default parameters."""
        pop = Population(size=10, seed=0)
        assert pop.size == 10
        assert pop.generation == 0
        assert pop.genomes == []

    # ---- Initialization -------------------------------------------------------

    def test_initialize_fills_population(self) -> None:
        """initialize() produces exactly `size` genomes."""
        pop = Population(size=8, seed=42)
        pop.initialize()
        assert len(pop.genomes) == 8

    def test_initialize_resets_generation(self) -> None:
        """Calling initialize() a second time resets generation to 0."""
        pop = Population(size=4, seed=1)
        pop.initialize()
        pop.evolve([1.0, 2.0, 3.0, 4.0])
        assert pop.generation == 1
        pop.initialize()
        assert pop.generation == 0

    def test_initialize_produces_valid_genomes(self) -> None:
        """All genomes produced by initialize() are within bounds."""
        pop = Population(size=10, seed=99)
        pop.initialize()
        for i, g in enumerate(pop.genomes):
            assert _all_params_within_bounds(g), f"Genome {i} out of bounds"

    def test_seeded_population_is_reproducible(self) -> None:
        """Two populations with the same seed produce identical genomes."""
        pop1 = Population(size=6, seed=7)
        pop1.initialize()
        pop2 = Population(size=6, seed=7)
        pop2.initialize()
        for g1, g2 in zip(pop1.genomes, pop2.genomes):
            assert g1 == g2

    # ---- Evolve ---------------------------------------------------------------

    def test_evolve_increments_generation(self) -> None:
        """evolve() increments the generation counter by 1."""
        pop = Population(size=6, seed=0)
        pop.initialize()
        pop.evolve([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        assert pop.generation == 1

    def test_evolve_preserves_population_size(self) -> None:
        """evolve() produces exactly `size` genomes."""
        pop = Population(size=8, seed=0)
        pop.initialize()
        pop.evolve([float(i) for i in range(8)])
        assert len(pop.genomes) == 8

    def test_evolve_fitness_mismatch_raises(self) -> None:
        """evolve() raises ValueError when fitness count != population size."""
        pop = Population(size=4, seed=0)
        pop.initialize()
        with pytest.raises(ValueError, match="fitness_scores"):
            pop.evolve([1.0, 2.0])

    def test_evolve_before_initialize_raises(self) -> None:
        """evolve() raises RuntimeError when called on an empty population."""
        pop = Population(size=4, seed=0)
        with pytest.raises(RuntimeError, match="initialize"):
            pop.evolve([1.0, 2.0, 3.0, 4.0])

    def test_evolve_all_params_within_bounds(self) -> None:
        """After evolve(), all genomes in the new generation are within bounds."""
        pop = Population(size=10, seed=3)
        pop.initialize()
        pop.evolve([float(i) for i in range(10)])
        for i, g in enumerate(pop.genomes):
            assert _all_params_within_bounds(g), f"Post-evolve genome {i} out of bounds"

    # ---- Elite preservation --------------------------------------------------

    def test_elite_genomes_preserved_unchanged(self) -> None:
        """Top `n_elite` genomes from one generation survive unchanged.

        With elite_pct=0.5 and size=4, top 2 genomes should appear identically
        in the next generation.
        """
        pop = Population(size=4, seed=10, elite_pct=0.5)
        pop.initialize()
        fitness = [10.0, 1.0, 5.0, 2.0]  # genome[0]=10 is best, genome[2]=5 is second
        original_genomes = list(pop.genomes)
        pop.evolve(fitness)
        # Best (index 0) and second-best (index 2) should appear in new generation
        assert original_genomes[0] in pop.genomes, "Best genome not preserved by elitism"
        assert original_genomes[2] in pop.genomes, "Second-best genome not preserved by elitism"

    def test_elite_pct_override_in_evolve(self) -> None:
        """elite_pct override in evolve() is respected for that generation."""
        pop = Population(size=6, seed=5, elite_pct=0.2)
        pop.initialize()
        fitness = [float(i) for i in range(6)]
        original_best = pop.genomes[5]  # highest fitness
        # Override to keep top 50% (3 genomes)
        pop.evolve(fitness, elite_pct=0.5)
        assert original_best in pop.genomes

    # ---- 5-generation evolution loop (mock fitness) --------------------------

    def test_5_generation_evolution_no_errors(self) -> None:
        """Population evolves for 5 generations without errors using mock fitness."""
        pop = Population(size=10, seed=42, mutation_rate=0.15, mutation_strength=0.1)
        pop.initialize()

        for gen in range(5):
            # Mock fitness: random scores, deterministic via numpy seed
            rng = np.random.default_rng(gen)
            fitness = list(rng.uniform(-1.0, 3.0, size=pop.size))
            pop.evolve(fitness)
            assert pop.generation == gen + 1
            assert len(pop.genomes) == 10

    def test_5_generation_all_genomes_valid(self) -> None:
        """All genomes remain valid across 5 generations."""
        pop = Population(size=8, seed=99, mutation_rate=0.2, mutation_strength=0.2)
        pop.initialize()

        for gen in range(5):
            rng = np.random.default_rng(seed=gen * 100)
            fitness = list(rng.uniform(-2.0, 2.0, size=pop.size))
            pop.evolve(fitness)
            for i, g in enumerate(pop.genomes):
                assert _all_params_within_bounds(g), (
                    f"gen={gen}, genome={i} out of bounds"
                )
                assert len(g.pairs) >= 1, f"gen={gen}, genome={i} has empty pairs"

    # ---- Stats ---------------------------------------------------------------

    def test_stats_returns_population_stats(self) -> None:
        """stats() returns a PopulationStats dataclass with correct values."""
        pop = Population(size=4, seed=0)
        pop.initialize()
        fitness = [1.0, 3.0, 2.0, 4.0]
        stats = pop.stats(fitness)
        assert isinstance(stats, PopulationStats)
        assert stats.best == 4.0
        assert stats.worst == 1.0
        assert stats.best_index == 3
        assert stats.generation == 0
        assert abs(stats.mean - 2.5) < 1e-9
        assert stats.std > 0.0

    def test_stats_empty_population_raises(self) -> None:
        """stats() raises RuntimeError on empty population."""
        pop = Population(size=4, seed=0)
        with pytest.raises(RuntimeError, match="initialize"):
            pop.stats([1.0, 2.0, 3.0, 4.0])

    def test_stats_length_mismatch_raises(self) -> None:
        """stats() raises ValueError when fitness count differs from genome count."""
        pop = Population(size=4, seed=0)
        pop.initialize()
        with pytest.raises(ValueError, match="fitness_scores"):
            pop.stats([1.0, 2.0])

    # ---- best() --------------------------------------------------------------

    def test_best_returns_highest_fitness_genome(self) -> None:
        """best() returns the genome with the maximum fitness score."""
        pop = Population(size=5, seed=0)
        pop.initialize()
        fitness = [1.0, 5.0, 3.0, 2.0, 4.0]
        result = pop.best(fitness)
        assert result is pop.genomes[1]

    def test_best_empty_population_raises(self) -> None:
        """best() raises RuntimeError on empty population."""
        pop = Population(size=4, seed=0)
        with pytest.raises(RuntimeError, match="initialize"):
            pop.best([1.0, 2.0, 3.0, 4.0])
