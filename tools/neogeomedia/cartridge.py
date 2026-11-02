from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from fmvcore import arguments, ffmpeg

from neogeomedia import (
    bake,
    bakeargs,
    denoise,
    frames,
    limits,
    probe,
    quality,
    shortfall,
    tiercache,
)

BUILD_SCRIPT = Path(__file__).resolve().parents[2] / "toolchain" / "build-in-docker.sh"
CARTRIDGE_NAME = "neogeomedia.neo"
ARCHIVE_NAME = "neogeomedia.zip"
NO_TIER_FITS = 3
REPORT_NAME = "report.json"
PREVIEW_HELP = "a .mp4 or .mkv of every frame the console draws, or a .png for four frames"


def _add_source_args(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument(
        "--start",
        type=arguments.number(low=0.0, high=limits.MAX_SOURCE_SECONDS, name="--start"),
        default=0.0,
        help="seconds to skip at the front",
    )


def _add_bake_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--duration",
        type=arguments.number(
            low=limits.MIN_SECONDS, high=limits.MAX_SOURCE_SECONDS, name="--duration"
        ),
        default=None,
        help="seconds to take; defaults to the whole film",
    )
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    parser.add_argument("--preview", type=Path, default=None, help=PREVIEW_HELP)
    parser.add_argument(
        "--dither",
        type=arguments.number(low=0.0, high=limits.MAX_DITHER, name="--dither"),
        default=limits.DEFAULT_DITHER,
        help=bakeargs.DITHER_HELP,
    )
    parser.add_argument(
        "--denoise",
        type=arguments.number_or_auto(low=0.0, high=limits.MAX_DENOISE, name="--denoise"),
        default=None,
        help="a strength, or auto to measure it on the film. Default: auto with search",
    )
    parser.add_argument(
        "--bake-only", action="store_true", help="stop after the bake, before the ROM build"
    )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--silent", action="store_true", help=bakeargs.SILENT_HELP)
    parser.add_argument("--bundle", type=Path, default=None, help=bakeargs.BUNDLE_HELP)
    parser.add_argument(
        "--seek-every",
        type=arguments.number(
            low=limits.MIN_SECONDS, high=limits.MAX_SOURCE_SECONDS, name="--seek-every"
        ),
        default=limits.SEEK_EVERY_SECONDS,
        help=bakeargs.SEEK_EVERY_HELP,
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"where the figures go, refused bake or not; defaults to {REPORT_NAME} in --build-dir",
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="neogeomedia",
        description="Bake a movie and build the cartridge that plays it.",
    )
    _add_source_args(parser)
    _add_bake_args(parser)
    _add_output_args(parser)
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
        "--dither",
        str(float(args.dither)),
        "--seek-every",
        str(float(args.seek_every)),
    ]
    if args.duration is not None:
        argv += ["--duration", str(float(args.duration))]
    if args.subtitles is not None:
        argv += ["--subtitles", str(args.subtitles)]
    if args.preview is not None:
        argv += ["--preview", str(args.preview)]
    if args.silent:
        argv += ["--silent"]
    if args.denoise not in (None, arguments.AUTO):
        argv += ["--denoise", str(args.denoise)]
    return argv


def _settle_denoise(args: argparse.Namespace) -> None:
    info = ffmpeg.probe(args.source)
    span = args.duration if args.duration is not None else max(0.0, info.duration - args.start)
    window = min(denoise.WINDOW_SECONDS, span)
    start = args.start + max(0.0, (span - window) / 2.0)
    tier = quality.tier_by_name(args.quality)
    scores = denoise.measure(args.source, tier, start=start, window=window)
    chosen = denoise.choose(scores)
    measured = ", ".join(f"{score.strength:g}: {score.error:.5f}" for score in scores)
    print(f"denoise {chosen.strength:g}, blurred error by strength {measured}", file=sys.stderr)
    args.denoise = str(chosen.strength)


def _span(args: argparse.Namespace, info: ffmpeg.SourceInfo) -> float:
    return float(
        args.duration if args.duration is not None else max(0.0, info.duration - args.start)
    )


def _read_reading(tier: quality.Tier, report: Path, status: int) -> probe.Reading:
    if not report.is_file():
        return probe.Reading(tier=tier, tiles=quality.CROM_TILES, capped=True)
    data = json.loads(report.read_text())
    capped = (
        status != 0
        or bool(data["dictionary_full"])
        or bool(data["budget_exceeded"])
        or bool(data.get("truncated"))
    )
    return probe.Reading(
        tier=tier,
        tiles=int(data["tile_count"]),
        capped=capped,
        exhausted=bool(data.get("rate_control_exhausted")),
    )


def _probe_bake(args: argparse.Namespace, scratch: Path, tier: quality.Tier) -> probe.Reading:
    print(f"measuring {tier.name}", file=sys.stderr)
    report = scratch / f"{tier.name}.json"
    argv = [*bake_argv(args), "--report-json", str(report), "--stop-when-over-budget"]
    argv[argv.index("--quality") + 1] = tier.name
    argv[argv.index("--build-dir") + 1] = str(scratch / tier.name)
    return _read_reading(tier, report, bake.main(argv))


