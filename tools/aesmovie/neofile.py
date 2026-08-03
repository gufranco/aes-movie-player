"""Write the .neo cart container without loading the cart into memory.

This replaces neosdconv, which holds the whole cartridge in a Node heap
and is killed by the OOM reaper once the C-ROM passes a few tens of
megabytes. A movie cart is mostly C-ROM by definition, so that ceiling
bounded the entire project. Writing the container in fixed-size chunks
keeps memory flat no matter how long the movie is.

The layout was recovered from a known-good neosdconv file and
cross-checked against geolith's `geo_neo_load`. A 4096-byte header holds
a magic tag, six little-endian region sizes, four metadata words, a
33-byte name and a 17-byte manufacturer. The regions follow in the order
P, S, M, V1, V2, C. The character region is the two ROM halves
interleaved byte by byte, which is what the LSPC tile decoder expects.

This module imports only the standard library so the build can run it
with whatever bare python3 the toolchain container happens to ship.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from typing import BinaryIO, Final

MAGIC: Final = b"NEO\x01"
HEADER_BYTES: Final = 4096
NAME_BYTES: Final = 33
MANUFACTURER_BYTES: Final = 17
NAME_OFFSET: Final = 44
MANUFACTURER_OFFSET: Final = 77
DEFAULT_CHUNK_BYTES: Final = 1 << 20

REGION_FILES: Final = {
    "p": "p1.p1",
    "s": "s1.s1",
    "m": "m1.m1",
    "v1": "v11.v1",
    "c1": "c1.c1",
    "c2": "c2.c2",
}


def _require(rom_dir: Path, key: str) -> Path:
    path = rom_dir / REGION_FILES[key]
    if not path.is_file():
        msg = f"missing cart region {REGION_FILES[key]} in {rom_dir}"
        raise FileNotFoundError(msg)
    return path


def build_header(
    *,
    psz: int,
    ssz: int,
    msz: int,
    v1sz: int,
    v2sz: int,
    csz: int,
    name: str,
    manufacturer: str,
    year: int,
    genre: int,
    screenshot: int,
    ngh: int,
) -> bytes:
    """Build the 4096-byte container header."""
    if len(name.encode()) >= NAME_BYTES:
        msg = f"name must be shorter than {NAME_BYTES} bytes, got {name!r}"
        raise ValueError(msg)
    if len(manufacturer.encode()) >= MANUFACTURER_BYTES:
        msg = f"manufacturer must be shorter than {MANUFACTURER_BYTES} bytes, got {manufacturer!r}"
        raise ValueError(msg)

    header = bytearray(HEADER_BYTES)
    header[0:4] = MAGIC
    struct.pack_into("<6I", header, 4, psz, ssz, msz, v1sz, v2sz, csz)
    struct.pack_into("<4I", header, 28, year, genre, screenshot, ngh)
    header[NAME_OFFSET : NAME_OFFSET + len(name.encode())] = name.encode()
    encoded = manufacturer.encode()
    header[MANUFACTURER_OFFSET : MANUFACTURER_OFFSET + len(encoded)] = encoded
    return bytes(header)


def _copy(source: Path, target: BinaryIO, chunk_bytes: int) -> None:
    with source.open("rb") as handle:
        while True:
            block = handle.read(chunk_bytes)
            if not block:
                return
            target.write(block)


def _interleave(first: Path, second: Path, target: BinaryIO, chunk_bytes: int) -> None:
    with first.open("rb") as left, second.open("rb") as right:
        while True:
            a = left.read(chunk_bytes)
            b = right.read(chunk_bytes)
            if not a and not b:
                return
            merged = bytearray(len(a) + len(b))
            merged[0::2] = a
            merged[1::2] = b
            target.write(merged)


def write_neo(
    *,
    rom_dir: Path,
    output: Path,
    name: str = "AES Movie Player",
    manufacturer: str = "aesmovie",
    year: int = 2026,
    genre: int = 0,
    screenshot: int = 1,
    ngh: int = 0x9999,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> Path:
    """Assemble the cart regions into a .neo container."""
    rom_dir = Path(rom_dir)
    paths = {key: _require(rom_dir, key) for key in REGION_FILES}
    sizes = {key: path.stat().st_size for key, path in paths.items()}
    if sizes["c1"] != sizes["c2"]:
        msg = f"character halves must be the same size, got {sizes['c1']} and {sizes['c2']}"
        raise ValueError(msg)

    header = build_header(
        psz=sizes["p"],
        ssz=sizes["s"],
        msz=sizes["m"],
        v1sz=sizes["v1"],
        v2sz=0,
        csz=sizes["c1"] + sizes["c2"],
        name=name,
        manufacturer=manufacturer,
        year=year,
        genre=genre,
        screenshot=screenshot,
        ngh=ngh,
    )

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as target:
        target.write(header)
        for key in ("p", "s", "m", "v1"):
            _copy(paths[key], target, chunk_bytes)
        _interleave(paths["c1"], paths["c2"], target, chunk_bytes)
    return output


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Assemble a .neo cart container.")
    parser.add_argument("--rom-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", default="AES Movie Player")
    parser.add_argument("--manufacturer", default="aesmovie")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--ngh", type=lambda value: int(value, 0), default=0x9999)
    args = parser.parse_args(argv)

    path = write_neo(
        rom_dir=args.rom_dir,
        output=args.output,
        name=args.name,
        manufacturer=args.manufacturer,
        year=args.year,
        ngh=args.ngh,
    )
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
