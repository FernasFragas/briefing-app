from __future__ import annotations

from dataclasses import dataclass

import pytest

from briefing_app.config import ReportGradingSettings
from briefing_app.dashboard.grading import (
    ABOVE_SPOT,
    BELOW_SPOT,
    DIRECTIONAL_FULL_CONVICTION,
    NO_SCENARIO_TABLE,
    OUTSIDE_ONE_SIGMA,
    WITHIN_ONE_SIGMA,
    alignment,
    compute_grade,
    thesis_band,
)
from briefing_app.dashboard.models import TradingIdeaRow
from briefing_app.models.candidate import Direction
from briefing_app.models.scoring import ConfidenceTier, NEUTRAL_BAND
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
        # 0.20 * 0.95 + 0.80 * 1.0: s_cte 0.95 is far past the neutral band, so the
        # directional alignment branch saturates at one band.
        (ConfidenceTier.A, 99.0, "A+"),
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
    assert result.probability_weight == pytest.approx(0.20)
    assert result.alignment_weight == pytest.approx(0.80)
    assert result.raw_score == pytest.approx(90.0)
    assert result.letter == "A+"


@pytest.mark.parametrize(
    ("s_cte", "direction", "expected"),
    [
        # Directional alignment is measured against full directional conviction and
        # caps there; the neutral band is where it is only just non-neutral.
        (DIRECTIONAL_FULL_CONVICTION, Direction.LONG, 1.0),
        (0.60, Direction.LONG, 1.0),
        (NEUTRAL_BAND, Direction.LONG, NEUTRAL_BAND / DIRECTIONAL_FULL_CONVICTION),
        (0.20, Direction.LONG, 0.20 / DIRECTIONAL_FULL_CONVICTION),
        (0.010, Direction.LONG, 0.010 / DIRECTIONAL_FULL_CONVICTION),
        (-0.40, Direction.LONG, 0.0),
        (0.0, Direction.LONG, 0.0),
        (-DIRECTIONAL_FULL_CONVICTION, Direction.SHORT, 1.0),
        (-0.60, Direction.SHORT, 1.0),
        (-NEUTRAL_BAND, Direction.SHORT, NEUTRAL_BAND / DIRECTIONAL_FULL_CONVICTION),
        (-0.20, Direction.SHORT, 0.20 / DIRECTIONAL_FULL_CONVICTION),
        (0.40, Direction.SHORT, 0.0),
        (0.0, Direction.SHORT, 0.0),
        (0.0, Direction.NEUTRAL, 1.0),
        (0.075, Direction.NEUTRAL, 0.5),
        (0.149, Direction.NEUTRAL, 1.0 - (0.149 / NEUTRAL_BAND)),
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

    # 0.20 * 0.80 + 0.80 * 1.0: s_cte 0.8 saturates the directional alignment branch.
    assert result.raw_score == pytest.approx(96.0)
    assert result.penalties == ["divergence_penalty", "crowding_penalty"]
    assert result.penalty_total == pytest.approx(20.0)
    assert result.score == pytest.approx(76.0)
    assert result.letter == "B+"


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


# --- G1: published grades must reconcile from published fields ------------------
#
# `TradingIdeaRow` publishes thesis_band, direction, thesis_probability, s_cte, tier
# and grade_penalties; `per_ticker_sections[].gate.confidence_multiplier` publishes the
# crowding input. Everything needed to re-derive `grade_score` is therefore on the
# artifact, and a reader who cannot reproduce a published grade has found a defect --
# either in the formula or in the fields the builder publishes alongside it.
#
# This reconciler is deliberately an independent re-implementation of the documented
# formula rather than a call into `grading`, so it fails when the two drift apart.

PUBLISHED_TIER_CEILINGS = {"A": 100.0, "B": 81.0, "C": 57.0}


def reconcile_published_grade(
    *,
    thesis_band: str,
    direction: str,
    thesis_probability: float,
    s_cte: float,
    tier: str,
    grade_penalties: list[str],
    confidence_multiplier: float = 1.0,
    settings: ReportGradingSettings | None = None,
) -> float:
    """Re-derive a published grade_score from published row fields alone."""

    settings = settings or ReportGradingSettings()

    if thesis_band in (ABOVE_SPOT, BELOW_SPOT):
        # Directional theses are weighted differently from neutral ones: the
        # probability of merely finishing on one side of spot is near 0.50 by
        # construction, so it carries the smaller weight.
        probability_weight = settings.directional_probability_weight
    else:
        probability_weight = settings.probability_weight

    # The alignment branch keys off direction, not band: `beyond +/-1 sigma` covers
    # both a NEUTRAL straddle and a directional skew structure.
    if direction in ("long", "short"):
        aligned = s_cte > 0.0 if direction == "long" else s_cte < 0.0
        support = (
            min(1.0, abs(s_cte) / DIRECTIONAL_FULL_CONVICTION) if aligned else 0.0
        )
    else:
        support = min(max(1.0 - (abs(s_cte) / NEUTRAL_BAND), 0.0), 1.0)

    raw_score = 100.0 * (
        probability_weight * thesis_probability
        + (1.0 - probability_weight) * support
    )

    penalty_total = 0.0
    if "divergence_penalty" in grade_penalties:
        penalty_total += settings.divergence_penalty
    if "crowding_penalty" in grade_penalties:
        penalty_total += settings.crowding_penalty_scale * (1.0 - confidence_multiplier)

    ceiling = PUBLISHED_TIER_CEILINGS[tier]
    return round(min(max(raw_score - penalty_total, 0.0), ceiling), 2)


RECONCILIATION_CASES = [
    # (setup_type, direction, s_cte, tier, above, within, confidence_multiplier,
    #  diverging_labels)
    (SetupType.EVENT_DIRECTIONAL_LONG, Direction.LONG, 0.010, ConfidenceTier.A, 0.30, 0.50, 1.0, ()),
    (SetupType.EVENT_DIRECTIONAL_LONG, Direction.LONG, 0.317, ConfidenceTier.A, 0.20, 0.30, 1.0, ()),
    # S_CTE sign contradicting the direction: alignment collapses to zero.
    (SetupType.EVENT_DIRECTIONAL_LONG, Direction.LONG, -0.010, ConfidenceTier.A, 0.30, 0.20, 1.0, ()),
    (SetupType.EVENT_DIRECTIONAL_PUT, Direction.SHORT, -0.213, ConfidenceTier.B, 0.20, 0.30, 1.0, ()),
    (SetupType.EVENT_DIRECTIONAL_PUT, Direction.SHORT, 0.213, ConfidenceTier.A, 0.20, 0.30, 1.0, ()),
    (SetupType.EVENT_DIRECTIONAL_VERTICAL, Direction.LONG, 0.096, ConfidenceTier.A, 0.30, 0.40, 0.5, ()),
    (SetupType.EVENT_DIRECTIONAL_VERTICAL, Direction.SHORT, -0.096, ConfidenceTier.C, 0.30, 0.40, 1.0, ()),
    # Neutral band, including a row sitting exactly on and beyond the band edge.
    (SetupType.WATCHLIST_NO_TRADE, Direction.NEUTRAL, -0.007, ConfidenceTier.A, 0.20, 0.76, 1.0, ()),
    (SetupType.WATCHLIST_NO_TRADE, Direction.NEUTRAL, 0.150, ConfidenceTier.A, 0.20, 0.68, 1.0, ()),
    (SetupType.WATCHLIST_NO_TRADE, Direction.NEUTRAL, 0.223, ConfidenceTier.B, 0.20, 0.68, 1.0, ()),
    (SetupType.SHORT_PREMIUM_IRON_CONDOR, Direction.NEUTRAL, 0.074, ConfidenceTier.A, 0.20, 0.65, 1.0, ()),
    # Penalised rows: divergence, crowding, and both at once.
    (
        SetupType.EVENT_DIRECTIONAL_LONG, Direction.LONG, 0.070, ConfidenceTier.A,
        0.30, 0.20, 1.0, ("1 to 2 sigma up",),
    ),
    (
        SetupType.EVENT_DIRECTIONAL_LONG, Direction.LONG, 0.163, ConfidenceTier.A,
        0.30, 0.20, 0.5, (),
    ),
    (
        SetupType.EVENT_DIRECTIONAL_LONG, Direction.LONG, 0.086, ConfidenceTier.A,
        0.30, 0.20, 0.25, ("within 1 sigma",),
    ),
    # `beyond +/-1 sigma`: one band, three directions. These reconcile only because
    # `direction` is published -- the band alone cannot pick the alignment branch.
    (SetupType.LONG_PREMIUM_STRADDLE, Direction.NEUTRAL, 0.100, ConfidenceTier.A, 0.30, 0.40, 1.0, ()),
    (SetupType.SKEW_STRUCTURE, Direction.SHORT, -0.100, ConfidenceTier.A, 0.30, 0.40, 1.0, ()),
    (SetupType.SKEW_STRUCTURE, Direction.LONG, 0.100, ConfidenceTier.A, 0.30, 0.40, 1.0, ()),
]


@pytest.mark.parametrize(
    (
        "setup_type",
        "direction",
        "s_cte",
        "tier",
        "above",
        "within",
        "confidence_multiplier",
        "diverging_labels",
    ),
    RECONCILIATION_CASES,
)
def test_published_grade_reconciles_from_published_fields(
    setup_type: SetupType,
    direction: Direction,
    s_cte: float,
    tier: ConfidenceTier,
    above: float,
    within: float,
    confidence_multiplier: float,
    diverging_labels: tuple[str, ...],
) -> None:
    setup = make_setup(
        setup_type,
        direction=direction,
        tier=tier,
        s_cte=s_cte,
        table=make_table(
            below=round(1.0 - above - within, 6),
            within=within,
            above=above,
            diverging_labels=diverging_labels,
        ),
    )

    result = compute_grade(setup, confidence_multiplier=confidence_multiplier)

    assert result.score is not None
    assert result.thesis_probability is not None
    reconciled = reconcile_published_grade(
        thesis_band=result.thesis_band,
        # build.py publishes `setup.direction`, the same value compute_grade branched on.
        direction=direction.value,
        thesis_probability=result.thesis_probability,
        # build.py publishes `setup.s_cte`, the same value compute_grade consumed.
        s_cte=s_cte,
        tier=tier.value,
        grade_penalties=result.penalties,
        confidence_multiplier=confidence_multiplier,
    )
    assert reconciled == pytest.approx(result.score, abs=0.01), (
        f"{setup_type.value} {direction.value} s_cte={s_cte} did not reconcile: "
        f"published {result.score}, recomputed {reconciled}"
    )


def test_every_reconciliation_case_reconciles_with_zero_unexplained_rows() -> None:
    unexplained: list[str] = []
    for (
        setup_type,
        direction,
        s_cte,
        tier,
        above,
        within,
        confidence_multiplier,
        diverging_labels,
    ) in RECONCILIATION_CASES:
        setup = make_setup(
            setup_type,
            direction=direction,
            tier=tier,
            s_cte=s_cte,
            table=make_table(
                below=round(1.0 - above - within, 6),
                within=within,
                above=above,
                diverging_labels=diverging_labels,
            ),
        )
        result = compute_grade(setup, confidence_multiplier=confidence_multiplier)
        assert result.score is not None and result.thesis_probability is not None
        reconciled = reconcile_published_grade(
            thesis_band=result.thesis_band,
            direction=direction.value,
            thesis_probability=result.thesis_probability,
            s_cte=s_cte,
            tier=tier.value,
            grade_penalties=result.penalties,
            confidence_multiplier=confidence_multiplier,
        )
        if abs(reconciled - result.score) > 0.01:
            unexplained.append(
                f"{setup_type.value}/{direction.value} s_cte={s_cte}: "
                f"published {result.score} vs recomputed {reconciled}"
            )

    assert unexplained == []


def test_directional_thesis_uses_its_own_probability_weight() -> None:
    """The 0.60/0.40 split is neutral-only; directional theses use 0.20/0.80.

    Reconciling a directional row against 0.60/0.40 over-predicts it, which is what
    `_effective_weights` in dashboard/grading.py exists to do. Pin the split so a
    silent change to it cannot pass as a rounding difference.
    """

    settings = ReportGradingSettings()
    directional = compute_grade(
        make_setup(
            SetupType.EVENT_DIRECTIONAL_LONG,
            direction=Direction.LONG,
            s_cte=0.010,
            table=make_table(below=0.30, within=0.20, above=0.50),
        )
    )
    neutral = compute_grade(
        make_setup(
            SetupType.SHORT_PREMIUM_IRON_CONDOR,
            direction=Direction.NEUTRAL,
            s_cte=0.010,
            table=make_table(below=0.30, within=0.20, above=0.50),
        )
    )

    assert directional.probability_weight == pytest.approx(
        settings.directional_probability_weight
    )
    assert directional.alignment_weight == pytest.approx(
        1.0 - settings.directional_probability_weight
    )
    assert neutral.probability_weight == pytest.approx(settings.probability_weight)
    assert neutral.alignment_weight == pytest.approx(settings.alignment_weight)


def test_grade_penalties_accounts_for_the_whole_penalty_total() -> None:
    """Every point deducted must be named in `grade_penalties`.

    `grade_penalties` is the only penalty evidence on a published row, so an applied
    penalty missing from the list makes the row irreconcilable for a reader.
    """

    settings = ReportGradingSettings()
    cases = [
        (1.0, ()),
        (0.5, ()),
        (0.0, ()),
        (1.0, ("1 to 2 sigma up",)),
        (0.5, ("1 to 2 sigma up",)),
    ]
    for confidence_multiplier, diverging_labels in cases:
        setup = make_setup(
            SetupType.EVENT_DIRECTIONAL_LONG,
            direction=Direction.LONG,
            s_cte=0.10,
            table=make_table(
                below=0.20, within=0.30, above=0.50, diverging_labels=diverging_labels
            ),
        )
        result = compute_grade(setup, confidence_multiplier=confidence_multiplier)

        named_total = 0.0
        if "divergence_penalty" in result.penalties:
            named_total += settings.divergence_penalty
        if "crowding_penalty" in result.penalties:
            named_total += settings.crowding_penalty_scale * (1.0 - confidence_multiplier)

        assert named_total == pytest.approx(result.penalty_total, abs=0.01), (
            f"grade_penalties {result.penalties} account for {named_total} of "
            f"{result.penalty_total} deducted points"
        )
        assert result.penalty_total > 0.0 or result.penalties == []


def test_beyond_one_sigma_band_alone_does_not_determine_alignment_branch() -> None:
    """The outside band needs `direction`, and `TradingIdeaRow` now publishes it.

    For `above spot` / `below spot` / `within 1 sigma` the thesis band names the
    direction, so a published row reconciles from the band alone. A `beyond +/-1 sigma`
    row does not: a skew structure carries a real LONG or SHORT direction while
    publishing the same band as a NEUTRAL straddle, and `alignment()` keys off
    direction, not band. Two such rows have identical band, probability, s_cte and tier
    yet grade differently.

    `direction` on `TradingIdeaRow` is what closes the gap: the second half of this
    test reconciles both rows from published fields, which is impossible without it.
    """

    table = make_table(below=0.30, within=0.40, above=0.30)
    neutral = compute_grade(
        make_setup(
            SetupType.LONG_PREMIUM_STRADDLE,
            direction=Direction.NEUTRAL,
            s_cte=0.10,
            table=table,
        )
    )
    short = compute_grade(
        make_setup(
            SetupType.SKEW_STRUCTURE,
            direction=Direction.SHORT,
            s_cte=0.10,
            table=table,
        )
    )

    assert neutral.thesis_band == short.thesis_band == OUTSIDE_ONE_SIGMA
    assert neutral.thesis_probability == pytest.approx(short.thesis_probability)
    assert neutral.score != short.score

    # `direction` is a published field on `TradingIdeaRow`, so a reader holding only the
    # document can pick the right alignment branch and reproduce both grades.
    assert "direction" in TradingIdeaRow.model_fields
    for grade, direction in ((neutral, Direction.NEUTRAL), (short, Direction.SHORT)):
        assert grade.score is not None and grade.thesis_probability is not None
        reconciled = reconcile_published_grade(
            thesis_band=grade.thesis_band,
            direction=direction.value,
            thesis_probability=grade.thesis_probability,
            s_cte=0.10,
            tier="A",
            grade_penalties=grade.penalties,
        )
        assert reconciled == pytest.approx(grade.score, abs=0.01)


def test_trading_idea_rows_publish_the_direction_the_grade_used() -> None:
    """The builder must publish `setup.direction`, not leave the field defaulted."""

    row = TradingIdeaRow(
        ticker="TEST",
        setup_type=SetupType.SKEW_STRUCTURE.value,
        direction=Direction.SHORT.value,
        thesis_band=OUTSIDE_ONE_SIGMA,
        status="TRADEABLE",
    )

    assert row.model_dump(mode="json")["direction"] == "short"


# --- G2: both alignment branches share one scale --------------------------------


def test_aligned_directional_row_never_grades_below_a_neutral_row_at_the_band_edge() -> None:
    """A directional idea with full S_CTE conviction must not lose to a dead neutral one.

    A neutral row sitting on the neutral-band edge has zero alignment support left:
    S_CTE has moved as far as the band allows before the row stops being neutral. A
    directional row at full conviction has maximal support. Swept across the full
    probability grid and both tiers, the directional row must grade at least as well.

    This is the regression that motivated G2: while the directional branch scored raw
    |S_CTE| it could not clear about a third of its alignment weight, so every neutral
    row outranked every directional row with an empty corridor between the two blocks.

    G2b moved the directional row of this comparison from ``NEUTRAL_BAND`` to
    ``DIRECTIONAL_FULL_CONVICTION``. The band edge is the point of *minimum*
    directional conviction, so a directional row sitting on it is deliberately no
    longer maximal, and it may now legitimately grade below a high-probability neutral
    row -- that interleaving is the point of G2b, not a regression of G2. The invariant
    G2 actually protects is the one pinned here: at full conviction the directional
    branch takes its whole alignment weight.
    """

    probabilities = [round(0.05 * step, 2) for step in range(1, 20)]
    failures: list[str] = []

    for tier in (ConfidenceTier.A, ConfidenceTier.B):
        for neutral_probability in probabilities:
            neutral = compute_grade(
                make_setup(
                    SetupType.SHORT_PREMIUM_IRON_CONDOR,
                    direction=Direction.NEUTRAL,
                    tier=tier,
                    # Exactly on the band edge: no alignment support remains.
                    s_cte=NEUTRAL_BAND,  # neutral branch: zero support
                    table=make_table(
                        below=round((1.0 - neutral_probability) / 2, 6),
                        within=neutral_probability,
                        above=round((1.0 - neutral_probability) / 2, 6),
                    ),
                )
            )
            for directional_probability in probabilities:
                directional = compute_grade(
                    make_setup(
                        SetupType.EVENT_DIRECTIONAL_LONG,
                        direction=Direction.LONG,
                        tier=tier,
                        # Full directional conviction, in the trade's direction.
                        s_cte=DIRECTIONAL_FULL_CONVICTION,
                        table=make_table(
                            below=round(1.0 - directional_probability, 6),
                            within=0.0,
                            above=directional_probability,
                        ),
                    )
                )
                assert neutral.score is not None and directional.score is not None
                if directional.score < neutral.score:
                    failures.append(
                        f"tier {tier.value}: directional P={directional_probability} "
                        f"graded {directional.score} below neutral "
                        f"P={neutral_probability} at {neutral.score}"
                    )

    assert failures == []


def test_both_alignment_branches_span_the_same_unit_range() -> None:
    """Neutral and directional alignment must reach the same floor and ceiling."""

    directional_long = [
        alignment(s_cte, Direction.LONG)
        for s_cte in (0.0, 0.05, 0.10, NEUTRAL_BAND, 0.50, 1.0)
    ]
    directional_short = [
        alignment(-s_cte, Direction.SHORT)
        for s_cte in (0.0, 0.05, 0.10, NEUTRAL_BAND, 0.50, 1.0)
    ]
    neutral = [
        alignment(s_cte, Direction.NEUTRAL)
        for s_cte in (0.0, 0.05, 0.10, NEUTRAL_BAND, 0.50, 1.0)
    ]

    for values in (directional_long, directional_short, neutral):
        assert min(values) == pytest.approx(0.0)
        assert max(values) == pytest.approx(1.0)
        assert all(0.0 <= value <= 1.0 for value in values)


def test_directional_alignment_is_monotonic_in_conviction_units() -> None:
    """Alignment rises with S_CTE up to full conviction, then holds at one."""

    steps = int(round(DIRECTIONAL_FULL_CONVICTION * 100))
    below_full = [alignment(step / 100, Direction.LONG) for step in range(0, steps + 1)]
    assert below_full == sorted(below_full)
    assert below_full[-1] == pytest.approx(1.0)
    # Expressed against the constant, so re-tuning the denominator does not break the
    # property this test exists to pin.
    assert alignment(0.30, Direction.LONG) == pytest.approx(
        min(1.0, 0.30 / DIRECTIONAL_FULL_CONVICTION)
    )
    assert alignment(3.00, Direction.LONG) == pytest.approx(1.0)


# --- G2b: the directional branch must not saturate at the neutral edge ----------


def test_directional_alignment_does_not_saturate_at_the_neutral_band_edge() -> None:
    """`NEUTRAL_BAND` is minimum directional conviction, not maximum.

    Dividing the directional branch by `NEUTRAL_BAND` made every row past 0.15 score
    identically, so with the 0.80 directional alignment weight a merely-non-neutral
    idea was indistinguishable from a strongly supported one. Four of the twelve
    directional rows on the 2026-09-04 live run sit past 0.15 (ORCL 0.317, GM 0.249,
    INTC 0.213, AAPL 0.163), so this was live, not hypothetical.
    """

    edge = alignment(NEUTRAL_BAND, Direction.LONG)
    strong = alignment(0.30, Direction.LONG)

    assert edge < strong
    assert edge < 1.0
    assert strong < 1.0


def test_no_live_observed_s_cte_saturates_the_directional_branch() -> None:
    """The observed live |S_CTE| range must stay strictly ordered, with headroom.

    The largest |S_CTE| seen on a live run is about 0.32. `DIRECTIONAL_FULL_CONVICTION`
    is set above it so no real row clips, and alignment stays strictly increasing.
    """

    observed = [
        0.00965, 0.07026, 0.07039, 0.08627, 0.09218, 0.09617,
        0.10999, 0.16340, 0.21347, 0.24919, 0.31687,
    ]
    scores = [alignment(value, Direction.LONG) for value in observed]

    assert max(observed) < DIRECTIONAL_FULL_CONVICTION
    assert scores == sorted(scores)
    assert len(set(scores)) == len(scores), "two live rows share an alignment score"
    assert max(scores) < 1.0


def test_directional_grades_differ_between_band_edge_and_double_the_band() -> None:
    """A row at |S_CTE| = 0.15 must not grade the same as one at 0.30."""

    table = make_table(below=0.30, within=0.20, above=0.50)
    edge = compute_grade(
        make_setup(
            SetupType.EVENT_DIRECTIONAL_LONG,
            direction=Direction.LONG,
            s_cte=0.15,
            table=table,
        )
    )
    strong = compute_grade(
        make_setup(
            SetupType.EVENT_DIRECTIONAL_LONG,
            direction=Direction.LONG,
            s_cte=0.30,
            table=table,
        )
    )

    assert edge.score is not None and strong.score is not None
    assert edge.score < strong.score
    # 0.80 alignment weight over (0.30 - 0.15) of a conviction unit.
    expected_gap = 100 * 0.80 * (
        min(1.0, 0.30 / DIRECTIONAL_FULL_CONVICTION)
        - min(1.0, 0.15 / DIRECTIONAL_FULL_CONVICTION)
    )
    assert strong.score - edge.score == pytest.approx(expected_gap, abs=0.01)
