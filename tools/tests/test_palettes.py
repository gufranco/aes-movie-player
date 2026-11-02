from __future__ import annotations

import struct

import numpy as np
import pytest
from fmvcore.testing import SEED

from neogeomedia import palettes

BASE_BANK = 16


def color(r5: int, g5: int, b5: int) -> int:
    return (r5 << 10) | (g5 << 5) | b5


def hardware_word(r5: int, g5: int, b5: int) -> int:
    low_bits = ((r5 & 1) << 14) | ((g5 & 1) << 13) | ((b5 & 1) << 12)
    return low_bits | ((r5 >> 1) << 8) | ((g5 >> 1) << 4) | (b5 >> 1)


def tile_of(values: list[int]) -> np.ndarray:
    columns = [values[i % len(values)] for i in range(16)]
    return np.tile(np.array(columns, dtype=np.uint16), (16, 1))


FIFTEEN_CHANNELS = [(2 * i, 31 - 2 * i, (5 * i) % 32) for i in range(15)]
FIFTEEN_COLORS = [color(*channels) for channels in FIFTEEN_CHANNELS]


def one_palette() -> palettes.PaletteSet:
    return palettes.PaletteSet(
        colors=np.array([FIFTEEN_COLORS], dtype=np.uint16), base_bank=BASE_BANK
    )


def built(tiles: np.ndarray, count: int) -> palettes.PaletteSet:
    return palettes.build_palette_set(tiles, count=count, base_bank=BASE_BANK, seed=SEED)


class TestPaletteSet:
    def test_the_cram_blob_is_thirty_two_bytes_per_palette(self):
        # Arrange
        palette_set = one_palette()

        # Act
        blob = palette_set.cram_blob()

        # Assert
        assert len(blob) == 32

    def test_slot_zero_is_reserved_for_transparency(self):
        # Arrange
        palette_set = one_palette()

        # Act
        words = struct.unpack(">16H", palette_set.cram_blob())

        # Assert
        assert words[0] == 0

    def test_the_fifteen_usable_slots_hold_the_hardware_encoded_colours(self):
        # Arrange
        palette_set = one_palette()

        # Act
        words = struct.unpack(">16H", palette_set.cram_blob())

        # Assert
        assert list(words[1:]) == [hardware_word(*channels) for channels in FIFTEEN_CHANNELS]

    def test_a_worked_colour_encodes_to_its_documented_word(self):
        # Arrange
        palette_set = palettes.PaletteSet(
            colors=np.full((1, 15), color(31, 0, 17), dtype=np.uint16), base_bank=BASE_BANK
        )

        # Act
        words = struct.unpack(">16H", palette_set.cram_blob())

        # Assert
        assert words[1] == 0x5F08

    def test_palettes_map_onto_consecutive_cram_banks(self):
        # Arrange
        palette_set = palettes.PaletteSet(
            colors=np.zeros((3, 15), dtype=np.uint16), base_bank=BASE_BANK
        )

        # Act
        banks = [palette_set.bank_of(i) for i in range(3)]

        # Assert
        assert banks == [16, 17, 18]

    @pytest.mark.parametrize(
        ("shape", "complaint"),
        [((250, 15), "CRAM"), ((4, 16), "15")],
        ids=["overflowing-cram", "wrongly-shaped"],
    )
    def test_an_impossible_palette_table_is_rejected(self, shape, complaint):
        # Arrange
        colors = np.zeros(shape, dtype=np.uint16)

        # Act
        with pytest.raises(ValueError, match=complaint) as refused:
            palettes.PaletteSet(colors=colors, base_bank=BASE_BANK)

        # Assert
        assert complaint in str(refused.value)


