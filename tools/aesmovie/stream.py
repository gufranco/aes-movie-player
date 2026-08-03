"""Keyframe and delta command stream for the on-cart player.

The screen is a 20 by 14 grid of 16x16 tiles held by sprites 1 to 20,
one sprite per column, chained with the SCB3 sticky bit. Sprite index 0
is never drawn by the LSPC, so the grid starts at sprite 1. A slot's
SCB1 entry therefore sits at word address `(col + 1) * 64 + row * 2`.

A frame record is a list of runs. A run carries a VRAM word address and
a count, followed by that many tile-number and attribute word pairs. The
player writes the address to REG_VRAMADDR once, sets the auto-increment
modulo to 1, and streams the words straight out of ROM, so a run costs
one register setup regardless of length. Consecutive rows in the same
column merge into one run, which makes a full keyframe exactly twenty
runs.

Every field is a big-endian 16-bit word, matching 68000 byte order, so
the player never byte-swaps.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

GRID_COLS: Final = 20
GRID_ROWS: Final = 14
SLOT_COUNT: Final = GRID_COLS * GRID_ROWS
VRAM_SCB1: Final = 0x0000
SCB1_WORDS_PER_SPRITE: Final = 64
FIRST_SPRITE: Final = 1
MAX_TILE_NUMBER: Final = 1 << 20
MAX_PALETTE: Final = 1 << 8


@dataclass(frozen=True, slots=True)
class SlotUpdate:
    col: int
    row: int
    tile: int
    palette: int
    hflip: bool
    vflip: bool


def vram_address(col: int, row: int) -> int:
    """SCB1 word address of a grid slot's tile entry."""
    if not (0 <= col < GRID_COLS and 0 <= row < GRID_ROWS):
        msg = f"slot ({col}, {row}) falls outside the {GRID_COLS}x{GRID_ROWS} grid"
        raise ValueError(msg)
    return VRAM_SCB1 + (col + FIRST_SPRITE) * SCB1_WORDS_PER_SPRITE + row * 2


def attribute_word(*, palette: int, tile: int, hflip: bool, vflip: bool) -> int:
    """Build the SCB1 odd word for a tile entry."""
    if not 0 <= palette < MAX_PALETTE:
        msg = f"palette {palette} does not fit the 8-bit attribute field"
        raise ValueError(msg)
    if not 0 <= tile < MAX_TILE_NUMBER:
        msg = f"tile {tile} does not fit the 20-bit tile number"
        raise ValueError(msg)
    return (palette << 8) | (((tile >> 16) & 0x0F) << 4) | (int(vflip) << 1) | int(hflip)


def pack_frame(updates: list[SlotUpdate]) -> bytes:
    """Pack one frame's slot updates into a run-coded record."""
    ordered = sorted(updates, key=lambda u: (u.col, u.row))
    seen: set[tuple[int, int]] = set()
    for item in ordered:
        slot = (item.col, item.row)
        if slot in seen:
            msg = f"duplicate update for slot {slot} in one frame"
            raise ValueError(msg)
        seen.add(slot)

    runs: list[list[SlotUpdate]] = []
    for item in ordered:
        if runs:
            last = runs[-1][-1]
            if last.col == item.col and last.row + 1 == item.row:
                runs[-1].append(item)
                continue
        runs.append([item])

    out = bytearray(struct.pack(">H", len(runs)))
    for run in runs:
        head = run[0]
        out += struct.pack(">HH", vram_address(head.col, head.row), len(run))
        for item in run:
            out += struct.pack(
                ">HH",
                item.tile & 0xFFFF,
                attribute_word(
                    palette=item.palette, tile=item.tile, hflip=item.hflip, vflip=item.vflip
                ),
            )
    return bytes(out)


class MovieStream:
    """Accumulates frame records and the seek index that points at them."""

    def __init__(self) -> None:
        self._blob = bytearray()
        self._offsets: list[int] = []
        self._keyframes: list[int] = []

    def __len__(self) -> int:
        return len(self._offsets)

    def append(self, updates: list[SlotUpdate], *, keyframe: bool = False) -> None:
        """Add one frame record to the stream."""
        if keyframe:
            self._keyframes.append(len(self._offsets))
        self._offsets.append(len(self._blob))
        self._blob += pack_frame(updates)

    def blob(self) -> bytes:
        return bytes(self._blob)

    def frame_offsets(self) -> npt.NDArray[np.uint32]:
        return np.array(self._offsets, dtype=np.uint32)

    def keyframes(self) -> npt.NDArray[np.uint32]:
        return np.array(self._keyframes, dtype=np.uint32)

    def index_blob(self) -> bytes:
        return self.frame_offsets().astype(">u4").tobytes()

    def keyframe_blob(self) -> bytes:
        return self.keyframes().astype(">u4").tobytes()
