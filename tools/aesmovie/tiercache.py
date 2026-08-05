"""Remember what a source actually cost, so it is measured once and never guessed.

Calibration samples short windows and extrapolates, and it is biased by
construction: every window starts with a cold dictionary where almost
every slot mints a tile, while a full bake amortises reuse across the
whole film. Measured against a real bake it read 946,352 tiles where the
encoder spent 846,784.

A bake is about eight minutes for a ten minute source, only four times
what calibration costs, so measuring the real thing is affordable. What
makes it worth doing once is this: the reading is stored against the
source's own bytes, and every later run reads it back instead of
sampling anything.

Rates are kept per tier rather than as a verdict. A verdict answers one
runtime; a rate answers every runtime, so trimming or extending the
window later needs no bake at all.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from aesmovie import quality

SAMPLE_BYTES = 1 << 20
CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class Params:
    """Everything outside the tier that changes what a bake costs."""

    start: float
    duration: float
    fit: str
    denoise: float
    frame_hold: int


def default_store() -> Path:
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / "aesmovie" / "tiers.json"


def content_digest(source: Path) -> str:
    """A cheap fingerprint of the bytes rather than of the name.

    Hashing a whole feature would cost more than the bake it saves, so
    this reads the head and the tail and mixes in the length. A rename
    keeps the key, an edit loses it, and two files that differ only deep
    in the middle at exactly the same length would collide, which is a
    trade the cost of the alternative earns.
    """
    source = Path(source)
    size = source.stat().st_size
    digest = hashlib.sha256(str(size).encode())
    with source.open("rb") as handle:
        digest.update(handle.read(SAMPLE_BYTES))
        if size > SAMPLE_BYTES:
            handle.seek(max(0, size - SAMPLE_BYTES))
            digest.update(handle.read(SAMPLE_BYTES))
    return digest.hexdigest()


def key_for(source: Path, params: Params) -> str:
    payload = json.dumps(asdict(params), sort_keys=True)
    return hashlib.sha256(
        f"{CACHE_VERSION}:{content_digest(source)}:{payload}".encode()
    ).hexdigest()


def _read(store: Path) -> dict[str, dict[str, float]]:
    try:
        loaded = json.loads(Path(store).read_text())
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def recall(store: Path, key: str) -> dict[str, float]:
    """Every tier rate known for this source, in tiles per minute."""
    return dict(_read(store).get(key, {}))


def remember(store: Path, key: str, tier: str, tiles_per_minute: float) -> None:
    """Record what one tier actually cost, leaving other readings alone."""
    store = Path(store)
    known = _read(store)
    known.setdefault(key, {})[tier] = float(tiles_per_minute)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(known, indent=2, sort_keys=True))


def nearest_measured(rates: dict[str, float], tier: quality.Tier) -> str | None:
    """The measured rung closest in cost to the one being asked about."""
    if not rates:
        return None
    return min(
        rates,
        key=lambda name: abs(quality.tier_by_name(name).relative_cost - tier.relative_cost),
    )


def predict(rates: dict[str, float], tier: quality.Tier, minutes: float) -> float | None:
    """Tiles this tier would spend, from readings rather than from a sample.

    A rung that was measured answers for itself. Any other is scaled from
    the closest reading by the ladder's own ratio, which the sweep put
    within a couple of percent across the colour rungs.
    """
    if tier.name in rates:
        return rates[tier.name] * minutes
    anchor = nearest_measured(rates, tier)
    if anchor is None:
        return None
    known = quality.tier_by_name(anchor)
    return rates[anchor] * (tier.relative_cost / known.relative_cost) * minutes


def best_fitting(
    rates: dict[str, float],
    *,
    minutes: float,
    budget: int,
    source_fps: float | None = None,
    vblank_fps: float | None = None,
) -> quality.Tier | None:
    """The best rung whose measured cost stays inside the budget."""
    for tier in quality.LADDER:
        if (
            source_fps is not None
            and vblank_fps is not None
            and not quality.reachable(tier, source_fps=source_fps, vblank_fps=vblank_fps)
        ):
            continue
        cost = predict(rates, tier, minutes)
        if cost is None:
            return None
        if cost <= budget:
            return tier
    return None
