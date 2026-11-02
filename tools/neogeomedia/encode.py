from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from fmvcore import colour

from neogeomedia import crom, neocolor, palettes, redraw, stream
from neogeomedia.dictionary import TileDictionary
from neogeomedia.ratecontrol import RateController
from neogeomedia.screen import Screen

GRID_COLS: Final = stream.GRID_COLS
GRID_ROWS: Final = stream.GRID_ROWS
SLOT_COUNT: Final = stream.SLOT_COUNT
TILE_PX: Final = 16
BLURRED_EVERY: Final = 8
FRAME_WIDTH: Final = GRID_COLS * TILE_PX
FRAME_HEIGHT: Final = GRID_ROWS * TILE_PX


@dataclass(frozen=True, slots=True)
class EncodeOptions:
    palette_count: int = 240
    base_bank: int = 16
    keyframe_interval: int = 90
    tolerance: float = 0.0005
    scene_cut_ratio: float = 0.90
    candidates: int = 12
    sample_stride: int = 8
    seed: int = 0
    collect_rendered: bool = True
    allow_flip: bool = False
    dictionary_capacity: int = 1 << 20
    frame_hold: int = 1
    motion_masking: float = 0.0
    chroma_weight: float = palettes.DEFAULT_CHROMA_WEIGHT
    scene_cut_floor: float = 0.01
    tile_budget: int = 0
    rate_control_gain: float = 4.0
    max_tolerance_scale: float = 4096.0
    stop_when_over_budget: bool = False
    dither: float = palettes.MAX_DITHER


@dataclass(frozen=True, slots=True)
class EncodeStats:
    frames: int
    tile_count: int
    dictionary_full: bool
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
    displayed_error: float
    blurred_error: float
    peak_tolerance: float
    budget_exceeded: bool
    truncated: bool
    rate_control_exhausted: bool


@dataclass(frozen=True, slots=True)
class EncodeResult:
    stream: stream.MovieStream
    dictionary: TileDictionary
    palette_set: palettes.PaletteSet
    palette_sets: list[palettes.PaletteSet]
    epoch_starts: list[int]
    updates_per_frame: npt.NDArray[np.int32]
    rendered: npt.NDArray[np.uint16]
    stats: EncodeStats


def to_tiles(frame_colors: npt.NDArray[np.uint16]) -> npt.NDArray[np.uint16]:
    count = frame_colors.shape[0]
    return frame_colors.reshape(count, GRID_ROWS, TILE_PX, GRID_COLS, TILE_PX).transpose(
        0, 1, 3, 2, 4
    )


def from_tiles(tiles: npt.NDArray[np.uint16]) -> npt.NDArray[np.uint16]:
    return tiles.transpose(0, 2, 1, 3).reshape(FRAME_HEIGHT, FRAME_WIDTH)


def _new_dictionary(options: EncodeOptions) -> TileDictionary:
    capacity = options.dictionary_capacity
    if options.tile_budget > 0:
        capacity = min(capacity, options.tile_budget)
    return TileDictionary(allow_flip=options.allow_flip, capacity=capacity)


def _tile_frames(
    chunks: Iterable[npt.NDArray[np.uint8]],
) -> Iterator[npt.NDArray[np.uint16]]:
    for chunk in chunks:
        grids = to_tiles(neocolor.rgb_to_color_index(chunk))
        for index in range(grids.shape[0]):
            yield grids[index]


def _validate(clip: npt.NDArray[np.uint8]) -> None:
    if clip.shape[0] == 0:
        msg = "cannot encode an empty clip"
        raise ValueError(msg)
    if clip.shape[1:] != (FRAME_HEIGHT, FRAME_WIDTH, 3):
        msg = f"frames must be 320x224 RGB, got {clip.shape[1:]}"
        raise ValueError(msg)


