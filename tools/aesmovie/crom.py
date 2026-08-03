"""Pack 16x16 4bpp tiles into Neo Geo C-ROM byte pairs.

Adapted from `pack_bitmap_to_tiles` in the DoomNG
`tools/doomng_build/bake/crom.py`, which packs a whole atlas
column-major. The dictionary here has no spatial layout, so this version
packs one independent tile per entry and vectorizes across the batch,
since a feature-length dictionary runs to hundreds of thousands of
tiles.

The byte layout is the one geolith's `geo_lspc_tpix` reads. A tile is
128 bytes in the interleaved C-ROM, where even bytes come from c1 and
odd bytes from c2. Within a tile, columns 8 to 15 occupy the first 64
bytes and columns 0 to 7 the last 64. Each pixel row is four
interleaved bytes, two from each ROM, holding bitplanes 0 and 1 in c1
and bitplanes 2 and 3 in c2. Bit `n` of a byte is the pixel at column
`n` of the eight-column half, so the leftmost displayed pixel is the
least significant bit.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt

TILE_PX: Final = 16
TILE_BYTES_PER_ROM: Final = 64
TILE_BYTES: Final = TILE_BYTES_PER_ROM * 2
MIN_ROM_BYTES: Final = 1 << 20

_BIT_POSITIONS: Final = np.arange(8, dtype=np.uint8)


def pack_tiles(tiles: npt.NDArray[np.uint8]) -> tuple[npt.NDArray[np.uint8], npt.NDArray[np.uint8]]:
    """Pack a batch of 16x16 nibble tiles into per-ROM byte arrays."""
    if tiles.ndim != 3 or tiles.shape[1:] != (TILE_PX, TILE_PX):
        msg = f"tiles must be a batch of 16x16 arrays, got shape {tiles.shape}"
        raise ValueError(msg)
    if tiles.size and int(tiles.max()) > 0x0F:
        msg = "tile pixels must be 4-bit palette indices in the range 0 to 15"
        raise ValueError(msg)

    count = tiles.shape[0]
    c1 = np.zeros((count, TILE_BYTES_PER_ROM), dtype=np.uint8)
    c2 = np.zeros((count, TILE_BYTES_PER_ROM), dtype=np.uint8)
    if count == 0:
        return c1, c2

    for row in range(TILE_PX):
        for half_offset, columns in ((0, slice(8, 16)), (32, slice(0, 8))):
            block = tiles[:, row, columns].astype(np.uint8)
            byte = half_offset + (row << 1)
            c1[:, byte] = np.bitwise_or.reduce((block & 1) << _BIT_POSITIONS, axis=1)
            c1[:, byte + 1] = np.bitwise_or.reduce(((block >> 1) & 1) << _BIT_POSITIONS, axis=1)
            c2[:, byte] = np.bitwise_or.reduce(((block >> 2) & 1) << _BIT_POSITIONS, axis=1)
            c2[:, byte + 1] = np.bitwise_or.reduce(((block >> 3) & 1) << _BIT_POSITIONS, axis=1)

    return c1, c2


def rom_size_for(tile_count: int) -> int:
    """Per-ROM byte size for a dictionary, rounded to a power of two.

    geolith masks the tile number with a mask derived from the C-ROM
    size and then takes the byte offset modulo that size, so a
    non-power-of-two ROM aliases high tile numbers onto low ones. Padding
    to a power of two makes the mask exact.
    """
    payload = tile_count * TILE_BYTES_PER_ROM
    size = MIN_ROM_BYTES
    while size < payload:
        size <<= 1
    return size


def build_rom_images(
    tiles: npt.NDArray[np.uint8], *, pad_to: int | None = None
) -> tuple[bytes, bytes]:
    """Pack a dictionary and pad both ROM images to their final size."""
    c1, c2 = pack_tiles(tiles)
    target = rom_size_for(tiles.shape[0]) if pad_to is None else pad_to
    payload = tiles.shape[0] * TILE_BYTES_PER_ROM
    if target < payload:
        msg = f"pad_to {target} is smaller than the {payload} byte payload"
        raise ValueError(msg)
    return c1.tobytes().ljust(target, b"\x00"), c2.tobytes().ljust(target, b"\x00")
