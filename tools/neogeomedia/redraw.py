from __future__ import annotations

import numpy as np
import numpy.typing as npt

from neogeomedia import palettes
from neogeomedia.encodeoptions import EncodeOptions
from neogeomedia.screen import GRID_COLS, GRID_ROWS, Screen


def movement(
    current: npt.NDArray[np.uint16],
    previous: npt.NDArray[np.uint16],
    targets: npt.NDArray[np.bool_],
    chroma_weight: float,
) -> npt.NDArray[np.float32]:
    grid = palettes.oklab_grid(chroma_weight)
    moved: npt.NDArray[np.float32] = (
        ((grid[current[targets]] - grid[previous[targets]]) ** 2).sum(axis=3).mean(axis=(1, 2))
    )
    return moved


def masked_threshold(
    current: npt.NDArray[np.uint16],
    previous: npt.NDArray[np.uint16] | None,
    targets: npt.NDArray[np.bool_],
    options: EncodeOptions,
    tolerance: float,
) -> npt.NDArray[np.float32] | float:
    if options.motion_masking <= 0.0 or previous is None:
        return tolerance
    moved = movement(current, previous, targets, options.chroma_weight)
    return tolerance + options.motion_masking * moved


def is_scene_cut(
    current: npt.NDArray[np.uint16],
    previous: npt.NDArray[np.uint16] | None,
    changed: npt.NDArray[np.bool_],
    index: int,
    options: EncodeOptions,
) -> bool:
    if index == 0 or previous is None:
        return True
    if not changed.any():
        return False
    moved = movement(current, previous, changed, options.chroma_weight)
    jumped = float((moved > options.scene_cut_floor).sum()) / float(changed.size)
    return jumped >= options.scene_cut_ratio


def select_targets(
    current: npt.NDArray[np.uint16],
    previous: npt.NDArray[np.uint16] | None,
    changed: npt.NDArray[np.bool_],
    pending: npt.NDArray[np.bool_],
    *,
    screen: Screen,
    keyframe: bool,
    options: EncodeOptions,
    tolerance: float,
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    if keyframe:
        return (
            np.ones((GRID_ROWS, GRID_COLS), dtype=bool),
            np.zeros((GRID_ROWS, GRID_COLS), dtype=bool),
        )
    targets = changed | pending
    if tolerance <= 0.0 or not targets.any():
        return targets, np.zeros_like(targets)
    threshold = masked_threshold(current, previous, targets, options, tolerance)
    keep = np.zeros_like(targets)
    keep[targets] = screen.drift(current, targets) > threshold
    return keep, targets & ~keep
