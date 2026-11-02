from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from neogeomedia import adpcmb

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
FLAT_SPAN: Final = 1e-12


@dataclass(frozen=True, slots=True)
class Tier:
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
    name = ALIASES.get(name, name)
    for tier in LADDER:
        if tier.name == name:
            return tier
    known = ", ".join(tier.name for tier in LADDER)
    msg = f"unknown quality tier {name!r}; choose one of {known}"
    raise ValueError(msg)


def effective_fps(tier: Tier, vblank_fps: float) -> float:
    return vblank_fps / tier.frame_hold


def tile_rate_for(
    tier: Tier, reference_rate: float, anchors: dict[float, float] | None = None
) -> float:
    relative = tier.relative_cost
    if anchors:
        relative = rescale(relative, anchors=anchors)
    return reference_rate * relative


def max_minutes(
    tier: Tier, reference_rate: float, anchors: dict[float, float] | None = None
) -> float:
    rate = tile_rate_for(tier, reference_rate, anchors)
    if rate <= 0.0:
        return float("inf")
    return CROM_TILES / rate


def audio_grade(rate_hz: float) -> int:
    steps = len(LADDER)
    if rate_hz >= MAX_AUDIO_HZ:
        return 1
    span = MAX_AUDIO_HZ / MIN_AUDIO_HZ
    ratio = MAX_AUDIO_HZ / max(rate_hz, MIN_AUDIO_HZ)
    grade = 1 + round((steps - 1) * math.log(ratio) / math.log(span))
    return max(1, min(steps, grade))


def audio_hz_for(minutes: float) -> float:
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
    tier: Tier
    minutes: float
    capacity_minutes: float

    @property
    def fits(self) -> bool:
        return self.minutes <= self.capacity_minutes * SAFETY_MARGIN

    @property
    def overshoot(self) -> float:
        if self.capacity_minutes <= 0.0:
            return float("inf")
        return self.minutes / self.capacity_minutes

    @property
    def spare_minutes(self) -> float:
        return self.capacity_minutes * SAFETY_MARGIN - self.minutes

    @property
    def trim_minutes(self) -> float:
        shortfall = -self.spare_minutes
        if shortfall <= 0.0:
            return 0.0
        return math.ceil(shortfall * SECONDS_PER_MINUTE) / SECONDS_PER_MINUTE


def clock(minutes: float) -> str:
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


def _estimate_caveat() -> list[str]:
    return [
        "",
        "This choice is an estimate. Measured against real bakes the ladder runs",
        "about 50% conservative on animation and about 13% optimistic on grainy",
        "live action, because how much a colour reduction saves depends on the",
        "content. A bake that overruns now fails rather than shipping a cartridge",
        "that stops tracking the source. To settle it by measurement instead, use",
        "the cartridge tool with --quality search.",
    ]


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


def _source_lines(
    source: str, minutes: float, size: tuple[int, int], source_fps: float, has_audio: bool
) -> list[str]:
    audio = "audio present" if has_audio else "no audio"
    width, height = size
    return [
        "Source",
        f"  {source}",
        f"  {clock(minutes)} runtime, {width}x{height}, {source_fps:.2f} fps, {audio}",
    ]


def _shortfall_lines(cheapest: Fit) -> list[str]:
    return [
        "",
        "This source does not fit the cartridge at any quality tier.",
        f"  The cheapest tier, '{cheapest.tier.name}', still overruns by"
        f" {clock(cheapest.trim_minutes)}.",
        f"  Cut the source to {clock(cheapest.capacity_minutes * SAFETY_MARGIN)}"
        " or shorter and bake again.",
    ]


def _selected_lines(chosen: Fit) -> list[str]:
    tier = chosen.tier
    return [
        "",
        f"Selected: {tier.name}",
        f"  {tier.summary}",
        f"  chroma weight {tier.chroma_weight}, frame hold {tier.frame_hold},"
        f" tolerance {tier.tolerance}, denoise {tier.denoise}",
        f"  holds {clock(chosen.capacity_minutes)}, uses {clock(chosen.minutes)},"
        f" {clock(chosen.spare_minutes)} spare",
    ]


