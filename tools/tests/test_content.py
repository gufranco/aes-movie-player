from __future__ import annotations

import pytest

from neogeomedia import content
from tests.bakehelp import lavfi_clip

pytestmark = pytest.mark.ffmpeg

COLOUR_BARS = "testsrc=size=640x360:rate=25:duration=2"
MOVING = "testsrc=size=320x224:rate=25:duration=2"
STILL_RED = "color=c=red:size=320x224:rate=25:duration=2"
STILL_BLACK = "color=c=black:size=320x224:rate=25:duration=1"
SCENES = tuple(
    f"color=c={name}:size=320x224:rate=25:duration=1" for name in ("red", "blue", "green")
)


@pytest.fixture(scope="module")
def clean_clip(tmp_path_factory):
    return lavfi_clip(tmp_path_factory.mktemp("clean") / "clean.mkv", COLOUR_BARS)


@pytest.fixture(scope="module")
def grey_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("grey") / "grey.mkv"
    return lavfi_clip(path, COLOUR_BARS, extra=("-vf", "hue=s=0"))


@pytest.fixture(scope="module")
def still_clip(tmp_path_factory):
    return lavfi_clip(tmp_path_factory.mktemp("still") / "still.mkv", STILL_RED)


class TestSaturation:
    def test_a_grey_source_measures_less_saturated_than_a_colour_one(self, clean_clip, grey_clip):
        # Arrange
        colour = content.measure(clean_clip, duration=2.0).saturation

        # Act
        grey = content.measure(grey_clip, duration=2.0)

        # Assert
        assert grey.saturation < colour

    def test_saturation_is_never_negative(self, grey_clip):
        # Arrange
        path = grey_clip

        # Act
        profile = content.measure(path, duration=2.0)

        # Assert
        assert profile.saturation >= 0.0


class TestSceneCuts:
    def test_a_still_source_reports_almost_no_cuts(self, clean_clip):
        # Arrange
        path = clean_clip

        # Act
        profile = content.measure(path, duration=2.0)

        # Assert
        assert profile.cuts_per_minute < 30.0

    def test_a_source_of_alternating_scenes_reports_cuts(self, tmp_path):
        # Arrange
        joined = ("-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0")
        path = lavfi_clip(tmp_path / "cuts.mkv", *SCENES, extra=joined)

        # Act
        profile = content.measure(path, duration=3.0)

        # Assert
        assert profile.cuts_per_minute > 20.0


class TestEpochCadence:
    def test_frequent_cuts_ask_for_shorter_epochs(self):
        # Arrange
        calm = content.epoch_seconds_for(cuts_per_minute=2.0)

        # Act
        busy = content.epoch_seconds_for(cuts_per_minute=60.0)

        # Assert
        assert busy < calm

    def test_a_flood_of_cuts_is_held_at_the_shortest_epoch(self):
        # Arrange
        cuts_per_minute = 10_000.0

        # Act
        seconds = content.epoch_seconds_for(cuts_per_minute=cuts_per_minute)

        # Assert
        assert seconds == 2.5

    def test_a_source_with_no_cuts_gets_the_longest_cadence(self):
        # Arrange
        cuts_per_minute = 0.0

        # Act
        seconds = content.epoch_seconds_for(cuts_per_minute=cuts_per_minute)

        # Assert
        assert seconds == 8.0

    def test_a_moderate_cut_rate_gets_one_epoch_per_cut(self):
        # Arrange
        cuts_per_minute = 12.0

        # Act
        seconds = content.epoch_seconds_for(cuts_per_minute=cuts_per_minute)

        # Assert
        assert seconds == 5.0


class TestMovementFloor:
    def test_a_single_frame_asks_for_the_minimum_floor(self, still_clip):
        # Arrange
        one_field = 0.02

        # Act
        floor = content.movement_floor(still_clip, duration=one_field)

        # Assert
        assert floor == content.MOVEMENT_FLOOR_MINIMUM

    def test_a_still_source_asks_for_a_low_floor(self, still_clip):
        # Arrange
        path = still_clip

        # Act
        floor = content.movement_floor(path, duration=2.0)

        # Assert
        assert floor < 0.001

    def test_a_moving_source_asks_for_a_higher_floor(self, still_clip, tmp_path):
        # Arrange
        moving = lavfi_clip(tmp_path / "moving.mkv", MOVING)
        still = content.movement_floor(still_clip, duration=2.0)

        # Act
        floor = content.movement_floor(moving, duration=2.0)

        # Assert
        assert floor > still

    def test_the_floor_is_never_zero(self, tmp_path):
        # Arrange
        flat = lavfi_clip(tmp_path / "flat.mkv", STILL_BLACK)

        # Act
        floor = content.movement_floor(flat, duration=1.0)

        # Assert
        assert floor == 1e-6
