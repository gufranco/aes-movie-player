from __future__ import annotations

import itertools

import pytest

from neogeomedia import quality

RATE = 100_000.0
VBLANK = 59.185
LADDER_SIZE = 35


class TestLadder:
    def test_it_runs_from_best_to_cheapest(self):
        # Arrange
        ladder = quality.LADDER

        # Act
        costs = [tier.relative_cost for tier in ladder]

        # Assert
        assert all(dearer > cheaper for dearer, cheaper in itertools.pairwise(costs))

    def test_every_tier_has_a_distinct_name(self):
        # Arrange
        ladder = quality.LADDER

        # Act
        names = {tier.name for tier in ladder}

        # Assert
        assert len(names) == LADDER_SIZE

    def test_the_reference_tier_costs_about_one(self):
        # Arrange
        name = quality.REFERENCE_TIER

        # Act
        tier = quality.tier_by_name(name)

        # Assert
        assert tier.relative_cost == pytest.approx(1.0, abs=0.06)

    def test_an_unknown_tier_is_rejected(self):
        # Arrange
        name = "cinematic"

        # Act
        with pytest.raises(ValueError, match="unknown quality tier") as raised:
            quality.tier_by_name(name)

        # Assert
        assert repr(name) in str(raised.value)


class TestCapacity:
    @pytest.mark.parametrize(
        ("name", "rate", "minutes"),
        [
            ("standard", 100_000.0, 10.48576),
            ("extreme", 100_000.0, 39.718788),
            ("standard", 50_000.0, 20.97152),
        ],
        ids=["the reference rung", "a cheaper tier holds longer", "half the rate holds double"],
    )
    def test_capacity_is_the_crom_tile_count_over_the_tier_rate(self, name, rate, minutes):
        # Arrange
        tier = quality.tier_by_name(name)

        # Act
        capacity = quality.max_minutes(tier, rate)

        # Assert
        assert capacity == pytest.approx(minutes)


class TestSelection:
    @pytest.mark.parametrize(
        ("minutes", "name"),
        [(1.0, "q01"), (2.0, "q01"), (20.0, "q32")],
        ids=["a short source gets the best tier", "two minutes still fit q01", "a long source"],
    )
    def test_a_longer_source_falls_down_the_ladder(self, minutes, name):
        # Arrange
        rate = RATE

        # Act
        fit = quality.select(minutes, rate)

        # Assert
        assert fit is not None
        assert fit.tier.name == name

    def test_a_source_beyond_every_tier_selects_nothing(self):
        # Arrange
        minutes = 600.0

        # Act
        fit = quality.select(minutes, RATE)

        # Assert
        assert fit is None

    def test_the_selected_tier_reports_spare_runtime(self):
        # Arrange
        minutes = 1.0

        # Act
        fit = quality.select(minutes, RATE)

        # Assert
        assert fit is not None
        assert fit.spare_minutes == pytest.approx(5.309287, abs=1e-6)
        assert fit.trim_minutes == 0.0


class TestOvershoot:
    def test_a_tier_that_overruns_reports_how_far(self):
        # Arrange
        minutes = 20.0

        # Act
        archival = quality.survey(minutes, RATE)[0]

        # Assert
        assert archival.fits is False
        assert archival.overshoot == pytest.approx(2.916336, abs=1e-6)
        assert archival.trim_minutes == pytest.approx(13.7)

    def test_trimming_by_the_reported_amount_makes_it_fit(self):
        # Arrange
        archival = quality.survey(20.0, RATE)[0]

        # Act
        trimmed = quality.Fit(
            archival.tier, 20.0 - archival.trim_minutes, archival.capacity_minutes
        )

        # Assert
        assert trimmed.fits is True


class TestClock:
    @pytest.mark.parametrize(
        ("minutes", "text"),
        [(3.5, "3:30"), (3.05, "3:03"), (125.0, "2:05:00")],
        ids=["minutes and seconds", "padded seconds", "hours when present"],
    )
    def test_it_renders_a_runtime_as_a_clock(self, minutes, text):
        # Arrange
        runtime = minutes

        # Act
        rendered = quality.clock(runtime)

        # Assert
        assert rendered == text


class TestReferenceTier:
    def test_it_is_the_most_expensive_rung(self):
        # Arrange
        dearest = max(tier.relative_cost for tier in quality.LADDER)

        # Act
        tier = quality.tier_by_name("reference")

        # Assert
        assert tier.relative_cost == dearest

    def test_it_is_first_on_the_ladder(self):
        # Arrange
        first = quality.LADDER[0]

        # Act
        tier = quality.tier_by_name("reference")

        # Assert
        assert tier is first

    @pytest.mark.parametrize(
        ("alias", "name"),
        [
            ("reference", "q01"),
            ("archival", "q03"),
            ("high", "q11"),
            ("standard", "q17"),
            ("extended", "q23"),
            ("long", "q28"),
            ("maximum", "q33"),
            ("extreme", "q35"),
        ],
    )
    def test_the_older_names_still_resolve(self, alias, name):
        # Arrange
        older = alias

        # Act
        tier = quality.tier_by_name(older)

        # Assert
        assert tier.name == name
        assert tier in quality.LADDER

    def test_it_spends_everything_on_the_picture(self):
        # Arrange
        finest = min(tier.tolerance for tier in quality.LADDER)

        # Act
        tier = quality.tier_by_name("reference")

        # Assert
        assert tier.chroma_weight == 1.0
        assert tier.frame_hold == 1
        assert tier.tolerance == finest
        assert tier.denoise == 0.0
        assert tier.candidates == 0

    def test_a_short_source_selects_it(self):
        # Arrange
        minutes = 0.5

        # Act
        fit = quality.select(minutes, RATE)

        # Assert
        assert fit is not None
        assert fit.tier is quality.tier_by_name("reference")


