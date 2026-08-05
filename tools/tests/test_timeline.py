"""Exercise the player's pure core as compiled C, not as a reimplementation.

`src/timeline.c` holds every lookup and every piece of arithmetic the
68000 player does that has no hardware in it: which keyframe a seek
lands on, which cue covers a frame, which ADPCM page the audio wants,
how far along the seek bar sits. A mistake in any of them is silent,
because the picture still appears and only the wrong part of it does.

These build the real translation unit with the host compiler and call
into it, so what is under test is the code that ships rather than a
Python copy of it that could drift.
"""

from __future__ import annotations

import ctypes
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "fmv" / "timeline.c"
FPS_NUM = 24
FPS_DEN = 1
SUBTITLE_STRIDE = 8 + 40 * 2


@pytest.fixture(scope="session")
def timeline(tmp_path_factory):
    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if compiler is None:
        pytest.skip("no host C compiler")
    library = tmp_path_factory.mktemp("timeline") / "libtimeline.so"
    subprocess.run(
        [
            compiler,
            "-std=c99",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-shared",
            "-fPIC",
            str(SOURCE),
            "-o",
            str(library),
        ],
        check=True,
    )
    loaded = ctypes.CDLL(str(library))
    loaded.timeline_clamp_frame.restype = ctypes.c_uint32
    loaded.timeline_keyframe_at_or_before.restype = ctypes.c_uint32
    loaded.timeline_subtitle_at.restype = ctypes.c_uint16
    loaded.timeline_seconds_to_frames.restype = ctypes.c_uint32
    loaded.timeline_frame_to_seconds.restype = ctypes.c_uint32
    loaded.timeline_audio_page.restype = ctypes.c_uint16
    loaded.timeline_bar_fill.restype = ctypes.c_uint16
    return loaded


def keyframe_table(frames):
    array = (ctypes.c_uint32 * len(frames))(*frames)
    return array, len(frames)


def cue_table(cues):
    blob = bytearray()
    for start, end in cues:
        blob += struct.pack(">II", start, end)
        blob += bytes(SUBTITLE_STRIDE - 8)
    return (ctypes.c_ubyte * len(blob)).from_buffer(blob), len(cues)


class TestSeekingLandsOnAKeyframe:
    def test_a_frame_between_keyframes_lands_on_the_one_before_it(self, timeline):
        table, count = keyframe_table([0, 90, 180, 270])

        assert timeline.timeline_keyframe_at_or_before(table, count, 200) == 180

    def test_a_frame_exactly_on_a_keyframe_lands_on_it(self, timeline):
        table, count = keyframe_table([0, 90, 180, 270])

        assert timeline.timeline_keyframe_at_or_before(table, count, 180) == 180

    def test_a_frame_before_the_first_keyframe_lands_on_the_first(self, timeline):
        table, count = keyframe_table([10, 90, 180])

        assert timeline.timeline_keyframe_at_or_before(table, count, 0) == 10

    def test_a_frame_past_the_last_keyframe_lands_on_the_last(self, timeline):
        table, count = keyframe_table([0, 90, 180])

        assert timeline.timeline_keyframe_at_or_before(table, count, 10_000) == 180

    def test_every_frame_in_a_span_lands_on_the_same_keyframe(self, timeline):
        table, count = keyframe_table([0, 90, 180, 270])

        landings = {
            timeline.timeline_keyframe_at_or_before(table, count, f) for f in range(90, 180)
        }

        assert landings == {90}

    def test_an_empty_table_does_not_read_off_the_end(self, timeline):
        table, _ = keyframe_table([0])

        assert timeline.timeline_keyframe_at_or_before(table, 0, 500) == 0


class TestClampingASeek:
    def test_a_target_past_the_end_lands_on_the_last_frame(self, timeline):
        assert timeline.timeline_clamp_frame(5_000, 1_000) == 999

    def test_a_target_inside_the_film_is_left_alone(self, timeline):
        assert timeline.timeline_clamp_frame(400, 1_000) == 400

    def test_the_last_frame_is_reachable(self, timeline):
        assert timeline.timeline_clamp_frame(999, 1_000) == 999

    def test_an_empty_film_does_not_wrap_around(self, timeline):
        assert timeline.timeline_clamp_frame(0, 0) == 0


