"""Measure what each quality setting costs, and build the ladder from that.

The rungs used to be hand-picked, with their relative costs written down
from ad-hoc runs. That is how the ladder ended up with a rung strictly
worse than the one below it: nothing was comparing them.

Here a grid of settings is encoded against the same decoded clip, so cost
and error are measured under identical conditions. Anything beaten on both
axes at once is dropped, and the rungs are spread evenly through the cost
that survives. A rung therefore always buys something over the rung below.

Decoding dominates the run, so the clip is decoded once and every setting
is encoded against it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt

from aesmovie import calibrate, encode, frames, neocolor, quality

SECONDS_PER_MINUTE: Final = 60.0

CHROMA_SWEEP: Final = (
    1.0, 0.94, 0.89, 0.84, 0.79, 0.74, 0.70, 0.66, 0.62, 0.58,
    0.54, 0.51, 0.48, 0.45, 0.42, 0.39, 0.37, 0.34, 0.31, 0.28,
    0.26, 0.24, 0.22, 0.20, 0.18, 0.16, 0.14, 0.12, 0.10, 0.08,
)  # fmt: skip

TOLERANCE_SWEEP: Final = (0.0005, 0.0009, 0.0018, 0.0032, 0.0061, 0.008, 0.012)

HOLD_SWEEP: Final = (1, 2, 3, 4, 5, 6)

_DEFAULT_CANDIDATES: Final[int] = quality.Tier(
    "probe", 1.0, 1, 0.0005, 0.0, 1.0, "probe"
).candidates
"""The ladder's own default, read off a throwaway rung rather than repeated.

A slots dataclass exposes a descriptor rather than the default on the class,
so the value has to come from an instance.
"""


@dataclass(frozen=True, slots=True)
class Point:
    """One measured setting: what it cost and how wrong it looked."""

    chroma_weight: float
    tolerance: float
    frame_hold: int
    cost: float
    error: float


def measure_point(
    clip: npt.NDArray[np.uint8],
    *,
    chroma_weight: float,
    tolerance: float,
    frame_hold: int,
    seed: int,
) -> Point:
    """Encode one setting against an already decoded clip."""
    sample_tiles = encode.to_tiles(neocolor.rgb_to_color_index(clip[::4])).reshape(-1, 16, 16)
    result = encode.encode_stream(
        [clip],
        encode.EncodeOptions(
            collect_rendered=False,
            chroma_weight=chroma_weight,
            frame_hold=frame_hold,
            tolerance=tolerance,
            seed=seed,
        ),
        sample_tiles=sample_tiles,
        total_frames=clip.shape[0],
    )
    minutes = clip.shape[0] / float(frames.VBLANK_FPS) / SECONDS_PER_MINUTE
    return Point(
        chroma_weight=chroma_weight,
        tolerance=tolerance,
        frame_hold=frame_hold,
        cost=result.stats.tile_count / minutes,
        error=result.stats.displayed_error,
    )


def frontier(points: Sequence[Point]) -> list[Point]:
    """Drop every setting beaten on cost and on error at once.

    What remains is the set worth having a rung for: each one is either
    cheaper or better than everything else that survived.
    """
    ranked = sorted(points, key=lambda entry: (entry.cost, entry.error))
    kept: list[Point] = []
    best_error = math.inf
    for entry in ranked:
        if entry.error < best_error:
            kept.append(entry)
            best_error = entry.error
    kept.reverse()
    return kept


def choose(measured: Sequence[Point], *, count: int) -> list[Point]:
    """Spread `count` rungs evenly through the measured cost range.

    Even spacing in cost, not in list position, is what makes a rung buy
    something: a frontier can crowd twenty settings into a few percent and
    leave a chasm below them.
    """
    if len(measured) <= count:
        return list(measured)
    top, bottom = measured[0].cost, measured[-1].cost
    step = (math.log(top) - math.log(bottom)) / (count - 1)
    taken: set[int] = set()
    for index in range(count):
        wanted = math.log(top) - step * index
        order = sorted(
            range(len(measured)),
            key=lambda position: abs(math.log(measured[position].cost) - wanted),
        )
        taken.add(next(position for position in order if position not in taken))
    return [measured[position] for position in sorted(taken)]


def _summary(entry: Point) -> str:
    colour = f"colour at {round(entry.chroma_weight * 100)}%"
    if entry.frame_hold == 1:
        return f"every frame, {colour}"
    fps = float(frames.VBLANK_FPS) / entry.frame_hold
    return f"{fps:.0f} fps, {colour}"


def to_tiers(measured: Sequence[Point], *, reference_cost: float) -> list[quality.Tier]:
    """Turn measured points into ladder rungs with costs relative to the reference.

    The top rung searches every palette rather than a shortlist. It is the
    rung chosen when nothing is being economised, so the one place where the
    shortlist's occasional wrong pick is not worth its speed.
    """
    return [
        quality.Tier(
            name=f"q{index + 1:02d}",
            candidates=0 if index == 0 else _DEFAULT_CANDIDATES,
            chroma_weight=entry.chroma_weight,
            frame_hold=entry.frame_hold,
            tolerance=entry.tolerance,
            denoise=0.0,
            relative_cost=entry.cost / reference_cost,
            summary=_summary(entry),
        )
        for index, entry in enumerate(measured)
    ]


def sweep(
    source: Path,
    *,
    count: int = calibrate.DEFAULT_SAMPLE_COUNT,
    seconds: float = calibrate.DEFAULT_SAMPLE_SECONDS,
    seed: int = 0,
) -> list[Point]:
    """Measure every setting in the grid against one source."""
    info = frames.probe(source)
    windows = calibrate.sample_windows(info.duration, count=count, seconds=seconds)
    clip = np.concatenate(
        [
            np.concatenate(list(frames.stream(source, start=offset, duration=span)))
            for offset, span in windows
        ]
    )

    points: list[Point] = []
    for chroma, tolerance in zip(CHROMA_SWEEP, _paired_tolerances(), strict=True):
        points.append(
            measure_point(clip, chroma_weight=chroma, tolerance=tolerance, frame_hold=1, seed=seed)
        )
    for hold in HOLD_SWEEP[1:]:
        points.append(
            measure_point(
                clip,
                chroma_weight=CHROMA_SWEEP[-1],
                tolerance=TOLERANCE_SWEEP[-1],
                frame_hold=hold,
                seed=seed,
            )
        )
    return points


def _paired_tolerances() -> list[float]:
    """Loosen the redraw threshold in step with the colour weight.

    The two levers move together: a picture already charged less for colour
    error has nothing to gain from being redrawn on a colour change too
    small to see.
    """
    span = len(CHROMA_SWEEP) - 1
    low, high = math.log(TOLERANCE_SWEEP[0]), math.log(TOLERANCE_SWEEP[-1])
    return [math.exp(low + (high - low) * index / span) for index in range(len(CHROMA_SWEEP))]
