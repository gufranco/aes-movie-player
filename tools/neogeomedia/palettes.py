from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from fmvcore import dither as ordered

from neogeomedia import neocolor

TILE_PX: Final = 16
TILE_PIXELS: Final = TILE_PX * TILE_PX
PALETTE_SLOTS: Final = neocolor.PALETTE_USABLE_COLORS
CRAM_BANKS: Final = 256
DESCRIPTOR_DIMS: Final = 9
TABLE_DIMS: Final = 2
_KMEANS_ITERATIONS: Final = 24
_ASSIGN_CHUNK_BYTES: Final = 64 << 20
NO_DITHER: Final = ordered.NO_DITHER
MAX_DITHER: Final = ordered.MAX_DITHER

DEFAULT_CHROMA_WEIGHT: Final = 1.0

_OKLAB_GRIDS: dict[float, npt.NDArray[np.float32]] = {}


def oklab_grid(chroma_weight: float = DEFAULT_CHROMA_WEIGHT) -> npt.NDArray[np.float32]:
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
        if self.colors.ndim != TABLE_DIMS or self.colors.shape[1] != PALETTE_SLOTS:
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
        return self.base_bank + palette_id

    def cram_blob(self) -> bytes:
        words = np.zeros((len(self), neocolor.PALETTE_COLORS), dtype=">u2")
        words[:, 1:] = neocolor.color_index_to_palette_word(self.colors).astype(">u2")
        return words.tobytes()


@dataclass(frozen=True, slots=True)
class Assignment:
    palette_ids: npt.NDArray[np.uint8]
    nibbles: npt.NDArray[np.uint8]
    error: npt.NDArray[np.float32]

    def rendered(self, palette_set: PaletteSet) -> npt.NDArray[np.uint16]:
        if self.palette_ids.size == 0:
            return np.zeros((0, TILE_PX, TILE_PX), dtype=np.uint16)
        return palette_set.colors[self.palette_ids[:, None, None], self.nibbles - 1]


def _sqdist(
    points: npt.NDArray[np.float32], centres: npt.NDArray[np.float32]
) -> npt.NDArray[np.float32]:
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


def _refine(
    lab: npt.NDArray[np.float32],
    weight: npt.NDArray[np.float64],
    centroids: npt.NDArray[np.float32],
    rng: np.random.Generator,
) -> bool:
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
    return moved


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
    centroids = _converged(lab, weight, lab[order[:PALETTE_SLOTS]].astype(np.float32), rng)
    centroids = _migrated(lab, weight, centroids, rng)

    chosen = colors[np.argmin(_sqdist(lab, centroids), axis=0)]
    return chosen.astype(np.uint16)


def _converged(
    lab: npt.NDArray[np.float32],
    weight: npt.NDArray[np.float64],
    centroids: npt.NDArray[np.float32],
    rng: np.random.Generator,
) -> npt.NDArray[np.float32]:
    moving = centroids.copy()
    for _ in range(_KMEANS_ITERATIONS):
        if not _refine(lab, weight, moving, rng):
            break
    return moving


MIGRATION_ROUNDS: Final = 10
MIGRATION_FACTOR: Final = 0.5


def _cluster_costs(
    lab: npt.NDArray[np.float32],
    weight: npt.NDArray[np.float64],
    centroids: npt.NDArray[np.float32],
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], npt.NDArray[np.float64], float]:
    distance = _sqdist(lab, centroids).astype(np.float64)
    nearest = np.argmin(distance, axis=1)
    near = distance[np.arange(lab.shape[0]), nearest]
    second = np.partition(distance, 1, axis=1)[:, 1]
    cost = np.bincount(nearest, weights=weight * near, minlength=PALETTE_SLOTS)
    removal = np.bincount(nearest, weights=weight * (second - near), minlength=PALETTE_SLOTS)
    return nearest, cost, removal, float((weight * near).sum())


def _migrated(
    lab: npt.NDArray[np.float32],
    weight: npt.NDArray[np.float64],
    centroids: npt.NDArray[np.float32],
    rng: np.random.Generator,
) -> npt.NDArray[np.float32]:
    best = centroids
    for _ in range(MIGRATION_ROUNDS):
        nearest, cost, removal, total = _cluster_costs(lab, weight, best)
        worst, weakest = int(np.argmax(cost)), int(np.argmin(removal))
        if worst == weakest or removal[weakest] >= MIGRATION_FACTOR * cost[worst]:
            break
        members = np.flatnonzero(nearest == worst)
        spread = weight[members] * ((lab[members] - best[worst]) ** 2).sum(axis=1)
        trial = best.copy()
        trial[weakest] = lab[members[int(np.argmax(spread))]]
        trial = _converged(lab, weight, trial, rng)
        if _cluster_costs(lab, weight, trial)[3] >= total:
            break
        best = trial
    return best


