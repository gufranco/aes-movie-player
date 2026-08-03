from __future__ import annotations

import struct

import pytest

from aesmovie import stream


def update(col, row, *, tile=0, palette=16, hflip=False, vflip=False):
    return stream.SlotUpdate(col=col, row=row, tile=tile, palette=palette, hflip=hflip, vflip=vflip)


def read_runs(blob: bytes):
    count = struct.unpack_from(">H", blob, 0)[0]
    offset = 2
    runs = []
    for _ in range(count):
        addr, tiles = struct.unpack_from(">HH", blob, offset)
        offset += 4
        entries = []
        for _ in range(tiles):
            entries.append(struct.unpack_from(">HH", blob, offset))
            offset += 4
        runs.append((addr, entries))
    assert offset == len(blob)
    return runs


class TestVramAddress:
    def test_the_grid_starts_at_sprite_one(self):
        assert stream.vram_address(0, 0) == 64

    def test_each_column_advances_one_sprite_block(self):
        assert stream.vram_address(1, 0) - stream.vram_address(0, 0) == 64

    def test_each_row_advances_one_tile_entry(self):
        assert stream.vram_address(0, 1) - stream.vram_address(0, 0) == 2

    def test_the_last_slot_stays_inside_its_sprite_block(self):
        assert stream.vram_address(19, 13) == 20 * 64 + 26

    @pytest.mark.parametrize(("col", "row"), [(-1, 0), (20, 0), (0, -1), (0, 14)])
    def test_out_of_grid_slots_are_rejected(self, col, row):
        with pytest.raises(ValueError, match="grid"):
            stream.vram_address(col, row)


class TestAttributeWord:
    def test_the_palette_occupies_the_high_byte(self):
        assert stream.attribute_word(palette=0xA5, tile=0, hflip=False, vflip=False) == 0xA500

    def test_the_high_tile_bits_occupy_bits_seven_to_four(self):
        word = stream.attribute_word(palette=0, tile=0xD_0000, hflip=False, vflip=False)

        assert word == 0x00D0

    def test_the_low_tile_bits_do_not_reach_the_attribute_word(self):
        word = stream.attribute_word(palette=0, tile=0xFFFF, hflip=False, vflip=False)

        assert word == 0x0000

    def test_horizontal_flip_is_bit_zero(self):
        assert stream.attribute_word(palette=0, tile=0, hflip=True, vflip=False) == 0x0001

    def test_vertical_flip_is_bit_one(self):
        assert stream.attribute_word(palette=0, tile=0, hflip=False, vflip=True) == 0x0002

    def test_auto_animation_bits_stay_clear(self):
        word = stream.attribute_word(palette=0xFF, tile=0xF_FFFF, hflip=True, vflip=True)

        assert word & 0x000C == 0

    def test_a_full_entry_combines_every_field(self):
        word = stream.attribute_word(palette=0x20, tile=0x9_1234, hflip=True, vflip=True)

        assert word == 0x2093

    def test_a_palette_outside_a_byte_is_rejected(self):
        with pytest.raises(ValueError, match="palette"):
            stream.attribute_word(palette=256, tile=0, hflip=False, vflip=False)

    def test_a_tile_outside_twenty_bits_is_rejected(self):
        with pytest.raises(ValueError, match="tile"):
            stream.attribute_word(palette=0, tile=1 << 20, hflip=False, vflip=False)


class TestPackFrame:
    def test_an_empty_frame_is_just_a_zero_run_count(self):
        blob = stream.pack_frame([])

        assert blob == b"\x00\x00"

    def test_a_single_update_becomes_one_run_of_one_tile(self):
        blob = stream.pack_frame([update(0, 0, tile=5, palette=17)])

        runs = read_runs(blob)
        assert runs == [(64, [(5, 0x1100)])]

    def test_consecutive_rows_in_one_column_merge_into_one_run(self):
        updates = [update(3, r, tile=r) for r in range(4)]

        blob = stream.pack_frame(updates)

        runs = read_runs(blob)
        assert len(runs) == 1
        assert runs[0][0] == stream.vram_address(3, 0)
        assert [entry[0] for entry in runs[0][1]] == [0, 1, 2, 3]

    def test_a_gap_between_rows_splits_the_run(self):
        updates = [update(3, 0), update(3, 1), update(3, 5)]

        runs = read_runs(stream.pack_frame(updates))

        assert len(runs) == 2

    def test_different_columns_never_merge(self):
        updates = [update(0, 13), update(1, 0)]

        runs = read_runs(stream.pack_frame(updates))

        assert len(runs) == 2

    def test_updates_are_sorted_before_packing(self):
        updates = [update(5, 2, tile=2), update(5, 0, tile=0), update(5, 1, tile=1)]

        runs = read_runs(stream.pack_frame(updates))

        assert len(runs) == 1
        assert [entry[0] for entry in runs[0][1]] == [0, 1, 2]

    def test_duplicate_slots_in_one_frame_are_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            stream.pack_frame([update(1, 1, tile=1), update(1, 1, tile=2)])

    def test_a_full_keyframe_packs_to_the_documented_size(self):
        updates = [update(c, r) for c in range(20) for r in range(14)]

        blob = stream.pack_frame(updates)

        assert len(blob) == 2 + 20 * (4 + 14 * 4)

    def test_a_full_keyframe_uses_one_run_per_column(self):
        updates = [update(c, r) for c in range(20) for r in range(14)]

        runs = read_runs(stream.pack_frame(updates))

        assert len(runs) == 20

    def test_every_record_stays_word_aligned(self):
        for count in range(0, 8):
            blob = stream.pack_frame([update(0, r) for r in range(count)])

            assert len(blob) % 2 == 0


