from __future__ import annotations

import json

import numpy as np
import pytest
from fmvcore.testing import seeded

from neogeomedia import bake, cartridge, quality, tiercache
from tests.bakehelp import SYNTHETIC_FILM
from tests.cartridgehelp import (
    cache_key,
    fake_docker,
    fake_host_compiler,
    header,
    last_report,
    plain,
    preview_pixels,
    remember_rates,
    short_clip,
    two_tone_clip,
)

pytestmark = pytest.mark.ffmpeg

fake = seeded()
WHOLE_CLIP_FRAMES = 12
SUBTITLE_STRIDE = 8 + 2 * 40
WHITE = 255
PAST_THE_END = "1.0"


@pytest.fixture(scope="module")
def movie(tmp_path_factory):
    return short_clip(tmp_path_factory.mktemp("cartridge") / "my movie.mp4")


@pytest.fixture(scope="module")
def two_tone(tmp_path_factory):
    return two_tone_clip(tmp_path_factory.mktemp("two-tone") / "two tone.mp4")


@pytest.fixture
def captions(tmp_path):
    path = tmp_path / "captions.srt"
    line = fake.word().upper()
    path.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{line}\n", encoding="utf-8")
    return path


def every_rung_refused() -> dict[str, float | None]:
    return dict.fromkeys(tier.name for tier in quality.LADDER)


class TestSourceValidation:
    def test_a_missing_source_is_named_in_the_error(self, tmp_path, capsys):
        # Arrange
        argv = [str(tmp_path / "absent.mkv")]

        # Act
        code = cartridge.main(argv)

        # Assert
        assert code == 2
        assert f"source not found: {tmp_path / 'absent.mkv'}" in capsys.readouterr().err

    def test_a_missing_subtitle_file_is_named_in_the_error(self, movie, tmp_path, capsys):
        # Arrange
        argv = [*plain(movie), "--subtitles", str(tmp_path / "absent.srt")]

        # Act
        code = cartridge.main(argv)

        # Assert
        assert code == 2
        assert f"subtitle file not found: {tmp_path / 'absent.srt'}" in capsys.readouterr().err

    def test_a_directory_given_as_the_source_is_rejected(self, tmp_path, capsys):
        # Arrange
        argv = [str(tmp_path)]

        # Act
        code = cartridge.main(argv)

        # Assert
        assert code == 2
        assert f"source is not a file: {tmp_path}" in capsys.readouterr().err


class TestANamedRung:
    def test_the_whole_film_is_baked_when_no_trim_is_given(self, movie, tmp_path, capsys):
        # Arrange
        argv = [*plain(movie), "--quality", "q17", "--build-dir", str(tmp_path / "out")]

        # Act
        code = cartridge.main([*argv, "--bake-only"])

        # Assert
        assert code == 0
        assert last_report(capsys.readouterr().out)["frames"] == WHOLE_CLIP_FRAMES

    def test_the_rung_and_the_trim_reach_the_bake(self, two_tone, tmp_path):
        # Arrange
        build = tmp_path / "out"
        window = ["--start", "0.6", "--duration", "0.25", "--preview", str(tmp_path / "p.mkv")]
        argv = [*plain(two_tone), "--quality", "q20", "--build-dir", str(build), *window]

        # Act
        code = cartridge.main([*argv, "--bake-only"])

        # Assert
        assert code == 0
        assert '#define MOVIE_TIER_NAME "Q20"' in header(build)
        assert "#define MOVIE_FRAME_COUNT 14\n" in header(build)
        assert np.all(preview_pixels(tmp_path / "p.mkv") == WHITE)

    def test_an_explicit_subtitle_file_reaches_the_bake(self, movie, captions, tmp_path):
        # Arrange
        build = tmp_path / "out"
        argv = [*plain(movie), "--quality", "q17", "--subtitles", str(captions)]

        # Act
        code = cartridge.main([*argv, "--build-dir", str(build), "--bake-only"])

        # Assert
        assert code == 0
        assert (build / "baked" / "subtitles.bin").stat().st_size == SUBTITLE_STRIDE


