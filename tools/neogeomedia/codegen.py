from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from importlib.metadata import version
from pathlib import Path
from typing import Final

from neogeomedia import crom, encode, epochs, fixtiles, frames, limits, subtitles
from neogeomedia import stream as stream_mod

CROM_BANK_BYTES: Final = 128 << 20
PERCENT: Final = 100

MOVIE_SYMBOL: Final = "fmv_movie_data"
STREAM_BASE_SYMBOL: Final = "fmv_stream_base"
STREAM_BANK_SYMBOL: Final = "fmv_stream_bank"
STREAM_BANK_STEM: Final = "fmv_stream__bank"

FIX_PALETTE_BANK: Final = 1

CYCLES_PER_UPDATE: Final = 64
CYCLES_PER_LINE: Final = 768
BLANK_LINES: Final = 40
VBLANK_CYCLES: Final = (BLANK_LINES - 1) * CYCLES_PER_LINE

GENERATED_DIR: Final = "generated"
SEEK_FRAMES: Final = round(limits.SEEK_EVERY_SECONDS * float(frames.VBLANK_FPS))

_ASM_BLOBS: Final = (
    ("movie_index", "index"),
    ("movie_keyframes", "keyframes"),
    ("movie_palettes", "palettes"),
    ("movie_epochs", "epochs"),
    ("movie_fix_palette", "fixpal"),
    ("movie_subtitles", "subtitles"),
)

_FIX_GLYPH_MACROS: Final = {
    "blank": "FIX_TILE_BLANK",
    "panel": "FIX_TILE_PANEL",
    "0": "FIX_TILE_DIGIT0",
    "colon": "FIX_TILE_COLON",
    "slash": "FIX_TILE_SLASH",
    "play": "FIX_TILE_PLAY",
    "pause": "FIX_TILE_PAUSE",
    "forward": "FIX_TILE_FORWARD",
    "rewind": "FIX_TILE_REWIND",
    "bar_empty": "FIX_TILE_BAR_EMPTY",
    "bar_filled": "FIX_TILE_BAR_FILLED",
    "panel_top": "FIX_TILE_PANEL_TOP",
    "bar_cap_left": "FIX_TILE_BAR_CAP_LEFT",
    "bar_cap_right": "FIX_TILE_BAR_CAP_RIGHT",
    "bar_knob": "FIX_TILE_BAR_KNOB",
    "A": "FIX_TILE_A",
    "percent": "FIX_TILE_PERCENT",
    "dot": "FIX_TILE_DOT",
    "dash": "FIX_TILE_DASH",
}

