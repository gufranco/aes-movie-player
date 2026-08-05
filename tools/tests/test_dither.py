from __future__ import annotations

import numpy as np

from aesmovie import palettes


def a_ramp_tile(low: int, high: int) -> np.ndarray:
    """A 16x16 tile sweeping a gradient, the shape that bands worst."""
    row = np.linspace(low, high, palettes.TILE_PX, dtype=np.float64)
    return np.tile(row, (palettes.TILE_PX, 1)).astype(np.uint16)


def a_palette_set(colors: list[int]) -> palettes.PaletteSet:
    entries = np.zeros((1, palettes.PALETTE_SLOTS), dtype=np.uint16)
    entries[0, : len(colors)] = colors
    entries[0, len(colors) :] = colors[-1]
    return palettes.PaletteSet(colors=entries, base_bank=16)


class TestTheThresholdField:
    def test_it_covers_a_whole_tile(self):
        field = palettes.bayer_thresholds()

        assert field.shape == (palettes.TILE_PX, palettes.TILE_PX)

    def test_it_stays_inside_the_unit_interval(self):
        field = palettes.bayer_thresholds()

        assert field.min() > 0.0
        assert field.max() < 1.0

    def test_it_repeats_on_a_period_that_divides_a_tile(self):
        field = palettes.bayer_thresholds()

        assert np.array_equal(field[:8, :8], field[8:, 8:])
        assert np.array_equal(field[:8, :8], field[8:, :8])

    def test_every_level_appears_equally_often(self):
        _, counts = np.unique(palettes.bayer_thresholds(), return_counts=True)

        assert set(counts.tolist()) == {4}


class TestItKeepsTilesInternable:
    def test_two_identical_tiles_still_quantise_identically(self):
        tiles = np.stack([a_ramp_tile(0, 0x7FFF)] * 2)
        assigner = palettes.PaletteAssigner(a_palette_set([0, 0x1000, 0x7FFF]), dither=True)

        out = assigner.assign(tiles)

        assert np.array_equal(out.nibbles[0], out.nibbles[1])

    def test_a_tile_quantises_the_same_wherever_it_sits_in_the_frame(self):
        one = a_ramp_tile(0, 0x7FFF)
        other = a_ramp_tile(0x2000, 0x5000)
        assigner = palettes.PaletteAssigner(a_palette_set([0, 0x1000, 0x7FFF]), dither=True)

        first = assigner.assign(np.stack([one, other, one]))
        second = assigner.assign(np.stack([other, one]))

        assert np.array_equal(first.nibbles[0], first.nibbles[2])
        assert np.array_equal(first.nibbles[0], second.nibbles[1])


class TestItActuallyDithers:
    def test_a_gradient_gains_intermediate_levels(self):
        tiles = a_ramp_tile(0, 0x7FFF)[None, :, :]
        palette = a_palette_set([0, 0x1000, 0x7FFF])

        plain = palettes.PaletteAssigner(palette).assign(tiles)
        mixed = palettes.PaletteAssigner(palette, dither=True).assign(tiles)

        assert len(np.unique(mixed.nibbles)) >= len(np.unique(plain.nibbles))

    def test_a_colour_sitting_on_a_palette_entry_is_never_swapped(self):
        flat = np.full((1, palettes.TILE_PX, palettes.TILE_PX), 0x1000, dtype=np.uint16)
        assigner = palettes.PaletteAssigner(a_palette_set([0, 0x1000, 0x7FFF]), dither=True)

        out = assigner.assign(flat)

        assert len(np.unique(out.nibbles)) == 1

    def test_leaving_it_off_changes_nothing(self):
        tiles = a_ramp_tile(0, 0x7FFF)[None, :, :]
        palette = a_palette_set([0, 0x1000, 0x7FFF])

        before = palettes.PaletteAssigner(palette).assign(tiles)
        after = palettes.PaletteAssigner(palette, dither=False).assign(tiles)

        assert np.array_equal(before.nibbles, after.nibbles)
