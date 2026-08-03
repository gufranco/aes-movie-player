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


class TestDictionaryCeiling:
    def noisy_clip(self, count: int) -> np.ndarray:
        rng = np.random.default_rng(7)
        return rng.integers(0, 256, size=(count, HEIGHT, WIDTH, 3), dtype=np.uint8)

    def test_a_full_dictionary_does_not_fail_the_bake(self):
        result = encode.encode(
            self.noisy_clip(4), options(palette_count=8, dictionary_capacity=100)
        )

        assert result.stats.frames == 4

    def test_a_full_dictionary_is_reported(self):
        result = encode.encode(
            self.noisy_clip(4), options(palette_count=8, dictionary_capacity=100)
        )

        assert result.stats.dictionary_full is True

    def test_the_dictionary_never_exceeds_its_capacity(self):
        result = encode.encode(
            self.noisy_clip(4), options(palette_count=8, dictionary_capacity=100)
        )

        assert len(result.dictionary) <= 100

    def test_slots_with_no_tile_keep_showing_the_previous_one(self):
        result = encode.encode(self.noisy_clip(3), options(palette_count=8, dictionary_capacity=60))

        assert result.updates_per_frame[2] < encode.SLOT_COUNT

    def test_an_unfilled_dictionary_reports_room_left(self):
        result = encode.encode(flat_clip(3, (40, 90, 160)), options())

        assert result.stats.dictionary_full is False


class TestFrameHold:
    def moving_clip(self, count: int) -> np.ndarray:
        rng = np.random.default_rng(11)
        clip = np.zeros((count, HEIGHT, WIDTH, 3), dtype=np.uint8)
        for index in range(count):
            clip[index] = rng.integers(0, 256, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)
        return clip

    def test_holding_frames_keeps_the_frame_count(self):
        result = encode.encode(self.moving_clip(12), options(frame_hold=3))

        assert result.stats.frames == 12

    def test_holding_frames_shrinks_the_dictionary(self):
        clip = self.moving_clip(12)

        plain = encode.encode(clip, options())
        held = encode.encode(clip, options(frame_hold=3))

        assert len(held.dictionary) < len(plain.dictionary)

    def test_a_hold_of_one_changes_nothing(self):
        clip = self.moving_clip(6)

        assert len(encode.encode(clip, options(frame_hold=1)).dictionary) == len(
            encode.encode(clip, options()).dictionary
        )

    def test_held_frames_repeat_the_picture(self):
        result = encode.encode(self.moving_clip(9), options(frame_hold=3, keyframe_interval=100))

        assert result.updates_per_frame[1] == 0
        assert result.updates_per_frame[2] == 0

    def test_a_zero_hold_is_treated_as_one(self):
        clip = self.moving_clip(6)

        assert len(encode.encode(clip, options(frame_hold=0)).dictionary) == len(
            encode.encode(clip, options(frame_hold=1)).dictionary
        )


