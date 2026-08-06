from __future__ import annotations

import pytest

from aesmovie import bundle


def _library(root):
    source = root / "src-fmv"
    source.mkdir(exist_ok=True)
    for name in (*bundle.LIBRARY_SOURCES, *bundle.AUDIO_SOURCES):
        (source / name).write_text(f"/* {name} */\n")
    return source


def _build(root, *, banks=1, audio=True):
    build = root / "build"
    generated = build / "generated"
    baked = build / "baked"
    generated.mkdir(parents=True, exist_ok=True)
    baked.mkdir(parents=True, exist_ok=True)
    for name in bundle.GENERATED_SOURCES:
        (generated / name).write_text(f"/* {name} */\n")
    for name in bundle.BAKED_ASSETS:
        (baked / name).write_bytes(b"\x00\x01")
    for bank in range(banks):
        (generated / f"fmv_stream__bank{bank}.S").write_text(f".globl fmv_stream_bank{bank}\n")
    if audio:
        (baked / "v2.bin").write_bytes(b"\x00")
        (generated / "audio_params.s").write_text(".equ x, 1\n")
    return build


def _write(root, **overrides):
    banks = overrides.pop("banks", 1)
    audio = overrides.pop("audio", True)
    settings = {
        "target": root / "out",
        "build_dir": overrides.pop("build_dir", None) or _build(root, banks=banks, audio=audio),
        "stream_banks": 1,
        "max_updates": 280,
        "tick_cycles": 17920,
        "tile_count": 33142,
        "crom_payload": 33142 * 64,
        "crom_size": 4194304,
        "palette_base": 16,
        "first_sprite": 1,
        "frames": 1775,
        "version": (1, 0),
        "library_root": overrides.pop("library_root", None) or _library(root),
    }
    settings.update(overrides)
    return bundle.write_bundle(**settings)


class TestLibrarySource:
    def test_it_carries_every_library_source(self, tmp_path):
        layout = _write(tmp_path)

        for name in bundle.LIBRARY_SOURCES:
            assert (layout.library / name).is_file(), name

    def test_it_carries_the_reference_sound_driver(self, tmp_path):
        layout = _write(tmp_path)

        assert (layout.library / "sound.s").is_file()

    def test_a_missing_library_source_is_an_error(self, tmp_path):
        library = _library(tmp_path)
        (library / "fmv.c").unlink()

        with pytest.raises(FileNotFoundError):
            _write(tmp_path, library_root=library)


class TestMovieData:
    def test_it_carries_the_generated_sources(self, tmp_path):
        layout = _write(tmp_path)

        for name in bundle.GENERATED_SOURCES:
            assert (layout.movie / name).is_file(), name

    def test_it_carries_one_stub_per_stream_bank(self, tmp_path):
        layout = _write(tmp_path, banks=3, stream_banks=3)

        stubs = sorted(layout.movie.glob(bundle.STREAM_BANK_GLOB))

        assert len(stubs) == 3

    def test_it_carries_every_baked_asset(self, tmp_path):
        layout = _write(tmp_path)

        for name in bundle.BAKED_ASSETS:
            assert (layout.movie / name).is_file(), name

    def test_a_silent_bake_leaves_the_voice_rom_out(self, tmp_path):
        layout = _write(tmp_path, audio=False)

        assert not (layout.movie / "v2.bin").exists()
        assert layout.has_audio is False

    def test_a_bake_with_sound_carries_the_voice_rom(self, tmp_path):
        layout = _write(tmp_path)

        assert (layout.movie / "v2.bin").is_file()
        assert layout.has_audio is True

    def test_a_missing_asset_is_an_error(self, tmp_path):
        build = _build(tmp_path)
        (build / "baked" / "index.bin").unlink()

        with pytest.raises(FileNotFoundError):
            _write(tmp_path, build_dir=build)

    def test_a_bank_count_that_disagrees_with_the_bake_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match="stream bank"):
            _write(tmp_path, banks=1, stream_banks=2)


