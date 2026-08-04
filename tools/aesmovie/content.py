"""Measure the properties of a source that change what a good bake looks like.

Geometry analysis lives in `frames`, because a bake cannot proceed without
it. What is measured here is different: nothing breaks if it is skipped, but
the numbers say which settings are safe on this particular material.

Two measurements, each tied to one decision:

- Saturation, from `signalstats`. Colour weight is charged against the a and
  b axes of the metric, so on washed-out material a low weight costs little
  and on vivid material it costs a lot.
- Scene cuts, from `scdet`. Palettes are fitted per epoch, and an epoch that
  spans a cut has to serve two scenes with one set of colours.

Grain is deliberately absent. Two candidates were tried and both measured
high-frequency content rather than noise: chroma bitplane noise called a
pristine 720p capture grainier than a synthetic clip built out of noise, and
comparing a source against a temporally denoised copy ranked the noisy clip
as the cleaner of the two, because motion moves that measure further than
grain does. A grain number that fires on detail would argue for denoising the
very texture the dictionary exists to carry, so none is reported.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from aesmovie import frames

MIN_EPOCH_SECONDS: Final = 2.5
MAX_EPOCH_SECONDS: Final = 8.0
CUT_SCORE_THRESHOLD: Final = 10.0
SECONDS_PER_MINUTE: Final = 60.0

_METADATA = re.compile(r"lavfi\.(\S+)=([0-9.eE+-]+)")


@dataclass(frozen=True, slots=True)
class ContentProfile:
    """What the source is made of, as far as ffmpeg can tell."""

    saturation: float
    cuts_per_minute: float


def _metadata_values(path: Path, filter_spec: str, key: str, *, duration: float) -> list[float]:
    """Run a filter that prints metadata and collect one key from it."""
    result = subprocess.run(
        [
            frames.require_tool("ffmpeg"),
            "-hide_banner",
            "-v",
            "error",
            "-i",
            str(path),
            "-t",
            f"{duration:.6f}",
            "-vf",
            f"{filter_spec},metadata=print:file=-",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    return [float(value) for name, value in _METADATA.findall(result.stdout) if name.endswith(key)]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def measure(path: Path, *, duration: float = 8.0) -> ContentProfile:
    """Profile a source without decoding it into the encoder."""
    path = Path(path)

    saturation = _metadata_values(path, "signalstats", "SATAVG", duration=duration)
    scores = _metadata_values(
        path, f"scdet=threshold={CUT_SCORE_THRESHOLD}", "score", duration=duration
    )

    cuts = sum(1 for score in scores if score > CUT_SCORE_THRESHOLD)
    minutes = max(duration, 1e-6) / SECONDS_PER_MINUTE
    return ContentProfile(
        saturation=max(0.0, _mean(saturation)),
        cuts_per_minute=cuts / minutes,
    )


def epoch_seconds_for(*, cuts_per_minute: float) -> float:
    """How long a palette epoch should last on material that cuts this often.

    An epoch spanning a cut serves two scenes from one set of colours, so
    the cadence tracks the cut rate. It is bounded at both ends: the loader
    needs frames to upload the next set, and an epoch long enough to cover a
    whole reel stops being per-scene at all.
    """
    if cuts_per_minute <= 0.0:
        return MAX_EPOCH_SECONDS
    wanted = SECONDS_PER_MINUTE / cuts_per_minute
    return min(MAX_EPOCH_SECONDS, max(MIN_EPOCH_SECONDS, wanted))
