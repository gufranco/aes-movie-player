"""MAME cart packaging tests.

The dataarea names and load flags are the ones MAME's Neo Geo cart slot
looks for, taken from `src/devices/bus/neogeo/slot.cpp`. Packaging for a
second, independent emulator is the closest available stand-in for a
console: an encoding that both geolith and MAME agree on is far more
likely to be right on hardware than one confirmed by either alone.
"""

from __future__ import annotations

import hashlib
import zipfile
from xml.etree import ElementTree

import pytest

from aesmovie import mamecart


@pytest.fixture
def rom_dir(tmp_path):
    (tmp_path / "p1.p1").write_bytes(bytes(range(256)) * 8)
    (tmp_path / "s1.s1").write_bytes(bytes(64))
    (tmp_path / "m1.m1").write_bytes(bytes(32))
    (tmp_path / "v11.v1").write_bytes(bytes(16))
    (tmp_path / "v21.v2").write_bytes(bytes(48))
    (tmp_path / "c1.c1").write_bytes(bytes(128))
    (tmp_path / "c2.c2").write_bytes(bytes(128))
    return tmp_path


class TestArchive:
    def test_it_writes_a_zip_of_the_rom_files(self, rom_dir, tmp_path):
        out = tmp_path / "cart.zip"

        mamecart.write_cart(rom_dir=rom_dir, output=out)

        with zipfile.ZipFile(out) as archive:
            assert set(archive.namelist()) >= {"p1.p1", "s1.s1", "m1.m1", "c1.c1", "c2.c2"}

    def test_the_second_voice_region_is_included_when_present(self, rom_dir, tmp_path):
        out = tmp_path / "cart.zip"

        mamecart.write_cart(rom_dir=rom_dir, output=out)

        with zipfile.ZipFile(out) as archive:
            assert "v21.v2" in archive.namelist()

    def test_the_archive_stores_files_uncompressed_by_default(self, rom_dir, tmp_path):
        out = tmp_path / "cart.zip"

        mamecart.write_cart(rom_dir=rom_dir, output=out)

        with zipfile.ZipFile(out) as archive:
            assert all(i.compress_type == zipfile.ZIP_STORED for i in archive.infolist())


class TestSoftwareList:
    def parse(self, path):
        return ElementTree.parse(path).getroot()

    def test_it_writes_a_software_list(self, rom_dir, tmp_path):
        out = tmp_path / "cart.zip"

        result = mamecart.write_cart(rom_dir=rom_dir, output=out)

        assert result.software_list.is_file()

    def test_the_list_is_named_neogeo(self, rom_dir, tmp_path):
        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        assert self.parse(result.software_list).get("name") == "neogeo"

    def test_the_part_uses_the_cart_interface(self, rom_dir, tmp_path):
        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        part = self.parse(result.software_list).find("software/part")
        assert part.get("interface") == "neo_cart"

    def test_every_region_uses_the_name_mame_looks_for(self, rom_dir, tmp_path):
        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        names = {d.get("name") for d in self.parse(result.software_list).iter("dataarea")}
        assert names == {"maincpu", "fixed", "audiocpu", "ymsnd:adpcma", "ymsnd:adpcmb", "sprites"}

    def test_the_program_rom_is_word_swapped_on_load(self, rom_dir, tmp_path):
        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        root = self.parse(result.software_list)
        maincpu = next(d for d in root.iter("dataarea") if d.get("name") == "maincpu")
        assert maincpu.find("rom").get("loadflag") == "load16_word_swap"

    def test_the_character_halves_interleave_on_load(self, rom_dir, tmp_path):
        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        root = self.parse(result.software_list)
        sprites = next(d for d in root.iter("dataarea") if d.get("name") == "sprites")
        assert [r.get("loadflag") for r in sprites.findall("rom")] == [
            "load16_byte",
            "load16_byte",
        ]

    def test_the_sprite_area_is_both_halves_together(self, rom_dir, tmp_path):
        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        root = self.parse(result.software_list)
        sprites = next(d for d in root.iter("dataarea") if d.get("name") == "sprites")
        assert int(sprites.get("size")) == 256

    def test_every_rom_carries_a_checksum(self, rom_dir, tmp_path):
        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        for rom in self.parse(result.software_list).iter("rom"):
            assert len(rom.get("sha1")) == 40
            assert len(rom.get("crc")) == 8

    def test_the_checksums_match_the_archived_files(self, rom_dir, tmp_path):
        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        root = self.parse(result.software_list)
        rom = next(r for r in root.iter("rom") if r.get("name") == "p1.p1")
        expected = hashlib.sha1((rom_dir / "p1.p1").read_bytes()).hexdigest()
        assert rom.get("sha1") == expected

    def test_the_voice_region_is_omitted_when_absent(self, rom_dir, tmp_path):
        (rom_dir / "v21.v2").unlink()

        result = mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "cart.zip")

        names = {d.get("name") for d in self.parse(result.software_list).iter("dataarea")}
        assert "ymsnd:adpcmb" not in names


class TestValidation:
    def test_a_missing_region_is_rejected(self, tmp_path):
        (tmp_path / "p1.p1").write_bytes(b"\x00")

        with pytest.raises(FileNotFoundError, match=r"s1\.s1"):
            mamecart.write_cart(rom_dir=tmp_path, output=tmp_path / "x.zip")

    def test_a_program_rom_beyond_the_bank_register_is_rejected(self, tmp_path, rom_dir):
        (rom_dir / "p1.p1").write_bytes(bytes(10 << 20))

        with pytest.raises(ValueError, match="bank"):
            mamecart.write_cart(rom_dir=rom_dir, output=tmp_path / "x.zip")
