from __future__ import annotations

import subprocess

import pytest

from aesmovie import cartridge


@pytest.fixture
def movie(tmp_path):
    path = tmp_path / "my movie.mkv"
    path.write_bytes(b"")
    return path


@pytest.fixture
def captions(tmp_path):
    path = tmp_path / "captions.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHELLO\n", encoding="utf-8")
    return path


@pytest.fixture
def recorded(monkeypatch):
    calls: dict[str, object] = {}

    def fake_bake(argv):
        calls["bake"] = list(argv)
        return 0

    def fake_run(command, **kwargs):
        calls["build"] = list(command)
        calls["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cartridge.bake, "main", fake_bake)
    monkeypatch.setattr(cartridge.subprocess, "run", fake_run)
    return calls


class TestSourceValidation:
    def test_a_missing_source_is_named_in_the_error(self, tmp_path, capsys):
        code = cartridge.main([str(tmp_path / "absent.mkv")])

        assert code != 0
        assert "absent.mkv" in capsys.readouterr().err

    def test_a_missing_subtitle_file_is_named_in_the_error(self, movie, tmp_path, capsys):
        code = cartridge.main([str(movie), "--subtitles", str(tmp_path / "absent.srt")])

        assert code != 0
        assert "absent.srt" in capsys.readouterr().err

    def test_a_directory_given_as_the_source_is_rejected(self, tmp_path, capsys):
        code = cartridge.main([str(tmp_path)])

        assert code != 0
        assert capsys.readouterr().err != ""


class TestBakeInvocation:
    def test_it_forwards_the_source(self, movie, recorded):
        cartridge.main([str(movie)])

        argv = recorded["bake"]

        assert "--source" in argv
        assert argv[argv.index("--source") + 1] == str(movie)

    def test_it_forwards_an_explicit_subtitle_file(self, movie, captions, recorded):
        cartridge.main([str(movie), "--subtitles", str(captions)])

        argv = recorded["bake"]

        assert argv[argv.index("--subtitles") + 1] == str(captions)

    def test_it_asks_for_the_automatic_tier_by_default(self, movie, recorded):
        cartridge.main([str(movie)])

        argv = recorded["bake"]

        assert argv[argv.index("--quality") + 1] == "auto"

    def test_a_named_tier_is_forwarded_instead(self, movie, recorded):
        cartridge.main([str(movie), "--quality", "q20"])

        argv = recorded["bake"]

        assert argv[argv.index("--quality") + 1] == "q20"

    def test_no_duration_is_passed_when_the_whole_film_is_wanted(self, movie, recorded):
        cartridge.main([str(movie)])

        assert "--duration" not in recorded["bake"]

    def test_a_trim_is_forwarded(self, movie, recorded):
        cartridge.main([str(movie), "--start", "12", "--duration", "300"])

        argv = recorded["bake"]

        assert argv[argv.index("--start") + 1] == "12.0"
        assert argv[argv.index("--duration") + 1] == "300.0"


class TestCartridgeBuild:
    def test_it_runs_the_build_after_a_good_bake(self, movie, recorded):
        code = cartridge.main([str(movie)])

        assert code == 0
        assert "build-in-docker.sh" in " ".join(recorded["build"])

    def test_the_build_is_told_which_directory_to_use(self, movie, tmp_path, recorded):
        cartridge.main([str(movie), "--build-dir", str(tmp_path / "out")])

        assert recorded["env"]["BUILD"] == str(tmp_path / "out")

    def test_bake_only_stops_before_the_build(self, movie, recorded):
        code = cartridge.main([str(movie), "--bake-only"])

        assert code == 0
        assert "build" not in recorded

    def test_a_failed_bake_skips_the_build(self, movie, monkeypatch, recorded):
        monkeypatch.setattr(cartridge.bake, "main", lambda _argv: 3)

        code = cartridge.main([str(movie)])

        assert code == 3
        assert "build" not in recorded


class TestReporting:
    def test_it_reports_the_cartridge_path_on_success(self, movie, tmp_path, recorded, capsys):
        out = tmp_path / "out"
        out.mkdir()
        (out / "aesmovie.neo").write_bytes(b"")

        cartridge.main([str(movie), "--build-dir", str(out)])

        assert "build" in recorded
        assert "aesmovie.neo" in capsys.readouterr().out
