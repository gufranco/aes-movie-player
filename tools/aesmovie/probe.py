"""Find the tier a source really supports by baking, not by sampling.

Calibration extrapolates from short windows and reads high, because each
window starts with a cold dictionary while a full bake amortises reuse.
This measures the thing itself instead.

Baking every rung from the best downwards would settle it, but two facts
make that wasteful. A bake is about eight minutes, and a rung that
overruns does not fail: the dictionary caps and the encoder finishes with
a truncated count, so a saturated bake says only "too expensive" and
carries no usable rate. So the search measures a rung that fits, takes
its exact cost, and jumps to the answer that cost implies, checking it.
Two bakes settle most sources, and every reading is kept so the next run
spends none.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from aesmovie import quality, tiercache

MAX_BAKES = 6
SEED_TIER = "q24"


@dataclass(frozen=True, slots=True)
class Reading:
    """What one bake actually spent, and whether it ran out of dictionary."""

    tier: quality.Tier
    tiles: int
    capped: bool


@dataclass(slots=True)
class Outcome:
    """The rung the source supports, and the readings that proved it."""

    tier: quality.Tier | None
    minutes: float
    rates: dict[str, float] = field(default_factory=dict)
    baked: list[str] = field(default_factory=list)
    too_expensive: list[str] = field(default_factory=list)


def _candidates(source_fps: float | None, vblank_fps: float | None) -> list[quality.Tier]:
    if source_fps is None or vblank_fps is None:
        return list(quality.LADDER)
    return [
        tier
        for tier in quality.LADDER
        if quality.reachable(tier, source_fps=source_fps, vblank_fps=vblank_fps)
    ]


def search(
    *,
    measure: Callable[[quality.Tier], Reading],
    minutes: float,
    budget: int,
    known: dict[str, float],
    source_fps: float | None = None,
    vblank_fps: float | None = None,
    max_bakes: int = MAX_BAKES,
) -> Outcome:
    """Bake until the best rung that fits is known, then stop.

    Never shortens the source. A source that fits nowhere comes back with
    no tier and the readings that showed it, leaving the decision to trim
    where it belongs.
    """
    ladder = _candidates(source_fps, vblank_fps)
    outcome = Outcome(tier=None, minutes=minutes, rates=dict(known))
    banned: set[str] = set()

    for _ in range(max_bakes):
        wanted = _best_allowed(outcome.rates, ladder, banned, minutes, budget)
        if wanted is None:
            wanted = quality.tier_by_name(SEED_TIER)
            if wanted not in ladder or wanted.name in banned:
                wanted = next((t for t in reversed(ladder) if t.name not in banned), None)
            if wanted is None:
                return outcome

        if wanted.name in outcome.rates and not _needs_proof(outcome, wanted):
            outcome.tier = wanted
            return outcome

        reading = measure(wanted)
        outcome.baked.append(wanted.name)

        if reading.capped or reading.tiles > budget:
            banned.add(wanted.name)
            outcome.too_expensive.append(wanted.name)
            for tier in ladder:
                if tier.relative_cost >= wanted.relative_cost:
                    banned.add(tier.name)
            continue

        outcome.rates[wanted.name] = reading.tiles / minutes
        outcome.tier = wanted

    return outcome


def _needs_proof(outcome: Outcome, tier: quality.Tier) -> bool:
    """A rung is settled once it has been baked in this run."""
    return tier.name not in outcome.baked


def _best_allowed(
    rates: dict[str, float],
    ladder: list[quality.Tier],
    banned: set[str],
    minutes: float,
    budget: int,
) -> quality.Tier | None:
    for tier in ladder:
        if tier.name in banned:
            continue
        cost = tiercache.predict(rates, tier, minutes)
        if cost is None:
            return None
        if cost <= budget:
            return tier
    return None
