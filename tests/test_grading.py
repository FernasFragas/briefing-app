from __future__ import annotations

from dataclasses import dataclass

import pytest

from briefing_app.config import ReportGradingSettings
from briefing_app.dashboard.grading import (
    ABOVE_SPOT,
    BELOW_SPOT,
    NO_SCENARIO_TABLE,
    OUTSIDE_ONE_SIGMA,
    WITHIN_ONE_SIGMA,
    alignment,
    compute_grade,
    thesis_band,
)
from briefing_app.models.candidate import Direction
from briefing_app.models.scoring import ConfidenceTier
from briefing_app.strategy.models import SetupType
from briefing_app.strategy.scenarios import ScenarioRow, ScenarioTable


@dataclass(frozen=True)
class StubSetup:
    setup_type: SetupType
    direction: Direction = Direction.LONG
    tier: ConfidenceTier = ConfidenceTier.A
    s_cte: float | None = 1.0
    scenario_table: ScenarioTable | None = None


def make_setup(
    setup_type: SetupType = SetupType.EVENT_DIRECTIONAL_LONG,
    *,
    direction: Direction = Direction.LONG,
    tier: ConfidenceTier = ConfidenceTier.A,
    s_cte: float | None = 1.0,
    table: ScenarioTable | None = None,
) -> StubSetup:
    return StubSetup(
        setup_type=setup_type,
        direction=direction,
        tier=tier,
        s_cte=s_cte,
        scenario_table=table if table is not None else make_table(),
    )


def make_table(
    *,
    below: float = 0.20,
    within: float = 0.50,
    above: float = 0.30,
    diverging_labels: tuple[str, ...] = (),
) -> ScenarioTable:
    return ScenarioTable(
        ticker="TEST",
        spot=100.0,
        horizon_days=10,
        rows=(
            row("below 2 sigma", 0.0, diverging_labels),
            row("1 to 2 sigma down", below, diverging_labels),
            row("within 1 sigma", within, diverging_labels),
            row("1 to 2 sigma up", above, diverging_labels),
            row("above 2 sigma", 0.0, diverging_labels),
        ),
        source="test",
    )


def row(
    label: str,
    probability: float,
    diverging_labels: tuple[str, ...],
) -> ScenarioRow:
    diverging = label in diverging_labels
    return ScenarioRow(
        label=label,
        lower=None,
        upper=None,
        probability=probability,
        implied_probability=0.8 if diverging else None,
        measured_probability=0.6 if diverging else None,
        source="test",
    )


@pytest.mark.parametrize(
    ("score", "letter"),
    [
        (34, "F"),
        (35, "D"),
        (49, "D"),
        (50, "C"),
        (57, "C"),
        (58, "C+"),
        (65, "C+"),
        (66, "B"),
        (73, "B"),
        (74, "B+"),
        (81, "B+"),
        (82, "A"),
        (89, "A"),
        (90, "A+"),
    ],
)
def test_grade_letter_boundaries(score: int, letter: str) -> None:
    settings = ReportGradingSettings(
        probability_weight=1.0,
        alignment_weight=0.0,
        divergence_penalty=0.0,
        crowding_penalty_scale=0.0,
    )
    setup = make_setup(
        SetupType.LONG_PREMIUM_STRADDLE,
        direction=Direction.NEUTRAL,
        table=make_table(within=1.0 - score / 100, above=score / 100),
    )

    result = compute_grade(setup, settings=settings)

    assert result.score == pytest.approx(score)
    assert result.letter == letter


@pytest.mark.parametrize(
    ("tier", "expected_score", "expected_letter"),
    [
        (ConfidenceTier.A, 95.0, "A+"),
        (ConfidenceTier.B, 81.0, "B+"),
        (ConfidenceTier.C, 57.0, "C"),
    ],
)
def test_grade_respects_tier_ceilings(
    tier: ConfidenceTier,
    expected_score: float,
    expected_letter: str,
) -> None:
    setup = make_setup(
        tier=tier,
        s_cte=0.95,
        table=make_table(below=0.05, within=0.0, above=0.95),
    )

    result = compute_grade(setup)

    assert result.score == pytest.approx(expected_score)
    assert result.letter == expected_letter
    ceiling = expected_score if tier is not ConfidenceTier.A else 100.0
    assert result.tier_ceiling == pytest.approx(ceiling)


THESIS_CASES = [
    (SetupType.SHORT_PREMIUM_IRON_CONDOR, Direction.NEUTRAL, WITHIN_ONE_SIGMA, 0.40),
    (SetupType.LONG_PREMIUM_STRADDLE, Direction.NEUTRAL, OUTSIDE_ONE_SIGMA, 0.60),
    (SetupType.LONG_PREMIUM_CALENDAR, Direction.NEUTRAL, OUTSIDE_ONE_SIGMA, 0.60),
    (SetupType.SKEW_STRUCTURE, Direction.SHORT, OUTSIDE_ONE_SIGMA, 0.60),
    (SetupType.EVENT_DIRECTIONAL_LONG, Direction.LONG, ABOVE_SPOT, 0.55),
    (SetupType.EVENT_DIRECTIONAL_PUT, Direction.SHORT, BELOW_SPOT, 0.45),
    (SetupType.EVENT_DIRECTIONAL_VERTICAL, Direction.LONG, ABOVE_SPOT, 0.55),
    (SetupType.POSITIONAL_LONG, Direction.LONG, ABOVE_SPOT, 0.55),
    (SetupType.BORROW_DEPENDENT_SHORT, Direction.SHORT, BELOW_SPOT, 0.45),
    (SetupType.WATCHLIST_NO_TRADE, Direction.LONG, ABOVE_SPOT, 0.55),
]