class TestMovieStream:
    def test_the_stream_concatenates_frame_records(self):
        movie = stream.MovieStream()
        movie.append([update(0, 0)])
        movie.append([])

        first = stream.pack_frame([update(0, 0)])
        assert movie.blob()[: len(first) + 2] == first + b"\x00\x00"

    def test_the_index_records_one_offset_per_frame(self):
        movie = stream.MovieStream()
        movie.append([update(0, 0)])
        movie.append([])

        assert len(movie.frame_offsets()) == 2

    def test_offsets_point_at_the_start_of_each_record(self):
        movie = stream.MovieStream()
        first = stream.pack_frame([update(0, 0)])
        movie.append([update(0, 0)])
        movie.append([])

        assert list(movie.frame_offsets()) == [0, len(first)]

    def test_keyframes_are_tracked_separately(self):
        movie = stream.MovieStream()
        movie.append([update(0, 0)], keyframe=True)
        movie.append([])
        movie.append([update(1, 1)], keyframe=True)

        assert list(movie.keyframes()) == [0, 2]

    def test_the_index_blob_is_four_bytes_per_frame(self):
        movie = stream.MovieStream()
        movie.append([])
        movie.append([])

        assert len(movie.index_blob()) == 8

    def test_the_index_blob_is_big_endian(self):
        movie = stream.MovieStream()
        movie.append([update(0, 0)])
        movie.append([])

        offsets = struct.unpack(">2I", movie.index_blob())
        assert offsets == tuple(movie.frame_offsets())

    def test_an_empty_stream_has_no_frames(self):
        movie = stream.MovieStream()

        assert len(movie) == 0
        assert not any(movie.blob())


class TestBankContainment:
    def test_records_never_straddle_a_bank_boundary(self):
        movie = stream.MovieStream(bank_size=256)
        big = [update(c, r) for c in range(4) for r in range(14)]

        for _ in range(12):
            movie.append(big)

        size = len(stream.pack_frame(big))
        for offset in movie.frame_offsets():
            assert offset // 256 == (int(offset) + size - 1) // 256

    def test_padding_advances_the_offset_to_the_next_bank(self):
        movie = stream.MovieStream(bank_size=64)
        movie.append([update(0, 0)])

        movie.append([update(c, 0) for c in range(7)])

        assert movie.frame_offsets()[1] == 64

    def test_a_record_larger_than_a_bank_is_rejected(self):
        movie = stream.MovieStream(bank_size=16)

        with pytest.raises(ValueError, match="bank"):
            movie.append([update(c, 0) for c in range(8)])

    def test_the_blob_is_padded_out_to_whole_banks(self):
        movie = stream.MovieStream(bank_size=64)
        movie.append([update(0, 0)])

        assert len(movie.blob()) == 64

    def test_an_empty_stream_still_occupies_one_bank(self):
        assert len(stream.MovieStream(bank_size=64).blob()) == 64

    def test_the_bank_count_covers_every_record(self):
        movie = stream.MovieStream(bank_size=64)
        for _ in range(6):
            movie.append([update(0, 0), update(1, 0)])

        assert movie.bank_count() == 2

    def test_an_empty_stream_still_reports_one_bank(self):
        assert stream.MovieStream(bank_size=64).bank_count() == 1

    def test_the_default_bank_size_is_the_switchable_window(self):
        assert stream.PROM_BANK_BYTES == 1 << 20

    def test_offsets_stay_reachable_through_the_bank_window(self):
        movie = stream.MovieStream(bank_size=128)
        for _ in range(10):
            movie.append([update(0, 0), update(1, 0), update(2, 0)])

        for offset in movie.frame_offsets():
            assert int(offset) % 128 < 128


class TestPayloadSize:
    def test_payload_size_excludes_bank_padding(self):
        movie = stream.MovieStream(bank_size=64)
        movie.append([update(0, 0)])

        assert movie.payload_size() == len(stream.pack_frame([update(0, 0)]))

    def test_payload_size_counts_padding_inserted_between_records(self):
        movie = stream.MovieStream(bank_size=64)
        movie.append([update(0, 0)])
        movie.append([update(c, 0) for c in range(7)])

        assert movie.payload_size() == 64 + 2 + 7 * 8
