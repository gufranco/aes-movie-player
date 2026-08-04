from __future__ import annotations

import itertools

import numpy as np
import pytest

from aesmovie import ladder


def point(cost: float, error: float, chroma: float = 1.0, hold: int = 1) -> ladder.Point:
    return ladder.Point(
        chroma_weight=chroma,
        tolerance=0.0005,
        frame_hold=hold,
        cost=cost,
        error=error,
    )


class TestTheFrontier:
    def test_a_point_beaten_on_both_axes_is_dropped(self):
        """Costing more for a worse picture is never worth a rung."""
        good = point(1.0, 0.10)
        beaten = point(1.5, 0.20)

        kept = ladder.frontier([good, beaten])

        assert kept == [good]

    def test_a_point_that_wins_on_one_axis_survives(self):
        cheap = point(0.5, 0.30)
        sharp = point(2.0, 0.05)

        kept = ladder.frontier([cheap, sharp])

        assert set(kept) == {cheap, sharp}

    def test_the_frontier_comes_back_cheapest_last(self):
        kept = ladder.frontier([point(0.5, 0.3), point(2.0, 0.05), point(1.0, 0.1)])

        assert [entry.cost for entry in kept] == [2.0, 1.0, 0.5]

    def test_an_exact_duplicate_is_kept_once(self):
        kept = ladder.frontier([point(1.0, 0.1), point(1.0, 0.1)])

        assert len(kept) == 1

    def test_an_empty_sweep_has_an_empty_frontier(self):
        assert ladder.frontier([]) == []


class TestChoosingRungs:
    def test_it_returns_the_number_of_rungs_asked_for(self):
        measured = [point(2.0 * 0.9**step, 0.01 * 1.1**step) for step in range(40)]

        chosen = ladder.choose(ladder.frontier(measured), count=12)

        assert len(chosen) == 12

    def test_the_extremes_are_always_kept(self):
        measured = [point(2.0 * 0.9**step, 0.01 * 1.1**step) for step in range(40)]
        kept = ladder.frontier(measured)

        chosen = ladder.choose(kept, count=8)

        assert chosen[0] == kept[0]
        assert chosen[-1] == kept[-1]

    def test_a_crowd_does_not_swallow_every_rung(self):
        """Fifty settings within a few percent must not use up the ladder.

        Spacing is chosen in cost, not in list position, so a cheap outlier
        still earns a rung even when it is outnumbered fifty to one.
        """
        crowded = [point(2.0 - step * 0.01, 0.01 + step * 0.001) for step in range(50)]
        crowded.append(point(0.5, 0.4))

        chosen = ladder.choose(ladder.frontier(crowded), count=4)

        assert min(entry.cost for entry in chosen) == 0.5

    def test_asking_for_more_rungs_than_measured_returns_what_exists(self):
        measured = ladder.frontier([point(2.0, 0.1), point(1.0, 0.2)])

        assert len(ladder.choose(measured, count=10)) == 2

    def test_the_rungs_descend_in_cost(self):
        measured = [point(2.0 * 0.9**step, 0.01 * 1.1**step) for step in range(40)]

        chosen = ladder.choose(ladder.frontier(measured), count=10)

        assert all(a.cost > b.cost for a, b in itertools.pairwise(chosen))


class TestRenderingTheLadder:
    def test_costs_are_relative_to_the_reference_rung(self):
        chosen = [point(2.0, 0.05), point(1.0, 0.10), point(0.5, 0.30)]

        rungs = ladder.to_tiers(chosen, reference_cost=1.0)

        assert [rung.relative_cost for rung in rungs] == [2.0, 1.0, 0.5]

    def test_every_rung_gets_a_distinct_name(self):
        chosen = [point(2.0 - step * 0.1, 0.05 + step * 0.01) for step in range(12)]

        names = [rung.name for rung in ladder.to_tiers(chosen, reference_cost=1.0)]

        assert len(set(names)) == len(names)

    def test_names_are_ordered_and_zero_padded(self):
        chosen = [point(2.0, 0.05), point(1.0, 0.1)]

        names = [rung.name for rung in ladder.to_tiers(chosen, reference_cost=1.0)]

        assert names == ["q01", "q02"]

    def test_a_held_rung_says_so_in_its_summary(self):
        chosen = [point(0.5, 0.4, chroma=0.12, hold=3)]

        summary = ladder.to_tiers(chosen, reference_cost=1.0)[0].summary

        assert "fps" in summary

    def test_a_full_rate_rung_names_its_colour(self):
        chosen = [point(1.0, 0.1, chroma=0.37, hold=1)]

        summary = ladder.to_tiers(chosen, reference_cost=1.0)[0].summary

        assert "37%" in summary


class TestMeasuringOnePoint:
    def test_it_reports_the_cost_and_the_error_of_one_setting(self, monkeypatch):
        clip = np.zeros((4, 224, 320, 3), dtype=np.uint8)

        class Stats:
            tile_count = 4200
            displayed_error = 0.0031

        class Result:
            stats = Stats()

        seen: dict[str, float] = {}

        def fake_encode(_clips, options, **_kwargs):
            seen["chroma"] = options.chroma_weight
            seen["tolerance"] = options.tolerance
            seen["hold"] = options.frame_hold
            return Result()

        monkeypatch.setattr(ladder.encode, "encode_stream", fake_encode)

        measured = ladder.measure_point(
            clip, chroma_weight=0.37, tolerance=0.0018, frame_hold=2, seed=0
        )

        assert measured.cost == pytest.approx(4200 / (4 / float(ladder.frames.VBLANK_FPS) / 60.0))
        assert measured.error == pytest.approx(0.0031)
        assert seen == {"chroma": 0.37, "tolerance": 0.0018, "hold": 2}
