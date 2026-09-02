"""Shared contract for the non-options components: `S_M`, `S_S`, `S_I`, `S_F`.

Every component answers the same four questions - what is the score, what went into it,
where did each number come from, and what could not be measured - so T7 can weight them
uniformly and T9 can render them without special cases.

Two rules are enforced here rather than left to each component:

1. A missing sub-score is `n/a`. Its weight is dropped and the remaining weights are
   re-normalized to 1.0, with the re-weighting disclosed. It is never scored as zero,
   which would silently drag a component toward neutral.
2. A reading past its staleness bound is not a reading. Bounds are release-cadence
   relative, so each component declares its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date as date_type, datetime
from typing import Any, Iterable, Mapping, Sequence

from briefing_app.models.candidate import Geography

#: Component identifiers, matching the `component_score.component` column.
MACRO = "S_M"
SENTIMENT = "S_S"
INSIDER = "S_I"
INSTITUTIONAL = "S_F"

#: Source quality, ordered worst to best. Drives T7's Tier A/B/C decision: an
#: aggregator-only required component is Tier B, an unavailable one is Tier C.
QUALITY_NONE = "none"
QUALITY_AGGREGATOR = "aggregator"
QUALITY_MANUAL = "manual"
QUALITY_PRIMARY = "primary"

_QUALITY_ORDER = (QUALITY_NONE, QUALITY_AGGREGATOR, QUALITY_MANUAL, QUALITY_PRIMARY)

#: Validation status, matching `market_data.ValidationStatus` values.
STATUS_VERIFIED = "verified"
STATUS_PARTIAL = "partial"
STATUS_UNAVAILABLE = "unavailable"


class ComponentError(ValueError):
    """Raised when a component is asked to score structurally invalid input."""


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def squash(value: float, *, scale: float) -> float:
    """Map an unbounded reading onto -1..+1, saturating smoothly at `scale`.

    `scale` is the reading that should score about 0.76, so the curve is calibrated in
    the unit of the input rather than by an opaque constant.
    """
    if scale <= 0:
        raise ComponentError("scale must be positive")
    ratio = value / scale
    return clamp(ratio / (1.0 + abs(ratio)) * 2.0)


def worst_quality(*qualities: str) -> str:
    """The weakest link decides a component's source quality."""
    present = [q for q in qualities if q]
    if not present:
        return QUALITY_NONE
    return min(present, key=lambda q: _QUALITY_ORDER.index(q) if q in _QUALITY_ORDER else 0)


@dataclass(frozen=True)
class SubScore:
    """One measurable leg of a component.

    `score` is `None` when the leg could not be measured; `na_reason` then says why, and
    the leg's weight is re-normalized away instead of counting as neutral.
    """

    name: str
    weight: float
    score: float | None = None
    na_reason: str | None = None
    detail: str | None = None
    source: str | None = None
    as_of: date_type | None = None
    sample_size: int = 0
    inputs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.weight < 0:
            raise ComponentError(f"sub-score {self.name} has a negative weight")
        if self.score is not None and not -1.0 <= self.score <= 1.0:
            raise ComponentError(
                f"sub-score {self.name} is {self.score}, outside -1.0..+1.0"
            )
        if self.score is None and not self.na_reason:
            raise ComponentError(f"sub-score {self.name} is n/a with no reason given")

    @property
    def available(self) -> bool:
        return self.score is not None

    def to_dict(self, weight_used: float) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "weight": self.weight,
            "weight_used": weight_used,
            "available": self.available,
            "na_reason": self.na_reason,
            "detail": self.detail,
            "source": self.source,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "sample_size": self.sample_size,
            "inputs": self.inputs,
        }


def combine_sub_scores(
    sub_scores: Sequence[SubScore],
) -> tuple[float | None, dict[str, float], list[str]]:
    """Weighted mean over available legs, re-normalized to 1.0.

    Returns `(score, weights_used, disclosures)`. `score` is `None` when no leg could be
    measured. `disclosures` names every dropped leg so the re-weighting is never silent.
    """
    available = [s for s in sub_scores if s.available and s.weight > 0]
    weights_used: dict[str, float] = {s.name: 0.0 for s in sub_scores}
    disclosures: list[str] = []

    for dropped in (s for s in sub_scores if not s.available):
        disclosures.append(
            f"{dropped.name} is n/a ({dropped.na_reason}); its {dropped.weight:.2f} "
            "weight was dropped and the remainder re-normalized."
        )

    total_weight = sum(s.weight for s in available)
    if not available or total_weight <= 0:
        return None, weights_used, disclosures

    score = 0.0
    for sub in available:
        used = sub.weight / total_weight
        weights_used[sub.name] = used
        score += (sub.score or 0.0) * used
    return clamp(score), weights_used, disclosures


def is_stale(as_of: date_type | None, *, run_date: date_type, max_age_days: int) -> bool:
    """Whether a reading is past its release-cadence bound."""
    if as_of is None:
        return True
    return (run_date - as_of).days > max_age_days


