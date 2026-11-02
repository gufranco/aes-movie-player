from __future__ import annotations

import itertools

import numpy as np
import pytest
from fmvcore.testing import SEED, seeded

from neogeomedia import ladder
from tests.bakehelp import SYNTHETIC_FILM

FLAT_FRAMES = 4
FLAT_COST_PER_MINUTE = 887.784090909
SWEEP_CHROMA = [
    1.0, 0.94, 0.89, 0.84, 0.79, 0.74, 0.70, 0.66, 0.62, 0.58,
    0.54, 0.51, 0.48, 0.45, 0.42, 0.39, 0.37, 0.34, 0.31, 0.28,
    0.26, 0.24, 0.22, 0.20, 0.18, 0.16, 0.14, 0.12, 0.10, 0.08,
]  # fmt: skip


def point(cost: float, error: float, chroma: float = 1.0, hold: int = 1) -> ladder.Point:
    return ladder.Point(
        chroma_weight=chroma,
        tolerance=seeded().pyfloat(min_value=0.0005, max_value=0.012),
        frame_hold=hold,
        cost=cost,
        error=error,
    )


def descending(count: int) -> list[ladder.Point]:
    return [point(2.0 * 0.9**step, 0.01 * 1.1**step) for step in range(count)]


def flat_clip() -> np.ndarray:
    grey = int(np.random.default_rng(SEED).integers(0, 256))
    return np.full((FLAT_FRAMES, 224, 320, 3), grey, dtype=np.uint8)


class TestTheFrontier:
    def test_a_point_beaten_on_both_axes_is_dropped(self):
        # Arrange
        good = point(1.0, 0.10)
        beaten = point(1.5, 0.20)

        # Act
        kept = ladder.frontier([good, beaten])

        # Assert
        assert kept == [good]

    def test_a_point_that_wins_on_one_axis_survives(self):
        # Arrange
        cheap = point(0.5, 0.30)
        sharp = point(2.0, 0.05)

        # Act
        kept = ladder.frontier([cheap, sharp])

        # Assert
        assert kept == [sharp, cheap]

    def test_the_frontier_comes_back_cheapest_last(self):
        # Arrange
        points = [point(0.5, 0.3), point(2.0, 0.05), point(1.0, 0.1)]

        # Act
        kept = ladder.frontier(points)

        # Assert
        assert [entry.cost for entry in kept] == [2.0, 1.0, 0.5]

    def test_an_exact_duplicate_is_kept_once(self):
        # Arrange
        twin = point(1.0, 0.1)

        # Act
        kept = ladder.frontier([twin, twin])

        # Assert
        assert kept == [twin]

    def test_an_empty_sweep_has_an_empty_frontier(self):
        # Arrange
        points: list[ladder.Point] = []

        # Act
        kept = ladder.frontier(points)

        # Assert
        assert kept == []


class TestChoosingRungs:
    def test_it_returns_the_number_of_rungs_asked_for(self):
        # Arrange
        measured = ladder.frontier(descending(40))

        # Act
        chosen = ladder.choose(measured, count=12)

        # Assert
        assert len(chosen) == 12

    def test_the_extremes_are_always_kept(self):
        # Arrange
        kept = ladder.frontier(descending(40))

        # Act
        chosen = ladder.choose(kept, count=8)

        # Assert
        assert (chosen[0], chosen[-1]) == (kept[0], kept[-1])

    def test_a_crowd_does_not_swallow_every_rung(self):
        # Arrange
        crowded = [point(2.0 - step * 0.01, 0.01 + step * 0.001) for step in range(50)]
        measured = ladder.frontier([*crowded, point(0.5, 0.4)])

        # Act
        chosen = ladder.choose(measured, count=4)

        # Assert
        assert min(entry.cost for entry in chosen) == 0.5

    def test_asking_for_more_rungs_than_measured_returns_what_exists(self):
        # Arrange
        measured = ladder.frontier([point(2.0, 0.1), point(1.0, 0.2)])

        # Act
        chosen = ladder.choose(measured, count=10)

        # Assert
        assert chosen == measured

    def test_the_rungs_descend_in_cost(self):
        # Arrange
        measured = ladder.frontier(descending(40))

        # Act
        chosen = ladder.choose(measured, count=10)

        # Assert
        assert all(a.cost > b.cost for a, b in itertools.pairwise(chosen))


