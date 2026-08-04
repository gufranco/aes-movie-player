"""Drive the bake passes and report what the movie costs in ROM.

Writes the cart-side artifacts under `build/baked/` and the two
generated sources under `build/generated/`. Large blobs reach the ROM
through `.incbin` in an assembly stub rather than as C arrays, because a
multi-megabyte C array costs minutes of compile time and buys nothing.

The stub names those blobs by filename alone and leaves the assembler
to find them on its include path, so the build passes `-I` for the baked
directory. Writing the path the baker happened to use would pin the
sources to one machine, and a bake taken from anywhere but the build
tree would fail to assemble.

The preview output re-encodes the decoded picture at the vblank rate, so
the quantization can be judged in motion without booting a cart.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from aesmovie import adpcmb, calibrate, encode, fixtiles, frames, neocolor, palettes, quality

SECONDS_PER_MINUTE: Final = 60.0
CROM_BANK_BYTES: Final = 128 << 20
ADPCM_B_BYTES: Final = 16 << 20
V_ROM_MIN_BYTES: Final = 1 << 19
MAX_SAMPLE_TILES: Final = 200_000
_SCENE_CUT_SHARE: Final = 0.6

# The player writes 48 palette words a frame, and an epoch holds 120
# palettes of 16 words, so a new set takes 40 frames to become resident.
# Three times that leaves room for the transport to be redrawing too.
MIN_EPOCH_FRAMES: Final = 120
FIX_PALETTE_BANK: Final = 1
S_ROM_BYTES: Final = 131072


def has_audio_stream(source: Path) -> bool:
    """True when the source carries at least one audio stream."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(source),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _decode_audio(
    source: Path, start: float, duration: float, rate_hz: float
) -> npt.NDArray[np.int16]:
    """Decode the source soundtrack to mono 16-bit at the target rate.

    A source with no audio track is a normal input, not a failure, so
    this reports an empty signal and the bake simply omits the voice ROM.
    """
    if not has_audio_stream(source):
        return np.zeros(0, dtype=np.int16)
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{start:.6f}",
            "-i",
            str(source),
            "-t",
            f"{duration:.6f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(int(rate_hz)),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype="<i2")


def self_tier_name(request: BakeRequest) -> str:
    """The rung this cart was baked at, for the overlay to display."""
    return (request.quality or "custom").upper()[:8]


def _fix_defines() -> str:
    names = {
        "blank": "FIX_TILE_BLANK",
        "panel": "FIX_TILE_PANEL",
        "0": "FIX_TILE_DIGIT0",
        "colon": "FIX_TILE_COLON",
        "slash": "FIX_TILE_SLASH",
        "play": "FIX_TILE_PLAY",
        "pause": "FIX_TILE_PAUSE",
        "forward": "FIX_TILE_FORWARD",
        "rewind": "FIX_TILE_REWIND",
        "bar_empty": "FIX_TILE_BAR_EMPTY",
        "bar_filled": "FIX_TILE_BAR_FILLED",
        "panel_top": "FIX_TILE_PANEL_TOP",
        "bar_cap_left": "FIX_TILE_BAR_CAP_LEFT",
        "bar_cap_right": "FIX_TILE_BAR_CAP_RIGHT",
        "bar_knob": "FIX_TILE_BAR_KNOB",
        "A": "FIX_TILE_A",
        "percent": "FIX_TILE_PERCENT",
        "dot": "FIX_TILE_DOT",
        "dash": "FIX_TILE_DASH",
    }
    return "\n".join(f"#define {macro} {fixtiles.GLYPHS[glyph]}" for glyph, macro in names.items())


