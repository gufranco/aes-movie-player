from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from aesmovie import cartridge, frames, tiercache


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
        cartridge.main([str(movie), "--quality", "q17"])

        argv = recorded["bake"]

        assert "--source" in argv
        assert argv[argv.index("--source") + 1] == str(movie)

    def test_it_forwards_an_explicit_subtitle_file(self, movie, captions, recorded):
        cartridge.main([str(movie), "--quality", "q17", "--subtitles", str(captions)])

        argv = recorded["bake"]

        assert argv[argv.index("--subtitles") + 1] == str(captions)

    def test_a_named_tier_is_forwarded_instead(self, movie, recorded):
        cartridge.main([str(movie), "--quality", "q20"])

        argv = recorded["bake"]

        assert argv[argv.index("--quality") + 1] == "q20"

    def test_no_duration_is_passed_when_the_whole_film_is_wanted(self, movie, recorded):
        cartridge.main([str(movie), "--quality", "q17"])

        assert "--duration" not in recorded["bake"]

    def test_a_trim_is_forwarded(self, movie, recorded):
        cartridge.main([str(movie), "--quality", "q17", "--start", "12", "--duration", "300"])

        argv = recorded["bake"]

        assert argv[argv.index("--start") + 1] == "12.0"
        assert argv[argv.index("--duration") + 1] == "300.0"


class TestCartridgeBuild:
    def test_it_runs_the_build_after_a_good_bake(self, movie, recorded):
        code = cartridge.main([str(movie), "--quality", "q17"])

        assert code == 0
        assert "build-in-docker.sh" in " ".join(recorded["build"])

    def test_the_build_is_told_which_directory_to_use(self, movie, tmp_path, recorded):
        cartridge.main([str(movie), "--quality", "q17", "--build-dir", str(tmp_path / "out")])

        assert recorded["env"]["BUILD"] == str(tmp_path / "out")

    def test_bake_only_stops_before_the_build(self, movie, recorded):
        code = cartridge.main([str(movie), "--quality", "q17", "--bake-only"])

        assert code == 0
        assert "build" not in recorded

    def test_a_failed_bake_skips_the_build(self, movie, monkeypatch, recorded):
        monkeypatch.setattr(cartridge.bake, "main", lambda _argv: 3)

        code = cartridge.main([str(movie), "--quality", "q17"])

        assert code == 3
        assert "build" not in recorded


class TestReporting:
    def test_it_reports_the_cartridge_path_on_success(self, movie, tmp_path, recorded, capsys):
        out = tmp_path / "out"
        out.mkdir()
        (out / "aesmovie.neo").write_bytes(b"")

        cartridge.main([str(movie), "--quality", "q17", "--build-dir", str(out)])

        assert "build" in recorded
        assert "aesmovie.neo" in capsys.readouterr().out


class TestSearchingForTheTier:
    def test_search_resolves_to_a_concrete_tier_before_baking(self, movie, recorded, monkeypatch):
        monkeypatch.setattr(
            cartridge.probe,
            "search",
            lambda **_k: cartridge.probe.Outcome(
                tier=cartridge.quality.tier_by_name("q19"), minutes=10.0
            ),
        )
        monkeypatch.setattr(cartridge.frames, "probe", lambda *_a, **_k: _stub_info())

        cartridge.main([str(movie), "--quality", "search"])

        argv = recorded["bake"]

        assert argv[argv.index("--quality") + 1] == "q19"

    def test_a_source_that_fits_nowhere_is_refused_rather_than_trimmed(
        self, movie, recorded, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            cartridge.probe,
            "search",
            lambda **_k: cartridge.probe.Outcome(tier=None, minutes=10.0),
        )
        monkeypatch.setattr(cartridge.frames, "probe", lambda *_a, **_k: _stub_info())

        code = cartridge.main([str(movie), "--quality", "search"])

        assert code != 0
        assert "bake" not in recorded
        assert "fits" in capsys.readouterr().err


def _stub_info():
    return frames.VideoInfo(width=1280, height=720, duration=600.0, fps=Fraction(24, 1))


