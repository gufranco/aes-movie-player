from __future__ import annotations

import dataclasses
import json

import pytest
from fmvcore.testing import seeded

from neogeomedia import limits, quality, tiercache

FILM_BYTES = 4096


@pytest.fixture
def fake():
    return seeded()


@pytest.fixture
def movie(tmp_path, fake):
    path = tmp_path / "film.mkv"
    path.write_bytes(fake.binary(length=FILM_BYTES))
    return path


@pytest.fixture
def params():
    return tiercache.Params(
        start=0.0, duration=600.0, denoise=0.0, frame_hold=1, dither=limits.DEFAULT_DITHER
    )


@pytest.fixture
def key(fake):
    return fake.sha256()


@pytest.fixture
def rate(fake):
    return fake.pyfloat(min_value=1_000, max_value=200_000)


@pytest.fixture
def store(tmp_path):
    return tmp_path / "tiers.json"


class TestTheKeyFollowsTheContent:
    def test_the_same_file_gives_the_same_key(self, movie, params):
        # Arrange
        first = tiercache.key_for(movie, params)

        # Act
        second = tiercache.key_for(movie, params)

        # Assert
        assert second == first
        assert len(second) == 64

    def test_renaming_the_file_does_not_change_the_key(self, movie, params, tmp_path):
        # Arrange
        before = tiercache.key_for(movie, params)
        renamed = movie.rename(tmp_path / "different name.mkv")

        # Act
        after = tiercache.key_for(renamed, params)

        # Assert
        assert after == before

    def test_editing_the_file_changes_the_key(self, movie, params, fake):
        # Arrange
        before = tiercache.key_for(movie, params)
        movie.write_bytes(fake.binary(length=FILM_BYTES))

        # Act
        after = tiercache.key_for(movie, params)

        # Assert
        assert after != before

    def test_a_different_length_changes_the_key(self, movie, params):
        # Arrange
        before = tiercache.key_for(movie, params)
        movie.write_bytes(movie.read_bytes() * 2)

        # Act
        after = tiercache.key_for(movie, params)

        # Assert
        assert after != before

    @pytest.mark.parametrize("change", [{"frame_hold": 2}, {"start": 30.0}, {"dither": 0.0}])
    def test_a_parameter_that_changes_cost_or_window_changes_the_key(self, movie, params, change):
        # Arrange
        before = tiercache.key_for(movie, params)
        other = dataclasses.replace(params, **change)

        # Act
        after = tiercache.key_for(movie, other)

        # Assert
        assert after != before


class TestStoringMeasurements:
    def test_a_reading_survives_a_round_trip(self, store, key, rate):
        # Arrange
        tiercache.remember(store, key, "q17", rate)

        # Act
        recalled = tiercache.recall(store, key)

        # Assert
        assert recalled == {"q17": rate}

    def test_readings_for_one_source_accumulate(self, store, key, rate):
        # Arrange
        tiercache.remember(store, key, "q17", rate)

        # Act
        tiercache.remember(store, key, "q10", rate * 2)

        # Assert
        assert tiercache.recall(store, key) == {"q17": rate, "q10": rate * 2}

    def test_sources_do_not_bleed_into_each_other(self, store, key, rate, fake):
        # Arrange
        tiercache.remember(store, key, "q17", rate)

        # Act
        tiercache.remember(store, fake.sha256(), "q17", rate / 2)

        # Assert
        assert tiercache.recall(store, key) == {"q17": rate}

    def test_an_absent_store_recalls_nothing(self, store, key):
        # Arrange
        missing = store.with_name("missing.json")

        # Act
        recalled = tiercache.recall(missing, key)

        # Assert
        assert recalled == {}

    def test_a_corrupt_store_recalls_nothing_rather_than_raising(self, store, key):
        # Arrange
        store.write_text("{ this is not json")

        # Act
        recalled = tiercache.recall(store, key)

        # Assert
        assert recalled == {}

    def test_a_corrupt_store_is_replaced_rather_than_appended_to(self, store, key, rate):
        # Arrange
        store.write_text("{ this is not json")

        # Act
        tiercache.remember(store, key, "q17", rate)

        # Assert
        assert tiercache.recall(store, key) == {"q17": rate}

    def test_a_store_from_another_version_is_ignored_rather_than_misread(self, store, key, rate):
        # Arrange
        old = {"version": 1, "sources": {key: {"tiers": {"q17": rate}}}}
        store.write_text(json.dumps(old))

        # Act
        recalled = tiercache.recall(store, key)

        # Assert
        assert recalled == {}