class TestMakeFragment:
    def test_it_writes_a_make_fragment(self, tmp_path):
        layout = _write(tmp_path)

        assert layout.makefile.is_file()
        assert layout.makefile.name == "fmv.mk"

    def test_the_fragment_accounts_for_every_bank(self, tmp_path):
        layout = _write(tmp_path, banks=2, stream_banks=2)

        text = layout.makefile.read_text()

        assert "FMV_BANK_NUMBERS = 0 1" in text
        assert "FMV_STREAM_BANKS = 2" in text

    def test_the_fragment_builds_an_object_for_each_bank_stub(self, tmp_path):
        layout = _write(tmp_path)

        text = layout.makefile.read_text()

        assert "fmv_stream__bank$(bank).o" in text
        assert "fmv_stream__bank%.S" in text

    def test_the_fragment_supplies_the_assembly_rule_ngdevkit_lacks(self, tmp_path):
        text = _write(tmp_path).makefile.read_text()

        assert "$(M68KGCC) $(NGCFLAGS) $(CFLAGS)" in text

    def test_the_fragment_adds_its_own_directories_to_the_source_list(self, tmp_path):
        text = _write(tmp_path).makefile.read_text()

        assert "SRCDIRS += $(FMV_SRC) $(FMV_MOVIE)" in text

    def test_a_video_only_build_drops_the_audio_object(self, tmp_path):
        text = _write(tmp_path).makefile.read_text()

        assert "-DFMV_NO_AUDIO" in text
        assert "fmv_audio.o" in text

    def test_the_fragment_passes_the_stream_base_to_the_linker(self, tmp_path):
        layout = _write(tmp_path)

        assert "fmv_stream_base" in layout.makefile.read_text()

    def test_the_fragment_lets_the_caller_choose_the_first_bank(self, tmp_path):
        layout = _write(tmp_path)

        assert "FMV_FIRST_BANK ?=" in layout.makefile.read_text()


class TestSpaceForTheCallersOwnTiles:
    def test_the_fragment_states_the_sprite_rom_size(self, tmp_path):
        text = _write(tmp_path).makefile.read_text()

        assert "FMV_CROM_BYTES = 4194304" in text

    def test_the_fragment_states_where_the_callers_tiles_begin(self, tmp_path):
        text = _write(tmp_path).makefile.read_text()

        assert "FMV_FIRST_FREE_TILE = 33142" in text

    def test_the_fragment_states_how_many_slots_the_slack_is_worth(self, tmp_path):
        text = _write(tmp_path).makefile.read_text()

        assert f"FMV_FREE_TILES = {(4194304 - 33142 * 64) // 64}" in text

    def test_a_dictionary_that_fills_the_rom_leaves_no_slack(self, tmp_path):
        layout = _write(tmp_path, crom_payload=4194304, crom_size=4194304)

        assert "FMV_FREE_TILES = 0" in layout.makefile.read_text()

    def test_the_fragment_reserves_the_banks_the_caller_owns(self, tmp_path):
        text = _write(tmp_path, banks=2, stream_banks=2).makefile.read_text()

        assert "FMV_ALL_BANK_NUMBERS" in text
        assert (
            "$(foreach bank,$(FMV_ALL_BANK_NUMBERS),$(eval $(PROM2): $(PROM2)_bank$(bank)))" in text
        )

    def test_the_second_program_rom_grows_with_the_first_bank(self, tmp_path):
        text = _write(tmp_path).makefile.read_text()

        assert "FMV_TOTAL_BANKS = $(shell expr $(FMV_FIRST_BANK) + $(FMV_STREAM_BANKS))" in text
        assert "FMV_PROM2_BYTES = $(shell expr $(FMV_TOTAL_BANKS) \\* 1048576)" in text

    def test_the_guide_shows_the_callers_tiles_listed_after_the_movies(self, tmp_path):
        text = _write(tmp_path).guide.read_text()

        assert "$(CROM1): $(FMV_MOVIE)/c1.bin $(BUILDDIR)/assets/my-tiles.c1" in text
        assert "CROMSIZE = $(FMV_CROM_BYTES)" in text


class TestGuide:
    def test_it_writes_an_integration_guide(self, tmp_path):
        layout = _write(tmp_path)

        assert layout.guide.is_file()

    def test_the_guide_names_the_calls_a_caller_makes(self, tmp_path):
        text = _write(tmp_path).guide.read_text()

        for call in ("fmv_defaults", "fmv_play", "fmv_open", "fmv_close"):
            assert call in text, call

    def test_the_guide_states_the_version_the_bundle_was_stamped_with(self, tmp_path):
        text = _write(tmp_path).guide.read_text()

        assert "1.0" in text

    def test_the_guide_states_what_a_frame_costs(self, tmp_path):
        text = _write(tmp_path).guide.read_text()

        assert "280" in text

    def test_the_guide_states_which_tiles_the_movie_owns(self, tmp_path):
        text = _write(tmp_path).guide.read_text()

        assert "33142" in text or "33,142" in text

    def test_the_guide_states_which_palettes_the_movie_owns(self, tmp_path):
        text = _write(tmp_path).guide.read_text()

        assert "16" in text
