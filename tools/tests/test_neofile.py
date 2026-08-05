"""Cart container tests.

The field offsets and the byte-interleaved C region were recovered from
a known-good file produced by neosdconv and cross-checked against
geolith's `geo_neo_load`, so these tests assert against the format the
emulator actually parses rather than against the writer's own idea of it.
"""

from __future__ import annotations

import struct

import pytest

from aesmovie import neofile

HEADER_BYTES = 4096


def write_regions(directory, *, p=b"", s=b"", m=b"", v1=b"", v2=None, c1=b"", c2=b""):
    (directory / "p1.p1").write_bytes(p)
    (directory / "s1.s1").write_bytes(s)
    (directory / "m1.m1").write_bytes(m)
    (directory / "v11.v1").write_bytes(v1)
    if v2 is not None:
        (directory / "v21.v2").write_bytes(v2)
    (directory / "c1.c1").write_bytes(c1)
    (directory / "c2.c2").write_bytes(c2)
    return directory


def read_header(path):
    data = path.read_bytes()[:HEADER_BYTES]
    tag = data[:4]
    sizes = struct.unpack_from("<6I", data, 4)
    year, genre, screenshot, ngh = struct.unpack_from("<4I", data, 28)
    return {
        "tag": tag,
        "psz": sizes[0],
        "ssz": sizes[1],
        "msz": sizes[2],
        "v1sz": sizes[3],
        "v2sz": sizes[4],
        "csz": sizes[5],
        "year": year,
        "genre": genre,
        "screenshot": screenshot,
        "ngh": ngh,
        "name": data[44:77].rstrip(b"\x00").decode(),
        "manufacturer": data[77:94].rstrip(b"\x00").decode(),
    }


@pytest.fixture
def cart(tmp_path):
    rom = write_regions(
        tmp_path,
        p=bytes(range(64)),
        s=bytes(range(32)),
        m=bytes(range(16)),
        v1=bytes(range(8)),
        c1=bytes([0x11, 0x22, 0x33, 0x44]),
        c2=bytes([0xAA, 0xBB, 0xCC, 0xDD]),
    )
    out = tmp_path / "cart.neo"
    neofile.write_neo(
        rom_dir=rom, output=out, name="Test Cart", manufacturer="tester", year=2026, ngh=0x1234
    )
    return out


class TestHeader:
    def test_the_magic_identifies_a_neo_container(self, cart):
        assert read_header(cart)["tag"] == b"NEO\x01"

    def test_region_sizes_match_the_inputs(self, cart):
        header = read_header(cart)

        assert (header["psz"], header["ssz"], header["msz"]) == (64, 32, 16)

    def test_the_second_voice_region_is_absent_by_default(self, cart):
        assert read_header(cart)["v2sz"] == 0

    def test_the_character_region_is_both_halves_together(self, cart):
        assert read_header(cart)["csz"] == 8

    def test_metadata_round_trips(self, cart):
        header = read_header(cart)

        assert header["name"] == "Test Cart"
        assert header["manufacturer"] == "tester"
        assert header["year"] == 2026
        assert header["ngh"] == 0x1234

    def test_the_header_occupies_exactly_four_kibibytes(self, cart):
        header = read_header(cart)
        payload = header["psz"] + header["ssz"] + header["msz"] + header["v1sz"] + header["csz"]

        assert cart.stat().st_size == HEADER_BYTES + payload


class TestPayload:
    def test_regions_follow_the_documented_order(self, cart):
        data = cart.read_bytes()
        header = read_header(cart)
        offset = HEADER_BYTES

        assert data[offset : offset + header["psz"]] == bytes(range(64))
        offset += header["psz"]
        assert data[offset : offset + header["ssz"]] == bytes(range(32))
        offset += header["ssz"]
        assert data[offset : offset + header["msz"]] == bytes(range(16))

    def test_the_character_region_interleaves_the_two_halves(self, cart):
        data = cart.read_bytes()
        header = read_header(cart)
        offset = HEADER_BYTES + header["psz"] + header["ssz"] + header["msz"] + header["v1sz"]

        assert data[offset : offset + 8] == bytes([0x11, 0xAA, 0x22, 0xBB, 0x33, 0xCC, 0x44, 0xDD])


