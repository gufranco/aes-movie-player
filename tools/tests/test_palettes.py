from __future__ import annotations

import struct

import numpy as np
import pytest

from aesmovie import neocolor, palettes


def color(r5: int, g5: int, b5: int) -> int:
    return (r5 << 10) | (g5 << 5) | b5


def tile_of(values: list[int]) -> np.ndarray:
    tile = np.zeros((16, 16), dtype=np.uint16)
    for i, value in enumerate(values):
        tile[:, i] = value
    for i in range(len(values), 16):
        tile[:, i] = values[i % len(values)]
    return tile


FIFTEEN_COLORS = [color(2 * i, 31 - 2 * i, (5 * i) % 32) for i in range(15)]


class TestPaletteSet:
    def test_the_cram_blob_is_thirty_two_bytes_per_palette(self):
        palette_set = palettes.PaletteSet(
            colors=np.array([FIFTEEN_COLORS], dtype=np.uint16), base_bank=16
        )

        assert len(palette_set.cram_blob()) == 32

    def test_slot_zero_is_reserved_for_transparency(self):
        palette_set = palettes.PaletteSet(
            colors=np.array([FIFTEEN_COLORS], dtype=np.uint16), base_bank=16
        )

        words = struct.unpack(">16H", palette_set.cram_blob())
        assert words[0] == 0

    def test_the_fifteen_usable_slots_hold_the_encoded_colours(self):
        palette_set = palettes.PaletteSet(
            colors=np.array([FIFTEEN_COLORS], dtype=np.uint16), base_bank=16
        )

        words = struct.unpack(">16H", palette_set.cram_blob())
        expected = neocolor.color_index_to_palette_word(np.array(FIFTEEN_COLORS))
        assert list(words[1:]) == [int(w) for w in expected]

    def test_palettes_map_onto_consecutive_cram_banks(self):
        palette_set = palettes.PaletteSet(colors=np.zeros((3, 15), dtype=np.uint16), base_bank=16)

        assert [palette_set.bank_of(i) for i in range(3)] == [16, 17, 18]

    def test_a_palette_set_overflowing_cram_is_rejected(self):
        with pytest.raises(ValueError, match="CRAM"):
            palettes.PaletteSet(colors=np.zeros((250, 15), dtype=np.uint16), base_bank=16)

    def test_a_wrongly_shaped_palette_table_is_rejected(self):
        with pytest.raises(ValueError, match="15"):
            palettes.PaletteSet(colors=np.zeros((4, 16), dtype=np.uint16), base_bank=16)


class TestBuildPaletteSet:
    def test_it_produces_the_requested_number_of_palettes(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS) for _ in range(8)])

        palette_set = palettes.build_palette_set(tiles, count=4, base_bank=16, seed=1)

        assert palette_set.colors.shape == (4, 15)

    def test_it_never_asks_for_more_palettes_than_cram_holds(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])

        with pytest.raises(ValueError, match="CRAM"):
            palettes.build_palette_set(tiles, count=250, base_bank=16, seed=1)

    def test_a_tile_with_fifteen_colours_is_reproduced_exactly(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])

        palette_set = palettes.build_palette_set(tiles, count=1, base_bank=16, seed=2)

        assert {int(c) for c in palette_set.colors[0]} == set(FIFTEEN_COLORS)

    def test_it_is_deterministic_for_a_fixed_seed(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS[: i or 1]) for i in range(12)])

        first = palettes.build_palette_set(tiles, count=6, base_bank=16, seed=7)
        second = palettes.build_palette_set(tiles, count=6, base_bank=16, seed=7)

        assert np.array_equal(first.colors, second.colors)

    def test_distinct_content_groups_get_distinct_palettes(self):
        warm = tile_of([color(31, 4, 4), color(28, 8, 2)])
        cool = tile_of([color(4, 4, 31), color(2, 8, 28)])
        tiles = np.stack([warm] * 8 + [cool] * 8)

        palette_set = palettes.build_palette_set(tiles, count=2, base_bank=16, seed=3)

        assigner = palettes.PaletteAssigner(palette_set)
        assignment = assigner.assign(np.stack([warm, cool]))
        assert assignment.palette_ids[0] != assignment.palette_ids[1]

    def test_an_empty_tile_batch_is_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            palettes.build_palette_set(
                np.zeros((0, 16, 16), dtype=np.uint16), count=4, base_bank=16, seed=1
            )


