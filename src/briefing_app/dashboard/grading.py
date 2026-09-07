"""Pure grade computation for dashboard trading ideas.

Grades only combine values already computed upstream: thesis-band probability,
S_CTE, confidence tier, and gate confidence. This module performs no I/O and does
not build, render, or mutate dashboard payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from briefing_app.config import ReportGradingSettings
from briefing_app.models.candidate import Direction
from briefing_app.models.scoring import ConfidenceTier, NEUTRAL_BAND
from briefing_app.strategy.models import SetupType
from briefing_app.strategy.scenarios import ScenarioTable


WITHIN_ONE_SIGMA = "within 1 sigma"
ABOVE_ONE_SIGMA = "beyond +1 sigma"
BELOW_ONE_SIGMA = "beyond -1 sigma"
OUTSIDE_ONE_SIGMA = "beyond +/-1 sigma"
ABOVE_SPOT = "above spot"
BELOW_SPOT = "below spot"

NO_SCENARIO_TABLE = "NO_SCENARIO_TABLE"
NO_THESIS_PROBABILITY = "NO_THESIS_PROBABILITY"
NO_S_CTE = "NO_S_CTE"

#: |S_CTE| at which a directional setup is treated as fully convicted.
#:
#: NEUTRAL_BAND is the threshold at which a signal *stops being neutral*: it marks the
#: point of *minimum* directional conviction, not maximum. Using it as the denominator
#: of the directional branch was a category error -- it saturated alignment at
#: |S_CTE| >= 0.15, so with the 0.80 directional alignment weight every row past the
#: band edge scored >= 80 raw whatever its probability, and strong directional ideas
#: became indistinguishable from merely non-neutral ones.
#:
#: 0.35 is chosen from observed live data: |S_CTE| tops out at 0.317 on real runs, so
#: 0.35 is the *smallest* denominator that leaves no live row saturating. Smaller was
#: tested and rejected -- 0.25 and 0.30 both still pin the strongest row at alignment
#: 1.0. Larger was tested and rejected too: the denominator only moves the top of the
#: directional range, and every value depresses the tail, so the smallest non-saturating
#: choice is the one that costs the weak rows least.
#:
#: This constant cannot fix the real asymmetry, and is not expected to. Directional raw
#: is `10 + 80 * alignment` because P(above spot) is pinned near 0.50 by construction and
#: carries only 0.20 weight, while a neutral row draws 30-52 points from a P that varies
#: 0.50-0.86. That 20-42 point head start is structural.
#:
#: An earlier version of this note proposed fixing it with "probability of reaching the
#: setup's target". **That is disproved -- do not attempt it**
#: (`docs/alternatives/directional-probability.md`, 2026-09-06). No target exists anywhere
#: in `strategy/`, and every buildable alternative was measured and rejected: a
#: distribution centred on spot cannot express direction, so no probability the scenario
#: table can produce carries directional information. Directional P was measured at spread
#: 0.049 across two runs, and *exactly* 0.5000 on every `measured_sigma` row.
#:
#: Two decisions came out of that search and are filed rather than applied, both in
#: `HANDOFF.md`: setting `directional_probability_weight` to 0.0 so alignment carries the
#: branch alone, and the larger finding that the real defect is on the *neutral* side --
#: a neutral row is paid `0.60 * 0.683 = 41` points for the definition of the band it is
#: measured over, which is a tautology, not evidence.
DIRECTIONAL_FULL_CONVICTION: float = 0.35

_BELOW_ROWS = ("below 2 sigma", "1 to 2 sigma down")
_WITHIN_ROWS = ("within 1 sigma",)
_ABOVE_ROWS = ("1 to 2 sigma up", "above 2 sigma")
_OUTSIDE_ROWS = (*_BELOW_ROWS, *_ABOVE_ROWS)
_ABOVE_SPOT_ROWS = (*_WITHIN_ROWS, *_ABOVE_ROWS)
_BELOW_SPOT_ROWS = (*_BELOW_ROWS, *_WITHIN_ROWS)

_TIER_CEILINGS: dict[ConfidenceTier, float] = {
    ConfidenceTier.A: 100.0,
    ConfidenceTier.B: 81.0,
    ConfidenceTier.C: 57.0,
}

_LETTER_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "A+"),
    (82.0, "A"),
    (74.0, "B+"),
    (66.0, "B"),
    (58.0, "C+"),
    (50.0, "C"),
    (35.0, "D"),
    (0.0, "F"),
)


class SetupLike(Protocol):
    setup_type: SetupType | str
    direction: Direction | str
    tier: ConfidenceTier | str
    s_cte: float | None
    scenario_table: ScenarioTable | None


@dataclass(frozen=True)
class GradeResult:
    """Computed grade plus audit fields needed by the report builder."""

    score: float | None
    letter: str | None
    penalties: list[str]
    thesis_band: str
    thesis_probability: float | None
    alignment: float | None
    raw_score: float | None
    penalty_total: float
    tier_ceiling: float | None
    probability_weight: float | None
    alignment_weight: float | None
    reasons: list[str]


@dataclass(frozen=True)
class _ThesisSelection:
    label: str
    probability: float | None
    row_labels: tuple[str, ...]
    has_scenario_table: bool


def thesis_band(setup: SetupLike) -> tuple[str, float | None]:
    """Return the setup's named thesis band and its probability when available."""

    thesis = _select_thesis_band(setup)
    return thesis.label, thesis.probability