def _upgrade_lines(fits: list[Fit], chosen: Fit) -> list[str]:
    better = [fit for fit in fits if fit.tier.relative_cost > chosen.tier.relative_cost]
    if not better:
        return []
    nearest = better[-1]
    return [
        "",
        f"To reach '{nearest.tier.name}' instead ({nearest.tier.summary}):",
        f"  Trim {clock(nearest.trim_minutes)}, bringing the source to"
        f" {clock(nearest.capacity_minutes * SAFETY_MARGIN)} or shorter.",
    ]


def _calibration_lines(reference_rate: float) -> list[str]:
    return [
        "",
        "Calibration",
        f"  measured {reference_rate:,.0f} tiles per minute at '{REFERENCE_TIER}'",
        "",
        "Quality ladder for this source",
    ]


def _verdict_lines(
    fits: list[Fit], chosen: Fit | None, reference_rate: float, has_audio: bool
) -> list[str]:
    if chosen is None:
        return _shortfall_lines(fits[-1])
    return [
        *_selected_lines(chosen),
        *_upgrade_lines(fits, chosen),
        *_budget_lines(chosen, reference_rate, has_audio),
        *_estimate_caveat(),
    ]


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
    scope = {"source_fps": float(source_fps), "vblank_fps": float(vblank_fps)}
    fits = survey(minutes, reference_rate, anchors, **scope)
    chosen = select(minutes, reference_rate, anchors, **scope)
    header = _source_lines(source, minutes, (width, height), source_fps, has_audio)
    lines = [
        *header,
        *_calibration_lines(reference_rate),
        *_ladder_table(fits, vblank_fps),
        *_verdict_lines(fits, chosen, reference_rate, has_audio),
    ]
    return "\n".join(lines)


def reachable(tier: Tier, *, source_fps: float, vblank_fps: float) -> bool:
    if tier.frame_hold <= 1:
        return True
    return vblank_fps / tier.frame_hold < source_fps


def survey(
    minutes: float,
    reference_rate: float,
    anchors: dict[float, float] | None = None,
    *,
    source_fps: float | None = None,
    vblank_fps: float | None = None,
) -> list[Fit]:
    ladder: tuple[Tier, ...] = LADDER
    if source_fps is not None and vblank_fps is not None:
        ladder = tuple(
            tier for tier in LADDER if reachable(tier, source_fps=source_fps, vblank_fps=vblank_fps)
        )
    return [Fit(tier, minutes, max_minutes(tier, reference_rate, anchors)) for tier in ladder]


def shortfall_message(
    minutes: float,
    reference_rate: float,
    anchors: dict[float, float] | None = None,
    *,
    source_fps: float | None = None,
    vblank_fps: float | None = None,
) -> str | None:
    scope = {"source_fps": source_fps, "vblank_fps": vblank_fps}
    if select(minutes, reference_rate, anchors, **scope) is not None:
        return None
    cheapest = survey(minutes, reference_rate, anchors, **scope)[-1]
    return (
        f"this source does not fit at any quality tier; trim "
        f"{clock(cheapest.trim_minutes)} and bake again"
    )


def select(
    minutes: float,
    reference_rate: float,
    anchors: dict[float, float] | None = None,
    *,
    source_fps: float | None = None,
    vblank_fps: float | None = None,
) -> Fit | None:
    for fit in survey(
        minutes, reference_rate, anchors, source_fps=source_fps, vblank_fps=vblank_fps
    ):
        if fit.fits:
            return fit
    return None


ANCHOR_TIERS: Final = ("q01", "q17", "q30", "q32")


def anchor_tiers(source_fps: float, vblank_fps: float) -> tuple[Tier, ...]:
    return tuple(
        tier
        for tier in (tier_by_name(name) for name in ANCHOR_TIERS)
        if reachable(tier, source_fps=source_fps, vblank_fps=vblank_fps)
    )


def rescale(relative_cost: float, *, anchors: dict[float, float]) -> float:
    known = sorted(anchors.items())
    if relative_cost <= known[0][0]:
        low, high = known[0], known[1]
    elif relative_cost >= known[-1][0]:
        low, high = known[-2], known[-1]
    else:
        index = next(i for i, (rung, _) in enumerate(known) if rung > relative_cost)
        low, high = known[index - 1], known[index]

    span = math.log(high[0]) - math.log(low[0])
    if abs(span) < FLAT_SPAN:
        return low[1]
    ratio = (math.log(relative_cost) - math.log(low[0])) / span
    return math.exp(math.log(low[1]) + ratio * (math.log(high[1]) - math.log(low[1])))
