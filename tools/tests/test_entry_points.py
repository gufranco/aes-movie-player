from __future__ import annotations

import runpy
import shutil
import sys
from pathlib import Path

import pytest

from tests.test_integrate import project_at

ROOT = Path(__file__).resolve().parents[2]
HELP_ENTRY_POINTS = (
    "tools/neogeomedia/bake.py",
    "tools/neogeomedia/cartridge.py",
    "tools/neogeomedia/mamecart.py",
    "tools/neogeomedia/neofile.py",
    "tools/neogeomedia/plan.py",
    "tools/scripts/capture_rom.py",
    "tools/scripts/check_vram_timing.py",
    "tools/scripts/compare_capture.py",
    "tools/scripts/fetch_clips.py",
    "tools/scripts/measure_audio.py",
    "tools/scripts/measure_drift.py",
    "tools/scripts/sweep_ladder.py",
    "tools/scripts/verify_capture.py",
)


def run_as_main(entry: str, *argv: str, monkeypatch: pytest.MonkeyPatch) -> int | str | None:
    monkeypatch.setattr(sys, "argv", [entry, *argv])
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(str(ROOT / entry), run_name="__main__")
    return exited.value.code


@pytest.mark.parametrize("entry", HELP_ENTRY_POINTS)
def test_running_the_file_reaches_its_command_line(entry, monkeypatch, capsys):
    # Arrange
    flag = "--help"

    # Act
    code = run_as_main(entry, flag, monkeypatch=monkeypatch)

    # Assert
    assert (code, "usage:" in capsys.readouterr().out) == (0, True)


def test_running_the_stamp_file_restamps_a_header(tmp_path, monkeypatch):
    # Arrange
    header = tmp_path / "fmv.h"
    shutil.copyfile(ROOT / "src" / "fmv" / "fmv.h", header)

    # Act
    code = run_as_main("tools/neogeomedia/stamp.py", str(header), monkeypatch=monkeypatch)

    # Assert
    assert code == 0


def test_running_the_integrate_file_edits_a_project(tmp_path, monkeypatch):
    # Arrange
    project = project_at(tmp_path)
    before = (project / "rom.mk").read_text()

    # Act
    code = run_as_main("tools/neogeomedia/integrate.py", str(project), monkeypatch=monkeypatch)

    # Assert
    assert (code, (project / "rom.mk").read_text() != before) == (0, True)
