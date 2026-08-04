from __future__ import annotations

import subprocess

import pytest

from aesmovie import content


@pytest.fixture(scope="module")
def clean_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("clean") / "clean.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def grey_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("grey") / "grey.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25:duration=2",
            "-vf",
            "hue=s=0",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


class TestSaturation:
    def test_a_grey_source_measures_less_saturated_than_a_colour_one(self, clean_clip, grey_clip):
        assert content.measure(grey_clip, duration=2.0).saturation < (
            content.measure(clean_clip, duration=2.0).saturation
        )

    def test_saturation_is_never_negative(self, grey_clip):
        assert content.measure(grey_clip, duration=2.0).saturation >= 0.0


class TestSceneCuts:
    def test_a_still_source_reports_almost_no_cuts(self, clean_clip):
        assert content.measure(clean_clip, duration=2.0).cuts_per_minute < 30.0

    def test_a_source_of_alternating_scenes_reports_cuts(self, tmp_path):
        path = tmp_path / "cuts.mkv"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:size=320x224:rate=25:duration=1",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:size=320x224:rate=25:duration=1",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:size=320x224:rate=25:duration=1",
                "-filter_complex",
                "[0:v][1:v][2:v]concat=n=3:v=1:a=0",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
        )

        assert content.measure(path, duration=3.0).cuts_per_minute > 20.0


class TestEpochCadence:
    def test_frequent_cuts_ask_for_shorter_epochs(self):
        busy = content.epoch_seconds_for(cuts_per_minute=60.0)
        calm = content.epoch_seconds_for(cuts_per_minute=2.0)

        assert busy < calm

    def test_the_cadence_stays_inside_its_bounds(self):
        assert content.epoch_seconds_for(cuts_per_minute=10_000.0) >= content.MIN_EPOCH_SECONDS
        assert content.epoch_seconds_for(cuts_per_minute=0.0) <= content.MAX_EPOCH_SECONDS

    def test_a_source_with_no_cuts_still_gets_a_cadence(self):
        assert content.epoch_seconds_for(cuts_per_minute=0.0) > 0.0
