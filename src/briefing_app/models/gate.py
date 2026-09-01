"""Catalyst-gate result contract.

The gate runs BEFORE any component data pull. It answers "is this idea allowed to be
scored for execution?", never "which way?". Everything it emits is persisted so the
same rejected name is not rediscovered and re-pitched every cycle.
"""

from __future__ import annotations

from datetime import UTC, date as date_type, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from briefing_app.models.candidate import Candidate, Catalyst, Instrument


class GateDecision(StrEnum):
    """`ACCEPTED` names proceed to the component data pull and scoring."""

    ACCEPTED = "accepted"
    WATCHLIST = "watchlist"
    REJECTED = "rejected"

    @property
    def is_scored(self) -> bool:
        return self is GateDecision.ACCEPTED


#: Ordering used to resolve the decision when several rules fire on one candidate.
_DECISION_SEVERITY: dict[GateDecision, int] = {
    GateDecision.ACCEPTED: 0,
    GateDecision.WATCHLIST: 1,
    GateDecision.REJECTED: 2,
}


class GateReasonCode(StrEnum):
    """Why a candidate was demoted or rejected."""

    DUPLICATE_TICKER = "duplicate_ticker"
    NO_CATALYST_IN_HORIZON = "no_catalyst_in_horizon"
    CLASS_NOT_ENABLED = "class_not_enabled"
    NO_INSTRUMENT_FIT = "no_instrument_fit"
    LEVERAGE_REQUIRES_CONFIRMED_CATALYST = "leverage_requires_confirmed_catalyst"
    EU_OPTIONS_UNAVAILABLE = "eu_options_unavailable"
    BORROW_SOURCE_UNDECLARED = "borrow_source_undeclared"
    UNVERIFIED_THESIS = "unverified_thesis"


#: A demotion keeps the name in view; a rejection means it is structurally untradeable
#: on this platform and stays out until the candidate declaration itself changes.
DECISION_BY_REASON: dict[GateReasonCode, GateDecision] = {
    GateReasonCode.DUPLICATE_TICKER: GateDecision.REJECTED,
    GateReasonCode.NO_INSTRUMENT_FIT: GateDecision.REJECTED,
    GateReasonCode.NO_CATALYST_IN_HORIZON: GateDecision.WATCHLIST,
    GateReasonCode.CLASS_NOT_ENABLED: GateDecision.WATCHLIST,
    GateReasonCode.LEVERAGE_REQUIRES_CONFIRMED_CATALYST: GateDecision.WATCHLIST,
    GateReasonCode.EU_OPTIONS_UNAVAILABLE: GateDecision.WATCHLIST,
    GateReasonCode.BORROW_SOURCE_UNDECLARED: GateDecision.WATCHLIST,
    GateReasonCode.UNVERIFIED_THESIS: GateDecision.WATCHLIST,
}


class GateFlagCode(StrEnum):
    """Non-blocking findings carried into scoring, tiering, and the setup engine."""

    ESTIMATED_CATALYST_ONLY = "estimated_catalyst_only"
    LEVERAGE_BLOCKED_ESTIMATED_CATALYST = "leverage_blocked_estimated_catalyst"
    EARNINGS_IN_HORIZON = "earnings_in_horizon"
    EU_OPTIONS_MANUAL_CAPTURE = "eu_options_manual_capture"
    CROWDED_CONSENSUS_TRADE = "crowded_consensus_trade"
    UNVERIFIED_THESIS = "unverified_thesis"
    REQUIRES_BORROW_VERIFICATION = "requires_borrow_verification"
    REPEAT_REJECTION = "repeat_rejection"


class GateReason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: GateReasonCode
    detail: str


class GateFlag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: GateFlagCode
    detail: str


