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
    Tier("q01", 1.0, 1, 0.000500, 0.0, 1.529, "every frame, colour at 100%", candidates=0),
    Tier("q02", 0.94, 1, 0.000558, 0.0, 1.497, "every frame, colour at 94%"),
    Tier("q03", 0.89, 1, 0.000623, 0.0, 1.459, "every frame, colour at 89%"),
    Tier("q04", 0.84, 1, 0.000695, 0.0, 1.415, "every frame, colour at 84%"),
    Tier("q05", 0.79, 1, 0.000775, 0.0, 1.376, "every frame, colour at 79%"),
    Tier("q06", 0.74, 1, 0.000865, 0.0, 1.336, "every frame, colour at 74%"),
    Tier("q07", 0.7, 1, 0.000965, 0.0, 1.300, "every frame, colour at 70%"),
    Tier("q08", 0.66, 1, 0.001077, 0.0, 1.268, "every frame, colour at 66%"),
    Tier("q09", 0.62, 1, 0.001201, 0.0, 1.237, "every frame, colour at 62%"),
    Tier("q10", 0.58, 1, 0.001341, 0.0, 1.207, "every frame, colour at 58%"),
    Tier("q11", 0.54, 1, 0.001496, 0.0, 1.178, "every frame, colour at 54%"),
    Tier("q12", 0.51, 1, 0.001669, 0.0, 1.149, "every frame, colour at 51%"),
    Tier("q13", 0.48, 1, 0.001862, 0.0, 1.120, "every frame, colour at 48%"),
    Tier("q14", 0.45, 1, 0.002078, 0.0, 1.090, "every frame, colour at 45%"),
    Tier("q15", 0.42, 1, 0.002319, 0.0, 1.060, "every frame, colour at 42%"),
    Tier("q16", 0.39, 1, 0.002587, 0.0, 1.030, "every frame, colour at 39%"),
    Tier("q17", 0.37, 1, 0.002887, 0.0, 1.000, "every frame, colour at 37%"),
    Tier("q18", 0.34, 1, 0.003222, 0.0, 0.969, "every frame, colour at 34%"),
    Tier("q19", 0.31, 1, 0.003595, 0.0, 0.938, "every frame, colour at 31%"),
    Tier("q20", 0.28, 1, 0.004011, 0.0, 0.907, "every frame, colour at 28%"),
    Tier("q21", 0.26, 1, 0.004475, 0.0, 0.876, "every frame, colour at 26%"),
    Tier("q22", 0.24, 1, 0.004994, 0.0, 0.845, "every frame, colour at 24%"),
    Tier("q23", 0.22, 1, 0.005572, 0.0, 0.813, "every frame, colour at 22%"),
    Tier("q24", 0.2, 1, 0.006218, 0.0, 0.780, "every frame, colour at 20%"),
    Tier("q25", 0.18, 1, 0.006938, 0.0, 0.747, "every frame, colour at 18%"),
    Tier("q26", 0.16, 1, 0.007741, 0.0, 0.713, "every frame, colour at 16%"),
    Tier("q27", 0.14, 1, 0.008638, 0.0, 0.680, "every frame, colour at 14%"),
    Tier("q28", 0.12, 1, 0.009638, 0.0, 0.646, "every frame, colour at 12%"),
    Tier("q29", 0.1, 1, 0.010754, 0.0, 0.613, "every frame, colour at 10%"),
    Tier("q30", 0.08, 1, 0.012000, 0.0, 0.581, "every frame, colour at 8%"),
    Tier("q31", 0.08, 2, 0.012000, 0.0, 0.525, "30 fps, colour at 8%"),
    Tier("q32", 0.08, 3, 0.012000, 0.0, 0.437, "20 fps, colour at 8%"),
    Tier("q33", 0.08, 4, 0.012000, 0.0, 0.357, "15 fps, colour at 8%"),
    Tier("q34", 0.08, 5, 0.012000, 0.0, 0.308, "12 fps, colour at 8%"),
    Tier("q35", 0.08, 6, 0.012000, 0.0, 0.264, "10 fps, colour at 8%"),
)
REFERENCE_TIER: Final = "q17"


