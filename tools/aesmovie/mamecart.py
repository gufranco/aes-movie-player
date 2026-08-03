"""Package the cart for MAME as well as for a flash cart.

Everything this project encodes was confirmed against geolith, which
models the board rather than being it. MAME is a second, independent
implementation, so a cart that behaves identically in both is far more
likely to be right on a console than one confirmed by either alone. That
matters here because the two emulators do not agree on everything: MAME
masks the program-ROM bank register with 0x07, matching the three-bit
latch on real hardware, while geolith allows far more banks. A cart that
overruns eight banks runs in geolith and reads the wrong bank on
hardware.

The dataarea names, sizes and load flags are the ones MAME's Neo Geo
cart slot looks for in `src/devices/bus/neogeo/slot.cpp`. `maincpu`
loads word-swapped because the ROM image is in physical MASK ROM order,
and the two character halves load byte-interleaved.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

PROM_FIXED_BYTES: Final = 1 << 20
PROM_BANK_BYTES: Final = 1 << 20
PROM_BANK_LIMIT: Final = 8
PROM_MAX_BYTES: Final = PROM_FIXED_BYTES + PROM_BANK_LIMIT * PROM_BANK_BYTES

REQUIRED_REGIONS: Final = ("p1.p1", "s1.s1", "m1.m1", "v11.v1", "c1.c1", "c2.c2")
OPTIONAL_REGIONS: Final = ("v21.v2",)


@dataclass(frozen=True, slots=True)
class CartPackage:
    archive: Path
    software_list: Path


def _digests(path: Path) -> tuple[str, str]:
    payload = path.read_bytes()
    return hashlib.sha1(payload).hexdigest(), format(zlib.crc32(payload) & 0xFFFFFFFF, "08x")


def _rom_element(
    parent: ElementTree.Element, path: Path, loadflag: str | None = None, offset: int = 0
) -> None:
    """Add one rom entry.

    The offset is not optional. MAME's own software lists carry it on
    every entry, and an interleaved pair needs 0 and 1 to land on
    alternating bytes. Omitting it loads both halves at zero, so the
    second silently overwrites the first and the sprite layer decodes
    from wrong data.
    """
    sha1, crc = _digests(path)
    attrs = {
        "name": path.name,
        "offset": f"0x{offset:06x}",
        "size": str(path.stat().st_size),
        "crc": crc,
        "sha1": sha1,
    }
    if loadflag:
        attrs["loadflag"] = loadflag
    ElementTree.SubElement(parent, "rom", attrs)


def build_software_list(
    rom_dir: Path, *, name: str, description: str, year: int, publisher: str
) -> ElementTree.Element:
    """Build the software-list entry MAME binds cart regions with."""
    root = ElementTree.Element(
        "softwarelist", {"name": "neogeo", "description": f"{description} homebrew cartridge"}
    )
    software = ElementTree.SubElement(root, "software", {"name": name})
    ElementTree.SubElement(software, "description").text = description
    ElementTree.SubElement(software, "year").text = str(year)
    ElementTree.SubElement(software, "publisher").text = publisher
    part = ElementTree.SubElement(software, "part", {"name": "cart", "interface": "neo_cart"})
    ElementTree.SubElement(part, "feature", {"name": "release", "value": "AES"})

    program = rom_dir / "p1.p1"
    area = ElementTree.SubElement(
        part,
        "dataarea",
        {
            "name": "maincpu",
            "size": str(program.stat().st_size),
            "width": "16",
            "endianness": "big",
        },
    )
    _rom_element(area, program, "load16_word_swap")

    for region, area_name in (
        ("s1.s1", "fixed"),
        ("m1.m1", "audiocpu"),
        ("v11.v1", "ymsnd:adpcma"),
    ):
        path = rom_dir / region
        area = ElementTree.SubElement(
            part, "dataarea", {"name": area_name, "size": str(path.stat().st_size)}
        )
        _rom_element(area, path)

    voice_two = rom_dir / "v21.v2"
    if voice_two.is_file():
        area = ElementTree.SubElement(
            part, "dataarea", {"name": "ymsnd:adpcmb", "size": str(voice_two.stat().st_size)}
        )
        _rom_element(area, voice_two)

    first, second = rom_dir / "c1.c1", rom_dir / "c2.c2"
    area = ElementTree.SubElement(
        part,
        "dataarea",
        {
            "name": "sprites",
            "size": str(first.stat().st_size + second.stat().st_size),
            "width": "32",
        },
    )
    _rom_element(area, first, "load16_byte", offset=0)
    _rom_element(area, second, "load16_byte", offset=1)
    return root


def write_cart(
    *,
    rom_dir: Path,
    output: Path,
    name: str = "aesmovie",
    description: str = "AES Movie Player",
    year: int = 2026,
    publisher: str = "aesmovie",
) -> CartPackage:
    """Write the MAME zip and the software list that binds it."""
    rom_dir = Path(rom_dir)
    for region in REQUIRED_REGIONS:
        if not (rom_dir / region).is_file():
            msg = f"missing cart region {region} in {rom_dir}"
            raise FileNotFoundError(msg)

    program_bytes = (rom_dir / "p1.p1").stat().st_size
    if program_bytes > PROM_MAX_BYTES:
        msg = (
            f"program ROM is {program_bytes} bytes, beyond the {PROM_MAX_BYTES} the three-bit "
            f"bank register can reach"
        )
        raise ValueError(msg)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    present = [r for r in (*REQUIRED_REGIONS, *OPTIONAL_REGIONS) if (rom_dir / r).is_file()]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
        for region in present:
            archive.write(rom_dir / region, region)

    listing = output.parent / "mame-hash" / "neogeo.xml"
    listing.parent.mkdir(parents=True, exist_ok=True)
    tree = ElementTree.ElementTree(
        build_software_list(
            rom_dir, name=name, description=description, year=year, publisher=publisher
        )
    )
    ElementTree.indent(tree, space="    ")
    tree.write(listing, encoding="utf-8", xml_declaration=True)
    return CartPackage(archive=output, software_list=listing)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Package the cart for MAME.")
    parser.add_argument("--rom-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    package = write_cart(rom_dir=args.rom_dir, output=args.output)
    print(f"wrote {package.archive} and {package.software_list}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