class TestAssignment:
    def test_pixel_indices_never_use_the_transparent_slot(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = palettes.build_palette_set(tiles, count=2, base_bank=16, seed=4)

        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        assert assignment.nibbles.min() >= 1

    def test_pixel_indices_stay_inside_the_palette(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = palettes.build_palette_set(tiles, count=2, base_bank=16, seed=4)

        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        assert assignment.nibbles.max() <= 15

    def test_an_exactly_representable_tile_quantizes_without_error(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = palettes.build_palette_set(tiles, count=1, base_bank=16, seed=5)

        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        assert assignment.error[0] == pytest.approx(0.0, abs=1e-9)

    def test_an_exactly_representable_tile_round_trips_to_its_own_colours(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = palettes.build_palette_set(tiles, count=1, base_bank=16, seed=5)

        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        rendered = palette_set.colors[assignment.palette_ids[0]][assignment.nibbles[0] - 1]
        assert np.array_equal(rendered, tiles[0])

    def test_a_tile_needing_more_than_fifteen_colours_carries_error(self):
        wide = np.zeros((1, 16, 16), dtype=np.uint16)
        wide[0] = np.arange(256, dtype=np.uint16).reshape(16, 16) * 101
        palette_set = palettes.build_palette_set(wide, count=1, base_bank=16, seed=6)

        assignment = palettes.PaletteAssigner(palette_set).assign(wide)

        assert assignment.error[0] > 0.0

    def test_the_lower_error_palette_wins(self):
        warm = color(31, 2, 2)
        cool = color(2, 2, 31)
        palette_set = palettes.PaletteSet(
            colors=np.array([[warm] * 15, [cool] * 15], dtype=np.uint16), base_bank=16
        )
        tile = np.full((1, 16, 16), cool, dtype=np.uint16)

        assignment = palettes.PaletteAssigner(palette_set).assign(tile)

        assert assignment.palette_ids[0] == 1

    def test_restricting_candidates_still_returns_one_choice_per_tile(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS) for _ in range(5)])
        palette_set = palettes.build_palette_set(tiles, count=4, base_bank=16, seed=8)

        assignment = palettes.PaletteAssigner(palette_set, candidates=2).assign(tiles)

        assert assignment.palette_ids.shape == (5,)

    def test_exhaustive_search_is_never_worse_than_a_restricted_search(self):
        rng = np.random.default_rng(99)
        tiles = rng.integers(0, 32768, size=(24, 16, 16), dtype=np.uint16)
        palette_set = palettes.build_palette_set(tiles, count=8, base_bank=16, seed=9)

        exhaustive = palettes.PaletteAssigner(palette_set).assign(tiles)
        restricted = palettes.PaletteAssigner(palette_set, candidates=2).assign(tiles)

        assert exhaustive.error.sum() <= restricted.error.sum() + 1e-6

    def test_assignment_shapes_follow_the_tile_batch(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS) for _ in range(3)])
        palette_set = palettes.build_palette_set(tiles, count=2, base_bank=16, seed=10)

        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        assert assignment.nibbles.shape == (3, 16, 16)
        assert assignment.error.shape == (3,)

    def test_an_empty_batch_assigns_nothing(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = palettes.build_palette_set(tiles, count=2, base_bank=16, seed=11)

        assignment = palettes.PaletteAssigner(palette_set).assign(
            np.zeros((0, 16, 16), dtype=np.uint16)
        )

        assert assignment.palette_ids.shape == (0,)

    def test_the_rendered_tile_is_reported_alongside_the_indices(self):
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = palettes.build_palette_set(tiles, count=1, base_bank=16, seed=12)

        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        assert np.array_equal(assignment.rendered(palette_set), tiles)
