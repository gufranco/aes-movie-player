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

        assert tiercache.recall(store, "abc") == {"q17": 1.0}

    def test_a_store_from_another_version_is_ignored_rather_than_misread(self, tmp_path):
        store = tmp_path / "tiers.json"
        store.write_text(json.dumps({"version": 1, "sources": {"abc": {"tiers": {"q17": 1.0}}}}))

        assert tiercache.recall(store, "abc") == {}


class TestTheFileIsReadable:
    @pytest.mark.reads_real_store
    def test_it_lives_at_the_top_of_the_project(self):
        store = tiercache.default_store()

        assert store.name == tiercache.STORE_NAME
        assert (store.parent / "README.md").is_file()

    def test_an_entry_names_the_film_beside_the_readings(self, tmp_path, movie, params):
        store = tmp_path / "tiers.json"
        tiercache.remember(store, "abc", "q17", 95_270.0)
        tiercache.describe(store, "abc", source=movie, params=params, chosen="q17")

        entry = json.loads(store.read_text())["sources"]["abc"]

        assert entry["file"] == "film.mkv"
        assert entry["quality"] == "q17"
        assert entry["window"]["duration"] == pytest.approx(600.0)
        assert entry["tiers"] == {"q17": 95_270.0}

    def test_describing_an_entry_does_not_disturb_its_readings(self, tmp_path, movie, params):
        store = tmp_path / "tiers.json"
        tiercache.remember(store, "abc", "q17", 95_270.0)
        tiercache.describe(store, "abc", source=movie, params=params)

        assert tiercache.recall(store, "abc") == {"q17": 95_270.0}

    def test_readings_land_under_a_described_entry_rather_than_replacing_it(
        self, tmp_path, movie, params
    ):
        store = tmp_path / "tiers.json"
        tiercache.describe(store, "abc", source=movie, params=params)
        tiercache.remember(store, "abc", "q17", 95_270.0)

        assert json.loads(store.read_text())["sources"]["abc"]["file"] == "film.mkv"
        assert tiercache.recall(store, "abc") == {"q17": 95_270.0}

    def test_the_file_ends_with_a_newline_so_a_diff_stays_quiet(self, tmp_path):
        store = tmp_path / "tiers.json"
        tiercache.remember(store, "abc", "q17", 1.0)

        assert store.read_text().endswith("}\n")


class TestWhatIsSettled:
    def test_a_rung_that_overran_is_settled_but_does_not_fit(self, tmp_path):
        store = tmp_path / "tiers.json"
        tiercache.remember(store, "abc", "q01", None)
        rates = tiercache.recall(store, "abc")
        q01 = quality.tier_by_name("q01")

        assert tiercache.settled(rates, q01)
        assert not tiercache.fits(rates, q01)

    def test_the_best_known_fit_walks_from_the_top(self):
        rates: dict[str, float | None] = {"q01": None, "q02": None, "q03": 90_000.0}

        tier = tiercache.best_known_fit(rates)

        assert tier is not None
        assert tier.name == "q03"

    def test_an_unsettled_rung_stops_the_walk_rather_than_being_guessed(self):
        rates: dict[str, float | None] = {"q01": None, "q03": 90_000.0}

        assert tiercache.best_known_fit(rates) is None

    def test_nothing_settled_means_nothing_known(self):
        assert tiercache.best_known_fit({}) is None
