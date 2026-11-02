from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from neogeomedia import encode
from tests.encodehelp import (
    HEIGHT,
    SLOT_COUNT,
    WIDTH,
    filler_colour,
    flat_clip,
    noise_clip,
    options,
)

BASE_TOLERANCE = 0.0005
DRIFT_TOLERANCE = 0.02
ROOMY_BUDGET = 1 << 20
CEILING = 100


def smooth_drift(count: int) -> np.ndarray:
    x = np.arange(WIDTH, dtype=np.float32)[None, :]
    y = np.arange(HEIGHT, dtype=np.float32)[:, None]
    clip = np.zeros((count, HEIGHT, WIDTH, 3), dtype=np.uint8)
    for index in range(count):
        base = x * 0.35 + y * 0.25 + index * 1.1
        clip[index, :, :, 0] = np.clip(90 + 40 * np.sin(base / 23.0), 0, 255)
        clip[index, :, :, 1] = np.clip(110 + 40 * np.sin(base / 31.0 + 1.0), 0, 255)
        clip[index, :, :, 2] = np.clip(130 + 40 * np.sin(base / 41.0 + 2.0), 0, 255)
    return clip


def drift_settings(**extra: Any) -> encode.EncodeOptions:
    return options(palette_count=8, keyframe_interval=1000, tolerance=DRIFT_TOLERANCE, **extra)


@pytest.fixture(scope="module")
def unheld() -> encode.EncodeResult:
    return encode.encode(noise_clip(12), options())


@pytest.fixture(scope="module")
def unbudgeted_short() -> encode.EncodeResult:
    return encode.encode(noise_clip(6), options())


@pytest.fixture(scope="module")
def unbudgeted_long() -> encode.EncodeResult:
    return encode.encode(noise_clip(10), options(keyframe_interval=1000))


@pytest.fixture(scope="module")
def unbudgeted_drift() -> encode.EncodeResult:
    return encode.encode(smooth_drift(60), drift_settings(tile_budget=0))


class TestDictionaryCeiling:
    def test_a_full_dictionary_is_reported_without_failing_the_bake(self):
        # Arrange
        clip = noise_clip(4)

        # Act
        result = encode.encode(clip, options(palette_count=8, dictionary_capacity=CEILING))

        # Assert
        assert result.stats.frames == 4
        assert result.stats.dictionary_full is True
        assert len(result.dictionary) <= CEILING

    def test_slots_with_no_tile_keep_showing_the_previous_one(self):
        # Arrange
        clip = noise_clip(3)

        # Act
        result = encode.encode(clip, options(palette_count=8, dictionary_capacity=60))

        # Assert
        assert result.updates_per_frame[2] < SLOT_COUNT

    def test_a_bake_told_to_stop_ends_when_the_dictionary_fills(self):
        # Arrange
        clip = noise_clip(6)
        settings = options(palette_count=8, dictionary_capacity=CEILING, stop_when_over_budget=True)

        # Act
        result = encode.encode(clip, settings)

        # Assert
        assert (result.stats.truncated, result.stats.dictionary_full) == (True, True)

    def test_an_unfilled_dictionary_reports_room_left(self):
        # Arrange
        clip = flat_clip(3, filler_colour())

        # Act
        result = encode.encode(clip, options())

        # Assert
        assert result.stats.dictionary_full is False


class TestFrameHold:
    def test_holding_frames_keeps_the_frame_count_and_shrinks_the_dictionary(self, unheld):
        # Arrange
        clip = noise_clip(12)

        # Act
        result = encode.encode(clip, options(frame_hold=3))

        # Assert
        assert result.stats.frames == 12
        assert len(result.dictionary) < len(unheld.dictionary)

    @pytest.mark.parametrize("hold", [1, 0], ids=["a hold of one", "a zero hold"])
    def test_a_hold_of_one_or_less_changes_nothing(self, unheld, hold):
        # Arrange
        clip = noise_clip(12)

        # Act
        result = encode.encode(clip, options(frame_hold=hold))

        # Assert
        assert len(result.dictionary) == len(unheld.dictionary)

    def test_held_frames_repeat_the_picture(self):
        # Arrange
        clip = noise_clip(9)

        # Act
        result = encode.encode(clip, options(frame_hold=3, keyframe_interval=100))

        # Assert
        assert result.updates_per_frame[1] == 0
        assert result.updates_per_frame[2] == 0


class TestRateControl:
    @pytest.mark.parametrize("budget", [0, ROOMY_BUDGET], ids=["no budget", "a generous budget"])
    def test_a_budget_it_never_reaches_leaves_the_encode_untouched(self, unbudgeted_short, budget):
        # Arrange
        clip = noise_clip(6)

        # Act
        result = encode.encode(clip, options(tile_budget=budget))

        # Assert
        assert len(result.dictionary) == len(unbudgeted_short.dictionary)
        assert result.stats.peak_tolerance <= BASE_TOLERANCE

    def test_a_tight_budget_is_respected_by_raising_the_tolerance(self, unbudgeted_long):
        # Arrange
        budget = len(unbudgeted_long.dictionary) // 2

        # Act
        result = encode.encode(noise_clip(10), options(keyframe_interval=1000, tile_budget=budget))

        # Assert
        assert len(result.dictionary) <= budget
        assert result.stats.peak_tolerance > BASE_TOLERANCE

    def test_a_budget_it_cannot_meet_is_reported(self):
        # Arrange
        clip = noise_clip(10)

        # Act
        result = encode.encode(clip, options(keyframe_interval=1, tile_budget=10))

        # Assert
        assert result.stats.budget_exceeded is True


class TestBudgetIsNotOverspent:
    def test_a_roomy_budget_changes_nothing(self, unbudgeted_drift):
        # Arrange
        budget = len(unbudgeted_drift.dictionary) * 8

        # Act
        result = encode.encode(smooth_drift(60), drift_settings(tile_budget=budget))

        # Assert
        assert len(result.dictionary) == len(unbudgeted_drift.dictionary)

    def test_the_threshold_is_never_finer_than_the_tier_asked(self):
        # Arrange
        clip = smooth_drift(60)

        # Act
        result = encode.encode(clip, drift_settings(tile_budget=ROOMY_BUDGET))

        # Assert
        assert result.stats.peak_tolerance >= DRIFT_TOLERANCE
