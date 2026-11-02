from __future__ import annotations

import pytest

from tests.capturehelp import flat_bake, flat_capture, load_script

pytestmark = pytest.mark.ffmpeg

FRAMES = 6
MATCH = 16
NEAR = 15
FAR = 4
BLACK = 0
OVERSCAN = 8


@pytest.fixture(scope="module")
def measure_drift():
    return load_script("measure_drift")


def movie(tmp_path, painted: dict[int, int]):
    levels = [painted.get(step, BLACK) for step in range(FRAMES)]
    return flat_bake(tmp_path / "baked", levels)


def shot(tmp_path, level: int):
    return flat_capture(tmp_path / "shot.png", level)


class TestFindingTheDisplayedFrame:
    def test_it_names_the_frame_the_capture_actually_shows(self, measure_drift, tmp_path, capsys):
        # Arrange
        baked = movie(tmp_path, {3: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=4, overscan=OVERSCAN)

        # Assert
        assert found == 3
        assert "player is 2 frames behind" in capsys.readouterr().out

    def test_a_capture_on_time_reports_no_shortfall(self, measure_drift, tmp_path, capsys):
        # Arrange
        baked = movie(tmp_path, {5: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=4, overscan=OVERSCAN)

        # Assert
        assert found == 5
        assert "player is 0 frames behind" in capsys.readouterr().out

    def test_it_scores_every_candidate_rather_than_the_first_plausible_one(
        self, measure_drift, tmp_path
    ):
        # Arrange
        baked = movie(tmp_path, {2: NEAR, 4: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=5, overscan=OVERSCAN)

        # Assert
        assert found == 4


class TestWindowBounds:
    @pytest.mark.parametrize(
        ("painted", "expected"),
        [(0, 2), (5, 5)],
        ids=["before-the-start", "past-the-end"],
    )
    def test_a_window_reaching_outside_the_movie_is_clamped(
        self, measure_drift, tmp_path, painted, expected
    ):
        # Arrange
        baked = movie(tmp_path, {painted: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, expected, window=60, overscan=OVERSCAN)

        # Assert
        assert found == painted


class TestAWindowPastTheFilm:
    def test_a_capture_later_than_the_film_finds_no_frame(self, measure_drift, tmp_path, capsys):
        # Arrange
        baked = movie(tmp_path, {4: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 100, window=5, overscan=OVERSCAN)

        # Assert
        assert (found, "best match" in capsys.readouterr().out) == (None, False)


class TestExitCode:
    @pytest.mark.parametrize(
        ("painted", "code"),
        [({1: MATCH, 4: MATCH}, 1), ({4: MATCH}, 0)],
        ids=["matches-nothing-decisively", "finds-a-frame"],
    )
    def test_the_exit_code_says_whether_a_frame_was_found(
        self, measure_drift, tmp_path, painted, code
    ):
        # Arrange
        baked = movie(tmp_path, painted)
        capture = shot(tmp_path, MATCH)
        argv = ["--capture", str(capture), "--baked", str(baked), "--expected", "5"]

        # Act
        status = measure_drift.main([*argv, "--window", "5"])

        # Assert
        assert status == code


class TestTiedMatches:
    def test_a_tie_resolves_to_the_frame_nearest_the_expected_one(self, measure_drift, tmp_path):
        # Arrange
        baked = movie(tmp_path, dict.fromkeys(range(1, FRAMES), MATCH))
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=5, overscan=OVERSCAN)

        # Assert
        assert found == 5

    def test_a_film_that_matches_everywhere_has_no_rival(self, measure_drift, tmp_path):
        # Arrange
        baked = movie(tmp_path, dict.fromkeys(range(FRAMES), MATCH))
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=5, overscan=OVERSCAN)

        # Assert
        assert found == 5

    def test_a_clear_winner_still_beats_a_nearer_tie(self, measure_drift, tmp_path):
        # Arrange
        baked = movie(tmp_path, {2: MATCH, 4: FAR, 5: FAR})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=5, overscan=OVERSCAN)

        # Assert
        assert found == 2


class TestAmbiguousMatches:
    def test_a_distant_frame_matching_just_as_well_refuses_to_answer(
        self, measure_drift, tmp_path, capsys
    ):
        # Arrange
        baked = movie(tmp_path, {1: MATCH, 4: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=5, overscan=OVERSCAN)

        # Assert
        assert found is None
        assert "ambiguous: the rival is within" in capsys.readouterr().out

    def test_a_decisive_match_still_answers(self, measure_drift, tmp_path):
        # Arrange
        baked = movie(tmp_path, {1: FAR, 4: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=5, overscan=OVERSCAN)

        # Assert
        assert found == 4

    def test_a_run_of_identical_frames_is_one_match_rather_than_rivals(
        self, measure_drift, tmp_path
    ):
        # Arrange
        baked = movie(tmp_path, {0: FAR, 3: MATCH, 4: MATCH, 5: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(baked, capture, 5, window=5, overscan=OVERSCAN)

        # Assert
        assert found == 5

    @pytest.mark.parametrize(
        ("separation", "expected"),
        [(1.1, 4), (100.0, None)],
        ids=["loose", "strict"],
    )
    def test_the_separation_it_demands_is_configurable(
        self, measure_drift, tmp_path, separation, expected
    ):
        # Arrange
        baked = movie(tmp_path, {1: NEAR, 4: MATCH})
        capture = shot(tmp_path, MATCH)

        # Act
        found = measure_drift.measure(
            baked, capture, 5, window=5, overscan=OVERSCAN, separation=separation
        )

        # Assert
        assert found == expected
