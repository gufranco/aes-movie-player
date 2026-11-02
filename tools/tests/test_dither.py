from __future__ import annotations

import numpy as np
import pytest

from neogeomedia import neocolor, palettes


def greys(*levels: int) -> np.ndarray:
    rgb = np.repeat(np.array(levels, dtype=np.uint8)[:, None], 3, axis=1)
    return neocolor.rgb_to_color_index(rgb)


BLACK, MID_GREY, WHITE = (int(index) for index in greys(0, 128, 255))
THREE_ENTRIES = [BLACK, MID_GREY, WHITE]
RED, GREEN, BLUE = 31 << 10, 31 << 5, 31
DIM_GREY = (15 << 10) | (15 << 5) | 15


def a_ramp_tile(low: int, high: int) -> np.ndarray:
    row = np.rint(np.linspace(low, high, palettes.TILE_PX)).astype(np.uint8)
    return np.tile(greys(*row.tolist()), (palettes.TILE_PX, 1)).astype(np.uint16)


def a_palette_set(colors: list[int]) -> palettes.PaletteSet:
    entries = np.zeros((1, palettes.PALETTE_SLOTS), dtype=np.uint16)
    entries[0, : len(colors)] = colors
    entries[0, len(colors) :] = colors[-1]
    return palettes.PaletteSet(colors=entries, base_bank=16)


def dithering() -> palettes.PaletteAssigner:
    return palettes.PaletteAssigner(a_palette_set(THREE_ENTRIES), dither=True)


class TestItKeepsTilesInternable:
    def test_two_identical_tiles_still_quantise_identically(self):
        # Arrange
        tiles = np.stack([a_ramp_tile(0, 255)] * 2)
        assigner = dithering()

        # Act
        out = assigner.assign(tiles)

        # Assert
        assert np.array_equal(out.nibbles[0], out.nibbles[1])

    def test_a_tile_quantises_the_same_wherever_it_sits_in_the_frame(self):
        # Arrange
        one = a_ramp_tile(0, 255)
        other = a_ramp_tile(64, 160)
        assigner = dithering()
        elsewhere = assigner.assign(np.stack([other, one]))

        # Act
        first = assigner.assign(np.stack([one, other, one]))

        # Assert
        assert np.array_equal(first.nibbles[0], first.nibbles[2])
        assert np.array_equal(first.nibbles[0], elsewhere.nibbles[1])


class TestItActuallyDithers:
    def test_a_gradient_gains_intermediate_levels(self):
        # Arrange
        tiles = a_ramp_tile(0, 255)[None, :, :]
        plain = palettes.PaletteAssigner(a_palette_set(THREE_ENTRIES)).assign(tiles)

        # Act
        mixed = dithering().assign(tiles)

        # Assert
        assert len(np.unique(mixed.nibbles)) >= len(np.unique(plain.nibbles))

    def test_a_colour_sitting_on_a_palette_entry_is_never_swapped(self):
        # Arrange
        flat = np.full((1, palettes.TILE_PX, palettes.TILE_PX), MID_GREY, dtype=np.uint16)
        assigner = dithering()

        # Act
        out = assigner.assign(flat)

        # Assert
        assert len(np.unique(out.nibbles)) == 1

    def test_a_colour_no_pair_of_entries_brackets_is_drawn_from_three(self):
        # Arrange
        primaries = [RED, GREEN, BLUE]
        flat = np.full((1, palettes.TILE_PX, palettes.TILE_PX), DIM_GREY, dtype=np.uint16)

        # Act
        out = palettes.PaletteAssigner(a_palette_set(primaries), dither=True).assign(flat)

        # Assert
        assert np.unique(out.nibbles).tolist() == [1, 2, 3]

    def test_leaving_it_off_changes_nothing(self):
        # Arrange
        tiles = a_ramp_tile(0, 255)[None, :, :]
        palette = a_palette_set(THREE_ENTRIES)
        before = palettes.PaletteAssigner(palette).assign(tiles)

        # Act
        after = palettes.PaletteAssigner(palette, dither=False).assign(tiles)

        # Assert
        assert np.array_equal(before.nibbles, after.nibbles)


def swapped_pixels(strength: float) -> int:
    tiles = a_ramp_tile(0, 255)[None, :, :]
    palette = a_palette_set(THREE_ENTRIES)
    plain = palettes.PaletteAssigner(palette).assign(tiles)
    mixed = palettes.PaletteAssigner(palette, dither=strength).assign(tiles)
    return int(np.count_nonzero(plain.nibbles != mixed.nibbles))


class TestStrength:
    def test_a_weaker_dither_swaps_fewer_pixels_than_a_full_one(self):
        # Arrange
        half, full = 0.5, palettes.MAX_DITHER

        # Act
        swapped = (swapped_pixels(half), swapped_pixels(full))

        # Assert
        assert 0 < swapped[0] < swapped[1]

    def test_strength_zero_is_no_dither(self):
        # Arrange
        strength = palettes.NO_DITHER

        # Act
        swapped = swapped_pixels(strength)

        # Assert
        assert swapped == 0

    @pytest.mark.parametrize("strength", [-0.1, 1.1], ids=["negative", "past-the-maximum"])
    def test_a_strength_outside_the_range_is_refused(self, strength):
        # Arrange
        palette = a_palette_set(THREE_ENTRIES)

        # Act
        with pytest.raises(ValueError, match="dither strength") as raised:
            palettes.PaletteAssigner(palette, dither=strength)

        # Assert
        assert f"{strength:g}" in str(raised.value)