class TestPerSourceCurve:
    @pytest.mark.parametrize(
        ("rung", "anchors", "expected"),
        [
            (1.0, {2.0: 2.0, 1.0: 1.0, 0.3: 0.3}, 1.0),
            (0.3, {2.0: 2.0, 1.0: 1.0, 0.3: 0.2}, 0.2),
            (2.0, {2.0: 2.5, 1.0: 1.0, 0.3: 0.3}, 2.5),
            (0.6, {2.0: 2.0, 1.0: 1.0, 0.3: 0.2}, 0.505171),
        ],
        ids=[
            "the reference anchor is left alone",
            "a cheaper source pulls the low end down",
            "a dearer source pushes the high end up",
            "a rung between anchors is interpolated",
        ],
    )
    def test_a_rung_follows_the_measured_anchors(self, rung, anchors, expected):
        # Arrange
        measured = dict(anchors)

        # Act
        corrected = quality.rescale(rung, anchors=measured)

        # Assert
        assert corrected == pytest.approx(expected, abs=1e-6)

    @pytest.mark.parametrize("rung", [2.0, 1.5, 1.0, 0.5, 0.3])
    def test_anchors_that_agree_change_nothing(self, rung):
        # Arrange
        anchors = {2.0: 2.0, 1.0: 1.0, 0.3: 0.3}

        # Act
        corrected = quality.rescale(rung, anchors=anchors)

        # Assert
        assert corrected == pytest.approx(rung)

    @pytest.mark.parametrize(
        ("rung", "expected"),
        [
            (2.0, 2.4),
            (1.6, 1.8106),
            (1.2, 1.259),
            (1.0, 1.0),
            (0.8, 0.7553),
            (0.5, 0.4182),
            (0.3, 0.22),
        ],
    )
    def test_the_correction_stays_ordered(self, rung, expected):
        # Arrange
        anchors = {2.0: 2.4, 1.0: 1.0, 0.3: 0.22}

        # Act
        corrected = quality.rescale(rung, anchors=anchors)

        # Assert
        assert corrected == pytest.approx(expected, abs=1e-4)


class TestUnreachableHolds:
    @pytest.mark.parametrize(
        ("source_fps", "name", "offered"),
        [(24.0, "q31", False), (24.0, "q32", True), (60.0, "q31", True)],
        ids=[
            "a hold that drops no source frame is not offered",
            "a hold that does drop frames stays on the ladder",
            "a faster source keeps the shorter hold",
        ],
    )
    def test_a_hold_is_offered_only_when_it_drops_source_frames(self, source_fps, name, offered):
        # Arrange
        scope = {"source_fps": source_fps, "vblank_fps": VBLANK}

        # Act
        survey = quality.survey(30.0, RATE, **scope)

        # Assert
        assert (name in [fit.tier.name for fit in survey]) is offered

    def test_without_a_source_rate_every_tier_is_offered(self):
        # Arrange
        minutes = 30.0

        # Act
        survey = quality.survey(minutes, RATE)

        # Assert
        assert len(survey) == LADDER_SIZE

    def test_selection_never_returns_a_tier_the_baker_would_refuse(self):
        # Arrange
        scope = {"source_fps": 24.0, "vblank_fps": VBLANK}

        # Act
        fit = quality.select(25.0, RATE, **scope)

        # Assert
        assert fit is not None
        assert fit.tier.name == "q33"


class TestAnchorChoice:
    def test_the_anchors_span_the_ladder_when_the_source_allows_a_hold(self):
        # Arrange
        source_fps = 24.0

        # Act
        anchors = quality.anchor_tiers(source_fps, VBLANK)

        # Assert
        assert [tier.name for tier in anchors] == ["q01", quality.REFERENCE_TIER, "q30", "q32"]
        assert max(tier.frame_hold for tier in anchors) == 3

    def test_a_slow_source_drops_the_hold_anchor(self):
        # Arrange
        source_fps = 10.0

        # Act
        anchors = quality.anchor_tiers(source_fps, VBLANK)

        # Assert
        assert [tier.frame_hold for tier in anchors] == [1, 1, 1]

    def test_every_anchor_is_a_real_tier(self):
        # Arrange
        source_fps = 24.0

        # Act
        anchors = quality.anchor_tiers(source_fps, VBLANK)

        # Assert
        assert all(quality.tier_by_name(tier.name) is tier for tier in anchors)


class TestEdges:
    def test_a_rung_that_costs_nothing_fits_any_length(self):
        # Arrange
        tier = quality.tier_by_name(quality.REFERENCE_TIER)

        # Act
        minutes = quality.max_minutes(tier, 0.0)

        # Assert
        assert minutes == float("inf")

    def test_a_film_of_no_length_takes_the_default_audio_rate(self):
        # Arrange
        minutes = 0.0

        # Act
        rate = quality.audio_hz_for(minutes)

        # Assert
        assert rate == quality.DEFAULT_AUDIO_HZ

    def test_a_rung_with_no_capacity_overshoots_without_bound(self):
        # Arrange
        fit = quality.Fit(tier=quality.LADDER[0], minutes=1.0, capacity_minutes=0.0)

        # Act
        overshoot = fit.overshoot

        # Assert
        assert overshoot == float("inf")

    def test_two_anchors_at_the_same_cost_give_the_lower_ones_rate(self):
        # Arrange
        anchors = {1.0: 500.0, 1.0 + 1e-14: 900.0}

        # Act
        rate = quality.rescale(1.0, anchors=anchors)

        # Assert
        assert rate == 500.0
