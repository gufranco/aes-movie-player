from __future__ import annotations

import pytest

from aesmovie import fixtiles, subtitles

SAMPLE = """1
00:00:01,000 --> 00:00:03,500
Hello there

2
00:00:04,000 --> 00:00:06,000
A second line
and its continuation
"""


class TestParsingCues:
    def test_it_reads_every_cue(self):
        cues = subtitles.parse(SAMPLE)

        assert len(cues) == 2

    def test_timings_are_read_in_seconds(self):
        first = subtitles.parse(SAMPLE)[0]

        assert first.start == pytest.approx(1.0)
        assert first.end == pytest.approx(3.5)

    def test_multiple_text_lines_are_kept_separate(self):
        second = subtitles.parse(SAMPLE)[1]

        assert second.lines == ("A second line", "and its continuation")

    def test_markup_is_stripped(self):
        cues = subtitles.parse("1\n00:00:00,000 --> 00:00:01,000\n<i>Slanted</i>\n")

        assert cues[0].lines == ("Slanted",)

    def test_an_empty_file_has_no_cues(self):
        assert subtitles.parse("") == []

    def test_a_cue_with_no_text_is_dropped(self):
        assert subtitles.parse("1\n00:00:00,000 --> 00:00:01,000\n\n") == []


class TestLayout:
    def test_a_long_line_is_wrapped_to_the_raster(self):
        laid = subtitles.layout(("word " * 20).strip())

        assert all(len(line) <= subtitles.COLUMNS for line in laid)

    def test_wrapping_never_splits_a_word(self):
        laid = subtitles.layout("antidisestablishmentarian words here")

        assert "antidisestablishmentarian" in laid[0]

    def test_it_keeps_at_most_the_lines_that_fit(self):
        laid = subtitles.layout(("word " * 60).strip())

        assert len(laid) <= subtitles.MAX_LINES

    def test_a_word_longer_than_the_raster_is_cut_rather_than_lost(self):
        laid = subtitles.layout("x" * 60)

        assert laid[0] == "x" * subtitles.COLUMNS


class TestEncoding:
    def test_each_cue_becomes_one_fixed_size_record(self):
        cues = subtitles.parse(SAMPLE)

        blob = subtitles.encode(cues, fps=60.0)

        assert len(blob) == len(cues) * subtitles.RECORD_BYTES

    def test_frames_come_from_the_timings_and_the_rate(self):
        cues = subtitles.parse(SAMPLE)

        start, end = subtitles.frame_span(cues[0], fps=60.0)

        assert start == 60
        assert end == 210

    def test_text_is_stored_as_glyph_indices(self):
        cues = subtitles.parse("1\n00:00:00,000 --> 00:00:01,000\nA\n")

        blob = subtitles.encode(cues, fps=60.0)
        row = blob[8 : 8 + subtitles.COLUMNS]

        assert fixtiles.GLYPHS["A"] in row

    def test_lowercase_keeps_its_own_shape_rather_than_folding_to_capitals(self):
        cues = subtitles.parse("1\n00:00:00,000 --> 00:00:01,000\nag\n")

        row = subtitles.encode(cues, fps=60.0)[8 : 8 + subtitles.COLUMNS]

        assert fixtiles.GLYPHS["a"] in row
        assert fixtiles.GLYPHS["g"] in row
        assert fixtiles.GLYPHS["A"] not in row

    def test_an_unknown_character_becomes_a_blank(self):
        cues = subtitles.parse("1\n00:00:00,000 --> 00:00:01,000\n§\n")

        row = subtitles.encode(cues, fps=60.0)[8 : 8 + subtitles.COLUMNS]

        assert set(row) == {fixtiles.GLYPHS["blank"]}

    def test_lines_are_centred(self):
        cues = subtitles.parse("1\n00:00:00,000 --> 00:00:01,000\nAB\n")

        row = subtitles.encode(cues, fps=60.0)[8 : 8 + subtitles.COLUMNS]
        first = next(index for index, value in enumerate(row) if value != fixtiles.GLYPHS["blank"])

        assert first == (subtitles.COLUMNS - 2) // 2

    def test_records_are_ordered_by_start_frame(self):
        cues = subtitles.parse(SAMPLE)[::-1]

        blob = subtitles.encode(cues, fps=60.0)
        starts = [
            int.from_bytes(blob[index * subtitles.RECORD_BYTES :][:4], "big")
            for index in range(len(cues))
        ]

        assert starts == sorted(starts)

    def test_overlapping_cues_are_trimmed_so_one_shows_at_a_time(self):
        overlapping = subtitles.parse(
            "1\n00:00:00,000 --> 00:00:05,000\nfirst\n\n2\n00:00:02,000 --> 00:00:06,000\nsecond\n"
        )

        blob = subtitles.encode(overlapping, fps=60.0)
        first_end = int.from_bytes(blob[4:8], "big")
        second_start = int.from_bytes(blob[subtitles.RECORD_BYTES :][:4], "big")

        assert first_end <= second_start


class TestFindingTheSidecar:
    def test_it_finds_a_file_beside_the_source(self, tmp_path):
        source = tmp_path / "film.mkv"
        source.write_bytes(b"")
        sidecar = tmp_path / "film.srt"
        sidecar.write_text(SAMPLE)

        assert subtitles.sidecar_for(source) == sidecar

    def test_a_source_with_no_sidecar_reports_none(self, tmp_path):
        source = tmp_path / "film.mkv"
        source.write_bytes(b"")

        assert subtitles.sidecar_for(source) is None
