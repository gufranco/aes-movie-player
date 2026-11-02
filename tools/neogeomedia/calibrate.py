from __future__ import annotations

from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
from fmvcore import ffmpeg

from neogeomedia import encode, frames, neocolor, palettes, quality

DEFAULT_SAMPLE_COUNT: int = 24
DEFAULT_SAMPLE_SECONDS: float = 3.0
SAMPLE_EVERY: Final = 4


def sample_windows(duration: float, *, count: int, seconds: float) -> list[tuple[float, float]]:
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


def windowed_clip(
    source: Path,
    windows: list[tuple[float, float]],
    *,
    start: float = 0.0,
) -> npt.NDArray[np.uint8]:
    return np.concatenate(
        [
            np.concatenate(list(frames.stream(source, start=start + offset, duration=span)))
            for offset, span in windows
        ]
    )


def _source_clip(
    source: Path,
    info: ffmpeg.SourceInfo,
    *,
    count: int,
    seconds: float,
    start: float,
    duration: float | None,
) -> npt.NDArray[np.uint8]:
    span_total = info.duration - start
    if duration is not None:
        span_total = min(span_total, duration)
    windows = sample_windows(span_total, count=count, seconds=seconds)
    return windowed_clip(source, windows, start=start)


def _minutes(clip: npt.NDArray[np.uint8]) -> float:
    frames_kept: int = clip.shape[0]
    return frames_kept / float(frames.VBLANK_FPS) / quality.SECONDS_PER_MINUTE


def measure_reference_rate(
    source: Path,
    *,
    count: int = DEFAULT_SAMPLE_COUNT,
    seconds: float = DEFAULT_SAMPLE_SECONDS,
    seed: int = 0,
    start: float = 0.0,
    duration: float | None = None,
    dither: float = palettes.MAX_DITHER,
) -> float:
    source = Path(source)
    clip = _source_clip(
        source,
        ffmpeg.probe(source),
        count=count,
        seconds=seconds,
        start=start,
        duration=duration,
    )
    tier = quality.tier_by_name(quality.REFERENCE_TIER)
    rate: float = _encode_rate(clip, tier, seed=seed, dither=dither) / _minutes(clip)
    return rate


def measure_anchors(
    source: Path,
    *,
    count: int = DEFAULT_SAMPLE_COUNT,
    seconds: float = DEFAULT_SAMPLE_SECONDS,
    seed: int = 0,
    start: float = 0.0,
    duration: float | None = None,
) -> tuple[float, dict[float, float]]:
    source = Path(source)
    info = ffmpeg.probe(source)
    clip = _source_clip(source, info, count=count, seconds=seconds, start=start, duration=duration)
    minutes = _minutes(clip)
    anchors = quality.anchor_tiers(float(info.fps), float(frames.VBLANK_FPS))
    rates = [(tier, _encode_rate(clip, tier, seed=seed) / minutes) for tier in anchors]
    measured = {tier.relative_cost: rate for tier, rate in rates}
    reference = [rate for tier, rate in rates if tier.name == quality.REFERENCE_TIER]
    reference_rate = reference[-1] if reference else 0.0
    return reference_rate, {rung: rate / reference_rate for rung, rate in measured.items()}


def _encode_rate(
    clip: npt.NDArray[np.uint8],
    tier: quality.Tier,
    *,
    seed: int,
    dither: float = palettes.MAX_DITHER,
) -> float:
    sample = encode.to_tiles(neocolor.rgb_to_color_index(clip[::SAMPLE_EVERY]))
    result = encode.encode_stream(
        [clip],
        encode.EncodeOptions(
            collect_rendered=False,
            chroma_weight=tier.chroma_weight,
            frame_hold=tier.frame_hold,
            tolerance=tier.tolerance,
            seed=seed,
            dither=dither,
        ),
        sample_tiles=sample.reshape(-1, encode.TILE_PX, encode.TILE_PX),
        total_frames=clip.shape[0],
    )
    return float(result.stats.tile_count)
