from __future__ import annotations

import pytest

from neogeomedia import encode, ratecontrol

BASE = 0.001


def controller(**overrides):
    options = encode.EncodeOptions(tolerance=BASE, **overrides)
    return ratecontrol.RateController(options)


class TestRateController:
    def test_no_budget_keeps_the_tier_threshold(self):
        # Arrange
        pacer = controller(tile_budget=0)

        # Act
        tolerance = pacer.tolerance(10_000, 5, 100)

        # Assert
        assert tolerance == BASE

    def test_overspending_raises_the_threshold_by_at_most_the_ramp(self):
        # Arrange
        pacer = controller(tile_budget=1_000)

        # Act
        tolerance = pacer.tolerance(500, 1, 100)

        # Assert
        assert tolerance == pytest.approx(BASE * 1.25)

    def test_a_spent_budget_jumps_straight_to_the_ceiling(self):
        # Arrange
        pacer = controller(tile_budget=1_000, max_tolerance_scale=64.0)

        # Act
        tolerance = pacer.tolerance(1_000, 1, 100)

        # Assert
        assert tolerance == pytest.approx(BASE * 64.0)

    def test_underspending_never_drops_below_the_tier_threshold(self):
        # Arrange
        pacer = controller(tile_budget=1_000_000)

        # Act
        tolerance = pacer.tolerance(0, 1, 100)

        # Assert
        assert tolerance == BASE

    def test_spending_just_under_what_is_affordable_leaves_the_threshold_alone(self):
        # Arrange
        pacer = controller(tile_budget=610)

        # Act
        tolerance = pacer.tolerance(100, 0, 100)

        # Assert
        assert tolerance == BASE

    def test_past_the_last_frame_the_current_scale_holds(self):
        # Arrange
        pacer = controller(tile_budget=1_000, max_tolerance_scale=64.0)
        pacer.tolerance(1_000, 1, 100)

        # Act
        tolerance = pacer.tolerance(1_000, 100, 100)

        # Assert
        assert tolerance == pytest.approx(BASE * 64.0)