class TestBuildPaletteSet:
    def test_it_produces_the_requested_number_of_palettes(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS) for _ in range(8)])

        # Act
        palette_set = built(tiles, 4)

        # Assert
        assert palette_set.colors.shape == (4, 15)

    def test_it_never_asks_for_more_palettes_than_cram_holds(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])

        # Act
        with pytest.raises(ValueError, match="CRAM") as refused:
            built(tiles, 250)

        # Assert
        assert "250" in str(refused.value)

    def test_a_tile_with_fifteen_colours_is_reproduced_exactly(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])

        # Act
        palette_set = built(tiles, 1)

        # Assert
        assert sorted(int(c) for c in palette_set.colors[0]) == sorted(FIFTEEN_COLORS)

    def test_it_is_deterministic_for_a_fixed_seed(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS[: i or 1]) for i in range(12)])

        # Act
        first = built(tiles, 6)
        second = built(tiles, 6)

        # Assert
        assert np.array_equal(first.colors, second.colors)

    def test_distinct_content_groups_get_distinct_palettes(self):
        # Arrange
        warm = tile_of([color(31, 4, 4), color(28, 8, 2)])
        cool = tile_of([color(4, 4, 31), color(2, 8, 28)])
        tiles = np.stack([warm] * 8 + [cool] * 8)

        # Act
        palette_set = built(tiles, 2)

        # Assert
        assignment = palettes.PaletteAssigner(palette_set).assign(np.stack([warm, cool]))
        assert assignment.palette_ids[0] != assignment.palette_ids[1]

    def test_an_empty_tile_batch_is_rejected(self):
        # Arrange
        tiles = np.zeros((0, 16, 16), dtype=np.uint16)

        # Act
        with pytest.raises(ValueError, match="empty") as refused:
            built(tiles, 4)

        # Assert
        assert "empty" in str(refused.value)

    def test_heavy_near_duplicate_shades_do_not_crowd_out_a_bright_group(self):
        # Arrange
        tiles = crowded_tiles()

        # Act
        palette_set = built(tiles, 1)

        # Assert
        error = palettes.PaletteAssigner(palette_set).assign(tiles).error.sum()
        assert error < CROWDED_ERROR_CEILING


CROWDED_ERROR_CEILING = 0.04
WORSE_MIGRATION_SEED = 52
BLOB_RADIUS = 0.01


def crowded_blob() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    blob = np.random.default_rng(SEED).normal(0.0, 0.001, (60, 3))
    far = np.stack(
        [[0.2 + 0.05 * step, 0.3 * (step % 3 - 1), 0.3 * (step % 2 * 2 - 1)] for step in range(15)]
    )
    lab = np.concatenate([blob, far]).astype(np.float32)
    centroids = np.concatenate([blob[:11], far[:4]]).astype(np.float32)
    return lab, np.ones(lab.shape[0], dtype=np.float64), centroids


