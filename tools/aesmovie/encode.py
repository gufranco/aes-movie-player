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

from collections.abc import Callable, Iterable, Iterator, Sequence
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
    peak_tolerance: float
    budget_exceeded: bool


@dataclass(frozen=True, slots=True)
class EncodeResult:
    stream: stream.MovieStream
    dictionary: TileDictionary
    palette_set: palettes.PaletteSet
    palette_sets: list[palettes.PaletteSet]
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


def _masked_threshold(
    current: npt.NDArray[np.uint16],
    previous: npt.NDArray[np.uint16] | None,
    targets: npt.NDArray[np.bool_],
    options: EncodeOptions,
    tolerance: float,
) -> npt.NDArray[np.float32] | float:
    """Per-slot error budget, raised where the picture is moving.

    Vision is far less sensitive to spatial detail in a region that is
    changing quickly, and far more sensitive in one that is still, where
    an error sits on screen and stays visible. A single flat threshold
    spends the same precision on both. Scaling the budget by how much
    the source itself moved buys back tiles from exactly the places the
    eye cannot inspect them, which is the whole point of a lossy codec.

    A masking factor of zero reproduces the flat threshold.

    Masking is only safe because a skipped slot stays pending and is
    re-tested every frame. Once its motion stops the budget collapses
    back to the flat threshold and the slot is corrected, so an error
    hidden by movement never outlives the movement that hid it.
    """
    if options.motion_masking <= 0.0 or previous is None:
        return tolerance
    moved = _movement(current, previous, targets, options.chroma_weight)
    return tolerance + options.motion_masking * moved


def _movement(
    current: npt.NDArray[np.uint16],
    previous: npt.NDArray[np.uint16],
    targets: npt.NDArray[np.bool_],
    chroma_weight: float,
) -> npt.NDArray[np.float32]:
    """Mean squared Oklab distance the source itself moved, per slot."""
    grid = palettes.oklab_grid(chroma_weight)
    moved: npt.NDArray[np.float32] = (
        ((grid[current[targets]] - grid[previous[targets]]) ** 2).sum(axis=3).mean(axis=(1, 2))
    )
    return moved


class _RateController:
    """Keeps tile spending on pace so the movie fits the cartridge.

    A tier is chosen from a sample, and a sample cannot know that the
    third act is busier than the first. Left alone the dictionary runs
    out partway through and every remaining slot freezes, which wrecks
    the end of the film instead of costing a little quality across all
    of it.

    Correcting from cumulative overshoot proved far too slow. By the
    time the running total is visibly over, the only thresholds that
    would still recover the deficit are ones this controller would take
    hundreds of frames to reach, so it arrives after the dictionary has
    already hit its cap. This instead compares the recent rate of tile
    creation against the rate the remaining budget affords, and holds a
    multiplier that ratchets up while spending is too fast and decays
    while it is not. Because the multiplier persists between frames it
    keeps climbing until it actually bites, which is the property a
    per-frame calculation cannot have.

    The multiplier never falls below one, so the tier's own threshold is
    a floor and the controller can only tighten.
    """

    _SMOOTHING: Final = 0.05
    _RAMP_LIMIT: Final = 1.25
    _DECAY: Final = 0.90
    _SLACK: Final = 0.95

    def __init__(self, options: EncodeOptions) -> None:
        self._budget = options.tile_budget
        self._base = options.tolerance
        self._max_scale = options.max_tolerance_scale
        self._scale = 1.0
        self._previous_tiles = 0
        self._rate = 0.0

    def tolerance(self, tiles_used: int, index: int, total_frames: int) -> float:
        """The error budget for this frame."""
        if self._budget <= 0 or total_frames <= 0:
            return self._base
        added = tiles_used - self._previous_tiles
        self._previous_tiles = tiles_used
        self._rate += (added - self._rate) * self._SMOOTHING

        remaining_frames = total_frames - index
        remaining_budget = self._budget - tiles_used
        if remaining_frames <= 0:
            return self._base * self._scale
        affordable = max(0.0, remaining_budget) / remaining_frames

        if affordable <= 0.0:
            self._scale = self._max_scale
        elif self._rate > affordable:
            ramp = min(self._rate / affordable, self._RAMP_LIMIT)
            self._scale = min(self._max_scale, self._scale * ramp)
        elif self._rate < affordable * self._SLACK:
            self._scale = max(1.0, self._scale * self._DECAY)
        return self._base * self._scale


