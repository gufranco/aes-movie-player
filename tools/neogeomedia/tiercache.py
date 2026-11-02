from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from neogeomedia import quality

SAMPLE_BYTES = 1 << 20
CACHE_VERSION = 4
STORE_NAME = "neogeomedia-tiers.json"


@dataclass(frozen=True, slots=True)
class Params:
    start: float
    duration: float
    denoise: float
    frame_hold: int
    dither: float


def default_store() -> Path:
    return Path(__file__).resolve().parents[2] / STORE_NAME


def content_digest(source: Path) -> str:
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
    try:
        loaded = json.loads(Path(store).read_text())
    except OSError, ValueError:
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
    entry = _read(store).get(key, {})
    tiers = entry.get("tiers")
    return dict(tiers) if isinstance(tiers, dict) else {}


def remember(store: Path, key: str, tier: str, tiles_per_minute: float | None) -> None:
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
    known = _read(store)
    entry = known.setdefault(key, {})
    entry["file"] = Path(source).name
    entry["digest"] = content_digest(Path(source))
    entry["window"] = asdict(params)
    if chosen is not None:
        entry["quality"] = chosen
    _write(store, known)


def settled(rates: Mapping[str, float | None], tier: quality.Tier) -> bool:
    return tier.name in rates


def fits(rates: Mapping[str, float | None], tier: quality.Tier) -> bool:
    return rates.get(tier.name) is not None


def best_known_fit(
    rates: Mapping[str, float | None],
    *,
    source_fps: float | None = None,
    vblank_fps: float | None = None,
) -> quality.Tier | None:
    for tier in quality.LADDER:
        if source_fps is not None and vblank_fps is not None:  # noqa: SIM102
            if not quality.reachable(tier, source_fps=source_fps, vblank_fps=vblank_fps):
                continue
        if not settled(rates, tier):
            return None
        if fits(rates, tier):
            return tier
    return None
