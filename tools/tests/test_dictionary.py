from __future__ import annotations

import numpy as np
import pytest
from fmvcore.testing import SEED

from neogeomedia.dictionary import MAX_TILES, TileDictionary


def random_tile(stream: int) -> np.ndarray:
    rng = np.random.default_rng((SEED, stream))
    return rng.integers(0, 16, size=(16, 16), dtype=np.uint8)


def asymmetric_tile(stream: int) -> np.ndarray:
    tile = random_tile(stream)
    tile[0, 0] = 1
    tile[0, 15] = 2
    tile[15, 0] = 3
    tile[15, 15] = 4
    return tile


def holding(
    *tiles: np.ndarray, allow_flip: bool = True, capacity: int = MAX_TILES
) -> TileDictionary:
    dictionary = TileDictionary(allow_flip=allow_flip, capacity=capacity)
    for tile in tiles:
        dictionary.intern(tile)
    return dictionary


class TestInterning:
    def test_the_first_tile_takes_index_zero(self):
        # Arrange
        dictionary = TileDictionary()

        # Act
        ref = dictionary.intern(random_tile(1))

        # Assert
        assert ref.index == 0

    def test_a_new_tile_takes_the_next_index(self):
        # Arrange
        dictionary = holding(asymmetric_tile(1))

        # Act
        ref = dictionary.intern(asymmetric_tile(2))

        # Assert
        assert ref.index == 1

    def test_an_identical_tile_reuses_its_entry(self):
        # Arrange
        tile = asymmetric_tile(3)
        dictionary = holding(tile)

        # Act
        second = dictionary.intern(tile.copy())

        # Assert
        assert (second.index, second.hflip, second.vflip) == (0, False, False)

    def test_repeats_do_not_grow_the_dictionary(self):
        # Arrange
        tile = asymmetric_tile(4)
        dictionary = holding(*[tile.copy() for _ in range(9)])

        # Act
        dictionary.intern(tile.copy())

        # Assert
        assert len(dictionary) == 1

    def test_the_stored_tile_matches_what_was_interned(self):
        # Arrange
        dictionary = TileDictionary()
        tile = asymmetric_tile(5)

        # Act
        dictionary.intern(tile)

        # Assert
        assert np.array_equal(dictionary.tiles()[0], tile)


class TestFlipDedup:
    @pytest.mark.parametrize(
        ("rows", "columns", "expected"),
        [
            (slice(None), slice(None, None, -1), (0, True, False)),
            (slice(None, None, -1), slice(None), (0, False, True)),
            (slice(None, None, -1), slice(None, None, -1), (0, True, True)),
        ],
        ids=["horizontal", "vertical", "double"],
    )
    def test_a_mirror_reuses_the_original_entry(self, rows, columns, expected):
        # Arrange
        tile = asymmetric_tile(6)
        dictionary = holding(tile)
        mirrored = np.ascontiguousarray(tile[rows, columns])

        # Act
        ref = dictionary.intern(mirrored)

        # Assert
        assert (ref.index, ref.hflip, ref.vflip) == expected

    def test_all_four_orientations_share_one_entry(self):
        # Arrange
        tile = asymmetric_tile(9)
        dictionary = holding(
            tile,
            np.ascontiguousarray(tile[:, ::-1]),
            np.ascontiguousarray(tile[::-1, :]),
        )

        # Act
        dictionary.intern(np.ascontiguousarray(tile[::-1, ::-1]))

        # Assert
        assert len(dictionary) == 1

    def test_flip_dedup_can_be_switched_off(self):
        # Arrange
        tile = asymmetric_tile(10)
        dictionary = holding(tile, allow_flip=False)

        # Act
        ref = dictionary.intern(np.ascontiguousarray(tile[:, ::-1]))

        # Assert
        assert ref.index == 1
        assert ref.hflip is False

    def test_a_symmetric_tile_never_reports_a_flip_against_itself(self):
        # Arrange
        tile = np.zeros((16, 16), dtype=np.uint8)
        tile[4:12, 4:12] = 7
        dictionary = holding(tile)

        # Act
        ref = dictionary.intern(tile.copy())

        # Assert
        assert (ref.index, ref.hflip, ref.vflip) == (0, False, False)


class TestValidation:
    def test_a_wrongly_shaped_tile_is_rejected(self):
        # Arrange
        dictionary = TileDictionary()

        # Act
        with pytest.raises(ValueError) as raised:
            dictionary.intern(np.zeros((8, 8), dtype=np.uint8))

        # Assert
        assert str(raised.value) == "tile must be 16x16, got shape (8, 8)"

    def test_a_tile_with_out_of_range_pixels_is_rejected(self):
        # Arrange
        dictionary = TileDictionary()
        tile = np.zeros((16, 16), dtype=np.uint8)
        tile[0, 0] = 16

        # Act
        with pytest.raises(ValueError) as raised:
            dictionary.intern(tile)

        # Assert
        assert str(raised.value) == "tile pixels must be 4-bit palette indices in the range 0 to 15"

    def test_exceeding_the_capacity_is_rejected_for_a_single_intern(self):
        # Arrange
        dictionary = holding(asymmetric_tile(11), capacity=1)

        # Act
        with pytest.raises(ValueError) as raised:
            dictionary.intern(asymmetric_tile(12))

        # Assert
        assert str(raised.value) == "dictionary is full at 1 tiles"


class TestBatch:
    def test_a_batch_returns_one_reference_per_tile(self):
        # Arrange
        dictionary = TileDictionary()
        tiles = np.stack([asymmetric_tile(i) for i in (20, 21, 22)])

        # Act
        refs = dictionary.intern_batch(tiles)

        # Assert
        assert [ref.index for ref in refs] == [0, 1, 2]

    def test_a_batch_dedups_across_its_own_members(self):
        # Arrange
        dictionary = TileDictionary(allow_flip=True)
        tile = asymmetric_tile(23)
        tiles = np.ascontiguousarray(np.stack([tile, tile[:, ::-1], tile]))

        # Act
        refs = dictionary.intern_batch(tiles)

        # Assert
        assert len(dictionary) == 1
        assert [r.hflip for r in refs] == [False, True, False]

    def test_an_empty_dictionary_reports_zero_length(self):
        # Arrange
        dictionary = TileDictionary()

        # Act
        length = len(dictionary)

        # Assert
        assert length == 0

    def test_tiles_of_an_empty_dictionary_are_an_empty_batch(self):
        # Arrange
        dictionary = TileDictionary()

        # Act
        tiles = dictionary.tiles()

        # Assert
        assert tiles.shape == (0, 16, 16)

    def test_an_empty_batch_interns_nothing(self):
        # Arrange
        dictionary = TileDictionary()

        # Act
        refs = dictionary.intern_batch(np.zeros((0, 16, 16), dtype=np.uint8))

        # Assert
        assert (refs, len(dictionary)) == ([], 0)


class TestRomImages:
    def test_padding_below_the_payload_is_refused(self):
        # Arrange
        dictionary = holding(asymmetric_tile(30), asymmetric_tile(31))

        # Act
        with pytest.raises(ValueError) as refused:
            dictionary.rom_images(pad_to=1)

        # Assert
        assert str(refused.value) == "pad_to 1 is smaller than the 128 byte payload"
