"""Report what a source can become on a cartridge, without baking it.

Calibrating takes well under a minute while a full bake takes hours, so
this exists to answer the question that decides the bake: what quality
is reachable, and what would trimming the source buy. Everything it
learns is printed rather than acted on, because shortening a film is the
owner's decision and not the baker's.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aesmovie import bake, calibrate, frames, quality


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aesmovie plan",
        description="Measure a source and report which quality tiers fit a cartridge.",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--fit", choices=("fill", "letterbox"), default="fill")
    parser.add_argument("--samples", type=int, default=calibrate.DEFAULT_SAMPLE_COUNT)
    parser.add_argument("--sample-seconds", type=float, default=calibrate.DEFAULT_SAMPLE_SECONDS)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    info = frames.probe(args.source)
    windows = calibrate.sample_windows(
        info.duration, count=args.samples, seconds=args.sample_seconds
    )
    sampled = sum(span for _, span in windows)
    print(
        f"Calibrating on {len(windows)} sample(s), {sampled:.0f}s of"
        f" {info.duration:.0f}s, at the '{quality.REFERENCE_TIER}' tier...",
        file=sys.stderr,
    )
    rate, anchors = calibrate.measure_anchors(
        args.source,
        count=args.samples,
        seconds=args.sample_seconds,
        fit=args.fit,
        seed=args.seed,
    )
    print(
        quality.format_plan(
            source=str(args.source),
            minutes=info.duration / quality.SECONDS_PER_MINUTE,
            width=info.width,
            height=info.height,
            source_fps=float(info.fps),
            has_audio=bake.has_audio_stream(args.source),
            reference_rate=rate,
            vblank_fps=float(frames.VBLANK_FPS),
            anchors=anchors,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