class TestRenderingTheLadder:
    def test_costs_are_relative_to_the_reference_rung(self):
        # Arrange
        chosen = [point(2.0, 0.05), point(1.0, 0.10), point(0.5, 0.30)]

        # Act
        rungs = ladder.to_tiers(chosen, reference_cost=1.0)

        # Assert
        assert [rung.relative_cost for rung in rungs] == [2.0, 1.0, 0.5]

    def test_every_rung_gets_a_distinct_name(self):
        # Arrange
        chosen = [point(2.0 - step * 0.1, 0.05 + step * 0.01) for step in range(12)]

        # Act
        rungs = ladder.to_tiers(chosen, reference_cost=1.0)

        # Assert
        assert len({rung.name for rung in rungs}) == 12

    def test_names_are_ordered_and_zero_padded(self):
        # Arrange
        chosen = [point(2.0, 0.05), point(1.0, 0.1)]

        # Act
        rungs = ladder.to_tiers(chosen, reference_cost=1.0)

        # Assert
        assert [rung.name for rung in rungs] == ["q01", "q02"]

    def test_only_the_top_rung_searches_every_palette(self):
        # Arrange
        chosen = [point(2.0, 0.05), point(1.0, 0.1)]

        # Act
        rungs = ladder.to_tiers(chosen, reference_cost=1.0)

        # Assert
        assert [rung.candidates for rung in rungs] == [0, 12]

    def test_a_held_rung_says_so_in_its_summary(self):
        # Arrange
        chosen = [point(0.5, 0.4, chroma=0.12, hold=3)]

        # Act
        rungs = ladder.to_tiers(chosen, reference_cost=1.0)

        # Assert
        assert rungs[0].summary == "20 fps, colour at 12%"

    def test_a_full_rate_rung_names_its_colour(self):
        # Arrange
        chosen = [point(1.0, 0.1, chroma=0.37, hold=1)]

        # Act
        rungs = ladder.to_tiers(chosen, reference_cost=1.0)

        # Assert
        assert rungs[0].summary == "every frame, colour at 37%"


class TestMeasuringOnePoint:
    def test_a_flat_clip_costs_one_tile_over_its_running_time(self):
        # Arrange
        clip = flat_clip()

        # Act
        measured = ladder.measure_point(
            clip, chroma_weight=0.37, tolerance=0.0018, frame_hold=2, seed=0, dither=0.0
        )

        # Assert
        assert measured.cost == pytest.approx(FLAT_COST_PER_MINUTE)
        assert measured.error == 0.0
        assert (measured.chroma_weight, measured.tolerance, measured.frame_hold) == (
            0.37,
            0.0018,
            2,
        )


class TestSweepingAFilm:
    @pytest.mark.ffmpeg
    def test_it_walks_every_colour_step_then_every_hold(self):
        # Arrange
        source = SYNTHETIC_FILM

        # Act
        points = ladder.sweep(source, count=1, seconds=0.05, dither=0.0)

        # Assert
        assert [entry.chroma_weight for entry in points] == [*SWEEP_CHROMA, *[0.08] * 5]
        assert [entry.frame_hold for entry in points] == [*[1] * 30, 2, 3, 4, 5, 6]
        assert points[0].tolerance == pytest.approx(0.0005)
        assert points[16].tolerance == pytest.approx(0.002887, rel=1e-3)
        assert [entry.tolerance for entry in points[29:]] == pytest.approx([0.012] * 6)
        assert points[0].error < points[29].error
        assert min(entry.error for entry in points) > 0.0