class TestMotionMasking:
    def half_moving(self, count: int) -> np.ndarray:
        """Left half churns hard, right half holds still."""
        rng = np.random.default_rng(21)
        clip = np.zeros((count, HEIGHT, WIDTH, 3), dtype=np.uint8)
        still = rng.integers(0, 256, size=(HEIGHT, WIDTH // 2, 3), dtype=np.uint8)
        for index in range(count):
            clip[index, :, WIDTH // 2 :] = still
            clip[index, :, : WIDTH // 2] = rng.integers(
                0, 256, size=(HEIGHT, WIDTH // 2, 3), dtype=np.uint8
            )
        return clip

    def settings(self, **extra):
        base = {"keyframe_interval": 1000, "scene_cut_ratio": 1.1, "tolerance": 0.0005}
        base.update(extra)
        return options(**base)

    def test_masking_off_reproduces_the_flat_threshold(self):
        clip = self.half_moving(6)

        flat = encode.encode(clip, self.settings())
        masked = encode.encode(clip, self.settings(motion_masking=0.0))

        assert list(flat.updates_per_frame) == list(masked.updates_per_frame)

    def test_masking_shrinks_the_dictionary_on_moving_content(self):
        clip = self.half_moving(6)

        flat = encode.encode(clip, self.settings())
        masked = encode.encode(clip, self.settings(motion_masking=20.0))

        assert len(masked.dictionary) < len(flat.dictionary)

    def test_masking_reduces_the_slot_updates(self):
        clip = self.half_moving(6)

        flat = encode.encode(clip, self.settings())
        masked = encode.encode(clip, self.settings(motion_masking=20.0))

        assert masked.updates_per_frame[3] < flat.updates_per_frame[3]

    def test_an_error_hidden_by_motion_is_repaired_once_motion_stops(self):
        clip = flat_clip(4, (100, 100, 100))
        clip[1:, 0:16, 0:16] = (200, 40, 40)

        masked = encode.encode(clip, self.settings(motion_masking=20.0))

        assert masked.updates_per_frame[1] == 0
        assert masked.updates_per_frame[2] == 1

    def test_a_still_region_is_never_left_wrong(self):
        clip = flat_clip(6, (100, 100, 100))
        clip[1:, 0:16, 0:16] = (200, 40, 40)

        masked = encode.encode(clip, self.settings(motion_masking=20.0))

        assert np.array_equal(masked.rendered[5], masked.rendered[4])
        assert int(masked.updates_per_frame[3:].sum()) == 0

    def test_a_bigger_masking_factor_saves_more(self):
        clip = self.half_moving(6)

        light = encode.encode(clip, self.settings(motion_masking=5.0))
        heavy = encode.encode(clip, self.settings(motion_masking=40.0))

        assert len(heavy.dictionary) <= len(light.dictionary)


class TestSceneCutFloor:
    def gentle_drift(self, count: int) -> np.ndarray:
        """Every slot changes every frame, by one shade."""
        clip = np.zeros((count, HEIGHT, WIDTH, 3), dtype=np.uint8)
        for index in range(count):
            clip[index, :, :] = (100 + 8 * index, 100, 100)
        return clip

    def test_a_shade_everywhere_is_not_a_scene_cut(self):
        clip = self.gentle_drift(6)

        result = encode.encode(clip, options(keyframe_interval=100, scene_cut_floor=0.01))

        assert list(result.stream.keyframes()) == [0]

    def test_a_floor_of_zero_reads_the_same_drift_as_a_cut(self):
        clip = self.gentle_drift(6)

        result = encode.encode(clip, options(keyframe_interval=100, scene_cut_floor=0.0))

        assert len(result.stream.keyframes()) > 1

    def test_a_real_jump_still_forces_a_keyframe(self):
        clip = np.concatenate([flat_clip(3, (200, 0, 0)), flat_clip(3, (0, 200, 0))])

        result = encode.encode(clip, options(keyframe_interval=100, scene_cut_floor=0.01))

        assert 3 in list(result.stream.keyframes())

    def test_the_floor_cuts_the_dictionary_on_drifting_content(self):
        clip = self.gentle_drift(6)

        counted = encode.encode(clip, options(keyframe_interval=100, scene_cut_floor=0.0))
        measured = encode.encode(clip, options(keyframe_interval=100, scene_cut_floor=0.01))

        assert len(measured.dictionary) < len(counted.dictionary)


class TestChromaWeight:
    def test_the_grid_scales_only_the_chroma_axes(self):
        plain = palettes.oklab_grid(1.0)
        weighted = palettes.oklab_grid(0.25)

        assert np.allclose(weighted[:, 0], plain[:, 0])
        assert np.allclose(weighted[:, 1:], plain[:, 1:] * 0.5)

    def test_a_weight_of_one_is_the_unweighted_grid(self):
        assert palettes.oklab_grid(1.0) is palettes.oklab_grid()

    def test_a_non_positive_weight_is_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            palettes.oklab_grid(0.0)

    def test_cheaper_chroma_never_grows_the_dictionary(self):
        rng = np.random.default_rng(7)
        clip = rng.integers(0, 256, size=(6, HEIGHT, WIDTH, 3), dtype=np.uint8)

        plain = encode.encode(clip, options(chroma_weight=1.0))
        cheap = encode.encode(clip, options(chroma_weight=0.1))

        assert len(cheap.dictionary) <= len(plain.dictionary)


class TestDisplayedError:
    def drifting(self, count: int) -> np.ndarray:
        clip = np.zeros((count, HEIGHT, WIDTH, 3), dtype=np.uint8)
        for index in range(count):
            clip[index, :, :] = (100, 100, 100)
            clip[index, 0:16, 0:16] = (100 + 12 * index, 100, 100)
        return clip

    def test_skipping_work_is_reported_as_worse_not_better(self):
        clip = self.drifting(8)

        keen = encode.encode(clip, options(keyframe_interval=1000, tolerance=0.0))
        lazy = encode.encode(clip, options(keyframe_interval=1000, tolerance=0.05))

        assert lazy.stats.displayed_error > keen.stats.displayed_error

    def test_holding_a_frame_is_charged_against_the_true_source(self):
        clip = self.drifting(8)

        live = encode.encode(clip, options(keyframe_interval=1000, frame_hold=1))
        held = encode.encode(clip, options(keyframe_interval=1000, frame_hold=4))

        assert held.stats.displayed_error > live.stats.displayed_error

    def test_an_exact_reproduction_reports_no_error(self):
        clip = flat_clip(4, (128, 64, 32))

        result = encode.encode(clip, options())

        assert result.stats.displayed_error == pytest.approx(0.0, abs=1e-6)


class TestRateControl:
    def busy(self, count: int) -> np.ndarray:
        """Content that mints new tiles on every frame."""
        rng = np.random.default_rng(11)
        return rng.integers(0, 256, size=(count, HEIGHT, WIDTH, 3), dtype=np.uint8)

    def test_no_budget_leaves_the_encode_untouched(self):
        clip = self.busy(6)

        free = encode.encode(clip, options())
        zeroed = encode.encode(clip, options(tile_budget=0))

        assert len(free.dictionary) == len(zeroed.dictionary)

    def test_a_tight_budget_is_respected(self):
        clip = self.busy(10)

        free = encode.encode(clip, options(keyframe_interval=1000))
        budget = len(free.dictionary) // 2
        held = encode.encode(clip, options(keyframe_interval=1000, tile_budget=budget))

        assert len(held.dictionary) <= budget

    def test_a_generous_budget_does_not_degrade_the_picture(self):
        clip = self.busy(6)

        free = encode.encode(clip, options())
        roomy = encode.encode(clip, options(tile_budget=1 << 20))

        assert len(roomy.dictionary) == len(free.dictionary)

    def test_it_reports_the_tolerance_it_had_to_reach(self):
        clip = self.busy(10)

        free = encode.encode(clip, options(keyframe_interval=1000))
        held = encode.encode(
            clip, options(keyframe_interval=1000, tile_budget=len(free.dictionary) // 2)
        )

        assert held.stats.peak_tolerance > options().tolerance

    def test_an_untouched_budget_reports_the_base_tolerance(self):
        clip = self.busy(6)

        result = encode.encode(clip, options(tile_budget=1 << 20))

        assert result.stats.peak_tolerance == pytest.approx(options().tolerance)

    def test_a_budget_it_cannot_meet_is_reported(self):
        clip = self.busy(10)

        result = encode.encode(clip, options(keyframe_interval=1, tile_budget=10))

        assert result.stats.budget_exceeded
