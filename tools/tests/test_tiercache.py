from __future__ import annotations

import json

import pytest

from aesmovie import quality, tiercache


@pytest.fixture
def movie(tmp_path):
    path = tmp_path / "film.mkv"
    path.write_bytes(b"a" * 4096)
    return path


@pytest.fixture
def params():
    return tiercache.Params(start=0.0, duration=600.0, fit="fill", denoise=0.0, frame_hold=1)


class TestTheKeyFollowsTheContent:
    def test_the_same_file_gives_the_same_key(self, movie, params):
        assert tiercache.key_for(movie, params) == tiercache.key_for(movie, params)

    def test_renaming_the_file_does_not_change_the_key(self, movie, params, tmp_path):
        before = tiercache.key_for(movie, params)
        renamed = tmp_path / "different name.mkv"
        movie.rename(renamed)

        assert tiercache.key_for(renamed, params) == before

    def test_editing_the_file_changes_the_key(self, movie, params):
        before = tiercache.key_for(movie, params)
        movie.write_bytes(b"b" * 4096)

        assert tiercache.key_for(movie, params) != before

    def test_a_different_length_changes_the_key(self, movie, params):
        before = tiercache.key_for(movie, params)
        movie.write_bytes(b"a" * 8192)

        assert tiercache.key_for(movie, params) != before

    def test_a_parameter_that_changes_cost_changes_the_key(self, movie, params):
        before = tiercache.key_for(movie, params)
        other = tiercache.Params(
            start=params.start,
            duration=params.duration,
            fit="letterbox",
            denoise=params.denoise,
            frame_hold=params.frame_hold,
        )

        assert tiercache.key_for(movie, other) != before

    def test_a_window_change_changes_the_key(self, movie, params):
        before = tiercache.key_for(movie, params)
        other = tiercache.Params(
            start=30.0,
            duration=params.duration,
            fit=params.fit,
            denoise=params.denoise,
            frame_hold=params.frame_hold,
        )

        assert tiercache.key_for(movie, other) != before


class TestStoringMeasurements:
    def test_a_reading_survives_a_round_trip(self, tmp_path):
        store = tmp_path / "tiers.json"
        tiercache.remember(store, "abc", "q17", 95_270.0)

        assert tiercache.recall(store, "abc") == {"q17": 95_270.0}

    def test_readings_for_one_source_accumulate(self, tmp_path):
        store = tmp_path / "tiers.json"
        tiercache.remember(store, "abc", "q17", 95_270.0)
        tiercache.remember(store, "abc", "q10", 120_000.0)

        assert tiercache.recall(store, "abc") == {"q17": 95_270.0, "q10": 120_000.0}

    def test_sources_do_not_bleed_into_each_other(self, tmp_path):
        store = tmp_path / "tiers.json"
        tiercache.remember(store, "abc", "q17", 95_270.0)
        tiercache.remember(store, "xyz", "q17", 10.0)

        assert tiercache.recall(store, "abc") == {"q17": 95_270.0}

    def test_an_absent_store_recalls_nothing(self, tmp_path):
        assert tiercache.recall(tmp_path / "missing.json", "abc") == {}

    def test_a_corrupt_store_recalls_nothing_rather_than_raising(self, tmp_path):
        store = tmp_path / "tiers.json"
        store.write_text("{ this is not json")

        assert tiercache.recall(store, "abc") == {}

    def test_a_corrupt_store_is_replaced_rather_than_appended_to(self, tmp_path):
        store = tmp_path / "tiers.json"
        store.write_text("{ this is not json")
        tiercache.remember(store, "abc", "q17", 1.0)

        assert json.loads(store.read_text())["abc"] == {"q17": 1.0}


class TestPredicting:
    def test_a_measured_tier_is_used_directly(self):
        rates = {"q17": 100_000.0}

        assert tiercache.predict(rates, quality.tier_by_name("q17"), 10.0) == pytest.approx(1e6)

    def test_an_unmeasured_tier_is_scaled_from_the_nearest_reading(self):
        rates = {"q17": 100_000.0}
        q16 = quality.tier_by_name("q16")
        q17 = quality.tier_by_name("q17")

        expected = 100_000.0 * (q16.relative_cost / q17.relative_cost) * 10.0

        assert tiercache.predict(rates, q16, 10.0) == pytest.approx(expected)

    def test_with_no_readings_at_all_nothing_can_be_predicted(self):
        assert tiercache.predict({}, quality.tier_by_name("q17"), 10.0) is None

    def test_the_nearest_reading_is_the_one_closest_in_cost(self):
        rates = {"q01": 1.0, "q30": 2.0}
        q29 = quality.tier_by_name("q29")

        chosen = tiercache.nearest_measured(rates, q29)

        assert chosen == "q30"


class TestChoosing:
    def test_it_takes_the_best_rung_that_fits(self):
        rates = {"q17": 100_000.0}

        tier = tiercache.best_fitting(rates, minutes=10.0, budget=1_020_000)

        assert tier is not None
        assert tier.name == "q17"

    def test_a_bigger_budget_reaches_a_better_rung(self):
        rates = {"q17": 100_000.0}

        loose = tiercache.best_fitting(rates, minutes=10.0, budget=10_000_000)
        tight = tiercache.best_fitting(rates, minutes=10.0, budget=1_020_000)

        assert loose is not None and tight is not None
        assert quality.LADDER.index(loose) < quality.LADDER.index(tight)

    def test_nothing_fits_when_the_budget_is_tiny(self):
        rates = {"q17": 100_000.0}

        assert tiercache.best_fitting(rates, minutes=600.0, budget=1000) is None

    def test_a_tier_the_baker_would_refuse_is_never_chosen(self):
        rates = {"q17": 100_000.0}

        tier = tiercache.best_fitting(
            rates, minutes=17.0, budget=1_048_576, source_fps=24.0, vblank_fps=59.185
        )

        assert tier is not None
        assert tier.name != "q31"
