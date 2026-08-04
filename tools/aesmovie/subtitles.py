"""Turn a subtitle sidecar into a table the player can read in vblank.

The player has no string handling and no time to do any: it gets one binary
search per frame and a row of glyph indices to copy. Everything that can be
decided ahead of time is decided here.

Records are fixed width so the search is an index rather than a walk, and
the text is already laid out, centred, and translated into fix-layer tile
numbers. The 68000 copies bytes into VRAM and does nothing else.

Cues are trimmed so that no two overlap, because the fix layer shows one
thing at a time and a player that had to merge them would need the string
handling this format exists to avoid.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from aesmovie import fixtiles

COLUMNS: Final = 40
MAX_LINES: Final = 2
RECORD_BYTES: Final = 8 + COLUMNS * MAX_LINES

_TIMING = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)
_MARKUP = re.compile(r"<[^>]+>|\{[^}]*\}")

_PUNCTUATION: Final = {
    " ": "blank",
    ".": "dot",
    "-": "dash",
    "%": "percent",
    ":": "colon",
    "/": "slash",
    ",": "comma",
    "'": "apostrophe",
    "?": "question",
    "!": "bang",
}


@dataclass(frozen=True, slots=True)
class Cue:
    """One subtitle, in seconds, with its text already split into lines."""

    start: float
    end: float
    lines: tuple[str, ...]


def sidecar_for(source: Path) -> Path | None:
    """The `.srt` sitting beside the source under the same name, if there is one."""
    candidate = Path(source).with_suffix(".srt")
    return candidate if candidate.is_file() else None


def _seconds(hours: str, minutes: str, secs: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis.ljust(3, "0")) / 1000.0


def parse(text: str) -> list[Cue]:
    """Read cues out of SubRip text, dropping anything with no words in it."""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        timing = _TIMING.search(block)
        if timing is None:
            continue
        start = _seconds(*timing.group(1, 2, 3, 4))
        end = _seconds(*timing.group(5, 6, 7, 8))
        body = block[timing.end() :]
        lines = tuple(
            stripped for raw in body.splitlines() if (stripped := _MARKUP.sub("", raw).strip())
        )
        if lines:
            cues.append(Cue(start=start, end=end, lines=lines))
    return cues


def layout(text: str) -> tuple[str, ...]:
    """Wrap to the raster without splitting words, keeping the lines that fit.

    A single word too long for a row is cut instead of dropped: losing the
    line entirely is worse than losing its tail.
    """
    wrapped = textwrap.wrap(text, width=COLUMNS, break_long_words=True) or [""]
    return tuple(line[:COLUMNS] for line in wrapped[:MAX_LINES])


def _glyph(character: str) -> int:
    if character in _PUNCTUATION:
        return fixtiles.GLYPHS.get(_PUNCTUATION[character], fixtiles.GLYPHS["blank"])
    upper = character.upper()
    return fixtiles.GLYPHS.get(upper, fixtiles.GLYPHS["blank"])


def _row(line: str) -> bytes:
    blank = fixtiles.GLYPHS["blank"]
    cells = [blank] * COLUMNS
    start = max(0, (COLUMNS - len(line)) // 2)
    for offset, character in enumerate(line[:COLUMNS]):
        cells[start + offset] = _glyph(character)
    return bytes(cells)


def frame_span(cue: Cue, *, fps: float) -> tuple[int, int]:
    """The half-open frame range a cue is on screen for."""
    return round(cue.start * fps), round(cue.end * fps)


def _trimmed(cues: list[Cue]) -> list[Cue]:
    """Shorten any cue that runs into the next one."""
    ordered = sorted(cues, key=lambda cue: (cue.start, cue.end))
    kept: list[Cue] = []
    for index, cue in enumerate(ordered):
        end = cue.end
        if index + 1 < len(ordered):
            end = min(end, ordered[index + 1].start)
        if end > cue.start:
            kept.append(Cue(start=cue.start, end=end, lines=cue.lines))
    return kept


def encode(cues: list[Cue], *, fps: float) -> bytes:
    """Pack cues into fixed width records of frames plus laid-out glyph rows."""
    blob = bytearray()
    blank_row = bytes([fixtiles.GLYPHS["blank"]] * COLUMNS)
    for cue in _trimmed(cues):
        start, end = frame_span(cue, fps=fps)
        blob += start.to_bytes(4, "big") + end.to_bytes(4, "big")
        rows = layout(" ".join(cue.lines))
        for index in range(MAX_LINES):
            blob += _row(rows[index]) if index < len(rows) else blank_row
    return bytes(blob)
