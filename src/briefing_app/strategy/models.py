"""Setup contract: what the rule engine emits, and why it refused everything else.

Nothing here decides anything. The engine in `strategy/engine.py` fills these in, the
renderer (T9) reads them, and `to_setup_signal_rows` / `to_setup_evidence_rows` map
them onto the `setup_signal` and `evidence_ledger` tables owned by T3.
"""

from __future__ import annotations

from datetime import UTC, date as date_type, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from briefing_app.models.candidate import Catalyst, Direction, ExpressionClass, Instrument
from briefing_app.models.scoring import ConfidenceTier, Posture
from briefing_app.strategy.invalidation import Invalidation
from briefing_app.strategy.leverage import LeverageCheck
from briefing_app.strategy.scenarios import ScenarioTable


class SetupType(StrEnum):
    """The rule that fired. `WATCHLIST_NO_TRADE` is the only one Tier C can reach."""

    SHORT_PREMIUM_IRON_CONDOR = "short_premium_iron_condor"
    LONG_PREMIUM_STRADDLE = "long_premium_straddle"
    LONG_PREMIUM_CALENDAR = "long_premium_calendar"
    SKEW_STRUCTURE = "skew_structure"
    EVENT_DIRECTIONAL_LONG = "event_directional_long"
    EVENT_DIRECTIONAL_PUT = "event_directional_put"
    EVENT_DIRECTIONAL_VERTICAL = "event_directional_vertical"
    POSITIONAL_LONG = "positional_long"
    BORROW_DEPENDENT_SHORT = "borrow_dependent_short"
    WATCHLIST_NO_TRADE = "watchlist_no_trade"

    @property
    def is_volatility(self) -> bool:
        return self in (
            SetupType.SHORT_PREMIUM_IRON_CONDOR,
            SetupType.LONG_PREMIUM_STRADDLE,
            SetupType.LONG_PREMIUM_CALENDAR,
            SetupType.SKEW_STRUCTURE,
        )

    @property
    def is_tradeable(self) -> bool:
        return self is not SetupType.WATCHLIST_NO_TRADE


#: Instruments each setup can actually be expressed in, before the platform's own
#: permitted list and the class fit narrow it further.
SETUP_INSTRUMENTS: dict[SetupType, tuple[Instrument, ...]] = {
    SetupType.SHORT_PREMIUM_IRON_CONDOR: (Instrument.OPTIONS,),
    SetupType.LONG_PREMIUM_STRADDLE: (Instrument.OPTIONS,),
    SetupType.LONG_PREMIUM_CALENDAR: (Instrument.OPTIONS,),
    SetupType.SKEW_STRUCTURE: (Instrument.OPTIONS,),
    SetupType.EVENT_DIRECTIONAL_LONG: (
        Instrument.OPTIONS,
        Instrument.SHARES,
        Instrument.ETF,
        Instrument.KNOCK_OUT,
        Instrument.FACTOR_CERTIFICATE,
        Instrument.WARRANT,
        Instrument.FUTURES,
        Instrument.CFD,
    ),
    SetupType.EVENT_DIRECTIONAL_PUT: (Instrument.OPTIONS,),
    SetupType.EVENT_DIRECTIONAL_VERTICAL: (Instrument.OPTIONS,),
    SetupType.POSITIONAL_LONG: (Instrument.SHARES, Instrument.ETF, Instrument.OPTIONS),
    SetupType.BORROW_DEPENDENT_SHORT: (
        Instrument.SHARES,
        Instrument.CFD,
        Instrument.OPTIONS,
        Instrument.KNOCK_OUT,
        Instrument.FACTOR_CERTIFICATE,
    ),
    SetupType.WATCHLIST_NO_TRADE: (),
}

#: Preference order when several permitted instruments fit. Defined risk first, then
#: cash, then anything with embedded leverage - which still has to clear the guard.
INSTRUMENT_PREFERENCE: tuple[Instrument, ...] = (
    Instrument.OPTIONS,
    Instrument.SHARES,
    Instrument.ETF,
    Instrument.FUTURES,
    Instrument.KNOCK_OUT,
    Instrument.FACTOR_CERTIFICATE,
    Instrument.WARRANT,
    Instrument.CFD,
)