def test_thesis_band_cases_cover_every_setup_type() -> None:
    assert {setup_type for setup_type, *_ in THESIS_CASES} == set(SetupType)


@pytest.mark.parametrize(
    ("setup_type", "direction", "expected_label", "expected_probability"),
    THESIS_CASES,
)
def test_thesis_band_maps_every_setup_type(
    setup_type: SetupType,
    direction: Direction,
    expected_label: str,
    expected_probability: float,
) -> None:
    setup = make_setup(
        setup_type,
        direction=direction,
        table=make_table(below=0.25, within=0.40, above=0.35),
    )

    label, probability = thesis_band(setup)

    assert label == expected_label
    assert probability == pytest.approx(expected_probability)


def test_event_directional_vertical_maps_short_direction_to_downside_probability() -> None:
    setup = make_setup(
        SetupType.EVENT_DIRECTIONAL_VERTICAL,
        direction=Direction.SHORT,
        table=make_table(below=0.25, within=0.40, above=0.35),
    )

    assert thesis_band(setup) == (BELOW_SPOT, pytest.approx(0.45))


@pytest.mark.parametrize(
    ("direction", "expected_label", "expected_probability"),
    [
        (Direction.LONG, ABOVE_SPOT, 0.55),
        (Direction.SHORT, BELOW_SPOT, 0.45),
        (Direction.NEUTRAL, WITHIN_ONE_SIGMA, 0.40),
    ],
)
def test_watchlist_no_trade_uses_direction_fallback(
    direction: Direction,
    expected_label: str,
    expected_probability: float,
) -> None:
    setup = make_setup(
        SetupType.WATCHLIST_NO_TRADE,
        direction=direction,
        table=make_table(below=0.25, within=0.40, above=0.35),
    )

    assert thesis_band(setup) == (expected_label, pytest.approx(expected_probability))


def test_scenario_table_exposes_directional_side_of_spot_probabilities() -> None:
    table = make_table(below=0.25, within=0.40, above=0.35)

    assert table.probability_above_spot == pytest.approx(0.55)
    assert table.probability_below_spot == pytest.approx(0.45)


def test_directional_grade_uses_side_of_spot_not_one_sigma_tail() -> None:
    setup = make_setup(
        SetupType.EVENT_DIRECTIONAL_LONG,
        direction=Direction.LONG,
        s_cte=1.0,
        table=make_table(below=0.1587, within=0.6826, above=0.1587),
    )

    result = compute_grade(setup)

    assert result.thesis_band == ABOVE_SPOT
    assert result.thesis_probability == pytest.approx(0.50)
    assert result.raw_score == pytest.approx(70.0)
    assert result.letter == "B"


@pytest.mark.parametrize(
    ("s_cte", "direction", "expected"),
    [
        (0.40, Direction.LONG, 0.40),
        (-0.40, Direction.LONG, 0.0),
        (0.0, Direction.LONG, 0.0),
        (-0.40, Direction.SHORT, 0.40),
        (0.40, Direction.SHORT, 0.0),
        (0.0, Direction.SHORT, 0.0),
        (0.0, Direction.NEUTRAL, 1.0),
        (0.149, Direction.NEUTRAL, 1.0),
        (0.15, Direction.NEUTRAL, 0.0),
        (-0.15, Direction.NEUTRAL, 0.0),
    ],
)
def test_alignment_sign_logic_and_neutral_band(
    s_cte: float,
    direction: Direction,
    expected: float,
) -> None:
    assert alignment(s_cte, direction) == pytest.approx(expected)


def test_compute_grade_applies_divergence_and_crowding_penalties() -> None:
    setup = make_setup(
        s_cte=0.8,
        table=make_table(
            below=0.20,
            within=0.0,
            above=0.80,
            diverging_labels=("1 to 2 sigma up",),
        ),
    )

    result = compute_grade(setup, confidence_multiplier=0.5)

    assert result.raw_score == pytest.approx(80.0)
    assert result.penalties == ["divergence_penalty", "crowding_penalty"]
    assert result.penalty_total == pytest.approx(20.0)
    assert result.score == pytest.approx(60.0)
    assert result.letter == "C+"


def test_tier_c_high_probability_and_alignment_grades_no_better_than_c() -> None:
    setup = make_setup(
        tier=ConfidenceTier.C,
        s_cte=0.9,
        table=make_table(below=0.05, within=0.0, above=0.95),
    )

    result = compute_grade(setup)

    assert result.score == pytest.approx(57.0)
    assert result.letter == "C"


def test_missing_probability_returns_unscored_result_with_reason() -> None:
    setup = StubSetup(
        setup_type=SetupType.EVENT_DIRECTIONAL_LONG,
        direction=Direction.LONG,
        tier=ConfidenceTier.A,
        s_cte=0.9,
        scenario_table=None,
    )

    result = compute_grade(setup)

    assert result.score is None
    assert result.letter is None
    assert result.thesis_band == ABOVE_SPOT
    assert result.thesis_probability is None
    assert result.penalties == []
    assert result.reasons == [NO_SCENARIO_TABLE]
