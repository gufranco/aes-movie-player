from __future__ import annotations

import itertools

import pytest

from neogeomedia import calibrate, quality
from tests.bakehelp import lavfi_clip

pytestmark = pytest.mark.ffmpeg

BUSY_OVER_BLACK = 10.0


@pytest.fixture(scope="module")
def synthetic_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("calibrate") / "source.mp4"
    return lavfi_clip(path, "testsrc=size=640x480:rate=24:duration=12")


@pytest.fixture(scope="module")
def half_black_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("calibrate") / "half-black.mp4"
    chain = (
        "testsrc=size=640x480:rate=24:duration=12,"
        "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='lt(t,8)'"
    )
    return lavfi_clip(path, chain)


class TestSampleWindows:
    def test_it_returns_the_requested_count(self):
        # Arrange
        duration = 600.0

        # Act
        windows = calibrate.sample_windows(duration, count=6, seconds=5.0)

        # Assert
        assert len(windows) == 6

    def test_the_windows_are_spread_across_the_source(self):
        # Arrange
        duration = 600.0

        # Act
        windows = calibrate.sample_windows(duration, count=4, seconds=5.0)

        # Assert
        assert [start for start, _ in windows] == [72.5, 222.5, 372.5, 522.5]

    def test_no_window_runs_past_the_end(self):
        # Arrange
        duration = 20.0

        # Act
        windows = calibrate.sample_windows(duration, count=4, seconds=5.0)

        # Assert
        assert windows == [(0.0, 5.0), (5.0, 5.0), (10.0, 5.0), (15.0, 5.0)]
        assert all(start + seconds <= duration for start, seconds in windows)

    def test_a_source_shorter_than_one_window_yields_the_whole_source(self):
        # Arrange
        duration = 3.0

        # Act
        windows = calibrate.sample_windows(duration, count=6, seconds=5.0)

        # Assert
        assert windows == [(0.0, 3.0)]

    def test_windows_do_not_overlap(self):
        # Arrange
        duration = 60.0

        # Act
        windows = calibrate.sample_windows(duration, count=6, seconds=5.0)

        # Assert
        assert [start for start, _ in windows] == [2.5, 12.5, 22.5, 32.5, 42.5, 52.5]
        assert all(
            start + seconds <= next_start + 1e-9
            for (start, seconds), (next_start, _) in itertools.pairwise(windows)
        )


class TestMeasureReferenceRate:
    def test_it_reports_a_positive_tile_rate(self, synthetic_clip):
        # Arrange
        source = synthetic_clip

        # Act
        rate = calibrate.measure_reference_rate(source, count=2, seconds=1.0, dither=0.0)

        # Assert
        assert rate > 0.0

    def test_the_rate_feeds_tier_selection(self, synthetic_clip):
        # Arrange
        rate = calibrate.measure_reference_rate(synthetic_clip, count=2, seconds=1.0, dither=0.0)
        tier = quality.tier_by_name("standard")

        # Act
        minutes = quality.max_minutes(tier, rate)

        # Assert
        assert minutes > 0.0


class TestSampledRange:
    def test_it_measures_only_the_stretch_that_will_be_baked(self, half_black_clip):
        # Arrange
        black = calibrate.measure_reference_rate(
            half_black_clip, count=2, seconds=1.0, dither=0.0, start=0.0, duration=8.0
        )

        # Act
        busy = calibrate.measure_reference_rate(
            half_black_clip, count=2, seconds=1.0, dither=0.0, start=8.0, duration=4.0
        )

        # Assert
        assert busy > BUSY_OVER_BLACK * black

    def test_a_duration_beyond_the_source_is_clamped(self, synthetic_clip):
        # Arrange
        source = synthetic_clip

        # Act
        rate = calibrate.measure_reference_rate(
            source, count=2, seconds=1.0, dither=0.0, start=0.0, duration=9999.0
        )

        # Assert
        assert rate > 0.0


class TestSampleWindowValidation:
    @pytest.mark.parametrize(
        ("duration", "count", "seconds", "message"),
        [
            (0.0, 2, 1.0, "duration must be positive, got 0.0"),
            (10.0, 0, 1.0, "sample count must be at least one, got 0"),
            (10.0, 2, 0.0, "sample seconds must be positive, got 0.0"),
        ],
        ids=["duration", "count", "seconds"],
    )
    def test_an_impossible_request_is_rejected(self, duration, count, seconds, message):
        # Arrange
        request = {"count": count, "seconds": seconds}

        # Act
        with pytest.raises(ValueError) as raised:
            calibrate.sample_windows(duration, **request)

        # Assert
        assert str(raised.value) == message
