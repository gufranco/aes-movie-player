from __future__ import annotations

import json
import subprocess

import pytest

from neogeomedia import bake, cartridge, quality
from tests.bakehelp import tone_clip
from tests.cartridgehelp import header, last_report, plain, remember_rates, short_clip

PAST_THE_END = "1.0"
STILL_ROWS = 4
STILL_WIDTH = 640
RASTER_HEIGHT = 224


@pytest.fixture(scope="module")
def movie(tmp_path_factory):
    return short_clip(tmp_path_factory.mktemp("outputs") / "film.mp4")


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    return tone_clip(tmp_path_factory.mktemp("tone") / "tone.mp4")


def named(source, build, *extra):
    return [*plain(source), "--quality", "q17", "--build-dir", str(build), *extra]


def png_size(path):
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries"]
    probe = [*command, "stream=width,height", "-of", "json", str(path)]
    stream = json.loads(subprocess.run(probe, capture_output=True, check=True).stdout)
    return stream["streams"][0]["width"], stream["streams"][0]["height"]


class TestTheReport:
    def test_every_bake_writes_a_report_beside_the_build(self, movie, tmp_path, capsys):
        # Arrange
        build = tmp_path / "out"

        # Act
        code = cartridge.main([*named(movie, build), "--bake-only"])

        # Assert
        assert code == 0
        written = json.loads((build / cartridge.REPORT_NAME).read_text())
        assert written == last_report(capsys.readouterr().out)

    def test_an_explicit_report_path_is_honoured(self, movie, tmp_path):
        # Arrange
        target = tmp_path / "figures" / "film.json"

        # Act
        cartridge.main([*named(movie, tmp_path / "out"), "--report", str(target), "--bake-only"])

        # Assert
        assert json.loads(target.read_text())["frames"] > 0

    def test_an_overrun_still_writes_its_report_and_names_what_fits(self, movie, tmp_path, capsys):
        # Arrange
        build = tmp_path / "out"

        # Act
        code = cartridge.main([*named(movie, build, "--duration", PAST_THE_END), "--bake-only"])

        # Assert
        assert code == bake.OVERRAN
        assert (build / cartridge.REPORT_NAME).is_file()
        assert "at q17 not even one second of this film fits" in capsys.readouterr().err

    def test_a_search_that_fits_nowhere_writes_the_cheapest_rung_and_what_fits(
        self, movie, tmp_path, capsys
    ):
        # Arrange
        store = tmp_path / "tiers.json"
        remember_rates(store, movie, 0.2, dict.fromkeys(tier.name for tier in quality.LADDER))
        argv = [*plain(movie), "--duration", "0.2", "--tier-cache", str(store)]

        # Act
        code = cartridge.main([*argv, "--build-dir", str(tmp_path / "out")])

        # Assert
        assert code == cartridge.NO_TIER_FITS
        assert json.loads((tmp_path / "out" / cartridge.REPORT_NAME).read_text())["frames"] > 0
        assert "this source fits no tier; at q35 not even one second" in capsys.readouterr().err


class TestFlagsReachTheBake:
    def test_silent_leaves_sound_out(self, tone, tmp_path, capsys):
        # Arrange
        argv = named(tone, tmp_path / "out", "--duration", "0.2", "--silent")

        # Act
        code = cartridge.main([*argv, "--bake-only"])

        # Assert
        assert code == 0
        assert last_report(capsys.readouterr().out)["has_audio"] is False

    def test_a_bundle_is_written_where_asked(self, movie, tmp_path):
        # Arrange
        drop_in = tmp_path / "drop-in"

        # Act
        cartridge.main([*named(movie, tmp_path / "out", "--bundle", str(drop_in)), "--bake-only"])

        # Assert
        assert (drop_in / "fmv.mk").is_file()

    def test_the_seek_spacing_reaches_the_header(self, movie, tmp_path):
        # Arrange
        build = tmp_path / "out"

        # Act
        cartridge.main([*named(movie, build, "--seek-every", "2"), "--bake-only"])

        # Assert
        assert "#define MOVIE_SEEK_FRAMES 118u\n" in header(build)

    def test_a_dither_strength_reaches_the_bake(self, movie, tmp_path, capsys):
        # Arrange
        argv = named(movie, tmp_path / "out", "--dither", "0.25")

        # Act
        cartridge.main([*argv, "--bake-only"])

        # Assert
        assert last_report(capsys.readouterr().out)["dither"] == 0.25

    def test_the_fit_flag_is_gone(self, movie, tmp_path):
        # Arrange
        argv = named(movie, tmp_path / "out", "--fit", "fill")

        # Act
        with pytest.raises(SystemExit) as refused:
            cartridge.main(argv)

        # Assert
        assert refused.value.code == 2

    def test_a_png_preview_holds_four_frames_beside_their_source(self, movie, tmp_path):
        # Arrange
        still = tmp_path / "preview.png"

        # Act
        cartridge.main([*named(movie, tmp_path / "out", "--preview", str(still)), "--bake-only"])

        # Assert
        assert png_size(still) == (STILL_WIDTH, STILL_ROWS * RASTER_HEIGHT)