class TestTheFileIsReadable:
    @pytest.mark.reads_real_store
    def test_it_lives_at_the_top_of_the_project(self):
        # Arrange
        name = "neogeomedia-tiers.json"

        # Act
        found = tiercache.default_store()

        # Assert
        assert found.name == name
        assert (found.parent / "README.md").is_file()

    def test_an_entry_names_the_film_beside_the_readings(self, store, key, rate, movie, params):
        # Arrange
        tiercache.remember(store, key, "q17", rate)

        # Act
        tiercache.describe(store, key, source=movie, params=params, chosen="q17")

        # Assert
        entry = json.loads(store.read_text())["sources"][key]
        assert entry["file"] == "film.mkv"
        assert entry["quality"] == "q17"
        assert entry["window"]["duration"] == pytest.approx(600.0)
        assert entry["tiers"] == {"q17": rate}

    def test_describing_an_entry_does_not_disturb_its_readings(
        self, store, key, rate, movie, params
    ):
        # Arrange
        tiercache.remember(store, key, "q17", rate)

        # Act
        tiercache.describe(store, key, source=movie, params=params)

        # Assert
        assert tiercache.recall(store, key) == {"q17": rate}

    def test_readings_land_under_a_described_entry_rather_than_replacing_it(
        self, store, key, rate, movie, params
    ):
        # Arrange
        tiercache.describe(store, key, source=movie, params=params)

        # Act
        tiercache.remember(store, key, "q17", rate)

        # Assert
        assert json.loads(store.read_text())["sources"][key]["file"] == "film.mkv"
        assert tiercache.recall(store, key) == {"q17": rate}

    def test_the_file_ends_with_a_newline_so_a_diff_stays_quiet(self, store, key, rate):
        # Arrange
        tier = "q17"

        # Act
        tiercache.remember(store, key, tier, rate)

        # Assert
        assert store.read_text().endswith("}\n")


class TestWhatIsSettled:
    @pytest.fixture
    def overran(self, store, key):
        tiercache.remember(store, key, "q01", None)
        return tiercache.recall(store, key)

    def test_a_rung_that_overran_is_settled(self, overran):
        # Arrange
        q01 = quality.tier_by_name("q01")

        # Act
        known = tiercache.settled(overran, q01)

        # Assert
        assert known is True

    def test_a_rung_that_overran_does_not_fit(self, overran):
        # Arrange
        q01 = quality.tier_by_name("q01")

        # Act
        fitting = tiercache.fits(overran, q01)

        # Assert
        assert fitting is False

    def test_the_best_known_fit_walks_from_the_top(self):
        # Arrange
        rates: dict[str, float | None] = {"q01": None, "q02": None, "q03": 90_000.0}

        # Act
        tier = tiercache.best_known_fit(rates)

        # Assert
        assert tier is not None
        assert tier.name == "q03"

    def test_an_unsettled_rung_stops_the_walk_rather_than_being_guessed(self):
        # Arrange
        rates: dict[str, float | None] = {"q01": None, "q03": 90_000.0}

        # Act
        tier = tiercache.best_known_fit(rates)

        # Assert
        assert tier is None

    def test_nothing_settled_means_nothing_known(self):
        # Arrange
        rates: dict[str, float | None] = {}

        # Act
        tier = tiercache.best_known_fit(rates)

        # Assert
        assert tier is None

    def test_an_unreachable_rung_is_skipped_rather_than_stopping_the_walk(self):
        # Arrange
        rates: dict[str, float | None] = {
            tier.name: None for tier in quality.LADDER if tier.frame_hold == 1
        }
        known = {**rates, "q35": 90_000.0}

        # Act
        tier = tiercache.best_known_fit(known, source_fps=10.0, vblank_fps=59.185)

        # Assert
        assert tier is not None
        assert tier.name == "q35"

    def test_every_rung_refused_means_none_fits(self):
        # Arrange
        rates: dict[str, float | None] = dict.fromkeys(tier.name for tier in quality.LADDER)

        # Act
        tier = tiercache.best_known_fit(rates)

        # Assert
        assert tier is None


class TestALargeFile:
    def test_a_change_past_the_first_mebibyte_changes_the_digest(self, tmp_path, fake):
        # Arrange
        path = tmp_path / "long.mkv"
        body = fake.binary(length=tiercache.SAMPLE_BYTES * 2)
        path.write_bytes(body)
        before = tiercache.content_digest(path)
        path.write_bytes(body[:-1] + bytes([body[-1] ^ 0xFF]))

        # Act
        after = tiercache.content_digest(path)

        # Assert
        assert after != before