def _cluster_palettes(
    flat: npt.NDArray[np.uint16],
    labels: npt.NDArray[np.int64],
    count: int,
    seed: int,
    chroma_weight: float,
) -> npt.NDArray[np.uint16]:
    palettes = np.zeros((count, PALETTE_SLOTS), dtype=np.uint16)
    for index in range(count):
        members = flat[labels == index]
        if members.size == 0:
            members = flat
        colors, counts = np.unique(members.reshape(-1), return_counts=True)
        palettes[index] = _fit_palette(colors, counts, seed + index, chroma_weight)
    return palettes


def build_palette_set(
    tiles: npt.NDArray[np.uint16],
    *,
    count: int,
    base_bank: int,
    seed: int,
    chroma_weight: float = DEFAULT_CHROMA_WEIGHT,
) -> PaletteSet:
    if tiles.shape[0] == 0:
        msg = "cannot build a palette set from an empty tile batch"
        raise ValueError(msg)
    if base_bank + count > CRAM_BANKS:
        msg = f"{count} palettes at base bank {base_bank} overflow the {CRAM_BANKS} CRAM banks"
        raise ValueError(msg)

    descriptors = _tile_descriptors(tiles, chroma_weight)
    labels, centroids = _kmeans(descriptors, count, seed)

    flat = tiles.reshape(tiles.shape[0], TILE_PIXELS)
    return PaletteSet(
        colors=_cluster_palettes(flat, labels, count, seed, chroma_weight),
        base_bank=base_bank,
        descriptors=centroids,
        chroma_weight=chroma_weight,
    )


class PaletteAssigner:
    def __init__(
        self, palette_set: PaletteSet, *, candidates: int = 0, dither: float = NO_DITHER
    ) -> None:
        ordered.check_strength(dither)
        self._palette_set = palette_set
        self._candidates = min(candidates if candidates > 0 else len(palette_set), len(palette_set))
        grid = oklab_grid(palette_set.chroma_weight)
        total = len(palette_set)
        self._slot = np.zeros((total, grid.shape[0]), dtype=np.uint8)
        self._error = np.zeros((total, grid.shape[0]), dtype=np.float32)
        picks = (total, grid.shape[0], ordered.PATTERN_CANDIDATES)
        self._pattern = np.zeros(picks, dtype=np.uint8) if dither > NO_DITHER else None
        for index in range(total):
            palette_lab = grid[palette_set.colors[index]]
            distance = ((grid[:, None, :] - palette_lab[None, :, :]) ** 2).sum(axis=2)
            self._slot[index] = np.argmin(distance, axis=1).astype(np.uint8)
            self._error[index] = np.min(distance, axis=1).astype(np.float32)
            if self._pattern is not None:
                self._pattern[index] = ordered.pattern_candidates(
                    grid, palette_lab, strength=dither
                )
        self._threshold = ordered.bayer_thresholds(TILE_PX).reshape(TILE_PIXELS)
        self._chunk = max(1, _ASSIGN_CHUNK_BYTES // (self._candidates * TILE_PIXELS * 4))

    def assign(self, tiles: npt.NDArray[np.uint16]) -> Assignment:
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
            chosen, error, quantised = self._assign_span(flat[start:stop], shortlist[start:stop])
            palette_ids[start:stop] = chosen.astype(np.uint8)
            best_error[start:stop] = error
            nibbles[start:stop] = quantised

        return Assignment(
            palette_ids=palette_ids,
            nibbles=nibbles.reshape(count, TILE_PX, TILE_PX),
            error=best_error,
        )

    def _assign_span(
        self, pixels: npt.NDArray[np.uint16], picks: npt.NDArray[np.int64]
    ) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float32], npt.NDArray[np.uint8]]:
        errors = self._error[picks[:, :, None], pixels[:, None, :]].sum(axis=2)
        winner = np.argmin(errors, axis=1)
        rows = np.arange(pixels.shape[0])
        chosen = picks[rows, winner]
        return chosen, errors[rows, winner], self._quantise(chosen, pixels) + 1

    def _quantise(
        self, chosen: npt.NDArray[np.int64], pixels: npt.NDArray[np.uint16]
    ) -> npt.NDArray[np.uint8]:
        if self._pattern is None:
            return self._slot[chosen[:, None], pixels]
        candidates = self._pattern[chosen[:, None], pixels]
        return ordered.pattern_pick(candidates, self._threshold[None, :])

    def _shortlist(self, tiles: npt.NDArray[np.uint16]) -> npt.NDArray[np.int64]:
        total = len(self._palette_set)
        if self._candidates >= total or self._palette_set.descriptors is None:
            return np.tile(np.arange(total), (tiles.shape[0], 1))
        descriptors = _tile_descriptors(tiles)
        centroids = self._palette_set.descriptors
        distance = _sqdist(descriptors, centroids)
        return np.argsort(distance, axis=1, kind="stable")[:, : self._candidates]
