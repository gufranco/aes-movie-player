from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from neogeomedia import tiercache
from tests.bakehelp import lavfi_clip

FRAME = "size=160x120:rate=24"
TWO_TONE = (
    f"color=c=black:{FRAME}:duration=0.5[dark];"
    f"color=c=white:{FRAME}:duration=0.5[light];"
    "[dark][light]concat=n=2:v=1:a=0"
)
DOCKER_LOG = "docker.log"
MEDIA_TOOLS = ("ffmpeg", "ffprobe")
SYSTEM_PATH = ("/usr/bin", "/bin")
HOST_COMPILER = "m68k-neogeo-elf-gcc"
PLAIN_DITHER = 0.0


def plain(source: Path) -> list[str]:
    return [str(source), "--dither", str(PLAIN_DITHER)]


def short_clip(path: Path) -> Path:
    return lavfi_clip(path, f"testsrc={FRAME}:duration=0.2")


def two_tone_clip(path: Path) -> Path:
    return lavfi_clip(path, TWO_TONE)


def fake_docker(monkeypatch: pytest.MonkeyPatch, directory: Path, *, status: int = 0) -> Path:
    shim = directory / "shim"
    shim.mkdir()
    log = directory / DOCKER_LOG
    script = shim / "docker"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{log}'\nexit {status}\n")
    script.chmod(0o755)
    for tool in MEDIA_TOOLS:
        (shim / tool).symlink_to(str(shutil.which(tool)))
    monkeypatch.setenv("PATH", ":".join([str(shim), *SYSTEM_PATH]))
    monkeypatch.delenv("NEOGEOMEDIA_TOOLCHAIN_IMAGE", raising=False)
    monkeypatch.delenv("NEOGEOMEDIA_IN_TOOLCHAIN_IMAGE", raising=False)
    return log


def fake_host_compiler(directory: Path) -> None:
    compiler = directory / "shim" / HOST_COMPILER
    compiler.write_text("#!/bin/sh\nexit 1\n")
    compiler.chmod(0o755)


def last_report(stdout: str) -> dict[str, object]:
    decoder = json.JSONDecoder()
    start = stdout.rindex('{\n  "frames"')
    report, _ = decoder.raw_decode(stdout, start)
    return dict(report)


def header(build: Path) -> str:
    return (build / "generated" / "movie_data.h").read_text()


def preview_pixels(path: Path) -> np.ndarray:
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, np.uint8)


def cache_key(source: Path, duration: float) -> str:
    params = tiercache.Params(
        start=0.0, duration=duration, denoise=0.0, frame_hold=1, dither=PLAIN_DITHER
    )
    return tiercache.key_for(source, params)


def remember_rates(
    store: Path, source: Path, duration: float, rates: dict[str, float | None]
) -> str:
    key = cache_key(source, duration)
    for name, rate in rates.items():
        tiercache.remember(store, key, name, rate)
    return key
