from __future__ import annotations

from pathlib import Path

import pytest

from neogeomedia import denoise, encode, frames, quality

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fmv-core-python" / "fixtures" / "synthetic.mp4"


def scored(strength: float, error: float, tiles: int) -> denoise.Score:
    return denoise.Score(strength=strength, error=error, tiles=tiles)


class TestChoose:
    def test_the_lowest_error_wins(self):
        # Arrange
        scores = [scored(0.0, 0.020, 900), scored(2.0, 0.018, 800), scored(4.0, 0.019, 700)]

        # Act
        chosen = denoise.choose(scores)

        # Assert
        assert chosen.strength == 2.0

    def test_a_near_tie_goes_to_the_cheaper_setting(self):
        # Arrange
        scores = [scored(0.0, 0.0200, 900), scored(4.0, 0.0201, 600)]

        # Act
        chosen = denoise.choose(scores)

        # Assert
        assert chosen.strength == 4.0

    def test_a_clear_loss_is_not_rescued_by_being_cheap(self):
        # Arrange
        scores = [scored(0.0, 0.0200, 900), scored(4.0, 0.0230, 300)]

        # Act
        chosen = denoise.choose(scores)

        # Assert
        assert chosen.strength == 0.0

    def test_no_scores_is_refused(self):
        # Arrange
        scores: list[denoise.Score] = []

        # Act
        with pytest.raises(ValueError) as refused:
            denoise.choose(scores)

        # Assert
        assert str(refused.value) == "no denoise strength was measured"


class TestMeasure:
    @pytest.mark.ffmpeg
    def test_every_candidate_is_scored_against_the_undenoised_source(self):
        # Arrange
        tier = quality.tier_by_name("q17")

        # Act
        scores = denoise.measure(
            FIXTURE, tier, start=0.0, window=1.0, candidates=(0.0, 4.0), dither=0.0
        )

        # Assert
        assert ([s.strength for s in scores], all(s.error > 0 for s in scores)) == (
            [0.0, 4.0],
            True,
        )

    @pytest.mark.ffmpeg
    def test_denoising_spends_no_more_tiles_than_leaving_the_source_alone(self):
        # Arrange
        tier = quality.tier_by_name("q17")

        # Act
        none, heavy = denoise.measure(
            FIXTURE, tier, start=0.0, window=1.0, candidates=(0.0, 8.0), dither=0.0
        )

        # Assert
        assert heavy.tiles <= none.tiles

    @pytest.mark.ffmpeg
    def test_each_trial_bakes_with_the_dither_the_film_will_be_baked_with(self):
        # Arrange
        tier = quality.tier_by_name("q17")
        clip = frames.decode(FIXTURE, start=0.0, duration=1.0)
        plain = encode.EncodeOptions(
            tolerance=tier.tolerance,
            candidates=tier.candidates,
            chroma_weight=tier.chroma_weight,
            frame_hold=tier.frame_hold,
            dither=0.0,
        )
        expected = encode.encode(clip, plain).stats.tile_count

        # Act
        (score,) = denoise.measure(
            FIXTURE, tier, start=0.0, window=1.0, candidates=(0.0,), dither=0.0
        )

        # Assert
        assert score.tiles == expected