@dataclass(frozen=True)
class ComponentResult:
    """One component's verdict plus everything needed to audit or re-weight it."""

    component: str
    ticker: str
    as_of: datetime
    geography: Geography
    available: bool
    score: float | None
    validation_status: str
    source_quality: str
    na_reason: str | None = None
    sub_scores: tuple[SubScore, ...] = ()
    weights_used: dict[str, float] = field(default_factory=dict)
    source_rows: tuple[dict[str, Any], ...] = ()
    evidence_rows: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[str, ...] = ()
    #: Set when a non-US disclosure regime stood in for the US source.
    eu_substitutes: tuple[str, ...] = ()

    @property
    def weight_profile(self) -> str:
        return self.geography.weight_profile

    def sub_score(self, name: str) -> SubScore | None:
        return next((s for s in self.sub_scores if s.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "ticker": self.ticker,
            "as_of": self.as_of.isoformat(),
            "geography": self.geography.value,
            "weight_profile": self.weight_profile,
            "available": self.available,
            "score": self.score,
            "validation_status": self.validation_status,
            "source_quality": self.source_quality,
            "na_reason": self.na_reason,
            "sub_scores": [
                s.to_dict(self.weights_used.get(s.name, 0.0)) for s in self.sub_scores
            ],
            "diagnostics": list(self.diagnostics),
            "eu_substitutes": list(self.eu_substitutes),
            "source_row_count": len(self.source_rows),
        }

    def to_component_score_row(
        self, run_id: int | None = None, *, required: bool = False
    ) -> dict[str, Any]:
        """A row for the `component_score` table. T7 fills the weight columns."""
        return {
            "run_id": run_id,
            "ticker": self.ticker,
            "component": self.component,
            "score": self.score,
            "validation_status": self.validation_status,
            "source_quality": self.source_quality,
            "required": required,
            "missing_reason": self.na_reason,
            "details": self.to_dict(),
        }


def build_evidence_rows(
    *,
    component: str,
    ticker: str,
    as_of: datetime,
    values: Mapping[str, Any],
    source: str,
    venue: str = "*",
    endpoint_or_file: str = "",
    validation_status: str = STATUS_VERIFIED,
    notes: Mapping[str, str] | None = None,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    """Evidence rows in the shape `evidence_ledger` expects.

    Every number a component reports must be reconstructable from these rows, so `None`
    values are skipped rather than written as an empty string that reads like a measurement.
    """
    notes = notes or {}
    rows: list[dict[str, Any]] = []
    for field_name, value in values.items():
        if value is None:
            continue
        rows.append(
            {
                "run_id": run_id,
                "ticker": ticker.strip().upper(),
                "component": component,
                "field_name": field_name,
                "field_value": str(value),
                "source": source,
                "venue": venue,
                "as_of": as_of,
                "endpoint_or_file": endpoint_or_file,
                "validation_status": validation_status,
                "note": notes.get(field_name),
            }
        )
    return rows


def evidence_from_sub_scores(
    component: str,
    ticker: str,
    as_of: datetime,
    sub_scores: Iterable[SubScore],
    *,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    """One evidence row per measured leg, carrying its own source and as-of date."""
    rows: list[dict[str, Any]] = []
    for sub in sub_scores:
        if not sub.available:
            continue
        rows.append(
            {
                "run_id": run_id,
                "ticker": ticker.strip().upper(),
                "component": component,
                "field_name": f"{component.lower()}_{sub.name}",
                "field_value": f"{sub.score:.4f}",
                "source": sub.source or "computed",
                "venue": "*",
                "as_of": _as_datetime(sub.as_of) or as_of,
                "endpoint_or_file": "",
                "validation_status": STATUS_VERIFIED,
                "note": sub.detail,
            }
        )
    return rows


def unavailable_component(
    *,
    component: str,
    ticker: str,
    geography: Geography,
    as_of: datetime,
    reason: str,
    sub_scores: Sequence[SubScore] = (),
    diagnostics: Sequence[str] = (),
    eu_substitutes: Sequence[str] = (),
) -> ComponentResult:
    """A component that could not be measured. `n/a`, never zero."""
    return ComponentResult(
        component=component,
        ticker=ticker.strip().upper(),
        as_of=as_of,
        geography=geography,
        available=False,
        score=None,
        validation_status=STATUS_UNAVAILABLE,
        source_quality=QUALITY_NONE,
        na_reason=reason,
        sub_scores=tuple(sub_scores),
        weights_used={s.name: 0.0 for s in sub_scores},
        diagnostics=tuple(diagnostics),
        eu_substitutes=tuple(eu_substitutes),
    )


def _as_datetime(value: date_type | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def to_datetime(value: date_type | datetime | None) -> datetime:
    """Normalize any date-ish value to an aware UTC datetime."""
    converted = _as_datetime(value)
    return converted or datetime.now(UTC)