class TestValidation:
    def test_mismatched_character_halves_are_rejected(self, tmp_path):
        rom = write_regions(tmp_path, c1=b"\x01\x02\x03", c2=b"\x01\x02")

        with pytest.raises(ValueError, match="same size"):
            neofile.write_neo(rom_dir=rom, output=tmp_path / "x.neo")

    def test_a_missing_region_file_is_rejected(self, tmp_path):
        (tmp_path / "p1.p1").write_bytes(b"\x00")

        with pytest.raises(FileNotFoundError, match=r"s1\.s1"):
            neofile.write_neo(rom_dir=tmp_path, output=tmp_path / "x.neo")

    def test_an_overlong_name_is_rejected(self, tmp_path):
        rom = write_regions(tmp_path, c1=b"\x01", c2=b"\x02")

        with pytest.raises(ValueError, match="name"):
            neofile.write_neo(rom_dir=rom, output=tmp_path / "x.neo", name="x" * 40)

    def test_an_overlong_manufacturer_is_rejected(self, tmp_path):
        rom = write_regions(tmp_path, c1=b"\x01", c2=b"\x02")

        with pytest.raises(ValueError, match="manufacturer"):
            neofile.write_neo(rom_dir=rom, output=tmp_path / "x.neo", manufacturer="y" * 40)


class TestStreaming:
    def test_a_large_character_region_is_written_without_holding_it_all(self, tmp_path):
        half = bytes(256) * 4096
        rom = write_regions(tmp_path, c1=half, c2=half)
        out = tmp_path / "big.neo"

        neofile.write_neo(rom_dir=rom, output=out, chunk_bytes=4096)

        assert read_header(out)["csz"] == len(half) * 2

    def test_chunked_interleaving_matches_a_direct_interleave(self, tmp_path):
        c1 = bytes(range(256)) * 8
        c2 = bytes(range(255, -1, -1)) * 8
        rom = write_regions(tmp_path, c1=c1, c2=c2)
        out = tmp_path / "chunked.neo"

        neofile.write_neo(rom_dir=rom, output=out, chunk_bytes=7)

        expected = bytearray(len(c1) * 2)
        expected[0::2] = c1
        expected[1::2] = c2
        assert out.read_bytes()[HEADER_BYTES:] == bytes(expected)


class TestSecondVoiceRegion:
    def test_the_second_voice_region_is_declared_when_present(self, tmp_path):
        rom = write_regions(tmp_path, v1=b"\x01\x02", v2=b"\x0a\x0b\x0c", c1=b"\x01", c2=b"\x02")
        out = tmp_path / "voice.neo"

        neofile.write_neo(rom_dir=rom, output=out)

        assert read_header(out)["v2sz"] == 3

    def test_the_second_voice_region_follows_the_first(self, tmp_path):
        rom = write_regions(tmp_path, v1=b"\x01\x02", v2=b"\x0a\x0b\x0c", c1=b"\x01", c2=b"\x02")
        out = tmp_path / "voice.neo"

        neofile.write_neo(rom_dir=rom, output=out)

        header = read_header(out)
        offset = HEADER_BYTES + header["psz"] + header["ssz"] + header["msz"]
        assert out.read_bytes()[offset : offset + 5] == b"\x01\x02\x0a\x0b\x0c"

    def test_the_character_region_still_follows_both_voices(self, tmp_path):
        rom = write_regions(tmp_path, v1=b"\x01", v2=b"\x0a", c1=b"\xf0", c2=b"\x0f")
        out = tmp_path / "voice.neo"

        neofile.write_neo(rom_dir=rom, output=out)

        header = read_header(out)
        offset = (
            HEADER_BYTES
            + header["psz"]
            + header["ssz"]
            + header["msz"]
            + header["v1sz"]
            + header["v2sz"]
        )
        assert out.read_bytes()[offset : offset + 2] == b"\xf0\x0f"


@pytest.fixture
def rom_dir(tmp_path):
    return write_regions(
        tmp_path,
        p=bytes(range(64)),
        s=bytes(range(32)),
        m=bytes(range(16)),
        v1=bytes(range(8)),
        c1=bytes([0x11, 0x22, 0x33, 0x44]),
        c2=bytes([0xAA, 0xBB, 0xCC, 0xDD]),
    )


class TestTheCommandLine:
    def test_it_writes_the_container_the_build_script_asks_for(self, rom_dir, tmp_path, capsys):
        output = tmp_path / "out" / "cart.neo"

        code = neofile.main(["--rom-dir", str(rom_dir), "--output", str(output)])

        assert code == 0
        assert output.is_file()
        assert str(output) in capsys.readouterr().out

    def test_the_name_reaches_the_header(self, rom_dir, tmp_path):
        output = tmp_path / "cart.neo"

        neofile.main(
            ["--rom-dir", str(rom_dir), "--output", str(output), "--name", "SOMETHING ELSE"]
        )

        assert b"SOMETHING ELSE" in output.read_bytes()[:4096]

    def test_the_ngh_accepts_hexadecimal(self, rom_dir, tmp_path):
        output = tmp_path / "cart.neo"

        code = neofile.main(["--rom-dir", str(rom_dir), "--output", str(output), "--ngh", "0x1234"])

        assert code == 0

    def test_a_missing_region_stops_it_rather_than_writing_half_a_cart(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()

        with pytest.raises((FileNotFoundError, SystemExit)):
            neofile.main(["--rom-dir", str(empty), "--output", str(tmp_path / "cart.neo")])
