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

    def test_it_starts_at_the_best_rung_and_walks_down(self):
        log: list[str] = []
        probe.search(measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known={})

        assert log[0] == "q01"
        assert log == [t.name for t in quality.LADDER[: len(log)]]

    def test_it_stops_at_the_first_rung_that_fits(self):
        log: list[str] = []
        found = probe.search(
            measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known={}
        )

        assert found.tier is not None
        assert log[-1] == found.tier.name

    def test_a_rung_that_overran_is_remembered_as_such(self):
        log: list[str] = []
        found = probe.search(
            measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known={}
        )

        assert found.rates["q01"] is None
        assert found.too_expensive[0] == "q01"

    def test_a_capped_bake_never_becomes_a_rate(self):
        log: list[str] = []
        found = probe.search(
            measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known={}
        )

        for name, rate in found.rates.items():
            if rate is None:
                continue
            tier = quality.tier_by_name(name)
            assert rate == pytest.approx(100_000.0 * tier.relative_cost, rel=1e-6)
            assert rate * MINUTES <= BUDGET

    def test_a_fully_settled_source_bakes_nothing(self):
        log: list[str] = []
        known: dict[str, float | None] = {
            t.name: (None if t.relative_cost > 1.0 else 100_000.0 * t.relative_cost)
            for t in quality.LADDER
        }

        found = probe.search(
            measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known=known
        )

        assert log == []
        assert found.tier is not None
        assert found.tier.name == "q17"

    def test_settled_failures_are_not_baked_again(self):
        log: list[str] = []
        known: dict[str, float | None] = {t.name: None for t in quality.LADDER[:10]}

        probe.search(measure=measurer(100_000.0, log), minutes=MINUTES, budget=BUDGET, known=known)

        assert "q01" not in log
        assert log[0] == "q11"

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
