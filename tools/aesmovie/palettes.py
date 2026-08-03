"""Per-tile palette clustering and assignment.

The LSPC gives each 16x16 tile one CRAM bank of 16 entries, and entry 0
is transparent, so a tile is quantized to 15 colors chosen from a bank.
With 256 banks and 16 reserved for the fix layer, the video draws from
240 banks, or 3600 simultaneous colors, and the encoder's job is to pick
banks that let every tile in the movie land close to its source colors.

The approach follows the tiled-palette-quantizer family cited in
`references.md`: describe each tile compactly, cluster tiles into as many
groups as there are banks, fit a palette per group, then assign every
tile to whichever bank quantizes it best. Clustering uses a nine
dimensional descriptor, the Oklab mean plus the darkest and brightest
pixel, because tiles that agree on those three points almost always
share a palette well.

Palette entries are chosen from colors that actually occur in the
source rather than from arbitrary grid points, the same choice
`median_cut_select` makes in the DoomNG `palette.py`, so a palette never
spends a slot on a color the content does not contain.

Distance is squared Oklab throughout, matching `oklab_distance_sq` in
the DoomNG `palette.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

from aesmovie import neocolor

TILE_PX: Final = 16
TILE_PIXELS: Final = TILE_PX * TILE_PX
PALETTE_SLOTS: Final = neocolor.PALETTE_USABLE_COLORS
CRAM_BANKS: Final = 256
DESCRIPTOR_DIMS: Final = 9
_KMEANS_ITERATIONS: Final = 24
_ASSIGN_CHUNK_BYTES: Final = 64 << 20

DEFAULT_CHROMA_WEIGHT: Final = 1.0

_OKLAB_GRIDS: dict[float, npt.NDArray[np.float32]] = {}


def oklab_grid(chroma_weight: float = DEFAULT_CHROMA_WEIGHT) -> npt.NDArray[np.float32]:
    """Color index to Oklab, with the chroma axes optionally scaled down.

    Vision resolves luminance far more finely than colour, which is why
    every broadcast and consumer codec since the 1950s has spent fewer
    bits on chroma than on luma. Angel Studios leaned on exactly this to
    fit Resident Evil 2's video into 24 MiB, quartering the horizontal
    chroma resolution outright.

    There is no separate chroma plane to subsample here, because a tile
    is a palette index and not a Y/Cb/Cr triple. The equivalent lever is
    the distance metric every stage already shares: scaling the `a` and
    `b` axes by the square root of the weight makes a squared distance
    charge chroma error at `chroma_weight` times the rate of luma error.
    Palette fitting, palette assignment, redraw decisions, and motion
    masking all measure distance through this table, so weighting it
    here moves the whole encoder onto a luma-first metric at once.

    A weight of one reproduces unweighted Oklab.
    """
    if chroma_weight <= 0.0:
        msg = f"chroma weight must be positive, got {chroma_weight}"
        raise ValueError(msg)
    cached = _OKLAB_GRIDS.get(chroma_weight)
    if cached is None:
        grid = neocolor.build_oklab_grid()
        if chroma_weight != 1.0:
            grid = grid * np.array(
                [1.0, np.sqrt(chroma_weight), np.sqrt(chroma_weight)], dtype=np.float32
            )
        cached = grid.astype(np.float32)
        _OKLAB_GRIDS[chroma_weight] = cached
    return cached


@dataclass(frozen=True, slots=True)
class PaletteSet:
    colors: npt.NDArray[np.uint16]
    base_bank: int
    descriptors: npt.NDArray[np.float32] | None = None
    chroma_weight: float = DEFAULT_CHROMA_WEIGHT

    def __post_init__(self) -> None:
        if self.colors.ndim != 2 or self.colors.shape[1] != PALETTE_SLOTS:
            msg = f"palette table must be (count, {PALETTE_SLOTS}), got {self.colors.shape}"
            raise ValueError(msg)
        if self.base_bank + self.colors.shape[0] > CRAM_BANKS:
            msg = (
                f"{self.colors.shape[0]} palettes at base bank {self.base_bank} "
                f"overflow the {CRAM_BANKS} CRAM banks"
            )
            raise ValueError(msg)

    def __len__(self) -> int:
        return int(self.colors.shape[0])

    def bank_of(self, palette_id: int) -> int:
        """CRAM bank holding a palette."""
        return self.base_bank + palette_id

    def cram_blob(self) -> bytes:
        """CRAM words for every palette, transparent slot first."""
        words = np.zeros((len(self), neocolor.PALETTE_COLORS), dtype=">u2")
        words[:, 1:] = neocolor.color_index_to_palette_word(self.colors).astype(">u2")
        return words.tobytes()


@dataclass(frozen=True, slots=True)
class Assignment:
    palette_ids: npt.NDArray[np.uint8]
    nibbles: npt.NDArray[np.uint8]
    error: npt.NDArray[np.float32]

    def rendered(self, palette_set: PaletteSet) -> npt.NDArray[np.uint16]:
        """Color indices the hardware will actually display."""
        if self.palette_ids.size == 0:
            return np.zeros((0, TILE_PX, TILE_PX), dtype=np.uint16)
        return palette_set.colors[self.palette_ids[:, None, None], self.nibbles - 1]


def _sqdist(
    points: npt.NDArray[np.float32], centres: npt.NDArray[np.float32]
) -> npt.NDArray[np.float32]:
    """Pairwise squared distance without materializing the difference tensor.

    The expanded form keeps memory at one value per pair instead of one
    per pair per dimension, which matters because a feature-length bake
    ranks hundreds of thousands of tiles against 240 palettes.
    """
    gram = points @ centres.T
    distance: npt.NDArray[np.float32] = (
        (points * points).sum(axis=1)[:, None]
        - 2.0 * gram
        + (centres * centres).sum(axis=1)[None, :]
    ).astype(np.float32)
    return distance


def _tile_descriptors(
    tiles: npt.NDArray[np.uint16], chroma_weight: float = DEFAULT_CHROMA_WEIGHT
) -> npt.NDArray[np.float32]:
    grid = oklab_grid(chroma_weight)
    lab = grid[tiles.reshape(tiles.shape[0], TILE_PIXELS)]
    lightness = lab[:, :, 0]
    darkest = lab[np.arange(lab.shape[0]), np.argmin(lightness, axis=1)]
    brightest = lab[np.arange(lab.shape[0]), np.argmax(lightness, axis=1)]
    return np.concatenate([lab.mean(axis=1), darkest, brightest], axis=1).astype(np.float32)


def _kmeans(
    points: npt.NDArray[np.float32], count: int, seed: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float32]]:
    rng = np.random.default_rng(seed)
    unique = np.unique(points, axis=0)
    if unique.shape[0] <= count:
        centroids = np.concatenate(
            [unique, unique[rng.integers(0, unique.shape[0], count - unique.shape[0])]]
        ).astype(np.float32)
    else:
        centroids = unique[rng.choice(unique.shape[0], count, replace=False)].astype(np.float32)

    labels = np.zeros(points.shape[0], dtype=np.int64)
    for _ in range(_KMEANS_ITERATIONS):
        labels = np.argmin(_sqdist(points, centroids), axis=1)
        moved = False
        for index in range(count):
            members = points[labels == index]
            if members.shape[0] == 0:
                continue
            mean = members.mean(axis=0).astype(np.float32)
            if not np.allclose(mean, centroids[index]):
                centroids[index] = mean
                moved = True
        if not moved:
            break
    return labels, centroids


def _fit_palette(
    colors: npt.NDArray[np.uint16],
    counts: npt.NDArray[np.int64],
    seed: int,
    chroma_weight: float = DEFAULT_CHROMA_WEIGHT,
) -> npt.NDArray[np.uint16]:
    grid = oklab_grid(chroma_weight)
    if colors.shape[0] <= PALETTE_SLOTS:
        padded = np.resize(colors, PALETTE_SLOTS)
        return padded.astype(np.uint16)

    lab = grid[colors]
    weight = counts.astype(np.float64)
    rng = np.random.default_rng(seed)
    order = np.argsort(-weight)
    centroids = lab[order[:PALETTE_SLOTS]].astype(np.float32)

    for _ in range(_KMEANS_ITERATIONS):
        labels = np.argmin(_sqdist(lab, centroids), axis=1)
        moved = False
        for index in range(PALETTE_SLOTS):
            mask = labels == index
            if not mask.any():
                centroids[index] = lab[rng.integers(0, lab.shape[0])]
                moved = True
                continue
            total = weight[mask].sum()
            mean = (lab[mask] * weight[mask, None]).sum(axis=0) / total
            if not np.allclose(mean, centroids[index]):
                centroids[index] = mean.astype(np.float32)
                moved = True
        if not moved:
            break

    chosen = colors[np.argmin(_sqdist(lab, centroids), axis=0)]
    return chosen.astype(np.uint16)


def build_palette_set(
    tiles: npt.NDArray[np.uint16],
    *,
    count: int,
    base_bank: int,
    seed: int,
    chroma_weight: float = DEFAULT_CHROMA_WEIGHT,
) -> PaletteSet:
    """Cluster a sample of tiles and fit one palette per cluster."""
    if tiles.shape[0] == 0:
        msg = "cannot build a palette set from an empty tile batch"
        raise ValueError(msg)
    if base_bank + count > CRAM_BANKS:
        msg = f"{count} palettes at base bank {base_bank} overflow the {CRAM_BANKS} CRAM banks"
        raise ValueError(msg)

    descriptors = _tile_descriptors(tiles, chroma_weight)
    labels, centroids = _kmeans(descriptors, count, seed)

    flat = tiles.reshape(tiles.shape[0], TILE_PIXELS)
    palettes = np.zeros((count, PALETTE_SLOTS), dtype=np.uint16)
    for index in range(count):
        members = flat[labels == index]
        if members.size == 0:
            members = flat
        colors, counts = np.unique(members.reshape(-1), return_counts=True)
        palettes[index] = _fit_palette(colors, counts, seed + index, chroma_weight)

    return PaletteSet(
        colors=palettes,
        base_bank=base_bank,
        descriptors=centroids,
        chroma_weight=chroma_weight,
    )


class PaletteAssigner:
    """Picks the best palette for each tile and emits its pixel indices."""

    def __init__(self, palette_set: PaletteSet, *, candidates: int = 0) -> None:
        self._palette_set = palette_set
        self._candidates = min(candidates if candidates > 0 else len(palette_set), len(palette_set))
        grid = oklab_grid(palette_set.chroma_weight)
        total = len(palette_set)
        self._slot = np.zeros((total, grid.shape[0]), dtype=np.uint8)
        self._error = np.zeros((total, grid.shape[0]), dtype=np.float32)
        for index in range(total):
            palette_lab = grid[palette_set.colors[index]]
            distance = ((grid[:, None, :] - palette_lab[None, :, :]) ** 2).sum(axis=2)
            self._slot[index] = np.argmin(distance, axis=1).astype(np.uint8)
            self._error[index] = np.min(distance, axis=1).astype(np.float32)
        self._chunk = max(1, _ASSIGN_CHUNK_BYTES // (self._candidates * TILE_PIXELS * 4))

    def assign(self, tiles: npt.NDArray[np.uint16]) -> Assignment:
        """Choose a palette per tile and quantize its pixels."""
        count = tiles.shape[0]
        if count == 0:
            return Assignment(
                palette_ids=np.zeros(0, dtype=np.uint8),
                nibbles=np.zeros((0, TILE_PX, TILE_PX), dtype=np.uint8),
                error=np.zeros(0, dtype=np.float32),
            )

        flat = tiles.reshape(count, TILE_PIXELS)
        palette_ids = np.zeros(count, dtype=np.uint8)
        best_error = np.zeros(count, dtype=np.float32)
        nibbles = np.zeros((count, TILE_PIXELS), dtype=np.uint8)

        shortlist = self._shortlist(tiles)
        for start in range(0, count, self._chunk):
            stop = min(start + self._chunk, count)
            pixels = flat[start:stop]
            picks = shortlist[start:stop]
            errors = self._error[picks[:, :, None], pixels[:, None, :]].sum(axis=2)
            winner = np.argmin(errors, axis=1)
            rows = np.arange(stop - start)
            chosen = picks[rows, winner]
            palette_ids[start:stop] = chosen.astype(np.uint8)
            best_error[start:stop] = errors[rows, winner]
            nibbles[start:stop] = self._slot[chosen[:, None], pixels] + 1

        return Assignment(
            palette_ids=palette_ids,
            nibbles=nibbles.reshape(count, TILE_PX, TILE_PX),
            error=best_error,
        )

    def _shortlist(self, tiles: npt.NDArray[np.uint16]) -> npt.NDArray[np.int64]:
        total = len(self._palette_set)
        if self._candidates >= total or self._palette_set.descriptors is None:
            return np.tile(np.arange(total), (tiles.shape[0], 1))
        descriptors = _tile_descriptors(tiles)
        centroids = self._palette_set.descriptors
        distance = _sqdist(descriptors, centroids)
        return np.argpartition(distance, self._candidates - 1, axis=1)[:, : self._candidates]