_HEADER_TEMPLATE: Final = """#ifndef MOVIE_DATA_H
#define MOVIE_DATA_H

#include "fmv.h"

#define MOVIE_BAKER_VERSION_MAJOR {baker_major}
#define MOVIE_BAKER_VERSION_MINOR {baker_minor}
#define MOVIE_BAKER_VERSION_STRING "{baker_major}.{baker_minor}"

#if MOVIE_BAKER_VERSION_MAJOR != FMV_VERSION_MAJOR \\
    || MOVIE_BAKER_VERSION_MINOR != FMV_VERSION_MINOR
#pragma message("this movie was baked by neogeomedia " MOVIE_BAKER_VERSION_STRING)
#pragma message("the fmv library beside it is " FMV_VERSION_STRING)
#error "baked movie and fmv library are different versions; re-bake, or replace fmv/"
#endif

#define MOVIE_FRAME_COUNT {frames}
#define MOVIE_TILE_COUNT {tiles}
#define MOVIE_FIRST_FREE_TILE {tiles}
#define MOVIE_FREE_TILES {free_tiles}
#define MOVIE_CROM_BYTES {crom_size}
#define MOVIE_PALETTE_COUNT {palettes}
#define MOVIE_PALETTE_BASE {base_bank}
#define MOVIE_EPOCH_COUNT {epochs}
#define MOVIE_EPOCH_PALETTES {epoch_palettes}
#define MOVIE_EPOCH_SLICE {epoch_slice}u
#define MOVIE_IMAGE_WIDTH {image_width}
#define MOVIE_IMAGE_HEIGHT {image_height}
#define MOVIE_TIER_NAME "{tier_name}"
#define MOVIE_CHROMA_PERCENT {chroma_percent}
#define MOVIE_CROM_PERCENT {crom_percent}
#define MOVIE_AUDIO_HZ {audio_hz}
#define MOVIE_FRAME_HOLD {frame_hold}
#define MOVIE_KEYFRAME_COUNT {keyframes}
#define MOVIE_GRID_COLS {cols}
#define MOVIE_GRID_ROWS {rows}
#define MOVIE_MAX_UPDATES {max_updates}
#define MOVIE_CYCLES_PER_UPDATE {cycles_per_update}
#define MOVIE_TICK_CYCLES {tick_cycles}
#define MOVIE_VBLANK_CYCLES {vblank_cycles}
#define MOVIE_STREAM_BANKS {stream_banks}
#define MOVIE_STREAM_BYTES {stream_bytes}u
#define MOVIE_FPS_NUM {fps_num}u
#define MOVIE_FPS_DEN {fps_den}u
#define MOVIE_AUDIO_PAGE_NUM {audio_page_num}u
#define MOVIE_AUDIO_PAGE_DEN {audio_page_den}u
#define MOVIE_SUBTITLE_COUNT {subtitle_count}
#define MOVIE_SUBTITLE_COLUMNS {subtitle_columns}
#define MOVIE_SUBTITLE_LINES {subtitle_lines}
#define MOVIE_SEEK_FRAMES {seek_frames}u

#define FIX_PALETTE {fix_palette}
{fix_defines}

extern const unsigned char movie_index[];
extern const unsigned char movie_keyframes[];
extern const unsigned char movie_palettes[];
extern const unsigned char movie_epochs[];
extern const unsigned char movie_subtitles[];
extern const unsigned char movie_fix_palette[];

extern const fmv_movie {movie_symbol};

#endif
"""

_MOVIE_TEMPLATE: Final = """#include "fmv.h"
#include "movie_data.h"

extern const unsigned char {stream_base_symbol}[];

const fmv_movie {movie_symbol} = {{
    .index = movie_index,
    .keyframes = movie_keyframes,
    .palettes = movie_palettes,
    .epochs = movie_epochs,
    .subtitles = movie_subtitles,
    .stream_base = (uint32_t){stream_base_symbol},
    .frames = {frames}u,
    .keyframe_count = {keyframes}u,
    .fps_num = {fps_num}u,
    .fps_den = {fps_den}u,
    .audio_page_num = {audio_page_num}u,
    .audio_page_den = {audio_page_den}u,
    .epoch_count = {epochs}u,
    .epoch_palettes = {epoch_palettes}u,
    .epoch_slice = {epoch_slice}u,
    .palette_base = {base_bank}u,
    .first_sprite = {first_sprite}u,
    .grid_cols = {cols}u,
    .grid_rows = {rows}u,
    .max_updates = {max_updates}u,
    .subtitle_count = {subtitle_count}u,
    .subtitle_columns = {subtitle_columns}u,
    .subtitle_lines = {subtitle_lines}u,
}};
"""

_ASM_ENTRY: Final = """    .globl {symbol}
    .balign 2
{symbol}:
    .incbin "{path}"
"""

_STREAM_BANK_ENTRY: Final = """    .section .rodata
    .globl {symbol}
    .balign 2
{symbol}:
    .incbin "{path}", {skip}, {count}
"""


@dataclass(frozen=True, slots=True)
class SourceSettings:
    tier_name: str
    chroma_weight: float
    frame_hold: int
    audio_pages: Fraction = Fraction(0)
    audio_hz: float = 0.0
    seek_frames: int = SEEK_FRAMES


def baker_version() -> tuple[int, int]:
    major, minor = version("neogeomedia").split(".")[:2]
    return int(major), int(minor)


def fix_defines() -> str:
    return "\n".join(
        f"#define {macro} {fixtiles.GLYPHS[glyph]}" for glyph, macro in _FIX_GLYPH_MACROS.items()
    )


def _generated_dir(build_dir: Path) -> Path:
    generated = build_dir / GENERATED_DIR
    generated.mkdir(parents=True, exist_ok=True)
    return generated


