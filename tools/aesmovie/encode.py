"""Turn vblank-rate frames into a tile dictionary and a command stream.

The encoder walks the clip one frame at a time holding a model of what
the LSPC currently shows. A slot is only touched when its source content
changed since the previous frame and the change is large enough to see,
which is what makes a 24 fps source cheap at the 59 Hz refresh: every
repeated source frame leaves all 280 slots alone and costs two bytes.

Keyframes rewrite all 280 slots whether or not they changed. That is
what makes them random-access entry points for the transport controls,
so the cost is deliberate. A keyframe also fires on a scene cut, where
most of the frame changed anyway and a delta would be no cheaper.

There is no framebuffer on this hardware, so there are no additive
residuals. Every correction resolves to pointing a slot at some tile
that exists in the dictionary, which means residual precision is
dictionary richness is C-ROM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

from aesmovie import crom, neocolor, palettes, stream
from aesmovie.dictionary import TileDictionary, TileRef

GRID_COLS: Final = stream.GRID_COLS
GRID_ROWS: Final = stream.GRID_ROWS
SLOT_COUNT: Final = stream.SLOT_COUNT
TILE_PX: Final = 16
FRAME_WIDTH: Final = GRID_COLS * TILE_PX
FRAME_HEIGHT: Final = GRID_ROWS * TILE_PX


@dataclass(frozen=True, slots=True)
class EncodeOptions:
    palette_count: int = 240
    base_bank: int = 16
    keyframe_interval: int = 45
    tolerance: float = 0.0
    scene_cut_ratio: float = 0.55
    candidates: int = 12
    allow_flip: bool = True
    sample_stride: int = 8
    seed: int = 0
    collect_rendered: bool = True


@dataclass(frozen=True, slots=True)
class EncodeStats:
    frames: int
    tile_count: int
    crom_payload_bytes: int
    crom_rom_bytes: int
    stream_bytes: int
    stream_rom_bytes: int
    keyframe_bytes: int
    delta_bytes: int
    index_bytes: int
    keyframe_count: int
    max_updates: int
    mean_updates: float
    mean_error: float


@dataclass(frozen=True, slots=True)
class EncodeResult:
    stream: stream.MovieStream
    dictionary: TileDictionary
    palette_set: palettes.PaletteSet
    updates_per_frame: npt.NDArray[np.int32]
    rendered: npt.NDArray[np.uint16]
    stats: EncodeStats


def to_tiles(frame_colors: npt.NDArray[np.uint16]) -> npt.NDArray[np.uint16]:
    """Split frames of color indices into a (frame, row, col, y, x) grid."""
    count = frame_colors.shape[0]
    return frame_colors.reshape(count, GRID_ROWS, TILE_PX, GRID_COLS, TILE_PX).transpose(
        0, 1, 3, 2, 4
    )


def from_tiles(tiles: npt.NDArray[np.uint16]) -> npt.NDArray[np.uint16]:
    """Reassemble one grid of tiles into a full frame."""
    return tiles.transpose(0, 2, 1, 3).reshape(FRAME_HEIGHT, FRAME_WIDTH)


def _validate(clip: npt.NDArray[np.uint8]) -> None:
    if clip.shape[0] == 0:
        msg = "cannot encode an empty clip"
        raise ValueError(msg)
    if clip.shape[1:] != (FRAME_HEIGHT, FRAME_WIDTH, 3):
        msg = f"frames must be 320x224 RGB, got {clip.shape[1:]}"
        raise ValueError(msg)


def _build_stats(
    *,
    movie: stream.MovieStream,
    dictionary: TileDictionary,
    updates_per_frame: npt.NDArray[np.int32],
    keyframe_bytes: int,
    delta_bytes: int,
    error_total: float,
    error_pixels: int,
) -> EncodeStats:
    tile_count = len(dictionary)
    return EncodeStats(
        frames=len(movie),
        tile_count=tile_count,
        crom_payload_bytes=tile_count * crom.TILE_BYTES,
        crom_rom_bytes=2 * crom.rom_size_for(tile_count),
        stream_bytes=movie.payload_size(),
        stream_rom_bytes=len(movie.blob()),
        keyframe_bytes=keyframe_bytes,
        delta_bytes=delta_bytes,
        index_bytes=len(movie.index_blob()),
        keyframe_count=len(movie.keyframes()),
        max_updates=int(updates_per_frame.max()),
        mean_updates=float(updates_per_frame.mean()),
        mean_error=(error_total / error_pixels) if error_pixels else 0.0,
    )


class _Screen:
    """What the LSPC is currently showing, tracked slot by slot."""

    def __init__(self, palette_set: palettes.PaletteSet) -> None:
        self._palette_set = palette_set
        self.tile = np.full((GRID_ROWS, GRID_COLS), -1, dtype=np.int64)
        self.palette = np.zeros((GRID_ROWS, GRID_COLS), dtype=np.int64)
        self.hflip = np.zeros((GRID_ROWS, GRID_COLS), dtype=bool)
        self.vflip = np.zeros((GRID_ROWS, GRID_COLS), dtype=bool)
        self.render = np.zeros((GRID_ROWS, GRID_COLS, TILE_PX, TILE_PX), dtype=np.uint16)

    def drift(
        self, source: npt.NDArray[np.uint16], targets: npt.NDArray[np.bool_]
    ) -> npt.NDArray[np.float32]:
        """Mean squared Oklab distance between the source and the picture on screen."""
        grid = palettes.oklab_grid()
        source_lab = grid[source[targets]]
        screen_lab = grid[self.render[targets]]
        return ((source_lab - screen_lab) ** 2).sum(axis=3).mean(axis=(1, 2))

    def commit(
        self,
        rows: npt.NDArray[np.int64],
        cols: npt.NDArray[np.int64],
        refs: list[TileRef],
        assignment: palettes.Assignment,
        *,
        force: bool,
    ) -> list[stream.SlotUpdate]:
        """Write the chosen tiles into the model and list what must be sent."""
        display = assignment.rendered(self._palette_set)
        updates: list[stream.SlotUpdate] = []
        for slot, (row, col) in enumerate(zip(rows, cols, strict=True)):
            ref = refs[slot]
            bank = self._palette_set.bank_of(int(assignment.palette_ids[slot]))
            already = (
                self.tile[row, col] == ref.index
                and self.palette[row, col] == bank
                and self.hflip[row, col] == ref.hflip
                and self.vflip[row, col] == ref.vflip
            )
            self.render[row, col] = display[slot]
            if already and not force:
                continue
            self.tile[row, col] = ref.index
            self.palette[row, col] = bank
            self.hflip[row, col] = ref.hflip
            self.vflip[row, col] = ref.vflip
            updates.append(
                stream.SlotUpdate(
                    col=int(col),
                    row=int(row),
                    tile=ref.index,
                    palette=bank,
                    hflip=ref.hflip,
                    vflip=ref.vflip,
                )
            )
        return updates


def encode(clip: npt.NDArray[np.uint8], options: EncodeOptions) -> EncodeResult:
    """Encode a clip into a tile dictionary and a keyframe-plus-delta stream."""
    _validate(clip)

    frame_colors = neocolor.rgb_to_color_index(clip)
    tiles = to_tiles(frame_colors)
    frames = tiles.shape[0]

    sample = tiles[:: max(1, options.sample_stride)].reshape(-1, TILE_PX, TILE_PX)
    palette_set = palettes.build_palette_set(
        sample, count=options.palette_count, base_bank=options.base_bank, seed=options.seed
    )
    assigner = palettes.PaletteAssigner(palette_set, candidates=options.candidates)
    dictionary = TileDictionary(allow_flip=options.allow_flip)
    screen = _Screen(palette_set)
    movie = stream.MovieStream()

    rendered = (
        np.zeros((frames, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint16)
        if options.collect_rendered
        else np.zeros((0, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint16)
    )
    updates_per_frame = np.zeros(frames, dtype=np.int32)
    keyframe_bytes = 0
    delta_bytes = 0
    error_total = 0.0
    error_pixels = 0
    last_keyframe = -options.keyframe_interval

    for index in range(frames):
        current = tiles[index]
        changed = (
            np.ones((GRID_ROWS, GRID_COLS), dtype=bool)
            if index == 0
            else (current != tiles[index - 1]).any(axis=(2, 3))
        )
        scene_cut = index == 0 or float(changed.mean()) >= options.scene_cut_ratio
        keyframe = scene_cut or (index - last_keyframe >= options.keyframe_interval)

        if keyframe:
            last_keyframe = index
            targets = np.ones((GRID_ROWS, GRID_COLS), dtype=bool)
        else:
            targets = changed
            if options.tolerance > 0.0 and targets.any():
                keep = np.zeros_like(targets)
                keep[targets] = screen.drift(current, targets) > options.tolerance
                targets = keep

        updates: list[stream.SlotUpdate] = []
        if targets.any():
            rows, cols = np.nonzero(targets)
            assignment = assigner.assign(current[rows, cols])
            error_total += float(assignment.error.sum())
            error_pixels += assignment.error.size * TILE_PX * TILE_PX
            refs = dictionary.intern_batch(assignment.nibbles)
            updates = screen.commit(rows, cols, refs, assignment, force=keyframe)

        before = movie.payload_size()
        movie.append(updates, keyframe=keyframe)
        written = movie.payload_size() - before
        if keyframe:
            keyframe_bytes += written
        else:
            delta_bytes += written

        updates_per_frame[index] = len(updates)
        if options.collect_rendered:
            rendered[index] = from_tiles(screen.render)

    stats = _build_stats(
        movie=movie,
        dictionary=dictionary,
        updates_per_frame=updates_per_frame,
        keyframe_bytes=keyframe_bytes,
        delta_bytes=delta_bytes,
        error_total=error_total,
        error_pixels=error_pixels,
    )

    return EncodeResult(
        stream=movie,
        dictionary=dictionary,
        palette_set=palette_set,
        updates_per_frame=updates_per_frame,
        rendered=rendered,
        stats=stats,
    )