_HEADER_TEMPLATE: Final = """#ifndef MOVIE_DATA_H
#define MOVIE_DATA_H

#define MOVIE_FRAME_COUNT {frames}
#define MOVIE_TILE_COUNT {tiles}
#define MOVIE_PALETTE_COUNT {palettes}
#define MOVIE_PALETTE_BASE {base_bank}
#define MOVIE_EPOCH_COUNT {epochs}
#define MOVIE_EPOCH_PALETTES {epoch_palettes}
#define MOVIE_IMAGE_WIDTH {image_width}
#define MOVIE_IMAGE_HEIGHT {image_height}
#define MOVIE_TIER_NAME "{tier_name}"
#define MOVIE_CHROMA_PERCENT {chroma_percent}
#define MOVIE_CROM_PERCENT {crom_percent}
#define MOVIE_AUDIO_HZ {audio_hz}
#define MOVIE_FRAME_HOLD {frame_hold}
#define MOVIE_KEYFRAME_COUNT {keyframes}
#define MOVIE_GRID_COLS {cols}
#define MOVIE_GRID_ROWS {rows}
#define MOVIE_MAX_UPDATES {max_updates}
#define MOVIE_STREAM_BANKS {stream_banks}
#define MOVIE_STREAM_BYTES {stream_bytes}u
#define MOVIE_FPS_NUM {fps_num}u
#define MOVIE_FPS_DEN {fps_den}u
#define MOVIE_AUDIO_PAGE_NUM {audio_page_num}u
#define MOVIE_AUDIO_PAGE_DEN {audio_page_den}u

#define FIX_PALETTE {fix_palette}
{fix_defines}

extern const unsigned char movie_index[];
extern const unsigned char movie_keyframes[];
extern const unsigned char movie_palettes[];
extern const unsigned char movie_epochs[];
extern const unsigned char movie_fix_palette[];

#endif
"""

_ASM_ENTRY: Final = """    .globl {symbol}
    .balign 2
{symbol}:
    .incbin "{path}"
"""


@dataclass(frozen=True, slots=True)
class BakeRequest:
    source: Path
    start: float
    duration: float
    build_dir: Path
    fit: frames.FitMode = "fill"
    palette_count: int = 240
    base_bank: int = 16
    keyframe_interval: int = 90
    tolerance: float = 0.0005
    scene_cut_ratio: float = 0.90
    candidates: int = 12
    allow_flip: bool = False
    sample_stride: int = 8
    seed: int = 0
    preview: Path | None = None
    denoise: float = 0.0
    frame_hold: int = 1
    motion_blur: int = 0
    motion_masking: float = 0.0
    chroma_weight: float = 1.0
    scene_cut_floor: float = 0.01
    palette_epoch_seconds: float = 5.0
    quality: str | None = None
    tile_budget: int = 0
    audio_rate_hz: float = 22050.0
    audio: bool = True


@dataclass(frozen=True, slots=True)
class BakeOutcome:
    request: BakeRequest
    result: encode.EncodeResult
    build_dir: Path
    artifacts: dict[str, Path] = field(default_factory=dict)

    def report(self) -> dict[str, Any]:
        """Sizes measured on this clip and what they project to."""
        stats = self.result.stats
        seconds = stats.frames / float(frames.VBLANK_FPS)
        minutes = seconds / SECONDS_PER_MINUTE
        crom_per_minute = stats.crom_payload_bytes / minutes
        stream_per_minute = stats.stream_bytes / minutes
        return {
            "frames": stats.frames,
            "seconds": round(seconds, 3),
            "denoise": self.request.denoise,
            "frame_hold": self.request.frame_hold,
            "motion_blur": self.request.motion_blur,
            "motion_masking": self.request.motion_masking,
            "chroma_weight": self.request.chroma_weight,
            "scene_cut_floor": self.request.scene_cut_floor,
            "palette_epoch_seconds": self.request.palette_epoch_seconds,
            "palette_epochs": len(self.result.palette_sets),
            "tile_budget": self.request.tile_budget,
            "tile_count": stats.tile_count,
            "dictionary_full": stats.dictionary_full,
            "crom_payload_bytes": stats.crom_payload_bytes,
            "crom_rom_bytes": stats.crom_rom_bytes,
            "stream_bytes": stats.stream_bytes,
            "stream_rom_bytes": stats.stream_rom_bytes,
            "keyframe_bytes": stats.keyframe_bytes,
            "delta_bytes": stats.delta_bytes,
            "index_bytes": stats.index_bytes,
            "keyframe_count": stats.keyframe_count,
            "stream_banks": self.result.stream.bank_count(),
            "max_updates": stats.max_updates,
            "mean_updates": round(stats.mean_updates, 2),
            "mean_error": stats.mean_error,
            "peak_tolerance": stats.peak_tolerance,
            "budget_exceeded": stats.budget_exceeded,
            "displayed_error": stats.displayed_error,
            "projected_crom_bytes_per_minute": round(crom_per_minute),
            "projected_stream_bytes_per_minute": round(stream_per_minute),
            "projected_minutes_per_crom_bank": round(CROM_BANK_BYTES / crom_per_minute, 2),
        }