class SetupDecision(StrEnum):
    CANDIDATE = "candidate"
    WATCHLIST = "watchlist"


class RejectionCode(StrEnum):
    """Why a rule that could have fired did not produce an executable setup."""

    GATE_NOT_SCORED = "gate_not_scored"
    TIER_C = "tier_c"
    NO_SCORE = "no_score"
    NO_MEASURED_RANGE = "no_measured_range"
    NO_CATALYST_IN_HORIZON = "no_catalyst_in_horizon"
    CATALYST_NOT_CONFIRMED = "catalyst_not_confirmed"
    MISSING_INVALIDATION = "missing_invalidation"
    NO_INSTRUMENT_FIT = "no_instrument_fit"
    NO_OPTIONS_STRUCTURE = "no_options_structure"
    ILLIQUID_CHAIN = "illiquid_chain"
    LIQUIDITY_UNVERIFIED = "liquidity_unverified"
    IV_RANK_UNAVAILABLE = "iv_rank_unavailable"
    IV_RANK_OUT_OF_BAND = "iv_rank_out_of_band"
    SCORE_NOT_NEUTRAL = "score_not_neutral"
    SCORE_TOO_WEAK = "score_too_weak"
    SKEW_EXTREME = "skew_extreme"
    SKEW_NOT_EXTREME = "skew_not_extreme"
    SKEW_UNAVAILABLE = "skew_unavailable"
    UNMODELED_CATALYST_IN_EXPIRY = "unmodeled_catalyst_in_expiry"
    VRP_NOT_SUPPORTIVE = "vrp_not_supportive"
    BORROW_EVIDENCE_MISSING = "borrow_evidence_missing"
    OWNERSHIP_EVIDENCE_MISSING = "ownership_evidence_missing"
    LEVERAGE_REFUSED = "leverage_refused"
    NO_SCENARIO_TABLE = "no_scenario_table"
    CLASS_RULE_NOT_MET = "class_rule_not_met"


class SetupRejection(BaseModel):
    """One refused setup, kept so the briefing can print why it did not fire."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    setup_type: SetupType
    code: RejectionCode
    detail: str

    def label(self) -> str:
        return f"{self.setup_type.value}: {self.detail}"


class SetupEvidence(BaseModel):
    """One sourced or computed field the setup stands on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str
    field_value: str
    source: str = "computed"
    venue: str = "*"
    as_of: datetime | None = None
    validation_status: str = "computed"
    note: str | None = None


