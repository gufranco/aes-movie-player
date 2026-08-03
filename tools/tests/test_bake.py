from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from aesmovie import adpcmb, bake, stream
from aesmovie import frames as frames_mod

_spec = importlib.util.spec_from_file_location(
    "verify_capture", Path(__file__).resolve().parents[1] / "scripts" / "verify_capture.py"
)
verify_capture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_capture)


@pytest.fixture(scope="module")
def synthetic_clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("bake") / "source.mp4"
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
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture(scope="module")
def baked(synthetic_clip, tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    return bake.run(
        bake.BakeRequest(
            source=synthetic_clip,
            start=0.0,
            duration=0.25,
            build_dir=out,
            palette_count=8,
            keyframe_interval=8,
            candidates=0,
            sample_stride=1,
        )
    )


class TestArtifacts:
    def test_it_writes_both_c_rom_halves(self, baked):
        assert (baked.build_dir / "baked" / "c1.bin").is_file()
        assert (baked.build_dir / "baked" / "c2.bin").is_file()

    def test_the_c_rom_halves_are_the_same_size(self, baked):
        c1 = (baked.build_dir / "baked" / "c1.bin").stat().st_size
        c2 = (baked.build_dir / "baked" / "c2.bin").stat().st_size

        assert c1 == c2

    def test_the_c_rom_size_is_a_power_of_two(self, baked):
        size = (baked.build_dir / "baked" / "c1.bin").stat().st_size

        assert size & (size - 1) == 0

    def test_it_writes_the_command_stream(self, baked):
        path = baked.build_dir / "baked" / "stream.bin"

        assert path.stat().st_size == baked.result.stats.stream_rom_bytes

    def test_it_writes_one_index_entry_per_frame(self, baked):
        path = baked.build_dir / "baked" / "index.bin"

        assert path.stat().st_size == 4 * baked.result.stats.frames

    def test_it_writes_the_palette_blob(self, baked):
        path = baked.build_dir / "baked" / "palettes.bin"

        assert path.stat().st_size == 8 * 32

    def test_every_blob_is_word_aligned(self, baked):
        for name in ("stream.bin", "index.bin", "keyframes.bin", "palettes.bin"):
            size = (baked.build_dir / "baked" / name).stat().st_size

            assert size % 2 == 0, name


class TestGeneratedSources:
    def test_it_emits_an_assembly_stub_linking_the_small_blobs(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.S").read_text()

        for name in ("index.bin", "keyframes.bin", "palettes.bin"):
            assert name in text

    def test_the_stub_names_blobs_without_a_path(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.S").read_text()

        assert '.incbin "index.bin"' in text
        assert str(baked.build_dir) not in text
        assert "/" not in text.split(".incbin")[1].split("\n")[0]

    def test_the_stream_is_not_linked_into_the_image(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.S").read_text()

        assert "stream.bin" not in text

    def test_the_assembly_stub_exports_the_player_symbols(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.S").read_text()

        for symbol in ("movie_index", "movie_keyframes", "movie_palettes"):
            assert f".globl {symbol}" in text

    def test_the_header_reports_the_stream_bank_count(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.h").read_text()

        assert "#define MOVIE_STREAM_BANKS 1" in text

    def test_the_stream_blob_is_a_whole_number_of_banks(self, baked):
        size = (baked.build_dir / "baked" / "stream.bin").stat().st_size

        assert size % stream.PROM_BANK_BYTES == 0

    def test_it_emits_a_header_with_the_frame_count(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.h").read_text()

        assert f"#define MOVIE_FRAME_COUNT {baked.result.stats.frames}" in text

    def test_it_emits_a_header_with_the_palette_base_bank(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.h").read_text()

        assert "#define MOVIE_PALETTE_BASE 16" in text

    def test_the_header_guards_against_double_inclusion(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.h").read_text()

        assert text.count("#ifndef MOVIE_DATA_H") == 1
        assert "#endif" in text


class TestReport:
    def test_the_report_records_the_dictionary_size(self, baked):
        report = baked.report()

        assert report["tile_count"] == baked.result.stats.tile_count

    def test_the_report_projects_a_feature_length_runtime(self, baked):
        report = baked.report()

        assert report["projected_crom_bytes_per_minute"] > 0

    def test_the_report_is_json_serializable(self, baked):
        assert json.loads(json.dumps(baked.report()))["frames"] == baked.result.stats.frames


class TestPreview:
    def test_it_can_render_a_preview_of_the_decoded_output(self, synthetic_clip, tmp_path):
        out = tmp_path / "build"
        preview = tmp_path / "preview.mp4"

        bake.run(
            bake.BakeRequest(
                source=synthetic_clip,
                start=0.0,
                duration=0.25,
                build_dir=out,
                palette_count=4,
                candidates=0,
                sample_stride=1,
                preview=preview,
            )
        )

        assert preview.stat().st_size > 0


class TestPreviewCodec:
    def test_matroska_previews_are_lossless(self):
        assert "ffv1" in bake._preview_codec(Path("out.mkv"))

    def test_other_containers_use_h264(self):
        assert "libx264" in bake._preview_codec(Path("out.mp4"))

    def test_a_lossless_preview_round_trips_the_rendered_picture(self, synthetic_clip, tmp_path):
        preview = tmp_path / "lossless.mkv"
        outcome = bake.run(
            bake.BakeRequest(
                source=synthetic_clip,
                start=0.0,
                duration=0.1,
                build_dir=tmp_path / "build",
                palette_count=8,
                candidates=0,
                sample_stride=1,
                preview=preview,
            )
        )

        raw = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(preview),
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            capture_output=True,
            check=True,
        ).stdout
        decoded = np.frombuffer(raw, np.uint8).reshape(-1, 224, 320, 3)
        assert len(decoded) == outcome.result.stats.frames

        rebuilt = verify_capture.reconstruct_frame(outcome.build_dir / "baked", 3)
        assert np.array_equal(decoded[3], rebuilt)


class TestCommandLine:
    def test_default_arguments_target_the_full_palette_bank_allocation(self):
        args = bake._parse_args(["--source", "clip.mp4", "--duration", "1"])

        assert args.palette_count == 240
        assert args.base_bank == 16

    def test_flip_dedup_is_off_unless_switched_on(self):
        assert bake._parse_args(["--source", "clip.mp4", "--duration", "1"]).flip is False

    def test_flip_dedup_can_be_switched_on(self):
        args = bake._parse_args(["--source", "clip.mp4", "--duration", "1", "--flip"])

        assert args.flip is True

    def test_the_defaults_are_the_measured_settings(self):
        args = bake._parse_args(["--source", "clip.mp4", "--duration", "1"])

        assert (args.scene_cut_ratio, args.tolerance, args.keyframe_interval) == (0.90, 0.0005, 90)

    def test_main_writes_a_report_and_reports_success(self, synthetic_clip, tmp_path, capsys):
        report = tmp_path / "report.json"

        code = bake.main(
            [
                "--source",
                str(synthetic_clip),
                "--duration",
                "0.2",
                "--build-dir",
                str(tmp_path / "build"),
                "--palette-count",
                "4",
                "--candidates",
                "0",
                "--sample-stride",
                "1",
                "--report-json",
                str(report),
            ]
        )

        assert code == 0
        assert json.loads(report.read_text())["frames"] == 11
        assert "tile_count" in capsys.readouterr().out

    def test_main_honours_the_letterbox_fit(self, synthetic_clip, tmp_path):
        build = tmp_path / "build"

        bake.main(
            [
                "--source",
                str(synthetic_clip),
                "--duration",
                "0.2",
                "--build-dir",
                str(build),
                "--fit",
                "letterbox",
                "--palette-count",
                "4",
                "--candidates",
                "0",
                "--sample-stride",
                "1",
            ]
        )

        assert (build / "baked" / "stream.bin").is_file()


class TestPreviewGuards:
    def test_a_preview_without_rendered_frames_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="no rendered frames"):
            bake._write_preview(tmp_path / "x.mkv", np.zeros((0, 224, 320), dtype=np.uint16))


class TestRenderCollection:
    def test_skipping_the_preview_skips_collecting_rendered_frames(self, synthetic_clip, tmp_path):
        outcome = bake.run(
            bake.BakeRequest(
                source=synthetic_clip,
                start=0.0,
                duration=0.2,
                build_dir=tmp_path / "build",
                palette_count=4,
                candidates=0,
                sample_stride=1,
            )
        )

        assert outcome.result.rendered.shape[0] == 0

    def test_a_preview_is_written_without_holding_the_frames(self, synthetic_clip, tmp_path):
        preview = tmp_path / "p.mkv"

        outcome = bake.run(
            bake.BakeRequest(
                source=synthetic_clip,
                start=0.0,
                duration=0.2,
                build_dir=tmp_path / "build",
                palette_count=4,
                candidates=0,
                sample_stride=1,
                preview=preview,
            )
        )

        assert outcome.result.rendered.shape[0] == 0
        assert preview.stat().st_size > 0


class TestAudio:
    def test_a_source_without_audio_is_detected(self, synthetic_clip):
        assert bake.has_audio_stream(synthetic_clip) is False

    def test_a_silent_source_bakes_without_a_voice_rom(self, synthetic_clip, tmp_path):
        outcome = bake.run(
            bake.BakeRequest(
                source=synthetic_clip,
                start=0.0,
                duration=0.2,
                build_dir=tmp_path / "build",
                palette_count=4,
                candidates=0,
                sample_stride=1,
            )
        )

        assert "voice" not in outcome.artifacts
        assert not (outcome.build_dir / "baked" / "v2.bin").exists()

    def test_a_source_with_audio_produces_a_voice_rom(self, tmp_path):
        source = tmp_path / "tone.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x240:rate=24:duration=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                str(source),
            ],
            check=True,
        )

        outcome = bake.run(
            bake.BakeRequest(
                source=source,
                start=0.0,
                duration=0.3,
                build_dir=tmp_path / "build",
                palette_count=4,
                candidates=0,
                sample_stride=1,
            )
        )

        assert (outcome.build_dir / "baked" / "v2.bin").is_file()

    def test_the_audio_parameters_are_emitted_for_the_z80(self, tmp_path):
        source = tmp_path / "tone2.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x240:rate=24:duration=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                str(source),
            ],
            check=True,
        )

        outcome = bake.run(
            bake.BakeRequest(
                source=source,
                start=0.0,
                duration=0.3,
                build_dir=tmp_path / "build",
                palette_count=4,
                candidates=0,
                sample_stride=1,
            )
        )

        params = (outcome.build_dir / "generated" / "audio_params.s").read_text()
        for name in ("ADPCM_B_START_LO", "ADPCM_B_END_HI", "ADPCM_B_DELTA_LO"):
            assert name in params

    def test_audio_can_be_switched_off(self, tmp_path):
        source = tmp_path / "tone3.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x240:rate=24:duration=1",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                str(source),
            ],
            check=True,
        )

        outcome = bake.run(
            bake.BakeRequest(
                source=source,
                start=0.0,
                duration=0.3,
                build_dir=tmp_path / "build",
                palette_count=4,
                candidates=0,
                sample_stride=1,
                audio=False,
            )
        )

        assert not (outcome.build_dir / "baked" / "v2.bin").exists()


class TestAudioVideoAlignment:
    def rate_and_pages(self):

        delta_n = adpcmb.delta_n_for(22050)
        return adpcmb.rate_for(delta_n), bake.audio_pages_per_frame(delta_n)

    def test_a_silent_bake_reports_no_audio_advance(self):
        assert bake.audio_pages_per_frame(0) == 0

    def test_the_ratio_matches_the_sample_rate(self):

        rate, pages = self.rate_and_pages()

        assert float(pages) == pytest.approx(rate / 512 / float(frames_mod.VBLANK_FPS), rel=1e-6)

    def test_audio_never_drifts_more_than_half_a_page_from_the_video(self):

        rate, pages = self.rate_and_pages()
        num, den = pages.numerator, pages.denominator
        half_page = 512 / rate / 2

        for frame in (0, 59, 1183, 3551, 60000, 106_000, 500_000):
            page = (frame * num + den // 2) // den
            audio_seconds = page * 512 / rate
            video_seconds = frame / float(frames_mod.VBLANK_FPS)

            assert abs(audio_seconds - video_seconds) <= half_page + 1e-9, frame

    def test_the_drift_does_not_grow_with_runtime(self):

        rate, pages = self.rate_and_pages()
        num, den = pages.numerator, pages.denominator

        def drift(frame):
            page = (frame * num + den // 2) // den
            return abs(page * 512 / rate - frame / float(frames_mod.VBLANK_FPS))

        assert drift(500_000) <= drift(1183) + 512 / rate

    def test_the_seek_granularity_is_one_page(self):
        rate, _ = self.rate_and_pages()

        assert 512 / rate == pytest.approx(0.0232, abs=0.001)

    def test_the_header_carries_the_alignment_ratio(self, synthetic_clip, tmp_path):
        outcome = bake.run(
            bake.BakeRequest(
                source=synthetic_clip,
                start=0.0,
                duration=0.2,
                build_dir=tmp_path / "b",
                palette_count=4,
                candidates=0,
                sample_stride=1,
            )
        )

        text = (outcome.build_dir / "generated" / "movie_data.h").read_text()
        assert "MOVIE_AUDIO_PAGE_NUM" in text
        assert "MOVIE_AUDIO_PAGE_DEN" in text


class TestSampleThinning:
    def test_a_small_sample_is_left_alone(self):
        tiles = np.zeros((10, 16, 16), dtype=np.uint16)

        assert bake._thin_sample(tiles, 0).shape[0] == 10

    def test_a_large_sample_is_capped(self):
        tiles = np.zeros((bake.MAX_SAMPLE_TILES + 5000, 16, 16), dtype=np.uint16)

        assert bake._thin_sample(tiles, 0).shape[0] == bake.MAX_SAMPLE_TILES

    def test_thinning_is_deterministic_for_a_seed(self):
        rng = np.random.default_rng(1)
        tiles = rng.integers(0, 100, size=(bake.MAX_SAMPLE_TILES + 100, 16, 16), dtype=np.uint16)

        assert np.array_equal(bake._thin_sample(tiles, 3), bake._thin_sample(tiles, 3))

    def test_thinning_keeps_source_order(self):
        rng = np.random.default_rng(2)
        tiles = rng.integers(0, 100, size=(bake.MAX_SAMPLE_TILES + 100, 16, 16), dtype=np.uint16)

        thinned = bake._thin_sample(tiles, 4)

        assert thinned.shape == (bake.MAX_SAMPLE_TILES, 16, 16)
