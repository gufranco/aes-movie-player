"""Measure every rung of the quality ladder against one window.

The ladder claims to be a frontier: no rung costs as much as another
while looking no better. Nothing checked that until this existed, and
the claim is worth checking because the planner trusts the declared
costs to decide what fits a cartridge. Baking the same window at every
tier turns the claim into a measurement, and turns the declared costs
into an error bar against what the encoder actually spends.

Each bake gets the whole tile budget for a short window, so the rate
controller never engages and every rung reports its natural cost rather
than what a controller squeezed it into.
"""

from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aesmovie import frames, quality

DEFAULT_START = 180.0
DEFAULT_DURATION = 45.0


@dataclass(frozen=True, slots=True)
class Measurement:
    """What one rung cost on the window every rung saw."""

    name: str
    declared: float
    tiles: int
    error: float


def cost_inversions(rows: list[Measurement]) -> list[tuple[str, str]]:
    """Neighbours where the cheaper-looking rung costs more."""
    return [(a.name, b.name) for a, b in itertools.pairwise(rows) if b.tiles > a.tiles]


def error_inversions(rows: list[Measurement]) -> list[tuple[str, str]]:
    """Neighbours where giving up quality improved the picture."""
    return [(a.name, b.name) for a, b in itertools.pairwise(rows) if b.error < a.error]


def dominated(rows: list[Measurement]) -> list[tuple[str, str, int, float]]:
    """Rungs another rung beats on cost and on error at once.

    A rung that costs at least as much as another while looking no
    better has no reason to exist: anyone who would pick it is better
    served by the rung that beats it.
    """
    found = []
    for row in rows:
        for other in rows:
            if other.name == row.name:
                continue
            cheaper = other.tiles <= row.tiles
            cleaner = other.error <= row.error
            strictly = other.tiles < row.tiles or other.error < row.error
            if cheaper and cleaner and strictly:
                found.append(
                    (row.name, other.name, row.tiles - other.tiles, row.error - other.error)
                )
                break
    return found


def model_error(rows: list[Measurement], *, reference: str) -> dict[str, float]:
    """How far each rung's declared cost sits from what it actually cost.

    Positive means the rung costs more than the ladder claims, which is
    the unsafe direction: the planner promises runtime the cartridge
    cannot hold.
    """
    anchor = next((row for row in rows if row.name == reference), None)
    if anchor is None:
        raise KeyError(f"no measurement for the reference rung {reference!r}")
    return {row.name: (row.tiles / anchor.tiles) / row.declared - 1 for row in rows}


def verdict(rows: list[Measurement]) -> int:
    """Zero when the ladder is a frontier, non-zero when it is not."""
    if dominated(rows) or cost_inversions(rows) or error_inversions(rows):
        return 1
    return 0


def format_report(rows: list[Measurement], *, reference: str) -> str:
    errors = model_error(rows, reference=reference)
    anchor = next(row for row in rows if row.name == reference)
    lines = [
        f"{len(rows)} rungs measured, reference {reference} = {anchor.tiles} tiles",
        "",
        f"{'tier':6}{'declared':>10}{'measured':>10}{'model':>9}{'tiles':>9}{'error':>11}",
        "-" * 55,
    ]
    for row in rows:
        measured = row.tiles / anchor.tiles
        lines.append(
            f"{row.name:6}{row.declared:10.3f}{measured:10.3f}"
            f"{errors[row.name] * 100:+8.1f}%{row.tiles:9d}{row.error:11.6f}"
        )

    lines.append("")
    cost_bad = cost_inversions(rows)
    error_bad = error_inversions(rows)
    lines.append(f"cost rises as quality falls: {cost_bad or 'nowhere'}")
    lines.append(f"error falls as quality falls: {error_bad or 'nowhere'}")

    beaten = dominated(rows)
    if beaten:
        lines.append("")
        for name, by, tiles, error in beaten:
            lines.append(f"  {name} is beaten by {by}: {tiles:+d} tiles, {error:+.6f} error")
    else:
        lines.append("every rung is on the frontier")
    return "\n".join(lines)


def measure(
    source: Path, out: Path, *, start: float, duration: float, keep: bool
) -> list[Measurement]:
    out.mkdir(parents=True, exist_ok=True)
    source_fps = float(frames.probe(source).fps)
    vblank = float(frames.VBLANK_FPS)
    rows: list[Measurement] = []

    for tier in quality.LADDER:
        if not quality.reachable(tier, source_fps=source_fps, vblank_fps=vblank):
            print(f"skip {tier.name}, its hold drops no frame of this source", file=sys.stderr)
            continue
        report = out / f"{tier.name}.json"
        if not report.is_file():
            work = out / f"work-{tier.name}"
            command = [
                sys.executable,
                "-m",
                "aesmovie.bake",
                "--source",
                str(source),
                "--start",
                str(start),
                "--duration",
                str(duration),
                "--quality",
                tier.name,
                "--build-dir",
                str(work),
                "--report-json",
                str(report),
            ]
            print(f"baking {tier.name}", file=sys.stderr)
            done = subprocess.run(command, capture_output=True, text=True, check=False)
            if done.returncode != 0:
                print(
                    f"  {tier.name} failed: {done.stderr.strip().splitlines()[-1:]}",
                    file=sys.stderr,
                )
                continue
            if not keep:
                subprocess.run(["rm", "-rf", str(work)], check=False)
        data = json.loads(report.read_text())
        rows.append(
            Measurement(
                name=tier.name,
                declared=tier.relative_cost,
                tiles=int(data["tile_count"]),
                error=float(data["displayed_error"]),
            )
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sweep_ladder",
        description="Bake one window at every tier and check the ladder is a frontier.",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--start", type=float, default=DEFAULT_START)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    parser.add_argument("--out", type=Path, default=Path("build/sweep"))
    parser.add_argument("--keep-builds", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if not args.source.is_file():
        print(f"source not found: {args.source}", file=sys.stderr)
        return 2

    rows = measure(
        args.source, args.out, start=args.start, duration=args.duration, keep=args.keep_builds
    )
    if not rows:
        print("no tier produced a report", file=sys.stderr)
        return 2

    print(format_report(rows, reference=quality.REFERENCE_TIER))
    return verdict(rows)


if __name__ == "__main__":
    raise SystemExit(main())
