from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from fmvcore import arguments, condition, ffmpeg

from neogeomedia import content, epochs, frames, limits, quality

DEFAULT_PALETTE_COUNT: Final = 240
DEFAULT_BASE_BANK: Final = 16
DEFAULT_KEYFRAME_INTERVAL: Final = 90
DEFAULT_TOLERANCE: Final = 0.0005
DEFAULT_SCENE_CUT_RATIO: Final = 0.90
DEFAULT_CANDIDATES: Final = 12
PROFILE_SECONDS: Final = 30.0
DITHER_HELP: Final = "ordered dither strength across palette entries, 0 for none. Default: 1"
BUNDLE_HELP: Final = "a folder to write a drop-in copy of the player library and this film into"
SILENT_HELP: Final = "leave sound out; it has its own ROM, so the picture gains no room"
AUDIO_DC_HELP: Final = "high-pass the soundtrack to remove a DC offset before it is encoded"
AUDIO_COMPRESS_HELP: Final = "compress the soundtrack's dynamics so quiet passages carry"
AUDIO_NORMALIZE_HELP: Final = "lift the soundtrack so its peak uses the output's full range"
AUDIO_SOFT_CLIP_HELP: Final = "soft-clip the soundtrack's peaks instead of letting them hard-clip"
SEEK_EVERY_HELP: Final = (
    f"seconds between the points C and D jump to. Default: {limits.SEEK_EVERY_SECONDS:g}"
)

_AUTO_REFUSAL: Final = (
    "'auto' is gone: it guessed the tier from a sample and the guess was wrong "
    "in both directions. Name a rung, or let the cartridge tool measure one "
    "with --quality search. To see the estimate without acting on it, run "
    "python -m neogeomedia.plan."
)


@dataclass(frozen=True, slots=True)
class Measured:
    scene_cut_floor: float
    palette_epoch_seconds: float
    sample_stride: int


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--quality", default=None)
    parser.add_argument(
        "--audio-rate",
        type=arguments.number(
            low=limits.MIN_AUDIO_RATE_HZ, high=limits.MAX_AUDIO_RATE_HZ, name="--audio-rate"
        ),
        default=None,
    )
    parser.add_argument(
        "--start",
        type=arguments.number(low=0.0, high=limits.MAX_SOURCE_SECONDS, name="--start"),
        default=0.0,
    )
    parser.add_argument(
        "--duration",
        type=arguments.number(
            low=limits.MIN_SECONDS, high=limits.MAX_SOURCE_SECONDS, name="--duration"
        ),
        default=None,
    )
    parser.add_argument("--subtitles", type=Path, default=None)
    parser.add_argument("--build-dir", type=Path, default=Path("build"))


def _add_audio_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--audio-remove-dc", action="store_true", help=AUDIO_DC_HELP)
    parser.add_argument("--audio-compress", action="store_true", help=AUDIO_COMPRESS_HELP)
    parser.add_argument("--audio-normalize", action="store_true", help=AUDIO_NORMALIZE_HELP)
    parser.add_argument("--audio-soft-clip", action="store_true", help=AUDIO_SOFT_CLIP_HELP)


def _add_picture_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--denoise",
        type=arguments.number(low=0.0, high=limits.MAX_DENOISE, name="--denoise"),
        default=None,
    )
    parser.add_argument(
        "--frame-hold",
        type=arguments.count(low=1, high=limits.MAX_FRAME_HOLD, name="--frame-hold"),
        default=None,
    )
    parser.add_argument(
        "--motion-blur",
        type=arguments.count(low=0, high=limits.MAX_MOTION_BLUR, name="--motion-blur"),
        default=0,
    )
    parser.add_argument(
        "--target-fps",
        type=arguments.number(
            low=limits.MIN_TARGET_FPS, high=float(frames.VBLANK_FPS), name="--target-fps"
        ),
        default=None,
    )
    parser.add_argument(
        "--motion-masking",
        type=arguments.number(low=0.0, high=limits.MAX_MOTION_MASKING, name="--motion-masking"),
        default=0.0,
    )


def _add_colour_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dither",
        type=arguments.number(low=0.0, high=limits.MAX_DITHER, name="--dither"),
        default=limits.DEFAULT_DITHER,
        help=DITHER_HELP,
    )
    parser.add_argument(
        "--chroma-weight",
        type=arguments.number(
            low=limits.MIN_CHROMA_WEIGHT, high=limits.MAX_CHROMA_WEIGHT, name="--chroma-weight"
        ),
        default=None,
    )
    parser.add_argument(
        "--scene-cut-floor",
        type=arguments.number(low=0.0, high=limits.MAX_FRACTION, name="--scene-cut-floor"),
        default=None,
    )
    parser.add_argument(
        "--palette-epoch-seconds",
        type=arguments.number(
            low=0.0, high=limits.MAX_SOURCE_SECONDS, name="--palette-epoch-seconds"
        ),
        default=None,
    )


