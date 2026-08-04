from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def sweep():
    spec = importlib.util.spec_from_file_location("sweep_ladder", SCRIPTS / "sweep_ladder.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def rung(sweep, name, declared, tiles, error):
    return sweep.Measurement(name=name, declared=declared, tiles=tiles, error=error)


@pytest.fixture
def healthy(sweep):
    return [
        rung(sweep, "q01", 1.50, 100, 0.001),
        rung(sweep, "q02", 1.20, 80, 0.002),
        rung(sweep, "q03", 1.00, 60, 0.004),
        rung(sweep, "q04", 0.80, 40, 0.008),
    ]


class TestMonotonicity:
    def test_a_healthy_ladder_has_no_cost_inversion(self, sweep, healthy):
        assert sweep.cost_inversions(healthy) == []

    def test_a_healthy_ladder_has_no_error_inversion(self, sweep, healthy):
        assert sweep.error_inversions(healthy) == []

    def test_a_rung_that_costs_more_than_the_one_above_is_reported(self, sweep, healthy):
        broken = list(healthy)
        broken[2] = rung(sweep, "q03", 1.00, 95, 0.004)

        assert sweep.cost_inversions(broken) == [("q02", "q03")]

    def test_a_rung_that_looks_better_than_the_one_above_is_reported(self, sweep, healthy):
        broken = list(healthy)
        broken[2] = rung(sweep, "q03", 1.00, 60, 0.0015)

        assert sweep.error_inversions(broken) == [("q02", "q03")]


class TestDominance:
    def test_a_healthy_ladder_has_no_dominated_rung(self, sweep, healthy):
        assert sweep.dominated(healthy) == []

    def test_a_rung_beaten_on_both_axes_is_named_with_its_beater(self, sweep, healthy):
        broken = list(healthy)
        broken[1] = rung(sweep, "q02", 1.20, 100, 0.005)

        found = sweep.dominated(broken)
        beaters = {row.name: row for row in broken}

        assert [name for name, _, _, _ in found] == ["q02"]
        beaten, by = found[0][0], found[0][1]
        assert beaters[by].tiles <= beaters[beaten].tiles
        assert beaters[by].error <= beaters[beaten].error

    def test_an_equal_rung_does_not_count_as_dominating(self, sweep):
        rows = [rung(sweep, "a", 1.0, 50, 0.001), rung(sweep, "b", 0.9, 50, 0.001)]

        assert sweep.dominated(rows) == []


class TestModelError:
    def test_the_reference_rung_has_no_model_error(self, sweep, healthy):
        errors = sweep.model_error(healthy, reference="q03")

        assert errors["q03"] == pytest.approx(0.0)

    def test_a_rung_costing_more_than_declared_reads_positive(self, sweep, healthy):
        errors = sweep.model_error(healthy, reference="q03")

        assert errors["q01"] == pytest.approx((100 / 60) / 1.50 - 1)

    def test_an_unknown_reference_is_refused(self, sweep, healthy):
        with pytest.raises(KeyError):
            sweep.model_error(healthy, reference="nope")


class TestReport:
    def test_every_rung_appears(self, sweep, healthy):
        text = sweep.format_report(healthy, reference="q03")

        for row in healthy:
            assert row.name in text

    def test_a_clean_ladder_says_so(self, sweep, healthy):
        assert "on the frontier" in sweep.format_report(healthy, reference="q03")

    def test_a_dominated_rung_is_called_out(self, sweep, healthy):
        broken = list(healthy)
        broken[1] = rung(sweep, "q02", 1.20, 100, 0.005)

        assert "beaten by" in sweep.format_report(broken, reference="q03")


class TestExitCode:
    def test_a_clean_ladder_passes(self, sweep, healthy):
        assert sweep.verdict(healthy) == 0

    def test_a_dominated_rung_fails(self, sweep, healthy):
        broken = list(healthy)
        broken[1] = rung(sweep, "q02", 1.20, 100, 0.005)

        assert sweep.verdict(broken) != 0

    def test_a_cost_inversion_fails(self, sweep, healthy):
        broken = list(healthy)
        broken[2] = rung(sweep, "q03", 1.00, 95, 0.004)

        assert sweep.verdict(broken) != 0
