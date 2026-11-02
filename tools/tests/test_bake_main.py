from __future__ import annotations

import json
import subprocess

import pytest

from neogeomedia import bake, bundle, soundtrack
from tests.bakehelp import SYNTHETIC_FILM, small_argv, tone_clip
from tests.cartridgehelp import header, last_report

pytestmark = pytest.mark.ffmpeg


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    return tone_clip(tmp_path_factory.mktemp("tone") / "tone.mp4")


class TestCommandLine:
    def test_main_writes_a_report_and_reports_success(self, synthetic_clip, tmp_path, capsys):
        # Arrange
        report = tmp_path / "report.json"
        argv = small_argv(synthetic_clip, tmp_path / "build", "--report-json", str(report))

        # Act
        code = bake.main(argv)

        # Assert
        assert code == 0
        assert json.loads(report.read_text())["frames"] == 11
        assert "tile_count" in capsys.readouterr().out

    def test_main_emits_a_bundle_when_asked_for_one(self, synthetic_clip, tmp_path, capsys):
        # Arrange
        drop_in = tmp_path / "drop-in"
        argv = small_argv(synthetic_clip, tmp_path / "build", "--bundle", str(drop_in))

        # Act
        code = bake.main(argv)

        # Assert
        assert code == 0
        assert (drop_in / "README.md").is_file()
        assert (drop_in / "fmv.mk").is_file()
        assert (drop_in / bundle.LIBRARY_DIR_NAME / "fmv.h").is_file()
        assert "drop-in bundle" in capsys.readouterr().err

    def test_the_fit_flag_is_gone_because_the_picture_always_fills(self, synthetic_clip, tmp_path):
        # Arrange
        argv = small_argv(synthetic_clip, tmp_path / "build", "--fit", "fill")

        # Act
        with pytest.raises(SystemExit) as refused:
            bake.main(argv)

        # Assert
        assert refused.value.code == 2


class TestSilent:
    def test_silent_leaves_the_soundtrack_out(self, tone, tmp_path, capsys):
        # Arrange
        build = tmp_path / "build"

        # Act
        code = bake.main(small_argv(tone, build, "--silent"))

        # Assert
        assert code == 0
        assert last_report(capsys.readouterr().out)["has_audio"] is False
        assert not (build / "baked" / soundtrack.VOICE_FILE).exists()

    def test_an_explicit_audio_rate_reaches_the_header(self, tone, tmp_path):
        # Arrange
        build = tmp_path / "build"

        # Act
        code = bake.main(small_argv(tone, build, "--audio-rate", "22050"))

        # Assert
        assert (code, "#define MOVIE_AUDIO_HZ 22050\n" in header(build)) == (0, True)

    def test_a_film_asked_to_be_silent_is_not_announced_as_soundless(self, tmp_path, capsys):
        # Arrange
        argv = small_argv(SYNTHETIC_FILM, tmp_path / "build", "--silent")

        # Act
        bake.main(argv)

        # Assert
        assert "carries no audio track" not in capsys.readouterr().err


class TestSeekEvery:
    @pytest.mark.parametrize(("extra", "frames"), [((), 592), (("--seek-every", "4"), 237)])
    def test_the_spacing_reaches_the_header_in_frames(
        self, synthetic_clip, tmp_path, extra, frames
    ):
        # Arrange
        build = tmp_path / "build"

        # Act
        bake.main(small_argv(synthetic_clip, build, *extra))

        # Assert
        header = (build / "generated" / "movie_data.h").read_text()
        assert f"#define MOVIE_SEEK_FRAMES {frames}u\n" in header

    @pytest.mark.parametrize("spacing", ["-1", "0"])
    def test_a_spacing_shorter_than_a_frame_is_refused(self, synthetic_clip, tmp_path, spacing):
        # Arrange
        argv = small_argv(synthetic_clip, tmp_path / "build", "--seek-every", spacing)

        # Act
        with pytest.raises(SystemExit) as refused:
            bake.main(argv)

        # Assert
        assert refused.value.code == 2


class TestDitherStrength:
    def test_a_strength_reaches_the_report(self, synthetic_clip, tmp_path, capsys):
        # Arrange
        argv = small_argv(synthetic_clip, tmp_path / "build", "--dither", "0.5")

        # Act
        bake.main(argv)

        # Assert
        assert last_report(capsys.readouterr().out)["dither"] == 0.5

    def test_the_default_is_full_dither(self, synthetic_clip, tmp_path, capsys):
        # Arrange
        argv = small_argv(synthetic_clip, tmp_path / "build")

        # Act
        bake.main(argv)

        # Assert
        assert last_report(capsys.readouterr().out)["dither"] == 1.0

    def test_a_strength_past_the_maximum_is_refused(self, synthetic_clip, tmp_path):
        # Arrange
        argv = small_argv(synthetic_clip, tmp_path / "build", "--dither", "1.5")

        # Act
        with pytest.raises(SystemExit) as refused:
            bake.main(argv)

        # Assert
        assert refused.value.code == 2