def _add_budget_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tile-budget",
        type=arguments.count(low=1, high=limits.MAX_TILES, name="--tile-budget"),
        default=None,
    )
    parser.add_argument(
        "--stop-when-over-budget",
        action="store_true",
        help="abandon the bake once it cannot finish, instead of encoding the rest",
    )
    parser.add_argument(
        "--palette-count",
        type=arguments.count(low=1, high=limits.MAX_PALETTES, name="--palette-count"),
        default=DEFAULT_PALETTE_COUNT,
    )
    parser.add_argument(
        "--base-bank",
        type=arguments.count(low=0, high=limits.MAX_PALETTES - 1, name="--base-bank"),
        default=DEFAULT_BASE_BANK,
    )
    parser.add_argument(
        "--keyframe-interval",
        type=arguments.count(low=1, high=limits.MAX_FRAMES, name="--keyframe-interval"),
        default=DEFAULT_KEYFRAME_INTERVAL,
    )


def _add_encoder_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tolerance",
        type=arguments.number(low=0.0, high=limits.MAX_FRACTION, name="--tolerance"),
        default=None,
    )
    parser.add_argument(
        "--scene-cut-ratio",
        type=arguments.number(low=0.0, high=limits.MAX_FRACTION, name="--scene-cut-ratio"),
        default=DEFAULT_SCENE_CUT_RATIO,
    )
    parser.add_argument(
        "--candidates",
        type=arguments.count(low=0, high=limits.MAX_PALETTES, name="--candidates"),
        default=None,
    )
    parser.add_argument("--flip", action="store_true")
    parser.add_argument(
        "--sample-stride",
        type=arguments.count(low=1, high=limits.MAX_FRAMES, name="--sample-stride"),
        default=None,
    )
    parser.add_argument(
        "--seed", type=arguments.count(low=0, high=limits.MAX_SEED, name="--seed"), default=0
    )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preview", type=Path, default=None)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--bundle", type=Path, default=None, help=BUNDLE_HELP)
    parser.add_argument("--silent", action="store_true", help=SILENT_HELP)
    parser.add_argument(
        "--seek-every",
        type=arguments.number(
            low=limits.MIN_SECONDS, high=limits.MAX_SOURCE_SECONDS, name="--seek-every"
        ),
        default=limits.SEEK_EVERY_SECONDS,
        help=SEEK_EVERY_HELP,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bake a video clip into Neo Geo cart data.")
    _add_source_args(parser)
    _add_audio_args(parser)
    _add_picture_args(parser)
    _add_colour_args(parser)
    _add_budget_args(parser)
    _add_encoder_args(parser)
    _add_output_args(parser)
    return parser.parse_args(argv)


def audio_conditioning_from(args: argparse.Namespace) -> condition.Conditioning:
    return condition.Conditioning(
        remove_dc=args.audio_remove_dc,
        compress=args.audio_compress,
        normalize=args.audio_normalize,
        soft_clip=args.audio_soft_clip,
    )


def resolve_duration(args: argparse.Namespace) -> float:
    if args.duration is not None:
        return float(args.duration)
    return max(0.0, ffmpeg.probe(args.source).duration - float(args.start))


def resolve_quality(args: argparse.Namespace) -> quality.Tier | None:
    if args.quality is None:
        return None
    if args.quality == "auto":
        raise SystemExit(_AUTO_REFUSAL)
    return quality.tier_by_name(args.quality)


def pick[Knob: (int, float)](
    explicit: Knob | None, tier_value: Knob | None, fallback: Knob
) -> Knob:
    if explicit is not None:
        return explicit
    if tier_value is not None:
        return tier_value
    return fallback


def resolve_frame_hold(args: argparse.Namespace, tier: quality.Tier | None) -> int:
    hold = int(pick(args.frame_hold, tier.frame_hold if tier else None, 1))
    if args.target_fps is not None:
        hold = frames.hold_for_target_fps(args.target_fps)
    if hold <= 1:
        return 1
    source_fps = ffmpeg.probe(args.source).fps
    if frames.source_frames_kept(hold, source_fps) >= 1.0:
        effective = float(frames.VBLANK_FPS) / hold
        msg = (
            f"a hold of {hold} runs at {effective:.1f} fps, at or above the source's "
            f"{float(source_fps):.1f} fps, so it drops no source frame and saves no tiles. "
            f"Use a hold of {int(float(frames.VBLANK_FPS) // float(source_fps)) + 1} or more."
        )
        raise SystemExit(msg)
    return hold


def measured_settings(args: argparse.Namespace) -> Measured:
    profile = content.measure(args.source, duration=PROFILE_SECONDS)
    floor = (
        args.scene_cut_floor
        if args.scene_cut_floor is not None
        else content.movement_floor(args.source)
    )
    epoch_seconds = (
        args.palette_epoch_seconds
        if args.palette_epoch_seconds is not None
        else content.epoch_seconds_for(cuts_per_minute=profile.cuts_per_minute)
    )
    stride = (
        args.sample_stride
        if args.sample_stride is not None
        else epochs.stride_for_epoch(epoch_frames=round(epoch_seconds * float(frames.VBLANK_FPS)))
    )
    print(
        f"measured from the source: scene cut floor {floor:.5f},"
        f" palette epoch {epoch_seconds:.1f}s"
        f" ({profile.cuts_per_minute:.1f} cuts/min, saturation {profile.saturation:.1f}),"
        f" palette sample every {stride} frames",
        file=sys.stderr,
    )
    return Measured(
        scene_cut_floor=floor, palette_epoch_seconds=epoch_seconds, sample_stride=stride
    )
