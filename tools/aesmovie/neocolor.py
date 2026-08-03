"""Neo Geo palette color model and perceptual distance.

The palette word layout and the digital-to-analog mapping are taken from
the geolith LSPC implementation, `src/geo_lspc.c`, `geo_lspc_palconv` and
`geo_lspc_palgen_raw`, because geolith is the decoder this project
verifies against. The word is

    |D0|R1|G1|B1|R5 R4 R3 R2|G5 G4 G3 G2|B5 B4 B3 B2|

Each channel carries five independent bits plus `D0`, a sixth bit shared
across all three channels. geolith reconstructs a six-bit level per
channel as `(c5 << 1) | D0`, inverts `D0`, and scales to eight bits with
the integer form of `value * 255 / 63 + 0.5`.

`D0` is fixed to zero by the baker. It buys half a level per channel,
roughly 1.6 percent, which is far below the error the fifteen-colors-per
-tile constraint already imposes, and fixing it keeps one color grid
across every pass.

Two digital-to-analog models exist. `geo_lspc_palgen_raw` treats the
level as a plain fraction of full scale. `geo_lspc_palgen_resnet` models
the actual resistor ladder on the board, five resistors per channel at
3900, 2200, 1000, 470, and 220 ohms, smooths the resulting curve, and
renormalizes. The resistor model is the default here because it is what
real hardware does, and because it is the emulator setting this project
captures against. It also reaches true black at level zero, where the
raw model bottoms out at 4.

The Oklab matrices are Bjorn Ottosson's reference coefficients, matching
`rgb_to_oklab` in the DoomNG `tools/doomng_build/bake/palette.py`,
vectorized over numpy arrays here.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt

C5_LEVELS: Final = 32
COLOR_INDEX_COUNT: Final = C5_LEVELS**3
PALETTE_COLORS: Final = 16
PALETTE_USABLE_COLORS: Final = PALETTE_COLORS - 1
TRANSPARENT_INDEX: Final = 0

_SRGB_LINEAR_THRESHOLD: Final = 0.04045

_OKLAB_M1: Final = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ],
    dtype=np.float64,
)

_OKLAB_M2: Final = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ],
    dtype=np.float64,
)


_LADDER_OHMS: Final = (3900.0, 2200.0, 1000.0, 470.0, 220.0)
_SMOOTHING_WEIGHT: Final = 1.6
_SMOOTHING_DIVISOR: Final = 4.2


def _raw_c5_to_srgb8(c5: npt.NDArray[np.integer]) -> npt.NDArray[np.uint8]:
    level6 = (c5.astype(np.int32) << 1) | 1
    return ((level6 * 259 + 33) >> 6).astype(np.uint8)


def _resistor_ladder_voltages() -> npt.NDArray[np.float64]:
    voltage = np.zeros(C5_LEVELS, dtype=np.float64)
    for level in range(C5_LEVELS):
        to_vcc = 0.0
        to_gnd = 0.0
        for bit, ohms in enumerate(_LADDER_OHMS):
            if level & (1 << bit):
                to_vcc = ohms if to_vcc == 0.0 else (to_vcc * ohms) / (to_vcc + ohms)
            else:
                to_gnd = ohms if to_gnd == 0.0 else (to_gnd * ohms) / (to_gnd + ohms)
        if to_vcc == 0.0:
            voltage[level] = 0.0
        elif to_gnd == 0.0:
            voltage[level] = 1.0
        else:
            voltage[level] = to_gnd / (to_vcc + to_gnd)
    return voltage


def _resnet_c5_to_srgb8() -> npt.NDArray[np.uint8]:
    raw = _resistor_ladder_voltages()
    smooth = raw.copy()
    smooth[1:-1] = (
        raw[:-2] * _SMOOTHING_WEIGHT + raw[1:-1] + raw[2:] * _SMOOTHING_WEIGHT
    ) / _SMOOTHING_DIVISOR
    normalized = (smooth - smooth[0]) / (smooth[-1] - smooth[0])
    levels: npt.NDArray[np.uint8] = (normalized * 255.0 + 0.5).astype(np.uint8)
    return levels


RAW_C5_TO_SRGB8: Final[npt.NDArray[np.uint8]] = _raw_c5_to_srgb8(np.arange(C5_LEVELS))
C5_TO_SRGB8: Final[npt.NDArray[np.uint8]] = _resnet_c5_to_srgb8()


def _srgb8_to_c5(value: npt.NDArray[np.integer]) -> npt.NDArray[np.uint8]:
    table = C5_TO_SRGB8.astype(np.int32)
    distance = np.abs(value.astype(np.int32)[..., None] - table)
    return np.argmin(distance, axis=-1).astype(np.uint8)


SRGB8_TO_C5: Final[npt.NDArray[np.uint8]] = _srgb8_to_c5(np.arange(256))


def pack_palette_word(r5: int, g5: int, b5: int, *, dark: bool = False) -> int:
    """Encode one CRAM word from 5-bit channels."""
    for name, value in (("r5", r5), ("g5", g5), ("b5", b5)):
        if not 0 <= value < C5_LEVELS:
            msg = f"{name} out of range: {value}"
            raise ValueError(msg)
    return (
        (0x8000 if dark else 0)
        | ((r5 & 1) << 14)
        | ((g5 & 1) << 13)
        | ((b5 & 1) << 12)
        | ((r5 >> 1) << 8)
        | ((g5 >> 1) << 4)
        | (b5 >> 1)
    )


def rgb_to_color_index(rgb: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint16]:
    """Map 8-bit sRGB triples to the 15-bit Neo Geo color grid index."""
    c5 = SRGB8_TO_C5[rgb].astype(np.uint16)
    packed = (c5[..., 0] << 10) | (c5[..., 1] << 5) | c5[..., 2]
    return packed.astype(np.uint16)


def color_index_to_c5(index: npt.NDArray[np.integer]) -> npt.NDArray[np.uint8]:
    """Split a color-grid index back into its three 5-bit channels."""
    idx = index.astype(np.int32)
    return np.stack(
        [(idx >> 10) & 0x1F, (idx >> 5) & 0x1F, idx & 0x1F],
        axis=-1,
    ).astype(np.uint8)


def color_index_to_rgb(index: npt.NDArray[np.integer]) -> npt.NDArray[np.uint8]:
    """Displayed sRGB for each color-grid index."""
    return C5_TO_SRGB8[color_index_to_c5(index)]


def color_index_to_palette_word(index: npt.NDArray[np.integer]) -> npt.NDArray[np.uint16]:
    """Encode CRAM words for a batch of color-grid indices."""
    c5 = color_index_to_c5(index).astype(np.uint16)
    r5, g5, b5 = c5[..., 0], c5[..., 1], c5[..., 2]
    return (
        ((r5 & 1) << 14)
        | ((g5 & 1) << 13)
        | ((b5 & 1) << 12)
        | ((r5 >> 1) << 8)
        | ((g5 >> 1) << 4)
        | (b5 >> 1)
    ).astype(np.uint16)


def srgb_to_oklab(rgb: npt.NDArray[np.integer]) -> npt.NDArray[np.float32]:
    """Convert 8-bit sRGB triples to Oklab."""
    channel = rgb.astype(np.float64) / 255.0
    linear = np.where(
        channel <= _SRGB_LINEAR_THRESHOLD,
        channel / 12.92,
        ((channel + 0.055) / 1.055) ** 2.4,
    )
    lms = linear @ _OKLAB_M1.T
    return (np.cbrt(lms) @ _OKLAB_M2.T).astype(np.float32)


def build_oklab_grid() -> npt.NDArray[np.float32]:
    """Oklab coordinates of every color on the 15-bit Neo Geo grid."""
    index = np.arange(COLOR_INDEX_COUNT)
    return srgb_to_oklab(color_index_to_rgb(index))
