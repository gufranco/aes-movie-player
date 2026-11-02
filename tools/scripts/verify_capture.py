from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import IO, NamedTuple, cast

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neogeomedia import neocolor
from tests.geolith_model import GeolithTileReader, StreamPlayer

RASTER_WIDTH = 320
RASTER_HEIGHT = 224
MIN_SCALE_FACTOR = 2

TIE = 1e-9


def tied_run(scored: dict[int, float], best: int) -> set[int]:
    run = {best}
    for direction in (-1, 1):
        step = best
        while step + direction in scored and abs(scored[step + direction] - scored[best]) <= TIE:
            step += direction
            run.add(step)
    return run


def _decode_rgb(path: Path) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    ).stdout


def stream_preview(path: Path) -> Iterator[np.ndarray]:
    stride = RASTER_WIDTH * RASTER_HEIGHT * 3
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    output = cast("IO[bytes]", process.stdout)
    try:
        while True:
            payload = output.read(stride)
            if len(payload) < stride:
                return
            yield np.frombuffer(payload, np.uint8).reshape(RASTER_HEIGHT, RASTER_WIDTH, 3)
    finally:
        output.close()
        process.wait()


def decode_capture(path: Path) -> np.ndarray:
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
    height, width = capture.shape[:2]
    if height % RASTER_HEIGHT != 0:
        return capture
    factor = height // RASTER_HEIGHT
    if factor < MIN_SCALE_FACTOR or width % factor != 0:
        return capture
    offset = factor // 2
    return capture[offset::factor, offset::factor]


def _palette_colors(blob: bytes) -> np.ndarray:
    words = np.frombuffer(blob, ">u2").reshape(-1, neocolor.PALETTE_COLORS)[:, 1:]
    r5 = ((words >> 8) & 0x0F) << 1 | ((words >> 14) & 1)
    g5 = ((words >> 4) & 0x0F) << 1 | ((words >> 13) & 1)
    b5 = (words & 0x0F) << 1 | ((words >> 12) & 1)
    return ((r5 << 10) | (g5 << 5) | b5).astype(np.uint16)


def _epoch_palettes(baked: Path, frame: int, colors: np.ndarray) -> tuple[int, np.ndarray]:
    table = baked / "epochs.bin"
    if not table.is_file():
        return 0, colors
    starts = struct.unpack(f">{table.stat().st_size // 4}I", table.read_bytes())
    if len(starts) <= 1:
        return 0, colors
    epoch = 0
    while epoch + 1 < len(starts) and starts[epoch + 1] <= frame:
        epoch += 1
    per_epoch = colors.shape[0] // len(starts)
    return epoch, colors[epoch * per_epoch : (epoch + 1) * per_epoch]


def reconstruct_frame(baked: Path, frame: int, *, base_bank: int = 16) -> np.ndarray:
    baked = Path(baked)
    stream = (baked / "stream.bin").read_bytes()
    index = (baked / "index.bin").read_bytes()
    offsets = struct.unpack(f">{len(index) // 4}I", index)
    if not 0 <= frame < len(offsets):
        msg = f"frame {frame} is outside the {len(offsets)} frame movie"
        raise ValueError(msg)

    player = StreamPlayer()
    for step in range(frame + 1):
        player.apply(stream, offsets[step])

    reader = GeolithTileReader((baked / "c1.bin").read_bytes(), (baked / "c2.bin").read_bytes())
    colors = _palette_colors((baked / "palettes.bin").read_bytes())
    epoch, colors = _epoch_palettes(baked, frame, colors)
    return neocolor.color_index_to_rgb(
        player.render(reader, colors, base_bank + (epoch & 1) * colors.shape[0])
    )


