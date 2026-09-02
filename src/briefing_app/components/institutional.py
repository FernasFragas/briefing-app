"""`S_F` - institutional flow.

US: 13F position changes, split by cohort. An active hedge fund adding is a decision; a
passive index aggregator adding is usually mechanical tracking of an index it does not
choose. Blending the two produces a flow signal that mostly measures fund inflows.

EU: 13F does not exist. Transparency Directive major-holdings notifications stand in,
and they are event signals - a holder crossed a disclosure threshold on a date - not a
quarterly accumulation wave. Scored and labelled as such, never as a US-style delta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type, datetime
from typing import Sequence

from briefing_app.components.base import (
    INSTITUTIONAL,
    QUALITY_MANUAL,
    QUALITY_PRIMARY,
    STATUS_PARTIAL,
    STATUS_VERIFIED,
    ComponentResult,
    SubScore,
    build_evidence_rows,
    clamp,
    combine_sub_scores,
    evidence_from_sub_scores,
    is_stale,
    squash,
    to_datetime,
    unavailable_component,
    worst_quality,
)
from briefing_app.models.candidate import Geography
from briefing_app.models.market_data import OwnershipChange

COHORT_ACTIVE = "active"
COHORT_PASSIVE = "passive"
COHORT_SOVEREIGN = "sovereign"

#: How much a cohort's flow says about conviction. Passive tracking is near-mechanical.
COHORT_WEIGHTS: dict[str, float] = {
    COHORT_ACTIVE: 1.0,
    COHORT_SOVEREIGN: 0.6,
    COHORT_PASSIVE: 0.2,
}

#: Name fragments used to classify a holder when the feed does not declare a cohort.
#: Inference is recorded per row so an evidence reader can see it was inferred.
_PASSIVE_NAMES: tuple[str, ...] = (
    "vanguard",
    "blackrock",
    "state street",
    "geode",
    "index",
    "ishares",
    "spdr",
    "northern trust",
    "charles schwab investment",
)
_SOVEREIGN_NAMES: tuple[str, ...] = (
    "norges",
    "sovereign",
    "gic private",
    "abu dhabi",
    "kuwait investment",
    "qatar investment",
    "pension",
    "retirement system",
    "superannuation",
    "calpers",
)

#: A 13F is due 45 days after quarter end, so the latest complete filing can legitimately
#: be about four and a half months old before the next one lands.
US_MAX_AGE_DAYS = 135

#: EU major-holdings notifications are event-driven; a crossing older than a quarter is
#: history, not current flow.
EU_MAX_AGE_DAYS = 90

#: Net share delta, as a share of total reported holdings, that saturates the score.
TURNOVER_SCALE = 0.10


@dataclass(frozen=True)
class CohortFlow:
    """Aggregated flow for one cohort."""

    cohort: str
    holders: int
    shares_held: float
    shares_delta: float
    inferred_holders: int = 0

    @property
    def turnover(self) -> float | None:
        base = self.shares_held - self.shares_delta
        if base <= 0:
            return None
        return self.shares_delta / base


@dataclass(frozen=True)
class OwnershipFlow:
    """The whole 13F pull, split by cohort."""

    cohorts: dict[str, CohortFlow] = field(default_factory=dict)
    latest_as_of: date_type | None = None
    total_shares_held: float = 0.0
    total_shares_delta: float = 0.0
    weighted_delta: float = 0.0
    increases: int = 0
    decreases: int = 0
    inferred_cohorts: int = 0

    @property
    def holder_count(self) -> int:
        return sum(c.holders for c in self.cohorts.values())


def classify_cohort(change: OwnershipChange) -> tuple[str, bool]:
    """Return `(cohort, inferred)`. A declared cohort always wins over a name guess."""
    if change.cohort:
        declared = change.cohort.strip().lower()
        for known in (COHORT_ACTIVE, COHORT_PASSIVE, COHORT_SOVEREIGN):
            if known in declared:
                return known, False
        if "hedge" in declared:
            return COHORT_ACTIVE, False
        if "index" in declared:
            return COHORT_PASSIVE, False

    name = (change.institution or "").strip().lower()
    if any(fragment in name for fragment in _PASSIVE_NAMES):
        return COHORT_PASSIVE, True
    if any(fragment in name for fragment in _SOVEREIGN_NAMES):
        return COHORT_SOVEREIGN, True
    return COHORT_ACTIVE, True


def aggregate_ownership(changes: Sequence[OwnershipChange]) -> OwnershipFlow:
    """Fold 13F rows into per-cohort flow."""
    buckets: dict[str, dict[str, float]] = {}
    latest: date_type | None = None
    increases = decreases = inferred_total = 0

    for change in changes:
        cohort, inferred = classify_cohort(change)
        bucket = buckets.setdefault(
            cohort, {"holders": 0, "shares_held": 0.0, "shares_delta": 0.0, "inferred": 0}
        )
        bucket["holders"] += 1
        bucket["shares_held"] += float(change.shares or 0.0)
        delta = float(change.shares_delta or 0.0)
        bucket["shares_delta"] += delta
        if inferred:
            bucket["inferred"] += 1
            inferred_total += 1
        if delta > 0:
            increases += 1
        elif delta < 0:
            decreases += 1
        latest = change.as_of if latest is None else max(latest, change.as_of)

    cohorts = {
        name: CohortFlow(
            cohort=name,
            holders=int(values["holders"]),
            shares_held=values["shares_held"],
            shares_delta=values["shares_delta"],
            inferred_holders=int(values["inferred"]),
        )
        for name, values in buckets.items()
    }
    weighted = sum(
        flow.shares_delta * COHORT_WEIGHTS.get(name, COHORT_WEIGHTS[COHORT_ACTIVE])
        for name, flow in cohorts.items()
    )
    return OwnershipFlow(
        cohorts=cohorts,
        latest_as_of=latest,
        total_shares_held=sum(c.shares_held for c in cohorts.values()),
        total_shares_delta=sum(c.shares_delta for c in cohorts.values()),
        weighted_delta=weighted,
        increases=increases,
        decreases=decreases,
        inferred_cohorts=inferred_total,
    )


def build_institutional_component(
    *,
    ticker: str,
    geography: Geography | str,
    ownership_changes: Sequence[OwnershipChange] = (),
    run_date: date_type,
    as_of: datetime | None = None,
    max_age_days: int | None = None,
    source: str | None = None,
    source_quality: str = QUALITY_PRIMARY,
    endpoint_or_file: str = "",
    run_id: int | None = None,
) -> ComponentResult:
    """Score `S_F`, or return `n/a` with the reason. Never zero for missing data."""
    geo = Geography(geography)
    clean_ticker = ticker.strip().upper()
    resolved_as_of = to_datetime(as_of or run_date)
    is_eu = not geo.is_us
    bound = max_age_days if max_age_days is not None else (EU_MAX_AGE_DAYS if is_eu else US_MAX_AGE_DAYS)
    resolved_source = source or (
        "Transparency Directive major-holdings notifications" if is_eu else "SEC Form 13F"
    )
    eu_substitutes = (
        (
            "Major-holdings notifications stand in for 13F. They are threshold-crossing "
            "events on a date, not a quarterly accumulation wave, and cover only holders "
            "above the disclosure threshold.",
        )
        if is_eu
        else ()
    )

    if not ownership_changes:
        return unavailable_component(
            component=INSTITUTIONAL,
            ticker=clean_ticker,
            geography=geo,
            as_of=resolved_as_of,
            reason=(
                "no major-holdings notifications available"
                if is_eu
                else "no 13F ownership data available"
            ),
            eu_substitutes=eu_substitutes,
        )

    flow = aggregate_ownership(ownership_changes)
    diagnostics: list[str] = []

    if is_stale(flow.latest_as_of, run_date=run_date, max_age_days=bound):
        latest = flow.latest_as_of.isoformat() if flow.latest_as_of else "unknown"
        return unavailable_component(
            component=INSTITUTIONAL,
            ticker=clean_ticker,
            geography=geo,
            as_of=resolved_as_of,
            reason=(
                f"ownership data as of {latest} is beyond its {bound}-day release "
                "cadence bound; stale ownership is n/a, not neutral"
            ),
            diagnostics=diagnostics,
            eu_substitutes=eu_substitutes,
        )

    if flow.inferred_cohorts:
        diagnostics.append(
            f"{flow.inferred_cohorts} of {flow.holder_count} holders had no declared "
            "cohort and were classified by name."
        )

    if is_eu:
        sub_scores = (_eu_notification_sub_score(ownership_changes, flow),)
        diagnostics.append(
            "EU name: scored from threshold-crossing notifications, not quarterly deltas."
        )
    else:
        sub_scores = (
            _active_flow_sub_score(flow),
            _breadth_sub_score(flow),
            _cohort_mix_sub_score(flow),
        )

    score, weights_used, disclosures = combine_sub_scores(sub_scores)
    diagnostics.extend(disclosures)

    evidence = build_evidence_rows(
        component=INSTITUTIONAL,
        ticker=clean_ticker,
        as_of=resolved_as_of,
        source=resolved_source,
        endpoint_or_file=endpoint_or_file,
        run_id=run_id,
        values={
            "institutional_holders": flow.holder_count,
            "institutional_shares_held": round(flow.total_shares_held, 2),
            "institutional_shares_delta": round(flow.total_shares_delta, 2),
            "institutional_weighted_delta": round(flow.weighted_delta, 2),
            "institutional_increases": flow.increases,
            "institutional_decreases": flow.decreases,
            "institutional_as_of": flow.latest_as_of,
            "institutional_cohorts_inferred": flow.inferred_cohorts or None,
            "s_f": None if score is None else round(score, 4),
        },
        notes={
            "institutional_cohorts_inferred": (
                "Cohort inferred from the holder name because the feed declared none."
            ),
            "s_f": (
                "EU major-holdings substitute; event signal, not accumulation."
                if is_eu
                else None
            ),
        },
    )
    evidence.extend(
        evidence_from_sub_scores(
            INSTITUTIONAL, clean_ticker, resolved_as_of, sub_scores, run_id=run_id
        )
    )

    quality = worst_quality(source_quality, QUALITY_MANUAL) if is_eu else source_quality
    return ComponentResult(
        component=INSTITUTIONAL,
        ticker=clean_ticker,
        as_of=resolved_as_of,
        geography=geo,
        available=score is not None,
        score=score,
        validation_status=STATUS_VERIFIED if score is not None else STATUS_PARTIAL,
        source_quality=quality,
        na_reason=None if score is not None else "no ownership sub-score could be measured",
        sub_scores=sub_scores,
        weights_used=weights_used,
        source_rows=tuple(
            {
                "institution": change.institution,
                "cohort": classify_cohort(change)[0],
                "cohort_inferred": classify_cohort(change)[1],
                "as_of": change.as_of.isoformat(),
                "shares": change.shares,
                "shares_delta": change.shares_delta,
                "percent_delta": change.percent_delta,
                "source": change.source,
            }
            for change in ownership_changes
        ),
        evidence_rows=tuple(evidence),
        diagnostics=tuple(diagnostics),
        eu_substitutes=eu_substitutes,
    )


def _active_flow_sub_score(flow: OwnershipFlow) -> SubScore:
    """Cohort-weighted net share change, as a fraction of the prior position."""
    base = flow.total_shares_held - flow.total_shares_delta
    if base <= 0:
        return SubScore(
            name="weighted_flow",
            weight=0.55,
            na_reason="13F rows carried no share counts to measure a delta against",
            sample_size=flow.holder_count,
        )
    turnover = flow.weighted_delta / base
    return SubScore(
        name="weighted_flow",
        weight=0.55,
        score=squash(turnover, scale=TURNOVER_SCALE),
        detail=(
            f"cohort-weighted delta {flow.weighted_delta:,.0f} shares on a "
            f"{base:,.0f} base ({turnover:+.2%})"
        ),
        as_of=flow.latest_as_of,
        sample_size=flow.holder_count,
        inputs={"weighted_delta": flow.weighted_delta, "prior_base": base},
    )


def _breadth_sub_score(flow: OwnershipFlow) -> SubScore:
    """How many holders moved the same way, regardless of size."""
    movers = flow.increases + flow.decreases
    if movers == 0:
        return SubScore(
            name="breadth",
            weight=0.25,
            na_reason="no holder changed its position in the period",
        )
    tilt = (flow.increases - flow.decreases) / movers
    conviction = min(1.0, movers / 10.0)
    return SubScore(
        name="breadth",
        weight=0.25,
        score=clamp(tilt * conviction),
        detail=f"{flow.increases} holders added vs {flow.decreases} trimmed",
        as_of=flow.latest_as_of,
        sample_size=movers,
        inputs={"increases": flow.increases, "decreases": flow.decreases},
    )


def _cohort_mix_sub_score(flow: OwnershipFlow) -> SubScore:
    """Whether the flow is discretionary or index tracking.

    Active money moving is the signal. If the whole delta is passive, the reading is
    about index membership, not about the company.
    """
    active = flow.cohorts.get(COHORT_ACTIVE)
    if active is None or active.shares_held <= 0:
        return SubScore(
            name="active_share",
            weight=0.20,
            na_reason="no active-manager holdings identified in the filing set",
        )
    active_turnover = active.turnover
    if active_turnover is None:
        return SubScore(
            name="active_share",
            weight=0.20,
            na_reason="active holdings carried no prior base to measure a delta against",
        )
    return SubScore(
        name="active_share",
        weight=0.20,
        score=squash(active_turnover, scale=TURNOVER_SCALE),
        detail=(
            f"active managers {active_turnover:+.2%} on {active.holders} holders "
            f"(passive and sovereign flow excluded from this leg)"
        ),
        as_of=flow.latest_as_of,
        sample_size=active.holders,
        inputs={"active_turnover": active_turnover, "active_holders": active.holders},
    )


def _eu_notification_sub_score(
    changes: Sequence[OwnershipChange], flow: OwnershipFlow
) -> SubScore:
    """EU threshold crossings: count direction, do not pretend to measure accumulation."""
    ups = sum(1 for c in changes if (c.percent_delta or c.shares_delta or 0) > 0)
    downs = sum(1 for c in changes if (c.percent_delta or c.shares_delta or 0) < 0)
    if ups + downs == 0:
        return SubScore(
            name="threshold_crossings",
            weight=1.0,
            na_reason="notifications carried no direction (no percent or share delta)",
            sample_size=len(changes),
        )
    tilt = (ups - downs) / (ups + downs)
    conviction = min(1.0, (ups + downs) / 3.0)
    return SubScore(
        name="threshold_crossings",
        weight=1.0,
        score=clamp(tilt * conviction),
        detail=(
            f"{ups} upward and {downs} downward threshold crossings; event signal, "
            "not a quarterly accumulation wave"
        ),
        as_of=flow.latest_as_of,
        sample_size=ups + downs,
        inputs={"crossings_up": ups, "crossings_down": downs},
    )