class TestCartridgeBuild:
    def test_a_good_bake_is_built_into_the_directory_it_used(
        self, movie, tmp_path, monkeypatch, capsys
    ):
        # Arrange
        log = fake_docker(monkeypatch, tmp_path)
        out = tmp_path / "out"
        out.mkdir()
        (out / cartridge.CARTRIDGE_NAME).write_bytes(bytes(fake.random_int(1, 64)))

        # Act
        code = cartridge.main([*plain(movie), "--quality", "q17", "--build-dir", str(out)])

        # Assert
        assert code == 0
        assert f"-e BUILD={out} " in log.read_text()
        assert f"{out / cartridge.CARTRIDGE_NAME}  " in capsys.readouterr().out

    def test_a_host_toolchain_on_the_path_still_builds_in_the_image(
        self, movie, tmp_path, monkeypatch
    ):
        # Arrange
        log = fake_docker(monkeypatch, tmp_path)
        fake_host_compiler(tmp_path)
        out = tmp_path / "out"

        # Act
        code = cartridge.main([*plain(movie), "--quality", "q17", "--build-dir", str(out)])

        # Assert
        assert code == 0
        assert f"-e BUILD={out} " in log.read_text()

    def test_a_failed_build_returns_its_status(self, movie, tmp_path, monkeypatch, capsys):
        # Arrange
        status = fake.random_int(1, 100)
        fake_docker(monkeypatch, tmp_path, status=status)
        argv = [*plain(movie), "--quality", "q17", "--build-dir", str(tmp_path / "out")]

        # Act
        code = cartridge.main(argv)

        # Assert
        assert code == status
        assert cartridge.CARTRIDGE_NAME not in capsys.readouterr().out

    def test_bake_only_stops_before_the_build(self, movie, tmp_path, monkeypatch):
        # Arrange
        log = fake_docker(monkeypatch, tmp_path)
        argv = [*plain(movie), "--quality", "q17", "--build-dir", str(tmp_path / "out")]

        # Act
        code = cartridge.main([*argv, "--bake-only"])

        # Assert
        assert code == 0
        assert not log.exists()

    def test_a_failed_bake_skips_the_build(self, movie, tmp_path, monkeypatch):
        # Arrange
        log = fake_docker(monkeypatch, tmp_path)
        argv = [*plain(movie), "--quality", "q17", "--duration", PAST_THE_END]

        # Act
        code = cartridge.main([*argv, "--build-dir", str(tmp_path / "out")])

        # Assert
        assert code == bake.OVERRAN
        assert not log.exists()


class TestSearchingFromRememberedRungs:
    def test_naming_no_rung_settles_it_by_searching(self, movie, tmp_path, capsys):
        # Arrange
        store = tmp_path / "tiers.json"
        remember_rates(store, movie, 0.2, every_rung_refused())

        # Act
        cartridge.main([*plain(movie), "--duration", "0.2", "--tier-cache", str(store)])

        # Assert
        assert "settled entirely from remembered measurements" in capsys.readouterr().err

    def test_a_source_that_fits_nowhere_is_refused_rather_than_trimmed(
        self, movie, tmp_path, capsys
    ):
        # Arrange
        store = tmp_path / "tiers.json"
        remember_rates(store, movie, 0.2, every_rung_refused())
        argv = [*plain(movie), "--duration", "0.2", "--tier-cache", str(store)]

        # Act
        code = cartridge.main([*argv, "--build-dir", str(tmp_path / "out")])

        # Assert
        assert code == cartridge.NO_TIER_FITS
        assert not (tmp_path / "out" / cartridge.CARTRIDGE_NAME).exists()
        assert "this source fits no tier" in capsys.readouterr().err

    def test_the_first_reachable_fitting_rung_is_baked_and_unreachable_ones_never_are(
        self, movie, tmp_path
    ):
        # Arrange
        store = tmp_path / "tiers.json"
        rate = fake.pyfloat(min_value=1.0, max_value=1_000.0)
        refused = dict.fromkeys(tier.name for tier in quality.LADDER[:30])
        fitting = {tier.name: rate for tier in quality.LADDER[31:]}
        remember_rates(store, movie, 0.2, {**refused, **fitting})
        argv = [*plain(movie), "--duration", "0.2", "--tier-cache", str(store), "--denoise", "0"]

        # Act
        code = cartridge.main([*argv, "--build-dir", str(tmp_path / "out"), "--bake-only"])

        # Assert
        assert code == 0
        assert '#define MOVIE_TIER_NAME "Q32"' in header(tmp_path / "out")
        assert not (tmp_path / "out-probe").exists()