def _thin_sample(tiles: np.ndarray, seed: int) -> np.ndarray:
    """Cap how many tiles the palette fit sees.

    Fitting the palette set materializes an Oklab triple per pixel of
    every sample tile. On a full-length clip the strided sample runs to
    over half a million tiles, which is gigabytes of float before the
    encoder has started. A capped random subset picks the same palettes
    for a fraction of the memory.
    """
    if tiles.shape[0] <= MAX_SAMPLE_TILES:
        return tiles
    rng = np.random.default_rng(seed)
    keep = rng.choice(tiles.shape[0], MAX_SAMPLE_TILES, replace=False)
    keep.sort()
    return tiles[keep]


def audio_pages_per_frame(delta_n: int) -> Fraction:
    """Voice-ROM pages advanced per video frame, as an exact fraction.

    The player multiplies a frame number by this to find where in the
    soundtrack that frame sits, which is what lets a seek re-point audio
    and video together. Two samples share a byte and a page is 256
    bytes, hence the 512.

    This is deliberately a ratio rather than fixed point. A rounded
    fixed-point step accumulates: at 4096ths of a page the error reaches
    a quarter of a second by the half-hour mark, which is a visible lip
    sync failure. An exact ratio keeps the error at the page
    quantization alone, about 23 ms, no matter how long the movie runs.
    """
    if delta_n <= 0:
        return Fraction(0)
    return adpcmb.exact_rate(delta_n) / (512 * frames.VBLANK_FPS)


def _write_sources(
    build_dir: Path,
    outcome_paths: dict[str, Path],
    result: encode.EncodeResult,
    request: BakeRequest,
    audio_pages: Fraction = Fraction(0),
) -> tuple[Path, Path]:
    generated = build_dir / "generated"
    generated.mkdir(parents=True, exist_ok=True)

    asm = generated / "movie_data.S"
    body = "    .section .rodata\n"
    for symbol, key in (
        ("movie_index", "index"),
        ("movie_keyframes", "keyframes"),
        ("movie_palettes", "palettes"),
        ("movie_epochs", "epochs"),
        ("movie_fix_palette", "fixpal"),
    ):
        body += _ASM_ENTRY.format(symbol=symbol, path=outcome_paths[key].name)
    asm.write_text(body)

    header = generated / "movie_data.h"
    header.write_text(
        _HEADER_TEMPLATE.format(
            frames=result.stats.frames,
            tiles=result.stats.tile_count,
            palettes=len(result.palette_set),
            epochs=len(result.palette_sets),
            epoch_palettes=len(result.palette_sets[0]),
            image_width=encode.FRAME_WIDTH,
            image_height=encode.FRAME_HEIGHT,
            tier_name=self_tier_name(request),
            chroma_percent=round(request.chroma_weight * 100),
            crom_percent=round(100 * result.stats.crom_payload_bytes / CROM_BANK_BYTES),
            audio_hz=round(request.audio_rate_hz),
            frame_hold=request.frame_hold,
            base_bank=result.palette_set.base_bank,
            keyframes=result.stats.keyframe_count,
            cols=encode.GRID_COLS,
            rows=encode.GRID_ROWS,
            max_updates=result.stats.max_updates,
            stream_banks=result.stream.bank_count(),
            stream_bytes=result.stats.stream_bytes,
            fps_num=frames.VBLANK_FPS.numerator,
            fps_den=frames.VBLANK_FPS.denominator,
            fix_palette=FIX_PALETTE_BANK,
            fix_defines=_fix_defines(),
            audio_page_num=audio_pages.numerator,
            audio_page_den=audio_pages.denominator or 1,
        )
    )
    return asm, header


