from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from neogeomedia import frames
from tests.bakehelp import lavfi_clip

pytestmark = pytest.mark.ffmpeg

RASTER = (224, 320, 3)


def churn(clip: np.ndarray) -> float:
    return float(np.abs(np.diff(clip.astype(np.int16), axis=0)).mean())


def repeated_frames(clip: np.ndarray) -> int:
    return sum(1 for index in range(1, len(clip)) if np.array_equal(clip[index], clip[index - 1]))


def joined(chunks) -> np.ndarray:
    return np.concatenate(list(chunks))


@pytest.fixture(scope="module")
def widescreen_clip(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("clip") / "source.mp4"
    return lavfi_clip(path, "testsrc=size=1280x720:rate=24:duration=2")


@pytest.fixture(scope="module")
def noisy_clip(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("noise") / "noise.mp4"
    return lavfi_clip(
        path, "testsrc=size=640x360:rate=24:duration=1", extra=("-vf", "noise=alls=40:allf=t+u")
    )


@pytest.fixture(scope="module")
def short_decode(widescreen_clip) -> np.ndarray:
    return frames.decode(widescreen_clip, start=0.0, duration=0.3)


@pytest.fixture(scope="module")
def plain_noisy_churn(noisy_clip) -> float:
    return churn(frames.decode(noisy_clip, start=0.0, duration=0.4))


@pytest.fixture(scope="module")
def plain_widescreen_churn(widescreen_clip) -> float:
    return churn(frames.decode(widescreen_clip, start=0.0, duration=0.4))


@pytest.fixture(scope="module")
def plain_stream(widescreen_clip) -> np.ndarray:
    return joined(frames.stream(widescreen_clip, start=0.0, duration=0.2))


class TestDecode:
    def test_decode_returns_frames_at_the_target_resolution(self, widescreen_clip):
        # Arrange
        duration = 0.5

        # Act
        clip = frames.decode(widescreen_clip, start=0.0, duration=duration)

        # Assert
        assert clip.shape == (29, *RASTER)

    def test_decoded_frames_are_eight_bit_rgb(self, widescreen_clip):
        # Arrange
        duration = 0.2

        # Act
        clip = frames.decode(widescreen_clip, start=0.0, duration=duration)

        # Assert
        assert clip.dtype == np.uint8

    def test_upsampling_from_a_slower_source_duplicates_frames(self, widescreen_clip):
        # Arrange
        duration = 1.0

        # Act
        clip = frames.decode(widescreen_clip, start=0.0, duration=duration)

        # Assert
        assert len(clip) == 59
        assert repeated_frames(clip) == 59 - 24

    def test_decoding_a_missing_file_is_rejected(self, tmp_path):
        # Arrange
        missing = tmp_path / "absent.mp4"

        # Act
        with pytest.raises(FileNotFoundError) as raised:
            frames.decode(missing, start=0.0, duration=0.2)

        # Assert
        assert "absent.mp4" in str(raised.value)


class TestDecodeLimits:
    def test_asking_for_more_than_the_clip_holds_is_rejected(self, widescreen_clip):
        # Arrange
        duration = 5.0

        # Act
        with pytest.raises(RuntimeError, match="expected") as raised:
            frames.decode(widescreen_clip, start=0.0, duration=duration)

        # Assert
        assert "expected 295" in str(raised.value)

    def test_seeking_past_the_end_is_rejected(self, widescreen_clip):
        # Arrange
        start = 30.0

        # Act
        with pytest.raises(RuntimeError, match="no frames") as raised:
            frames.decode(widescreen_clip, start=start, duration=0.5)

        # Assert
        assert "at 30.0s" in str(raised.value)


class TestDecodeFilters:
    def test_denoising_a_clip_still_returns_the_expected_frames(self, widescreen_clip):
        # Arrange
        strength = 1.0

        # Act
        clip = frames.decode(widescreen_clip, start=0.0, duration=0.3, denoise=strength)

        # Assert
        assert clip.shape == (17, *RASTER)

    def test_denoising_reduces_frame_to_frame_change(self, noisy_clip, plain_noisy_churn):
        # Arrange
        plain = plain_noisy_churn

        # Act
        cleaned = frames.decode(noisy_clip, start=0.0, duration=0.4, denoise=2.0)

        # Assert
        assert churn(cleaned) < plain

    def test_blur_smooths_frame_to_frame_change(self, widescreen_clip, plain_widescreen_churn):
        # Arrange
        plain = plain_widescreen_churn

        # Act
        blurred = frames.decode(widescreen_clip, start=0.0, duration=0.4, motion_blur=3)

        # Assert
        assert churn(blurred) < plain


class TestStreaming:
    def test_streaming_yields_every_frame_in_chunks_of_the_requested_size(self, widescreen_clip):
        # Arrange
        chunk_frames = 8

        # Act
        chunks = list(
            frames.stream(widescreen_clip, start=0.0, duration=0.5, chunk_frames=chunk_frames)
        )

        # Assert
        assert [len(chunk) for chunk in chunks] == [8, 8, 8, 5]

    def test_streamed_chunks_have_the_target_geometry(self, widescreen_clip):
        # Arrange
        chunk_frames = 8

        # Act
        chunks = list(
            frames.stream(widescreen_clip, start=0.0, duration=0.3, chunk_frames=chunk_frames)
        )

        # Assert
        assert [chunk.shape for chunk in chunks] == [(8, *RASTER), (8, *RASTER), (1, *RASTER)]

    def test_streaming_matches_a_whole_clip_decode(self, widescreen_clip, short_decode):
        # Arrange
        chunk_frames = 5

        # Act
        streamed = joined(
            frames.stream(widescreen_clip, start=0.0, duration=0.3, chunk_frames=chunk_frames)
        )

        # Assert
        assert np.array_equal(streamed, short_decode)

    def test_streaming_honours_denoise(self, widescreen_clip, plain_stream):
        # Arrange
        plain = plain_stream

        # Act
        cleaned = joined(frames.stream(widescreen_clip, start=0.0, duration=0.2, denoise=2.0))

        # Assert
        assert cleaned.shape == plain.shape
        assert np.array_equal(plain, cleaned) is False

    def test_sampling_returns_evenly_spaced_frames(self, widescreen_clip):
        # Arrange
        stride = 4

        # Act
        sample = frames.sample(widescreen_clip, start=0.0, duration=0.5, stride=stride)

        # Assert
        assert len(sample) == len(range(0, 29, 4))

    def test_a_sample_matches_the_strided_whole_clip(self, widescreen_clip, short_decode):
        # Arrange
        stride = 3

        # Act
        sample = frames.sample(widescreen_clip, start=0.0, duration=0.3, stride=stride)

        # Assert
        assert np.array_equal(sample, short_decode[::3])

    def test_streaming_one_frame_a_chunk_yields_every_frame_alone(self, widescreen_clip):
        # Arrange
        chunk_frames = 1

        # Act
        chunks = list(
            frames.stream(widescreen_clip, start=0.0, duration=0.3, chunk_frames=chunk_frames)
        )

        # Assert
        assert [len(chunk) for chunk in chunks] == [1] * 17

    def test_a_stride_longer_than_a_chunk_skips_whole_chunks(self, widescreen_clip):
        # Arrange
        stride = 100

        # Act
        sample = frames.sample(widescreen_clip, start=0.0, duration=1.2, stride=stride)

        # Assert
        assert sample.shape == (1, *RASTER)

    def test_sampling_no_time_returns_no_frames(self, widescreen_clip):
        # Arrange
        duration = 0.0

        # Act
        sample = frames.sample(widescreen_clip, start=0.0, duration=duration, stride=2)

        # Assert
        assert sample.shape == (0, *RASTER)
