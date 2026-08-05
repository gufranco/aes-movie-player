from __future__ import annotations

import pytest

from aesmovie import probe, quality

BUDGET = 1_048_576
MINUTES = 10.0


def measurer(true_rates, log):
    """A stand-in for baking: reports what a tier would really cost."""

    def measure(tier: quality.Tier) -> probe.Reading:
        log.append(tier.name)
        rate = true_rates * tier.relative_cost
        tiles = rate * MINUTES
        if tiles > BUDGET:
            return probe.Reading(tier=tier, tiles=BUDGET, capped=True)
        return probe.Reading(tier=tier, tiles=int(tiles), capped=False)

    return measure


class TestSearching:
    def test_it_finds_the_best_rung_that_actually_fits(self):
        log: list[str] = []
        found = probe.search(
            measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known={}
        )

        assert found.tier is not None
        cost = 100_000.0 * found.tier.relative_cost * MINUTES
        assert cost <= BUDGET
        better = quality.LADDER[quality.LADDER.index(found.tier) - 1]
        assert 100_000.0 * better.relative_cost * MINUTES > BUDGET

    def test_it_does_not_bake_the_whole_ladder(self):
        log: list[str] = []
        probe.search(measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known={})

        assert len(log) < 6

    def test_a_capped_bake_never_becomes_a_rate(self):
        log: list[str] = []
        found = probe.search(
            measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known={}
        )

        for name, rate in found.rates.items():
            tier = quality.tier_by_name(name)
            assert rate == pytest.approx(100_000.0 * tier.relative_cost, rel=1e-6)

    def test_readings_already_known_shorten_the_search(self):
        log: list[str] = []
        known = {"q17": 100_000.0}
        probe.search(measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known=known)

        assert len(log) <= 2

    def test_an_impossible_source_reports_nothing_rather_than_guessing(self):
        log: list[str] = []
        found = probe.search(
            measure=measurer(50_000_000.0, log), minutes=MINUTES, budget=BUDGET, known={}
        )

        assert found.tier is None

    def test_every_bake_it_ran_is_reported(self):
        log: list[str] = []
        found = probe.search(
            measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known={}
        )

        assert found.baked == log

    def test_a_tier_the_baker_would_refuse_is_never_measured(self):
        log: list[str] = []
        probe.search(
            measure=measurer(3_000_000.0, log),
            minutes=MINUTES,
            budget=BUDGET,
            known={},
            source_fps=24.0,
            vblank_fps=59.185,
        )

        assert "q31" not in log


class TestItNeverTrims:
    def test_it_reports_no_fit_rather_than_shortening_the_source(self):
        log: list[str] = []
        found = probe.search(
            measure=measurer(50_000_000.0, log), minutes=MINUTES, budget=BUDGET, known={}
        )

        assert found.tier is None
        assert found.minutes == MINUTES
