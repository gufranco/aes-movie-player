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

A reading is stored against the window it measured, start and duration
included in the key, because a rate taken over ten minutes says nothing
certain about sixty: a film's second hour is not as busy as its first.
Widening the window asks a new question and gets a fresh bake.

What is stored per rung is a rate rather than a verdict, so the same
reading answers both "does this fit" and "by how much".
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from aesmovie import quality

SAMPLE_BYTES = 1 << 20
CACHE_VERSION = 2


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


def _read(store: Path) -> dict[str, dict[str, float | None]]:
    try:
        loaded = json.loads(Path(store).read_text())
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def recall(store: Path, key: str) -> dict[str, float | None]:
    """What is settled about this source.

    A number is the rate that tier really cost, in tiles per minute. A
    null is a rung that was baked and overran, which is worth keeping so
    it is never baked again.
    """
    return dict(_read(store).get(key, {}))


def remember(store: Path, key: str, tier: str, tiles_per_minute: float | None) -> None:
    """Record one settled rung, leaving the others alone."""
    store = Path(store)
    known = _read(store)
    value = None if tiles_per_minute is None else float(tiles_per_minute)
    known.setdefault(key, {})[tier] = value
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(known, indent=2, sort_keys=True))


def settled(rates: Mapping[str, float | None], tier: quality.Tier) -> bool:
    """Whether this rung has already been baked for this source."""
    return tier.name in rates


def fits(rates: Mapping[str, float | None], tier: quality.Tier) -> bool:
    """Whether a settled rung fit. Meaningless for an unsettled one."""
    return rates.get(tier.name) is not None


def best_known_fit(
    rates: Mapping[str, float | None],
    *,
    source_fps: float | None = None,
    vblank_fps: float | None = None,
) -> quality.Tier | None:
    """The best rung already proved to fit, without predicting anything.

    Walks from the best rung down and stops at the first that is both
    settled and fitting. A rung that has never been baked stops the walk
    rather than being guessed at, because an unsettled rung above the
    answer is exactly what still needs measuring.
    """
    for tier in quality.LADDER:
        if source_fps is not None and vblank_fps is not None:  # noqa: SIM102
            if not quality.reachable(tier, source_fps=source_fps, vblank_fps=vblank_fps):
                continue
        if not settled(rates, tier):
            return None
        if fits(rates, tier):
            return tier
    return None
