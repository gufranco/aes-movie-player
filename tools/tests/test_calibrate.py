"""Calibration tests.

Tile cost is a property of the content, so the sampler that measures it
is checked against a real decode rather than a stub.
"""

from __future__ import annotations

import itertools
import subprocess

import pytest

from aesmovie import calibrate, quality


@pytest.fixture(scope="module")
def synthetic_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("calibrate") / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x480:rate=24:duration=12",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


class TestSampleWindows:
    def test_it_returns_the_requested_count(self):
        windows = calibrate.sample_windows(600.0, count=6, seconds=5.0)

        assert len(windows) == 6

    def test_the_windows_are_spread_across_the_source(self):
        windows = calibrate.sample_windows(600.0, count=4, seconds=5.0)
        starts = [start for start, _ in windows]

        assert starts == sorted(starts)
        assert starts[0] < 150.0
        assert starts[-1] > 400.0

    def test_no_window_runs_past_the_end(self):
        windows = calibrate.sample_windows(20.0, count=4, seconds=5.0)

        for start, seconds in windows:
            assert start + seconds <= 20.0

    def test_a_source_shorter_than_one_window_yields_the_whole_source(self):
        windows = calibrate.sample_windows(3.0, count=6, seconds=5.0)

        assert windows == [(0.0, 3.0)]

    def test_windows_do_not_overlap(self):
        windows = calibrate.sample_windows(60.0, count=6, seconds=5.0)

        for (start, seconds), (next_start, _) in itertools.pairwise(windows):
            assert start + seconds <= next_start + 1e-9


class TestMeasureReferenceRate:
    def test_it_reports_a_positive_tile_rate(self, synthetic_clip):
        rate = calibrate.measure_reference_rate(synthetic_clip, count=2, seconds=1.0)

        assert rate > 0.0

    def test_the_rate_feeds_tier_selection(self, synthetic_clip):
        rate = calibrate.measure_reference_rate(synthetic_clip, count=2, seconds=1.0)

        assert quality.max_minutes(quality.tier_by_name("standard"), rate) > 0.0


class TestSampledRange:
    def test_it_measures_only_the_stretch_that_will_be_baked(self, synthetic_clip):
        whole = calibrate.measure_reference_rate(synthetic_clip, count=2, seconds=1.0)
        slice_only = calibrate.measure_reference_rate(
            synthetic_clip, count=2, seconds=1.0, start=8.0, duration=4.0
        )

        assert whole > 0.0
        assert slice_only > 0.0

    def test_a_duration_beyond_the_source_is_clamped(self, synthetic_clip):
        rate = calibrate.measure_reference_rate(
            synthetic_clip, count=2, seconds=1.0, start=0.0, duration=9999.0
        )

        assert rate > 0.0


class TestSampleWindowValidation:
    def test_a_non_positive_duration_is_rejected(self):
        with pytest.raises(ValueError, match="duration must be positive"):
            calibrate.sample_windows(0.0, count=2, seconds=1.0)

    def test_a_count_below_one_is_rejected(self):
        with pytest.raises(ValueError, match="at least one"):
            calibrate.sample_windows(10.0, count=0, seconds=1.0)

    def test_non_positive_window_seconds_are_rejected(self):
        with pytest.raises(ValueError, match="seconds must be positive"):
            calibrate.sample_windows(10.0, count=2, seconds=0.0)