class TestReportNames:
    def test_shared_facts_carry_the_family_names(self, synthetic_clip, tmp_path, capsys):
        # Arrange
        argv = small_argv(synthetic_clip, tmp_path / "build")

        # Act
        bake.main(argv)

        # Assert
        report = last_report(capsys.readouterr().out)
        assert {"banks", "bytes", "fps", "bars", "seconds", "has_audio"} <= set(report)
        assert not {"stream_banks", "stream_bytes"} & set(report)
        assert report["fps"] == pytest.approx(59.185, abs=0.001)
        assert report["bars"] is None

    def test_an_overrun_writes_no_bundle(self, tmp_path):
        # Arrange
        drop_in = tmp_path / "drop-in"
        argv = small_argv(SYNTHETIC_FILM, tmp_path / "build", "--tile-budget", "1")

        # Act
        code = bake.main([*argv, "--bundle", str(drop_in)])

        # Assert
        assert code == bake.OVERRAN
        assert not drop_in.exists()


class TestBundleFromABake:
    def test_it_writes_a_bundle_from_a_finished_bake(self, baked, tmp_path):
        # Arrange
        target = tmp_path / "drop-in"

        # Act
        layout = bake.write_movie_bundle(target, baked)

        # Assert
        assert layout.guide.is_file()
        assert layout.makefile.is_file()
        assert (layout.library / "fmv.h").is_file()
        assert (layout.movie / "movie_data.h").is_file()

    def test_the_bundle_reports_what_the_bake_measured(self, baked, tmp_path):
        # Arrange
        stats = baked.result.stats

        # Act
        layout = bake.write_movie_bundle(tmp_path / "drop-in", baked)

        # Assert
        text = layout.guide.read_text()
        assert str(stats.max_updates) in text
        assert str(stats.tile_count) in text

    def test_the_bundle_carries_the_library_the_repository_holds(self, baked, tmp_path):
        # Arrange
        expected = (bundle.LIBRARY_ROOT / "fmv.c").read_text()

        # Act
        layout = bake.write_movie_bundle(tmp_path / "drop-in", baked)

        # Assert
        assert (layout.library / "fmv.c").read_text() == expected


class TestTheHeaderNamesTheRungActuallyUsed:
    def test_a_named_rung_is_what_the_header_records(self, tmp_path):
        # Arrange
        build = tmp_path / "build"
        argv = small_argv(SYNTHETIC_FILM, build, "--quality", "q07")

        # Act
        code = bake.main(argv)

        # Assert
        assert code == 0
        assert '#define MOVIE_TIER_NAME "Q07"' in (build / "generated" / "movie_data.h").read_text()

    def test_auto_is_refused_before_anything_is_baked(self, tmp_path):
        # Arrange
        build = tmp_path / "build"
        argv = small_argv(SYNTHETIC_FILM, build, "--quality", "auto")

        # Act
        with pytest.raises(SystemExit) as stopped:
            bake.main(argv)

        # Assert
        assert "search" in str(stopped.value)
        assert not build.exists()


class TestAnOverrunIsAFailure:
    @pytest.mark.parametrize(
        ("report", "expected"),
        [
            ({"dictionary_full": True, "budget_exceeded": False}, True),
            ({"dictionary_full": False, "budget_exceeded": True}, True),
            ({"truncated": True}, True),
            ({"dictionary_full": False, "budget_exceeded": False}, False),
            ({}, False),
        ],
    )
    def test_only_a_bake_that_ran_out_of_room_is_an_overrun(self, report, expected):
        # Arrange
        figures = dict(report)

        # Act
        overran = bake._overran(figures)

        # Assert
        assert overran is expected

    def test_the_overrun_code_is_distinct_from_every_other_failure(self):
        # Arrange
        others = (0, 1, 2, 3)

        # Act
        code = bake.OVERRAN

        # Assert
        assert code not in others

    def test_a_tile_budget_too_small_for_the_film_exits_with_the_overrun_code(self, tmp_path):
        # Arrange
        argv = small_argv(SYNTHETIC_FILM, tmp_path / "build", "--tile-budget", "1")

        # Act
        code = bake.main(argv)

        # Assert
        assert code == bake.OVERRAN


class TestASilentSourceSaysSo:
    def test_a_source_without_a_soundtrack_is_announced(self, tmp_path, capsys):
        # Arrange
        argv = small_argv(SYNTHETIC_FILM, tmp_path / "build")

        # Act
        code = bake.main(argv)

        # Assert
        assert code == 0
        assert "silent" in capsys.readouterr().err

    def test_a_source_with_a_soundtrack_says_nothing_about_it(self, tone, tmp_path, capsys):
        # Arrange
        argv = small_argv(tone, tmp_path / "build")

        # Act
        code = bake.main(argv)

        # Assert
        assert code == 0
        assert "silent" not in capsys.readouterr().err

    def test_an_unreadable_source_is_not_called_silent(self, tmp_path, capsys):
        # Arrange
        argv = small_argv(tmp_path / "absent.mkv", tmp_path / "build")

        # Act
        with pytest.raises((FileNotFoundError, subprocess.CalledProcessError)):
            bake.main(argv)

        # Assert
        assert "silent" not in capsys.readouterr().err
