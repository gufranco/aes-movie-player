from __future__ import annotations

import math
from typing import Final

from neogeomedia import adpcmb, frames, palettes, quality

MAX_SOURCE_SECONDS: Final = 4 * 60 * 60
MIN_SECONDS: Final = 1 / float(frames.VBLANK_FPS)
MAX_FRAMES: Final = math.ceil(MAX_SOURCE_SECONDS * float(frames.VBLANK_FPS))
MIN_AUDIO_RATE_HZ: Final = 1850.0
MAX_AUDIO_RATE_HZ: Final = adpcmb.BASE_RATE_HZ
MAX_DENOISE: Final = 64.0
MAX_FRAME_HOLD: Final = math.floor(float(frames.VBLANK_FPS))
MAX_MOTION_BLUR: Final = 1024
MIN_TARGET_FPS: Final = 1.0
MAX_MOTION_MASKING: Final = 4096.0
MIN_CHROMA_WEIGHT: Final = 0.001
MAX_CHROMA_WEIGHT: Final = 16.0
MAX_FRACTION: Final = 1.0
MAX_TILES: Final = quality.CROM_TILES
MAX_PALETTES: Final = palettes.CRAM_BANKS
MAX_SEED: Final = 2**32 - 1
MAX_DITHER: Final = palettes.MAX_DITHER
DEFAULT_DITHER: Final = palettes.MAX_DITHER
SEEK_EVERY_SECONDS: Final = 10.0
