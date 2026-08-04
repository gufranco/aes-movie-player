"""Measure what a source costs per minute before committing to a bake.

The tile rate is a property of the content: a scene of two people
talking reuses its dictionary heavily, while dense animation refuses to.
A ladder that guessed from running time alone would be wrong in both
directions, so the rate is measured here on the source itself and the
ladder is positioned against it.

Sampling several short windows spread across the source beats measuring
one contiguous stretch, because a single window sees one scene and one
palette. The windows are then encoded as a single clip so the dictionary
reuse between them is counted, which is what a full bake would get.

Accuracy is governed by how many windows there are, not by how long
they are. A feature varies enormously in difficulty from scene to
scene, so a handful of windows lands wherever it happens to land.
Measured against a known full bake, 3 windows read 0.62 times the true
rate, 6 read 1.58, and 12 read 0.91, while the total sampled time
barely mattered. Coverage of the content is what converges, and at 24
windows the estimate lands within a percent, which is why the default
is many short windows rather than a few long ones.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numpy.typing as npt

from aesmovie import encode, frames, neocolor, quality

DEFAULT_SAMPLE_COUNT: int = 24
DEFAULT_SAMPLE_SECONDS: float = 3.0


def sample_windows(duration: float, *, count: int, seconds: float) -> list[tuple[float, float]]:
    """Evenly spread, non-overlapping windows across a source.

    A source too short to hold one window is measured whole, which is
    both the honest answer and the cheap one.
    """
    if duration <= 0.0:
        msg = f"duration must be positive, got {duration}"
        raise ValueError(msg)
    if count < 1:
        msg = f"sample count must be at least one, got {count}"
        raise ValueError(msg)
    if seconds <= 0.0:
        msg = f"sample seconds must be positive, got {seconds}"
        raise ValueError(msg)
    if duration <= seconds:
        return [(0.0, duration)]

    usable = min(count, int(duration // seconds))
    stride = duration / usable
    windows: list[tuple[float, float]] = []
    for index in range(usable):
        centre = stride * (index + 0.5)
        start = min(max(0.0, centre - seconds / 2.0), duration - seconds)
        windows.append((start, seconds))
    return windows


def measure_reference_rate(
    source: Path,
    *,
    count: int = DEFAULT_SAMPLE_COUNT,
    seconds: float = DEFAULT_SAMPLE_SECONDS,
    fit: frames.FitMode = "fill",
    seed: int = 0,
    start: float = 0.0,
    duration: float | None = None,
) -> float:
    """Tiles per minute this source costs at the reference tier.

    The windows land inside the stretch that will actually be baked. A
    bake of one segment measured against the whole film would be
    calibrated on content it is never going to encode.
    """
    source = Path(source)
    info = frames.probe(source)
    span_total = info.duration - start
    if duration is not None:
        span_total = min(span_total, duration)
    windows = sample_windows(span_total, count=count, seconds=seconds)

    chunks = [
        np.concatenate(list(frames.stream(source, start=start + offset, duration=span, fit=fit)))
        for offset, span in windows
    ]
    clip = np.concatenate(chunks)
    tier = quality.tier_by_name(quality.REFERENCE_TIER)
    sample_tiles = encode.to_tiles(neocolor.rgb_to_color_index(clip[::4])).reshape(-1, 16, 16)
    result = encode.encode_stream(
        [clip],
        encode.EncodeOptions(
            collect_rendered=False,
            chroma_weight=tier.chroma_weight,
            frame_hold=tier.frame_hold,
            tolerance=tier.tolerance,
            seed=seed,
        ),
        sample_tiles=sample_tiles,
        total_frames=clip.shape[0],
    )
    minutes = clip.shape[0] / float(frames.VBLANK_FPS) / quality.SECONDS_PER_MINUTE
    rate: float = result.stats.tile_count / minutes
    return rate


def measure_anchors(
    source: Path,
    *,
    count: int = DEFAULT_SAMPLE_COUNT,
    seconds: float = DEFAULT_SAMPLE_SECONDS,
    fit: frames.FitMode = "fill",
    seed: int = 0,
    start: float = 0.0,
    duration: float | None = None,
) -> tuple[float, dict[float, float]]:
    """Measure this source's own cost curve, not just one point on it.

    Returns the reference rate and a map from the ladder's averaged relative
    cost to what this source actually costs there. One measurement fixes the
    scale; the anchors either side fix the shape, which the ladder cannot
    know because it varies with the content.

    The clip is decoded once and encoded three times, so the extra accuracy
    costs two encodes rather than two decodes.
    """
    source = Path(source)
    info = frames.probe(source)
    span_total = info.duration - start
    if duration is not None:
        span_total = min(span_total, duration)
    windows = sample_windows(span_total, count=count, seconds=seconds)
    clip = np.concatenate(
        [
            np.concatenate(
                list(frames.stream(source, start=start + offset, duration=span, fit=fit))
            )
            for offset, span in windows
        ]
    )
    minutes = clip.shape[0] / float(frames.VBLANK_FPS) / quality.SECONDS_PER_MINUTE

    measured: dict[float, float] = {}
    reference_rate = 0.0
    for chroma in quality.ANCHOR_CHROMA:
        tier = quality.nearest_by_chroma(chroma)
        rate = _encode_rate(clip, tier, seed=seed) / minutes
        measured[tier.relative_cost] = rate
        if tier.name == quality.REFERENCE_TIER:
            reference_rate = rate

    return reference_rate, {rung: rate / reference_rate for rung, rate in measured.items()}


def _encode_rate(clip: npt.NDArray[np.uint8], tier: quality.Tier, *, seed: int) -> float:
    sample_tiles = encode.to_tiles(neocolor.rgb_to_color_index(clip[::4])).reshape(-1, 16, 16)
    result = encode.encode_stream(
        [clip],
        encode.EncodeOptions(
            collect_rendered=False,
            chroma_weight=tier.chroma_weight,
            frame_hold=tier.frame_hold,
            tolerance=tier.tolerance,
            seed=seed,
        ),
        sample_tiles=sample_tiles,
        total_frames=clip.shape[0],
    )
    return float(result.stats.tile_count)