def _preview_codec(path: Path) -> list[str]:
    """Lossless for .mkv, viewable h264 otherwise.

    A lossy preview layers its own artifacts on top of the quantizer's,
    which is exactly what a quality judgement must not do, so the
    verification path writes FFV1 and only the shareable copy is h264.
    """
    if path.suffix.lower() == ".mkv":
        return ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "rgb24"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p"]


def _write_audio_params(build_dir: Path, encoded: adpcmb.EncodedAudio) -> Path:
    """Emit the ADPCM-B register values the Z80 driver assembles against."""
    generated = build_dir / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    path = generated / "audio_params.s"
    path.write_text(
        "\n".join(
            [
                f"    ADPCM_B_START_LO = 0x{encoded.start_address & 0xFF:02x}",
                f"    ADPCM_B_START_HI = 0x{(encoded.start_address >> 8) & 0xFF:02x}",
                f"    ADPCM_B_END_LO = 0x{encoded.end_address & 0xFF:02x}",
                f"    ADPCM_B_END_HI = 0x{(encoded.end_address >> 8) & 0xFF:02x}",
                f"    ADPCM_B_DELTA_LO = 0x{encoded.delta_n & 0xFF:02x}",
                f"    ADPCM_B_DELTA_HI = 0x{(encoded.delta_n >> 8) & 0xFF:02x}",
                "",
            ]
        )
    )
    return path


class _PreviewWriter:
    """Feeds rendered frames to ffmpeg as they are produced.

    A full-capacity bake renders more frames than fit in memory, so the
    preview cannot be assembled at the end. Frames go down the pipe as
    the encoder finishes them.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rate = frames.VBLANK_FPS
        self._process = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{encode.FRAME_WIDTH}x{encode.FRAME_HEIGHT}",
                "-r",
                f"{rate.numerator}/{rate.denominator}",
                "-i",
                "-",
                *_preview_codec(path),
                str(path),
            ],
            stdin=subprocess.PIPE,
        )
        self._path = path

    def write(self, frame: np.ndarray) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(neocolor.color_index_to_rgb(frame).astype(np.uint8).tobytes())

    def close(self) -> None:
        assert self._process.stdin is not None
        self._process.stdin.close()
        if self._process.wait() != 0:
            msg = f"ffmpeg failed to write the preview at {self._path}"
            raise RuntimeError(msg)


def _write_preview(path: Path, rendered: np.ndarray) -> None:
    if rendered.shape[0] == 0:
        msg = "preview requested but no rendered frames were collected"
        raise ValueError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = frames.VBLANK_FPS
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{encode.FRAME_WIDTH}x{encode.FRAME_HEIGHT}",
            "-r",
            f"{rate.numerator}/{rate.denominator}",
            "-i",
            "-",
            *_preview_codec(path),
            str(path),
        ],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    for frame in rendered:
        process.stdin.write(neocolor.color_index_to_rgb(frame).astype(np.uint8).tobytes())
    process.stdin.close()
    if process.wait() != 0:
        msg = f"ffmpeg failed to write the preview at {path}"
        raise RuntimeError(msg)


def _palette_blob(result: encode.EncodeResult) -> bytes:
    """Every epoch's CRAM words, back to back in playing order."""
    return b"".join(palette_set.cram_blob() for palette_set in result.palette_sets)


def _epoch_blob(result: encode.EncodeResult) -> bytes:
    """The frame each epoch begins on.

    The half it lives in is not stored, because it alternates: an epoch
    occupies the half its index parity names, which is what lets the
    next set be written while the current one is still being read.
    """
    return np.asarray(result.epoch_starts, dtype=">u4").tobytes()


