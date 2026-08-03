"""Global tile dictionary with mirror deduplication.

Every distinct 16x16 pattern the movie needs is stored once and
addressed by a 20-bit tile number. The LSPC applies horizontal and
vertical flip per tile from the SCB1 attribute word, so a pattern and
its three mirrors share one C-ROM entry. Registering all four
orientations of a new tile at insert time makes every later lookup a
single dictionary hit.

The dictionary key is the palette-index pattern alone, not the pattern
plus its palette. The palette lives in the attribute word, so two slots
showing the same shape under different palettes cost one tile between
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

TILE_PX: Final = 16
MAX_TILES: Final = 1 << 20


@dataclass(frozen=True, slots=True)
class TileRef:
    index: int
    hflip: bool
    vflip: bool


class TileDictionary:
    """Interns 16x16 nibble tiles, collapsing mirrored duplicates."""

    def __init__(self, *, allow_flip: bool = True) -> None:
        self._allow_flip = allow_flip
        self._entries: list[npt.NDArray[np.uint8] | None] = []
        self._lookup: dict[bytes, TileRef] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def tiles(self) -> npt.NDArray[np.uint8]:
        """The stored patterns in tile-number order."""
        if not self._entries:
            return np.zeros((0, TILE_PX, TILE_PX), dtype=np.uint8)
        return np.stack([entry for entry in self._entries if entry is not None])

    def intern(self, tile: npt.NDArray[np.uint8]) -> TileRef:
        """Return the reference for a pattern, adding it when new."""
        if tile.shape != (TILE_PX, TILE_PX):
            msg = f"tile must be 16x16, got shape {tile.shape}"
            raise ValueError(msg)
        if tile.size and int(tile.max()) > 0x0F:
            msg = "tile pixels must be 4-bit palette indices in the range 0 to 15"
            raise ValueError(msg)

        tile = np.ascontiguousarray(tile, dtype=np.uint8)
        key = tile.tobytes()
        existing = self._lookup.get(key)
        if existing is not None:
            return existing

        index = len(self._entries)
        if index >= MAX_TILES:
            msg = f"dictionary exceeds the 20-bit tile number limit of {MAX_TILES} tiles"
            raise ValueError(msg)

        self._entries.append(tile)
        ref = TileRef(index=index, hflip=False, vflip=False)
        self._lookup[key] = ref
        if self._allow_flip:
            self._register_mirrors(tile, index)
        return ref

    def intern_batch(self, tiles: npt.NDArray[np.uint8]) -> list[TileRef]:
        """Intern a batch of patterns in order."""
        return [self.intern(tiles[i]) for i in range(tiles.shape[0])]

    def _register_mirrors(self, tile: npt.NDArray[np.uint8], index: int) -> None:
        variants = (
            (tile[:, ::-1], True, False),
            (tile[::-1, :], False, True),
            (tile[::-1, ::-1], True, True),
        )
        for variant, hflip, vflip in variants:
            key = np.ascontiguousarray(variant).tobytes()
            if key not in self._lookup:
                self._lookup[key] = TileRef(index=index, hflip=hflip, vflip=vflip)
