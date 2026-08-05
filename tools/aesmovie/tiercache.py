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

The file lives at the top of the project rather than in a user cache,
because what it holds is a property of the film and the ladder rather
than of one workstation. Committing it lets everyone building the same
cartridge skip the same bakes. It is written sorted and one field per
line so a diff reads, and each entry carries the file name and the
window beside the readings, since a key that is only a hash tells a
reviewer nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from aesmovie import quality

SAMPLE_BYTES = 1 << 20
CACHE_VERSION = 3
STORE_NAME = "aesmovie-tiers.json"


@dataclass(frozen=True, slots=True)
class Params:
    """Everything outside the tier that changes what a bake costs."""

    start: float
    duration: float
    fit: str
    denoise: float
    frame_hold: int


def default_store() -> Path:
    """The versionable file at the top of the project."""
    return Path(__file__).resolve().parents[2] / STORE_NAME


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


def _read(store: Path) -> dict[str, dict[str, object]]:
    """Every entry in the file, or nothing if it is absent or foreign."""
    try:
        loaded = json.loads(Path(store).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict) or loaded.get("version") != CACHE_VERSION:
        return {}
    sources = loaded.get("sources")
    return sources if isinstance(sources, dict) else {}


def _write(store: Path, sources: dict[str, dict[str, object]]) -> None:
    store = Path(store)
    store.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": CACHE_VERSION, "sources": sources}
    store.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def recall(store: Path, key: str) -> dict[str, float | None]:
    """What is settled about this source.

    A number is the rate that tier really cost, in tiles per minute. A
    null is a rung that was baked and overran, which is worth keeping so
    it is never baked again.
    """
    entry = _read(store).get(key, {})
    tiers = entry.get("tiers")
    return dict(tiers) if isinstance(tiers, dict) else {}


def remember(store: Path, key: str, tier: str, tiles_per_minute: float | None) -> None:
    """Record one settled rung, leaving the others alone."""
    known = _read(store)
    entry = known.setdefault(key, {})
    tiers = entry.get("tiers")
    if not isinstance(tiers, dict):
        tiers = {}
        entry["tiers"] = tiers
    tiers[tier] = None if tiles_per_minute is None else float(tiles_per_minute)
    _write(store, known)


def describe(
    store: Path, key: str, *, source: Path, params: Params, chosen: str | None = None
) -> None:
    """Name the entry, so a reviewer reading the file knows what it is about.

    The key is a hash and stays a hash, because the file name is not
    stable enough to key on. These fields sit beside it for people.
    """
    known = _read(store)
    entry = known.setdefault(key, {})
    entry["file"] = Path(source).name
    entry["digest"] = content_digest(Path(source))
    entry["window"] = asdict(params)
    if chosen is not None:
        entry["quality"] = chosen
    _write(store, known)


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
