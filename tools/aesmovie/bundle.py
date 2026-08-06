"""Emit a folder a game project drops in to get a movie into its cart.

Everything ships as source. The library is copied rather than installed,
so the copy a developer holds is pinned to the bake that produced it,
and a mismatch between the two announces itself at compile time instead
of misbehaving at runtime.

The layout mirrors what an ngdevkit project already looks like: source
under one directory, generated data under another, and a make fragment
to include. Nothing here reaches outside the emitted folder, so dropping
it in touches only files the developer owns.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from aesmovie import crom
from aesmovie import stream as stream_mod

LIBRARY_DIR_NAME: Final = "src"
MOVIE_DIR_NAME: Final = "movie"
MAKEFILE_NAME: Final = "fmv.mk"
GUIDE_NAME: Final = "README.md"

LIBRARY_SOURCES: Final = (
    "fmv.h",
    "fmv.c",
    "fmv_audio.h",
    "fmv_audio.c",
    "hw.h",
    "timeline.h",
    "timeline.c",
)
"""The video path. `fmv.h` is the only header a caller includes."""

AUDIO_SOURCES: Final = ("sound.s",)
"""The reference Z80 driver, which a caller hosts or replaces."""

GENERATED_SOURCES: Final = ("movie_data.S", "movie_data.h", "movie_data_value.c")

GENERATED_OPTIONAL: Final = ("audio_params.s",)

PACKAGERS: Final = ("neofile.py", "mamecart.py")
"""Cartridge packagers that can express an ADPCM-B ROM.

ngdevkit's own romtool declares every voice ROM as ADPCM-A, and
MAME allocates a delta-T region only when a software list names
`ymsnd:adpcmb`, so a soundtrack packaged that way is silent. These
two are standard-library only and travel with the bundle."""

PACKAGER_DIR_NAME: Final = "package"

BAKED_ASSETS: Final = (
    "index.bin",
    "keyframes.bin",
    "palettes.bin",
    "epochs.bin",
    "fixpal.bin",
    "subtitles.bin",
    "stream.bin",
    "c1.bin",
    "c2.bin",
    "fix.s1",
)

BAKED_OPTIONAL: Final = ("v2.bin",)

STREAM_BANK_GLOB: Final = "fmv_stream__bank*.S"

_TEMPLATES: Final = Path(__file__).resolve().parent / "templates"
LIBRARY_ROOT: Final = Path(__file__).resolve().parents[2] / "src" / "fmv"
PACKAGER_ROOT: Final = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class BundleLayout:
    root: Path
    library: Path
    movie: Path
    makefile: Path
    guide: Path
    stream_banks: int
    has_audio: bool


def rom_image_size(payload: int) -> int:
    """Round a payload up to a size a Neo Geo ROM image may take.

    Every ROM in a cartridge is a power of two, because the hardware
    masks an address with a mask derived from the size. A payload that
    lands anywhere else is padded by whoever assembles the cartridge.
    """
    size = 1 << 20
    while size < payload:
        size <<= 1
    return size


def _copy_all(names: tuple[str, ...], source: Path, target: Path, *, required: bool) -> list[Path]:
    copied: list[Path] = []
    for name in names:
        origin = source / name
        if not origin.is_file():
            if required:
                msg = f"the bundle needs {name}, which is not in {source}"
                raise FileNotFoundError(msg)
            continue
        shutil.copy2(origin, target / name)
        copied.append(target / name)
    return copied


def _render(name: str, fields: dict[str, object]) -> str:
    return (_TEMPLATES / name).read_text(encoding="utf-8").format(**fields)


def write_bundle(
    *,
    target: Path,
    build_dir: Path,
    stream_banks: int,
    max_updates: int,
    tick_cycles: int,
    tile_count: int,
    crom_payload: int,
    crom_size: int,
    palette_base: int,
    first_sprite: int,
    frames: int,
    version: tuple[int, int],
    library_root: Path = LIBRARY_ROOT,
) -> BundleLayout:
    """Write the drop-in folder and return where each part landed."""
    target = Path(target)
    library = target / LIBRARY_DIR_NAME
    movie = target / MOVIE_DIR_NAME
    for directory in (target, library, movie):
        directory.mkdir(parents=True, exist_ok=True)

    _copy_all(LIBRARY_SOURCES, Path(library_root), library, required=True)
    audio_sources = _copy_all(AUDIO_SOURCES, Path(library_root), library, required=False)

    generated = Path(build_dir) / "generated"
    baked = Path(build_dir) / "baked"
    _copy_all(GENERATED_SOURCES, generated, movie, required=True)
    _copy_all(GENERATED_OPTIONAL, generated, movie, required=False)
    _copy_all(BAKED_ASSETS, baked, movie, required=True)
    voice = _copy_all(BAKED_OPTIONAL, baked, movie, required=False)

    packagers = target / PACKAGER_DIR_NAME
    packagers.mkdir(parents=True, exist_ok=True)
    _copy_all(PACKAGERS, PACKAGER_ROOT, packagers, required=True)

    banks = sorted(generated.glob(STREAM_BANK_GLOB))
    if len(banks) != stream_banks:
        msg = (
            f"the bake reports {stream_banks} stream bank(s) but emitted {len(banks)} stub(s); "
            f"the bundle would carry a stream with a hole in it"
        )
        raise ValueError(msg)
    for stub in banks:
        shutil.copy2(stub, movie / stub.name)

    major, minor = version
    fields: dict[str, object] = {
        "version": f"{major}.{minor}",
        "library_dir": LIBRARY_DIR_NAME,
        "movie_dir": MOVIE_DIR_NAME,
        "packager_dir": PACKAGER_DIR_NAME,
        "stream_banks": stream_banks,
        "last_bank": stream_banks - 1,
        "bank_numbers": " ".join(str(bank) for bank in range(stream_banks)),
        "max_updates": max_updates,
        "tick_cycles": tick_cycles,
        "tile_count": tile_count,
        "last_tile": tile_count - 1,
        "crom_payload": crom_payload,
        "crom_size": crom_size,
        "vrom_size": rom_image_size(voice[0].stat().st_size) if voice else 0,
        "free_tiles": (crom_size - crom_payload) // crom.TILE_BYTES_PER_ROM,
        "palette_base": palette_base,
        "first_sprite": first_sprite,
        "last_sprite": first_sprite + stream_mod.GRID_COLS - 1,
        "frames": frames,
        "audio": "yes" if voice else "no",
    }

    makefile = target / MAKEFILE_NAME
    makefile.write_text(_render(MAKEFILE_NAME, fields), encoding="utf-8")
    guide = target / GUIDE_NAME
    guide.write_text(_render("bundle_readme.md", fields), encoding="utf-8")

    return BundleLayout(
        root=target,
        library=library,
        movie=movie,
        makefile=makefile,
        guide=guide,
        stream_banks=stream_banks,
        has_audio=bool(voice and audio_sources),
    )
