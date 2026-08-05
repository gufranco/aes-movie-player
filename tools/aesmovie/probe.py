"""Find the tier a source supports by baking, never by predicting.

Calibration samples short windows and extrapolates, and it reads high by
construction: every window starts with a cold dictionary where almost
every slot mints a tile, while a full bake amortises reuse across the
whole film. On the reference film it predicted 946,352 tiles where the
encoder spent 846,784. Worse, the ratio between two rungs is a property
of the content rather than of the settings, so no table can price them
for every film.

So nothing is predicted here. Rungs are baked and the results are read.
What is measured is measured, and what is not measured is not guessed
at.

Which rungs get baked is a separate question from whether anything is
estimated. Cost falls strictly from every rung to the next, and a rung
that fits implies every cheaper rung fits, so the rungs that fit form a
suffix of the ladder and only its boundary has to be found.

The search still starts at the richest rung, because a source that can
afford it should cost one bake to discover. When that rung does not fit
the probe doubles its stride, `q02`, `q04`, `q08`, until a rung fits,
then bisects the bracket that doubling just proved. The answer is the
same rung a walk from the top would reach; what changes is that a film
settling deep in the ladder costs about nine bakes instead of thirty.

A rung fails in three ways, and all three mean the same thing. It can
fill the dictionary, it can pass the tile budget, or it can stay inside
the budget only because rate control degraded it far enough to get
there. The third is the one worth naming: the controller trades picture
quality for room, so a rung rescued at its ceiling is nominally richer
than the rung below while looking worse. Accepting it would defeat the
search.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from aesmovie import quality, tiercache


@dataclass(frozen=True, slots=True)
class Reading:
    """What one bake spent, and whether it finished on its own terms."""

    tier: quality.Tier
    tiles: int
    capped: bool
    exhausted: bool = False

    def fits(self, budget: int) -> bool:
        """Whether this rung finished the film inside the cartridge."""
        return not self.capped and not self.exhausted and self.tiles <= budget


@dataclass(slots=True)
class Outcome:
    """The rung the source supports, and what was learned getting there."""

    tier: quality.Tier | None
    minutes: float
    rates: dict[str, float | None] = field(default_factory=dict)
    baked: list[str] = field(default_factory=list)
    too_expensive: list[str] = field(default_factory=list)


def candidates(source_fps: float | None, vblank_fps: float | None) -> list[quality.Tier]:
    """The ladder, richest first, without rungs the baker would refuse."""
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
    """The richest rung that fits, settled by baking.

    Never shortens the source. A source that fits nowhere comes back with
    no tier, leaving the decision to trim where it belongs.
    """
    outcome = Outcome(tier=None, minutes=minutes, rates=dict(known))
    rungs = candidates(source_fps, vblank_fps)

    def fits(index: int) -> bool:
        return _fits(rungs[index], outcome, measure=measure, minutes=minutes, budget=budget)

    low, high = _bracket(len(rungs), fits)
    while low < high:
        middle = (low + high) // 2
        if fits(middle):
            high = middle
        else:
            low = middle + 1

    if low < len(rungs):
        outcome.tier = rungs[low]
    return outcome


def _bracket(count: int, fits: Callable[[int], bool]) -> tuple[int, int]:
    """Narrow the answer to a span, richest rung first, by doubling.

    Returns the half-open span the answer lies in. A span of
    `(count, count)` means nothing fits, which is the caller's cue to
    report that rather than to trim anything.
    """
    if count == 0:
        return 0, 0
    if fits(0):
        return 0, 0
    stride, previous = 1, 0
    while stride < count:
        if fits(stride):
            return previous + 1, stride
        previous = stride
        stride *= 2
    if previous + 1 >= count:
        return count, count
    return previous + 1, count


def _fits(
    tier: quality.Tier,
    outcome: Outcome,
    *,
    measure: Callable[[quality.Tier], Reading],
    minutes: float,
    budget: int,
) -> bool:
    """Whether this rung fits, baking it only if nothing already knows."""
    if tiercache.settled(outcome.rates, tier):
        return tiercache.fits(outcome.rates, tier)

    reading = measure(tier)
    outcome.baked.append(tier.name)
    if not reading.fits(budget):
        outcome.rates[tier.name] = None
        outcome.too_expensive.append(tier.name)
        return False

    outcome.rates[tier.name] = reading.tiles / minutes
    return True
