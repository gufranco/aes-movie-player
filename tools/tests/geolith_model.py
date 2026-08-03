"""A model of the parts of the LSPC this project drives.

Both classes are independent transcriptions of geolith's
`src/geo_lspc.c`, not calls into the baker. `GeolithTileReader` mirrors
`geo_lspc_tpix` and the sprite pixel loop, including the flip handling.
`StreamPlayer` mirrors the VRAM write port plus the SCB1 decode at
`geo_lspc_sprcalc`, so replaying a baked stream through it reconstructs
the picture the emulator would put on screen.
"""

from __future__ import annotations

import struct
from typing import Final

import numpy as np

TILE_BYTES: Final = 128
VRAM_WORDS: Final = 0x8000
SCB1_WORDS_PER_SPRITE: Final = 64
GRID_COLS: Final = 20
GRID_ROWS: Final = 14
TILE_PX: Final = 16


class GeolithTileReader:
    def __init__(self, c1: np.ndarray | bytes, c2: np.ndarray | bytes) -> None:
        left = np.frombuffer(c1, dtype=np.uint8) if isinstance(c1, bytes) else c1.reshape(-1)
        right = np.frombuffer(c2, dtype=np.uint8) if isinstance(c2, bytes) else c2.reshape(-1)
        interleaved = np.empty(left.size + right.size, dtype=np.uint8)
        interleaved[0::2] = left
        interleaved[1::2] = right
        self._rom = interleaved

    def pixel(self, tile: int, x: int, y: int, *, hflip: bool = False, vflip: bool = False) -> int:
        row = (0x0F - y) if vflip else y
        ftile = 0x00 if hflip else 0x08
        fpix = 0x07 if hflip else 0x00
        base = tile * TILE_BYTES + (((0x08 & x) ^ ftile) << 3) + (row << 2)
        bit = (x & 0x07) ^ fpix
        v0 = (self._rom[base + 0] >> bit) & 1
        v1 = (self._rom[base + 2] >> bit) & 1
        v2 = (self._rom[base + 1] >> bit) & 1
        v3 = (self._rom[base + 3] >> bit) & 1
        return int(v0 | (v1 << 1) | (v2 << 2) | (v3 << 3))

    def tile(self, index: int, *, hflip: bool = False, vflip: bool = False) -> np.ndarray:
        return np.array(
            [
                [self.pixel(index, x, y, hflip=hflip, vflip=vflip) for x in range(TILE_PX)]
                for y in range(TILE_PX)
            ],
            dtype=np.uint8,
        )


class StreamPlayer:
    """Applies baked frame records to a VRAM model and reads back the grid."""

    def __init__(self) -> None:
        self.vram = np.zeros(VRAM_WORDS, dtype=np.uint16)

    def apply(self, blob: bytes, offset: int) -> int:
        run_count = struct.unpack_from(">H", blob, offset)[0]
        cursor = offset + 2
        for _ in range(run_count):
            address, tiles = struct.unpack_from(">HH", blob, cursor)
            cursor += 4
            for step in range(tiles):
                tile_lo, attr = struct.unpack_from(">HH", blob, cursor)
                cursor += 4
                self.vram[address + step * 2] = tile_lo
                self.vram[address + step * 2 + 1] = attr
        return cursor

    def slot(self, col: int, row: int) -> tuple[int, int, bool, bool]:
        address = (col + 1) * SCB1_WORDS_PER_SPRITE + row * 2
        tile_lo = int(self.vram[address])
        attr = int(self.vram[address + 1])
        tile = tile_lo | ((attr & 0x00F0) << 12)
        palette = (attr >> 8) & 0xFF
        return tile, palette, bool(attr & 0x01), bool(attr & 0x02)

    def render(
        self, reader: GeolithTileReader, palette_colors: np.ndarray, base_bank: int
    ) -> np.ndarray:
        frame = np.zeros((GRID_ROWS * TILE_PX, GRID_COLS * TILE_PX), dtype=np.uint16)
        for col in range(GRID_COLS):
            for row in range(GRID_ROWS):
                tile, palette, hflip, vflip = self.slot(col, row)
                nibbles = reader.tile(tile, hflip=hflip, vflip=vflip)
                colors = palette_colors[palette - base_bank][nibbles - 1]
                frame[row * TILE_PX : (row + 1) * TILE_PX, col * TILE_PX : (col + 1) * TILE_PX] = (
                    colors
                )
        return frame