class Setup(BaseModel):
    """One emitted setup. A `CANDIDATE` decision carries the full required set.

    The plan's floor - horizon, dated catalyst, invalidation, instrument fit, evidence,
    Tier A/B - is enforced here rather than left to the caller, so a setup object that
    exists at all is one that passed it.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    ticker: str
    setup_type: SetupType
    decision: SetupDecision = SetupDecision.CANDIDATE
    expression_class: ExpressionClass
    direction: Direction
    horizon_days: int = Field(gt=0)
    horizon_label: str
    tier: ConfidenceTier
    posture: Posture
    s_cte: float | None = None
    instrument: Instrument | None = None
    alternative_instruments: list[Instrument] = Field(default_factory=list)
    catalyst: Catalyst | None = None
    invalidation: Invalidation | None = None
    scenario_table: ScenarioTable | None = None
    range_low: float | None = None
    range_high: float | None = None
    leverage_check: LeverageCheck | None = None
    rationale: str = ""
    triggers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: list[SetupEvidence] = Field(default_factory=list)
    size_fraction: float = 0.0

    @model_validator(mode="after")
    def _executable_setups_carry_the_required_set(self) -> "Setup":
        if self.decision is not SetupDecision.CANDIDATE:
            return self
        missing: list[str] = []
        if not self.tier.is_tradeable:
            missing.append("tier A/B")
        if self.catalyst is None:
            missing.append("dated catalyst")
        if self.invalidation is None:
            missing.append("invalidation")
        if self.instrument is None:
            missing.append("instrument")
        if not self.evidence:
            missing.append("evidence")
        if missing:
            raise ValueError(
                f"{self.ticker} {self.setup_type.value} cannot be a candidate setup "
                f"without: {', '.join(missing)}"
            )
        return self

    @property
    def catalyst_date(self) -> date_type | None:
        return self.catalyst.event_date if self.catalyst is not None else None

    @property
    def is_tradeable(self) -> bool:
        return self.decision is SetupDecision.CANDIDATE and self.tier.is_tradeable

    @property
    def is_leveraged(self) -> bool:
        return self.leverage_check is not None

    def one_liner(self) -> str:
        instrument = self.instrument.value if self.instrument else "n/a"
        catalyst = self.catalyst.label() if self.catalyst else "no dated catalyst"
        invalidation = self.invalidation.description if self.invalidation else "no invalidation"
        score = f"{self.s_cte:+.2f}" if self.s_cte is not None else "n/a"
        return (
            f"{self.ticker} {self.setup_type.value} [{self.expression_class.value}/"
            f"Tier {self.tier.value}] S_CTE {score} - {self.horizon_label}, {instrument}, "
            f"catalyst {catalyst}, invalid if {invalidation}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "setup_type": self.setup_type.value,
            "decision": self.decision.value,
            "expression_class": self.expression_class.value,
            "direction": self.direction.value,
            "horizon_days": self.horizon_days,
            "horizon_label": self.horizon_label,
            "tier": self.tier.value,
            "posture": self.posture.value,
            "s_cte": self.s_cte,
            "size_fraction": self.size_fraction,
            "instrument": self.instrument.value if self.instrument else None,
            "alternative_instruments": [i.value for i in self.alternative_instruments],
            "catalyst": (
                {
                    "name": self.catalyst.name,
                    "date": self.catalyst.event_date.isoformat(),
                    "status": self.catalyst.status.value,
                }
                if self.catalyst
                else None
            ),
            "invalidation": self.invalidation.to_dict() if self.invalidation else None,
            "range_low": self.range_low,
            "range_high": self.range_high,
            "scenarios": self.scenario_table.to_dict() if self.scenario_table else None,
            "leverage_check": self.leverage_check.to_dict() if self.leverage_check else None,
            "rationale": self.rationale,
            "triggers": list(self.triggers),
            "warnings": list(self.warnings),
            "evidence": [e.model_dump(mode="json") for e in self.evidence],
        }


class CandidateSetupResult(BaseModel):
    """Every rule outcome for one ticker: what fired and what refused to."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    expression_class: ExpressionClass
    tier: ConfidenceTier
    tier_floors: list[str] = Field(default_factory=list)
    setups: list[Setup] = Field(default_factory=list)
    rejections: list[SetupRejection] = Field(default_factory=list)

    @property
    def tradeable_setups(self) -> list[Setup]:
        return [setup for setup in self.setups if setup.is_tradeable]

    @property
    def rejection_codes(self) -> list[RejectionCode]:
        return [rejection.code for rejection in self.rejections]

    def rejection_summary(self) -> str:
        return "; ".join(rejection.label() for rejection in self.rejections)


