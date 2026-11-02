from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
from fmvcore import ffmpeg

from neogeomedia import calibrate, encode, frames, neocolor, palettes, quality

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


@dataclass(frozen=True, slots=True)
class Point:
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
    dither: float = palettes.MAX_DITHER,
) -> Point:
    sample_tiles = encode.to_tiles(neocolor.rgb_to_color_index(clip[::4])).reshape(-1, 16, 16)
    result = encode.encode_stream(
        [clip],
        encode.EncodeOptions(
            collect_rendered=False,
            chroma_weight=chroma_weight,
            frame_hold=frame_hold,
            tolerance=tolerance,
            seed=seed,
            dither=dither,
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
    dither: float = palettes.MAX_DITHER,
) -> list[Point]:
    info = ffmpeg.probe(source)
    windows = calibrate.sample_windows(info.duration, count=count, seconds=seconds)
    clip = calibrate.windowed_clip(source, windows)
    colour_points = [
        measure_point(
            clip,
            chroma_weight=chroma,
            tolerance=tolerance,
            frame_hold=1,
            seed=seed,
            dither=dither,
        )
        for chroma, tolerance in zip(CHROMA_SWEEP, _paired_tolerances(), strict=True)
    ]
    hold_points = [
        measure_point(
            clip,
            chroma_weight=CHROMA_SWEEP[-1],
            tolerance=TOLERANCE_SWEEP[-1],
            frame_hold=hold,
            seed=seed,
            dither=dither,
        )
        for hold in HOLD_SWEEP[1:]
    ]
    return [*colour_points, *hold_points]


def _paired_tolerances() -> list[float]:
    span = len(CHROMA_SWEEP) - 1
    low, high = math.log(TOLERANCE_SWEEP[0]), math.log(TOLERANCE_SWEEP[-1])
    return [math.exp(low + (high - low) * index / span) for index in range(len(CHROMA_SWEEP))]
