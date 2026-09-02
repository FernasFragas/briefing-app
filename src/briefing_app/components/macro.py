"""`S_M` - macro context, and the 30-day catalyst calendar.

Macro has no direction for a ticker on its own: rising rates are a tailwind for one
sector and a headwind for another. So `S_M` is the product of two declared things - an
observed factor trend (sourced, dated) and the sector's sensitivity to that factor
(declared before the pull, in config) - never an inference about what "should" help.

Where no sensitivity is declared, the factor is `n/a` rather than assumed neutral.

Event risk is reported beside the score, not folded into it. A dense release calendar
does not make a name bullish or bearish; it makes the range wider and the conviction
lower, which are T5's and T8's jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timedelta
from math import sqrt
from typing import Mapping, Sequence
import re

from briefing_app.components.base import (
    MACRO,
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
    to_datetime,
    unavailable_component,
)
from briefing_app.models.candidate import Catalyst, CatalystStatus, Geography
from briefing_app.models.market_data import CatalystCalendar, MacroCalendar, MacroEvent

#: Factor buckets. Each maps to one sub-score so a reader can see which channel moved.
BUCKET_POLICY = "policy_path"
BUCKET_GROWTH = "growth_inflation"
BUCKET_COMMODITY = "commodity"
BUCKET_SECTOR_POLICY = "sector_policy"

BUCKET_WEIGHTS: dict[str, float] = {
    BUCKET_POLICY: 0.30,
    BUCKET_GROWTH: 0.30,
    BUCKET_COMMODITY: 0.20,
    BUCKET_SECTOR_POLICY: 0.20,
}

#: Which bucket a named factor belongs to.
FACTOR_BUCKETS: dict[str, str] = {
    "policy_rate": BUCKET_POLICY,
    "fed_funds": BUCKET_POLICY,
    "ecb_rate": BUCKET_POLICY,
    "yield_curve": BUCKET_POLICY,
    "real_yields": BUCKET_POLICY,
    "treasury_10y": BUCKET_POLICY,
    "dollar": BUCKET_POLICY,
    "credit_spreads": BUCKET_POLICY,
    "cpi": BUCKET_GROWTH,
    "inflation": BUCKET_GROWTH,
    "ppi": BUCKET_GROWTH,
    "nonfarm_payroll": BUCKET_GROWTH,
    "unemployment": BUCKET_GROWTH,
    "real_gdp": BUCKET_GROWTH,
    "retail_sales": BUCKET_GROWTH,
    "pce": BUCKET_GROWTH,
    "brent": BUCKET_COMMODITY,
    "wti": BUCKET_COMMODITY,
    "natural_gas": BUCKET_COMMODITY,
    "copper": BUCKET_COMMODITY,
    "aluminum": BUCKET_COMMODITY,
    "all_commodities": BUCKET_COMMODITY,
}

#: Macro readings are only current until the series releases again.
MAX_AGE_DAYS = 45

#: Horizon for the published catalyst calendar.
CALENDAR_DAYS = 30

#: Event importance that counts toward event risk.
_HIGH_IMPORTANCE = {"high", "3", "critical"}

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_SUFFIXES = {"k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9, "t": 1e12}


@dataclass(frozen=True)
class MacroReading:
    """One observed macro factor: what moved, which way, when, and from where."""

    name: str
    trend: float
    as_of: date_type
    source: str
    level: float | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not -1.0 <= self.trend <= 1.0:
            raise ValueError(f"macro reading {self.name} trend must be -1.0..+1.0")


@dataclass(frozen=True)
class SectorExposure:
    """How a sector responds to each macro factor. Declared in config, never inferred.

    A sensitivity of -1 means the factor rising is a full headwind; +1 a full tailwind.
    An undeclared factor is not scored, so a name is never given macro credit for a
    relationship nobody wrote down.
    """

    sector: str
    sensitivities: Mapping[str, float] = field(default_factory=dict)
    policy_stance: float | None = None
    policy_note: str | None = None
    policy_source: str | None = None

    def sensitivity(self, factor: str) -> float | None:
        value = self.sensitivities.get(factor)
        if value is None:
            return None
        return clamp(float(value))


@dataclass(frozen=True)
class CalendarEntry:
    """One dated event on the published 30-day calendar."""

    name: str
    event_date: date_type
    status: str
    kind: str
    scope: str
    source: str
    importance: str | None = None
    relevance: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "date": self.event_date.isoformat(),
            "status": self.status,
            "kind": self.kind,
            "scope": self.scope,
            "source": self.source,
            "importance": self.importance,
            "relevance": self.relevance,
        }


def parse_macro_number(value: object) -> float | None:
    """Parse a release figure such as `150K`, `3.2%`, or `1.5M` into a float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace(",", "")
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    number = float(match.group().replace(",", "."))
    tail = text[match.end() :].strip()
    for suffix, multiplier in _SUFFIXES.items():
        if tail.startswith(suffix):
            return number * multiplier
    return number


