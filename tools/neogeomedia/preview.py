from __future__ import annotations

import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
from fmvcore import video

from neogeomedia import encode, frames, neocolor

PREVIEW_FRAMES: Final = 4
STILL_SUFFIX: Final = ".png"


MOST_DRIFT: Final = 7
PICTURE: Final = video.Picture(
    width=encode.FRAME_WIDTH,
    height=encode.FRAME_HEIGHT,
    rate=frames.VBLANK_FPS,
    most_drift=MOST_DRIFT,
)
CHECKED_FRAMES: Final = 60


class PreviewWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._process = subprocess.Popen(video.writer_command(path, PICTURE), stdin=subprocess.PIPE)
        self._path = path
        self._kept: tuple[npt.NDArray[np.uint8], ...] = ()

    def watch(self, chunks: Iterable[npt.NDArray[np.uint8]]) -> Iterable[npt.NDArray[np.uint8]]:
        return chunks

    def write(self, frame: np.ndarray) -> None:
        assert self._process.stdin is not None
        shown = neocolor.color_index_to_rgb(frame).astype(np.uint8)
        if len(self._kept) < CHECKED_FRAMES:
            self._kept = (*self._kept, shown)
        self._process.stdin.write(shown.tobytes())

    def close(self) -> None:
        assert self._process.stdin is not None
        self._process.stdin.close()
        if self._process.wait() != 0:
            msg = f"ffmpeg failed to write the preview at {self._path}"
            raise RuntimeError(msg)
        video.check(self._path, PICTURE, list(self._kept))


def picks(total: int) -> tuple[int, ...]:
    if total < 1:
        return ()
    spread = np.linspace(0, total - 1, min(PREVIEW_FRAMES, total)).astype(int)
    return tuple(sorted({int(index) for index in spread}))


class StillWriter:
    def __init__(self, path: Path, total: int) -> None:
        self._path = path
        self._picks = picks(total)
        self._sources: dict[int, npt.NDArray[np.uint8]] = {}
        self._shown: dict[int, npt.NDArray[np.uint8]] = {}
        self._written = 0

    def watch(self, chunks: Iterable[npt.NDArray[np.uint8]]) -> Iterator[npt.NDArray[np.uint8]]:
        first = 0
        for chunk in chunks:
            kept = {i: chunk[i - first] for i in self._picks if first <= i < first + len(chunk)}
            self._sources = {**self._sources, **kept}
            first += len(chunk)
            yield chunk

    def write(self, frame: np.ndarray) -> None:
        index = self._written
        self._written = index + 1
        if index in self._picks:
            shown = neocolor.color_index_to_rgb(frame).astype(np.uint8)
            self._shown = {**self._shown, index: shown}

    def close(self) -> None:
        both = [i for i in self._picks if i in self._sources and i in self._shown]
        if not both:
            msg = "a preview needs at least one frame shown and one source frame"
            raise ValueError(msg)
        rows = [np.concatenate([self._shown[i], self._sources[i]], axis=1) for i in both]
        save_png(self._path, np.concatenate(rows, axis=0))


def save_png(path: Path, image: npt.NDArray[np.uint8]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = image.shape[:2]
    command = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24"]
    subprocess.run(
        [*command, "-s", f"{width}x{height}", "-i", "-", str(path)],
        input=np.ascontiguousarray(image).tobytes(),
        check=True,
    )


def open_writer(path: Path, total: int) -> PreviewWriter | StillWriter:
    if path.suffix.lower() == STILL_SUFFIX:
        return StillWriter(path, total)
    return PreviewWriter(path)