class CandidateGateResult(BaseModel):
    """One candidate's verdict, with everything downstream stages need to honour it."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    decision: GateDecision
    candidate: Candidate
    horizon_days: int
    window_start: date_type
    window_end: date_type
    reasons: list[GateReason] = Field(default_factory=list)
    flags: list[GateFlag] = Field(default_factory=list)
    catalysts_in_horizon: list[Catalyst] = Field(default_factory=list)
    primary_catalyst: Catalyst | None = None
    permitted_instruments: list[Instrument] = Field(default_factory=list)
    blocked_instruments: list[Instrument] = Field(default_factory=list)
    leverage_allowed: bool = False
    requires_borrow_verification: bool = False
    earnings_in_horizon: bool = False
    confidence_multiplier: float = 1.0
    first_flagged_on: date_type | None = None
    occurrences: int = 0

    @property
    def is_scored(self) -> bool:
        return self.decision.is_scored

    @property
    def reason_codes(self) -> list[GateReasonCode]:
        return [reason.code for reason in self.reasons]

    @property
    def flag_codes(self) -> list[GateFlagCode]:
        return [flag.code for flag in self.flags]

    @property
    def is_repeat(self) -> bool:
        return GateFlagCode.REPEAT_REJECTION in self.flag_codes

    def reason_summary(self) -> str:
        return "; ".join(reason.detail for reason in self.reasons)


class GateReport(BaseModel):
    """The full gate pass for one run: scored names, demotions, and rejections."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_date: date_type
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    default_horizon_days: int
    results: list[CandidateGateResult] = Field(default_factory=list)
    load_warnings: list[str] = Field(default_factory=list)
    load_errors: list[str] = Field(default_factory=list)

    def by_decision(self, decision: GateDecision) -> list[CandidateGateResult]:
        return [result for result in self.results if result.decision is decision]

    @property
    def accepted(self) -> list[CandidateGateResult]:
        return self.by_decision(GateDecision.ACCEPTED)

    @property
    def watchlist(self) -> list[CandidateGateResult]:
        return self.by_decision(GateDecision.WATCHLIST)

    @property
    def rejected(self) -> list[CandidateGateResult]:
        return self.by_decision(GateDecision.REJECTED)

    @property
    def gated_out(self) -> list[CandidateGateResult]:
        """Everything on the rejected-at-gate table: demotions and hard rejections."""
        return [result for result in self.results if not result.is_scored]

    def counts(self) -> dict[str, int]:
        return {
            "total": len(self.results),
            "accepted": len(self.accepted),
            "watchlist": len(self.watchlist),
            "rejected": len(self.rejected),
            "repeat": len([r for r in self.gated_out if r.is_repeat]),
        }


def resolve_decision(reasons: list[GateReason]) -> GateDecision:
    """Most severe reason wins. No reasons means the candidate is scored."""
    decision = GateDecision.ACCEPTED
    for reason in reasons:
        candidate_decision = DECISION_BY_REASON[reason.code]
        if _DECISION_SEVERITY[candidate_decision] > _DECISION_SEVERITY[decision]:
            decision = candidate_decision
    return decision


def to_candidate_gate_rows(
    report: GateReport, run_id: int | None = None
) -> list[dict[str, object]]:
    """Rows shaped for the `candidate_gate` table owned by T3.

    That table is keyed by `(run_id, ticker)`, so a ticker declared in more than one
    file collapses to the record the gate actually kept - the first one. The dropped
    duplicates are counted in `details` rather than silently overwriting the verdict.
    """
    rows: list[dict[str, object]] = []
    row_by_ticker: dict[str, dict[str, object]] = {}

    for result in report.results:
        existing = row_by_ticker.get(result.ticker)
        if existing is not None:
            details = existing["details"]
            assert isinstance(details, dict)
            details["duplicate_entries"] = int(details.get("duplicate_entries", 0)) + 1
            continue

        catalyst = result.primary_catalyst
        row: dict[str, object] = {
            "run_id": run_id,
            "ticker": result.ticker,
            "decision": result.decision.value,
            "reason": result.reason_summary() or None,
            "catalyst_name": catalyst.name if catalyst else None,
            "catalyst_date": catalyst.event_date if catalyst else None,
            "catalyst_status": catalyst.status.value if catalyst else None,
            "expression_class": result.candidate.expression_class.value,
            "details": {
                "reason_codes": [code.value for code in result.reason_codes],
                "flags": [code.value for code in result.flag_codes],
                "geography": result.candidate.geography.value,
                "venue": result.candidate.venue,
                "direction": result.candidate.direction.value,
                "source": result.candidate.source.value,
                "horizon_days": result.horizon_days,
                "window_start": result.window_start.isoformat(),
                "window_end": result.window_end.isoformat(),
                "permitted_instruments": [i.value for i in result.permitted_instruments],
                "blocked_instruments": [i.value for i in result.blocked_instruments],
                "leverage_allowed": result.leverage_allowed,
                "requires_borrow_verification": result.requires_borrow_verification,
                "earnings_in_horizon": result.earnings_in_horizon,
                "confidence_multiplier": result.confidence_multiplier,
                "catalysts_in_horizon": len(result.catalysts_in_horizon),
                "occurrences": result.occurrences,
                "first_flagged_on": (
                    result.first_flagged_on.isoformat() if result.first_flagged_on else None
                ),
            },
        }
        row_by_ticker[result.ticker] = row
        rows.append(row)

    return rows
