from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from aesmovie import bake, neocolor


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

        assert path.stat().st_size == baked.result.stats.stream_bytes

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
    def test_it_emits_an_assembly_stub_linking_every_blob(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.S").read_text()

        for name in ("stream.bin", "index.bin", "keyframes.bin", "palettes.bin"):
            assert name in text

    def test_the_assembly_stub_exports_the_player_symbols(self, baked):
        text = (baked.build_dir / "generated" / "movie_data.S").read_text()

        for symbol in ("movie_stream", "movie_index", "movie_keyframes", "movie_palettes"):
            assert f".globl {symbol}" in text

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
        expected = neocolor.color_index_to_rgb(outcome.result.rendered)
        assert np.array_equal(decoded, expected)


class TestCommandLine:
    def test_default_arguments_target_the_full_palette_bank_allocation(self):
        args = bake._parse_args(["--source", "clip.mp4", "--duration", "1"])

        assert args.palette_count == 240
        assert args.base_bank == 16

    def test_flip_dedup_is_on_unless_switched_off(self):
        args = bake._parse_args(["--source", "clip.mp4", "--duration", "1", "--no-flip"])

        assert args.no_flip is True

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
