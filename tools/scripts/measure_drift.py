"""Report how far the player's frame counter has fallen behind the raster.

A capture taken after N vblanks should show movie frame N. Any shortfall is
the player missing its deadline: the movie advances one frame per vblank it
survives, and a frame whose work overruns costs a whole extra vblank. The
sound chip does not wait, so the shortfall measured here is the gap the ear
eventually hears.

The stream is replayed once and every candidate in the window is scored
against the same pass, rather than replaying from the start per candidate.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify_capture as vc

from aesmovie import neocolor

# The menu owns the first sixteen palettes, so video starts above them.
VIDEO_BASE_BANK = 16

_TIE = 1e-9
"""Errors this close are the same picture, not a better one."""


def _both_halves(epoch: int, colors: np.ndarray) -> np.ndarray:
    """Place an epoch's palettes in the CRAM half it occupies.

    A scan crosses epoch boundaries, and a slot interned under the previous
    epoch still points into the other half. Rendering both halves lets that
    slot resolve to black and score badly rather than raise, which is what a
    search wants: the wrong candidate should lose, not stop the scan.
    """
    half = colors.shape[0]
    both = np.zeros((half * 2, *colors.shape[1:]), dtype=colors.dtype)
    start = (epoch & 1) * half
    both[start : start + half] = colors
    return both


def _tied_run(errors: dict[int, float], best: int) -> set[int]:
    run = {best}
    step = best
    while step - 1 in errors and abs(errors[step - 1] - errors[best]) <= _TIE:
        step -= 1
        run.add(step)
    step = best
    while step + 1 in errors and abs(errors[step + 1] - errors[best]) <= _TIE:
        step += 1
        run.add(step)
    return run


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
    target = shot.astype(np.int16)
    left = overscan
    right = vc.RASTER_WIDTH - overscan

    stream = (baked / "stream.bin").read_bytes()
    index = (baked / "index.bin").read_bytes()
    offsets = struct.unpack(f">{len(index) // 4}I", index)
    reader = vc.GeolithTileReader((baked / "c1.bin").read_bytes(), (baked / "c2.bin").read_bytes())
    base = vc._palette_colors((baked / "palettes.bin").read_bytes())

    low = max(0, expected - window)
    high = min(len(offsets) - 1, expected + window)
    player = vc.StreamPlayer()
    best_error, best_frame = float("inf"), None
    scored: dict[int, float] = {}

    for step in range(high + 1):
        player.apply(stream, offsets[step])
        if step < low:
            continue
        epoch, colors = vc._epoch_palettes(baked, step, base)
        painted = player.render(reader, _both_halves(epoch, colors), VIDEO_BASE_BANK)
        rgb = neocolor.color_index_to_rgb(painted)
        error = float(np.abs(rgb[:, left:right, :].astype(np.int16) - target).mean())
        scored[step] = error
        if error < best_error - _TIE:
            best_error, best_frame = error, step
        # A static shot repeats itself exactly, so the match is a run of
        # frames rather than one. The player is somewhere in that run, and
        # the only defensible pick is the end nearest where it should be.
        elif (
            abs(error - best_error) <= _TIE
            and best_frame is not None
            and abs(step - expected) < abs(best_frame - expected)
        ):
            best_error, best_frame = min(best_error, error), step

    print(f"capture taken after {expected} vblanks")
    if best_frame is None:
        return None
    print(f"best match at movie frame {best_frame}, error {best_error:.4f} of 255")

    run = _tied_run(scored, best_frame)
    rivals = {step: error for step, error in scored.items() if step not in run}
    if rivals:
        contender = min(rivals, key=lambda step: rivals[step])
        margin = rivals[contender] - best_error
        print(
            f"nearest rival at frame {contender}, "
            f"error {rivals[contender]:.4f}, margin {margin:.4f}"
        )
        if margin < separation:
            print(
                f"ambiguous: the rival is within {separation:.4f} of the best match, "
                "so this scan cannot say where the player is"
            )
            return None

    behind = expected - best_frame
    print(f"player is {behind} frames behind, {behind / max(expected, 1):.4%} of the run")
    return best_frame


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
