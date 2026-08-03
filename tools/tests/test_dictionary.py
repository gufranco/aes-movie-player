from __future__ import annotations

import numpy as np
import pytest

from aesmovie.dictionary import MAX_TILES, TileDictionary


def random_tile(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 16, size=(16, 16), dtype=np.uint8)


def asymmetric_tile(seed: int) -> np.ndarray:
    tile = random_tile(seed)
    tile[0, 0] = 1
    tile[0, 15] = 2
    tile[15, 0] = 3
    tile[15, 15] = 4
    return tile


class TestInterning:
    def test_the_first_tile_takes_index_zero(self):
        dictionary = TileDictionary()

        ref = dictionary.intern(random_tile(1))

        assert ref.index == 0

    def test_a_new_tile_takes_the_next_index(self):
        dictionary = TileDictionary()
        dictionary.intern(asymmetric_tile(1))

        ref = dictionary.intern(asymmetric_tile(2))

        assert ref.index == 1

    def test_an_identical_tile_reuses_its_entry(self):
        dictionary = TileDictionary()
        tile = asymmetric_tile(3)
        first = dictionary.intern(tile)

        second = dictionary.intern(tile.copy())

        assert (second.index, second.hflip, second.vflip) == (first.index, False, False)

    def test_repeats_do_not_grow_the_dictionary(self):
        dictionary = TileDictionary()
        tile = asymmetric_tile(4)

        for _ in range(10):
            dictionary.intern(tile.copy())

        assert len(dictionary) == 1

    def test_the_stored_tile_matches_what_was_interned(self):
        dictionary = TileDictionary()
        tile = asymmetric_tile(5)

        dictionary.intern(tile)

        assert np.array_equal(dictionary.tiles()[0], tile)


class TestFlipDedup:
    def test_a_horizontal_mirror_reuses_the_original_entry(self):
        dictionary = TileDictionary()
        tile = asymmetric_tile(6)
        original = dictionary.intern(tile)

        ref = dictionary.intern(tile[:, ::-1].copy())

        assert (ref.index, ref.hflip, ref.vflip) == (original.index, True, False)

    def test_a_vertical_mirror_reuses_the_original_entry(self):
        dictionary = TileDictionary()
        tile = asymmetric_tile(7)
        original = dictionary.intern(tile)

        ref = dictionary.intern(tile[::-1, :].copy())

        assert (ref.index, ref.hflip, ref.vflip) == (original.index, False, True)

    def test_a_double_mirror_reuses_the_original_entry(self):
        dictionary = TileDictionary()
        tile = asymmetric_tile(8)
        original = dictionary.intern(tile)

        ref = dictionary.intern(tile[::-1, ::-1].copy())

        assert (ref.index, ref.hflip, ref.vflip) == (original.index, True, True)

    def test_all_four_orientations_share_one_entry(self):
        dictionary = TileDictionary()
        tile = asymmetric_tile(9)

        for variant in (tile, tile[:, ::-1], tile[::-1, :], tile[::-1, ::-1]):
            dictionary.intern(np.ascontiguousarray(variant))

        assert len(dictionary) == 1

    def test_flip_dedup_can_be_switched_off(self):
        dictionary = TileDictionary(allow_flip=False)
        tile = asymmetric_tile(10)
        dictionary.intern(tile)

        ref = dictionary.intern(tile[:, ::-1].copy())

        assert ref.index == 1
        assert ref.hflip is False

    def test_a_symmetric_tile_never_reports_a_flip_against_itself(self):
        dictionary = TileDictionary()
        tile = np.zeros((16, 16), dtype=np.uint8)
        tile[4:12, 4:12] = 7
        original = dictionary.intern(tile)

        ref = dictionary.intern(tile.copy())

        assert (ref.index, ref.hflip, ref.vflip) == (original.index, False, False)


class TestValidation:
    def test_a_wrongly_shaped_tile_is_rejected(self):
        dictionary = TileDictionary()

        with pytest.raises(ValueError, match="16x16"):
            dictionary.intern(np.zeros((8, 8), dtype=np.uint8))

    def test_a_tile_with_out_of_range_pixels_is_rejected(self):
        dictionary = TileDictionary()
        tile = np.zeros((16, 16), dtype=np.uint8)
        tile[0, 0] = 16

        with pytest.raises(ValueError, match="4-bit"):
            dictionary.intern(tile)

    def test_exceeding_the_twenty_bit_tile_number_is_rejected(self):
        dictionary = TileDictionary()
        dictionary._entries = [None] * MAX_TILES

        with pytest.raises(ValueError, match="20-bit"):
            dictionary.intern(random_tile(11))


class TestBatch:
    def test_a_batch_returns_one_reference_per_tile(self):
        dictionary = TileDictionary()
        tiles = np.stack([asymmetric_tile(i) for i in (20, 21, 22)])

        refs = dictionary.intern_batch(tiles)

        assert len(refs) == 3

    def test_a_batch_dedups_across_its_own_members(self):
        dictionary = TileDictionary()
        tile = asymmetric_tile(23)
        tiles = np.stack([tile, tile[:, ::-1], tile])

        refs = dictionary.intern_batch(np.ascontiguousarray(tiles))

        assert len(dictionary) == 1
        assert [r.hflip for r in refs] == [False, True, False]

    def test_an_empty_dictionary_reports_zero_length(self):
        assert len(TileDictionary()) == 0

    def test_tiles_of_an_empty_dictionary_are_an_empty_batch(self):
        assert TileDictionary().tiles().shape == (0, 16, 16)