def _new_dictionary(options: EncodeOptions) -> TileDictionary:
    """The dictionary this encode may fill, capped by any tile budget.

    Capping here rather than in the controller is what makes the budget
    a guarantee: no threshold can be raised high enough to slow some
    content down, but a dictionary that refuses to grow always holds.
    """
    capacity = options.dictionary_capacity
    if options.tile_budget > 0:
        capacity = min(capacity, options.tile_budget)
    return TileDictionary(allow_flip=options.allow_flip, capacity=capacity)


def _is_scene_cut(
    current: npt.NDArray[np.uint16],
    previous: npt.NDArray[np.uint16] | None,
    changed: npt.NDArray[np.bool_],
    index: int,
    options: EncodeOptions,
) -> bool:
    """Whether the picture jumped rather than moved.

    A cut earns a keyframe because a delta could not be cheaper when
    nearly every slot has to be rewritten anyway. Deciding that on the
    count of slots that differ at all does not work on photographed
    material: grain, dither, and any gentle camera move perturb almost
    every slot by a shade every frame, so a plain count reads a still
    scene as a cut. Measured on real footage that fired on 22% of all
    frames, and each false cut rewrote all 280 slots and interned the
    tiles a delta would have skipped.

    Magnitude separates the two cases cleanly. A slot counts toward a
    cut only once the source moved further than `scene_cut_floor`, which
    leaves gradual motion to the delta path where it belongs.
    """
    if index == 0 or previous is None:
        return True
    if not changed.any():
        return False
    moved = _movement(current, previous, changed, options.chroma_weight)
    jumped = float((moved > options.scene_cut_floor).sum()) / float(changed.size)
    return jumped >= options.scene_cut_ratio


