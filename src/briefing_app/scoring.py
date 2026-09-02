"""Composite score and confidence-tier engine (T7).

The component builders and options engine produce already-standardized scores. This
module owns only the cross-component arithmetic: geography-specific weights, missing
component reweighting, required-set tiering, universal Tier C floors, and storage row
shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date as date_type, datetime, timedelta
import json
import uuid
from typing import Any, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from briefing_app.components.base import (
    QUALITY_AGGREGATOR,
    QUALITY_MANUAL,
    QUALITY_NONE,
    QUALITY_PRIMARY,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    STATUS_VERIFIED,
    ComponentResult,
)
from briefing_app.models.candidate import Candidate, ExpressionClass, Geography
from briefing_app.models.gate import CandidateGateResult
from briefing_app.models.scoring import (
    COMPONENTS,
    REQUIRED_COMPONENTS,
    ComponentScore,
    ConfidenceTier,
    Posture,
    ScoringResult,
    weights_for,
)
from briefing_app.options_math import OptionsStructureResult


SCORING_COMPONENT = "S_CTE"

_OK_STATUSES = {STATUS_VERIFIED, "computed", "ok"}
_DEGRADED_STATUSES = {STATUS_PARTIAL, "stale", "truncated"}
_UNAVAILABLE_STATUSES = {
    STATUS_UNAVAILABLE,
    "missing",
    "paywalled",
    "unverifiable",
    "rejected",
    "synthetic",
    "throttled",
    "malformed",
    "no_credentials",
    "network_error",
    "placeholder",
}
_PRIMARY_QUALITIES = {QUALITY_PRIMARY, "exchange", "api", "provider", "computed"}
_DEGRADED_QUALITIES = {QUALITY_AGGREGATOR, QUALITY_MANUAL, "stale", "fallback"}
_UNAVAILABLE_QUALITIES = {QUALITY_NONE, "unavailable", "unverifiable"}


ScoreInput = ComponentResult | ComponentScore | OptionsStructureResult | Mapping[str, Any]


@dataclass(frozen=True)
class ScoringContext:
    """One ticker's T7 inputs.

    `subject` is usually a `CandidateGateResult`, because the class, geography,
    in-horizon catalyst, and permitted instruments were declared before data pull.
    A raw `Candidate` is accepted for fixture-level tests and offline scoring.
    """

    subject: Candidate | CandidateGateResult
    components: Sequence[ScoreInput] = ()
    options_structure: OptionsStructureResult | None = None
    measured_sigma_available: bool | None = None
    catalyst_available: bool | None = None
    invalidation_available: bool | None = None
    borrow_verified: bool | None = None
    notes: Sequence[str] = ()


class ScoringReport(BaseModel):
    """Composite scores for one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_date: date_type
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    results: list[ScoringResult] = Field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "tickers": len(self.results),
            "tier_a": len([r for r in self.results if r.tier is ConfidenceTier.A]),
            "tier_b": len([r for r in self.results if r.tier is ConfidenceTier.B]),
            "tier_c": len([r for r in self.results if r.tier is ConfidenceTier.C]),
            "scored": len([r for r in self.results if r.s_cte is not None]),
        }

    def matrix(self) -> list[dict[str, Any]]:
        """Compact rows for the Master Alpha Selection Matrix."""
        return [
            {
                "ticker": result.ticker,
                "expression_class": result.expression_class.value,
                "geography": result.geography.value,
                "s_cte": result.s_cte,
                "tier": result.tier.value,
                "posture": result.posture.value,
                "required_set_verdict": result.required_set_verdict,
                "weights_used": result.weights_used,
                "missing_components": result.missing_components,
                "tier_reasons": list(result.tier_reasons),
            }
            for result in self.results
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_date": self.run_date.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "counts": self.counts(),
            "matrix": self.matrix(),
            "results": [result.model_dump(mode="json") for result in self.results],
        }


def make_run_id(run_date: date_type) -> str:
    return f"scoring-{run_date.isoformat()}-{uuid.uuid4().hex[:8]}"