def histogram(seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    drawn = int(rng.integers(16, 60))
    colours = np.unique(rng.integers(0, 32768, drawn)).astype(np.uint16)
    counts = rng.integers(1, 200, colours.size)
    if rng.random() < 0.5:
        counts[: max(1, colours.size // 3)] *= 40
    return palettes.oklab_grid()[colours], counts.astype(np.float64)


class TestMigration:
    def test_centroids_crowded_into_one_blob_move_out_one_a_round(self):
        # Arrange
        lab, weight, centroids = crowded_blob()

        # Act
        moved = palettes._migrated(lab, weight, centroids, np.random.default_rng(SEED))

        # Assert
        in_blob = np.linalg.norm(moved, axis=1) < BLOB_RADIUS
        assert int(in_blob.sum()) == 11 - palettes.MIGRATION_ROUNDS

    def test_a_migration_that_would_raise_the_cost_is_discarded(self):
        # Arrange
        lab, weight = histogram(WORSE_MIGRATION_SEED)
        rng = np.random.default_rng(0)
        heaviest = lab[np.argsort(-weight)[:15]].astype(np.float32)
        centroids = palettes._converged(lab, weight, heaviest, rng)

        # Act
        moved = palettes._migrated(lab, weight, centroids, rng)

        # Assert
        assert np.array_equal(moved, centroids)


def crowded_tiles() -> np.ndarray:
    dark = [color(1, 1, shade) for shade in range(18)]
    bright = [color(31 - (step % 6), 20 + step // 6, 2) for step in range(8)]
    flat = np.array(dark * 20 + bright, dtype=np.uint16)
    flat = np.concatenate([flat, flat[: (-flat.size) % 256]])
    return flat.reshape(-1, 16, 16)


class TestAssignment:
    def test_pixel_indices_stay_inside_the_usable_palette_slots(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = built(tiles, 2)

        # Act
        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        # Assert
        assert assignment.nibbles.min() >= 1
        assert assignment.nibbles.max() <= 15

    def test_an_exactly_representable_tile_quantizes_without_error(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = built(tiles, 1)

        # Act
        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        # Assert
        assert assignment.error[0] == pytest.approx(0.0, abs=1e-9)

    def test_an_exactly_representable_tile_round_trips_to_its_own_colours(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = built(tiles, 1)

        # Act
        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        # Assert
        rendered = palette_set.colors[assignment.palette_ids[0]][assignment.nibbles[0] - 1]
        assert np.array_equal(rendered, tiles[0])

    def test_a_tile_needing_more_than_fifteen_colours_carries_error(self):
        # Arrange
        wide = (np.arange(256, dtype=np.uint16).reshape(1, 16, 16) * 101).astype(np.uint16)
        palette_set = built(wide, 1)

        # Act
        assignment = palettes.PaletteAssigner(palette_set).assign(wide)

        # Assert
        assert assignment.error[0] > 0.0

    def test_the_lower_error_palette_wins(self):
        # Arrange
        warm = color(31, 2, 2)
        cool = color(2, 2, 31)
        palette_set = palettes.PaletteSet(
            colors=np.array([[warm] * 15, [cool] * 15], dtype=np.uint16), base_bank=BASE_BANK
        )
        tile = np.full((1, 16, 16), cool, dtype=np.uint16)

        # Act
        assignment = palettes.PaletteAssigner(palette_set).assign(tile)

        # Assert
        assert assignment.palette_ids.tolist() == [1]

    def test_restricting_candidates_still_returns_one_choice_per_tile(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS) for _ in range(5)])
        palette_set = built(tiles, 4)

        # Act
        assignment = palettes.PaletteAssigner(palette_set, candidates=2).assign(tiles)

        # Assert
        assert assignment.palette_ids.shape == (5,)

    def test_a_tie_between_palettes_goes_to_the_first_as_the_full_search_does(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS) for _ in range(4)])
        palette_set = built(tiles, 3)

        # Act
        assignment = palettes.PaletteAssigner(palette_set, candidates=1).assign(tiles)

        # Assert
        assert assignment.palette_ids.tolist() == [0, 0, 0, 0]

    def test_exhaustive_search_is_never_worse_than_a_restricted_search(self):
        # Arrange
        rng = np.random.default_rng(SEED)
        tiles = rng.integers(0, 32768, size=(24, 16, 16), dtype=np.uint16)
        palette_set = built(tiles, 8)
        restricted = palettes.PaletteAssigner(palette_set, candidates=2).assign(tiles)

        # Act
        exhaustive = palettes.PaletteAssigner(palette_set).assign(tiles)

        # Assert
        assert exhaustive.error.sum() <= restricted.error.sum() + 1e-6

    def test_assignment_shapes_follow_the_tile_batch(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS) for _ in range(3)])
        palette_set = built(tiles, 2)

        # Act
        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        # Assert
        assert assignment.nibbles.shape == (3, 16, 16)
        assert assignment.error.shape == (3,)

    def test_an_empty_batch_assigns_nothing(self):
        # Arrange
        palette_set = built(np.stack([tile_of(FIFTEEN_COLORS)]), 2)
        empty = np.zeros((0, 16, 16), dtype=np.uint16)

        # Act
        assignment = palettes.PaletteAssigner(palette_set).assign(empty)

        # Assert
        assert assignment.palette_ids.shape == (0,)

    def test_the_rendered_tile_is_reported_alongside_the_indices(self):
        # Arrange
        tiles = np.stack([tile_of(FIFTEEN_COLORS)])
        palette_set = built(tiles, 1)
        assignment = palettes.PaletteAssigner(palette_set).assign(tiles)

        # Act
        rendered = assignment.rendered(palette_set)

        # Assert
        assert np.array_equal(rendered, tiles)