def alignment(s_cte: float, direction: Direction | str) -> float:
    """Return the S_CTE alignment contribution for the setup direction.

    Both branches return a unit-interval support score, but each is measured against
    the reference point that is meaningful for its own thesis:

    * A directional setup scores how far its S_CTE has travelled from zero towards
      ``DIRECTIONAL_FULL_CONVICTION``, and 0.0 when the S_CTE sign contradicts the
      direction. Full conviction is the ceiling, so alignment keeps discriminating
      between a barely-non-neutral row and a strongly supported one.
    * A neutral setup scores the distance it still has left before ``NEUTRAL_BAND``,
      which for a neutral thesis genuinely is the point where support reaches zero:
      past the band edge the row has stopped being neutral. That branch is unchanged.

    Both branches must reach the same floor and ceiling. Scoring the directional branch
    as the raw S_CTE magnitude capped its contribution at roughly a third of the
    alignment weight while the neutral branch could take all of it, which sorted every
    neutral row above every directional one regardless of how strong the directional
    evidence was. Dividing it by ``NEUTRAL_BAND`` instead over-corrected: it saturated
    at the neutral edge, the point of *minimum* directional conviction.
    """

    direction = _coerce_direction(direction)
    if direction is Direction.LONG:
        return _conviction_units(s_cte) if s_cte > 0.0 else 0.0
    if direction is Direction.SHORT:
        return _conviction_units(s_cte) if s_cte < 0.0 else 0.0
    return _bounded_probability(1.0 - (abs(s_cte) / NEUTRAL_BAND))


def _conviction_units(s_cte: float) -> float:
    """Return |S_CTE| as a fraction of full directional conviction, capped at one."""

    return min(1.0, abs(s_cte) / DIRECTIONAL_FULL_CONVICTION)


def letter_for_score(score: float) -> str:
    """Map a clamped numeric score to the dashboard letter band."""

    for boundary, letter in _LETTER_BANDS:
        if score >= boundary:
            return letter
    return "F"


def compute_grade(
    setup: SetupLike,
    *,
    confidence_multiplier: float = 1.0,
    settings: ReportGradingSettings | None = None,
) -> GradeResult:
    """Compute a dashboard grade for a scored setup.

    A missing thesis probability produces an unscored result. The grade is never
    inferred from S_CTE alone because the report names `P(thesis band)` as an input.
    """

    grading_settings = settings or ReportGradingSettings()
    thesis = _select_thesis_band(setup)
    if thesis.probability is None:
        reason = NO_SCENARIO_TABLE if not thesis.has_scenario_table else NO_THESIS_PROBABILITY
        return GradeResult(
            score=None,
            letter=None,
            penalties=[],
            thesis_band=thesis.label,
            thesis_probability=None,
            alignment=None,
            raw_score=None,
            penalty_total=0.0,
            tier_ceiling=None,
            probability_weight=None,
            alignment_weight=None,
            reasons=[reason],
        )

    s_cte = setup.s_cte
    if s_cte is None:
        return GradeResult(
            score=None,
            letter=None,
            penalties=[],
            thesis_band=thesis.label,
            thesis_probability=thesis.probability,
            alignment=None,
            raw_score=None,
            penalty_total=0.0,
            tier_ceiling=None,
            probability_weight=None,
            alignment_weight=None,
            reasons=[NO_S_CTE],
        )

    _validate_unit_interval("confidence_multiplier", confidence_multiplier)
    tier = _coerce_tier(setup.tier)
    alignment_score = alignment(s_cte, setup.direction)
    probability_weight, alignment_weight = _effective_weights(grading_settings, thesis)
    raw_score = 100.0 * (
        probability_weight * thesis.probability
        + alignment_weight * alignment_score
    )

    penalties: list[str] = []
    penalty_total = 0.0
    if setup.scenario_table is not None and _thesis_diverges(
        setup.scenario_table, thesis.row_labels
    ):
        penalties.append("divergence_penalty")
        penalty_total += grading_settings.divergence_penalty

    crowding_penalty = grading_settings.crowding_penalty_scale * (
        1.0 - confidence_multiplier
    )
    if crowding_penalty > 0.0:
        penalties.append("crowding_penalty")
        penalty_total += crowding_penalty

    tier_ceiling = _TIER_CEILINGS[tier]
    score = round(min(max(raw_score - penalty_total, 0.0), tier_ceiling), 2)
    return GradeResult(
        score=score,
        letter=letter_for_score(score),
        penalties=penalties,
        thesis_band=thesis.label,
        thesis_probability=thesis.probability,
        alignment=alignment_score,
        raw_score=round(raw_score, 2),
        penalty_total=round(penalty_total, 2),
        tier_ceiling=tier_ceiling,
        probability_weight=probability_weight,
        alignment_weight=alignment_weight,
        reasons=[],
    )


