from __future__ import annotations

import numpy as np
import pytest

from aesmovie import crom, encode, palettes
from tests.geolith_model import GeolithTileReader, StreamPlayer

HEIGHT = 224
WIDTH = 320


def flat_clip(count: int, color: tuple[int, int, int]) -> np.ndarray:
    clip = np.zeros((count, HEIGHT, WIDTH, 3), dtype=np.uint8)
    clip[:, :, :] = color
    return clip


def options(**overrides) -> encode.EncodeOptions:
    base = {
        "palette_count": 4,
        "base_bank": 16,
        "keyframe_interval": 8,
        "candidates": 0,
        "sample_stride": 1,
        "seed": 5,
    }
    base.update(overrides)
    return encode.EncodeOptions(**base)


class TestFrameCadence:
    def test_the_stream_holds_one_record_per_source_frame(self):
        result = encode.encode(flat_clip(12, (200, 40, 40)), options())

        assert len(result.stream) == 12

    def test_the_first_frame_is_always_a_keyframe(self):
        result = encode.encode(flat_clip(4, (10, 200, 30)), options())

        assert next(iter(result.stream.keyframes())) == 0

    def test_keyframes_follow_the_requested_interval(self):
        result = encode.encode(flat_clip(20, (10, 200, 30)), options(keyframe_interval=8))

        assert list(result.stream.keyframes()) == [0, 8, 16]

    def test_a_keyframe_rewrites_every_slot(self):
        result = encode.encode(flat_clip(9, (10, 200, 30)), options(keyframe_interval=8))

        assert result.updates_per_frame[8] == encode.SLOT_COUNT

    def test_a_static_clip_emits_no_deltas_between_keyframes(self):
        result = encode.encode(flat_clip(6, (10, 200, 30)), options(keyframe_interval=100))

        assert list(result.updates_per_frame[1:]) == [0] * 5


class TestDictionary:
    def test_a_flat_clip_needs_a_single_tile(self):
        result = encode.encode(flat_clip(6, (120, 60, 200)), options())

        assert len(result.dictionary) == 1

    def test_uniform_frames_cost_at_most_one_tile_per_colour(self):
        clip = np.concatenate([flat_clip(3, (200, 0, 0)), flat_clip(3, (0, 0, 200))])

        result = encode.encode(clip, options(keyframe_interval=100))

        assert len(result.dictionary) <= 2

    def test_content_returning_to_an_earlier_frame_adds_no_tiles(self):
        rng = np.random.default_rng(3)
        first = rng.integers(0, 256, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)
        second = rng.integers(0, 256, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)
        two = np.stack([first, second])
        three = np.stack([first, second, first])

        without_return = encode.encode(two, options(keyframe_interval=100))
        with_return = encode.encode(three, options(keyframe_interval=100))

        assert len(with_return.dictionary) == len(without_return.dictionary)

    def test_the_tile_count_is_reported(self):
        result = encode.encode(flat_clip(3, (30, 30, 30)), options())

        assert result.stats.tile_count == len(result.dictionary)


class TestDeltas:
    def test_changing_one_slot_emits_one_update(self):
        clip = flat_clip(3, (200, 30, 30))
        clip[1:, 0:16, 0:16] = (30, 30, 200)

        result = encode.encode(clip, options(keyframe_interval=100))

        assert result.updates_per_frame[1] == 1

    def test_a_reverted_slot_emits_again(self):
        clip = flat_clip(4, (200, 30, 30))
        clip[1, 0:16, 0:16] = (30, 30, 200)

        result = encode.encode(clip, options(keyframe_interval=100))

        assert list(result.updates_per_frame) == [encode.SLOT_COUNT, 1, 1, 0]

    def test_a_duplicated_source_frame_costs_nothing(self):
        clip = flat_clip(4, (90, 140, 60))

        result = encode.encode(clip, options(keyframe_interval=100))

        assert result.stats.delta_bytes == 2 * 3


class TestTolerance:
    def drifting_clip(self, shade: int) -> np.ndarray:
        clip = flat_clip(3, (100, 100, 100))
        clip[1:, 0:16, 0:16] = (shade, 100, 100)
        return clip

    def test_the_probe_change_survives_colour_quantization(self):
        result = encode.encode(self.drifting_clip(120), options(keyframe_interval=100))

        assert result.updates_per_frame[1] == 1

    def test_a_tolerance_above_the_change_suppresses_it(self):
        result = encode.encode(
            self.drifting_clip(120), options(keyframe_interval=100, tolerance=0.002)
        )

        assert result.updates_per_frame[1] == 0

    def test_a_tolerance_below_the_change_keeps_it(self):
        result = encode.encode(
            self.drifting_clip(120), options(keyframe_interval=100, tolerance=0.0005)
        )

        assert result.updates_per_frame[1] == 1

    def test_zero_tolerance_keeps_every_visible_change(self):
        result = encode.encode(
            self.drifting_clip(200), options(keyframe_interval=100, tolerance=0.0)
        )

        assert result.updates_per_frame[1] == 1

    def test_a_suppressed_slot_leaves_the_earlier_picture_on_screen(self):
        result = encode.encode(
            self.drifting_clip(120), options(keyframe_interval=100, tolerance=0.002)
        )

        assert np.array_equal(result.rendered[1], result.rendered[0])