def _epoch_starts(
    grids: npt.NDArray[np.uint16], step: int, stride: int, total: int, floor: float
) -> list[int]:
    """Where epochs begin: at scene cuts, falling back to a fixed cadence.

    A bucket that straddles a cut has to carry colours for both sides of
    it, which is the thing per-scene palettes exist to avoid. Starting
    each epoch at a real cut measured 4% less error and 1.7% fewer tiles
    than an even split. Cuts further apart than the cadence are still
    subdivided, so a long static scene does not become one huge epoch.
    """
    grid = palettes.oklab_grid(1.0)
    starts = [0]
    previous = grids[0] if grids.shape[0] else None
    for row in range(1, grids.shape[0]):
        current = grids[row]
        if previous is not None:
            moved = ((grid[current] - grid[previous]) ** 2).sum(axis=4).mean(axis=(2, 3))
            frame = row * stride
            if float((moved > floor).mean()) > _SCENE_CUT_SHARE and frame - starts[-1] >= step // 4:
                starts.append(frame)
        previous = current
    filled: list[int] = []
    for index, start in enumerate(starts):
        stop = starts[index + 1] if index + 1 < len(starts) else total
        filled.extend(range(start, stop, step))

    # An epoch has to last long enough for the player to write the next
    # one into the other half of CRAM, a slice at a time. Any boundary
    # that arrives sooner leaves that half still holding the epoch
    # before last, and the picture comes back a checkerboard of two
    # scenes. The guard above spaces scene cuts from each other but says
    # nothing about the boundaries subdivision adds between them, so the
    # final list is what has to be thinned.
    spaced: list[int] = []
    for start in filled:
        if not spaced or start - spaced[-1] >= MIN_EPOCH_FRAMES:
            spaced.append(start)
    return spaced