def _select_targets(
    current: npt.NDArray[np.uint16],
    previous: npt.NDArray[np.uint16] | None,
    changed: npt.NDArray[np.bool_],
    pending: npt.NDArray[np.bool_],
    *,
    screen: _Screen,
    keyframe: bool,
    options: EncodeOptions,
    tolerance: float,
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    """Which slots to redraw this frame, and which stay owed a redraw.

    A keyframe takes every slot and clears the backlog, which is what
    makes it a seek target. Otherwise a slot is a candidate when its
    source changed or when an earlier frame skipped it, and it is only
    redrawn when the picture on screen has drifted past the budget.

    A skipped slot stays pending rather than being forgotten, so an
    error the encoder chose to tolerate is re-tested on every later
    frame and repaired as soon as it stops being cheap to hide.
    """
    if keyframe:
        return (
            np.ones((GRID_ROWS, GRID_COLS), dtype=bool),
            np.zeros((GRID_ROWS, GRID_COLS), dtype=bool),
        )
    targets = changed | pending
    if tolerance <= 0.0 or not targets.any():
        return targets, np.zeros_like(targets)
    threshold = _masked_threshold(current, previous, targets, options, tolerance)
    keep = np.zeros_like(targets)
    keep[targets] = screen.drift(current, targets) > threshold
    return keep, targets & ~keep


def _tile_frames(
    chunks: Iterable[npt.NDArray[np.uint8]],
) -> Iterator[npt.NDArray[np.uint16]]:
    """Yield one frame's tile grid at a time from chunks of RGB frames."""
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
    """Running counters the encode loop accumulates across frames."""

    keyframe_bytes: int = 0
    delta_bytes: int = 0
    error_total: float = 0.0
    error_pixels: int = 0
    displayed_error_total: float = 0.0
    displayed_frames: int = 0
    peak_tolerance: float = 0.0

    def track_tolerance(self, tolerance: float) -> float:
        """Record the highest budget the controller had to reach."""
        self.peak_tolerance = max(self.peak_tolerance, tolerance)
        return tolerance


def _build_stats(
    *,
    movie: stream.MovieStream,
    dictionary: TileDictionary,
    updates_per_frame: npt.NDArray[np.int32],
    totals: _Totals,
    budget: int,
) -> EncodeStats:
    tile_count = len(dictionary)
    return EncodeStats(
        frames=len(movie),
        tile_count=tile_count,
        dictionary_full=dictionary.is_full(),
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
        mean_error=(totals.error_total / totals.error_pixels) if totals.error_pixels else 0.0,
        displayed_error=(
            (totals.displayed_error_total / totals.displayed_frames)
            if totals.displayed_frames
            else 0.0
        ),
        peak_tolerance=totals.peak_tolerance,
        budget_exceeded=bool(budget > 0 and tile_count >= budget),
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
        grid = palettes.oklab_grid(self._palette_set.chroma_weight)
        source_lab = grid[source[targets]]
        screen_lab = grid[self.render[targets]]
        return ((source_lab - screen_lab) ** 2).sum(axis=3).mean(axis=(1, 2))

    def retarget(self, palette_set: palettes.PaletteSet) -> None:
        """Point the model at a new epoch's colours.

        What is on screen does not change, so the model of it must not
        either. Only the palettes that later assignments are measured
        against move.
        """
        self._palette_set = palette_set

    def fidelity(self, source: npt.NDArray[np.uint16]) -> float:
        """Mean squared Oklab error of the whole displayed frame.

        Deliberately measured on the unweighted grid over every slot,
        including the ones the encoder chose not to redraw. `mean_error`
        averages the palette error of tiles that were written, so it
        improves when the encoder skips more work, which makes it
        useless for judging output quality. This is the number that
        answers whether the picture on screen still matches the source,
        and no encoder knob can flatter it.

        The comparison is against the true source frame for this refresh,
        never the frame the encoder chose to hold. Holding a frame across
        four refreshes is a real error the viewer sees, so measuring
        against the held copy would score a cheat as free.
        """
        grid = palettes.oklab_grid(palettes.DEFAULT_CHROMA_WEIGHT)
        error: float = float(((grid[source] - grid[self.render]) ** 2).sum(axis=4).mean())
        return error

    def commit(
        self,
        rows: npt.NDArray[np.int64],
        cols: npt.NDArray[np.int64],
        refs: list[TileRef | None],
        assignment: palettes.Assignment,
        *,
        force: bool,
    ) -> list[stream.SlotUpdate]:
        """Write the chosen tiles into the model and list what must be sent."""
        display = assignment.rendered(self._palette_set)
        updates: list[stream.SlotUpdate] = []
        for slot, (row, col) in enumerate(zip(rows, cols, strict=True)):
            ref = refs[slot]
            if ref is None:
                continue
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
    """Encode a whole in-memory clip. Convenience wrapper over `encode_stream`."""
    _validate(clip)
    sample = to_tiles(neocolor.rgb_to_color_index(clip[:: max(1, options.sample_stride)]))
    return encode_stream(
        [clip],
        options,
        sample_tiles=sample.reshape(-1, TILE_PX, TILE_PX),
        total_frames=clip.shape[0],
    )


def _build_palette_sets(
    options: EncodeOptions,
    sample_tiles: npt.NDArray[np.uint16],
    epoch_samples: Sequence[tuple[int, npt.NDArray[np.uint16]]] | None,
) -> tuple[list[int], list[palettes.PaletteSet]]:
    """One palette set per epoch, alternating between the two CRAM halves.

    Colours refitted per scene score around a tenth better than a single
    set stretched over a whole feature, but the new set has to reach CRAM
    before the scene it belongs to appears. Alternating halves buys that
    time: the next epoch is written into the half nobody is reading while
    the current one is still on screen.
    """
    if not epoch_samples:
        return [0], [
            palettes.build_palette_set(
                sample_tiles,
                count=options.palette_count,
                base_bank=options.base_bank,
                seed=options.seed,
                chroma_weight=options.chroma_weight,
            )
        ]

    half = options.palette_count // 2
    starts: list[int] = []
    sets: list[palettes.PaletteSet] = []
    for epoch, (start, tiles) in enumerate(epoch_samples):
        starts.append(start)
        sets.append(
            palettes.build_palette_set(
                tiles,
                count=half,
                base_bank=options.base_bank + (epoch % 2) * half,
                seed=options.seed + epoch,
                chroma_weight=options.chroma_weight,
            )
        )
    return starts, sets


def _enter_epoch(
    palette_set: palettes.PaletteSet,
    epoch: int,
    screen: _Screen,
    dictionary: TileDictionary,
    options: EncodeOptions,
) -> palettes.PaletteAssigner:
    """Move the encoder onto a new epoch's colours."""
    screen.retarget(palette_set)
    dictionary.reseed(epoch)
    return palettes.PaletteAssigner(palette_set, candidates=options.candidates)


def _record_frame(
    screen: _Screen,
    incoming: npt.NDArray[np.uint16],
    index: int,
    rendered: npt.NDArray[np.uint16],
    *,
    totals: _Totals,
    options: EncodeOptions,
    on_render: Callable[[npt.NDArray[np.uint16]], None] | None,
) -> None:
    """Score this frame and hand the picture to whoever wants it."""
    totals.displayed_error_total += screen.fidelity(incoming)
    totals.displayed_frames += 1
    if options.collect_rendered:
        rendered[index] = from_tiles(screen.render)
    if on_render is not None:
        on_render(from_tiles(screen.render))


def encode_stream(
    chunks: Iterable[npt.NDArray[np.uint8]],
    options: EncodeOptions,
    *,
    sample_tiles: npt.NDArray[np.uint16],
    total_frames: int,
    epoch_samples: Sequence[tuple[int, npt.NDArray[np.uint16]]] | None = None,
    on_render: Callable[[npt.NDArray[np.uint16]], None] | None = None,
) -> EncodeResult:
    """Encode frames as they arrive, holding only two frames at a time.

    A cart filled to the character-ROM ceiling is around 15,600 frames.
    Neither the source nor the rendered output fits in memory at that
    length, so the palette set is fitted from a strided sample taken in
    an earlier pass and the frames themselves stream past.
    """
    epoch_starts, palette_sets = _build_palette_sets(options, sample_tiles, epoch_samples)
    epoch = 0
    dictionary = _new_dictionary(options)
    screen = _Screen(palette_sets[0])
    assigner = _enter_epoch(palette_sets[0], 0, screen, dictionary, options)
    movie = stream.MovieStream()

    rendered = (
        np.zeros((total_frames, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint16)
        if options.collect_rendered
        else np.zeros((0, FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint16)
    )
    updates_per_frame = np.zeros(total_frames, dtype=np.int32)
    totals, controller = _Totals(), _RateController(options)
    last_keyframe = -options.keyframe_interval

    previous: npt.NDArray[np.uint16] | None = None
    previous_source: npt.NDArray[np.uint16] | None = None
    pending = np.zeros((GRID_ROWS, GRID_COLS), dtype=bool)
    hold = max(1, options.frame_hold)
    held: npt.NDArray[np.uint16] | None = None
    for index, incoming in enumerate(_tile_frames(chunks)):
        if index % hold == 0:
            held = incoming
        current = held if held is not None else incoming
        changed = (
            np.ones((GRID_ROWS, GRID_COLS), dtype=bool)
            if previous is None
            else (current != previous).any(axis=(2, 3))
        )
        previous_source = previous
        previous = current
        if epoch + 1 < len(epoch_starts) and index >= epoch_starts[epoch + 1]:
            epoch += 1
            assigner = _enter_epoch(palette_sets[epoch], epoch, screen, dictionary, options)
        scene_cut = _is_scene_cut(current, previous_source, changed, index, options) or (
            index in epoch_starts and index > 0
        )
        keyframe = scene_cut or (index - last_keyframe >= options.keyframe_interval)

        if keyframe:
            last_keyframe = index
        tolerance = totals.track_tolerance(
            controller.tolerance(len(dictionary), index, total_frames)
        )
        targets, pending = _select_targets(
            current,
            previous_source,
            changed,
            pending,
            screen=screen,
            keyframe=keyframe,
            options=options,
            tolerance=tolerance,
        )

        updates: list[stream.SlotUpdate] = []
        if targets.any():
            rows, cols = np.nonzero(targets)
            assignment = assigner.assign(current[rows, cols])
            totals.error_total += float(assignment.error.sum())
            totals.error_pixels += assignment.error.size * TILE_PX * TILE_PX
            refs = dictionary.intern_batch(assignment.nibbles)
            updates = screen.commit(rows, cols, refs, assignment, force=keyframe)

        before = movie.payload_size()
        movie.append(updates, keyframe=keyframe)
        written = movie.payload_size() - before
        if keyframe:
            totals.keyframe_bytes += written
        else:
            totals.delta_bytes += written

        updates_per_frame[index] = len(updates)
        _record_frame(
            screen,
            incoming,
            index,
            rendered,
            totals=totals,
            options=options,
            on_render=on_render,
        )

    stats = _build_stats(
        movie=movie,
        dictionary=dictionary,
        updates_per_frame=updates_per_frame,
        totals=totals,
        budget=options.tile_budget,
    )

    return EncodeResult(
        stream=movie,
        dictionary=dictionary,
        palette_set=palette_sets[0],
        palette_sets=palette_sets,
        updates_per_frame=updates_per_frame,
        rendered=rendered,
        stats=stats,
    )