class TestSceneCuts:
    def test_a_full_frame_change_forces_a_keyframe(self):
        clip = np.concatenate([flat_clip(3, (200, 0, 0)), flat_clip(3, (0, 200, 0))])

        result = encode.encode(clip, options(keyframe_interval=100, scene_cut_ratio=0.5))

        assert 3 in list(result.stream.keyframes())

    def test_a_small_change_does_not_force_a_keyframe(self):
        clip = flat_clip(6, (200, 0, 0))
        clip[3:, 0:16, 0:16] = (0, 200, 0)

        result = encode.encode(clip, options(keyframe_interval=100, scene_cut_ratio=0.5))

        assert list(result.stream.keyframes()) == [0]


class TestValidation:
    def test_an_empty_clip_is_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            encode.encode(np.zeros((0, HEIGHT, WIDTH, 3), dtype=np.uint8), options())

    def test_a_wrongly_sized_clip_is_rejected(self):
        with pytest.raises(ValueError, match="320x224"):
            encode.encode(np.zeros((2, 100, 100, 3), dtype=np.uint8), options())


class TestPlaybackFidelity:
    """Replays the baked stream through the LSPC model and compares pictures."""

    def gradient_clip(self, count: int) -> np.ndarray:
        rng = np.random.default_rng(42)
        base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        ramp_x = np.linspace(0, 255, WIDTH, dtype=np.uint8)
        ramp_y = np.linspace(0, 255, HEIGHT, dtype=np.uint8)
        base[:, :, 0] = ramp_x[None, :]
        base[:, :, 1] = ramp_y[:, None]
        base[:, :, 2] = 128
        clip = np.repeat(base[None], count, axis=0)
        for index in range(1, count):
            top = rng.integers(0, HEIGHT - 16)
            left = rng.integers(0, WIDTH - 16)
            clip[index:, top : top + 16, left : left + 16] = rng.integers(
                0, 256, size=(16, 16, 3), dtype=np.uint8
            )
        return clip

    def test_replaying_the_stream_reproduces_the_encoder_render(self):
        clip = self.gradient_clip(10)
        result = encode.encode(clip, options(palette_count=16, keyframe_interval=4))
        c1, c2 = crom.pack_tiles(result.dictionary.tiles())
        reader = GeolithTileReader(c1, c2)
        player = StreamPlayer()
        blob = result.stream.blob()

        cursor = 0
        for frame in range(len(result.stream)):
            cursor = player.apply(blob, cursor)
            actual = player.render(reader, result.palette_set.colors, result.palette_set.base_bank)
            assert np.array_equal(actual, result.rendered[frame]), f"frame {frame} differs"

    def test_a_keyframe_alone_reconstructs_the_full_picture(self):
        clip = self.gradient_clip(9)
        result = encode.encode(clip, options(palette_count=16, keyframe_interval=4))
        c1, c2 = crom.pack_tiles(result.dictionary.tiles())
        reader = GeolithTileReader(c1, c2)
        blob = result.stream.blob()
        offsets = result.stream.frame_offsets()

        player = StreamPlayer()
        player.apply(blob, int(offsets[8]))

        actual = player.render(reader, result.palette_set.colors, result.palette_set.base_bank)
        assert np.array_equal(actual, result.rendered[8])

    def test_the_reported_render_matches_the_source_within_the_quantizer_error(self):
        clip = self.gradient_clip(4)

        result = encode.encode(clip, options(palette_count=32, keyframe_interval=4))

        assert result.stats.mean_error >= 0.0
        assert result.rendered.shape == (4, HEIGHT, WIDTH)


class TestEmptyAssignment:
    def test_rendering_an_empty_assignment_yields_no_tiles(self):
        palette_set = palettes.PaletteSet(colors=np.zeros((2, 15), dtype=np.uint16), base_bank=16)
        assignment = palettes.PaletteAssigner(palette_set).assign(
            np.zeros((0, 16, 16), dtype=np.uint16)
        )

        assert assignment.rendered(palette_set).shape == (0, 16, 16)
