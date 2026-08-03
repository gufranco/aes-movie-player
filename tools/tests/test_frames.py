"""Source decode tests.

The decode tests drive the real ffmpeg binary against a generated clip
rather than a stubbed decoder, so the filter chain is checked as ffmpeg
actually applies it.
"""

from __future__ import annotations

import subprocess
from fractions import Fraction

import numpy as np
import pytest

from aesmovie import frames

VBLANK_FPS = frames.VBLANK_FPS


@pytest.fixture(scope="module")
def synthetic_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=24:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


class TestVblankRate:
    def test_the_vblank_rate_matches_the_neo_geo_raster(self):
        assert Fraction(6_000_000, 384 * 264) == VBLANK_FPS

    def test_the_vblank_rate_is_the_documented_frequency(self):
        assert float(VBLANK_FPS) == pytest.approx(59.1856, abs=1e-4)


class TestFrameCount:
    def test_frame_count_follows_the_vblank_rate(self):
        assert frames.frame_count(seconds=1.0) == 59

    def test_a_twenty_second_clip_fills_the_expected_frame_budget(self):
        assert frames.frame_count(seconds=20.0) == 1183


class TestFillGeometry:
    def test_a_wider_source_is_cropped_horizontally(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        assert geometry.crop == (1028, 720)

    def test_a_taller_source_is_cropped_vertically(self):
        geometry = frames.plan_geometry(720, 1280, 320, 224, fit="fill")

        assert geometry.crop == (720, 504)

    def test_a_matching_aspect_is_not_cropped(self):
        geometry = frames.plan_geometry(640, 448, 320, 224, fit="fill")

        assert geometry.crop == (640, 448)

    def test_fill_uses_the_whole_target_frame(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        assert geometry.image == (320, 224)
        assert geometry.pad_top == 0

    def test_crop_dimensions_stay_even(self):
        geometry = frames.plan_geometry(1281, 721, 320, 224, fit="fill")

        assert geometry.crop[0] % 2 == 0
        assert geometry.crop[1] % 2 == 0

    def test_crop_never_exceeds_the_source(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        assert geometry.crop[0] <= 1280
        assert geometry.crop[1] <= 720


class TestLetterboxGeometry:
    def test_a_sixteen_by_nine_source_lands_on_ten_tile_rows(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="letterbox")

        assert geometry.image == (320, 160)

    def test_letterbox_bars_are_tile_aligned_and_symmetric(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="letterbox")

        assert geometry.pad_top == 32
        assert geometry.pad_top % 16 == 0
        assert geometry.pad_top * 2 + geometry.image[1] == 224

    def test_a_matching_aspect_needs_no_bars(self):
        geometry = frames.plan_geometry(640, 448, 320, 224, fit="letterbox")

        assert geometry.pad_top == 0
        assert geometry.image == (320, 224)


class TestFilterChain:
    def test_the_chain_crops_then_scales_then_resamples(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        chain = frames.build_filter(geometry)

        assert chain.index("crop=") < chain.index("scale=") < chain.index("fps=")

    def test_the_chain_requests_packed_rgb_output(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        chain = frames.build_filter(geometry)

        assert chain.endswith("format=rgb24")

    def test_the_chain_pads_only_when_letterboxing(self):
        fill = frames.build_filter(frames.plan_geometry(1280, 720, 320, 224, fit="fill"))
        boxed = frames.build_filter(frames.plan_geometry(1280, 720, 320, 224, fit="letterbox"))

        assert "pad=" not in fill
        assert "pad=320:224:0:32" in boxed

    def test_an_unknown_fit_mode_is_rejected(self):
        with pytest.raises(ValueError, match="fit"):
            frames.plan_geometry(1280, 720, 320, 224, fit="stretch")


class TestProbe:
    def test_probe_reports_the_source_geometry(self, synthetic_clip):
        info = frames.probe(synthetic_clip)

        assert (info.width, info.height) == (1280, 720)

    def test_probe_reports_the_source_duration(self, synthetic_clip):
        info = frames.probe(synthetic_clip)

        assert info.duration == pytest.approx(2.0, abs=0.1)

    def test_probing_a_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            frames.probe(tmp_path / "absent.mp4")


class TestDecode:
    def test_decode_returns_frames_at_the_target_resolution(self, synthetic_clip):
        clip = frames.decode(synthetic_clip, start=0.0, duration=0.5)

        assert clip.shape[1:] == (224, 320, 3)

    def test_decode_returns_the_vblank_rate_frame_count(self, synthetic_clip):
        clip = frames.decode(synthetic_clip, start=0.0, duration=0.5)

        assert clip.shape[0] == frames.frame_count(seconds=0.5)

    def test_decoded_frames_are_eight_bit_rgb(self, synthetic_clip):
        clip = frames.decode(synthetic_clip, start=0.0, duration=0.2)

        assert clip.dtype == np.uint8

    def test_upsampling_from_a_slower_source_duplicates_frames(self, synthetic_clip):
        clip = frames.decode(synthetic_clip, start=0.0, duration=1.0)

        identical = sum(1 for i in range(1, len(clip)) if np.array_equal(clip[i], clip[i - 1]))
        assert identical > len(clip) // 3

    def test_letterboxed_output_has_black_bars(self, synthetic_clip):
        clip = frames.decode(synthetic_clip, start=0.0, duration=0.2, fit="letterbox")

        assert not clip[0, :32].any()
        assert not clip[0, -32:].any()

    def test_decoding_a_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            frames.decode(tmp_path / "absent.mp4", start=0.0, duration=0.2)


class TestDecodeLimits:
    def test_asking_for_more_than_the_clip_holds_is_rejected(self, synthetic_clip):
        with pytest.raises(RuntimeError, match="expected"):
            frames.decode(synthetic_clip, start=0.0, duration=5.0)

    def test_seeking_past_the_end_is_rejected(self, synthetic_clip):
        with pytest.raises(RuntimeError, match="no frames"):
            frames.decode(synthetic_clip, start=30.0, duration=0.5)

    def test_a_missing_tool_is_reported_by_name(self, monkeypatch):
        monkeypatch.setattr(frames.shutil, "which", lambda _: None)

        with pytest.raises(RuntimeError, match="ffprobe"):
            frames._require_tool("ffprobe")


class TestDenoise:
    def test_the_chain_has_no_denoiser_by_default(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        assert "hqdn3d" not in frames.build_filter(geometry)

    def test_a_positive_strength_inserts_the_denoiser(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        assert "hqdn3d" in frames.build_filter(geometry, denoise=1.0)

    def test_the_denoiser_runs_after_the_downscale(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        chain = frames.build_filter(geometry, denoise=1.0)

        assert chain.index("scale=") < chain.index("hqdn3d")

    def test_the_denoiser_runs_before_the_frame_rate_resample(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        chain = frames.build_filter(geometry, denoise=1.0)

        assert chain.index("hqdn3d") < chain.index("fps=")

    def test_strength_scales_every_term(self):
        weak = frames.Denoise().scaled(1.0).to_filter()
        strong = frames.Denoise().scaled(2.0).to_filter()

        assert weak != strong
        assert strong == "hqdn3d=8:6:12:9"

    def test_the_denoiser_runs_before_letterbox_padding(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="letterbox")

        chain = frames.build_filter(geometry, denoise=1.0)

        assert chain.index("hqdn3d") < chain.index("pad=")

    def test_denoising_a_clip_still_returns_the_expected_frames(self, synthetic_clip):
        clip = frames.decode(synthetic_clip, start=0.0, duration=0.3, denoise=1.0)

        assert clip.shape == (frames.frame_count(seconds=0.3), 224, 320, 3)

    def test_denoising_reduces_frame_to_frame_change(self, tmp_path):
        noisy = tmp_path / "noise.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=640x360:rate=24:duration=1",
                "-vf",
                "noise=alls=40:allf=t+u",
                "-pix_fmt",
                "yuv420p",
                str(noisy),
            ],
            check=True,
        )

        plain = frames.decode(noisy, start=0.0, duration=0.4)
        cleaned = frames.decode(noisy, start=0.0, duration=0.4, denoise=2.0)

        def churn(clip):
            return float(np.abs(np.diff(clip.astype(np.int16), axis=0)).mean())

        assert churn(cleaned) < churn(plain)


class TestStreaming:
    def test_streaming_yields_every_frame(self, synthetic_clip):
        chunks = list(frames.stream(synthetic_clip, start=0.0, duration=0.5, chunk_frames=8))

        assert sum(len(c) for c in chunks) == frames.frame_count(seconds=0.5)

    def test_streamed_chunks_have_the_target_geometry(self, synthetic_clip):
        for chunk in frames.stream(synthetic_clip, start=0.0, duration=0.3, chunk_frames=8):
            assert chunk.shape[1:] == (224, 320, 3)

    def test_streaming_matches_a_whole_clip_decode(self, synthetic_clip):
        whole = frames.decode(synthetic_clip, start=0.0, duration=0.3)

        streamed = np.concatenate(
            list(frames.stream(synthetic_clip, start=0.0, duration=0.3, chunk_frames=5))
        )

        assert np.array_equal(streamed, whole)

    def test_chunks_respect_the_requested_size(self, synthetic_clip):
        chunks = list(frames.stream(synthetic_clip, start=0.0, duration=0.5, chunk_frames=8))

        assert all(len(c) <= 8 for c in chunks)

    def test_streaming_honours_denoise(self, synthetic_clip):
        plain = np.concatenate(list(frames.stream(synthetic_clip, start=0.0, duration=0.2)))
        cleaned = np.concatenate(
            list(frames.stream(synthetic_clip, start=0.0, duration=0.2, denoise=2.0))
        )

        assert not np.array_equal(plain, cleaned)

    def test_sampling_returns_evenly_spaced_frames(self, synthetic_clip):
        sample = frames.sample(synthetic_clip, start=0.0, duration=0.5, stride=4)

        assert len(sample) == len(range(0, frames.frame_count(seconds=0.5), 4))

    def test_a_sample_matches_the_strided_whole_clip(self, synthetic_clip):
        whole = frames.decode(synthetic_clip, start=0.0, duration=0.3)

        sample = frames.sample(synthetic_clip, start=0.0, duration=0.3, stride=3)

        assert np.array_equal(sample, whole[::3])


class TestMotionBlur:
    def test_no_blur_by_default(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        assert "tmix" not in frames.build_filter(geometry)

    def test_a_single_frame_blur_is_a_no_op(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        assert "tmix" not in frames.build_filter(geometry, motion_blur=1)

    def test_blur_averages_the_requested_frame_count(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        assert "tmix=frames=3" in frames.build_filter(geometry, motion_blur=3)

    def test_blur_runs_before_the_frame_rate_resample(self):
        geometry = frames.plan_geometry(1280, 720, 320, 224, fit="fill")

        chain = frames.build_filter(geometry, motion_blur=2)

        assert chain.index("tmix") < chain.index("fps=")

    def test_blur_smooths_frame_to_frame_change(self, synthetic_clip):
        plain = frames.decode(synthetic_clip, start=0.0, duration=0.4)
        blurred = frames.decode(synthetic_clip, start=0.0, duration=0.4, motion_blur=3)

        def churn(clip):
            return float(np.abs(np.diff(clip.astype(np.int16), axis=0)).mean())

        assert churn(blurred) < churn(plain)


class TestFrameHoldPlanning:
    def test_a_target_rate_maps_to_the_nearest_hold(self):
        assert frames.hold_for_target_fps(59.2) == 1
        assert frames.hold_for_target_fps(29.6) == 2
        assert frames.hold_for_target_fps(15.0) == 4

    def test_a_non_positive_target_is_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            frames.hold_for_target_fps(0.0)

    def test_a_hold_above_the_source_cadence_keeps_every_frame(self):
        assert frames.source_frames_kept(2, Fraction(24)) == 1.0

    def test_a_hold_below_the_source_cadence_drops_frames(self):
        assert frames.source_frames_kept(4, Fraction(24)) < 1.0

    def test_a_faster_source_makes_the_same_hold_drop_more(self):
        assert frames.source_frames_kept(3, Fraction(30)) < frames.source_frames_kept(
            3, Fraction(24)
        )


class TestSourceAnalysis:
    """What the source itself says about how it should be baked."""

    def interlaced_clip(self, tmp_path):
        path = tmp_path / "interlaced.mp4"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                "-i", "testsrc=size=640x480:rate=25:duration=2",
                "-vf", "interlace", "-flags", "+ilme+ildct",
                "-pix_fmt", "yuv420p", str(path),
            ],
            check=True,
        )
        return path

    def letterboxed_clip(self, tmp_path):
        path = tmp_path / "bars.mp4"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                "-i", "testsrc=size=640x360:rate=25:duration=2",
                "-vf", "pad=640:480:0:60:black",
                "-pix_fmt", "yuv420p", str(path),
            ],
            check=True,
        )
        return path

    def test_a_progressive_source_is_not_flagged(self, synthetic_clip):
        assert frames.analyse(synthetic_clip, duration=1.0).interlaced is False

    def test_an_interlaced_source_is_flagged(self, tmp_path):
        clip = self.interlaced_clip(tmp_path)

        assert frames.analyse(clip, duration=1.5).interlaced is True

    def test_a_full_frame_source_reports_no_bars(self, synthetic_clip):
        assert frames.analyse(synthetic_clip, duration=1.0).crop is None

    def test_black_bars_are_detected(self, tmp_path):
        clip = self.letterboxed_clip(tmp_path)

        crop = frames.analyse(clip, duration=1.5).crop

        assert crop is not None
        assert crop[1] < 480

    def test_the_deinterlacer_is_only_added_when_needed(self):
        geometry = frames.plan_geometry(640, 480)

        assert "yadif" in frames.build_filter(geometry, deinterlace=True)
        assert "yadif" not in frames.build_filter(geometry, deinterlace=False)

    def test_the_deinterlacer_runs_before_the_scaler(self):
        geometry = frames.plan_geometry(640, 480)

        chain = frames.build_filter(geometry, deinterlace=True)

        assert chain.index("yadif") < chain.index("scale=")
