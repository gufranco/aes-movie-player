"""Colour model tests.

`geolith_reference_rgb` is an independent transcription of geolith's
`geo_lspc_palconv` plus `geo_lspc_palgen_raw` from `src/geo_lspc.c`. It
decodes a CRAM word the way the target emulator does, so the assertions
below check the baker against the real decoder rather than against
another copy of the baker's own arithmetic.
"""

from __future__ import annotations

import numpy as np
import pytest

from aesmovie import neocolor


def geolith_reference_rgb(word: int) -> tuple[int, int, int]:
    r6 = ((word >> 6) & 0x3C) | ((word >> 13) & 0x02) | ((word >> 15) & 0x01)
    g6 = ((word >> 2) & 0x3C) | ((word >> 12) & 0x02) | ((word >> 15) & 0x01)
    b6 = ((word << 2) & 0x3C) | ((word >> 11) & 0x02) | ((word >> 15) & 0x01)
    return tuple(((level ^ 0x01) * 259 + 33) >> 6 for level in (r6, g6, b6))  # type: ignore[return-value]


def geolith_resnet_levels() -> list[int]:
    resistance = [3900.0, 2200.0, 1000.0, 470.0, 220.0]
    v_raw = []
    for value in range(32):
        r_to_vcc = 0.0
        r_to_gnd = 0.0
        for bit in range(5):
            r = resistance[bit]
            if value & (1 << bit):
                r_to_vcc = r if r_to_vcc == 0.0 else (r_to_vcc * r) / (r_to_vcc + r)
            else:
                r_to_gnd = r if r_to_gnd == 0.0 else (r_to_gnd * r) / (r_to_gnd + r)
        if r_to_vcc == 0.0:
            v_raw.append(0.0)
        elif r_to_gnd == 0.0:
            v_raw.append(1.0)
        else:
            v_raw.append(r_to_gnd / (r_to_vcc + r_to_gnd))

    v_smooth = list(v_raw)
    for i in range(1, 31):
        v_smooth[i] = (v_raw[i - 1] * 1.6 + v_raw[i] + v_raw[i + 1] * 1.6) / 4.2

    lo, hi = v_smooth[0], v_smooth[31]
    return [int((v_smooth[i] - lo) / (hi - lo) * 255.0 + 0.5) for i in range(32)]


def geolith_resnet_rgb(word: int) -> tuple[int, int, int]:
    levels = geolith_resnet_levels()
    channels = (
        ((word >> 6) & 0x3C) | ((word >> 13) & 0x02) | ((word >> 15) & 0x01),
        ((word >> 2) & 0x3C) | ((word >> 12) & 0x02) | ((word >> 15) & 0x01),
        ((word << 2) & 0x3C) | ((word >> 11) & 0x02) | ((word >> 15) & 0x01),
    )
    if any(level & 1 for level in channels):
        msg = "the resistor-network oracle only covers words with the dark bit clear"
        raise ValueError(msg)
    return tuple(levels[level >> 1] for level in channels)


class TestResistorNetworkLevels:
    def test_the_default_model_matches_the_emulator_resistor_network(self):
        assert [int(v) for v in neocolor.C5_TO_SRGB8] == geolith_resnet_levels()

    def test_the_resistor_network_reaches_true_black(self):
        assert int(neocolor.C5_TO_SRGB8[0]) == 0

    def test_the_resistor_network_reaches_full_white(self):
        assert int(neocolor.C5_TO_SRGB8[31]) == 255

    def test_the_raw_model_stays_available_for_comparison(self):
        assert int(neocolor.RAW_C5_TO_SRGB8[0]) == 4
        assert int(neocolor.RAW_C5_TO_SRGB8[31]) == 255

    def test_the_two_models_never_disagree_by_more_than_a_step(self):
        difference = np.abs(neocolor.C5_TO_SRGB8.astype(int) - neocolor.RAW_C5_TO_SRGB8.astype(int))

        assert difference.max() <= 12


class TestPaletteWord:
    def test_every_channel_level_decodes_to_the_documented_raw_display_value(self):
        levels = range(neocolor.C5_LEVELS)

        words = [neocolor.pack_palette_word(c5, 0, 0) for c5 in levels]

        decoded = [geolith_reference_rgb(w)[0] for w in words]
        assert decoded == [int(v) for v in neocolor.RAW_C5_TO_SRGB8]

    def test_channels_are_independent_in_the_encoded_word(self):
        word = neocolor.pack_palette_word(31, 0, 17)

        red, green, blue = geolith_reference_rgb(word)

        assert (red, green, blue) == (
            int(neocolor.RAW_C5_TO_SRGB8[31]),
            int(neocolor.RAW_C5_TO_SRGB8[0]),
            int(neocolor.RAW_C5_TO_SRGB8[17]),
        )

    def test_black_is_not_reachable_with_the_dark_bit_clear(self):
        word = neocolor.pack_palette_word(0, 0, 0)

        assert geolith_reference_rgb(word) == (4, 4, 4)

    def test_setting_the_dark_bit_reaches_true_black(self):
        word = neocolor.pack_palette_word(0, 0, 0, dark=True)

        assert geolith_reference_rgb(word) == (0, 0, 0)

    def test_full_intensity_reaches_saturation(self):
        word = neocolor.pack_palette_word(31, 31, 31)

        assert geolith_reference_rgb(word) == (255, 255, 255)

    def test_the_word_fits_sixteen_bits_for_every_grid_colour(self):
        words = [
            neocolor.pack_palette_word(r, g, b)
            for r in range(0, neocolor.C5_LEVELS, 7)
            for g in range(0, neocolor.C5_LEVELS, 7)
            for b in range(0, neocolor.C5_LEVELS, 7)
        ]

        assert all(0 <= w <= 0xFFFF for w in words)

    @pytest.mark.parametrize("channel", ["r5", "g5", "b5"])
    def test_out_of_range_channels_are_rejected(self, channel):
        args = {"r5": 0, "g5": 0, "b5": 0}
        args[channel] = neocolor.C5_LEVELS

        with pytest.raises(ValueError, match=channel):
            neocolor.pack_palette_word(**args)


