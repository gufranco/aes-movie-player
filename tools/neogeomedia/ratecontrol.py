from __future__ import annotations

from typing import Final

from neogeomedia.encodeoptions import EncodeOptions


class RateController:
    _SMOOTHING: Final = 0.05
    _RAMP_LIMIT: Final = 1.25
    _DECAY: Final = 0.90
    _SLACK: Final = 0.95

    def __init__(self, options: EncodeOptions) -> None:
        self._budget = options.tile_budget
        self._base = options.tolerance
        self._max_scale = options.max_tolerance_scale
        self._scale = 1.0
        self._previous_tiles = 0
        self._rate = 0.0

    def tolerance(self, tiles_used: int, index: int, total_frames: int) -> float:
        if self._budget <= 0 or total_frames <= 0:
            return self._base
        added = tiles_used - self._previous_tiles
        self._previous_tiles = tiles_used
        self._rate += (added - self._rate) * self._SMOOTHING

        remaining_frames = total_frames - index
        remaining_budget = self._budget - tiles_used
        if remaining_frames <= 0:
            return self._base * self._scale
        affordable = max(0.0, remaining_budget) / remaining_frames

        if affordable <= 0.0:
            self._scale = self._max_scale
        elif self._rate > affordable:
            ramp = min(self._rate / affordable, self._RAMP_LIMIT)
            self._scale = min(self._max_scale, self._scale * ramp)
        elif self._rate < affordable * self._SLACK:
            self._scale = max(1.0, self._scale * self._DECAY)
        return self._base * self._scale
