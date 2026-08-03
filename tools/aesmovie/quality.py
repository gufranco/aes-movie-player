"""Quality tiers, and choosing one that fits the cartridge.

A cartridge holds a fixed number of tiles, so the longest movie it can
play is decided by how many tiles each minute costs. That cost is a
property of the content rather than of the running time: dense animation
can cost several times what a dialogue scene costs. A ladder indexed by
duration alone would therefore over-compress easy sources and
under-compress hard ones, so the rate is measured on the source itself
and the ladder only says how to spend what was measured.

Three ceilings bound a bake. Character ROM holds the tile dictionary and
binds first at every tier measured. Program ROM carries the command
stream and keeps around half its space spare throughout. The ADPCM-B
voice ROM holds the soundtrack and only constrains anything past about
25 minutes, where the sample rate has to come down to fit.

The relative costs below were measured on dense animation. They set the
shape of the ladder, never its absolute position, which calibration
supplies per source.

The rungs follow the measured Pareto frontier, which turned out to hold
a surprise: frame rate is a far worse thing to spend than colour. At a
fixed cost, keeping every frame and thinning the palette beat dropping
to a third of the frame rate by nearly half the error, and did it for
fewer tiles. Every rung down to 0.645 therefore keeps all 59.2 frames a
second, and holding frames only begins once colour has been spent all
the way down. An earlier ladder started dropping frames at 0.686, above
the point where the data says not to, which is why its middle rungs felt
like a cliff rather than a step.

Steps are around 9%. Finer would be false precision: the costs come from
one clip, so a 5% difference between neighbours sits inside the noise of
the measurement that produced them.

There is no lossless rung and there cannot be one. A tile draws from a
single bank of 15 colours, and 83% of tiles in real footage hold more
distinct colours than that once the picture is reduced to the hardware's
15-bit palette, so the quantisation step always discards something. The
top rung instead guarantees that nothing the encoder controls is given
up: every frame is shown, no drift is tolerated, colour is charged at
the same rate as luminance, nothing is denoised, and every palette is
searched rather than a shortlist.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from aesmovie import adpcmb

CROM_BYTES: Final = 128 << 20
CROM_TILES: Final = 1 << 20
TILE_BYTES: Final = 128
STREAM_BYTES: Final = 8 << 20
ADPCM_B_BYTES: Final = 16 << 20
ADPCM_B_BYTES_PER_SAMPLE: Final = 0.5
ADPCM_B_PAGE_BYTES: Final = 256
ADPCM_B_MAX_PAGES: Final = ADPCM_B_BYTES // ADPCM_B_PAGE_BYTES

MAX_AUDIO_HZ: Final = 55555.0
DEFAULT_AUDIO_HZ: Final = MAX_AUDIO_HZ
MIN_AUDIO_HZ: Final = 8000.0
SECONDS_PER_MINUTE: Final = 60.0
SAFETY_MARGIN: Final = 0.92


@dataclass(frozen=True, slots=True)
class Tier:
    """One rung of the ladder, and what it costs relative to `standard`."""

    name: str
    chroma_weight: float
    frame_hold: int
    tolerance: float
    denoise: float
    relative_cost: float
    summary: str
    candidates: int = 12


LADDER: Final = (
    Tier("q01", 1.0, 1, 0.0005, 0.0, 2.283, "every frame, colour at 100%", candidates=0),
    Tier("q02", 0.89, 1, 0.0006, 0.0, 2.071, "every frame, colour at 89%"),
    Tier("q03", 0.79, 1, 0.0007, 0.0, 1.88, "every frame, colour at 79%"),
    Tier("q04", 0.7, 1, 0.0008, 0.0, 1.705, "every frame, colour at 70%"),
    Tier("q05", 0.62, 1, 0.0009, 0.0, 1.547, "every frame, colour at 62%"),
    Tier("q06", 0.54, 1, 0.001, 0.0, 1.404, "every frame, colour at 54%"),
    Tier("q07", 0.48, 1, 0.0011, 0.0, 1.274, "every frame, colour at 48%"),
    Tier("q08", 0.42, 1, 0.0015, 0.0, 1.156, "every frame, colour at 42%"),
    Tier("q09", 0.37, 1, 0.0018, 0.0, 1.049, "every frame, colour at 37%"),
    Tier("q10", 0.31, 1, 0.0024, 0.0, 0.952, "every frame, colour at 31%"),
    Tier("q11", 0.24, 1, 0.0032, 0.0, 0.863, "every frame, colour at 24%"),
    Tier("q12", 0.2, 1, 0.0044, 0.0, 0.783, "every frame, colour at 20%"),
    Tier("q13", 0.16, 1, 0.0061, 0.0, 0.711, "every frame, colour at 16%"),
    Tier("q14", 0.12, 1, 0.008, 0.0, 0.645, "every frame, colour at 12%"),
    Tier("q15", 0.12, 3, 0.008, 0.0, 0.602, "20 fps, colour at 12%"),
    Tier("q16", 0.12, 4, 0.008, 0.0, 0.549, "15 fps, colour at 12%"),
    Tier("q17", 0.12, 5, 0.008, 0.0, 0.507, "12 fps, colour at 12%"),
    Tier("q18", 0.12, 6, 0.008, 0.0, 0.47, "10 fps, colour at 12%"),
)

REFERENCE_TIER: Final = "q09"


ALIASES: Final = {
    "reference": "q01",
    "archival": "q02",
    "high": "q06",
    "standard": "q09",
    "extended": "q12",
    "long": "q14",
    "maximum": "q16",
    "extreme": "q18",
}


def tier_by_name(name: str) -> Tier:
    """Look a tier up by name, listing the ladder when it is not one.

    The older seven names still resolve, to the rung nearest what they
    used to mean, so existing commands keep working.
    """
    name = ALIASES.get(name, name)
    for tier in LADDER:
        if tier.name == name:
            return tier
    known = ", ".join(tier.name for tier in LADDER)
    msg = f"unknown quality tier {name!r}; choose one of {known}"
    raise ValueError(msg)


def effective_fps(tier: Tier, vblank_fps: float) -> float:
    """Frames per second this tier actually shows."""
    return vblank_fps / tier.frame_hold


def tile_rate_for(tier: Tier, reference_rate: float) -> float:
    """Tiles per minute this tier costs, given the measured reference."""
    return reference_rate * tier.relative_cost


def max_minutes(tier: Tier, reference_rate: float) -> float:
    """Longest movie this tier fits, before any safety margin."""
    rate = tile_rate_for(tier, reference_rate)
    if rate <= 0.0:
        return float("inf")
    return CROM_TILES / rate


def audio_grade(rate_hz: float) -> int:
    """Where a sample rate sits on the same scale the picture uses.

    The rate itself is never rounded to a step. Audio lives in its own
    ROM and competes with nothing, so the planner always takes the
    highest rate that fits and stepping it could only give quality away.
    This is for reporting: it places whatever rate came out on the same
    eighteen-rung scale as the picture, so the two are comparable at a
    glance. Grade one is the chip's own maximum, and each grade down is
    the same ratio the picture ladder uses between neighbours.
    """
    steps = len(LADDER)
    if rate_hz >= MAX_AUDIO_HZ:
        return 1
    span = MAX_AUDIO_HZ / MIN_AUDIO_HZ
    ratio = MAX_AUDIO_HZ / max(rate_hz, MIN_AUDIO_HZ)
    grade = 1 + round((steps - 1) * math.log(ratio) / math.log(span))
    return max(1, min(steps, grade))


def audio_hz_for(minutes: float) -> float:
    """Highest sample rate whose soundtrack the player can still address.

    Audio lives in its own ROM, so a finer rate costs the picture
    nothing at all and the only thing holding it down is how long the
    movie runs. It therefore starts at what the chip itself can play and
    comes down only far enough to fit.

    The limit is the page counter rather than the ROM. ADPCM-B addresses
    in 256-byte pages through a 16-bit register, so the last page a
    player can name is 65,535 and filling the voice ROM to exactly its
    16 MiB puts the final page one beyond that. The counter wraps and
    playback restarts from the beginning of the sample.

    The rate is then floored onto the chip's own Delta-N grid, because
    the encoder quantises to that grid afterwards and rounding to the
    nearest step can come back a fraction above what was asked for. A
    fixed safety margin cannot cover that, since the excess grows with
    runtime; landing on the grid deliberately does.
    """
    if minutes <= 0.0:
        return DEFAULT_AUDIO_HZ
    seconds = minutes * SECONDS_PER_MINUTE
    budget = (ADPCM_B_MAX_PAGES - 1) * ADPCM_B_PAGE_BYTES
    affordable = budget / (seconds * ADPCM_B_BYTES_PER_SAMPLE)
    if affordable >= DEFAULT_AUDIO_HZ:
        return DEFAULT_AUDIO_HZ
    return adpcmb.rate_below(affordable)


@dataclass(frozen=True, slots=True)
class Fit:
    """How one tier stands against a specific runtime."""

    tier: Tier
    minutes: float
    capacity_minutes: float

    @property
    def fits(self) -> bool:
        return self.minutes <= self.capacity_minutes * SAFETY_MARGIN

    @property
    def overshoot(self) -> float:
        """How many times over capacity the source runs, 1.0 when exact."""
        if self.capacity_minutes <= 0.0:
            return float("inf")
        return self.minutes / self.capacity_minutes

    @property
    def spare_minutes(self) -> float:
        """Runtime still available at this tier, negative when over."""
        return self.capacity_minutes * SAFETY_MARGIN - self.minutes

    @property
    def trim_minutes(self) -> float:
        """Runtime that would have to come out to reach this tier.

        Rounded up to the next whole second. The exact shortfall lands on
        the boundary, where floating point can leave a source a
        fraction over after trimming by precisely the figure it was
        given, and advice that does not quite work is worse than none.
        Seconds are also the unit the figure is displayed in.
        """
        shortfall = -self.spare_minutes
        if shortfall <= 0.0:
            return 0.0
        return math.ceil(shortfall * SECONDS_PER_MINUTE) / SECONDS_PER_MINUTE


def clock(minutes: float) -> str:
    """Runtime as h:mm:ss, or m:ss when under an hour."""
    total = round(minutes * SECONDS_PER_MINUTE)
    hours, rest = divmod(total, 3600)
    mins, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def _mib(value: float) -> str:
    return f"{value / (1 << 20):.1f} MiB"


def _ladder_table(fits: list[Fit], vblank_fps: float) -> list[str]:
    lines = [
        f"  {'tier':<10}{'picture':<38}{'fps':>6}{'holds':>10}{'verdict':>22}",
        f"  {'-' * 84}",
    ]
    for fit in fits:
        fps = effective_fps(fit.tier, vblank_fps)
        if fit.fits:
            verdict = f"fits, {clock(fit.spare_minutes)} spare"
        else:
            verdict = f"over by {clock(fit.trim_minutes)}"
        lines.append(
            f"  {fit.tier.name:<10}{fit.tier.summary:<38}{fps:>6.1f}"
            f"{clock(fit.capacity_minutes):>10}{verdict:>22}"
        )
    return lines


def _budget_lines(fit: Fit, reference_rate: float, has_audio: bool) -> list[str]:
    tiles = tile_rate_for(fit.tier, reference_rate) * fit.minutes
    crom = tiles * TILE_BYTES
    audio_hz = audio_hz_for(fit.minutes)
    audio_bytes = fit.minutes * SECONDS_PER_MINUTE * audio_hz * ADPCM_B_BYTES_PER_SAMPLE
    lines = [
        "",
        "Cartridge budget at this tier",
        f"  C-ROM   {_mib(crom):>10} of {_mib(CROM_BYTES)}   {crom / CROM_BYTES:5.0%}"
        f"   {int(tiles):,} tiles",
    ]
    if has_audio:
        lines.append(
            f"  audio   {_mib(audio_bytes):>10} of {_mib(ADPCM_B_BYTES)}"
            f"   {audio_bytes / ADPCM_B_BYTES:5.0%}   at {audio_hz / 1000:.1f} kHz"
            f", grade {audio_grade(audio_hz)} of {len(LADDER)}"
        )
        if audio_hz < DEFAULT_AUDIO_HZ:
            lines.append(
                f"          the soundtrack drops below {DEFAULT_AUDIO_HZ / 1000:.1f} kHz"
                " to fit this runtime"
            )
    else:
        lines.append("  audio            none in the source")
    return lines


def format_plan(
    *,
    source: str,
    minutes: float,
    width: int,
    height: int,
    source_fps: float,
    has_audio: bool,
    reference_rate: float,
    vblank_fps: float,
) -> str:
    """A full account of what this source can become, and what it costs.

    Written to be acted on rather than skimmed. Every tier is listed with
    the runtime it holds for this particular source, so a runtime that
    just misses a better tier shows exactly how much has to come out, and
    trimming the source stays a decision the person makes with the
    numbers in front of them.
    """
    fits = survey(minutes, reference_rate)
    chosen = select(minutes, reference_rate)
    audio = "audio present" if has_audio else "no audio"
    lines = [
        "Source",
        f"  {source}",
        f"  {clock(minutes)} runtime, {width}x{height}, {source_fps:.2f} fps, {audio}",
        "",
        "Calibration",
        f"  measured {reference_rate:,.0f} tiles per minute at '{REFERENCE_TIER}'",
        "",
        "Quality ladder for this source",
        *_ladder_table(fits, vblank_fps),
    ]

    if chosen is None:
        cheapest = fits[-1]
        lines += [
            "",
            "This source does not fit the cartridge at any quality tier.",
            f"  The cheapest tier, '{cheapest.tier.name}', still overruns by"
            f" {clock(cheapest.trim_minutes)}.",
            f"  Cut the source to {clock(cheapest.capacity_minutes * SAFETY_MARGIN)}"
            " or shorter and bake again.",
        ]
        return "\n".join(lines)

    lines += [
        "",
        f"Selected: {chosen.tier.name}",
        f"  {chosen.tier.summary}",
        f"  chroma weight {chosen.tier.chroma_weight}, frame hold {chosen.tier.frame_hold},"
        f" tolerance {chosen.tier.tolerance}, denoise {chosen.tier.denoise}",
        f"  holds {clock(chosen.capacity_minutes)}, uses {clock(chosen.minutes)},"
        f" {clock(chosen.spare_minutes)} spare",
    ]

    better = [fit for fit in fits if fit.tier.relative_cost > chosen.tier.relative_cost]
    if better:
        nearest = better[-1]
        lines += [
            "",
            f"To reach '{nearest.tier.name}' instead ({nearest.tier.summary}):",
            f"  Trim {clock(nearest.trim_minutes)}, bringing the source to"
            f" {clock(nearest.capacity_minutes * SAFETY_MARGIN)} or shorter.",
        ]
    lines += _budget_lines(chosen, reference_rate, has_audio)
    return "\n".join(lines)


def survey(minutes: float, reference_rate: float) -> list[Fit]:
    """Every tier measured against one runtime, best quality first."""
    return [Fit(tier, minutes, max_minutes(tier, reference_rate)) for tier in LADDER]


def shortfall_message(minutes: float, reference_rate: float) -> str | None:
    """Why a source cannot be baked at all, or None when some tier fits.

    Kept apart from the command line so the decision, and the number the
    reader is asked to act on, can be checked without a source long
    enough to actually overrun a cartridge.
    """
    if select(minutes, reference_rate) is not None:
        return None
    cheapest = survey(minutes, reference_rate)[-1]
    return (
        f"this source does not fit at any quality tier; trim "
        f"{clock(cheapest.trim_minutes)} and bake again"
    )


def select(minutes: float, reference_rate: float) -> Fit | None:
    """The best tier that fits, or None when even the cheapest overruns."""
    for fit in survey(minutes, reference_rate):
        if fit.fits:
            return fit
    return None