class TestMeasuringARung:
    def test_a_finished_bake_becomes_a_rate(self, movie, tmp_path):
        # Arrange
        store = tmp_path / "tiers.json"
        argv = [*plain(movie), "--duration", "0.2", "--tier-cache", str(store), "--denoise", "0"]

        # Act
        cartridge.main([*argv, "--build-dir", str(tmp_path / "out"), "--bake-only"])

        # Assert
        measured = json.loads((tmp_path / "out-probe" / "q01.json").read_text())
        rates = tiercache.recall(store, cache_key(movie, 0.2))
        assert list(rates) == ["q01"]
        assert rates["q01"] == pytest.approx(measured["tile_count"] * 60 / 0.2)

    def test_each_refused_rung_is_remembered_and_measured_in_its_own_directory(
        self, movie, tmp_path, capsys
    ):
        # Arrange
        store = tmp_path / "tiers.json"
        rest = {tier.name: None for tier in quality.LADDER[2:]}
        key = remember_rates(store, movie, float(PAST_THE_END), rest)
        argv = [*plain(movie), "--duration", PAST_THE_END, "--tier-cache", str(store)]

        # Act
        code = cartridge.main([*argv, "--build-dir", str(tmp_path / "out"), "--bake-only"])

        # Assert
        assert code == cartridge.NO_TIER_FITS
        assert tiercache.recall(store, key) == {**rest, "q01": None, "q02": None}
        assert sorted(p.name for p in (tmp_path / "out-probe").iterdir() if p.is_dir()) == [
            "q01",
            "q02",
        ]
        assert "this source fits no tier" in capsys.readouterr().err


class TestReadingAProbeReport:
    @pytest.mark.parametrize(
        ("report", "status", "capped"),
        [
            ({"tile_count": 5, "dictionary_full": True, "budget_exceeded": False}, 4, True),
            ({"tile_count": 9, "dictionary_full": False, "budget_exceeded": True}, 0, True),
            ({"tile_count": 9, "dictionary_full": False, "budget_exceeded": False}, 0, False),
        ],
        ids=["dictionary-full", "budget-exceeded-on-a-clean-exit", "clean"],
    )
    def test_a_report_is_capped_only_when_the_bake_overran(self, tmp_path, report, status, capped):
        # Arrange
        path = tmp_path / "q17.json"
        path.write_text(json.dumps(report))
        tier = quality.tier_by_name("q17")

        # Act
        reading = cartridge._read_reading(tier, path, status)

        # Assert
        assert (reading.tiles, reading.capped) == (report["tile_count"], capped)

    def test_a_bake_that_leaves_no_report_counts_as_a_refusal(self, tmp_path):
        # Arrange
        tier = quality.tier_by_name("q17")

        # Act
        reading = cartridge._read_reading(tier, tmp_path / "absent.json", 0)

        # Assert
        assert (reading.tiles, reading.capped) == (quality.CROM_TILES, True)


class TestDenoise:
    def test_a_number_is_forwarded_to_the_bake(self, movie, tmp_path, capsys):
        # Arrange
        argv = [*plain(movie), "--quality", "q17", "--denoise", "2"]

        # Act
        cartridge.main([*argv, "--build-dir", str(tmp_path / "out"), "--bake-only"])

        # Assert
        assert last_report(capsys.readouterr().out)["denoise"] == 2.0

    def test_a_named_rung_measures_nothing_unless_asked(self, movie, tmp_path, capsys):
        # Arrange
        argv = [*plain(movie), "--quality", "q17", "--build-dir", str(tmp_path / "out")]

        # Act
        cartridge.main([*argv, "--bake-only"])

        # Assert
        captured = capsys.readouterr()
        assert last_report(captured.out)["denoise"] == 0.0
        assert "blurred error by strength" not in captured.err

    def test_a_negative_strength_is_refused(self, movie):
        # Arrange
        argv = [*plain(movie), "--denoise", "-1"]

        # Act
        with pytest.raises(SystemExit) as refused:
            cartridge.main(argv)

        # Assert
        assert refused.value.code == 2

    def test_auto_measures_the_strength_on_the_film(self, tmp_path, capsys):
        # Arrange
        argv = [
            *plain(SYNTHETIC_FILM),
            "--quality",
            "q17",
            "--denoise",
            "auto",
            "--duration",
            "0.5",
        ]

        # Act
        cartridge.main([*argv, "--build-dir", str(tmp_path), "--bake-only"])

        # Assert
        captured = capsys.readouterr()
        assert "denoise 0, blurred error by strength" in captured.err
        assert last_report(captured.out)["denoise"] == 0.0
