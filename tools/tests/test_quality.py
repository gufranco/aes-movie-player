"""Quality tier selection tests.

The ladder decides how long a movie can be, so the arithmetic that picks
a tier is checked directly rather than through a bake.
"""

from __future__ import annotations

import pytest

from aesmovie import quality


class TestLadder:
    def test_it_runs_from_best_to_cheapest(self):
        costs = [tier.relative_cost for tier in quality.LADDER]

        assert costs == sorted(costs, reverse=True)

    def test_every_tier_has_a_distinct_name(self):
        names = [tier.name for tier in quality.LADDER]

        assert len(names) == len(set(names))

    def test_the_reference_tier_costs_exactly_one(self):
        assert quality.tier_by_name(quality.REFERENCE_TIER).relative_cost == 1.0

    def test_an_unknown_tier_is_rejected(self):
        with pytest.raises(ValueError, match="unknown quality tier"):
            quality.tier_by_name("cinematic")


class TestCapacity:
    def test_a_cheaper_tier_holds_a_longer_movie(self):
        rate = 100_000.0

        standard = quality.max_minutes(quality.tier_by_name("standard"), rate)
        extreme = quality.max_minutes(quality.tier_by_name("extreme"), rate)

        assert extreme > standard

    def test_capacity_scales_inversely_with_the_measured_rate(self):
        tier = quality.tier_by_name("standard")

        cheap = quality.max_minutes(tier, 50_000.0)
        dear = quality.max_minutes(tier, 100_000.0)

        assert cheap == pytest.approx(dear * 2.0)


class TestSelection:
    def test_a_short_source_gets_the_best_tier(self):
        fit = quality.select(1.0, 100_000.0)

        assert fit is not None
        assert fit.tier.name == "archival"

    def test_a_long_source_falls_down_the_ladder(self):
        short = quality.select(2.0, 100_000.0)
        long = quality.select(20.0, 100_000.0)

        assert short is not None
        assert long is not None
        assert long.tier.relative_cost < short.tier.relative_cost

    def test_a_source_beyond_every_tier_selects_nothing(self):
        assert quality.select(600.0, 100_000.0) is None

    def test_the_selected_tier_reports_spare_runtime(self):
        fit = quality.select(1.0, 100_000.0)

        assert fit is not None
        assert fit.spare_minutes > 0.0
        assert fit.trim_minutes == 0.0


class TestOvershoot:
    def test_a_tier_that_overruns_reports_how_far(self):
        survey = quality.survey(20.0, 100_000.0)
        archival = survey[0]

        assert not archival.fits
        assert archival.overshoot > 1.0
        assert archival.trim_minutes > 0.0

    def test_trimming_by_the_reported_amount_makes_it_fit(self):
        survey = quality.survey(20.0, 100_000.0)
        archival = survey[0]

        trimmed = quality.Fit(
            archival.tier, 20.0 - archival.trim_minutes, archival.capacity_minutes
        )

        assert trimmed.fits


class TestAudioRate:
    def test_a_short_movie_keeps_the_full_rate(self):
        assert quality.audio_hz_for(5.0) == quality.DEFAULT_AUDIO_HZ

    def test_a_long_movie_drops_the_rate_to_fit(self):
        assert quality.audio_hz_for(60.0) < quality.DEFAULT_AUDIO_HZ

    def test_the_chosen_rate_always_fits_the_voice_rom(self):
        minutes = 40.0

        rate = quality.audio_hz_for(minutes)
        needed = minutes * quality.SECONDS_PER_MINUTE * rate * quality.ADPCM_B_BYTES_PER_SAMPLE

        assert needed <= quality.ADPCM_B_BYTES


class TestClock:
    def test_it_renders_minutes_and_seconds(self):
        assert quality.clock(3.5) == "3:30"

    def test_it_pads_seconds(self):
        assert quality.clock(3.05) == "3:03"

    def test_it_renders_hours_when_present(self):
        assert quality.clock(125.0) == "2:05:00"


class TestPlanReport:
    def plan(self, minutes: float, rate: float = 100_000.0) -> str:
        return quality.format_plan(
            source="film.mkv",
            minutes=minutes,
            width=1920,
            height=1080,
            source_fps=24.0,
            has_audio=True,
            reference_rate=rate,
            vblank_fps=59.1856,
        )

    def test_it_names_every_tier(self):
        text = self.plan(12.0)

        for tier in quality.LADDER:
            assert tier.name in text

    def test_it_states_the_selected_tier(self):
        text = self.plan(12.0)

        assert "Selected" in text

    def test_it_reports_the_measured_rate(self):
        text = self.plan(12.0)

        assert "100,000" in text

    def test_it_tells_the_user_how_much_to_trim_for_a_better_tier(self):
        text = self.plan(12.0)

        assert "Trim" in text

    def test_it_says_plainly_when_nothing_fits(self):
        text = self.plan(600.0)

        assert "does not fit" in text

    def test_a_source_that_fits_the_best_tier_needs_no_trim_advice(self):
        text = self.plan(0.5)

        assert "archival" in text
        assert "Trim" not in text

    def test_it_reports_the_budget_of_the_selected_tier(self):
        text = self.plan(12.0)

        assert "C-ROM" in text
        assert "audio" in text
