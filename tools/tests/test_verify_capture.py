from __future__ import annotations

import importlib.util
import subprocess
import subprocess as sp
from pathlib import Path

import numpy as np
import pytest

from aesmovie import bake as baker

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_capture.py"
_spec = importlib.util.spec_from_file_location("verify_capture", SCRIPT)
assert _spec is not None and _spec.loader is not None
verify_capture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_capture)

WIDTH = 320
HEIGHT = 224
OVERSCAN = 8


def make_frames(count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(count, HEIGHT, WIDTH, 3), dtype=np.uint8)


def write_lossless(path: Path, frames: np.ndarray) -> None:
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            "60",
            "-i",
            "-",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "rgb24",
            str(path),
        ],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    process.stdin.write(frames.tobytes())
    process.stdin.close()
    assert process.wait() == 0


def write_png(path: Path, image: np.ndarray) -> None:
    height, width = image.shape[:2]
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-i",
            "-",
            "-frames:v",
            "1",
            str(path),
        ],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    process.stdin.write(image.tobytes())
    process.stdin.close()
    assert process.wait() == 0


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    directory = tmp_path_factory.mktemp("verify")
    frames = make_frames(6, seed=17)
    preview = directory / "preview.mkv"
    write_lossless(preview, frames)
    return frames, preview, directory


class TestDecoding:
    def test_the_preview_decodes_back_to_the_written_frames(self, rendered):
        frames, preview, _ = rendered

        decoded = verify_capture.decode_preview(preview)

        assert np.array_equal(decoded, frames)

    def test_a_capture_decodes_at_its_own_geometry(self, rendered):
        frames, _, directory = rendered
        capture = directory / "shot.png"
        write_png(capture, frames[2][:, OVERSCAN : WIDTH - OVERSCAN])

        decoded = verify_capture.decode_capture(capture)

        assert decoded.shape == (HEIGHT, WIDTH - 2 * OVERSCAN, 3)


class TestMatching:
    def run_main(self, capture: Path, preview: Path, **kwargs) -> int:
        argv = ["--capture", str(capture), "--preview", str(preview)]
        for key, value in kwargs.items():
            argv += [f"--{key.replace('_', '-')}", str(value)]
        return verify_capture.main(argv)

    def test_an_exact_capture_passes(self, rendered, capsys):
        frames, preview, directory = rendered
        capture = directory / "exact.png"
        write_png(capture, frames[3][:, OVERSCAN : WIDTH - OVERSCAN])

        code = self.run_main(capture, preview)

        assert code == 0
        assert "exact pixel match: True" in capsys.readouterr().out

    def test_it_reports_which_frame_matched(self, rendered, capsys):
        frames, preview, directory = rendered
        capture = directory / "which.png"
        write_png(capture, frames[4][:, OVERSCAN : WIDTH - OVERSCAN])

        self.run_main(capture, preview)

        assert "rendered frame 4" in capsys.readouterr().out

    def test_an_unrelated_capture_fails(self, rendered):
        _, preview, directory = rendered
        capture = directory / "unrelated.png"
        write_png(capture, make_frames(1, seed=999)[0][:, OVERSCAN : WIDTH - OVERSCAN])

        assert self.run_main(capture, preview) == 1

    def test_a_wrongly_sized_capture_is_rejected(self, rendered):
        _, preview, directory = rendered
        capture = directory / "wrong.png"
        write_png(capture, make_frames(1, seed=5)[0])

        assert self.run_main(capture, preview) == 2

    def test_a_capture_with_the_wrong_line_count_is_rejected(self, rendered):
        _, preview, directory = rendered
        capture = directory / "short.png"
        write_png(capture, make_frames(1, seed=6)[0][:100, OVERSCAN : WIDTH - OVERSCAN])

        assert self.run_main(capture, preview) == 2


class TestUpscaledCaptures:
    def test_an_integer_upscaled_capture_is_reduced_to_the_active_area(self):
        frame = make_frames(1, seed=31)[0][:, OVERSCAN : WIDTH - OVERSCAN]
        upscaled = np.repeat(np.repeat(frame, 6, axis=0), 6, axis=1)

        reduced = verify_capture.downscale_capture(upscaled)

        assert np.array_equal(reduced, frame)

    def test_a_native_capture_is_left_alone(self):
        frame = make_frames(1, seed=32)[0][:, OVERSCAN : WIDTH - OVERSCAN]

        assert np.array_equal(verify_capture.downscale_capture(frame), frame)

    def test_an_upscaled_capture_still_matches_its_rendered_frame(self, rendered, capsys):
        frames, preview, directory = rendered
        capture = directory / "upscaled.png"
        frame = frames[1][:, OVERSCAN : WIDTH - OVERSCAN]
        write_png(capture, np.repeat(np.repeat(frame, 3, axis=0), 3, axis=1))

        code = verify_capture.main(["--capture", str(capture), "--preview", str(preview)])

        assert code == 0
        assert "rendered frame 1" in capsys.readouterr().out


class TestReconstruction:
    def bake(self, tmp_path):
        source = tmp_path / "src.mp4"
        sp.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=640x360:rate=24:duration=1",
                "-pix_fmt",
                "yuv420p",
                str(source),
            ],
            check=True,
        )
        build = tmp_path / "build"
        return baker.run(
            baker.BakeRequest(
                source=source,
                start=0.0,
                duration=0.2,
                build_dir=build,
                palette_count=8,
                candidates=0,
                sample_stride=1,
                preview=tmp_path / "ref.mkv",
            )
        )

    def test_reconstruction_matches_the_rendered_preview(self, tmp_path):
        outcome = self.bake(tmp_path)
        frame = outcome.result.stats.frames - 1

        rebuilt = verify_capture.reconstruct_frame(outcome.build_dir / "baked", frame)

        reference = verify_capture.decode_preview(tmp_path / "ref.mkv")[frame]
        assert np.array_equal(rebuilt, reference)

    def test_reconstruction_matches_at_an_intermediate_frame(self, tmp_path):
        outcome = self.bake(tmp_path)

        rebuilt = verify_capture.reconstruct_frame(outcome.build_dir / "baked", 3)

        reference = verify_capture.decode_preview(tmp_path / "ref.mkv")[3]
        assert np.array_equal(rebuilt, reference)

    def test_a_capture_verifies_against_the_baked_artifacts(self, tmp_path, capsys):
        outcome = self.bake(tmp_path)
        frame = 5
        rebuilt = verify_capture.reconstruct_frame(outcome.build_dir / "baked", frame)
        capture = tmp_path / "shot.png"
        write_png(capture, rebuilt[:, OVERSCAN : WIDTH - OVERSCAN])

        code = verify_capture.main(
            [
                "--capture",
                str(capture),
                "--baked",
                str(outcome.build_dir / "baked"),
                "--frame",
                str(frame),
            ]
        )

        assert code == 0
        assert "exact pixel match: True" in capsys.readouterr().out

    def test_verifying_without_a_reference_is_rejected(self, tmp_path):
        capture = tmp_path / "lonely.png"
        write_png(capture, make_frames(1, seed=8)[0][:, OVERSCAN : WIDTH - OVERSCAN])

        with pytest.raises(SystemExit):
            verify_capture.main(["--capture", str(capture)])
