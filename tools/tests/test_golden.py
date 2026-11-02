from __future__ import annotations

import numpy as np
import pytest
from fmvcore.testing import SEED

from neogeomedia import encode

HEIGHT = 224
WIDTH = 320
FRAME_COUNT = 24
GOLDEN_STREAM_BYTES = 27180
GOLDEN_TILES = 6067
GOLDEN_DISPLAYED_ERROR = 0.001310
GOLDEN_TOLERANCE = 0.005


def golden_clip() -> np.ndarray:
    rng = np.random.default_rng(SEED)
    rows, columns = np.mgrid[0:HEIGHT, 0:WIDTH]
    frames = []
    for index in range(FRAME_COUNT):
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.int16)
        frame[..., 0] = (columns + 6 * index) % 256
        frame[..., 1] = (rows * 2 + 3 * index) % 256
        frame[..., 2] = ((columns + rows) // 2) % 256
        frame[60:140, 40 + 8 * index : 120 + 8 * index] = (230, 40, 40)
        frame = frame + rng.integers(-5, 6, frame.shape)
        frames.append(np.clip(frame, 0, 255).astype(np.uint8))
    return np.stack(frames)


@pytest.fixture(scope="module")
def stats() -> encode.EncodeStats:
    return encode.encode(golden_clip(), encode.EncodeOptions(seed=0)).stats


class TestGoldenStream:
    def test_the_stream_keeps_its_blessed_size(self, stats):
        # Arrange
        expected = GOLDEN_STREAM_BYTES

        # Act
        measured = stats.stream_bytes

        # Assert
        assert measured == pytest.approx(expected, rel=GOLDEN_TOLERANCE)

    def test_the_dictionary_keeps_its_blessed_tile_count(self, stats):
        # Arrange
        expected = GOLDEN_TILES

        # Act
        measured = stats.tile_count

        # Assert
        assert measured == pytest.approx(expected, rel=GOLDEN_TOLERANCE)

    def test_the_picture_keeps_its_blessed_error(self, stats):
        # Arrange
        expected = GOLDEN_DISPLAYED_ERROR

        # Act
        measured = stats.displayed_error

        # Assert
        assert measured == pytest.approx(expected, rel=GOLDEN_TOLERANCE)
