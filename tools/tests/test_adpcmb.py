"""ADPCM-B encoder tests.

`YmfmDecoder` transcribes `adpcm_b_channel_clock` from the ymfm core
that geolith drives the YM2610 with. Encoding then decoding through it
proves the nibbles reconstruct the intended waveform on the chip that
will actually play them, rather than merely round-tripping through the
encoder's own model.
"""

from __future__ import annotations

import numpy as np
import pytest

from aesmovie import adpcmb

STEP_SCALE = (57, 57, 57, 57, 77, 102, 128, 153)
STEP_MIN = 127
STEP_MAX = 24576


class YmfmDecoder:
    def __init__(self) -> None:
        self.accumulator = 0
        self.step = STEP_MIN

    def nibble(self, data: int) -> int:
        delta = (2 * (data & 7) + 1) * self.step // 8
        if data & 8:
            delta = -delta
        self.accumulator = max(-32768, min(32767, self.accumulator + delta))
        self.step = max(STEP_MIN, min(STEP_MAX, (self.step * STEP_SCALE[data & 7]) // 64))
        return self.accumulator

    def decode(self, payload: bytes) -> np.ndarray:
        out = []
        for byte in payload:
            out.append(self.nibble((byte >> 4) & 0x0F))
            out.append(self.nibble(byte & 0x0F))
        return np.array(out, dtype=np.int32)


def sine(count: int, cycles: float, amplitude: int = 20000) -> np.ndarray:
    t = np.linspace(0.0, cycles * 2.0 * np.pi, count, endpoint=False)
    return (np.sin(t) * amplitude).astype(np.int16)


class TestDeltaN:
    def test_the_rate_register_follows_the_documented_formula(self):
        assert adpcmb.delta_n_for(55555) == 65535

    def test_a_common_rate_lands_close_to_the_request(self):
        delta_n = adpcmb.delta_n_for(22050)

        assert adpcmb.rate_for(delta_n) == pytest.approx(22050, abs=2)

    def test_the_register_stays_inside_sixteen_bits(self):
        assert 0 < adpcmb.delta_n_for(55555) <= 0xFFFF

    def test_a_rate_above_the_ceiling_is_rejected(self):
        with pytest.raises(ValueError, match="rate"):
            adpcmb.delta_n_for(60000)

    def test_a_non_positive_rate_is_rejected(self):
        with pytest.raises(ValueError, match="rate"):
            adpcmb.delta_n_for(0)


class TestEncoding:
    def test_two_samples_pack_into_one_byte(self):
        encoded = adpcmb.encode(sine(512, 2.0))

        assert len(encoded.payload) == 256

    def test_an_odd_sample_count_pads_to_a_whole_byte(self):
        encoded = adpcmb.encode(sine(511, 2.0))

        assert len(encoded.payload) == 256

    def test_the_high_nibble_holds_the_earlier_sample(self):
        encoded = adpcmb.encode(np.array([20000, 20000], dtype=np.int16))

        first = (encoded.payload[0] >> 4) & 0x0F
        assert first & 0x08 == 0

    def test_silence_encodes_to_the_smallest_steps(self):
        encoded = adpcmb.encode(np.zeros(512, dtype=np.int16))

        decoded = YmfmDecoder().decode(encoded.payload)[:512]
        assert int(np.abs(decoded).max()) < 200

    def test_the_padding_tail_does_not_ramp_away(self):
        encoded = adpcmb.encode(np.zeros(300, dtype=np.int16))

        decoded = YmfmDecoder().decode(encoded.payload)
        assert int(np.abs(decoded).max()) < 200

    def test_a_sine_reconstructs_within_a_few_percent(self):
        source = sine(4096, 16.0)

        encoded = adpcmb.encode(source)

        decoded = YmfmDecoder().decode(encoded.payload)[: len(source)]
        error = np.abs(decoded - source.astype(np.int32)).mean()
        assert error < 0.05 * 20000

    def test_a_loud_sine_does_not_clip_the_accumulator(self):
        source = sine(2048, 8.0, amplitude=32000)

        encoded = adpcmb.encode(source)

        decoded = YmfmDecoder().decode(encoded.payload)[: len(source)]
        assert np.abs(decoded - source.astype(np.int32)).mean() < 0.08 * 32000

    def test_a_step_change_is_tracked_within_a_few_samples(self):
        source = np.concatenate([np.zeros(32, dtype=np.int16), np.full(224, 15000, dtype=np.int16)])

        encoded = adpcmb.encode(source)

        decoded = YmfmDecoder().decode(encoded.payload)[: len(source)]
        assert abs(int(decoded[-1]) - 15000) < 1500

    def test_encoding_is_deterministic(self):
        source = sine(512, 5.0)

        assert adpcmb.encode(source).payload == adpcmb.encode(source).payload

    def test_an_empty_signal_is_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            adpcmb.encode(np.zeros(0, dtype=np.int16))

    def test_a_stereo_signal_is_rejected(self):
        with pytest.raises(ValueError, match="mono"):
            adpcmb.encode(np.zeros((64, 2), dtype=np.int16))


class TestRomLayout:
    def test_the_rom_pads_to_the_requested_size(self):
        encoded = adpcmb.encode(sine(1024, 4.0))

        rom = adpcmb.build_rom(encoded, pad_to=65536)

        assert len(rom) == 65536

    def test_the_payload_sits_at_the_front_of_the_rom(self):
        encoded = adpcmb.encode(sine(1024, 4.0))

        rom = adpcmb.build_rom(encoded, pad_to=65536)

        assert rom[: len(encoded.payload)] == encoded.payload

    def test_addresses_are_reported_in_the_chip_s_units(self):
        encoded = adpcmb.encode(sine(2048, 4.0))

        assert encoded.start_address == 0
        assert encoded.end_address == (len(encoded.payload) - 1) >> 8

    def test_the_payload_is_padded_to_a_page_boundary(self):
        encoded = adpcmb.encode(sine(300, 2.0))

        assert len(encoded.payload) % 256 == 0

    def test_a_rom_smaller_than_the_payload_is_rejected(self):
        encoded = adpcmb.encode(sine(4096, 4.0))

        with pytest.raises(ValueError, match="pad_to"):
            adpcmb.build_rom(encoded, pad_to=256)

    def test_the_sixteen_mebibyte_ceiling_is_enforced(self):
        encoded = adpcmb.encode(sine(512, 2.0))

        with pytest.raises(ValueError, match="16 MiB"):
            adpcmb.build_rom(encoded, pad_to=(16 << 20) + 256)
