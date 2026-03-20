"""Genetic algorithm operators for StrategyGenome evolution.

All operators work on ``StrategyGenome`` objects via their numpy vector
representation so the math is uniform across the parameter space.

Functions:
    tournament_select  - Select one parent via k-tournament selection
    crossover          - Single-point crossover of two parent vectors
    mutate             - Gaussian perturbation on a random subset of genes
    clip_genome        - Enforce all parameter bounds after mutation/crossover
"""

from __future__ import annotations

import random

import numpy as np

from agent.strategies.evolutionary.genome import (
    AVAILABLE_PAIRS,
    INT_BOUNDS,
    SCALAR_BOUNDS,
    VECTOR_LEN,
    StrategyGenome,
    _INT_KEYS,
    _INT_LEN,
    _PAIRS_LEN,
    _SCALAR_KEYS,
    _SCALAR_LEN,
)


def tournament_select(
    population: list[StrategyGenome],
    fitness_scores: list[float],
    k: int = 3,
    seed: int | None = None,
) -> StrategyGenome:
    """Select one genome via tournament selection.

    Randomly picks ``k`` candidates from the population and returns the one
    with the highest fitness score.  Tournament selection provides selection
    pressure without requiring fitness normalisation and handles negative
    fitness values (e.g., negative Sharpe ratios) gracefully.

    Args:
        population: Current population of genomes.
        fitness_scores: Fitness value for each genome (same order as population).
        k: Tournament size — higher k = stronger selection pressure (default 3).
        seed: Optional random seed for reproducibility.

    Returns:
        The genome with the highest fitness among the k sampled candidates.

    Raises:
        ValueError: If population and fitness_scores lengths differ.
    """
    if len(population) != len(fitness_scores):
        raise ValueError(
            f"population length {len(population)} != fitness_scores length {len(fitness_scores)}"
        )
    if k < 1:
        raise ValueError(f"Tournament size k must be >= 1, got {k}")

    rng = random.Random(seed)
    # Clamp k to population size so we never sample more than available.
    k = min(k, len(population))
    indices = rng.sample(range(len(population)), k=k)
    best_idx = max(indices, key=lambda i: fitness_scores[i])
    return population[best_idx]


def crossover(
    parent_a: StrategyGenome,
    parent_b: StrategyGenome,
    seed: int | None = None,
) -> StrategyGenome:
    """Single-point crossover on the parameter vector.

    Picks a random crossover point ``c`` in [1, VECTOR_LEN - 1].  The child
    takes genes [0:c] from parent_a and genes [c:] from parent_b.  The result
    is clipped and reconstructed into a valid StrategyGenome.

    Args:
        parent_a: First parent genome.
        parent_b: Second parent genome.
        seed: Optional random seed.

    Returns:
        A new StrategyGenome combining parameters from both parents.
    """
    rng = random.Random(seed)
    vec_a = parent_a.to_vector()
    vec_b = parent_b.to_vector()

    # Crossover point is in [1, VECTOR_LEN - 1] so neither parent is copied whole.
    cut = rng.randint(1, VECTOR_LEN - 1)
    child_vec = np.concatenate([vec_a[:cut], vec_b[cut:]])

    child_vec = _clip_vector(child_vec)
    return StrategyGenome.from_vector(child_vec)


def mutate(
    genome: StrategyGenome,
    mutation_rate: float = 0.1,
    mutation_strength: float = 0.1,
    seed: int | None = None,
) -> StrategyGenome:
    """Apply Gaussian perturbation to 1–2 randomly chosen genes.

    Each gene is mutated independently with probability ``mutation_rate``.  The
    perturbation is drawn from N(0, mutation_strength * range) where ``range``
    is the parameter's (hi - lo) bound width.  This keeps perturbations
    proportional to the parameter scale.

    For pair genes (binary mask), mutation flips the bit instead of applying
    Gaussian noise.  The result always has at least one active pair.

    Args:
        genome: Genome to mutate (not modified in-place; a new genome is returned).
        mutation_rate: Probability that any individual gene is mutated (0–1).
            Default 0.1 (10 %) — roughly 1–2 mutations per genome for VECTOR_LEN=17.
        mutation_strength: Gaussian std as a fraction of the parameter range (0–1).
            Default 0.1 (10 % of range).
        seed: Optional random seed.

    Returns:
        A new StrategyGenome with 0 or more genes perturbed within bounds.
    """
    if not 0.0 <= mutation_rate <= 1.0:
        raise ValueError(f"mutation_rate must be in [0, 1], got {mutation_rate}")
    if mutation_strength <= 0.0:
        raise ValueError(f"mutation_strength must be > 0, got {mutation_strength}")

    np_rng = np.random.default_rng(seed)
    vec = genome.to_vector().copy()

    # Mutate scalar genes
    for i, key in enumerate(_SCALAR_KEYS):
        if np_rng.random() < mutation_rate:
            lo, hi = SCALAR_BOUNDS[key]
            noise = np_rng.normal(0.0, mutation_strength * (hi - lo))
            vec[i] = float(np.clip(vec[i] + noise, lo, hi))

    # Mutate integer genes
    for j, key in enumerate(_INT_KEYS):
        if np_rng.random() < mutation_rate:
            lo, hi = INT_BOUNDS[key]
            # Scale noise to the integer range; round to nearest int after adding.
            noise = np_rng.normal(0.0, mutation_strength * (hi - lo))
            vec[_SCALAR_LEN + j] = float(np.clip(round(vec[_SCALAR_LEN + j] + noise), lo, hi))

    # Mutate pair mask genes — flip the bit
    pair_offset = _SCALAR_LEN + _INT_LEN
    for k in range(_PAIRS_LEN):
        if np_rng.random() < mutation_rate:
            vec[pair_offset + k] = 1.0 - vec[pair_offset + k]

    # Ensure at least one pair is active after mutation
    if not any(vec[pair_offset + k] >= 0.5 for k in range(_PAIRS_LEN)):
        vec[pair_offset + int(np_rng.integers(0, _PAIRS_LEN))] = 1.0

    return StrategyGenome.from_vector(vec)


def clip_genome(genome: StrategyGenome) -> StrategyGenome:
    """Return a copy of ``genome`` with all parameters clamped within bounds.

    This is a safety guard to be called after any operator that could produce
    out-of-range values (e.g., direct vector arithmetic outside the operators
    defined here).

    Args:
        genome: Genome to clip (not modified in-place).

    Returns:
        A new StrategyGenome with all parameters within their valid ranges.
    """
    vec = genome.to_vector()
    vec = _clip_vector(vec)
    return StrategyGenome.from_vector(vec)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clip_vector(vec: np.ndarray) -> np.ndarray:
    """Clip each element of the parameter vector to its valid range.

    Args:
        vec: Float64 array of length VECTOR_LEN.

    Returns:
        A new clipped array (input is not modified).
    """
    vec = vec.copy()

    # Clip scalar genes
    for i, key in enumerate(_SCALAR_KEYS):
        lo, hi = SCALAR_BOUNDS[key]
        vec[i] = float(np.clip(vec[i], lo, hi))

    # Clip integer genes
    for j, key in enumerate(_INT_KEYS):
        lo, hi = INT_BOUNDS[key]
        vec[_SCALAR_LEN + j] = float(np.clip(vec[_SCALAR_LEN + j], lo, hi))

    # Pair mask — clamp to [0, 1]
    pair_offset = _SCALAR_LEN + _INT_LEN
    for k in range(_PAIRS_LEN):
        vec[pair_offset + k] = float(np.clip(vec[pair_offset + k], 0.0, 1.0))

    return vec
