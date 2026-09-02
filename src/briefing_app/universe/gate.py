"""The catalyst gate: the hard filter that runs before any component data pull.

Rules implemented here are the ones decidable from the candidate declaration alone.
Data-dependent gates (Tier C after the pull, illiquid chain, unverified borrow) belong
to T5/T7/T8; this stage marks the obligations they must honour instead of guessing.

Every applicable rule is evaluated - the gate does not stop at the first failure - so a
rejected name carries its full reason list into the published rejected-at-gate table.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type, timedelta
from typing import Mapping

from briefing_app.config import GateSettings
from briefing_app.models.candidate import (
    OPTIONS_DEPENDENT_CLASSES,
    Candidate,
    Catalyst,
    Crowding,
    ExpressionClass,
    Instrument,
)
from briefing_app.models.gate import (
    CandidateGateResult,
    GateDecision,
    GateFlag,
    GateFlagCode,
    GateReason,
    GateReasonCode,
    GateReport,
    resolve_decision,
)
from briefing_app.universe.store import RejectionRecord


def make_run_id(run_date: date_type) -> str:
    return f"gate-{run_date.isoformat()}-{uuid.uuid4().hex[:8]}"


def _instrument_list(instruments: list[Instrument]) -> str:
    return ", ".join(instrument.value for instrument in instruments) or "none"


def _select_primary_catalyst(catalysts: list[Catalyst]) -> Catalyst | None:
    """Earliest in-horizon catalyst; a Confirmed date outranks an Estimated one."""
    if not catalysts:
        return None
    return min(catalysts, key=lambda c: (c.event_date, 0 if c.is_confirmed else 1))


def evaluate_candidate(
    candidate: Candidate,
    *,
    run_date: date_type,
    settings: GateSettings,
    history: Mapping[str, RejectionRecord] | None = None,
    duplicate_of: str | None = None,
) -> CandidateGateResult:
    """Apply every gate rule to one candidate and resolve a single decision."""
    reasons: list[GateReason] = []
    flags: list[GateFlag] = []

    horizon_days = candidate.effective_horizon_days(settings.default_horizon_days)
    window_start = run_date
    window_end = run_date + timedelta(days=horizon_days)
    in_horizon = candidate.catalysts_between(window_start, window_end)
    primary_catalyst = _select_primary_catalyst(in_horizon)
    has_confirmed = any(catalyst.is_confirmed for catalyst in in_horizon)
    earnings_in_horizon = any(catalyst.is_earnings for catalyst in in_horizon)

    if duplicate_of is not None:
        reasons.append(
            GateReason(
                code=GateReasonCode.DUPLICATE_TICKER,
                detail=f"already loaded from {duplicate_of}",
            )
        )

    # Rule: the declared expression class must be reachable on the current data plan.
    if candidate.expression_class not in settings.enabled_expression_classes:
        enabled = ", ".join(c.value for c in settings.enabled_expression_classes)
        reasons.append(
            GateReason(
                code=GateReasonCode.CLASS_NOT_ENABLED,
                detail=(
                    f"class {candidate.expression_class.value} is not enabled "
                    f"this run (enabled: {enabled or 'none'})"
                ),
            )
        )

    # Rule: no dated catalyst inside the horizon -> watchlist, never scored for execution.
    if not in_horizon:
        reasons.append(
            GateReason(
                code=GateReasonCode.NO_CATALYST_IN_HORIZON,
                detail=(
                    f"no dated catalyst between {window_start.isoformat()} and "
                    f"{window_end.isoformat()} ({horizon_days}d horizon)"
                ),
            )
        )

    # Rule: an Estimated date never authorises a leveraged expression.
    leverage_allowed = has_confirmed or settings.allow_leverage_on_estimated_catalyst
    permitted = list(candidate.permitted_instruments)
    blocked: list[Instrument] = []
    if not leverage_allowed:
        blocked = [i for i in permitted if settings.is_leveraged(i)]
        permitted = [i for i in permitted if not settings.is_leveraged(i)]
        if blocked:
            flags.append(
                GateFlag(
                    code=GateFlagCode.LEVERAGE_BLOCKED_ESTIMATED_CATALYST,
                    detail=(
                        f"leveraged instruments withdrawn ({_instrument_list(blocked)}): "
                        "no confirmed catalyst in horizon"
                    ),
                )
            )

    if in_horizon and not has_confirmed:
        flags.append(
            GateFlag(
                code=GateFlagCode.ESTIMATED_CATALYST_ONLY,
                detail="every in-horizon catalyst is Estimated (cadence-inferred)",
            )
        )

    # Rule: an idea that cannot be expressed on the user's platform is not an idea.
    class_instruments = settings.instruments_for_class(candidate.expression_class)
    fit = [i for i in permitted if i in class_instruments]
    if not fit:
        declared_fit = [i for i in candidate.permitted_instruments if i in class_instruments]
        if declared_fit and blocked:
            reasons.append(
                GateReason(
                    code=GateReasonCode.LEVERAGE_REQUIRES_CONFIRMED_CATALYST,
                    detail=(
                        f"only leveraged instruments ({_instrument_list(declared_fit)}) can "
                        f"express class {candidate.expression_class.value} here, and the "
                        "in-horizon catalyst is not Confirmed"
                    ),
                )
            )
        else:
            reasons.append(
                GateReason(
                    code=GateReasonCode.NO_INSTRUMENT_FIT,
                    detail=(
                        f"broker {candidate.broker or 'unset'} permits "
                        f"{_instrument_list(candidate.permitted_instruments)}; class "
                        f"{candidate.expression_class.value} needs one of "
                        f"{_instrument_list(list(class_instruments))}"
                    ),
                )
            )

    # Rule: classes that require S_O cannot run on a non-US name with no chain source.
    needs_chain = candidate.expression_class in OPTIONS_DEPENDENT_CLASSES
    if needs_chain and not candidate.geography.is_us:
        if settings.eu_options_track == "C":
            reasons.append(
                GateReason(
                    code=GateReasonCode.EU_OPTIONS_UNAVAILABLE,
                    detail=(
                        f"class {candidate.expression_class.value} requires a per-strike "
                        f"chain; no options capture track is available for "
                        f"{candidate.geography.value} names (track C -> S_O = n/a)"
                    ),
                )
            )
        elif settings.eu_options_track == "B":
            flags.append(
                GateFlag(
                    code=GateFlagCode.EU_OPTIONS_MANUAL_CAPTURE,
                    detail="S_O depends on a manual chain capture; caps the name at Tier B",
                )
            )

    # Rule: no short without a declared borrow / short-interest source.
    requires_borrow_verification = candidate.expression_class is ExpressionClass.S
    if requires_borrow_verification:
        if settings.require_borrow_source_for_shorts and not candidate.borrow_source:
            reasons.append(
                GateReason(
                    code=GateReasonCode.BORROW_SOURCE_UNDECLARED,
                    detail="class S candidate declares no borrow / short-interest source",
                )
            )
        else:
            flags.append(
                GateFlag(
                    code=GateFlagCode.REQUIRES_BORROW_VERIFICATION,
                    detail=(
                        f"borrow evidence from {candidate.borrow_source} must be verified "
                        "before any short setup is emitted"
                    ),
                )
            )

    # Rule: a thesis resting only on aggregator numbers is demoted or flagged unverified.
    if settings.require_thesis_source and not candidate.has_primary_thesis_support:
        detail = (
            "no primary source behind the thesis (exchange, regulator, filing, or company IR)"
        )
        if settings.unverified_thesis_action == "watchlist":
            reasons.append(
                GateReason(code=GateReasonCode.UNVERIFIED_THESIS, detail=detail)
            )
        else:
            flags.append(GateFlag(code=GateFlagCode.UNVERIFIED_THESIS, detail=detail))

    # Flag only: crowding changes sizing and the exit, not the decision.
    confidence_multiplier = 1.0
    telegraphed = any(catalyst.telegraphed for catalyst in in_horizon)
    if candidate.crowding is Crowding.CONSENSUS and telegraphed:
        confidence_multiplier = settings.crowded_confidence_multiplier
        flags.append(
            GateFlag(
                code=GateFlagCode.CROWDED_CONSENSUS_TRADE,
                detail=(
                    "consensus positioning with a widely telegraphed catalyst; confidence "
                    f"x{confidence_multiplier:g}"
                ),
            )
        )

    # Flag only: an earnings date inside the window must be modelled in the range (T5/T8).
    if earnings_in_horizon:
        flags.append(
            GateFlag(
                code=GateFlagCode.EARNINGS_IN_HORIZON,
                detail="earnings inside the holding window must be modelled in the range",
            )
        )

    decision = resolve_decision(reasons)

    gated_out = decision is not GateDecision.ACCEPTED
    first_flagged_on: date_type | None = run_date if gated_out else None
    occurrences = 1 if gated_out else 0
    if gated_out and history:
        record = history.get(candidate.ticker)
        if record is not None:
            first_flagged_on = record.first_flagged_on
            occurrences = record.occurrences + 1
            flags.append(
                GateFlag(
                    code=GateFlagCode.REPEAT_REJECTION,
                    detail=(
                        f"already gated out {record.occurrences}x since "
                        f"{record.first_flagged_on.isoformat()}"
                    ),
                )
            )

    return CandidateGateResult(
        ticker=candidate.ticker,
        decision=decision,
        candidate=candidate,
        horizon_days=horizon_days,
        window_start=window_start,
        window_end=window_end,
        reasons=reasons,
        flags=flags,
        catalysts_in_horizon=in_horizon,
        primary_catalyst=primary_catalyst,
        permitted_instruments=fit,
        blocked_instruments=blocked,
        leverage_allowed=leverage_allowed and bool(fit),
        requires_borrow_verification=requires_borrow_verification,
        earnings_in_horizon=earnings_in_horizon,
        confidence_multiplier=confidence_multiplier,
        first_flagged_on=first_flagged_on,
        occurrences=occurrences,
    )


def run_gate(
    candidates: list[Candidate],
    *,
    run_date: date_type,
    settings: GateSettings,
    history: Mapping[str, RejectionRecord] | None = None,
    run_id: str | None = None,
    load_warnings: list[str] | None = None,
    load_errors: list[str] | None = None,
) -> GateReport:
    """Gate the whole universe. The first record for a ticker wins; later ones are rejected."""
    results: list[CandidateGateResult] = []
    seen: dict[str, Candidate] = {}

    for candidate in candidates:
        duplicate_of: str | None = None
        first = seen.get(candidate.ticker)
        if first is not None:
            duplicate_of = first.origin or first.source.value
        else:
            seen[candidate.ticker] = candidate
        results.append(
            evaluate_candidate(
                candidate,
                run_date=run_date,
                settings=settings,
                history=history,
                duplicate_of=duplicate_of,
            )
        )

    return GateReport(
        run_id=run_id or make_run_id(run_date),
        run_date=run_date,
        default_horizon_days=settings.default_horizon_days,
        results=results,
        load_warnings=list(load_warnings or []),
        load_errors=list(load_errors or []),
    )