def build_scoring_result(
    subject: Candidate | CandidateGateResult,
    components: Iterable[ScoreInput] = (),
    *,
    options_structure: OptionsStructureResult | None = None,
    run_date: date_type | None = None,
    measured_sigma_available: bool | None = None,
    catalyst_available: bool | None = None,
    invalidation_available: bool | None = None,
    borrow_verified: bool | None = None,
    notes: Sequence[str] = (),
) -> ScoringResult:
    """Compute one ticker's `S_CTE`, component disclosures, posture, and tier.

    Missing components are dropped from the denominator. Required components still
    control the tier, so a missing `S_O` for class `E` can leave a visible arithmetic
    score while correctly flooring the name to Tier C.
    """

    candidate, gate_result = _resolve_subject(subject)
    expression_class = candidate.expression_class
    geography = candidate.geography
    weights = weights_for(geography)
    required = REQUIRED_COMPONENTS[expression_class]

    normalized_inputs = list(components)
    if options_structure is not None:
        normalized_inputs.append(options_structure)

    by_component = _normalize_inputs(normalized_inputs)
    completed = _complete_component_set(by_component, weights, required)
    s_cte = _weighted_score(completed)
    tier, tier_reasons = _confidence_tier(completed, required)

    floor_reasons = _universal_floor_reasons(
        candidate=candidate,
        gate_result=gate_result,
        options_structure=options_structure,
        run_date=run_date,
        measured_sigma_available=measured_sigma_available,
        catalyst_available=catalyst_available,
        invalidation_available=invalidation_available,
        borrow_verified=borrow_verified,
    )
    if floor_reasons:
        tier = tier.floor_to(ConfidenceTier.C)
        tier_reasons.extend(floor_reasons)

    disclosures = _missing_component_notes(completed)
    return ScoringResult(
        ticker=candidate.ticker,
        expression_class=expression_class,
        geography=geography,
        s_cte=s_cte,
        tier=tier,
        components=completed,
        tier_reasons=tier_reasons,
        notes=[*disclosures, *notes],
    )


def score_candidate(
    subject: Candidate | CandidateGateResult,
    components: Iterable[ScoreInput] = (),
    **kwargs: Any,
) -> ScoringResult:
    """Alias for callers that read better as a verb."""
    return build_scoring_result(subject, components, **kwargs)


def run_scoring(
    contexts: Iterable[ScoringContext],
    *,
    run_date: date_type,
    run_id: str | None = None,
) -> ScoringReport:
    results = [
        build_scoring_result(
            context.subject,
            context.components,
            options_structure=context.options_structure,
            run_date=run_date,
            measured_sigma_available=context.measured_sigma_available,
            catalyst_available=context.catalyst_available,
            invalidation_available=context.invalidation_available,
            borrow_verified=context.borrow_verified,
            notes=context.notes,
        )
        for context in contexts
    ]
    return ScoringReport(
        run_id=run_id or make_run_id(run_date),
        run_date=run_date,
        results=results,
    )


