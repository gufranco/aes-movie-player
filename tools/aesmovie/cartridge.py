"""Turn a movie file into a cartridge with one command.

The baker and the ROM build are separate tools because they answer
separate questions, but the common case is neither: it is someone with a
video file who wants a cartridge out the other end. This runs the whole
path, chooses the quality tier by measuring the source, and takes the
subtitle file by name rather than insisting it sit beside the movie
under a matching name.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from aesmovie import bake, frames, probe, quality, tiercache

BUILD_SCRIPT = Path(__file__).resolve().parents[2] / "toolchain" / "build-in-docker.sh"
CARTRIDGE_NAME = "aesmovie.neo"
ARCHIVE_NAME = "aesmovie.zip"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aesmovie",
        description="Bake a movie and build the cartridge that plays it.",
    )
    parser.add_argument("source", type=Path, help="the video file to put on the cartridge")
    parser.add_argument(
        "--subtitles",
        type=Path,
        default=None,
        help="a SubRip .srt file; defaults to one sitting beside the source",
    )
    parser.add_argument(
        "--quality",
        default="search",
        help="a rung such as q17, or search to settle it by baking. Default: search",
    )
    parser.add_argument(
        "--tier-cache",
        type=Path,
        default=None,
        help=f"where measured tier costs are kept; defaults to {tiercache.STORE_NAME}",
    )
    parser.add_argument("--start", type=float, default=0.0, help="seconds to skip at the front")
    parser.add_argument(
        "--duration", type=float, default=None, help="seconds to take; defaults to the whole film"
    )
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    parser.add_argument("--preview", type=Path, default=None)
    parser.add_argument("--fit", choices=("fill", "letterbox"), default="fill")
    parser.add_argument(
        "--dither",
        action="store_true",
        help="ordered threshold across palette entries, to break up banding",
    )
    parser.add_argument(
        "--bake-only", action="store_true", help="stop after the bake, before the ROM build"
    )
    return parser.parse_args(argv)


def _complain(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _check_inputs(args: argparse.Namespace) -> int | None:
    if not args.source.exists():
        return _complain(f"source not found: {args.source}")
    if not args.source.is_file():
        return _complain(f"source is not a file: {args.source}")
    if args.subtitles is not None and not args.subtitles.is_file():
        return _complain(f"subtitle file not found: {args.subtitles}")
    return None


def bake_argv(args: argparse.Namespace) -> list[str]:
    argv = [
        "--source",
        str(args.source),
        "--quality",
        str(args.quality),
        "--start",
        str(float(args.start)),
        "--build-dir",
        str(args.build_dir),
        "--fit",
        str(args.fit),
    ]
    if args.duration is not None:
        argv += ["--duration", str(float(args.duration))]
    if args.subtitles is not None:
        argv += ["--subtitles", str(args.subtitles)]
    if args.preview is not None:
        argv += ["--preview", str(args.preview)]
    if args.dither:
        argv += ["--dither"]
    return argv


def _measured_tier(args: argparse.Namespace) -> quality.Tier | None:
    """Resolve a tier by baking rather than by sampling, remembering the result."""
    info = frames.probe(args.source)
    span = args.duration if args.duration is not None else max(0.0, info.duration - args.start)
    minutes = span / quality.SECONDS_PER_MINUTE
    store = args.tier_cache or tiercache.default_store()
    params = tiercache.Params(
        start=float(args.start), duration=float(span), fit=args.fit, denoise=0.0, frame_hold=1
    )
    key = tiercache.key_for(args.source, params)
    tiercache.describe(store, key, source=args.source, params=params)
    known = tiercache.recall(store, key)
    if known:
        print(f"{len(known)} tier cost(s) already measured for this source", file=sys.stderr)

    scratch = args.build_dir.parent / f"{args.build_dir.name}-probe"

    def run(tier: quality.Tier) -> probe.Reading:
        print(f"measuring {tier.name}", file=sys.stderr)
        report = scratch / f"{tier.name}.json"
        argv = [*bake_argv(args), "--report-json", str(report)]
        argv[argv.index("--quality") + 1] = tier.name
        argv[argv.index("--build-dir") + 1] = str(scratch / tier.name)
        status = bake.main(argv)
        if not report.is_file():
            return probe.Reading(tier=tier, tiles=quality.CROM_TILES, capped=True)
        data = json.loads(report.read_text())
        capped = status != 0 or bool(data["dictionary_full"]) or bool(data["budget_exceeded"])
        return probe.Reading(tier=tier, tiles=int(data["tile_count"]), capped=capped)

    outcome = probe.search(
        measure=run,
        minutes=minutes,
        budget=quality.CROM_TILES,
        known=known,
        source_fps=float(info.fps),
        vblank_fps=float(frames.VBLANK_FPS),
    )
    for name, rate in outcome.rates.items():
        tiercache.remember(store, key, name, rate)
    if outcome.tier is not None:
        tiercache.describe(store, key, source=args.source, params=params, chosen=outcome.tier.name)
    if outcome.too_expensive:
        print(f"overran: {', '.join(outcome.too_expensive)}", file=sys.stderr)
    if outcome.baked:
        print(f"baked {len(outcome.baked)} rung(s) to settle it", file=sys.stderr)
    else:
        print("settled entirely from remembered measurements", file=sys.stderr)
    return outcome.tier


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    failure = _check_inputs(args)
    if failure is not None:
        return failure

    if args.quality == "search":
        tier = _measured_tier(args)
        if tier is None:
            print(
                "this source fits no tier; trim it yourself or lower the runtime",
                file=sys.stderr,
            )
            return 3
        print(f"measured choice: {tier.name}", file=sys.stderr)
        args.quality = tier.name

    print(f"baking {args.source}", file=sys.stderr)
    status = bake.main(bake_argv(args))
    if status != 0:
        return status

    if args.bake_only:
        print(f"baked into {args.build_dir}", file=sys.stderr)
        return 0

    print("building the cartridge", file=sys.stderr)
    environment = dict(os.environ, BUILD=str(args.build_dir))
    completed = subprocess.run(["bash", str(BUILD_SCRIPT)], env=environment, check=False)
    if completed.returncode != 0:
        return completed.returncode

    cartridge = args.build_dir / CARTRIDGE_NAME
    archive = args.build_dir / ARCHIVE_NAME
    for produced in (cartridge, archive):
        if produced.exists():
            print(f"{produced}  {produced.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