def _reading_bake(monkeypatch, *, tiles, full=False, exceeded=False, status=0, write_report=True):
    """Stand in for a bake that reports what it spent."""
    seen: list[str] = []

    def fake_bake(argv):
        tier = argv[argv.index("--quality") + 1]
        seen.append(tier)
        if "--report-json" in argv and write_report:
            report = Path(argv[argv.index("--report-json") + 1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps(
                    {
                        "tile_count": tiles(tier),
                        "dictionary_full": full,
                        "budget_exceeded": exceeded,
                    }
                )
            )
        return status

    monkeypatch.setattr(cartridge.bake, "main", fake_bake)
    monkeypatch.setattr(cartridge.frames, "probe", lambda *_a, **_k: _stub_info())
    return seen


class TestMeasuringARung:
    def test_a_finished_bake_becomes_a_rate(self, tmp_path, movie, monkeypatch):
        store = tmp_path / "tiers.json"
        _reading_bake(monkeypatch, tiles=lambda _t: 1_000)

        cartridge.main(
            [
                str(movie),
                "--quality",
                "search",
                "--tier-cache",
                str(store),
                "--build-dir",
                str(tmp_path / "out"),
                "--bake-only",
                "--duration",
                "60",
            ]
        )

        rates = tiercache.recall(store, next(iter(json.loads(store.read_text())["sources"])))

        assert rates
        assert all(rate == pytest.approx(1_000.0) for rate in rates.values())

    def test_a_bake_that_refuses_is_remembered_as_a_refusal(
        self, tmp_path, movie, monkeypatch, capsys
    ):
        store = tmp_path / "tiers.json"
        _reading_bake(monkeypatch, tiles=lambda _t: 5, full=True, status=cartridge.bake.OVERRAN)

        code = cartridge.main(
            [
                str(movie),
                "--quality",
                "search",
                "--tier-cache",
                str(store),
                "--build-dir",
                str(tmp_path / "out"),
                "--bake-only",
                "--duration",
                "60",
            ]
        )

        rates = tiercache.recall(store, next(iter(json.loads(store.read_text())["sources"])))

        assert code != 0
        assert set(rates.values()) == {None}
        assert "fits no tier" in capsys.readouterr().err

    def test_a_bake_that_leaves_no_report_counts_as_a_refusal(self, tmp_path, movie, monkeypatch):
        store = tmp_path / "tiers.json"
        _reading_bake(monkeypatch, tiles=lambda _t: 1, write_report=False)

        code = cartridge.main(
            [
                str(movie),
                "--quality",
                "search",
                "--tier-cache",
                str(store),
                "--build-dir",
                str(tmp_path / "out"),
                "--bake-only",
                "--duration",
                "60",
            ]
        )

        assert code != 0

    def test_an_exceeded_budget_counts_as_a_refusal_even_on_a_clean_exit(
        self, tmp_path, movie, monkeypatch
    ):
        store = tmp_path / "tiers.json"
        _reading_bake(monkeypatch, tiles=lambda _t: 9, exceeded=True, status=0)

        code = cartridge.main(
            [
                str(movie),
                "--quality",
                "search",
                "--tier-cache",
                str(store),
                "--build-dir",
                str(tmp_path / "out"),
                "--bake-only",
                "--duration",
                "60",
            ]
        )

        assert code != 0

    def test_each_rung_is_measured_in_its_own_directory(self, tmp_path, movie, monkeypatch):
        store = tmp_path / "tiers.json"
        directories: list[str] = []

        def fake_bake(argv):
            if "--report-json" not in argv:
                return 0
            directories.append(argv[argv.index("--build-dir") + 1])
            report = Path(argv[argv.index("--report-json") + 1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps({"tile_count": 1, "dictionary_full": False, "budget_exceeded": False})
            )
            return 0

        monkeypatch.setattr(cartridge.bake, "main", fake_bake)
        monkeypatch.setattr(cartridge.frames, "probe", lambda *_a, **_k: _stub_info())

        cartridge.main(
            [
                str(movie),
                "--quality",
                "search",
                "--tier-cache",
                str(store),
                "--build-dir",
                str(tmp_path / "out"),
                "--bake-only",
                "--duration",
                "60",
            ]
        )

        assert len(set(directories)) == len(directories)


class TestTheDefaultIsMeasured:
    def test_naming_no_rung_settles_it_by_baking(self, movie, monkeypatch):
        asked: list[str] = []
        monkeypatch.setattr(
            cartridge.probe,
            "search",
            lambda **_k: (
                asked.append("searched") or cartridge.probe.Outcome(tier=None, minutes=1.0)
            ),
        )
        monkeypatch.setattr(cartridge.frames, "probe", lambda *_a, **_k: _stub_info())

        cartridge.main([str(movie)])

        assert asked == ["searched"]

    def test_a_named_rung_is_taken_as_given(self, movie, recorded):
        cartridge.main([str(movie), "--quality", "q20"])

        argv = recorded["bake"]

        assert argv[argv.index("--quality") + 1] == "q20"


class TestTheSearchKnowsTheSource:
    def test_it_passes_the_source_rate_so_unreachable_rungs_are_never_baked(
        self, movie, tmp_path, monkeypatch
    ):
        seen: dict[str, object] = {}

        def capture(**kwargs):
            seen.update(kwargs)
            return cartridge.probe.Outcome(tier=cartridge.quality.tier_by_name("q17"), minutes=1.0)

        monkeypatch.setattr(cartridge.probe, "search", capture)
        monkeypatch.setattr(cartridge.frames, "probe", lambda *_a, **_k: _stub_info())
        monkeypatch.setattr(cartridge.bake, "main", lambda _argv: 0)
        monkeypatch.setattr(cartridge.subprocess, "run", lambda *_a, **_k: None)

        cartridge.main([str(movie), "--tier-cache", str(tmp_path / "t.json"), "--bake-only"])

        assert seen["source_fps"] == pytest.approx(24.0)
        assert seen["vblank_fps"] == pytest.approx(float(frames.VBLANK_FPS))