def release_surprise(event: MacroEvent) -> float | None:
    """Signed surprise versus consensus, normalized by the size of the estimate."""
    actual = parse_macro_number(event.actual)
    estimate = parse_macro_number(event.estimate)
    if actual is None or estimate is None:
        return None
    scale = abs(estimate)
    if scale == 0:
        previous = parse_macro_number(event.previous)
        scale = abs(previous) if previous else 1.0
    if scale == 0:
        return None
    return (actual - estimate) / scale


def release_change_reading(
    events: Sequence[MacroEvent],
    *,
    factor: str,
    run_date: date_type,
    max_age_days: int = MAX_AGE_DAYS,
    min_history: int = 8,
) -> MacroReading | None:
    """Trend for a factor from its own release history, when no consensus is published.

    Free-plan macro feeds publish released levels without an estimate, so `release_surprise`
    has nothing to compare against. A release-over-release change is still a sourced,
    dated observation of the factor, and it is scored on the series' own scale: the latest
    change is expressed in standard deviations of that series' historical changes, so a
    move that is ordinary for the series reads as a weak trend and a two-sigma move reads
    as a full one.

    Returns `None` — never a neutral 0.0 — when the series is too short to establish that
    scale, is flat, or has not printed inside the staleness bound.
    """

    dated = sorted(
        (
            (event.event_date.date(), parse_macro_number(event.actual), event)
            for event in events
            if event.actual is not None
        ),
        key=lambda item: item[0],
    )
    observations = [item for item in dated if item[1] is not None and item[0] <= run_date]
    if len(observations) < min_history + 1:
        return None

    period_date, latest_value, latest_event = observations[-1]
    # Age from publication, not from the period measured. A monthly series is dated to the
    # month it covers, so a print two weeks old reads as two months stale against a 45-day
    # bound and drops out of the component entirely. Providers that publish no release date
    # leave `released_at` unset and keep the previous behaviour.
    latest_date = _known_at(latest_event, period_date)
    if is_stale(latest_date, run_date=run_date, max_age_days=max_age_days):
        return None

    values = [value for _, value, _ in observations]
    changes = [later - earlier for earlier, later in zip(values, values[1:])]
    scale = _stdev(changes)
    # A series that has moved by the same step every time has no distribution to score
    # against, and floating-point noise leaves its deviation just above zero rather than
    # at it. Scoring against that noise would report any move as a full-strength trend.
    reference = max((abs(value) for value in values), default=0.0) or 1.0
    if scale is None or scale < reference * 1e-9:
        return None

    latest_change = changes[-1]
    previous_value = values[-2]
    return MacroReading(
        name=factor,
        trend=clamp(latest_change / (2 * scale)),
        as_of=latest_date,
        source=latest_event.source,
        level=latest_value,
        detail=(
            f"{latest_event.name} released {latest_value} on {latest_date.isoformat()}"
            + (
                f" for the period beginning {period_date.isoformat()}"
                if latest_date != period_date
                else ""
            )
            + f" versus {previous_value} previously; change of {latest_change:+.4g} against a "
            f"{scale:.4g} standard deviation of {len(changes)} prior release changes. "
            "Release-over-release change, not a consensus surprise."
        ),
    )