class SetupReport(BaseModel):
    """The rule-engine pass for one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    run_date: date_type
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    results: list[CandidateSetupResult] = Field(default_factory=list)

    @property
    def setups(self) -> list[Setup]:
        return [setup for result in self.results for setup in result.setups]

    @property
    def tradeable_setups(self) -> list[Setup]:
        return [setup for setup in self.setups if setup.is_tradeable]

    @property
    def rejections(self) -> list[SetupRejection]:
        return [rejection for result in self.results for rejection in result.rejections]

    def counts(self) -> dict[str, int]:
        return {
            "tickers": len(self.results),
            "setups": len(self.setups),
            "tradeable": len(self.tradeable_setups),
            "watchlist": len([s for s in self.setups if s.decision is SetupDecision.WATCHLIST]),
            "rejections": len(self.rejections),
        }

    def tactical_dashboard(self) -> dict[str, Setup | None]:
        """Top long, top short, top volatility setup. Tier C can never appear here."""
        eligible = [setup for setup in self.tradeable_setups if setup.setup_type.is_tradeable]

        def best(candidates: list[Setup]) -> Setup | None:
            if not candidates:
                return None
            return max(candidates, key=_conviction_key)

        return {
            "top_long": best(
                [s for s in eligible if s.direction is Direction.LONG and not s.setup_type.is_volatility]
            ),
            "top_short": best(
                [s for s in eligible if s.direction is Direction.SHORT and not s.setup_type.is_volatility]
            ),
            "top_volatility": best([s for s in eligible if s.setup_type.is_volatility]),
        }


def _conviction_key(setup: Setup) -> tuple[float, float, float]:
    """Tier first, then absolute edge, then a confirmed catalyst inside the horizon."""
    return (
        setup.tier.size_fraction,
        abs(setup.s_cte) if setup.s_cte is not None else 0.0,
        1.0 if setup.catalyst is not None and setup.catalyst.is_confirmed else 0.0,
    )


def to_setup_signal_rows(report: SetupReport, run_id: int | None = None) -> list[dict[str, Any]]:
    """Rows shaped for the `setup_signal` table, keyed `(run_id, ticker, setup_type, horizon)`."""
    rows: list[dict[str, Any]] = []
    for result in report.results:
        for setup in result.setups:
            rows.append(
                {
                    "run_id": run_id,
                    "ticker": setup.ticker,
                    "setup_type": setup.setup_type.value,
                    "horizon": setup.horizon_label,
                    "expression_class": setup.expression_class.value,
                    "direction": setup.direction.value,
                    "confidence_tier": setup.tier.value,
                    "cte_score": setup.s_cte,
                    "instrument": setup.instrument.value if setup.instrument else None,
                    "invalidation": (
                        setup.invalidation.description if setup.invalidation else None
                    ),
                    "catalyst_date": setup.catalyst_date,
                    "range_low": setup.range_low,
                    "range_high": setup.range_high,
                    "scenario_probabilities": (
                        setup.scenario_table.probabilities() if setup.scenario_table else {}
                    ),
                    "decision": setup.decision.value,
                    "rationale": setup.rationale,
                    "details": {
                        "posture": setup.posture.value,
                        "size_fraction": setup.size_fraction,
                        "horizon_days": setup.horizon_days,
                        "triggers": list(setup.triggers),
                        "warnings": list(setup.warnings),
                        "tier_floors": list(result.tier_floors),
                        "alternative_instruments": [
                            i.value for i in setup.alternative_instruments
                        ],
                        "invalidation": (
                            setup.invalidation.to_dict() if setup.invalidation else None
                        ),
                        "scenarios": (
                            setup.scenario_table.to_dict() if setup.scenario_table else None
                        ),
                        "leverage_check": (
                            setup.leverage_check.to_dict() if setup.leverage_check else None
                        ),
                        "rejections": [
                            {"setup_type": r.setup_type.value, "code": r.code.value, "detail": r.detail}
                            for r in result.rejections
                        ],
                    },
                }
            )
    return rows


def to_setup_evidence_rows(
    report: SetupReport, run_id: int | None = None
) -> list[dict[str, Any]]:
    """Evidence-ledger rows for the `SETUP` component, one per field a setup stands on."""
    rows: list[dict[str, Any]] = []
    generated_at = report.generated_at
    for setup in report.setups:
        for item in setup.evidence:
            rows.append(
                {
                    "run_id": run_id,
                    "ticker": setup.ticker,
                    "component": "SETUP",
                    "field_name": f"{setup.setup_type.value}.{item.field_name}",
                    "field_value": item.field_value,
                    "source": item.source,
                    "venue": item.venue,
                    "as_of": item.as_of or generated_at,
                    "endpoint_or_file": "",
                    "validation_status": item.validation_status,
                    "note": item.note,
                }
            )
    return rows
