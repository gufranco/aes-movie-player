"""Find the tier a source supports by baking from the best rung down.

Calibration samples short windows and extrapolates, and it reads high by
construction: every window starts with a cold dictionary where almost
every slot mints a tile, while a full bake amortises reuse across the
whole film. On the reference film it predicted 946,352 tiles where the
encoder spent 846,784.

So nothing is predicted here. The best rung is baked, and if it overran,
the next, until one fits. The first that fits is the answer, and there is
no estimate anywhere to be wrong. That costs a run of bakes the first
time a source is seen, and nothing at all afterwards, because every rung
settled this way is remembered against the source's own bytes.

A rung that overruns does not fail: the dictionary caps and the encoder
finishes with a truncated count. That count is not a rate and is never
kept as one. What is kept is the fact that the rung overran, so it is
never baked twice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from aesmovie import quality, tiercache


@dataclass(frozen=True, slots=True)
class Reading:
    """What one bake spent, and whether it ran out of dictionary."""

    tier: quality.Tier
    tiles: int
    capped: bool


@dataclass(slots=True)
class Outcome:
    """The rung the source supports, and what was learned getting there."""

    tier: quality.Tier | None
    minutes: float
    rates: dict[str, float | None] = field(default_factory=dict)
    baked: list[str] = field(default_factory=list)
    too_expensive: list[str] = field(default_factory=list)


def candidates(source_fps: float | None, vblank_fps: float | None) -> list[quality.Tier]:
    """The ladder, best first, without rungs the baker would refuse."""
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
    known: dict[str, float | None],
    source_fps: float | None = None,
    vblank_fps: float | None = None,
) -> Outcome:
    """Bake from the best rung down and stop at the first that fits.

    Never shortens the source. A source that fits nowhere comes back with
    no tier, leaving the decision to trim where it belongs.
    """
    outcome = Outcome(tier=None, minutes=minutes, rates=dict(known))

    for tier in candidates(source_fps, vblank_fps):
        if tiercache.settled(outcome.rates, tier):
            if tiercache.fits(outcome.rates, tier):
                outcome.tier = tier
                return outcome
            outcome.too_expensive.append(tier.name)
            continue

        reading = measure(tier)
        outcome.baked.append(tier.name)

        if reading.capped or reading.tiles > budget:
            outcome.rates[tier.name] = None
            outcome.too_expensive.append(tier.name)
            continue

        outcome.rates[tier.name] = reading.tiles / minutes
        outcome.tier = tier
        return outcome

    return outcome