@dataclass(slots=True)
class _Totals:
    keyframe_bytes: int = 0
    delta_bytes: int = 0
    error_total: float = 0.0
    error_pixels: int = 0
    displayed_error_total: float = 0.0
    displayed_frames: int = 0
    blurred_error_total: float = 0.0
    blurred_frames: int = 0
    peak_tolerance: float = 0.0

    def track_tolerance(self, tolerance: float) -> float:
        self.peak_tolerance = max(self.peak_tolerance, tolerance)
        return tolerance


def encode(clip: npt.NDArray[np.uint8], options: EncodeOptions) -> EncodeResult:
    _validate(clip)
    sample = to_tiles(neocolor.rgb_to_color_index(clip[:: max(1, options.sample_stride)]))
    return encode_stream(
        [clip],
        options,
        sample_tiles=sample.reshape(-1, TILE_PX, TILE_PX),
        total_frames=clip.shape[0],
    )


def _fit(
    tiles: npt.NDArray[np.uint16], options: EncodeOptions, *, count: int, base_bank: int, seed: int
) -> palettes.PaletteSet:
    return palettes.build_palette_set(
        tiles, count=count, base_bank=base_bank, seed=seed, chroma_weight=options.chroma_weight
    )


def _build_palette_sets(
    options: EncodeOptions,
    sample_tiles: npt.NDArray[np.uint16],
    epoch_samples: Sequence[tuple[int, npt.NDArray[np.uint16]]] | None,
) -> tuple[list[int], list[palettes.PaletteSet]]:
    whole = {"count": options.palette_count, "base_bank": options.base_bank, "seed": options.seed}
    if not epoch_samples:
        return [0], [_fit(sample_tiles, options, **whole)]
    if len(epoch_samples) == 1:
        start, tiles = epoch_samples[0]
        return [start], [_fit(tiles, options, **whole)]
    half = options.palette_count // 2
    starts = [start for start, _ in epoch_samples]
    sets = [
        _fit(
            tiles,
            options,
            count=half,
            base_bank=options.base_bank + (epoch % 2) * half,
            seed=options.seed + epoch,
        )
        for epoch, (_, tiles) in enumerate(epoch_samples)
    ]
    return starts, sets


def _enter_epoch(
    palette_set: palettes.PaletteSet,
    epoch: int,
    screen: Screen,
    dictionary: TileDictionary,
    options: EncodeOptions,
) -> palettes.PaletteAssigner:
    screen.retarget(palette_set)
    dictionary.reseed(epoch)
    return palettes.PaletteAssigner(
        palette_set, candidates=options.candidates, dither=options.dither
    )


def _advance_epoch(
    epoch: int,
    index: int,
    assigner: palettes.PaletteAssigner,
    *,
    epoch_starts: Sequence[int],
    palette_sets: Sequence[palettes.PaletteSet],
    screen: Screen,
    dictionary: TileDictionary,
    options: EncodeOptions,
) -> tuple[int, palettes.PaletteAssigner]:
    if epoch + 1 >= len(epoch_starts) or index < epoch_starts[epoch + 1]:
        return epoch, assigner
    following = epoch + 1
    return following, _enter_epoch(palette_sets[following], following, screen, dictionary, options)


