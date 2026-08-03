"""Match a geolith screenshot against the baker's own rendered frames.

The boot delay between powering the cart and the first movie frame is not
known ahead of time, so this searches every rendered frame for the one
that best matches the capture instead of assuming an offset. A near-zero
best match proves the whole chain agrees with the emulator: the packed
C-ROM bytes, the SCB attribute words, the palette upload, the run-coded
stream, and the player's VRAM writes.

The capture is cropped by geolith's overscan options, so the reference
frames are cropped the same way before comparison.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

RASTER_WIDTH = 320
RASTER_HEIGHT = 224


def _decode_rgb(path: Path) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    ).stdout


def decode_preview(path: Path) -> np.ndarray:
    """Every rendered frame from a lossless preview."""
    stride = RASTER_WIDTH * RASTER_HEIGHT * 3
    payload = _decode_rgb(path)
    return np.frombuffer(payload[: len(payload) // stride * stride], np.uint8).reshape(
        -1, RASTER_HEIGHT, RASTER_WIDTH, 3
    )


def decode_capture(path: Path) -> np.ndarray:
    """One screenshot at whatever geometry the emulator produced."""
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    width, height = (int(part) for part in probe.stdout.strip().split(","))
    return np.frombuffer(_decode_rgb(path), np.uint8).reshape(height, width, 3)


def downscale_capture(capture: np.ndarray) -> np.ndarray:
    """Undo the front end's integer upscale, if it applied one.

    RetroArch writes the screenshot at the window scale rather than at
    the emulated resolution, so a capture arrives as a whole multiple of
    the active area. Sampling the centre of each block recovers the
    original pixels exactly for nearest-neighbour scaling and stays
    representative for any other filter.
    """
    height, width = capture.shape[:2]
    if height % RASTER_HEIGHT != 0:
        return capture
    factor = height // RASTER_HEIGHT
    if factor < 2 or width % factor != 0:
        return capture
    offset = factor // 2
    return capture[offset::factor, offset::factor]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Match a capture against the baked render.")
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--overscan", type=int, default=8)
    parser.add_argument("--max-mean-error", type=float, default=1.0)
    args = parser.parse_args(argv)

    capture = decode_capture(args.capture)
    reference = decode_preview(args.preview)

    capture = downscale_capture(capture)

    height, width = capture.shape[:2]
    if height != RASTER_HEIGHT:
        print(
            f"capture height {height} is not the {RASTER_HEIGHT} line active area",
            file=sys.stderr,
        )
        return 2

    left = args.overscan
    right = RASTER_WIDTH - args.overscan
    if width != right - left:
        print(
            f"capture width {width} does not match a {args.overscan} pixel overscan",
            file=sys.stderr,
        )
        return 2

    cropped = reference[:, :, left:right, :].astype(np.int16)
    error = np.abs(cropped - capture.astype(np.int16)).mean(axis=(1, 2, 3))
    best = int(np.argmin(error))

    print(f"best match: rendered frame {best} of {len(reference)}")
    print(f"mean absolute error: {error[best]:.4f} of 255")
    print(f"exact pixel match: {np.array_equal(cropped[best].astype(np.uint8), capture)}")
    print(f"worst frame error: {error.max():.4f}, median {np.median(error):.4f}")

    if error[best] > args.max_mean_error:
        print(
            f"FAIL: best match error {error[best]:.4f} exceeds {args.max_mean_error}",
            file=sys.stderr,
        )
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
