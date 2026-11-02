from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from fmvcore import video

from neogeomedia import encode, neocolor, preview


class TestPreviewWriter:
    @pytest.mark.ffmpeg
    def test_frames_written_come_back_out_of_a_lossless_preview(self, tmp_path):
        # Arrange
        rng = np.random.default_rng(7)
        shape = (encode.FRAME_HEIGHT, encode.FRAME_WIDTH)
        frame = rng.integers(0, 1 << 15, size=shape, dtype=np.uint16)
        path = tmp_path / "nested" / "preview.mkv"
        writer = preview.PreviewWriter(path)
        writer.write(frame)

        # Act
        writer.close()

        # Assert
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True,
            check=True,
        ).stdout
        decoded = np.frombuffer(raw, np.uint8).reshape(-1, *shape, 3)
        assert np.array_equal(decoded[0], neocolor.color_index_to_rgb(frame))

    @pytest.mark.ffmpeg
    def test_frames_past_the_checked_ones_are_still_written(self, tmp_path):
        # Arrange
        shape = (encode.FRAME_HEIGHT, encode.FRAME_WIDTH)
        path = tmp_path / "long.mkv"
        writer = preview.PreviewWriter(path)
        for level in range(preview.CHECKED_FRAMES + 1):
            writer.write(np.full(shape, level, dtype=np.uint16))

        # Act
        writer.close()

        # Assert
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True,
            check=True,
        ).stdout
        assert len(raw) == (preview.CHECKED_FRAMES + 1) * shape[0] * shape[1] * 3

    @pytest.mark.ffmpeg
    def test_an_mp4_preview_is_enlarged_and_checked(self, tmp_path):
        # Arrange
        rng = np.random.default_rng(7)
        shape = (encode.FRAME_HEIGHT, encode.FRAME_WIDTH)
        path = tmp_path / "preview.mp4"
        writer = preview.PreviewWriter(path)
        writer.write(rng.integers(0, 1 << 15, size=shape, dtype=np.uint16))

        # Act
        writer.close()

        # Assert
        factor = video.enlargement(preview.PICTURE)
        size = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert size == f"{encode.FRAME_WIDTH * factor},{encode.FRAME_HEIGHT * factor}"

    @pytest.mark.ffmpeg
    def test_a_preview_ffmpeg_cannot_write_is_an_error(self, tmp_path):
        # Arrange
        writer = preview.PreviewWriter(tmp_path / "preview.not-a-container")

        # Act
        with pytest.raises(RuntimeError) as raised:
            writer.close()

        # Assert
        assert "preview.not-a-container" in str(raised.value)


def still_pixels(path: Path) -> np.ndarray:
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, np.uint8)


class TestPicks:
    @pytest.mark.parametrize(
        ("total", "expected"),
        [(0, ()), (1, (0,)), (3, (0, 1, 2)), (10, (0, 3, 6, 9))],
        ids=["empty", "one", "fewer-than-four", "spread"],
    )
    def test_four_frames_are_spread_across_the_film(self, total, expected):
        # Arrange
        frames_in_film = total

        # Act
        chosen = preview.picks(frames_in_film)

        # Assert
        assert chosen == expected


class TestStillWriter:
    def test_each_row_holds_the_console_frame_beside_its_source(self, tmp_path):
        # Arrange
        rng = np.random.default_rng(11)
        shape = (encode.FRAME_HEIGHT, encode.FRAME_WIDTH)
        shown = rng.integers(0, 1 << 15, size=(2, *shape), dtype=np.uint16)
        sources = rng.integers(0, 256, size=(2, *shape, 3), dtype=np.uint8)
        path = tmp_path / "nested" / "still.png"
        writer = preview.open_writer(path, 2)
        list(writer.watch([sources[:1], sources[1:]]))
        for frame in shown:
            writer.write(frame)

        # Act
        writer.close()

        # Assert
        image = still_pixels(path).reshape(2 * shape[0], 2 * shape[1], 3)
        for row in range(2):
            band = image[row * shape[0] : (row + 1) * shape[0]]
            assert np.array_equal(band[:, : shape[1]], neocolor.color_index_to_rgb(shown[row]))
            assert np.array_equal(band[:, shape[1] :], sources[row])

    def test_a_still_with_no_frames_is_an_error(self, tmp_path):
        # Arrange
        writer = preview.open_writer(tmp_path / "still.png", 0)

        # Act
        with pytest.raises(ValueError, match="at least one frame") as raised:
            writer.close()

        # Assert
        assert not (tmp_path / "still.png").exists()
        assert "one source frame" in str(raised.value)

    def test_a_video_preview_watches_without_touching_the_frames(self, video_writer):
        # Arrange
        chunks = [np.zeros((1, 2, 2, 3), dtype=np.uint8)]

        # Act
        watched = video_writer.watch(chunks)

        # Assert
        assert watched is chunks


@pytest.fixture
def video_writer(tmp_path):
    writer = preview.open_writer(tmp_path / "preview.mkv", 1)
    yield writer
    writer.write(np.zeros((encode.FRAME_HEIGHT, encode.FRAME_WIDTH), dtype=np.uint16))
    writer.close()