def _render_buffer(total_frames: int, options: EncodeOptions) -> npt.NDArray[np.uint16]:
    kept = total_frames if options.collect_rendered else 0
    return np.zeros((kept, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint16)


def _should_stop(dictionary: TileDictionary, options: EncodeOptions) -> bool:
    return options.stop_when_over_budget and _out_of_room(dictionary, options)


def _out_of_room(dictionary: TileDictionary, options: EncodeOptions) -> bool:
    if dictionary.is_full():
        return True
    return options.tile_budget > 0 and len(dictionary) >= options.tile_budget


def _record_frame(
    screen: Screen,
    incoming: npt.NDArray[np.uint16],
    index: int,
    rendered: npt.NDArray[np.uint16],
    *,
    totals: _Totals,
    options: EncodeOptions,
    on_render: Callable[[npt.NDArray[np.uint16]], None] | None,
) -> None:
    totals.displayed_error_total += screen.fidelity(incoming)
    totals.displayed_frames += 1
    if index % BLURRED_EVERY == 0:
        totals.blurred_error_total += _blurred(screen.render, incoming)
        totals.blurred_frames += 1
    if options.collect_rendered:
        rendered[index] = from_tiles(screen.render)
    if on_render is not None:
        on_render(from_tiles(screen.render))


def _blurred(shown: npt.NDArray[np.uint16], wanted: npt.NDArray[np.uint16]) -> float:
    shown_rgb = neocolor.color_index_to_rgb(from_tiles(shown))
    wanted_rgb = neocolor.color_index_to_rgb(from_tiles(wanted))
    return colour.blurred_error(shown_rgb[None], wanted_rgb[None])


def _mean(total: float, count: int) -> float:
    return (total / count) if count else 0.0


class _Encoder:
    def __init__(
        self,
        options: EncodeOptions,
        epochs: tuple[list[int], list[palettes.PaletteSet]],
        total_frames: int,
        on_render: Callable[[npt.NDArray[np.uint16]], None] | None,
    ) -> None:
        self.options, self.total_frames, self.on_render = options, total_frames, on_render
        self.epoch_starts, self.palette_sets = epochs
        self.epoch = 0
        self.dictionary = _new_dictionary(options)
        self.screen = Screen(self.palette_sets[0])
        self.assigner = _enter_epoch(self.palette_sets[0], 0, self.screen, self.dictionary, options)
        self.movie = stream.MovieStream()
        self.rendered = _render_buffer(total_frames, options)
        self.updates_per_frame = np.zeros(total_frames, dtype=np.int32)
        self.totals, self.controller = _Totals(), RateController(options)
        self.last_keyframe = -options.keyframe_interval
        self.previous: npt.NDArray[np.uint16] | None = None
        self.pending = np.zeros((GRID_ROWS, GRID_COLS), dtype=bool)
        self.hold = max(1, options.frame_hold)
        self.held: npt.NDArray[np.uint16] | None = None

    def _source(
        self, index: int, incoming: npt.NDArray[np.uint16]
    ) -> tuple[npt.NDArray[np.uint16], npt.NDArray[np.uint16] | None, npt.NDArray[np.bool_]]:
        if index % self.hold == 0:
            self.held = incoming
        current = self.held if self.held is not None else incoming
        changed = (
            np.ones((GRID_ROWS, GRID_COLS), dtype=bool)
            if self.previous is None
            else (current != self.previous).any(axis=(2, 3))
        )
        previous_source, self.previous = self.previous, current
        return current, previous_source, changed

    def _advance(self, index: int) -> None:
        self.epoch, self.assigner = _advance_epoch(
            self.epoch,
            index,
            self.assigner,
            epoch_starts=self.epoch_starts,
            palette_sets=self.palette_sets,
            screen=self.screen,
            dictionary=self.dictionary,
            options=self.options,
        )

    def _is_keyframe(
        self,
        index: int,
        current: npt.NDArray[np.uint16],
        previous_source: npt.NDArray[np.uint16] | None,
        changed: npt.NDArray[np.bool_],
    ) -> bool:
        scene_cut = redraw.is_scene_cut(current, previous_source, changed, index, self.options) or (
            index in self.epoch_starts and index > 0
        )
        keyframe = scene_cut or (index - self.last_keyframe >= self.options.keyframe_interval)
        if keyframe:
            self.last_keyframe = index
        return keyframe

    def _updates(
        self, current: npt.NDArray[np.uint16], targets: npt.NDArray[np.bool_], keyframe: bool
    ) -> list[stream.SlotUpdate]:
        if not targets.any():
            return []
        rows, cols = np.nonzero(targets)
        assignment = self.assigner.assign(current[rows, cols])
        self.totals.error_total += float(assignment.error.sum())
        self.totals.error_pixels += assignment.error.size * TILE_PX * TILE_PX
        refs = self.dictionary.intern_batch(assignment.nibbles)
        return self.screen.commit(rows, cols, refs, assignment, force=keyframe)

    def _append(self, updates: list[stream.SlotUpdate], keyframe: bool) -> None:
        before = self.movie.payload_size()
        self.movie.append(updates, keyframe=keyframe)
        written = self.movie.payload_size() - before
        if keyframe:
            self.totals.keyframe_bytes += written
        else:
            self.totals.delta_bytes += written

    def step(self, index: int, incoming: npt.NDArray[np.uint16]) -> bool:
        current, previous_source, changed = self._source(index, incoming)
        self._advance(index)
        keyframe = self._is_keyframe(index, current, previous_source, changed)
        tolerance = self.totals.track_tolerance(
            self.controller.tolerance(len(self.dictionary), index, self.total_frames)
        )
        targets, self.pending = redraw.select_targets(
            current,
            previous_source,
            changed,
            self.pending,
            screen=self.screen,
            keyframe=keyframe,
            options=self.options,
            tolerance=tolerance,
        )
        updates = self._updates(current, targets, keyframe)
        self._append(updates, keyframe)
        self.updates_per_frame[index] = len(updates)
        self._record(index, incoming)
        return _should_stop(self.dictionary, self.options)

    def _record(self, index: int, incoming: npt.NDArray[np.uint16]) -> None:
        _record_frame(
            self.screen,
            incoming,
            index,
            self.rendered,
            totals=self.totals,
            options=self.options,
            on_render=self.on_render,
        )

    def _stats(self, updates_per_frame: npt.NDArray[np.int32]) -> EncodeStats:
        movie, totals, options = self.movie, self.totals, self.options
        tile_count = len(self.dictionary)
        ceiling = options.tolerance * options.max_tolerance_scale
        return EncodeStats(
            frames=len(movie),
            tile_count=tile_count,
            dictionary_full=self.dictionary.is_full(),
            crom_payload_bytes=tile_count * crom.TILE_BYTES,
            crom_rom_bytes=2 * crom.rom_size_for(tile_count),
            stream_bytes=movie.payload_size(),
            stream_rom_bytes=len(movie.blob()),
            keyframe_bytes=totals.keyframe_bytes,
            delta_bytes=totals.delta_bytes,
            index_bytes=len(movie.index_blob()),
            keyframe_count=len(movie.keyframes()),
            max_updates=int(updates_per_frame.max()),
            mean_updates=float(updates_per_frame.mean()),
            mean_error=_mean(totals.error_total, totals.error_pixels),
            displayed_error=_mean(totals.displayed_error_total, totals.displayed_frames),
            blurred_error=_mean(totals.blurred_error_total, totals.blurred_frames),
            peak_tolerance=totals.peak_tolerance,
            budget_exceeded=bool(options.tile_budget > 0 and tile_count >= options.tile_budget),
            truncated=bool(self.total_frames > 0 and len(movie) < self.total_frames),
            rate_control_exhausted=bool(ceiling > 0.0 and totals.peak_tolerance >= ceiling),
        )

    def result(self) -> EncodeResult:
        updates_per_frame = self.updates_per_frame[: len(self.movie)]
        return EncodeResult(
            stream=self.movie,
            dictionary=self.dictionary,
            palette_set=self.palette_sets[0],
            palette_sets=self.palette_sets,
            epoch_starts=self.epoch_starts,
            updates_per_frame=updates_per_frame,
            rendered=self.rendered,
            stats=self._stats(updates_per_frame),
        )


def encode_stream(
    chunks: Iterable[npt.NDArray[np.uint8]],
    options: EncodeOptions,
    *,
    sample_tiles: npt.NDArray[np.uint16],
    total_frames: int,
    epoch_samples: Sequence[tuple[int, npt.NDArray[np.uint16]]] | None = None,
    on_render: Callable[[npt.NDArray[np.uint16]], None] | None = None,
) -> EncodeResult:
    epochs = _build_palette_sets(options, sample_tiles, epoch_samples)
    encoder = _Encoder(options, epochs, total_frames, on_render)
    for index, incoming in enumerate(_tile_frames(chunks)):
        if encoder.step(index, incoming):
            break
    return encoder.result()
