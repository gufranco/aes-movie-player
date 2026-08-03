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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

CROM_BYTES: Final = 128 << 20
CROM_TILES: Final = 1 << 20
TILE_BYTES: Final = 128
STREAM_BYTES: Final = 8 << 20
ADPCM_B_BYTES: Final = 16 << 20
ADPCM_B_BYTES_PER_SAMPLE: Final = 0.5
DEFAULT_AUDIO_HZ: Final = 22050.0
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


LADDER: Final = (
    Tier("archival", 1.0, 1, 0.0005, 0.0, 1.678, "every frame, full colour precision"),
    Tier("high", 0.5, 1, 0.0005, 0.0, 1.515, "every frame, slightly cheaper colour"),
    Tier("standard", 0.35, 1, 0.001, 0.0, 1.000, "every frame, cheaper colour"),
    Tier("extended", 0.35, 3, 0.002, 0.0, 0.686, "20 fps, cheaper colour"),
    Tier("long", 0.25, 4, 0.004, 1.0, 0.466, "15 fps, mild denoise"),
    Tier("maximum", 0.15, 5, 0.008, 2.0, 0.335, "12 fps, visible softening"),
    Tier("extreme", 0.10, 6, 0.015, 3.0, 0.238, "10 fps, heavy softening"),
)

REFERENCE_TIER: Final = "standard"


def tier_by_name(name: str) -> Tier:
    """Look a tier up by name, listing the ladder when it is not one."""
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


def audio_hz_for(minutes: float) -> float:
    """Highest sample rate whose soundtrack still fits the voice ROM."""
    if minutes <= 0.0:
        return DEFAULT_AUDIO_HZ
    seconds = minutes * SECONDS_PER_MINUTE
    affordable = ADPCM_B_BYTES / (seconds * ADPCM_B_BYTES_PER_SAMPLE)
    return min(DEFAULT_AUDIO_HZ, affordable)


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
        """Runtime that would have to come out to reach this tier."""
        return max(0.0, -self.spare_minutes)


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


def select(minutes: float, reference_rate: float) -> Fit | None:
    """The best tier that fits, or None when even the cheapest overruns."""
    for fit in survey(minutes, reference_rate):
        if fit.fits:
            return fit
    return None