ALIASES: Final = {
    "reference": "q01",
    "archival": "q03",
    "high": "q11",
    "standard": "q17",
    "extended": "q23",
    "long": "q28",
    "maximum": "q33",
    "extreme": "q35",
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


def tile_rate_for(
    tier: Tier, reference_rate: float, anchors: dict[float, float] | None = None
) -> float:
    """Tiles per minute this tier costs, given the measured reference.

    The ladder's cost is averaged over several sources, and the shape of
    that curve is a property of the content: measured across four sources
    the same setting varied by up to 2x at the extremes. When the source's
    own anchors are known, the averaged cost is bent onto them.
    """
    relative = tier.relative_cost
    if anchors:
        relative = rescale(relative, anchors=anchors)
    return reference_rate * relative


def max_minutes(
    tier: Tier, reference_rate: float, anchors: dict[float, float] | None = None
) -> float:
    """Longest movie this tier fits, before any safety margin."""
    rate = tile_rate_for(tier, reference_rate, anchors)
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
    anchors: dict[float, float] | None = None,
) -> str:
    """A full account of what this source can become, and what it costs.

    Written to be acted on rather than skimmed. Every tier is listed with
    the runtime it holds for this particular source, so a runtime that
    just misses a better tier shows exactly how much has to come out, and
    trimming the source stays a decision the person makes with the
    numbers in front of them.
    """
    fits = survey(minutes, reference_rate, anchors)
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


def survey(
    minutes: float, reference_rate: float, anchors: dict[float, float] | None = None
) -> list[Fit]:
    """Every tier measured against one runtime, best quality first."""
    return [Fit(tier, minutes, max_minutes(tier, reference_rate, anchors)) for tier in LADDER]


def shortfall_message(
    minutes: float, reference_rate: float, anchors: dict[float, float] | None = None
) -> str | None:
    """Why a source cannot be baked at all, or None when some tier fits.

    Kept apart from the command line so the decision, and the number the
    reader is asked to act on, can be checked without a source long
    enough to actually overrun a cartridge.
    """
    if select(minutes, reference_rate, anchors) is not None:
        return None
    cheapest = survey(minutes, reference_rate, anchors)[-1]
    return (
        f"this source does not fit at any quality tier; trim "
        f"{clock(cheapest.trim_minutes)} and bake again"
    )


def select(
    minutes: float, reference_rate: float, anchors: dict[float, float] | None = None
) -> Fit | None:
    """The best tier that fits, or None when even the cheapest overruns."""
    for fit in survey(minutes, reference_rate, anchors):
        if fit.fits:
            return fit
    return None


ANCHOR_CHROMA: Final = (1.0, 0.37, 0.08)
"""Where the source's own cost curve is measured.

One anchor is not enough. Measured across four sources, the cost of a
setting relative to the reference agreed by construction at the reference
and diverged by up to 2x at the extremes: at colour 8% the cheapest source
came in at 0.378 and the dearest at 0.756. A ladder averaged over sources
therefore mispredicts any single one, and it does so worst exactly where
the rungs are cheapest. Three anchors pin both ends and the middle.
"""


def rescale(relative_cost: float, *, anchors: dict[float, float]) -> float:
    """Bend the ladder's averaged cost onto the curve this source actually has.

    The anchors map a rung's averaged relative cost to what the source
    measured there. Rungs between two anchors are interpolated in log space,
    which keeps the ordering: a rung cheaper on the ladder stays cheaper
    after correction.
    """
    known = sorted(anchors.items())
    if relative_cost <= known[0][0]:
        low, high = known[0], known[1]
    elif relative_cost >= known[-1][0]:
        low, high = known[-2], known[-1]
    else:
        index = next(i for i, (rung, _) in enumerate(known) if rung > relative_cost)
        low, high = known[index - 1], known[index]

    span = math.log(high[0]) - math.log(low[0])
    if abs(span) < 1e-12:
        return low[1]
    ratio = (math.log(relative_cost) - math.log(low[0])) / span
    return math.exp(math.log(low[1]) + ratio * (math.log(high[1]) - math.log(low[1])))


def nearest_by_chroma(chroma_weight: float) -> Tier:
    """The rung whose colour weight is closest to a wanted one."""
    return min(LADDER, key=lambda tier: abs(tier.chroma_weight - chroma_weight))
