"""Tile packer tests.

`GeolithTileReader` is an independent transcription of `geo_lspc_tpix`
and the sprite pixel loop in geolith's `src/geo_lspc.c`. It reads the
byte-interleaved C-ROM the way the target emulator does, including the
flip handling, so a round trip through it proves the packed bytes render
as the source tile rather than merely matching the packer's own
arithmetic.
"""

from __future__ import annotations

import numpy as np
import pytest

from aesmovie import crom
from tests.geolith_model import GeolithTileReader

TILE_BYTES = 128


def random_tiles(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 16, size=(count, 16, 16), dtype=np.uint8)


class TestPackTiles:
    def test_each_tile_occupies_sixty_four_bytes_per_rom(self):
        tiles = random_tiles(7, seed=20260802)

        c1, c2 = crom.pack_tiles(tiles)

        assert c1.shape == (7, 64)
        assert c2.shape == (7, 64)

    def test_packed_tiles_read_back_identically_through_the_emulator_decoder(self):
        tiles = random_tiles(64, seed=11)

        c1, c2 = crom.pack_tiles(tiles)

        reader = GeolithTileReader(c1, c2)
        for index in range(len(tiles)):
            assert np.array_equal(reader.tile(index), tiles[index])

    def test_horizontal_flip_reads_the_mirrored_tile(self):
        tiles = random_tiles(8, seed=12)

        c1, c2 = crom.pack_tiles(tiles)

        reader = GeolithTileReader(c1, c2)
        for index in range(len(tiles)):
            assert np.array_equal(reader.tile(index, hflip=True), tiles[index][:, ::-1])

    def test_vertical_flip_reads_the_mirrored_tile(self):
        tiles = random_tiles(8, seed=13)

        c1, c2 = crom.pack_tiles(tiles)

        reader = GeolithTileReader(c1, c2)
        for index in range(len(tiles)):
            assert np.array_equal(reader.tile(index, vflip=True), tiles[index][::-1, :])

    def test_both_flips_read_the_doubly_mirrored_tile(self):
        tiles = random_tiles(8, seed=14)

        c1, c2 = crom.pack_tiles(tiles)

        reader = GeolithTileReader(c1, c2)
        for index in range(len(tiles)):
            expected = tiles[index][::-1, ::-1]
            assert np.array_equal(reader.tile(index, hflip=True, vflip=True), expected)

    def test_a_uniform_tile_packs_to_a_constant_byte_pattern(self):
        tiles = np.full((1, 16, 16), 0x0F, dtype=np.uint8)

        c1, c2 = crom.pack_tiles(tiles)

        assert np.all(c1 == 0xFF)
        assert np.all(c2 == 0xFF)

    def test_a_zero_tile_packs_to_zero_bytes(self):
        tiles = np.zeros((1, 16, 16), dtype=np.uint8)

        c1, c2 = crom.pack_tiles(tiles)

        assert not c1.any()
        assert not c2.any()

    def test_a_single_lit_pixel_sets_exactly_one_bit(self):
        tiles = np.zeros((1, 16, 16), dtype=np.uint8)
        tiles[0, 5, 3] = 0x08

        c1, c2 = crom.pack_tiles(tiles)

        assert int(c1.sum()) == 0
        assert int(np.unpackbits(c2).sum()) == 1

    def test_pixel_values_above_the_nibble_range_are_rejected(self):
        tiles = np.zeros((1, 16, 16), dtype=np.uint8)
        tiles[0, 0, 0] = 16

        with pytest.raises(ValueError, match="4-bit"):
            crom.pack_tiles(tiles)

    def test_wrongly_shaped_input_is_rejected(self):
        tiles = np.zeros((1, 8, 8), dtype=np.uint8)

        with pytest.raises(ValueError, match="16x16"):
            crom.pack_tiles(tiles)

    def test_an_empty_batch_packs_to_empty_roms(self):
        tiles = np.zeros((0, 16, 16), dtype=np.uint8)

        c1, c2 = crom.pack_tiles(tiles)

        assert c1.shape == (0, 64)
        assert c2.shape == (0, 64)


class TestRomImages:
    def test_rom_images_pad_to_the_requested_size(self):
        tiles = random_tiles(3, seed=15)

        c1, c2 = crom.build_rom_images(tiles, pad_to=4096)

        assert len(c1) == 4096
        assert len(c2) == 4096

    def test_rom_images_hold_the_packed_tiles_at_the_front(self):
        tiles = random_tiles(3, seed=16)

        c1, c2 = crom.build_rom_images(tiles, pad_to=4096)

        packed_c1, packed_c2 = crom.pack_tiles(tiles)
        assert c1[: 3 * 64] == packed_c1.tobytes()
        assert c2[: 3 * 64] == packed_c2.tobytes()

    def test_padding_smaller_than_the_payload_is_rejected(self):
        tiles = random_tiles(64, seed=17)

        with pytest.raises(ValueError, match="pad_to"):
            crom.build_rom_images(tiles, pad_to=128)


class TestPowerOfTwoPadding:
    @pytest.mark.parametrize(
        ("tile_count", "expected"),
        [(1, 1 << 20), (16384, 1 << 20), (16385, 1 << 21), (100_000, 1 << 23)],
    )
    def test_rom_size_rounds_up_to_a_power_of_two(self, tile_count, expected):
        assert crom.rom_size_for(tile_count) == expected

    def test_zero_tiles_still_produce_the_minimum_rom(self):
        assert crom.rom_size_for(0) == 1 << 20
