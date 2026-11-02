from __future__ import annotations

import argparse
import struct
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify_capture as vc

from neogeomedia import neocolor
from tests.geolith_model import GeolithTileReader, StreamPlayer

VIDEO_BASE_BANK = 16

_TIE = 1e-9


def _both_halves(epoch: int, colors: np.ndarray) -> np.ndarray:
    half = colors.shape[0]
    both = np.zeros((half * 2, *colors.shape[1:]), dtype=colors.dtype)
    start = (epoch & 1) * half
    both[start : start + half] = colors
    return both


class Movie(NamedTuple):
    stream: bytes
    offsets: tuple[int, ...]
    reader: GeolithTileReader
    base: np.ndarray


class Search(NamedTuple):
    best_error: float
    best_frame: int | None
    scored: dict[int, float]


def _load(baked: Path) -> Movie:
    index = (baked / "index.bin").read_bytes()
    return Movie(
        stream=(baked / "stream.bin").read_bytes(),
        offsets=struct.unpack(f">{len(index) // 4}I", index),
        reader=GeolithTileReader((baked / "c1.bin").read_bytes(), (baked / "c2.bin").read_bytes()),
        base=vc._palette_colors((baked / "palettes.bin").read_bytes()),
    )


def _prefer(error: float, step: int, best: tuple[float, int | None], expected: int) -> bool:
    best_error, best_frame = best
    if error < best_error - _TIE:
        return True
    return (
        abs(error - best_error) <= _TIE
        and best_frame is not None
        and abs(step - expected) < abs(best_frame - expected)
    )


def _errors(
    baked: Path, movie: Movie, target: np.ndarray, steps: range, columns: slice
) -> Iterator[tuple[int, float]]:
    player = StreamPlayer()
    for step in range(steps.stop):
        player.apply(movie.stream, movie.offsets[step])
        if step < steps.start:
            continue
        epoch, colors = vc._epoch_palettes(baked, step, movie.base)
        painted = player.render(movie.reader, _both_halves(epoch, colors), VIDEO_BASE_BANK)
        rgb = neocolor.color_index_to_rgb(painted)
        yield step, float(np.abs(rgb[:, columns, :].astype(np.int16) - target).mean())


def _search(
    baked: Path, movie: Movie, target: np.ndarray, *, expected: int, window: int, columns: slice
) -> Search:
    low = max(0, expected - window)
    high = min(len(movie.offsets) - 1, expected + window)
    scored = dict(_errors(baked, movie, target, range(low, high + 1), columns))
    best: tuple[float, int | None] = (float("inf"), None)
    for step, error in scored.items():
        if _prefer(error, step, best, expected):
            best = (min(best[0], error), step)
    return Search(best_error=best[0], best_frame=best[1], scored=scored)


def _ambiguous(found: Search, best_frame: int, separation: float) -> bool:
    run = vc.tied_run(found.scored, best_frame)
    rivals = {step: error for step, error in found.scored.items() if step not in run}
    if not rivals:
        return False
    contender = min(rivals, key=lambda step: rivals[step])
    margin = rivals[contender] - found.best_error
    print(f"nearest rival at frame {contender}, error {rivals[contender]:.4f}, margin {margin:.4f}")
    if margin >= separation:
        return False
    print(
        f"ambiguous: the rival is within {separation:.4f} of the best match, "
        "so this scan cannot say where the player is"
    )
    return True


def measure(
    baked: Path,
    capture: Path,
    expected: int,
    window: int,
    overscan: int,
    *,
    separation: float = 1.0,
) -> int | None:
    shot = vc.downscale_capture(vc.decode_capture(capture))
    columns = slice(overscan, vc.RASTER_WIDTH - overscan)
    found = _search(
        baked,
        _load(baked),
        shot.astype(np.int16),
        expected=expected,
        window=window,
        columns=columns,
    )
    print(f"capture taken after {expected} vblanks")
    if found.best_frame is None:
        return None
    print(f"best match at movie frame {found.best_frame}, error {found.best_error:.4f} of 255")
    if _ambiguous(found, found.best_frame, separation):
        return None
    behind = expected - found.best_frame
    print(f"player is {behind} frames behind, {behind / max(expected, 1):.4%} of the run")
    return found.best_frame


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure player drift against the raster.")
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--baked", type=Path, default=Path("build/baked"))
    parser.add_argument("--expected", type=int, required=True)
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--overscan", type=int, default=8)
    parser.add_argument("--min-separation", type=float, default=1.0)
    args = parser.parse_args(argv)

    found = measure(
        args.baked,
        args.capture,
        args.expected,
        args.window,
        args.overscan,
        separation=args.min_separation,
    )
    return 0 if found is not None else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
