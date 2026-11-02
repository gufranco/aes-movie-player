from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
from fmvcore import colour

from neogeomedia import encode, frames, neocolor, palettes, quality

CANDIDATES: Final = (0.0, 1.0, 2.0, 4.0)
WINDOW_SECONDS: Final = 2.0
NEAR_TIE: Final = 0.01


@dataclass(frozen=True, slots=True)
class Score:
    strength: float
    error: float
    tiles: int


def choose(scores: Sequence[Score]) -> Score:
    if not scores:
        msg = "no denoise strength was measured"
        raise ValueError(msg)
    best = min(scores, key=lambda score: score.error)
    close = [score for score in scores if score.error <= best.error * (1.0 + NEAR_TIE)]
    return min(close, key=lambda score: (score.tiles, score.error))


@dataclass(frozen=True, slots=True)
class _Trial:
    source: Path
    tier: quality.Tier
    start: float
    window: float
    reference: np.ndarray
    dither: float


def measure(
    source: Path,
    tier: quality.Tier,
    *,
    start: float,
    window: float = WINDOW_SECONDS,
    candidates: Sequence[float] = CANDIDATES,
    dither: float = palettes.MAX_DITHER,
) -> list[Score]:
    reference = frames.decode(source, start=start, duration=window)
    trial = _Trial(source, tier, start, window, reference, dither)
    return [_score(trial, strength) for strength in candidates]


def _score(trial: _Trial, strength: float) -> Score:
    clip = frames.decode(trial.source, start=trial.start, duration=trial.window, denoise=strength)
    result = encode.encode(clip, _options(trial.tier, trial.dither))
    shown = neocolor.color_index_to_rgb(result.rendered)
    error = colour.blurred_error(shown, trial.reference[: shown.shape[0]])
    return Score(strength=strength, error=error, tiles=result.stats.tile_count)


def _options(tier: quality.Tier, dither: float) -> encode.EncodeOptions:
    return encode.EncodeOptions(
        tolerance=tier.tolerance,
        candidates=tier.candidates,
        chroma_weight=tier.chroma_weight,
        frame_hold=tier.frame_hold,
        dither=dither,
    )
