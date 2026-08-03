"""Decode a source clip into vblank-rate 320x224 RGB frames.

The Neo Geo raster is 384 pixels by 264 lines at a 6 MHz dot clock, so
the refresh is 6000000 / (384 * 264), about 59.1856 Hz. The player
advances one movie frame per vblank, so the baker resamples the source
to exactly that rate. A 24 fps source therefore repeats most frames,
and a repeated frame costs nothing downstream because every tile slot
is unchanged.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Final, Literal

import numpy as np
import numpy.typing as npt

VBLANK_FPS: Final = Fraction(6_000_000, 384 * 264)
TARGET_WIDTH: Final = 320
TARGET_HEIGHT: Final = 224
TILE_PX: Final = 16

FitMode = Literal["fill", "letterbox"]
_FIT_MODES: Final = ("fill", "letterbox")


@dataclass(frozen=True, slots=True)
class VideoInfo:
    width: int
    height: int
    duration: float


@dataclass(frozen=True, slots=True)
class Denoise:
    """hqdn3d strengths, spatial then temporal.

    Denoising runs after the downscale rather than before it, because
    what matters here is the temporal stability of the 320x224 tiles the
    encoder deduplicates. Grain that survives into the scaled frame makes
    every tile differ from its neighbour in time, which destroys the
    delta path and inflates the dictionary. Cleaning the scaled image
    targets exactly that.
    """

    luma_spatial: float = 4.0
    chroma_spatial: float = 3.0
    luma_temporal: float = 6.0
    chroma_temporal: float = 4.5

    def scaled(self, strength: float) -> Denoise:
        return Denoise(
            luma_spatial=self.luma_spatial * strength,
            chroma_spatial=self.chroma_spatial * strength,
            luma_temporal=self.luma_temporal * strength,
            chroma_temporal=self.chroma_temporal * strength,
        )

    def to_filter(self) -> str:
        return (
            f"hqdn3d={self.luma_spatial:g}:{self.chroma_spatial:g}"
            f":{self.luma_temporal:g}:{self.chroma_temporal:g}"
        )


@dataclass(frozen=True, slots=True)
class Geometry:
    crop: tuple[int, int]
    image: tuple[int, int]
    target: tuple[int, int]
    pad_top: int


def frame_count(*, seconds: float) -> int:
    """Number of vblank-rate frames covering a duration."""
    return int(seconds * VBLANK_FPS)


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        msg = f"{name} not found on PATH"
        raise RuntimeError(msg)
    return path


def probe(path: Path) -> VideoInfo:
    """Read the source geometry and duration with ffprobe."""
    path = Path(path)
    if not path.is_file():
        msg = f"source clip not found: {path}"
        raise FileNotFoundError(msg)
    result = subprocess.run(
        [
            _require_tool("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    return VideoInfo(
        width=int(stream["width"]),
        height=int(stream["height"]),
        duration=float(payload["format"]["duration"]),
    )


def _even(value: int) -> int:
    return value - (value % 2)


def plan_geometry(
    source_width: int,
    source_height: int,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    *,
    fit: FitMode = "fill",
) -> Geometry:
    """Work out the crop, scale, and pad that map a source onto the raster."""
    if fit not in _FIT_MODES:
        msg = f"unknown fit mode {fit!r}, expected one of {_FIT_MODES}"
        raise ValueError(msg)

    target = (target_width, target_height)
    source_aspect = source_width / source_height

    if fit == "fill":
        target_aspect = target_width / target_height
        if source_aspect > target_aspect:
            crop = (_even(round(source_height * target_aspect)), _even(source_height))
        else:
            crop = (_even(source_width), _even(round(source_width / target_aspect)))
        return Geometry(crop=crop, image=target, target=target, pad_top=0)

    crop = (_even(source_width), _even(source_height))
    rows_total = target_height // TILE_PX
    ideal_rows = (target_width / source_aspect) / TILE_PX
    image_rows = max(
        (
            rows
            for rows in range(rows_total, 0, -1)
            if rows <= ideal_rows and (rows_total - rows) % 2 == 0
        ),
        default=rows_total,
    )
    image_height = image_rows * TILE_PX
    return Geometry(
        crop=crop,
        image=(target_width, image_height),
        target=target,
        pad_top=(target_height - image_height) // 2,
    )


def build_filter(
    geometry: Geometry,
    fps: Fraction = VBLANK_FPS,
    denoise: float = 0.0,
    motion_blur: int = 0,
) -> str:
    """Build the ffmpeg filter chain for a planned geometry.

    Scaling runs before the frame-rate resample so upsampling to the
    vblank rate duplicates already-scaled frames instead of scaling the
    same source frame two or three times.
    """
    crop_w, crop_h = geometry.crop
    image_w, image_h = geometry.image
    target_w, target_h = geometry.target
    stages = [
        f"crop={crop_w}:{crop_h}",
        f"scale={image_w}:{image_h}:flags=lanczos",
    ]
    if denoise > 0.0:
        stages.append(Denoise().scaled(denoise).to_filter())
    if motion_blur > 1:
        stages.append(f"tmix=frames={motion_blur}")
    if geometry.pad_top:
        stages.append(f"pad={target_w}:{target_h}:0:{geometry.pad_top}:black")
    stages.append(f"fps={fps.numerator}/{fps.denominator}")
    stages.append("format=rgb24")
    return ",".join(stages)


def decode(
    path: Path,
    *,
    start: float,
    duration: float,
    fit: FitMode = "fill",
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    denoise: float = 0.0,
    motion_blur: int = 0,
) -> npt.NDArray[np.uint8]:
    """Decode a clip window into vblank-rate RGB frames."""
    info = probe(path)
    geometry = plan_geometry(info.width, info.height, target_width, target_height, fit=fit)
    wanted = frame_count(seconds=duration)
    result = subprocess.run(
        [
            _require_tool("ffmpeg"),
            "-v",
            "error",
            "-ss",
            f"{start:.6f}",
            "-i",
            str(path),
            "-t",
            f"{duration:.6f}",
            "-vf",
            build_filter(geometry, denoise=denoise, motion_blur=motion_blur),
            "-an",
            "-sn",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    stride = target_width * target_height * 3
    produced = len(result.stdout) // stride
    if produced == 0:
        msg = f"ffmpeg produced no frames for {path} at {start}s for {duration}s"
        raise RuntimeError(msg)
    clip = np.frombuffer(result.stdout[: produced * stride], dtype=np.uint8).reshape(
        produced, target_height, target_width, 3
    )
    if produced >= wanted:
        return np.array(clip[:wanted])
    if wanted - produced > 2:
        msg = f"ffmpeg produced {produced} frames, expected {wanted}"
        raise RuntimeError(msg)
    tail = np.repeat(clip[-1:], wanted - produced, axis=0)
    return np.concatenate([clip, tail], axis=0)


DEFAULT_CHUNK_FRAMES: Final = 64


def _decode_process(
    path: Path,
    *,
    start: float,
    duration: float,
    fit: FitMode,
    target_width: int,
    target_height: int,
    denoise: float,
    motion_blur: int,
) -> subprocess.Popen[bytes]:
    info = probe(path)
    geometry = plan_geometry(info.width, info.height, target_width, target_height, fit=fit)
    return subprocess.Popen(
        [
            _require_tool("ffmpeg"),
            "-v",
            "error",
            "-ss",
            f"{start:.6f}",
            "-i",
            str(path),
            "-t",
            f"{duration:.6f}",
            "-vf",
            build_filter(geometry, denoise=denoise, motion_blur=motion_blur),
            "-an",
            "-sn",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def stream(
    path: Path,
    *,
    start: float,
    duration: float,
    fit: FitMode = "fill",
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    denoise: float = 0.0,
    motion_blur: int = 0,
    chunk_frames: int = DEFAULT_CHUNK_FRAMES,
) -> Iterator[npt.NDArray[np.uint8]]:
    """Yield decoded frames in chunks instead of all at once.

    A cart filled to the 128 MiB character-ROM ceiling is about four and
    a half minutes of video, which is roughly 15,600 frames. Holding
    those as RGB would be over three gigabytes before the encoder has
    allocated anything, so a full-capacity bake is only possible if the
    frames arrive a chunk at a time.
    """
    stride = target_width * target_height * 3
    wanted = frame_count(seconds=duration)
    process = _decode_process(
        path,
        start=start,
        duration=duration,
        fit=fit,
        target_width=target_width,
        target_height=target_height,
        denoise=denoise,
        motion_blur=motion_blur,
    )
    assert process.stdout is not None
    produced = 0
    try:
        while produced < wanted:
            batch = min(chunk_frames, wanted - produced)
            payload = process.stdout.read(batch * stride)
            if not payload:
                break
            whole = len(payload) // stride
            if whole == 0:
                break
            yield np.frombuffer(payload[: whole * stride], dtype=np.uint8).reshape(
                whole, target_height, target_width, 3
            )
            produced += whole
    finally:
        process.stdout.close()
        process.wait()


def sample(
    path: Path,
    *,
    start: float,
    duration: float,
    stride: int,
    fit: FitMode = "fill",
    denoise: float = 0.0,
    motion_blur: int = 0,
) -> npt.NDArray[np.uint8]:
    """Every `stride`-th frame, for fitting the palette set."""
    kept: list[npt.NDArray[np.uint8]] = []
    index = 0
    for chunk in stream(
        path, start=start, duration=duration, fit=fit, denoise=denoise, motion_blur=motion_blur
    ):
        offsets = [i for i in range(len(chunk)) if (index + i) % stride == 0]
        if offsets:
            kept.append(chunk[offsets])
        index += len(chunk)
    if not kept:
        return np.zeros((0, TARGET_HEIGHT, TARGET_WIDTH, 3), dtype=np.uint8)
    return np.concatenate(kept)