def _known_at(event: MacroEvent, period_date: date_type) -> date_type:
    """When a reading became public, falling back to the period it measures."""

    released_at = getattr(event, "released_at", None)
    return released_at.date() if released_at is not None else period_date


def _stdev(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return sqrt(variance)


def build_catalyst_calendar(
    *,
    run_date: date_type,
    macro_calendar: MacroCalendar | None = None,
    catalyst_calendar: CatalystCalendar | None = None,
    manual_catalysts: Sequence[Catalyst] = (),
    days: int = CALENDAR_DAYS,
) -> list[CalendarEntry]:
    """The 30-day dated calendar, each entry marked Confirmed or Estimated.

    Scheduled macro releases are Confirmed - the date is published by the agency even
    when the number is not known. Single-name events carry whatever status the source
    declared, so a cadence-inferred earnings date stays Estimated.
    """
    window_end = run_date + timedelta(days=days)
    entries: list[CalendarEntry] = []

    if macro_calendar is not None:
        for event in macro_calendar.events:
            event_date = event.event_date.date()
            if not run_date <= event_date <= window_end:
                continue
            entries.append(
                CalendarEntry(
                    name=event.name,
                    event_date=event_date,
                    status=CatalystStatus.CONFIRMED.value,
                    kind="macro",
                    scope="macro",
                    source=event.source,
                    importance=event.importance,
                    relevance=f"{event.country} scheduled release" if event.country else None,
                )
            )

    if catalyst_calendar is not None:
        for event in catalyst_calendar.events:
            if not run_date <= event.event_date <= window_end:
                continue
            entries.append(
                CalendarEntry(
                    name=event.name,
                    event_date=event.event_date,
                    status=event.status,
                    kind=event.kind,
                    scope="single_name",
                    source=event.source,
                    relevance=event.ticker,
                )
            )

    for catalyst in manual_catalysts:
        if not run_date <= catalyst.event_date <= window_end:
            continue
        entries.append(
            CalendarEntry(
                name=catalyst.name,
                event_date=catalyst.event_date,
                status=catalyst.status.value,
                kind=catalyst.kind,
                scope="single_name",
                source=catalyst.source or "manual catalyst",
                relevance=catalyst.note,
            )
        )

    return sorted(entries, key=lambda e: (e.event_date, e.scope, e.name))


def event_risk(entries: Sequence[CalendarEntry], *, horizon_days: int) -> float:
    """Density of high-importance dated events, 0..1.

    Reported beside the score. A crowded calendar widens ranges and cuts conviction; it
    does not make a name bullish.
    """
    if horizon_days <= 0:
        return 0.0
    heavy = sum(
        1
        for entry in entries
        if (entry.importance or "").strip().lower() in _HIGH_IMPORTANCE
        or entry.kind in {"earnings", "macro"}
    )
    return clamp(heavy / max(1.0, horizon_days / 7.0), 0.0, 1.0)


def build_macro_component(
    *,
    ticker: str,
    geography: Geography | str,
    run_date: date_type,
    readings: Sequence[MacroReading] = (),
    exposure: SectorExposure | None = None,
    macro_calendar: MacroCalendar | None = None,
    catalyst_calendar: CatalystCalendar | None = None,
    manual_catalysts: Sequence[Catalyst] = (),
    calendar_days: int = CALENDAR_DAYS,
    as_of: datetime | None = None,
    max_age_days: int = MAX_AGE_DAYS,
    source_quality: str = QUALITY_PRIMARY,
    endpoint_or_file: str = "",
    run_id: int | None = None,
) -> ComponentResult:
    """Score `S_M` from sourced factor readings and a declared sector exposure."""
    geo = Geography(geography)
    clean_ticker = ticker.strip().upper()
    resolved_as_of = to_datetime(as_of or run_date)

    calendar = build_catalyst_calendar(
        run_date=run_date,
        macro_calendar=macro_calendar,
        catalyst_calendar=catalyst_calendar,
        manual_catalysts=manual_catalysts,
        days=calendar_days,
    )
    risk = event_risk(calendar, horizon_days=calendar_days)
    diagnostics: list[str] = []

    if exposure is None:
        return unavailable_component(
            component=MACRO,
            ticker=clean_ticker,
            geography=geo,
            as_of=resolved_as_of,
            reason=(
                "no sector exposure declared; macro direction cannot be inferred from "
                "a factor trend alone"
            ),
            diagnostics=[
                f"{len(calendar)} dated events in the next {calendar_days} days were "
                "still collected for the calendar."
            ],
        )

    fresh: list[MacroReading] = []
    for reading in readings:
        if is_stale(reading.as_of, run_date=run_date, max_age_days=max_age_days):
            diagnostics.append(
                f"{reading.name} reading from {reading.as_of.isoformat()} is beyond the "
                f"{max_age_days}-day bound and was dropped."
            )
            continue
        fresh.append(reading)

    surprises = _surprise_readings(macro_calendar, run_date=run_date, max_age_days=max_age_days)
    bucketed = _bucket_scores(fresh + surprises, exposure, diagnostics)

    sub_scores = (
        _bucket_sub_score(BUCKET_POLICY, bucketed, "no dated rates, curve, or credit reading with a declared sensitivity"),
        _bucket_sub_score(BUCKET_GROWTH, bucketed, "no growth or inflation release with a declared sensitivity"),
        _bucket_sub_score(BUCKET_COMMODITY, bucketed, "no commodity reading with a declared sensitivity"),
        _sector_policy_sub_score(exposure),
    )
    score, weights_used, disclosures = combine_sub_scores(sub_scores)
    diagnostics.extend(disclosures)

    if score is None:
        return unavailable_component(
            component=MACRO,
            ticker=clean_ticker,
            geography=geo,
            as_of=resolved_as_of,
            reason="no macro factor could be scored against the declared sector exposure",
            sub_scores=sub_scores,
            diagnostics=diagnostics,
        )

    evidence = build_evidence_rows(
        component=MACRO,
        ticker=clean_ticker,
        as_of=resolved_as_of,
        source=macro_calendar.source if macro_calendar else "macro readings",
        endpoint_or_file=endpoint_or_file,
        run_id=run_id,
        values={
            "macro_sector": exposure.sector,
            "macro_readings_used": sum(len(v) for v in bucketed.values()) or None,
            "macro_calendar_events": len(calendar),
            "macro_event_risk": round(risk, 4),
            "s_m": round(score, 4),
        },
        notes={
            "macro_event_risk": (
                "Density of high-importance dated events; reported beside the score, "
                "never folded into its direction."
            ),
            "s_m": f"scored against declared {exposure.sector} sensitivities",
        },
    )
    evidence.extend(
        evidence_from_sub_scores(MACRO, clean_ticker, resolved_as_of, sub_scores, run_id=run_id)
    )
    for reading in fresh:
        evidence.extend(
            build_evidence_rows(
                component=MACRO,
                ticker=clean_ticker,
                as_of=to_datetime(reading.as_of),
                source=reading.source,
                run_id=run_id,
                values={f"macro_{reading.name}_trend": round(reading.trend, 4)},
                notes={f"macro_{reading.name}_trend": reading.detail},
            )
        )

    return ComponentResult(
        component=MACRO,
        ticker=clean_ticker,
        as_of=resolved_as_of,
        geography=geo,
        available=True,
        score=score,
        validation_status=STATUS_VERIFIED if all(s.available for s in sub_scores) else STATUS_PARTIAL,
        source_quality=source_quality,
        sub_scores=sub_scores,
        weights_used=weights_used,
        source_rows=tuple(entry.to_dict() for entry in calendar),
        evidence_rows=tuple(evidence),
        diagnostics=tuple(diagnostics),
    )


def _surprise_readings(
    macro_calendar: MacroCalendar | None,
    *,
    run_date: date_type,
    max_age_days: int,
) -> list[MacroReading]:
    """Turn released numbers into factor trends via their surprise versus consensus."""
    if macro_calendar is None:
        return []
    readings: list[MacroReading] = []
    for event in macro_calendar.events:
        event_date = event.event_date.date()
        if event_date > run_date or is_stale(event_date, run_date=run_date, max_age_days=max_age_days):
            continue
        surprise = release_surprise(event)
        if surprise is None:
            continue
        factor = _factor_for_event(event.name)
        if factor is None:
            continue
        readings.append(
            MacroReading(
                name=factor,
                trend=clamp(surprise / 0.10),
                as_of=event_date,
                source=event.source,
                level=parse_macro_number(event.actual),
                detail=f"{event.name} actual {event.actual} vs estimate {event.estimate}",
            )
        )
    return readings


def _factor_for_event(name: str) -> str | None:
    lowered = name.strip().lower()
    for factor in FACTOR_BUCKETS:
        if factor.replace("_", " ") in lowered or factor in lowered:
            return factor
    if "payroll" in lowered or "jobs" in lowered:
        return "nonfarm_payroll"
    if "inflation" in lowered or "consumer price" in lowered:
        return "cpi"
    if "gdp" in lowered:
        return "real_gdp"
    return None


def _bucket_scores(
    readings: Sequence[MacroReading],
    exposure: SectorExposure,
    diagnostics: list[str],
) -> dict[str, list[tuple[MacroReading, float]]]:
    """Score each reading against its declared sensitivity, grouped by bucket."""
    buckets: dict[str, list[tuple[MacroReading, float]]] = {
        BUCKET_POLICY: [],
        BUCKET_GROWTH: [],
        BUCKET_COMMODITY: [],
    }
    for reading in readings:
        bucket = FACTOR_BUCKETS.get(reading.name)
        if bucket is None:
            diagnostics.append(f"{reading.name} has no factor bucket and was skipped.")
            continue
        sensitivity = exposure.sensitivity(reading.name)
        if sensitivity is None:
            diagnostics.append(
                f"{reading.name} has no declared {exposure.sector} sensitivity; "
                "skipped rather than assumed neutral."
            )
            continue
        buckets[bucket].append((reading, clamp(reading.trend * sensitivity)))
    return buckets


def _bucket_sub_score(
    bucket: str,
    bucketed: Mapping[str, Sequence[tuple[MacroReading, float]]],
    na_reason: str,
) -> SubScore:
    rows = list(bucketed.get(bucket, ()))
    weight = BUCKET_WEIGHTS[bucket]
    if not rows:
        return SubScore(name=bucket, weight=weight, na_reason=na_reason)
    score = sum(value for _reading, value in rows) / len(rows)
    latest = max(reading.as_of for reading, _ in rows)
    return SubScore(
        name=bucket,
        weight=weight,
        score=clamp(score),
        detail="; ".join(
            f"{reading.name} trend {reading.trend:+.2f} -> {value:+.2f}"
            for reading, value in rows
        ),
        source=", ".join(sorted({reading.source for reading, _ in rows})),
        as_of=latest,
        sample_size=len(rows),
        inputs={reading.name: round(value, 4) for reading, value in rows},
    )


def _sector_policy_sub_score(exposure: SectorExposure) -> SubScore:
    weight = BUCKET_WEIGHTS[BUCKET_SECTOR_POLICY]
    if exposure.policy_stance is None:
        return SubScore(
            name=BUCKET_SECTOR_POLICY,
            weight=weight,
            na_reason=f"no policy or regulatory stance declared for {exposure.sector}",
        )
    return SubScore(
        name=BUCKET_SECTOR_POLICY,
        weight=weight,
        score=clamp(exposure.policy_stance),
        detail=exposure.policy_note,
        source=exposure.policy_source,
    )