class Scan(NamedTuple):
    best: int
    best_error: float
    best_frame: np.ndarray | None
    seen: int
    worst: float
    scored: dict[int, float]


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Match a capture against the baked render.")
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--preview", type=Path, default=None)
    parser.add_argument("--baked", type=Path, default=None)
    parser.add_argument("--frame", type=int, default=None)
    parser.add_argument("--overscan", type=int, default=8)
    parser.add_argument("--max-mean-error", type=float, default=1.0)
    parser.add_argument("--min-separation", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.preview is None and args.baked is None:
        parser.error("pass either --preview or --baked")
    if args.baked is not None and args.frame is None:
        parser.error("--baked needs --frame")
    return args


def _geometry_complaint(capture: np.ndarray, overscan: int) -> str | None:
    height, width = capture.shape[:2]
    if height != RASTER_HEIGHT:
        return f"capture height {height} is not the {RASTER_HEIGHT} line active area"
    if width != RASTER_WIDTH - 2 * overscan:
        return f"capture width {width} does not match a {overscan} pixel overscan"
    return None


def _scan(reference: Iterator[np.ndarray], capture: np.ndarray, overscan: int) -> Scan:
    target = capture.astype(np.int16)
    best, best_error, best_frame, count = -1, float("inf"), None, 0
    worst = 0.0
    scored: dict[int, float] = {}
    for index, frame in enumerate(reference):
        cropped = frame[:, overscan : RASTER_WIDTH - overscan, :].astype(np.int16)
        error = float(np.abs(cropped - target).mean())
        scored[index] = error
        worst = max(worst, error)
        if error < best_error:
            best, best_error, best_frame = index, error, cropped
        count = index + 1
    return Scan(best, best_error, best_frame, count, worst, scored)


def _nearest_rival(scan: Scan) -> tuple[int, float] | None:
    run = tied_run(scan.scored, scan.best)
    rivals = {step: error for step, error in scan.scored.items() if step not in run}
    if not rivals:
        return None
    contender = min(rivals, key=lambda step: rivals[step])
    return contender, rivals[contender]


def _report(
    scan: Scan, best_frame: np.ndarray, capture: np.ndarray, rival: tuple[int, float] | None
) -> None:
    print(f"best match: rendered frame {scan.best} of {scan.seen}")
    print(f"mean absolute error: {scan.best_error:.4f} of 255")
    print(f"exact pixel match: {np.array_equal(best_frame.astype(np.uint8), capture)}")
    print(f"worst frame error: {scan.worst:.4f}")
    if rival is not None:
        contender, error = rival
        margin = error - scan.best_error
        print(f"nearest rival: frame {contender} at {error:.4f}, {margin:.4f} behind")


def _verdict(scan: Scan, rival: tuple[int, float] | None, args: argparse.Namespace) -> int:
    if scan.best_error > args.max_mean_error:
        print(
            f"FAIL: best match error {scan.best_error:.4f} exceeds {args.max_mean_error}",
            file=sys.stderr,
        )
        return 1
    if rival is not None and rival[1] - scan.best_error < args.min_separation:
        print(
            f"AMBIGUOUS: frame {scan.best} at {scan.best_error:.4f} and frame {rival[0]} at "
            f"{rival[1]:.4f} sit within {args.min_separation} of each other, so which "
            f"one the capture shows is a guess rather than a measurement",
            file=sys.stderr,
        )
        return 2
    print("PASS")
    return 0


def main(argv: list[str]) -> int:
    args = _parse(argv)
    capture = downscale_capture(decode_capture(args.capture))
    complaint = _geometry_complaint(capture, args.overscan)
    if complaint is not None:
        print(complaint, file=sys.stderr)
        return 2
    reference = (
        stream_preview(args.preview)
        if args.preview is not None
        else iter([reconstruct_frame(args.baked, args.frame)])
    )
    scan = _scan(reference, capture, args.overscan)
    if scan.best_frame is None:
        print("the reference produced no frames", file=sys.stderr)
        return 2
    rival = _nearest_rival(scan)
    _report(scan, scan.best_frame, capture, rival)
    return _verdict(scan, rival, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
