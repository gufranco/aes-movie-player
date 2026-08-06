from __future__ import annotations

import pytest

from aesmovie import integrate

STOCK_ROM_MK = """PROMSIZE=1048576
PROM1=$(ROM)/$(GAMEROM)-p1.p1
# PROM2=$(ROM)/$(GAMEROM)-p2.p2
CROMSIZE=2097152
SROMSIZE=131072
"""

STOCK_MAKEFILE = """GAMEROM=ngdevkit
include rom.mk

include build.mk

include emu.mk

ELF=$(BUILDDIR)/rom.elf
$(ELF):	$(BUILDDIR)/main.o
$(PROM1): $(ELF)

$(SROM1): $(BUILDDIR)/assets/base-srom-text-shadow.fix

$(CROM1): $(BUILDDIR)/assets/base-crom-logo.c1
$(CROM2): $(BUILDDIR)/assets/base-crom-logo.c2

SOUND_DRIVER=$(BUILDDIR)/assets/base-sound-driver.ihx
$(MROM1): $(SOUND_DRIVER)
"""


class TestCartridgeDeclaration:
    def test_it_declares_the_second_program_rom(self):
        text = integrate.cartridge_edits(STOCK_ROM_MK, 4194304)

        assert "PROM2=$(ROM)/$(GAMEROM)-p2.p2" in text
        assert "# PROM2=" not in text

    def test_it_widens_the_sprite_rom_to_hold_the_movie(self):
        text = integrate.cartridge_edits(STOCK_ROM_MK, 4194304)

        assert "CROMSIZE=4194304" in text

    def test_it_leaves_the_rest_of_the_declaration_alone(self):
        text = integrate.cartridge_edits(STOCK_ROM_MK, 4194304)

        assert "PROMSIZE=1048576" in text
        assert "SROMSIZE=131072" in text

    def test_a_declaration_the_guide_does_not_recognise_is_an_error(self):
        with pytest.raises(SystemExit):
            integrate.cartridge_edits("PROMSIZE=1048576\n", 4194304)


class TestMakefile:
    def test_the_fragment_is_included_before_the_build_rules(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert text.index("include fmv/fmv.mk") < text.index("include build.mk")

    def test_the_fragment_is_included_after_the_cartridge_declaration(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert text.index("include rom.mk") < text.index("include fmv/fmv.mk")

    def test_it_names_the_projects_own_objects_before_the_include(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert text.index("FMV_GAME_OBJS") < text.index("include fmv/fmv.mk")

    def test_it_sizes_the_second_program_rom_for_the_stream(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 2097152)

        assert "PROM2SIZE = 2097152" in text

    def test_it_points_the_cartridge_at_the_movies_rom_images(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        for line in (
            "$(CROM1): $(FMV_MOVIE)/c1.bin",
            "$(CROM2): $(FMV_MOVIE)/c2.bin",
            "$(SROM1): $(FMV_MOVIE)/fix.s1",
        ):
            assert line in text, line

    def test_it_builds_the_program_rom_from_the_first_bank_elf(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert "$(PROM1): $(BUILDDIR)/rom-fmv-bank0.elf" in text

    def test_it_asks_for_a_video_only_build(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert "FMV_AUDIO = no" in text

    def test_a_makefile_without_the_build_rules_is_an_error(self):
        with pytest.raises(SystemExit):
            integrate.makefile_edits("include rom.mk\n", 1048576)

    def test_the_stock_program_rom_wiring_is_replaced_not_added_to(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert "$(PROM1): $(ELF)" not in text
        assert "ELF=$(BUILDDIR)/rom.elf" not in text

    def test_the_demo_assets_stop_being_prerequisites(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert "base-crom-logo" not in text
        assert "base-srom-text-shadow" not in text

    def test_the_sound_driver_comes_from_ngdevkit(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert "SOUND_DRIVER=$(NGSHAREDIR)/nullsound_driver.ihx" in text

    def test_a_makefile_missing_the_stock_asset_lines_is_an_error(self):
        stripped = STOCK_MAKEFILE.replace(
            "$(CROM1): $(BUILDDIR)/assets/base-crom-logo.c1\n"
            "$(CROM2): $(BUILDDIR)/assets/base-crom-logo.c2",
            "",
        )

        with pytest.raises(SystemExit):
            integrate.makefile_edits(stripped, 1048576)

    def test_it_edits_nothing_the_baker_emitted(self):
        text = integrate.makefile_edits(STOCK_MAKEFILE, 1048576)

        assert "fmv/movie/" not in text
        assert "fmv/src/" not in text


class TestApplyingToAProject:
    def _project(self, root):
        (root / "rom.mk").write_text(STOCK_ROM_MK)
        (root / "Makefile").write_text(STOCK_MAKEFILE)
        return root

    def test_it_rewrites_both_editable_files(self, tmp_path):
        project = self._project(tmp_path)

        integrate.apply(project, crom_bytes=4194304, prom2_bytes=1048576)

        assert "CROMSIZE=4194304" in (project / "rom.mk").read_text()
        assert "include fmv/fmv.mk" in (project / "Makefile").read_text()

    def test_it_leaves_every_other_file_alone(self, tmp_path):
        project = self._project(tmp_path)
        (project / "build.mk").write_text("untouched\n")

        integrate.apply(project, crom_bytes=4194304, prom2_bytes=1048576)

        assert (project / "build.mk").read_text() == "untouched\n"

    def test_the_command_line_applies_the_same_edits(self, tmp_path):
        project = self._project(tmp_path)

        code = integrate.main([str(project), "4194304", "1048576"])

        assert code == 0
        assert "PROM2SIZE = 1048576" in (project / "Makefile").read_text()
