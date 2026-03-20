"""Population — manages a generation of StrategyGenomes and their evolution.

The Population class is the main driver for the genetic algorithm loop.
It initialises a pool of random genomes and, given fitness scores, produces
the next generation via elitism + tournament selection + crossover + mutation.

Typical usage:
    pop = Population(size=12, seed=42)
    pop.initialize()

    for gen in range(10):
        scores = [evaluate(g) for g in pop.genomes]
        print(pop.stats(scores))
        pop.evolve(scores)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import structlog

from agent.strategies.evolutionary.genome import StrategyGenome
from agent.strategies.evolutionary.operators import crossover, mutate, tournament_select

logger = structlog.get_logger(__name__)


@dataclass
class PopulationStats:
    """Summary statistics for one generation's fitness scores.

    Attributes:
        generation: Zero-based generation index.
        mean: Mean fitness across all genomes.
        std: Standard deviation of fitness.
        best: Highest fitness value.
        worst: Lowest fitness value.
        best_index: Index of the genome with the highest fitness.
    """

    generation: int
    mean: float
    std: float
    best: float
    worst: float
    best_index: int


class Population:
    """Manages a fixed-size pool of StrategyGenomes across generations.

    Args:
        size: Number of genomes in the population (must be >= 2).
        seed: Master random seed used to derive per-operation seeds, ensuring
              fully reproducible runs when provided.
        mutation_rate: Probability that any individual gene is mutated per
                       generation (passed through to ``mutate()``).
        mutation_strength: Gaussian std as a fraction of parameter range
                           (passed through to ``mutate()``).
        elite_pct: Fraction of the population preserved unchanged into the
                   next generation (default 0.2 = top 20 %).
        tournament_k: Tournament size for parent selection (default 3).
    """

    def __init__(
        self,
        size: int = 20,
        seed: int | None = None,
        mutation_rate: float = 0.1,
        mutation_strength: float = 0.1,
        elite_pct: float = 0.2,
        tournament_k: int = 3,
    ) -> None:
        if size < 2:
            raise ValueError(f"Population size must be >= 2, got {size}")
        if not 0.0 < elite_pct < 1.0:
            raise ValueError(f"elite_pct must be in (0, 1), got {elite_pct}")

        self.size = size
        self.seed = seed
        self.mutation_rate = mutation_rate
        self.mutation_strength = mutation_strength
        self.elite_pct = elite_pct
        self.tournament_k = tournament_k

        self.generation: int = 0
        self.genomes: list[StrategyGenome] = []

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Populate with ``self.size`` randomly sampled genomes.

        Each genome receives a unique derived seed so the full population is
        reproducible when ``self.seed`` is set.  Calling ``initialize()`` a
        second time resets the generation counter and replaces all genomes.
        """
        self.generation = 0
        self.genomes = [
            StrategyGenome.from_random(
                seed=(None if self.seed is None else self.seed + i)
            )
            for i in range(self.size)
        ]
        logger.info(
            "population_initialized",
            size=self.size,
            seed=self.seed,
            generation=self.generation,
        )

    # ------------------------------------------------------------------
    # Evolution
    # ------------------------------------------------------------------

    def evolve(
        self,
        fitness_scores: list[float],
        elite_pct: float | None = None,
    ) -> None:
        """Produce the next generation in-place.

        Algorithm:
            1. Sort genomes by fitness (descending).
            2. Carry the top ``n_elite`` genomes unchanged (elitism).
            3. Fill the remaining slots by:
               a. Selecting two parents via tournament selection.
               b. Producing a child via single-point crossover.
               c. Applying Gaussian mutation.
            4. Increment ``self.generation``.

        Args:
            fitness_scores: Fitness value for each genome in ``self.genomes``
                            (same order, same length).
            elite_pct: Override for ``self.elite_pct`` for this generation only.

        Raises:
            ValueError: If ``len(fitness_scores) != len(self.genomes)``.
        """
        if not self.genomes:
            raise RuntimeError("Population is empty — call initialize() first.")
        if len(fitness_scores) != len(self.genomes):
            raise ValueError(
                f"fitness_scores length {len(fitness_scores)} != "
                f"population size {len(self.genomes)}"
            )

        ep = elite_pct if elite_pct is not None else self.elite_pct
        n_elite = max(1, math.ceil(self.size * ep))

        # Sort descending by fitness.
        ranked = sorted(
            zip(fitness_scores, self.genomes), key=lambda x: x[0], reverse=True
        )
        elite_genomes = [g for _, g in ranked[:n_elite]]
        next_gen: list[StrategyGenome] = list(elite_genomes)

        # Fill remaining slots.
        gen_seed_base = None if self.seed is None else self.seed + self.generation * 1000
        slot = n_elite
        while len(next_gen) < self.size:
            parent_seed_a = None if gen_seed_base is None else gen_seed_base + slot
            parent_seed_b = None if gen_seed_base is None else gen_seed_base + slot + 1
            mutate_seed = None if gen_seed_base is None else gen_seed_base + slot + 2
            cross_seed = None if gen_seed_base is None else gen_seed_base + slot + 3

            parent_a = tournament_select(
                self.genomes, fitness_scores, k=self.tournament_k, seed=parent_seed_a
            )
            parent_b = tournament_select(
                self.genomes, fitness_scores, k=self.tournament_k, seed=parent_seed_b
            )
            child = crossover(parent_a, parent_b, seed=cross_seed)
            child = mutate(
                child,
                mutation_rate=self.mutation_rate,
                mutation_strength=self.mutation_strength,
                seed=mutate_seed,
            )
            next_gen.append(child)
            slot += 4  # advance seed offset

        self.genomes = next_gen[: self.size]
        self.generation += 1

        logger.info(
            "population_evolved",
            generation=self.generation,
            n_elite=n_elite,
            size=self.size,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def best(self, fitness_scores: list[float]) -> StrategyGenome:
        """Return the genome with the highest fitness score.

        Args:
            fitness_scores: Fitness value for each genome (same order).

        Returns:
            The StrategyGenome with the maximum fitness.

        Raises:
            RuntimeError: If the population is empty.
            ValueError: If lengths differ.
        """
        if not self.genomes:
            raise RuntimeError("Population is empty — call initialize() first.")
        if len(fitness_scores) != len(self.genomes):
            raise ValueError(
                f"fitness_scores length {len(fitness_scores)} != "
                f"population size {len(self.genomes)}"
            )
        best_idx = max(range(len(fitness_scores)), key=lambda i: fitness_scores[i])
        return self.genomes[best_idx]

    def stats(self, fitness_scores: list[float]) -> PopulationStats:
        """Compute summary statistics for the current generation.

        Args:
            fitness_scores: Fitness value for each genome (same order).

        Returns:
            A PopulationStats dataclass with mean, std, best, worst, and
            the index of the best genome.

        Raises:
            RuntimeError: If the population is empty.
            ValueError: If lengths differ.
        """
        if not self.genomes:
            raise RuntimeError("Population is empty — call initialize() first.")
        if len(fitness_scores) != len(self.genomes):
            raise ValueError(
                f"fitness_scores length {len(fitness_scores)} != "
                f"population size {len(self.genomes)}"
            )

        scores = fitness_scores
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        std = math.sqrt(variance)
        best_idx = max(range(n), key=lambda i: scores[i])

        return PopulationStats(
            generation=self.generation,
            mean=mean,
            std=std,
            best=scores[best_idx],
            worst=min(scores),
            best_index=best_idx,
        )
