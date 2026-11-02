from __future__ import annotations

from dataclasses import dataclass

from neogeomedia import palettes


@dataclass(frozen=True, slots=True)
class EncodeOptions:
    palette_count: int = 240
    base_bank: int = 16
    keyframe_interval: int = 90
    tolerance: float = 0.0005
    scene_cut_ratio: float = 0.90
    candidates: int = 12
    sample_stride: int = 8
    seed: int = 0
    collect_rendered: bool = True
    allow_flip: bool = False
    dictionary_capacity: int = 1 << 20
    frame_hold: int = 1
    motion_masking: float = 0.0
    chroma_weight: float = palettes.DEFAULT_CHROMA_WEIGHT
    scene_cut_floor: float = 0.01
    tile_budget: int = 0
    rate_control_gain: float = 4.0
    max_tolerance_scale: float = 4096.0
    stop_when_over_budget: bool = False
    dither: float = palettes.MAX_DITHER