def _say_how_it_settled(outcome: probe.Outcome) -> None:
    if outcome.too_expensive:
        print(f"overran: {', '.join(outcome.too_expensive)}", file=sys.stderr)
    if outcome.baked:
        print(f"baked {len(outcome.baked)} rung(s) to settle it", file=sys.stderr)
    else:
        print("settled entirely from remembered measurements", file=sys.stderr)


def _measured_tier(args: argparse.Namespace) -> quality.Tier | None:
    info = ffmpeg.probe(args.source)
    span = _span(args, info)
    store = args.tier_cache or tiercache.default_store()
    params = tiercache.Params(
        start=float(args.start),
        duration=span,
        denoise=0.0,
        frame_hold=1,
        dither=float(args.dither),
    )
    key = tiercache.key_for(args.source, params)
    tiercache.describe(store, key, source=args.source, params=params)
    known = tiercache.recall(store, key)
    if known:
        print(f"{len(known)} tier cost(s) already measured for this source", file=sys.stderr)
    scratch = _scratch(args, "probe")
    outcome = probe.search(
        measure=lambda tier: _probe_bake(args, scratch, tier),
        minutes=span / quality.SECONDS_PER_MINUTE,
        budget=quality.CROM_TILES,
        known=known,
        source_fps=float(info.fps),
        vblank_fps=float(frames.VBLANK_FPS),
    )
    for name, rate in outcome.rates.items():
        tiercache.remember(store, key, name, rate)
    if outcome.tier is not None:
        tiercache.describe(store, key, source=args.source, params=params, chosen=outcome.tier.name)
    _say_how_it_settled(outcome)
    return outcome.tier


def _scratch(args: argparse.Namespace, kind: str) -> Path:
    return Path(args.build_dir.parent / f"{args.build_dir.name}-{kind}")


def _report_path(args: argparse.Namespace) -> Path:
    return Path(args.report or args.build_dir / REPORT_NAME)


def _outputs(args: argparse.Namespace) -> list[str]:
    bundled = [] if args.bundle is None else ["--bundle", str(args.bundle)]
    return ["--report-json", str(_report_path(args)), *bundled]


def _reach(args: argparse.Namespace, tier: quality.Tier) -> tuple[float, Path]:
    scratch = _scratch(args, "reach")
    report = scratch / f"{tier.name}.json"
    report.unlink(missing_ok=True)
    _probe_bake(args, scratch, tier)
    if not report.is_file():
        return 0.0, report
    frames_held = float(json.loads(report.read_text())["frames"])
    return frames_held / float(frames.VBLANK_FPS), report


def _cheapest(rungs: list[quality.Tier]) -> quality.Tier:
    return min(rungs or quality.LADDER, key=lambda tier: tier.relative_cost)


def _suggest_duration(args: argparse.Namespace, tier: quality.Tier) -> str:
    seconds, _ = _reach(args, tier)
    cheapest = tier == _cheapest(list(quality.LADDER))
    return shortfall.shortfall(seconds=seconds, rung=tier.name, cheapest=cheapest)


def _refuse_search(args: argparse.Namespace) -> int:
    info = ffmpeg.probe(args.source)
    tier = _cheapest(probe.candidates(float(info.fps), float(frames.VBLANK_FPS)))
    seconds, measured = _reach(args, tier)
    if measured.is_file():
        _report_path(args).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(measured, _report_path(args))
    advice = shortfall.shortfall(seconds=seconds, rung=tier.name, cheapest=True)
    print(f"this source fits no tier; {advice}", file=sys.stderr)
    return NO_TIER_FITS


def _settle_quality(args: argparse.Namespace) -> int | None:
    if args.quality == "search":
        tier = _measured_tier(args)
        if tier is None:
            return _refuse_search(args)
        print(f"measured choice: {tier.name}", file=sys.stderr)
        args.quality = tier.name
        args.denoise = arguments.AUTO if args.denoise is None else args.denoise
    if args.denoise == arguments.AUTO:
        _settle_denoise(args)
    return None


def _build_cartridge(build_dir: Path) -> int:
    print("building the cartridge", file=sys.stderr)
    environment = dict(os.environ, BUILD=str(build_dir))
    completed = subprocess.run(["bash", str(BUILD_SCRIPT)], env=environment, check=False)
    if completed.returncode != 0:
        return completed.returncode
    for produced in (build_dir / CARTRIDGE_NAME, build_dir / ARCHIVE_NAME):
        if produced.exists():
            print(f"{produced}  {produced.stat().st_size} bytes")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    failure = _check_inputs(args)
    if failure is not None:
        return failure
    unsettled = _settle_quality(args)
    if unsettled is not None:
        return unsettled
    print(f"baking {args.source}", file=sys.stderr)
    status = bake.main([*bake_argv(args), *_outputs(args)])
    if status == bake.OVERRAN:
        print(_suggest_duration(args, quality.tier_by_name(args.quality)), file=sys.stderr)
    if status != 0:
        return status
    if args.bake_only:
        print(f"baked into {args.build_dir}", file=sys.stderr)
        return 0
    return _build_cartridge(args.build_dir)


if __name__ == "__main__":
    raise SystemExit(main())