def to_component_score_rows(
    result_or_report: ScoringResult | ScoringReport,
    run_id: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in _iter_results(result_or_report):
        disclosure = result.disclosure()
        for component in result.components:
            rows.append(
                {
                    "run_id": run_id,
                    "ticker": result.ticker,
                    "component": component.component,
                    "score": component.score,
                    "original_weight": component.original_weight,
                    "weight_used": component.weight_used,
                    "validation_status": component.validation_status,
                    "source_quality": component.source_quality,
                    "required": component.required,
                    "missing_reason": component.missing_reason,
                    "details": {
                        "expression_class": result.expression_class.value,
                        "geography": result.geography.value,
                        "posture": result.posture.value,
                        "tier": result.tier.value,
                        "required_set_verdict": result.required_set_verdict,
                        "component": component.model_dump(mode="json"),
                        "scoring": disclosure,
                    },
                }
            )
    return rows


def to_scoring_evidence_rows(
    result_or_report: ScoringResult | ScoringReport,
    run_id: int | None = None,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    evidence_time = as_of or (
        result_or_report.generated_at if isinstance(result_or_report, ScoringReport) else datetime.now(UTC)
    )

    for result in _iter_results(result_or_report):
        values = {
            "expression_class": result.expression_class.value,
            "weight_profile": result.weight_profile,
            "s_cte": result.s_cte,
            "confidence_tier": result.tier.value,
            "posture": result.posture.value,
            "required_set_verdict": result.required_set_verdict,
            "weights_used": json.dumps(result.weights_used, sort_keys=True),
            "missing_components": json.dumps(result.missing_components),
            "missing_required": json.dumps(result.missing_required),
        }
        for field_name, value in values.items():
            if value is None:
                continue
            rows.append(
                {
                    "run_id": run_id,
                    "ticker": result.ticker,
                    "component": SCORING_COMPONENT,
                    "field_name": field_name,
                    "field_value": str(value),
                    "source": (
                        "candidate declaration"
                        if field_name == "expression_class"
                        else "computed"
                    ),
                    "venue": "*",
                    "as_of": evidence_time,
                    "endpoint_or_file": "",
                    "validation_status": (
                        STATUS_VERIFIED
                        if field_name == "expression_class"
                        else "computed"
                    ),
                    "note": _evidence_note(result, field_name),
                }
            )
    return rows


def to_daily_snapshot_row(
    result: ScoringResult,
    *,
    snap_date: date_type,
    run_id: int | None = None,
    options_structure: OptionsStructureResult | None = None,
    raw: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Row shaped for `daily_snapshot`, including T5 fields when supplied."""
    row: dict[str, Any] = {
        "run_id": run_id,
        "ticker": result.ticker,
        "snap_date": snap_date,
        "geography": result.geography.value,
        "component_scores": {
            component.component: component.score for component in result.components
        },
        "cte_score": result.s_cte,
        "confidence_tier": result.tier.value,
        "expression_class": result.expression_class.value,
        "raw": {
            "scoring": result.disclosure(),
            "components": [component.model_dump(mode="json") for component in result.components],
            **dict(raw or {}),
        },
    }

    if options_structure is not None:
        weekly = options_structure.expected_moves.get("weekly")
        monthly = options_structure.expected_moves.get("monthly")
        realized_20 = options_structure.realized_volatility.get(20)
        row.update(
            {
                "spot": options_structure.spot,
                "iv_atm": weekly.iv_atm if weekly else None,
                "iv_rank": options_structure.iv_rank,
                "expected_move_1w": weekly.straddle_pct if weekly else None,
                "expected_move_1m": monthly.straddle_pct if monthly else None,
                "pc_ratio_vol": (
                    options_structure.put_call.volume_ratio
                    if options_structure.put_call
                    else None
                ),
                "pc_ratio_oi": (
                    options_structure.put_call.open_interest_ratio
                    if options_structure.put_call
                    else None
                ),
                "rr_25d": (
                    options_structure.risk_reversal_25d.rr_25d
                    if options_structure.risk_reversal_25d
                    else None
                ),
                "realized_vol_20d": (
                    realized_20.annualized_vol if realized_20 else None
                ),
            }
        )
    return row


def to_daily_snapshot_rows(
    report: ScoringReport,
    *,
    snap_date: date_type,
    run_id: int | None = None,
    options_structures: Mapping[str, OptionsStructureResult] | None = None,
) -> list[dict[str, Any]]:
    structures = options_structures or {}
    return [
        to_daily_snapshot_row(
            result,
            snap_date=snap_date,
            run_id=run_id,
            options_structure=structures.get(result.ticker),
        )
        for result in report.results
    ]


def _resolve_subject(
    subject: Candidate | CandidateGateResult,
) -> tuple[Candidate, CandidateGateResult | None]:
    if isinstance(subject, CandidateGateResult):
        return subject.candidate, subject
    return subject, None


def _normalize_inputs(inputs: Iterable[ScoreInput]) -> dict[str, ComponentScore]:
    by_component: dict[str, ComponentScore] = {}
    for item in inputs:
        component = _component_score_from_input(item)
        by_component[component.component] = component
    return by_component


def _component_score_from_input(item: ScoreInput) -> ComponentScore:
    if isinstance(item, ComponentScore):
        source_quality = item.source_quality
        if item.score is not None and not source_quality:
            source_quality = QUALITY_PRIMARY
        return item.model_copy(update={"source_quality": source_quality})

    if isinstance(item, ComponentResult):
        return ComponentScore(
            component=item.component,
            score=item.score if item.available else None,
            validation_status=item.validation_status,
            source_quality=item.source_quality,
            missing_reason=item.na_reason,
            as_of=item.as_of.date(),
        )

    if isinstance(item, OptionsStructureResult):
        validation_status = _structure_validation_status(item)
        return ComponentScore(
            component="S_O",
            score=item.score if item.available else None,
            validation_status=validation_status,
            source_quality=QUALITY_PRIMARY if item.available else QUALITY_NONE,
            missing_reason=item.na_reason,
            as_of=item.as_of.date(),
        )

    raw = dict(item)
    score = raw.get("score")
    status = str(raw.get("validation_status") or (STATUS_VERIFIED if score is not None else STATUS_UNAVAILABLE))
    source_quality = raw.get("source_quality")
    if score is not None and not source_quality:
        source_quality = QUALITY_PRIMARY
    return ComponentScore(
        component=str(raw["component"]),
        score=score,
        validation_status=status,
        source_quality=source_quality,
        missing_reason=raw.get("missing_reason") or raw.get("na_reason"),
        as_of=raw.get("as_of"),
    )


def _structure_validation_status(structure: OptionsStructureResult) -> str:
    statuses = {
        str(row.get("validation_status"))
        for row in structure.evidence_rows
        if isinstance(row, Mapping) and row.get("validation_status")
    }
    if STATUS_UNAVAILABLE in statuses:
        return STATUS_UNAVAILABLE
    if STATUS_PARTIAL in statuses:
        return STATUS_PARTIAL
    if statuses:
        return STATUS_VERIFIED if statuses <= _OK_STATUSES else sorted(statuses)[0]
    return STATUS_VERIFIED if structure.available else STATUS_UNAVAILABLE


def _complete_component_set(
    by_component: Mapping[str, ComponentScore],
    weights: Mapping[str, float],
    required: frozenset[str],
) -> list[ComponentScore]:
    total_available_weight = sum(
        weights[name]
        for name in COMPONENTS
        if name in by_component and by_component[name].score is not None
    )

    completed: list[ComponentScore] = []
    for name in COMPONENTS:
        original_weight = float(weights[name])
        source = by_component.get(name)
        if source is None:
            source = ComponentScore(
                component=name,
                score=None,
                validation_status=STATUS_UNAVAILABLE,
                source_quality=QUALITY_NONE,
                missing_reason="component not supplied",
            )
        weight_used = (
            original_weight / total_available_weight
            if source.score is not None and total_available_weight > 0
            else 0.0
        )
        missing_reason = source.missing_reason
        if source.score is None and not missing_reason:
            missing_reason = "component score is n/a"
        completed.append(
            source.model_copy(
                update={
                    "original_weight": original_weight,
                    "weight_used": weight_used,
                    "required": name in required,
                    "missing_reason": missing_reason,
                }
            )
        )
    return completed


def _weighted_score(components: Sequence[ComponentScore]) -> float | None:
    available = [component for component in components if component.score is not None]
    if not available:
        return None
    score = sum(float(component.score) * component.weight_used for component in available)
    return max(-1.0, min(1.0, score))


def _confidence_tier(
    components: Sequence[ComponentScore],
    required: frozenset[str],
) -> tuple[ConfidenceTier, list[str]]:
    tier = ConfidenceTier.A
    reasons: list[str] = []
    by_component = {component.component: component for component in components}

    for name in sorted(required):
        component = by_component[name]
        condition = _required_component_condition(component)
        if condition is ConfidenceTier.C:
            tier = tier.floor_to(ConfidenceTier.C)
            reasons.append(_required_component_reason(component, ConfidenceTier.C))
        elif condition is ConfidenceTier.B:
            tier = tier.floor_to(ConfidenceTier.B)
            reasons.append(_required_component_reason(component, ConfidenceTier.B))

    return tier, reasons


def _required_component_condition(component: ComponentScore) -> ConfidenceTier:
    if component.score is None:
        return ConfidenceTier.C

    status = _clean(component.validation_status)
    quality = _clean(component.source_quality)
    if status in _UNAVAILABLE_STATUSES or quality in _UNAVAILABLE_QUALITIES:
        return ConfidenceTier.C
    if status in _DEGRADED_STATUSES or quality in _DEGRADED_QUALITIES or not quality:
        return ConfidenceTier.B
    if status in _OK_STATUSES and quality in _PRIMARY_QUALITIES:
        return ConfidenceTier.A
    if status not in _OK_STATUSES:
        return ConfidenceTier.B
    return ConfidenceTier.A


def _required_component_reason(component: ComponentScore, tier: ConfidenceTier) -> str:
    label = f"{component.component} required component"
    if tier is ConfidenceTier.C:
        reason = component.missing_reason or component.validation_status
        return f"{label} unavailable/unverifiable: {reason}"

    parts: list[str] = []
    if _clean(component.validation_status) in _DEGRADED_STATUSES:
        parts.append(f"status {component.validation_status}")
    if _clean(component.source_quality) in _DEGRADED_QUALITIES or not component.source_quality:
        parts.append(f"source quality {component.source_quality or 'unknown'}")
    return f"{label} degraded: {', '.join(parts) or 'non-primary source'}"


def _universal_floor_reasons(
    *,
    candidate: Candidate,
    gate_result: CandidateGateResult | None,
    options_structure: OptionsStructureResult | None,
    run_date: date_type | None,
    measured_sigma_available: bool | None,
    catalyst_available: bool | None,
    invalidation_available: bool | None,
    borrow_verified: bool | None,
) -> list[str]:
    reasons: list[str] = []

    measured = measured_sigma_available
    if measured is None:
        measured = options_structure is not None and options_structure.measured_range is not None
    if measured is False:
        reasons.append("universal Tier C floor: missing measured sigma from real closes")

    catalyst = catalyst_available
    if catalyst is None:
        if gate_result is not None:
            catalyst = gate_result.primary_catalyst is not None
        elif run_date is not None:
            horizon_days = candidate.effective_horizon_days(10)
            catalyst = bool(
                candidate.catalysts_between(
                    run_date,
                    run_date + timedelta(days=horizon_days),
                )
            )
        else:
            catalyst = bool(candidate.catalysts)
    if catalyst is False:
        reasons.append("universal Tier C floor: missing dated catalyst inside horizon")

    if invalidation_available is False:
        reasons.append("universal Tier C floor: missing invalidation level")

    if candidate.expression_class is ExpressionClass.S:
        borrow = borrow_verified
        if borrow is None and options_structure is not None and options_structure.short_borrow is not None:
            borrow = options_structure.short_borrow.verified
        if borrow is not True:
            reasons.append("universal Tier C floor: missing borrow or short-interest evidence")

    return reasons


def _missing_component_notes(components: Sequence[ComponentScore]) -> list[str]:
    notes: list[str] = []
    for component in components:
        if component.score is None:
            notes.append(
                f"{component.component} is n/a ({component.missing_reason}); its "
                f"{component.original_weight:.2f} original weight was dropped and "
                "remaining available components were re-normalized."
            )
    return notes


def _iter_results(
    result_or_report: ScoringResult | ScoringReport,
) -> Iterable[ScoringResult]:
    if isinstance(result_or_report, ScoringReport):
        return result_or_report.results
    return (result_or_report,)


def _evidence_note(result: ScoringResult, field_name: str) -> str | None:
    if field_name == "expression_class":
        return "Declared before provider data pull; controls required components."
    if field_name == "confidence_tier":
        return "; ".join(result.tier_reasons) or None
    if field_name == "weights_used":
        return "Missing components were dropped and available weights re-normalized."
    return None


def _clean(value: str | None) -> str:
    return str(value or "").strip().lower()
