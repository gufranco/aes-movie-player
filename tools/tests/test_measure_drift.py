from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def measure_drift():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("measure_drift", SCRIPTS / "measure_drift.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def flat_reconstruction(measure_drift, monkeypatch):
    """Stub the reconstruction so a test controls what each frame looks like."""
    painted: dict[int, int] = {}

    class Player:
        def __init__(self):
            self.step = -1

        def apply(self, _data, offset):
            self.step = offset

        def render(self, *_args):
            return np.full((224, 320), painted.get(self.step, 0), dtype=np.uint8)

    monkeypatch.setattr(measure_drift.vc, "StreamPlayer", Player)
    monkeypatch.setattr(measure_drift.vc, "GeolithTileReader", lambda *_args: object())
    monkeypatch.setattr(
        measure_drift.vc, "_palette_colors", lambda *_args: np.zeros((1, 15, 3), np.uint8)
    )
    monkeypatch.setattr(
        measure_drift.vc, "_epoch_palettes", lambda *_args: (0, np.zeros((1, 15, 3), np.uint8))
    )
    monkeypatch.setattr(
        measure_drift.neocolor,
        "color_index_to_rgb",
        lambda indexed: np.repeat(indexed[:, :, None], 3, axis=2).astype(np.uint8),
    )
    return painted


@pytest.fixture
def baked(tmp_path):
    """Six frames whose offsets are their own index, so a stub can key on them."""
    root = tmp_path / "baked"
    root.mkdir()
    (root / "stream.bin").write_bytes(b"")
    (root / "index.bin").write_bytes(struct.pack(">6I", 0, 1, 2, 3, 4, 5))
    (root / "c1.bin").write_bytes(b"")
    (root / "c2.bin").write_bytes(b"")
    (root / "palettes.bin").write_bytes(b"")
    return root


def _capture(measure_drift, monkeypatch, value):
    shot = np.full((224, 304, 3), value, dtype=np.uint8)
    monkeypatch.setattr(measure_drift.vc, "decode_capture", lambda *_args: shot)
    monkeypatch.setattr(measure_drift.vc, "downscale_capture", lambda image: image)


class TestFindingTheDisplayedFrame:
    def test_it_names_the_frame_the_capture_actually_shows(
        self, measure_drift, monkeypatch, baked, flat_reconstruction, capsys
    ):
        flat_reconstruction[3] = 200
        _capture(measure_drift, monkeypatch, 200)

        found = measure_drift.measure(baked, Path("shot.png"), 5, window=4, overscan=8)

        assert found == 3
        assert "2 frames behind" in capsys.readouterr().out

    def test_a_capture_on_time_reports_no_shortfall(
        self, measure_drift, monkeypatch, baked, flat_reconstruction, capsys
    ):
        flat_reconstruction[5] = 90
        _capture(measure_drift, monkeypatch, 90)

        found = measure_drift.measure(baked, Path("shot.png"), 5, window=4, overscan=8)

        assert found == 5
        assert "0 frames behind" in capsys.readouterr().out

    def test_it_scores_every_candidate_rather_than_the_first_plausible_one(
        self, measure_drift, monkeypatch, baked, flat_reconstruction
    ):
        flat_reconstruction[2] = 118
        flat_reconstruction[4] = 120
        _capture(measure_drift, monkeypatch, 120)

        found = measure_drift.measure(baked, Path("shot.png"), 5, window=5, overscan=8)

        assert found == 4


class TestWindowBounds:
    def test_a_window_reaching_before_the_start_is_clamped(
        self, measure_drift, monkeypatch, baked, flat_reconstruction
    ):
        flat_reconstruction[0] = 40
        _capture(measure_drift, monkeypatch, 40)

        assert measure_drift.measure(baked, Path("shot.png"), 2, window=60, overscan=8) == 0

    def test_a_window_reaching_past_the_end_is_clamped(
        self, measure_drift, monkeypatch, baked, flat_reconstruction
    ):
        flat_reconstruction[5] = 40
        _capture(measure_drift, monkeypatch, 40)

        assert measure_drift.measure(baked, Path("shot.png"), 5, window=60, overscan=8) == 5


class TestExitCode:
    def test_a_scan_that_matches_nothing_fails(self, measure_drift, monkeypatch):
        monkeypatch.setattr(measure_drift, "measure", lambda *_args, **_kwargs: None)

        assert measure_drift.main(["--capture", "shot.png", "--expected", "10"]) == 1

    def test_a_scan_that_finds_a_frame_succeeds(self, measure_drift, monkeypatch):
        monkeypatch.setattr(measure_drift, "measure", lambda *_args, **_kwargs: 4)

        assert measure_drift.main(["--capture", "shot.png", "--expected", "10"]) == 0