class TestChannelQuantization:
    def test_display_levels_span_the_full_output_range(self):
        levels = neocolor.C5_TO_SRGB8

        assert (int(levels[0]), int(levels[-1])) == (0, 255)

    def test_display_levels_increase_strictly(self):
        levels = neocolor.C5_TO_SRGB8.astype(int)

        assert np.all(np.diff(levels) > 0)

    def test_quantizing_a_displayed_level_returns_its_own_index(self):
        recovered = neocolor.SRGB8_TO_C5[neocolor.C5_TO_SRGB8]

        assert np.array_equal(recovered, np.arange(neocolor.C5_LEVELS, dtype=np.uint8))

    def test_quantization_never_exceeds_half_the_widest_step(self):
        source = np.arange(256)

        error = np.abs(neocolor.C5_TO_SRGB8[neocolor.SRGB8_TO_C5[source]].astype(int) - source)

        widest_step = int(np.diff(neocolor.C5_TO_SRGB8.astype(int)).max())
        assert error.max() <= (widest_step + 1) // 2


class TestColourIndex:
    def test_index_packing_round_trips_through_channel_split(self):
        index = np.arange(neocolor.COLOR_INDEX_COUNT)

        channels = neocolor.color_index_to_c5(index)

        repacked = (
            (channels[:, 0].astype(np.uint16) << 10)
            | (channels[:, 1].astype(np.uint16) << 5)
            | channels[:, 2].astype(np.uint16)
        )
        assert np.array_equal(repacked, index.astype(np.uint16))

    def test_displayed_grid_colours_quantize_back_to_themselves(self):
        index = np.arange(neocolor.COLOR_INDEX_COUNT)

        recovered = neocolor.rgb_to_color_index(neocolor.color_index_to_rgb(index))

        assert np.array_equal(recovered, index.astype(np.uint16))

    def test_vectorized_word_encoding_matches_the_scalar_encoder(self):
        index = np.arange(0, neocolor.COLOR_INDEX_COUNT, 313)

        words = neocolor.color_index_to_palette_word(index)

        channels = neocolor.color_index_to_c5(index)
        expected = [neocolor.pack_palette_word(int(r), int(g), int(b)) for r, g, b in channels]
        assert [int(w) for w in words] == expected

    def test_every_grid_word_decodes_to_its_own_displayed_colour(self):
        index = np.arange(0, neocolor.COLOR_INDEX_COUNT, 97)

        words = neocolor.color_index_to_palette_word(index)

        decoded = np.array([geolith_resnet_rgb(int(w)) for w in words], dtype=np.uint8)
        assert np.array_equal(decoded, neocolor.color_index_to_rgb(index))


class TestOklab:
    def test_white_maps_to_unit_lightness_and_neutral_chroma(self):
        white = np.array([[255, 255, 255]], dtype=np.uint8)

        lab = neocolor.srgb_to_oklab(white)[0]

        assert lab[0] == pytest.approx(1.0, abs=1e-3)
        assert lab[1] == pytest.approx(0.0, abs=1e-3)
        assert lab[2] == pytest.approx(0.0, abs=1e-3)

    def test_black_maps_to_the_origin(self):
        black = np.array([[0, 0, 0]], dtype=np.uint8)

        lab = neocolor.srgb_to_oklab(black)[0]

        assert np.allclose(lab, 0.0, atol=1e-6)

    def test_pure_red_has_positive_a_and_positive_b(self):
        red = np.array([[255, 0, 0]], dtype=np.uint8)

        lab = neocolor.srgb_to_oklab(red)[0]

        assert lab[1] > 0.0
        assert lab[2] > 0.0

    def test_lightness_is_monotonic_along_the_grey_axis(self):
        greys = np.stack([np.arange(256)] * 3, axis=-1).astype(np.uint8)

        lightness = neocolor.srgb_to_oklab(greys)[:, 0]

        assert np.all(np.diff(lightness) > 0)

    def test_grid_table_covers_every_colour_index(self):
        grid = neocolor.build_oklab_grid()

        assert grid.shape == (neocolor.COLOR_INDEX_COUNT, 3)

    def test_grid_table_agrees_with_direct_conversion(self):
        index = np.arange(0, neocolor.COLOR_INDEX_COUNT, 521)

        grid = neocolor.build_oklab_grid()[index]

        direct = neocolor.srgb_to_oklab(neocolor.color_index_to_rgb(index))
        assert np.allclose(grid, direct, atol=1e-6)
