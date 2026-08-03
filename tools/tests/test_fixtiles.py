"""Fix-layer glyph tests.

`geolith_fix_pixel` transcribes the S-ROM decode in geolith's
`geo_lspc_fixline_default`. A fix tile is 32 bytes holding 8x8 pixels at
four bits each, two pixels per byte with the low nibble on the left, and
the column pairs are stored in the order 0x10, 0x18, 0x00, 0x08. Reading
the packed bytes back through that order proves the glyphs land on
screen the way they were drawn.
"""

from __future__ import annotations

import pytest

from aesmovie import fixtiles


def geolith_fix_pixel(tile: bytes, x: int, y: int) -> int:
    offsets = (0x10, 0x18, 0x00, 0x08)
    byte = tile[offsets[x >> 1] + y]
    return (byte & 0x0F) if (x & 1) == 0 else ((byte >> 4) & 0x0F)


def decode(tile: bytes) -> list[list[int]]:
    return [[geolith_fix_pixel(tile, x, y) for x in range(8)] for y in range(8)]


class TestPacking:
    def test_a_tile_is_thirty_two_bytes(self):
        packed = fixtiles.pack_tile([[0] * 8 for _ in range(8)])

        assert len(packed) == 32

    def test_a_drawn_tile_reads_back_through_the_emulator_decode(self):
        pattern = [[(x + y) % 16 for x in range(8)] for y in range(8)]

        packed = fixtiles.pack_tile(pattern)

        assert decode(packed) == pattern

    def test_the_left_pixel_of_a_pair_is_the_low_nibble(self):
        pattern = [[0] * 8 for _ in range(8)]
        pattern[0][0] = 0x0F

        packed = fixtiles.pack_tile(pattern)

        assert packed[0x10] == 0x0F

    def test_the_right_pixel_of_a_pair_is_the_high_nibble(self):
        pattern = [[0] * 8 for _ in range(8)]
        pattern[0][1] = 0x0F

        packed = fixtiles.pack_tile(pattern)

        assert packed[0x10] == 0xF0

    def test_a_pixel_above_the_nibble_range_is_rejected(self):
        pattern = [[0] * 8 for _ in range(8)]
        pattern[0][0] = 16

        with pytest.raises(ValueError, match="4-bit"):
            fixtiles.pack_tile(pattern)

    def test_a_wrongly_shaped_tile_is_rejected(self):
        with pytest.raises(ValueError, match="8x8"):
            fixtiles.pack_tile([[0] * 4 for _ in range(8)])


class TestGlyphSet:
    def test_the_blank_tile_is_index_zero(self):
        assert fixtiles.GLYPHS["blank"] == 0

    def test_digits_occupy_ten_consecutive_indices(self):
        indices = [fixtiles.GLYPHS[str(d)] for d in range(10)]

        assert indices == list(range(indices[0], indices[0] + 10))

    def test_every_transport_glyph_is_present(self):
        for name in ("play", "pause", "forward", "rewind"):
            assert name in fixtiles.GLYPHS

    def test_every_scrubber_glyph_is_present(self):
        for name in ("bar_empty", "bar_filled", "panel"):
            assert name in fixtiles.GLYPHS

    def test_glyph_indices_are_unique(self):
        indices = list(fixtiles.GLYPHS.values())

        assert len(indices) == len(set(indices))

    def test_glyph_indices_fit_the_twelve_bit_map_field(self):
        assert max(fixtiles.GLYPHS.values()) < 0x1000


class TestRom:
    def test_the_rom_holds_every_glyph(self):
        rom = fixtiles.build_rom()

        assert len(rom) >= (max(fixtiles.GLYPHS.values()) + 1) * 32

    def test_the_rom_pads_to_the_requested_size(self):
        rom = fixtiles.build_rom(pad_to=131072)

        assert len(rom) == 131072

    def test_the_blank_tile_is_fully_transparent(self):
        rom = fixtiles.build_rom()

        assert rom[:32] == bytes(32)

    def test_the_panel_tile_is_fully_opaque(self):
        rom = fixtiles.build_rom()
        index = fixtiles.GLYPHS["panel"]

        tile = rom[index * 32 : index * 32 + 32]
        assert all(value != 0 for row in decode(tile) for value in row)

    def test_the_filled_bar_differs_from_the_empty_bar(self):
        rom = fixtiles.build_rom()

        empty = fixtiles.GLYPHS["bar_empty"]
        filled = fixtiles.GLYPHS["bar_filled"]
        assert rom[empty * 32 : empty * 32 + 32] != rom[filled * 32 : filled * 32 + 32]

    def test_digits_are_visually_distinct(self):
        rom = fixtiles.build_rom()

        drawn = {
            bytes(rom[fixtiles.GLYPHS[str(d)] * 32 : fixtiles.GLYPHS[str(d)] * 32 + 32])
            for d in range(10)
        }
        assert len(drawn) == 10

    def test_padding_smaller_than_the_glyphs_is_rejected(self):
        with pytest.raises(ValueError, match="pad_to"):
            fixtiles.build_rom(pad_to=32)


class TestPalette:
    def test_the_overlay_palette_has_sixteen_entries(self):
        assert len(fixtiles.palette_words()) == 16

    def test_the_transparent_slot_is_first(self):
        assert fixtiles.palette_words()[0] == 0

    def test_the_ink_slot_is_brighter_than_the_panel_slot(self):
        words = fixtiles.palette_words()

        assert words[fixtiles.INK] > words[fixtiles.PANEL]
