"""Build the T9 dashboard payload from computed stage artifacts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type, datetime
from typing import Any, Mapping, Sequence

from briefing_app.components import ComponentResult
from briefing_app.dashboard.grading import compute_grade
from briefing_app.dashboard.models import (
    ConditionalityRow,
    DashboardPayload,
    EvidenceLedgerRow,
    MarketOverviewPoint,
    MasterAlphaRow,
    PerTickerSection,
    PriorScorecardRow,
    RejectedGateRow,
    TacticalDashboard,
    TradingIdeaRow,
)
from briefing_app.models.gate import CandidateGateResult, GateReport
from briefing_app.models.scoring import ScoringResult
from briefing_app.strategy.models import (
    CandidateSetupResult,
    Setup,
    SetupDecision,
    SetupReport,
    SetupType,
    to_setup_evidence_rows,
)


def build_dashboard_payload(
    *,
    run_id: str,
    run_date: date_type,
    generated_at: datetime,
    data_mode: str = "unknown",
    gate_report: GateReport | None = None,
    scores: Sequence[ScoringResult] = (),
    component_results: Sequence[ComponentResult] = (),
    setup_report: SetupReport | None = None,
    evidence_rows: Sequence[Mapping[str, Any]] = (),
    prior_scorecards: Sequence[Mapping[str, Any]] = (),
    market_overview: Sequence[MarketOverviewPoint | Mapping[str, Any]] = (),
    diagnostics: Sequence[str] = (),
) -> DashboardPayload:
    """Assemble the dashboard sections without recomputing any scores.

    All inputs are already computed or sourced by earlier stages. Missing sections are
    represented as empty lists or `None`, so the renderer can show "unavailable" instead
    of treating gaps as zeros.
    """
    gates = _gate_by_ticker(gate_report)
    score_by_ticker = {score.ticker: score for score in scores}
    components_by_ticker: dict[str, list[ComponentResult]] = defaultdict(list)
    for component in component_results:
        components_by_ticker[component.ticker].append(component)
    setup_by_ticker = _setup_result_by_ticker(setup_report)

    ledger = _build_evidence_ledger(
        explicit_rows=evidence_rows,
        component_results=component_results,
        setup_report=setup_report,
    )
    evidence_by_ticker: dict[str, list[EvidenceLedgerRow]] = defaultdict(list)
    for row in ledger:
        evidence_by_ticker[row.ticker].append(row)

    tickers = sorted(
        set(gates)
        | set(score_by_ticker)
        | set(components_by_ticker)
        | set(setup_by_ticker)
        | {row.ticker for row in ledger if row.ticker != "*"}
    )
    idea_tickers = sorted(
        set(score_by_ticker)
        | set(setup_by_ticker)
        | {ticker for ticker, gate in gates.items() if gate.is_scored}
    )
    trading_ideas = _trading_ideas(
        tickers=idea_tickers,
        gates=gates,
        scores=score_by_ticker,
        setup_results=setup_by_ticker,
    )

    return DashboardPayload(
        run_id=run_id,
        run_date=run_date,
        generated_at=generated_at,
        data_mode=data_mode,
        trading_ideas=trading_ideas,
        prior_scorecard=[_prior_row(row) for row in prior_scorecards],
        market_overview=[_market_point(point) for point in market_overview],
        master_alpha_selection_matrix=[
            _master_row(
                ticker=ticker,
                gate=gates.get(ticker),
                score=score_by_ticker.get(ticker),
                components=components_by_ticker.get(ticker, []),
                setup_result=setup_by_ticker.get(ticker),
            )
            for ticker in tickers
        ],
        rejected_at_gate=_rejected_rows(gate_report),
        evidence_ledger=ledger,
        tactical_execution_dashboard=_tactical_dashboard(setup_report),
        conditionality_table=_conditionality_rows(setup_report),
        per_ticker_sections=[
            _ticker_section(
                ticker=ticker,
                gate=gates.get(ticker),
                score=score_by_ticker.get(ticker),
                components=components_by_ticker.get(ticker, []),
                setup_result=setup_by_ticker.get(ticker),
                evidence=evidence_by_ticker.get(ticker, []),
                data_mode=data_mode,
            )
            for ticker in tickers
        ],
        diagnostics=list(diagnostics),
    )


def _gate_by_ticker(report: GateReport | None) -> dict[str, CandidateGateResult]:
    if report is None:
        return {}
    results: dict[str, CandidateGateResult] = {}
    for result in report.results:
        results.setdefault(result.ticker, result)
    return results


def _setup_result_by_ticker(report: SetupReport | None) -> dict[str, CandidateSetupResult]:
    if report is None:
        return {}
    return {result.ticker: result for result in report.results}


def _build_evidence_ledger(
    *,
    explicit_rows: Sequence[Mapping[str, Any]],
    component_results: Sequence[ComponentResult],
    setup_report: SetupReport | None,
) -> list[EvidenceLedgerRow]:
    rows: list[EvidenceLedgerRow] = []
    for row in explicit_rows:
        rows.append(_evidence_row(row))
    for component in component_results:
        rows.extend(_evidence_row(row) for row in component.evidence_rows)
    if setup_report is not None:
        rows.extend(_evidence_row(row) for row in to_setup_evidence_rows(setup_report))

    deduped: dict[tuple[str, str, str, str, str | None], EvidenceLedgerRow] = {}
    for row in rows:
        key = (row.ticker, row.component, row.field_name, row.field_value, row.as_of)
        deduped.setdefault(key, row)
    return sorted(
        deduped.values(),
        key=lambda row: (row.ticker, row.component, row.field_name, row.source),
    )


def _master_row(
    *,
    ticker: str,
    gate: CandidateGateResult | None,
    score: ScoringResult | None,
    components: Sequence[ComponentResult],
    setup_result: CandidateSetupResult | None,
) -> MasterAlphaRow:
    candidate = gate.candidate if gate is not None else None
    tradeable = setup_result.tradeable_setups if setup_result is not None else []
    top_setup = tradeable[0].setup_type.value if tradeable else None
    component_scores = {
        component.component: component.score
        for component in sorted(components, key=lambda c: c.component)
    }
    source_quality = {
        component.component: component.source_quality
        for component in sorted(components, key=lambda c: c.component)
    }

    if score is not None:
        for component_score in score.components:
            component_scores.setdefault(component_score.component, component_score.score)
            source_quality.setdefault(component_score.component, component_score.source_quality)

    return MasterAlphaRow(
        ticker=ticker,
        venue=candidate.venue if candidate is not None else None,
        geography=candidate.geography.value if candidate is not None else None,
        expression_class=(
            score.expression_class.value
            if score is not None
            else (candidate.expression_class.value if candidate is not None else None)
        ),
        direction=candidate.direction.value if candidate is not None else None,
        gate_decision=gate.decision.value if gate is not None else None,
        s_cte=score.s_cte if score is not None else None,
        tier=score.tier.value if score is not None else None,
        posture=score.posture.value if score is not None else None,
        component_scores=component_scores,
        missing_components=score.missing_components if score is not None else [],
        source_quality=source_quality,
        primary_catalyst=_catalyst_dict(gate.primary_catalyst) if gate is not None else None,
        top_setup=top_setup,
        tradeable_setup_count=len(tradeable),
        flags=[flag.code.value for flag in gate.flags] if gate is not None else [],
    )


def _rejected_rows(report: GateReport | None) -> list[RejectedGateRow]:
    if report is None:
        return []
    return [
        RejectedGateRow(
            ticker=result.ticker,
            decision=result.decision.value,
            reason_codes=[code.value for code in result.reason_codes],
            detail=result.reason_summary() or None,
            first_flagged_on=_date_str(result.first_flagged_on),
            occurrences=result.occurrences,
        )
        for result in report.gated_out
    ]


def _tactical_dashboard(report: SetupReport | None) -> TacticalDashboard:
    if report is None:
        return TacticalDashboard()
    dashboard = report.tactical_dashboard()
    return TacticalDashboard(
        top_long=_setup_summary(dashboard.get("top_long")),
        top_short=_setup_summary(dashboard.get("top_short")),
        top_volatility=_setup_summary(dashboard.get("top_volatility")),
    )


def _conditionality_rows(report: SetupReport | None) -> list[ConditionalityRow]:
    if report is None:
        return []
    rows: list[ConditionalityRow] = []
    for result in report.results:
        rejection_rows = [
            {
                "setup_type": rejection.setup_type.value,
                "code": rejection.code.value,
                "detail": rejection.detail,
            }
            for rejection in result.rejections
        ]
        for setup in result.setups:
            invalidation = setup.invalidation.to_dict() if setup.invalidation else None
            conditions = list(invalidation.get("conditions", [])) if invalidation else []
            rows.append(
                ConditionalityRow(
                    ticker=setup.ticker,
                    setup_type=setup.setup_type.value,
                    decision=setup.decision.value,
                    catalyst=_catalyst_dict(setup.catalyst),
                    invalidation=invalidation,
                    triggers=list(setup.triggers),
                    conditions=conditions,
                    warnings=list(setup.warnings),
                    rejections=rejection_rows,
                )
            )
        if not result.setups and rejection_rows:
            rows.append(
                ConditionalityRow(
                    ticker=result.ticker,
                    setup_type="unavailable",
                    decision="watchlist",
                    rejections=rejection_rows,
                )
            )
    return rows


def _trading_ideas(
    *,
    tickers: Sequence[str],
    gates: Mapping[str, CandidateGateResult],
    scores: Mapping[str, ScoringResult],
    setup_results: Mapping[str, CandidateSetupResult],
) -> list[TradingIdeaRow]:
    rows: list[TradingIdeaRow] = []
    for ticker in tickers:
        gate = gates.get(ticker)
        score = scores.get(ticker)
        setup_result = setup_results.get(ticker)
        setup = _representative_setup(setup_result)
        status = _idea_status(gate=gate, score=score, setup_result=setup_result, setup=setup)
        grade = (
            compute_grade(
                setup,
                confidence_multiplier=(
                    gate.confidence_multiplier if gate is not None else 1.0
                ),
            )
            if score is not None and setup is not None and status != "UNSCORED"
            else None
        )
        if grade is not None and grade.score is None and grade.reasons:
            grade_reason = "; ".join(grade.reasons)
        else:
            grade_reason = None

        rows.append(
            TradingIdeaRow(
                ticker=ticker,
                setup_type=setup.setup_type.value if setup is not None else None,
                grade_letter=grade.letter if grade is not None else None,
                grade_score=grade.score if grade is not None else None,
                thesis_probability=(
                    grade.thesis_probability if grade is not None else None
                ),
                thesis_band=grade.thesis_band if grade is not None else None,
                s_cte=(
                    setup.s_cte
                    if setup is not None
                    else (score.s_cte if score is not None else None)
                ),
                tier=_idea_tier(score=score, setup_result=setup_result, setup=setup),
                status=status,
                catalyst=_catalyst_dict(
                    setup.catalyst
                    if setup is not None
                    else (gate.primary_catalyst if gate is not None else None)
                ),
                blocked_reason=(
                    None
                    if status == "TRADEABLE"
                    else _blocked_reason(
                        gate=gate,
                        score=score,
                        setup_result=setup_result,
                        grade_reason=grade_reason,
                    )
                ),
                grade_penalties=grade.penalties if grade is not None else [],
                headline=_idea_headline(ticker=ticker, setup=setup, status=status),
            )
        )

    return sorted(rows, key=_idea_sort_key)


def _representative_setup(result: CandidateSetupResult | None) -> Setup | None:
    if result is None or not result.setups:
        return None
    tradeable = result.tradeable_setups
    if tradeable:
        return tradeable[0]
    watchlist = [
        setup
        for setup in result.setups
        if setup.decision is SetupDecision.WATCHLIST
        or setup.setup_type is SetupType.WATCHLIST_NO_TRADE
    ]
    return watchlist[0] if watchlist else result.setups[0]


def _idea_status(
    *,
    gate: CandidateGateResult | None,
    score: ScoringResult | None,
    setup_result: CandidateSetupResult | None,
    setup: Setup | None,
) -> str:
    if score is None:
        if gate is not None and not gate.is_scored:
            return "WATCHLIST" if gate.decision.value == "watchlist" else "BLOCKED"
        return "UNSCORED"

    if setup is not None:
        if setup.is_tradeable:
            return "TRADEABLE"
        if (
            setup.decision is SetupDecision.WATCHLIST
            or setup.setup_type is SetupType.WATCHLIST_NO_TRADE
        ):
            return "WATCHLIST"

    if setup_result is not None and setup_result.rejections:
        return "BLOCKED"
    if gate is not None and not gate.is_scored:
        return "WATCHLIST" if gate.decision.value == "watchlist" else "BLOCKED"
    return "BLOCKED"


def _idea_tier(
    *,
    score: ScoringResult | None,
    setup_result: CandidateSetupResult | None,
    setup: Setup | None,
) -> str | None:
    if setup is not None:
        return setup.tier.value
    if score is not None:
        return score.tier.value
    if setup_result is not None:
        return setup_result.tier.value
    return None


def _blocked_reason(
    *,
    gate: CandidateGateResult | None,
    score: ScoringResult | None,
    setup_result: CandidateSetupResult | None,
    grade_reason: str | None,
) -> str:
    causes: list[str] = []
    if score is None:
        if gate is None or gate.is_scored:
            causes.append("missing scoring result")
    else:
        causes.extend(
            f"missing required component: {component}"
            for component in score.missing_required
        )
        causes.extend(score.tier_reasons)
    if setup_result is not None:
        causes.extend(setup_result.tier_floors)
    if grade_reason:
        causes.append(grade_reason)

    deduped = _dedupe_non_empty(causes)
    if deduped:
        return "; ".join(deduped)

    rejection = _top_rejection(setup_result)
    if rejection is not None:
        return f"{_humanize(rejection.code.value)}: {rejection.detail}"
    if gate is not None and gate.reason_summary():
        return gate.reason_summary()
    if gate is not None and not gate.is_scored:
        return f"gate decision {gate.decision.value}"
    return "no tradeable setup emitted"


def _top_rejection(setup_result: CandidateSetupResult | None) -> Any | None:
    if setup_result is None or not setup_result.rejections:
        return None
    return next(
        (
            rejection
            for rejection in setup_result.rejections
            if rejection.code.value != "tier_c"
        ),
        setup_result.rejections[0],
    )


def _idea_headline(*, ticker: str, setup: Setup | None, status: str) -> str:
    if setup is not None:
        return f"{ticker} {_humanize(setup.setup_type.value)}"
    if status == "UNSCORED":
        return f"{ticker} unscored"
    return f"{ticker} no setup"


def _idea_sort_key(row: TradingIdeaRow) -> tuple[bool, float, str]:
    return (row.grade_score is None, -(row.grade_score or 0.0), row.ticker)


def _dedupe_non_empty(values: Sequence[str | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            deduped.append(cleaned)
    return deduped


def _ticker_section(
    *,
    ticker: str,
    gate: CandidateGateResult | None,
    score: ScoringResult | None,
    components: Sequence[ComponentResult],
    setup_result: CandidateSetupResult | None,
    evidence: Sequence[EvidenceLedgerRow],
    data_mode: str,
) -> PerTickerSection:
    return PerTickerSection(
        ticker=ticker,
        gate=_gate_summary(gate) if gate is not None else None,
        score=score.disclosure() if score is not None else None,
        components=[
            _component_summary(component, data_mode=data_mode)
            for component in components
        ],
        setups=[setup.to_dict() for setup in setup_result.setups] if setup_result else [],
        setup_rejections=[
            {
                "setup_type": rejection.setup_type.value,
                "code": rejection.code.value,
                "detail": rejection.detail,
            }
            for rejection in (setup_result.rejections if setup_result else [])
        ],
        evidence=list(evidence),
    )


def _gate_summary(result: CandidateGateResult) -> dict[str, Any]:
    return {
        "ticker": result.ticker,
        "decision": result.decision.value,
        "horizon_days": result.horizon_days,
        "window_start": result.window_start.isoformat(),
        "window_end": result.window_end.isoformat(),
        "reason_codes": [code.value for code in result.reason_codes],
        "reasons": [reason.detail for reason in result.reasons],
        "flags": [flag.code.value for flag in result.flags],
        "primary_catalyst": _catalyst_dict(result.primary_catalyst),
        "permitted_instruments": [instrument.value for instrument in result.permitted_instruments],
        "blocked_instruments": [instrument.value for instrument in result.blocked_instruments],
        "leverage_allowed": result.leverage_allowed,
        "requires_borrow_verification": result.requires_borrow_verification,
        "earnings_in_horizon": result.earnings_in_horizon,
        "confidence_multiplier": result.confidence_multiplier,
    }


def _component_summary(result: ComponentResult, *, data_mode: str) -> dict[str, Any]:
    summary = result.to_dict()
    legs_defined = len(result.sub_scores)
    legs_scored = sum(
        1
        for sub_score in result.sub_scores
        if sub_score.score is not None
        and result.weights_used.get(sub_score.name, 0.0) > 0.0
    )
    summary["legs_defined"] = legs_defined
    summary["legs_scored"] = legs_scored
    summary["legs_summary"] = f"{legs_scored} of {legs_defined} legs"
    summary["absent_legs"] = [
        {
            "name": sub_score.name,
            "reason": _absent_leg_reason(result, sub_score.name, sub_score.na_reason),
        }
        for sub_score in result.sub_scores
        if sub_score.score is None
    ]
    if data_mode == "fixture":
        summary["leg_count_note"] = (
            "fixture leg counts describe the fixture, not live sourcing"
        )
    summary["source_rows"] = list(result.source_rows)
    return summary


def _absent_leg_reason(
    result: ComponentResult, leg_name: str, na_reason: str | None
) -> str:
    if na_reason:
        return na_reason
    needle = leg_name.lower()
    for diagnostic in result.diagnostics:
        if needle in diagnostic.lower():
            return diagnostic
    if result.na_reason:
        return result.na_reason
    if result.diagnostics:
        return result.diagnostics[0]
    return "unavailable"


def _setup_summary(setup: Setup | None) -> dict[str, Any] | None:
    if setup is None:
        return None
    data = setup.to_dict()
    data["one_liner"] = setup.one_liner()
    return data


def _catalyst_dict(catalyst: Any | None) -> dict[str, Any] | None:
    if catalyst is None:
        return None
    return {
        "name": catalyst.name,
        "date": catalyst.event_date.isoformat(),
        "status": catalyst.status.value if hasattr(catalyst.status, "value") else str(catalyst.status),
        "kind": getattr(catalyst, "kind", None),
        "source": getattr(catalyst, "source", None),
    }


def _evidence_row(row: Mapping[str, Any]) -> EvidenceLedgerRow:
    status = row.get("validation_status", "verified")
    if hasattr(status, "value"):
        status = status.value
    return EvidenceLedgerRow(
        ticker=str(row.get("ticker") or "*").strip().upper() or "*",
        component=str(row["component"]),
        field_name=str(row["field_name"]),
        field_value=str(row["field_value"]),
        source=str(row.get("source") or "computed"),
        venue=str(row.get("venue") or "*"),
        as_of=_date_str(row.get("as_of")),
        endpoint_or_file=str(row.get("endpoint_or_file") or ""),
        validation_status=str(status),
        note=row.get("note"),
    )


def _prior_row(row: Mapping[str, Any]) -> PriorScorecardRow:
    return PriorScorecardRow(
        ticker=str(row["ticker"]),
        snap_date=_date_str(row.get("snap_date")),
        component_scores=dict(row.get("component_scores") or {}),
        cte_score=row.get("cte_score"),
        confidence_tier=row.get("confidence_tier"),
        expression_class=row.get("expression_class"),
    )


def _market_point(point: MarketOverviewPoint | Mapping[str, Any]) -> MarketOverviewPoint:
    if isinstance(point, MarketOverviewPoint):
        return point
    data = dict(point)
    data["as_of"] = _date_str(data.get("as_of"))
    return MarketOverviewPoint.model_validate(data)


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date_type)):
        return value.isoformat()
    return str(value)


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip()


def all_source_labels(payload: DashboardPayload) -> list[str]:
    """Source labels made available to prompt templates."""
    labels: set[str] = set()
    labels.update(point.source for point in payload.market_overview)
    labels.update(row.source for row in payload.evidence_ledger)
    for section in payload.per_ticker_sections:
        for component in section.components:
            for sub in component.get("sub_scores", []):
                source = sub.get("source")
                if source:
                    labels.add(str(source))
    return sorted(labels)
