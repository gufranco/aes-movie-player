"""Plan command tests.

The plan command is the surface a person reads before deciding whether
to trim a source, so it is driven end to end against a real clip.
"""

from __future__ import annotations

import subprocess

import pytest

from aesmovie import plan, quality


@pytest.fixture(scope="module")
def synthetic_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("plan") / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x480:rate=24:duration=8",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


class TestPlanCommand:
    def run(self, clip, capsys):
        code = plan.main(["--source", str(clip), "--samples", "2", "--sample-seconds", "1"])
        return code, capsys.readouterr().out

    def test_it_succeeds_on_a_real_source(self, synthetic_clip, capsys):
        code, _ = self.run(synthetic_clip, capsys)

        assert code == 0

    def test_it_prints_the_ladder(self, synthetic_clip, capsys):
        _, out = self.run(synthetic_clip, capsys)

        assert "Quality ladder" in out
        assert quality.LADDER[0].name in out
        assert quality.LADDER[-1].name in out

    def test_it_prints_the_measured_rate(self, synthetic_clip, capsys):
        _, out = self.run(synthetic_clip, capsys)

        assert "tiles per minute" in out

    def test_it_prints_the_cartridge_budget(self, synthetic_clip, capsys):
        _, out = self.run(synthetic_clip, capsys)

        assert "C-ROM" in out

    def test_it_names_the_source(self, synthetic_clip, capsys):
        _, out = self.run(synthetic_clip, capsys)

        assert "source.mp4" in out