def write_stream_banks(build_dir: Path, stream_path: Path, banks: int) -> list[Path]:
    generated = _generated_dir(build_dir)
    stubs = [generated / f"{STREAM_BANK_STEM}{bank}.S" for bank in range(banks)]
    for bank, stub in enumerate(stubs):
        stub.write_text(
            _STREAM_BANK_ENTRY.format(
                symbol=f"{STREAM_BANK_SYMBOL}{bank}",
                path=stream_path.name,
                skip=bank * stream_mod.PROM_BANK_BYTES,
                count=stream_mod.PROM_BANK_BYTES,
            )
        )
    return stubs


def _write_asm(generated: Path, artifacts: dict[str, Path]) -> Path:
    asm = generated / "movie_data.S"
    entries = (
        _ASM_ENTRY.format(symbol=symbol, path=artifacts[key].name) for symbol, key in _ASM_BLOBS
    )
    asm.write_text("    .section .rodata\n" + "".join(entries))
    return asm


def _movie_fields(result: encode.EncodeResult) -> dict[str, object]:
    stats = result.stats
    crom_size = crom.rom_size_for(stats.tile_count)
    return {
        "frames": stats.frames,
        "tiles": stats.tile_count,
        "palettes": len(result.palette_set),
        "epochs": len(result.palette_sets),
        "epoch_palettes": len(result.palette_sets[0]),
        "crom_percent": round(PERCENT * stats.crom_payload_bytes / CROM_BANK_BYTES),
        "base_bank": result.palette_set.base_bank,
        "keyframes": stats.keyframe_count,
        "max_updates": stats.max_updates,
        "stream_banks": result.stream.bank_count(),
        "stream_bytes": stats.stream_bytes,
        "crom_size": crom_size,
        "free_tiles": (crom_size - stats.tile_count * crom.TILE_BYTES_PER_ROM)
        // crom.TILE_BYTES_PER_ROM,
        "tick_cycles": stats.max_updates * CYCLES_PER_UPDATE,
    }


def _layout_fields() -> dict[str, object]:
    return {
        "epoch_slice": epochs.PALETTE_WORDS_PER_FRAME,
        "image_width": encode.FRAME_WIDTH,
        "image_height": encode.FRAME_HEIGHT,
        "cols": encode.GRID_COLS,
        "rows": encode.GRID_ROWS,
        "fps_num": frames.VBLANK_FPS.numerator,
        "fps_den": frames.VBLANK_FPS.denominator,
        "fix_palette": FIX_PALETTE_BANK,
        "fix_defines": fix_defines(),
        "subtitle_columns": subtitles.COLUMNS,
        "subtitle_lines": subtitles.MAX_LINES,
        "movie_symbol": MOVIE_SYMBOL,
        "first_sprite": stream_mod.FIRST_SPRITE,
        "stream_base_symbol": STREAM_BASE_SYMBOL,
        "cycles_per_update": CYCLES_PER_UPDATE,
        "vblank_cycles": VBLANK_CYCLES,
    }


def _subtitle_count(artifacts: dict[str, Path]) -> int:
    return artifacts["subtitles"].stat().st_size // subtitles.RECORD_BYTES


def _settings_fields(settings: SourceSettings, artifacts: dict[str, Path]) -> dict[str, object]:
    major, minor = baker_version()
    return {
        "tier_name": settings.tier_name,
        "chroma_percent": round(settings.chroma_weight * PERCENT),
        "audio_hz": round(settings.audio_hz),
        "frame_hold": settings.frame_hold,
        "seek_frames": settings.seek_frames,
        "audio_page_num": settings.audio_pages.numerator,
        "audio_page_den": settings.audio_pages.denominator or 1,
        "subtitle_count": _subtitle_count(artifacts),
        "baker_major": major,
        "baker_minor": minor,
    }


def write_sources(
    build_dir: Path,
    artifacts: dict[str, Path],
    result: encode.EncodeResult,
    settings: SourceSettings,
) -> tuple[Path, Path]:
    generated = _generated_dir(build_dir)
    asm = _write_asm(generated, artifacts)
    fields = {
        **_movie_fields(result),
        **_layout_fields(),
        **_settings_fields(settings, artifacts),
    }
    header = generated / "movie_data.h"
    header.write_text(_HEADER_TEMPLATE.format(**fields))
    movie = generated / "movie_data_value.c"
    movie.write_text(_MOVIE_TEMPLATE.format(**fields))
    return asm, header