class TestWhichCueIsShowing:
    def test_a_frame_inside_a_cue_finds_it(self, timeline):
        table, count = cue_table([(0, 50), (100, 150), (200, 250)])

        assert timeline.timeline_subtitle_at(table, count, SUBTITLE_STRIDE, 120) == 1

    def test_a_frame_in_the_gap_between_cues_finds_nothing(self, timeline):
        table, count = cue_table([(0, 50), (100, 150)])

        assert timeline.timeline_subtitle_at(table, count, SUBTITLE_STRIDE, 75) == count

    def test_a_cue_starts_on_its_first_frame(self, timeline):
        table, count = cue_table([(100, 150)])

        assert timeline.timeline_subtitle_at(table, count, SUBTITLE_STRIDE, 100) == 0

    def test_a_cue_is_gone_on_its_end_frame(self, timeline):
        table, count = cue_table([(100, 150)])

        assert timeline.timeline_subtitle_at(table, count, SUBTITLE_STRIDE, 150) == count

    def test_a_frame_before_every_cue_finds_nothing(self, timeline):
        table, count = cue_table([(100, 150)])

        assert timeline.timeline_subtitle_at(table, count, SUBTITLE_STRIDE, 10) == count

    def test_a_frame_after_every_cue_finds_nothing(self, timeline):
        table, count = cue_table([(100, 150)])

        assert timeline.timeline_subtitle_at(table, count, SUBTITLE_STRIDE, 9_999) == count

    def test_back_to_back_cues_never_leave_a_hole(self, timeline):
        table, count = cue_table([(0, 100), (100, 200)])

        showing = [
            timeline.timeline_subtitle_at(table, count, SUBTITLE_STRIDE, f) for f in range(200)
        ]

        assert set(showing[:100]) == {0}
        assert set(showing[100:]) == {1}

    def test_a_film_with_no_cues_finds_nothing(self, timeline):
        table, _ = cue_table([(0, 100)])

        assert timeline.timeline_subtitle_at(table, 0, SUBTITLE_STRIDE, 50) == 0


class TestTheClockAndTheBar:
    def test_a_second_of_frames_reads_as_a_second(self, timeline):
        assert timeline.timeline_frame_to_seconds(FPS_NUM, FPS_NUM, FPS_DEN) == 1

    def test_seconds_and_frames_round_trip(self, timeline):
        frames = timeline.timeline_seconds_to_frames(93, FPS_NUM, FPS_DEN)

        assert timeline.timeline_frame_to_seconds(frames, FPS_NUM, FPS_DEN) == 93

    def test_a_long_film_does_not_overflow_the_clock(self, timeline):
        frames = timeline.timeline_seconds_to_frames(10_000, FPS_NUM, FPS_DEN)

        assert frames == 240_000
        assert timeline.timeline_frame_to_seconds(frames, FPS_NUM, FPS_DEN) == 10_000

    def test_the_bar_starts_empty(self, timeline):
        assert timeline.timeline_bar_fill(0, 1_000, 26) == 0

    def test_the_bar_ends_full(self, timeline):
        assert timeline.timeline_bar_fill(999, 1_000, 26) == 26

    def test_the_bar_never_runs_past_its_end(self, timeline):
        assert timeline.timeline_bar_fill(5_000, 1_000, 26) == 26

    def test_the_bar_only_ever_moves_forward(self, timeline):
        seen = [timeline.timeline_bar_fill(f, 1_000, 26) for f in range(1_000)]

        assert seen == sorted(seen)

    def test_a_single_frame_film_does_not_divide_by_zero(self, timeline):
        assert timeline.timeline_bar_fill(0, 1, 26) == 0


class TestWhichAudioPage:
    def test_the_first_frame_starts_at_the_first_page(self, timeline):
        assert timeline.timeline_audio_page(0, 1, 100) == 0

    def test_pages_advance_with_the_film(self, timeline):
        early = timeline.timeline_audio_page(1_000, 3, 100)
        late = timeline.timeline_audio_page(2_000, 3, 100)

        assert late > early

    def test_it_rounds_to_the_nearest_page_rather_than_down(self, timeline):
        assert timeline.timeline_audio_page(1, 1, 2) == 1

    def test_a_film_long_enough_to_overflow_32_bits_still_scales(self, timeline):
        assert timeline.timeline_audio_page(1_000_000, 4_000, 1_000_000) == 4_000

    def test_a_silent_film_asks_for_no_page(self, timeline):
        assert timeline.timeline_audio_page(5_000, 0, 100) == 0
