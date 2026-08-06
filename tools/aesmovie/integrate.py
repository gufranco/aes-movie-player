"""Apply the edits the bundle's integration guide asks a developer for.

This is the guide in executable form. Every change lands in the
project's own `Makefile` and `rom.mk`, the two files an ngdevkit project
exists to have edited. Nothing here touches a linkscript, and nothing
touches a file the baker emitted. If that ever stops being true, the
shape of the bundle is wrong rather than the shape of this module.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

BUILD_INCLUDE: Final = "include build.mk"
STOCK_CROM_SIZE: Final = "CROMSIZE=2097152"
STOCK_PROM2: Final = "# PROM2=$(ROM)/$(GAMEROM)-p2.p2"

STOCK_PROGRAM_ROM: Final = "ELF=$(BUILDDIR)/rom.elf\n$(ELF):\t$(BUILDDIR)/main.o\n$(PROM1): $(ELF)"
MOVIE_PROGRAM_ROM: Final = "$(PROM1): $(BUILDDIR)/rom-fmv-bank0.elf"

STOCK_SOUND_DRIVER: Final = "SOUND_DRIVER=$(BUILDDIR)/assets/base-sound-driver.ihx"
SILENT_SOUND_DRIVER: Final = "SOUND_DRIVER=$(NGSHAREDIR)/nullsound_driver.ihx"
MOVIE_SOUND_DRIVER: Final = "SOUND_DRIVER=$(FMV_SOUND_DRIVER)"

STOCK_CARTRIDGE_ASSETS: Final = (
    (
        "$(SROM1): $(BUILDDIR)/assets/base-srom-text-shadow.fix",
        "$(SROM1): $(FMV_MOVIE)/fix.s1",
    ),
    (
        "$(CROM1): $(BUILDDIR)/assets/base-crom-logo.c1\n"
        "$(CROM2): $(BUILDDIR)/assets/base-crom-logo.c2",
        "$(CROM1): $(FMV_MOVIE)/c1.bin\n$(CROM2): $(FMV_MOVIE)/c2.bin",
    ),
)


def cartridge_edits(text: str) -> str:
    """Declare the second program ROM and widen the sprite ROM.

    A stock template leaves the second program ROM commented out and
    sizes the sprite ROM for a demo logo. A movie needs both, and the
    size comes from the fragment rather than from anyone measuring a
    file, so a re-bake carries its own new size with it.
    """
    if STOCK_PROM2 not in text or STOCK_CROM_SIZE not in text:
        msg = "the stock rom.mk no longer looks the way the guide describes"
        raise SystemExit(msg)
    text = text.replace(STOCK_PROM2, "PROM2=$(ROM)/$(GAMEROM)-p2.p2")
    return text.replace(STOCK_CROM_SIZE, "CROMSIZE=$(FMV_CROM_BYTES)")


def makefile_edits(text: str, *, audio: bool = False) -> str:
    """Include the fragment and point the cartridge at the movie.

    The include sits between the cartridge declaration and the build
    rules, because the fragment adds its own directories to `SRCDIRS`
    and the build rules read that.

    The lines that name the template's demo assets are replaced rather
    than added to. A cartridge target takes its content from its first
    prerequisite, so leaving the stock line in place would build the
    ROM from the logo the template ships instead of from the movie.
    """
    for stock in (BUILD_INCLUDE, STOCK_PROGRAM_ROM):
        if stock not in text:
            msg = f"the stock Makefile no longer carries {stock!r}"
            raise SystemExit(msg)

    added = f"""FMV_GAME_OBJS = $(BUILDDIR)/main.o
FMV_AUDIO = {"yes" if audio else "no"}
PROM2SIZE = $(FMV_PROM2_BYTES)
CFLAGS += $(FMV_CFLAGS)
LDFLAGS += $(FMV_LDFLAGS)
include fmv/fmv.mk

{BUILD_INCLUDE}"""
    text = text.replace(BUILD_INCLUDE, added, 1)
    text = text.replace(STOCK_PROGRAM_ROM, MOVIE_PROGRAM_ROM, 1)
    driver = MOVIE_SOUND_DRIVER if audio else SILENT_SOUND_DRIVER
    for stock, movie in (*STOCK_CARTRIDGE_ASSETS, (STOCK_SOUND_DRIVER, driver)):
        if stock not in text:
            msg = f"the stock Makefile no longer carries {stock!r}"
            raise SystemExit(msg)
        text = text.replace(stock, movie, 1)
    return text


def apply(project: Path, *, audio: bool = False) -> None:
    """Rewrite a stock project's two editable files in place."""
    cartridge = project / "rom.mk"
    cartridge.write_text(cartridge_edits(cartridge.read_text()))
    makefile = project / "Makefile"
    makefile.write_text(makefile_edits(makefile.read_text(), audio=audio))


def main(argv: list[str]) -> int:
    apply(Path(argv[0]), audio="--audio" in argv[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