def _effective_weights(
    settings: ReportGradingSettings,
    thesis: _ThesisSelection,
) -> tuple[float, float]:
    if thesis.label in (ABOVE_SPOT, BELOW_SPOT):
        probability_weight = settings.directional_probability_weight
        return probability_weight, 1.0 - probability_weight
    return settings.probability_weight, settings.alignment_weight


def _select_thesis_band(setup: SetupLike) -> _ThesisSelection:
    setup_type = _coerce_setup_type(setup.setup_type)
    direction = _coerce_direction(setup.direction)
    table = setup.scenario_table

    if setup_type is SetupType.SHORT_PREMIUM_IRON_CONDOR:
        return _selection(
            WITHIN_ONE_SIGMA,
            table,
            lambda scenario: scenario.probability_in_one_sigma,
            _WITHIN_ROWS,
        )
    if setup_type in (
        SetupType.LONG_PREMIUM_STRADDLE,
        SetupType.LONG_PREMIUM_CALENDAR,
        SetupType.SKEW_STRUCTURE,
    ):
        return _selection(
            OUTSIDE_ONE_SIGMA,
            table,
            lambda scenario: 1.0 - scenario.probability_in_one_sigma,
            _OUTSIDE_ROWS,
        )
    if setup_type in (
        SetupType.EVENT_DIRECTIONAL_LONG,
        SetupType.POSITIONAL_LONG,
    ):
        return _above_spot_selection(table)
    if setup_type in (
        SetupType.EVENT_DIRECTIONAL_PUT,
        SetupType.BORROW_DEPENDENT_SHORT,
    ):
        return _below_spot_selection(table)
    if setup_type in (
        SetupType.EVENT_DIRECTIONAL_VERTICAL,
        SetupType.WATCHLIST_NO_TRADE,
    ):
        if direction is Direction.LONG:
            return _above_spot_selection(table)
        if direction is Direction.SHORT:
            return _below_spot_selection(table)
        return _selection(
            WITHIN_ONE_SIGMA,
            table,
            lambda scenario: scenario.probability_in_one_sigma,
            _WITHIN_ROWS,
        )

    raise ValueError(f"unsupported setup_type: {setup.setup_type!r}")


def _above_spot_selection(table: ScenarioTable | None) -> _ThesisSelection:
    return _selection(
        ABOVE_SPOT,
        table,
        lambda scenario: scenario.probability_above_spot,
        _ABOVE_SPOT_ROWS,
    )


def _below_spot_selection(table: ScenarioTable | None) -> _ThesisSelection:
    return _selection(
        BELOW_SPOT,
        table,
        lambda scenario: scenario.probability_below_spot,
        _BELOW_SPOT_ROWS,
    )


def _selection(
    label: str,
    table: ScenarioTable | None,
    probability_getter: Callable[[ScenarioTable], float],
    row_labels: tuple[str, ...],
) -> _ThesisSelection:
    probability = (
        None
        if table is None
        else _bounded_probability(probability_getter(table))
    )
    return _ThesisSelection(
        label=label,
        probability=probability,
        row_labels=row_labels,
        has_scenario_table=table is not None,
    )


def _thesis_diverges(table: ScenarioTable, row_labels: tuple[str, ...]) -> bool:
    thesis_labels = set(row_labels)
    return any(row.label in thesis_labels for row in table.diverging_rows)


def _bounded_probability(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _validate_unit_interval(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")


def _coerce_direction(value: Direction | str) -> Direction:
    if isinstance(value, Direction):
        return value
    return Direction(value)


def _coerce_tier(value: ConfidenceTier | str) -> ConfidenceTier:
    if isinstance(value, ConfidenceTier):
        return value
    return ConfidenceTier(str(value).strip().upper())


def _coerce_setup_type(value: SetupType | str) -> SetupType:
    if isinstance(value, SetupType):
        return value
    key = str(value).strip()
    normalised = key.lower().replace("-", "_").replace(" ", "_")
    for member in SetupType:
        if normalised in (member.value, member.name.lower()):
            return member
    raise ValueError(f"unsupported setup_type: {value!r}")