def _epoch_samples(
    grids: npt.NDArray[np.uint16], request: BakeRequest
) -> list[tuple[int, npt.NDArray[np.uint16]]] | None:
    """Split the palette sample into one bucket per epoch.

    The sample is every `sample_stride`-th frame in order, so a movie
    frame maps onto a sample row by dividing by that stride. Buckets are
    thinned individually, since thinning the whole sample first would
    shuffle away the ordering the split depends on.
    """
    if request.palette_epoch_seconds <= 0.0:
        return None
    step = int(request.palette_epoch_seconds * float(frames.VBLANK_FPS))
    if step <= 0:
        return None
    stride = max(1, request.sample_stride)
    total = frames.frame_count(seconds=request.duration)
    buckets: list[tuple[int, npt.NDArray[np.uint16]]] = []
    for start in _epoch_starts(grids, step, stride, total, request.scene_cut_floor):
        stop = min(start + step, total)
        rows = grids[start // stride : (stop + stride - 1) // stride]
        if rows.shape[0] == 0:
            continue
        tiles = rows.reshape(-1, encode.TILE_PX, encode.TILE_PX)
        buckets.append((start, _thin_sample(tiles, request.seed + start)))
    return buckets or None


def run(request: BakeRequest) -> BakeOutcome:
    """Decode, encode, and write every cart artifact."""
    sample_clip = frames.sample(
        request.source,
        start=request.start,
        duration=request.duration,
        stride=max(1, request.sample_stride),
        fit=request.fit,
        denoise=request.denoise,
        motion_blur=request.motion_blur,
    )
    sample_grids = encode.to_tiles(neocolor.rgb_to_color_index(sample_clip))
    del sample_clip
    epoch_samples = _epoch_samples(sample_grids, request)
    sample_tiles = _thin_sample(
        sample_grids.reshape(-1, encode.TILE_PX, encode.TILE_PX), request.seed
    )
    del sample_grids

    preview = _PreviewWriter(request.preview) if request.preview else None
    chunks = frames.stream(
        request.source,
        start=request.start,
        duration=request.duration,
        fit=request.fit,
        denoise=request.denoise,
        motion_blur=request.motion_blur,
    )
    result = encode.encode_stream(
        chunks,
        encode.EncodeOptions(
            palette_count=request.palette_count,
            base_bank=request.base_bank,
            keyframe_interval=request.keyframe_interval,
            tolerance=request.tolerance,
            scene_cut_ratio=request.scene_cut_ratio,
            candidates=request.candidates,
            allow_flip=request.allow_flip,
            sample_stride=request.sample_stride,
            seed=request.seed,
            frame_hold=request.frame_hold,
            motion_masking=request.motion_masking,
            chroma_weight=request.chroma_weight,
            scene_cut_floor=request.scene_cut_floor,
            tile_budget=request.tile_budget,
            collect_rendered=False,
        ),
        sample_tiles=sample_tiles,
        epoch_samples=epoch_samples,
        total_frames=frames.frame_count(seconds=request.duration),
        on_render=preview.write if preview else None,
    )
    if preview:
        preview.close()

    baked = request.build_dir / "baked"
    baked.mkdir(parents=True, exist_ok=True)
    c1, c2 = result.dictionary.rom_images()
    payload = {
        "c1": (baked / "c1.bin", c1),
        "c2": (baked / "c2.bin", c2),
        "stream": (baked / "stream.bin", result.stream.blob()),
        "index": (baked / "index.bin", result.stream.index_blob()),
        "keyframes": (baked / "keyframes.bin", result.stream.keyframe_blob()),
        "palettes": (baked / "palettes.bin", _palette_blob(result)),
        "epochs": (baked / "epochs.bin", _epoch_blob(result)),
        "fix": (baked / "fix.s1", fixtiles.build_rom(pad_to=S_ROM_BYTES)),
        "fixpal": (
            baked / "fixpal.bin",
            b"".join(word.to_bytes(2, "big") for word in fixtiles.palette_words()),
        ),
    }
    artifacts: dict[str, Path] = {}
    for key, (path, blob) in payload.items():
        data = blob if len(blob) % 2 == 0 else blob + b"\x00"
        path.write_bytes(data)
        artifacts[key] = path

    audio_pages = Fraction(0)
    if request.audio:
        samples = _decode_audio(
            request.source, request.start, request.duration, request.audio_rate_hz
        )
        if samples.size:
            encoded = adpcmb.encode(samples, rate_hz=request.audio_rate_hz)
            voice = adpcmb.build_rom(encoded, pad_to=max(V_ROM_MIN_BYTES, len(encoded.payload)))
            (baked / "v2.bin").write_bytes(voice)
            artifacts["voice"] = baked / "v2.bin"
            _write_audio_params(request.build_dir, encoded)
            audio_pages = audio_pages_per_frame(encoded.delta_n)

    asm, header = _write_sources(request.build_dir, artifacts, result, request, audio_pages)
    artifacts["asm"] = asm
    artifacts["header"] = header

    if request.preview is not None:
        artifacts["preview"] = request.preview

    return BakeOutcome(
        request=request, result=result, build_dir=request.build_dir, artifacts=artifacts
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bake a video clip into Neo Geo cart data.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--quality", default=None)
    parser.add_argument("--audio-rate", type=float, default=None)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    parser.add_argument("--fit", choices=("fill", "letterbox"), default="fill")
    parser.add_argument("--denoise", type=float, default=None)
    parser.add_argument("--frame-hold", type=int, default=None)
    parser.add_argument("--motion-blur", type=int, default=0)
    parser.add_argument("--target-fps", type=float, default=None)
    parser.add_argument("--motion-masking", type=float, default=0.0)
    parser.add_argument("--chroma-weight", type=float, default=None)
    parser.add_argument("--scene-cut-floor", type=float, default=0.01)
    parser.add_argument("--palette-epoch-seconds", type=float, default=5.0)
    parser.add_argument("--tile-budget", type=int, default=None)
    parser.add_argument("--palette-count", type=int, default=240)
    parser.add_argument("--base-bank", type=int, default=16)
    parser.add_argument("--keyframe-interval", type=int, default=90)
    parser.add_argument("--tolerance", type=float, default=None)
    parser.add_argument("--scene-cut-ratio", type=float, default=0.90)
    parser.add_argument("--candidates", type=int, default=None)
    parser.add_argument("--flip", action="store_true")
    parser.add_argument("--sample-stride", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--preview", type=Path, default=None)
    parser.add_argument("--report-json", type=Path, default=None)
    return parser.parse_args(argv)


def _resolve_quality(args: argparse.Namespace) -> quality.Tier | None:
    """Pick the tier, measuring the source when asked to choose.

    `auto` calibrates and reports before anything is baked, because the
    choice it makes is the one worth arguing with, and a bake is far too
    slow to be the place that argument happens.
    """
    if args.quality is None:
        return None
    info = frames.probe(args.source)
    minutes = min(args.duration, max(0.0, info.duration - args.start))
    minutes /= quality.SECONDS_PER_MINUTE
    if args.quality != "auto":
        return quality.tier_by_name(args.quality)

    rate = calibrate.measure_reference_rate(
        args.source, fit=args.fit, seed=args.seed, start=args.start, duration=args.duration
    )
    print(
        quality.format_plan(
            source=str(args.source),
            minutes=minutes,
            width=info.width,
            height=info.height,
            source_fps=float(info.fps),
            has_audio=has_audio_stream(args.source),
            reference_rate=rate,
            vblank_fps=float(frames.VBLANK_FPS),
        ),
        file=sys.stderr,
    )
    shortfall = quality.shortfall_message(minutes, rate)
    if shortfall is not None:
        raise SystemExit(shortfall)
    chosen = quality.select(minutes, rate)
    assert chosen is not None
    return chosen.tier


def _pick[Knob: (int, float)](
    explicit: Knob | None, tier_value: Knob | None, fallback: Knob
) -> Knob:
    """An explicit flag wins, then the tier, then the built-in default."""
    if explicit is not None:
        return explicit
    if tier_value is not None:
        return tier_value
    return fallback


def _resolve_frame_hold(args: argparse.Namespace, tier: quality.Tier | None) -> int:
    """Turn a wanted frame rate into a hold, and reject a hold that does nothing.

    A hold counts display refreshes while the interesting quantity is
    source frames, so the two only agree when the source runs at the
    raster rate. Asking for 30 fps from a 24 fps source picks a hold of
    2, which skips no source frame and buys no tiles while still
    costing temporal accuracy. That is worth an error rather than a
    silent no-op.
    """
    hold = int(_pick(args.frame_hold, tier.frame_hold if tier else None, 1))
    if args.target_fps is not None:
        hold = frames.hold_for_target_fps(args.target_fps)
    if hold <= 1:
        return 1
    source_fps = frames.probe(args.source).fps
    if frames.source_frames_kept(hold, source_fps) >= 1.0:
        effective = float(frames.VBLANK_FPS) / hold
        msg = (
            f"a hold of {hold} runs at {effective:.1f} fps, at or above the source's "
            f"{float(source_fps):.1f} fps, so it drops no source frame and saves no tiles. "
            f"Use a hold of {int(float(frames.VBLANK_FPS) // float(source_fps)) + 1} or more."
        )
        raise SystemExit(msg)
    return hold


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    tier = _resolve_quality(args)
    frame_hold = _resolve_frame_hold(args, tier)
    tile_budget = quality.CROM_TILES if tier is not None else None
    audio_rate = args.audio_rate
    if audio_rate is None:
        audio_rate = quality.audio_hz_for(args.duration / quality.SECONDS_PER_MINUTE)
    outcome = run(
        BakeRequest(
            source=args.source,
            start=args.start,
            duration=args.duration,
            build_dir=args.build_dir,
            fit=args.fit,
            denoise=_pick(args.denoise, tier.denoise if tier else None, 0.0),
            frame_hold=frame_hold,
            motion_blur=args.motion_blur,
            motion_masking=args.motion_masking,
            chroma_weight=_pick(args.chroma_weight, tier.chroma_weight if tier else None, 1.0),
            scene_cut_floor=args.scene_cut_floor,
            palette_epoch_seconds=args.palette_epoch_seconds,
            quality=tier.name if tier is not None else args.quality,
            tile_budget=_pick(args.tile_budget, tile_budget, 0),
            palette_count=args.palette_count,
            base_bank=args.base_bank,
            keyframe_interval=args.keyframe_interval,
            tolerance=_pick(args.tolerance, tier.tolerance if tier else None, 0.0005),
            scene_cut_ratio=args.scene_cut_ratio,
            candidates=_pick(args.candidates, tier.candidates if tier else None, 12),
            allow_flip=args.flip,
            sample_stride=args.sample_stride,
            seed=args.seed,
            preview=args.preview,
            audio_rate_hz=audio_rate,
        )
    )
    report = outcome.report()
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
