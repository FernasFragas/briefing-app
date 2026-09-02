"""The setup rule engine.

Setups are generated in code. The LLM may explain a setup that fired; it never decides
one. Every rule evaluates in full and records its own refusal, so the briefing can
print "why not" next to "why" instead of showing a silent gap.

The floor from plan Phase 7 is enforced in one place - `_build_setup` - so no rule can
skip it: horizon, dated catalyst, invalidation, instrument fit, evidence, Tier A/B.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date as date_type, datetime
from math import sqrt
from typing import Any, Iterable, Sequence

from briefing_app.config import OptionFilterSettings, StrategySettings
from briefing_app.models.candidate import (
    Candidate,
    Catalyst,
    Direction,
    ExpressionClass,
    Instrument,
)
from briefing_app.models.gate import CandidateGateResult
from briefing_app.models.scoring import ConfidenceTier, Posture, ScoringResult
from briefing_app.options_math import (
    OptionQuote,
    OptionsStructureResult,
    mid_price,
    normalize_option_quotes,
    percentile_rank,
)
from briefing_app.strategy.invalidation import Invalidation, build_invalidation
from briefing_app.strategy.leverage import LeverageCheck, check_leverage
from briefing_app.strategy.models import (
    INSTRUMENT_PREFERENCE,
    SETUP_INSTRUMENTS,
    CandidateSetupResult,
    RejectionCode,
    Setup,
    SetupDecision,
    SetupEvidence,
    SetupRejection,
    SetupReport,
    SetupType,
)
from briefing_app.strategy.scenarios import ScenarioTable, build_scenario_table

TRADING_DAYS_PER_YEAR: int = 252


def make_run_id(run_date: date_type) -> str:
    return f"setups-{run_date.isoformat()}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class ChainLiquidity:
    """Whether the chain can actually carry a multi-leg structure."""

    quote_count: int
    liquid_count: int
    liquid_fraction: float
    ok: bool
    reasons: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return self.quote_count > 0

    def summary(self) -> str:
        if self.ok:
            return f"{self.liquid_count}/{self.quote_count} strikes pass the quote filters"
        return "; ".join(self.reasons) or "chain liquidity not established"


@dataclass
class SetupContext:
    """Everything the engine needs about one name, from the stages that own it.

    `structure` is the T5 `S_O` result and `score` the T7 composite. Either may be
    absent or degraded; the rules refuse rather than substitute.
    """

    gate_result: CandidateGateResult
    score: ScoringResult
    structure: OptionsStructureResult | None = None
    option_quotes: Sequence[OptionQuote | dict[str, Any]] = ()
    #: The name's own 25-delta risk-reversal history, for "materially away from history".
    risk_reversal_history: Sequence[float] = ()
    #: Events known to fall inside the expiry that the range does NOT model.
    unmodeled_catalysts: Sequence[Catalyst] = ()
    requested_leverage: float | None = None

    @property
    def candidate(self) -> Candidate:
        return self.gate_result.candidate

    @property
    def ticker(self) -> str:
        return self.gate_result.ticker


@dataclass
class _Evaluation:
    """Resolved inputs for one ticker, shared by every rule."""

    context: SetupContext
    settings: StrategySettings
    filters: OptionFilterSettings
    run_date: date_type
    tier: ConfidenceTier
    tier_floors: list[str] = field(default_factory=list)
    liquidity: ChainLiquidity | None = None
    scenario_table: ScenarioTable | None = None

    @property
    def candidate(self) -> Candidate:
        return self.context.candidate

    @property
    def ticker(self) -> str:
        return self.context.ticker

    @property
    def score(self) -> ScoringResult:
        return self.context.score

    @property
    def structure(self) -> OptionsStructureResult | None:
        structure = self.context.structure
        return structure if structure is not None and structure.available else None

    @property
    def s_cte(self) -> float | None:
        return self.score.s_cte

    @property
    def posture(self) -> Posture:
        return self.score.posture

    @property
    def catalyst(self) -> Catalyst | None:
        return self.context.gate_result.primary_catalyst

    @property
    def horizon_days(self) -> int:
        return self.context.gate_result.horizon_days

    @property
    def horizon_label(self) -> str:
        return f"{self.horizon_days}d"

    @property
    def spot(self) -> float | None:
        return self.structure.spot if self.structure else None

    @property
    def measured_range(self):
        return self.structure.measured_range if self.structure else None

    @property
    def iv_rank(self) -> float | None:
        return self.structure.iv_rank if self.structure else None

    @property
    def vrp(self) -> float | None:
        return self.structure.variance_risk_premium if self.structure else None

    @property
    def risk_reversal(self):
        return self.structure.risk_reversal_25d if self.structure else None

    @property
    def distribution(self):
        return self.structure.implied_distribution if self.structure else None

    @property
    def short_borrow(self):
        return self.structure.short_borrow if self.structure else None

    @property
    def borrow_verified(self) -> bool:
        borrow = self.short_borrow
        return borrow is not None and borrow.verified

    @property
    def daily_vol_pct(self) -> float | None:
        """Routine daily move, for the knock-out barrier comparison."""
        if not self.structure:
            return None
        realized = self.structure.realized_volatility.get(20)
        return realized.daily_stdev * 100.0 if realized is not None else None

    def reject(self, setup_type: SetupType, code: RejectionCode, detail: str) -> SetupRejection:
        return SetupRejection(
            ticker=self.ticker, setup_type=setup_type, code=code, detail=detail
        )


def evaluate_candidate_setups(
    context: SetupContext,
    *,
    run_date: date_type,
    settings: StrategySettings | None = None,
    filters: OptionFilterSettings | None = None,
) -> CandidateSetupResult:
    """Run every rule for one name and return what fired, plus every refusal."""

    settings = settings or StrategySettings()
    filters = filters or OptionFilterSettings()
    evaluation = _Evaluation(
        context=context,
        settings=settings,
        filters=filters,
        run_date=run_date,
        tier=context.score.tier,
    )

    outcomes: list[Setup | SetupRejection] = []
    gate_result = context.gate_result

    if not gate_result.is_scored:
        detail = gate_result.reason_summary() or f"gate decision {gate_result.decision.value}"
        outcomes.append(
            evaluation.reject(
                SetupType.WATCHLIST_NO_TRADE, RejectionCode.GATE_NOT_SCORED, detail
            )
        )
        return _collect(evaluation, outcomes)

    _apply_tier_floors(evaluation)
    evaluation.liquidity = _assess_chain_liquidity(
        context.option_quotes, filters, settings, as_of=context.structure.as_of if context.structure else None
    )
    evaluation.scenario_table = _build_scenarios(evaluation)

    if evaluation.tier is ConfidenceTier.C:
        outcomes.extend(_tier_floor_rejections(evaluation))
        outcomes.append(
            evaluation.reject(
                SetupType.WATCHLIST_NO_TRADE,
                RejectionCode.TIER_C,
                "; ".join(evaluation.tier_floors) or "required component unavailable",
            )
        )
        return _collect(evaluation, outcomes)

    expression_class = context.score.expression_class
    if expression_class is ExpressionClass.V:
        outcomes.append(_short_premium_rule(evaluation))
        outcomes.append(_long_premium_rule(evaluation))
        outcomes.append(_skew_rule(evaluation))
    elif expression_class is ExpressionClass.E:
        outcomes.append(_event_directional_rule(evaluation))
    elif expression_class is ExpressionClass.P:
        outcomes.append(_positional_long_rule(evaluation))
    elif expression_class is ExpressionClass.S:
        outcomes.append(_borrow_dependent_short_rule(evaluation))

    return _collect(evaluation, outcomes)


def run_strategy_engine(
    contexts: Iterable[SetupContext],
    *,
    run_date: date_type,
    settings: StrategySettings | None = None,
    filters: OptionFilterSettings | None = None,
    run_id: str | None = None,
) -> SetupReport:
    """Run the rule engine across the scored universe."""
    results = [
        evaluate_candidate_setups(
            context, run_date=run_date, settings=settings, filters=filters
        )
        for context in contexts
    ]
    return SetupReport(
        run_id=run_id or make_run_id(run_date), run_date=run_date, results=results
    )


# --- tiering, liquidity, scenarios ---------------------------------------------------


def _apply_tier_floors(evaluation: _Evaluation) -> None:
    """Universal Tier C floors from plan Phase 6, applied before any rule runs."""
    floors: list[str] = []

    if evaluation.measured_range is None:
        floors.append("no measured sigma range from real closes")
    if evaluation.catalyst is None:
        floors.append("no dated catalyst inside the holding window")
    if evaluation.score.expression_class is ExpressionClass.S and not evaluation.borrow_verified:
        floors.append("borrow-dependent short without verified borrow / short-interest evidence")
    if evaluation.s_cte is None:
        floors.append("no composite score")

    if floors:
        evaluation.tier = evaluation.tier.floor_to(ConfidenceTier.C)
        evaluation.tier_floors = floors


def _tier_floor_rejections(evaluation: _Evaluation) -> list[SetupRejection]:
    rejections: list[SetupRejection] = []
    if evaluation.s_cte is None:
        rejections.append(
            evaluation.reject(
                SetupType.WATCHLIST_NO_TRADE,
                RejectionCode.NO_SCORE,
                "no composite score",
            )
        )
    if evaluation.measured_range is None:
        rejections.append(
            evaluation.reject(
                SetupType.WATCHLIST_NO_TRADE,
                RejectionCode.NO_MEASURED_RANGE,
                "no measured sigma range from real closes",
            )
        )
    if evaluation.catalyst is None:
        rejections.append(
            evaluation.reject(
                SetupType.WATCHLIST_NO_TRADE,
                RejectionCode.NO_CATALYST_IN_HORIZON,
                "no dated catalyst inside the holding window",
            )
        )
    if evaluation.score.expression_class is ExpressionClass.S and not evaluation.borrow_verified:
        rejections.append(
            evaluation.reject(
                SetupType.BORROW_DEPENDENT_SHORT,
                RejectionCode.BORROW_EVIDENCE_MISSING,
                "borrow-dependent short without verified borrow / short-interest evidence",
            )
        )
    return rejections


def _assess_chain_liquidity(
    quotes: Sequence[OptionQuote | dict[str, Any]],
    filters: OptionFilterSettings,
    settings: StrategySettings,
    *,
    as_of: datetime | None = None,
) -> ChainLiquidity:
    """Count strikes that clear the quote filters, and say so when none were supplied."""
    normalized = normalize_option_quotes(list(quotes)) if quotes else []
    if not normalized:
        return ChainLiquidity(
            quote_count=0,
            liquid_count=0,
            liquid_fraction=0.0,
            ok=False,
            reasons=("no option quotes supplied; chain liquidity unverified",),
        )

    liquid = 0
    for quote in normalized:
        if quote.open_interest < filters.min_open_interest:
            continue
        if quote.volume < filters.min_volume:
            continue
        mid = mid_price(quote.bid, quote.ask)
        if mid <= 0.0:
            continue
        if ((quote.ask - quote.bid) / mid) > filters.max_bid_ask_width_pct:
            continue
        if as_of is not None and quote.as_of is not None:
            age_minutes = (as_of - quote.as_of).total_seconds() / 60.0
            if age_minutes > filters.max_quote_age_minutes:
                continue
        liquid += 1

    fraction = liquid / len(normalized)
    reasons: list[str] = []
    if len(normalized) < settings.min_chain_quotes:
        reasons.append(
            f"chain has {len(normalized)} quotes, below the {settings.min_chain_quotes} minimum"
        )
    if fraction < settings.min_liquid_strike_fraction:
        reasons.append(
            f"only {fraction:.0%} of strikes clear the quote filters, below "
            f"{settings.min_liquid_strike_fraction:.0%}"
        )
    return ChainLiquidity(
        quote_count=len(normalized),
        liquid_count=liquid,
        liquid_fraction=fraction,
        ok=not reasons,
        reasons=tuple(reasons),
    )


def _build_scenarios(evaluation: _Evaluation) -> ScenarioTable | None:
    measured_range = evaluation.measured_range
    if measured_range is None:
        return None
    return build_scenario_table(
        ticker=evaluation.ticker,
        measured_range=measured_range,
        spot=evaluation.spot,
        distribution=evaluation.distribution,
        horizon_days=evaluation.horizon_days,
    )


# --- volatility rules (class V) ------------------------------------------------------


def _short_premium_rule(evaluation: _Evaluation) -> Setup | SetupRejection:
    """`iv_rank > 70`, neutral score, contained skew, modelled events, liquid chain."""
    setup_type = SetupType.SHORT_PREMIUM_IRON_CONDOR
    settings = evaluation.settings

    if evaluation.structure is None:
        return evaluation.reject(
            setup_type, RejectionCode.NO_OPTIONS_STRUCTURE, "S_O is n/a: no verified chain"
        )
    if evaluation.iv_rank is None:
        return evaluation.reject(
            setup_type, RejectionCode.IV_RANK_UNAVAILABLE, "no IV rank history for this name"
        )
    if evaluation.iv_rank <= settings.short_premium_iv_rank_min:
        return evaluation.reject(
            setup_type,
            RejectionCode.IV_RANK_OUT_OF_BAND,
            f"IV rank {evaluation.iv_rank:.1f} is not above {settings.short_premium_iv_rank_min:.1f}",
        )
    if abs(evaluation.s_cte) >= settings.neutral_score_band:
        return evaluation.reject(
            setup_type,
            RejectionCode.SCORE_NOT_NEUTRAL,
            f"S_CTE {evaluation.s_cte:+.2f} is outside the neutral band "
            f"+/-{settings.neutral_score_band:.2f}",
        )

    risk_reversal = evaluation.risk_reversal
    if risk_reversal is None:
        return evaluation.reject(
            setup_type, RejectionCode.SKEW_UNAVAILABLE, "no 25-delta risk reversal available"
        )
    if abs(risk_reversal.rr_25d) > settings.extreme_skew_rr:
        return evaluation.reject(
            setup_type,
            RejectionCode.SKEW_EXTREME,
            f"25d risk reversal {risk_reversal.rr_25d:+.3f} exceeds "
            f"+/-{settings.extreme_skew_rr:.3f}; a symmetric condor is mispriced against it",
        )

    if evaluation.vrp is None:
        return evaluation.reject(
            setup_type, RejectionCode.VRP_NOT_SUPPORTIVE, "variance risk premium unavailable"
        )
    if evaluation.vrp <= settings.short_premium_min_vrp:
        return evaluation.reject(
            setup_type,
            RejectionCode.VRP_NOT_SUPPORTIVE,
            f"variance risk premium {evaluation.vrp:+.3f} is not above "
            f"{settings.short_premium_min_vrp:+.3f}: implied is not rich to realized",
        )

    unmodeled = _unmodeled_catalysts(evaluation)
    if unmodeled:
        return evaluation.reject(
            setup_type,
            RejectionCode.UNMODELED_CATALYST_IN_EXPIRY,
            "event risk inside the expiry is not modelled in the range: "
            + ", ".join(catalyst.label() for catalyst in unmodeled),
        )

    liquidity = evaluation.liquidity
    if liquidity is None or not liquidity.known:
        return evaluation.reject(
            setup_type,
            RejectionCode.LIQUIDITY_UNVERIFIED,
            "no option quotes supplied: a four-leg structure needs a verified liquid chain",
        )
    if not liquidity.ok:
        return evaluation.reject(setup_type, RejectionCode.ILLIQUID_CHAIN, liquidity.summary())

    return _build_setup(
        evaluation,
        setup_type=setup_type,
        direction=Direction.NEUTRAL,
        rationale=(
            f"IV rank {evaluation.iv_rank:.1f} with a neutral S_CTE "
            f"{evaluation.s_cte:+.2f} and contained skew: sell the wings inside the "
            "measured 2 sigma range"
        ),
        triggers=[
            f"iv_rank {evaluation.iv_rank:.1f} > {settings.short_premium_iv_rank_min:.1f}",
            f"|S_CTE| {abs(evaluation.s_cte):.2f} < {settings.neutral_score_band:.2f}",
            f"|rr_25d| {abs(risk_reversal.rr_25d):.3f} <= {settings.extreme_skew_rr:.3f}",
            f"vrp {evaluation.vrp:+.3f} > {settings.short_premium_min_vrp:+.3f}",
            liquidity.summary(),
        ],
        extra_evidence=[
            _evidence(evaluation, "iv_rank", evaluation.iv_rank),
            _evidence(evaluation, "variance_risk_premium", evaluation.vrp),
            _evidence(evaluation, "rr_25d", risk_reversal.rr_25d),
            _evidence(evaluation, "liquid_strike_fraction", liquidity.liquid_fraction),
        ],
    )


def _long_premium_rule(evaluation: _Evaluation) -> Setup | SetupRejection:
    """Cheap IV into a dated catalyst: straddle, or a calendar when the event is late."""
    settings = evaluation.settings
    catalyst = evaluation.catalyst
    setup_type = SetupType.LONG_PREMIUM_STRADDLE

    if evaluation.structure is None:
        return evaluation.reject(
            setup_type, RejectionCode.NO_OPTIONS_STRUCTURE, "S_O is n/a: no verified chain"
        )
    days_to_catalyst = (catalyst.event_date - evaluation.run_date).days
    if days_to_catalyst > settings.catalyst_window_days:
        return evaluation.reject(
            setup_type,
            RejectionCode.NO_CATALYST_IN_HORIZON,
            f"{catalyst.label()} is {days_to_catalyst}d out, beyond the "
            f"{settings.catalyst_window_days}d long-premium window",
        )

    cheap_by_rank = (
        evaluation.iv_rank is not None and evaluation.iv_rank < settings.long_premium_iv_rank_max
    )
    cheap_vs_event = evaluation.vrp is not None and evaluation.vrp < 0.0
    if not (cheap_by_rank or cheap_vs_event):
        rank_text = f"{evaluation.iv_rank:.1f}" if evaluation.iv_rank is not None else "n/a"
        vrp_text = f"{evaluation.vrp:+.3f}" if evaluation.vrp is not None else "n/a"
        return evaluation.reject(
            setup_type,
            RejectionCode.IV_RANK_OUT_OF_BAND,
            f"IV is not cheap: rank {rank_text} is not below "
            f"{settings.long_premium_iv_rank_max:.1f} and VRP {vrp_text} is not negative",
        )

    liquidity = evaluation.liquidity
    if liquidity is not None and liquidity.known and not liquidity.ok:
        return evaluation.reject(setup_type, RejectionCode.ILLIQUID_CHAIN, liquidity.summary())

    # A catalyst landing after the front expiry is a calendar, not a straddle.
    front = evaluation.structure.expected_moves.get("weekly")
    if front is not None and catalyst.event_date > front.expiry:
        setup_type = SetupType.LONG_PREMIUM_CALENDAR
        structure_note = (
            f"catalyst {catalyst.event_date.isoformat()} falls after the front expiry "
            f"{front.expiry.isoformat()}: own the back month, sell the front"
        )
    else:
        structure_note = "own the move through the event across one expiry"

    trigger = (
        f"iv_rank {evaluation.iv_rank:.1f} < {settings.long_premium_iv_rank_max:.1f}"
        if cheap_by_rank
        else f"vrp {evaluation.vrp:+.3f} < 0: implied is cheap to realized into the event"
    )
    return _build_setup(
        evaluation,
        setup_type=setup_type,
        direction=Direction.NEUTRAL,
        rationale=f"{trigger}; {structure_note}",
        triggers=[trigger, f"catalyst in {days_to_catalyst}d"],
        extra_evidence=[
            _evidence(evaluation, "iv_rank", evaluation.iv_rank),
            _evidence(evaluation, "variance_risk_premium", evaluation.vrp),
            _evidence(evaluation, "days_to_catalyst", days_to_catalyst),
        ],
    )


def _skew_rule(evaluation: _Evaluation) -> Setup | SetupRejection:
    """25d risk reversal materially away from its own history, with the tails to back it."""
    setup_type = SetupType.SKEW_STRUCTURE
    settings = evaluation.settings
    risk_reversal = evaluation.risk_reversal

    if evaluation.structure is None:
        return evaluation.reject(
            setup_type, RejectionCode.NO_OPTIONS_STRUCTURE, "S_O is n/a: no verified chain"
        )
    if risk_reversal is None:
        return evaluation.reject(
            setup_type, RejectionCode.SKEW_UNAVAILABLE, "no 25-delta risk reversal available"
        )

    history = [value for value in evaluation.context.risk_reversal_history if value is not None]
    if not history:
        return evaluation.reject(
            setup_type,
            RejectionCode.SKEW_UNAVAILABLE,
            "no risk-reversal history: 'materially away from own history' is unmeasurable",
        )

    rank = percentile_rank(risk_reversal.rr_25d, history)
    if rank is None or settings.skew_percentile_low < rank < settings.skew_percentile_high:
        return evaluation.reject(
            setup_type,
            RejectionCode.SKEW_NOT_EXTREME,
            f"25d risk reversal {risk_reversal.rr_25d:+.3f} sits at the "
            f"{rank:.0f}th percentile of its own history, inside "
            f"{settings.skew_percentile_low:.0f}-{settings.skew_percentile_high:.0f}",
        )

    direction = Direction.LONG if risk_reversal.rr_25d > 0 else Direction.SHORT
    table = evaluation.scenario_table
    if table is None:
        return evaluation.reject(
            setup_type, RejectionCode.NO_SCENARIO_TABLE, "no scenario table: range unavailable"
        )

    upside = table.probability_above_one_sigma
    downside = table.probability_below_one_sigma
    tail_edge = upside - downside if direction is Direction.LONG else downside - upside
    if tail_edge < settings.skew_min_tail_edge:
        return evaluation.reject(
            setup_type,
            RejectionCode.SKEW_NOT_EXTREME,
            f"skew points {direction.value} but the distribution gives that tail "
            f"{tail_edge:+.3f} of edge, below {settings.skew_min_tail_edge:.3f}",
        )

    if direction is Direction.SHORT:
        blocker = _bearish_borrow_blocker(evaluation)
        if blocker is not None:
            return evaluation.reject(setup_type, RejectionCode.BORROW_EVIDENCE_MISSING, blocker)

    return _build_setup(
        evaluation,
        setup_type=setup_type,
        direction=direction,
        rationale=(
            f"25d risk reversal {risk_reversal.rr_25d:+.3f} at the {rank:.0f}th percentile "
            f"of its own history, with {tail_edge:+.3f} of matching tail probability"
        ),
        triggers=[
            f"rr_25d percentile {rank:.0f}",
            f"tail edge {tail_edge:+.3f} >= {settings.skew_min_tail_edge:.3f}",
        ],
        extra_evidence=[
            _evidence(evaluation, "rr_25d", risk_reversal.rr_25d),
            _evidence(evaluation, "rr_25d_percentile", rank),
            _evidence(evaluation, "tail_edge", tail_edge),
        ],
    )


# --- directional rules (classes E, P, S) ---------------------------------------------


def _event_directional_rule(evaluation: _Evaluation) -> Setup | SetupRejection:
    """Directional edge into a confirmed dated catalyst, with the vol check attached."""
    settings = evaluation.settings
    catalyst = evaluation.catalyst
    posture = evaluation.posture
    score = evaluation.s_cte

    if posture is Posture.NEUTRAL:
        return evaluation.reject(
            SetupType.EVENT_DIRECTIONAL_VERTICAL,
            RejectionCode.SCORE_TOO_WEAK,
            f"S_CTE {score:+.2f} is inside the neutral band "
            f"+/-{settings.neutral_score_band:.2f}: no directional edge to express",
        )

    bullish = posture.is_bullish
    if posture.is_strong:
        setup_type = (
            SetupType.EVENT_DIRECTIONAL_LONG if bullish else SetupType.EVENT_DIRECTIONAL_PUT
        )
    else:
        setup_type = SetupType.EVENT_DIRECTIONAL_VERTICAL

    if settings.require_confirmed_catalyst_for_event and not catalyst.is_confirmed:
        return evaluation.reject(
            setup_type,
            RejectionCode.CATALYST_NOT_CONFIRMED,
            f"{catalyst.label()} is cadence-inferred; an event trade needs an IR or "
            "exchange-sourced date",
        )

    direction = Direction.LONG if bullish else Direction.SHORT
    if direction is Direction.SHORT:
        blocker = _bearish_borrow_blocker(evaluation)
        if blocker is not None:
            return evaluation.reject(setup_type, RejectionCode.BORROW_EVIDENCE_MISSING, blocker)

    if evaluation.scenario_table is None:
        return evaluation.reject(
            setup_type,
            RejectionCode.NO_SCENARIO_TABLE,
            "no scenario probabilities: the measured range is unavailable",
        )

    warnings: list[str] = []
    priced_in = _already_priced_in(evaluation)
    if priced_in is not None:
        warnings.append(priced_in)

    return _build_setup(
        evaluation,
        setup_type=setup_type,
        direction=direction,
        rationale=(
            f"S_CTE {score:+.2f} ({posture.value}) into {catalyst.label()}, "
            f"{(catalyst.event_date - evaluation.run_date).days}d out"
        ),
        triggers=[
            f"S_CTE {score:+.2f} {'>=' if bullish else '<='} "
            f"{'+' if bullish else '-'}{settings.neutral_score_band:.2f}",
            f"catalyst {catalyst.status.value}",
        ],
        warnings=warnings,
        extra_evidence=[
            _evidence(evaluation, "posture", posture.value),
            _evidence(evaluation, "catalyst_status", catalyst.status.value),
        ],
    )


def _positional_long_rule(evaluation: _Evaluation) -> Setup | SetupRejection:
    """Multi-week long where sentiment, insiders, and institutional flow all line up."""
    setup_type = SetupType.POSITIONAL_LONG
    settings = evaluation.settings
    score = evaluation.s_cte

    if score < settings.neutral_score_band:
        detail = (
            f"S_CTE {score:+.2f} is bearish; a multi-week short is class S and needs "
            "verified borrow"
            if score <= -settings.neutral_score_band
            else f"S_CTE {score:+.2f} is inside the neutral band "
            f"+/-{settings.neutral_score_band:.2f}"
        )
        code = (
            RejectionCode.CLASS_RULE_NOT_MET
            if score <= -settings.neutral_score_band
            else RejectionCode.SCORE_TOO_WEAK
        )
        return evaluation.reject(setup_type, code, detail)

    missing = [name for name in ("S_S", "S_I", "S_F") if evaluation.score.score_of(name) is None]
    if missing:
        return evaluation.reject(
            setup_type,
            RejectionCode.OWNERSHIP_EVIDENCE_MISSING,
            f"positional thesis needs {', '.join(missing)}: ownership, insider, and "
            "sentiment evidence are not all available",
        )

    return _build_setup(
        evaluation,
        setup_type=setup_type,
        direction=Direction.LONG,
        rationale=(
            f"S_CTE {score:+.2f} with sentiment {evaluation.score.score_of('S_S'):+.2f}, "
            f"insiders {evaluation.score.score_of('S_I'):+.2f}, and institutional flow "
            f"{evaluation.score.score_of('S_F'):+.2f} aligned"
        ),
        triggers=[f"S_CTE {score:+.2f} >= {settings.neutral_score_band:.2f}", "S_S/S_I/S_F available"],
        extra_evidence=[
            _evidence(evaluation, "s_s", evaluation.score.score_of("S_S")),
            _evidence(evaluation, "s_i", evaluation.score.score_of("S_I")),
            _evidence(evaluation, "s_f", evaluation.score.score_of("S_F")),
        ],
    )


def _borrow_dependent_short_rule(evaluation: _Evaluation) -> Setup | SetupRejection:
    """Negative score, verified borrow, dated catalyst, and squeeze risk stated openly."""
    setup_type = SetupType.BORROW_DEPENDENT_SHORT
    settings = evaluation.settings
    score = evaluation.s_cte

    if score > -settings.neutral_score_band:
        return evaluation.reject(
            setup_type,
            RejectionCode.SCORE_TOO_WEAK,
            f"S_CTE {score:+.2f} is not below -{settings.neutral_score_band:.2f}",
        )

    borrow = evaluation.short_borrow
    if borrow is None or not borrow.verified:
        return evaluation.reject(
            setup_type,
            RejectionCode.BORROW_EVIDENCE_MISSING,
            "no verified borrow / short-interest evidence",
        )

    missing = [name for name in ("S_S", "S_I", "S_F") if evaluation.score.score_of(name) is None]
    if missing:
        return evaluation.reject(
            setup_type,
            RejectionCode.OWNERSHIP_EVIDENCE_MISSING,
            f"short thesis needs {', '.join(missing)}: the class S required set is incomplete",
        )

    warnings: list[str] = []
    if borrow.squeeze_risk_score is not None:
        warnings.append(
            f"squeeze risk {borrow.squeeze_risk_score:.2f} from "
            f"{', '.join(borrow.inputs_used) or 'no numeric inputs'}"
        )

    return _build_setup(
        evaluation,
        setup_type=setup_type,
        direction=Direction.SHORT,
        rationale=(
            f"S_CTE {score:+.2f} with verified borrow into "
            f"{evaluation.catalyst.label()}"
        ),
        triggers=[
            f"S_CTE {score:+.2f} <= -{settings.neutral_score_band:.2f}",
            "borrow / short-interest verified",
        ],
        warnings=warnings,
        extra_evidence=[
            _evidence(
                evaluation,
                "borrow_verified",
                True,
                source=evaluation.candidate.borrow_source or "computed",
                validation_status="verified",
            ),
            _evidence(evaluation, "squeeze_risk_score", borrow.squeeze_risk_score),
        ],
    )


# --- shared construction -------------------------------------------------------------


def _build_setup(
    evaluation: _Evaluation,
    *,
    setup_type: SetupType,
    direction: Direction,
    rationale: str,
    triggers: Sequence[str] = (),
    warnings: Sequence[str] = (),
    extra_evidence: Sequence[SetupEvidence | None] = (),
) -> Setup | SetupRejection:
    """Apply the Phase 7 floor to a rule that fired, or turn it into a refusal."""

    instrument, alternatives = _select_instrument(evaluation, setup_type)
    if instrument is None:
        permitted = ", ".join(i.value for i in evaluation.context.gate_result.permitted_instruments)
        allowed = ", ".join(i.value for i in SETUP_INSTRUMENTS[setup_type])
        return evaluation.reject(
            setup_type,
            RejectionCode.NO_INSTRUMENT_FIT,
            f"{setup_type.value} needs one of [{allowed}]; the platform permits "
            f"[{permitted or 'none'}] for this name",
        )

    invalidation = build_invalidation(
        direction=direction,
        spot=evaluation.spot or 0.0,
        measured_range=evaluation.measured_range,
        oi_clusters=evaluation.structure.oi_clusters if evaluation.structure else (),
        catalyst=evaluation.catalyst,
        horizon_end=evaluation.context.gate_result.window_end,
        extra_conditions=_extra_failure_conditions(evaluation, direction),
    )
    if invalidation is None:
        return evaluation.reject(
            setup_type,
            RejectionCode.MISSING_INVALIDATION,
            "no invalidation level can be generated from the measured range or option walls",
        )

    leverage_check: LeverageCheck | None = None
    if _is_leveraged(instrument):
        leverage_check = _run_leverage_guard(evaluation, invalidation)
        if not leverage_check.allowed:
            return evaluation.reject(
                setup_type, RejectionCode.LEVERAGE_REFUSED, leverage_check.summary()
            )

    measured_range = evaluation.measured_range
    all_warnings = list(warnings)
    if leverage_check is not None:
        all_warnings.extend(leverage_check.warnings)
    if evaluation.scenario_table is not None:
        all_warnings.extend(
            f"implied and measured probabilities diverge on '{row.label}' "
            f"({row.divergence:+.3f})"
            for row in evaluation.scenario_table.diverging_rows
        )
    if evaluation.context.gate_result.confidence_multiplier < 1.0:
        all_warnings.append(
            f"crowded consensus trade: confidence x"
            f"{evaluation.context.gate_result.confidence_multiplier:g}"
        )

    evidence = _base_evidence(evaluation, invalidation)
    evidence.extend(item for item in extra_evidence if item is not None)
    if leverage_check is not None and leverage_check.simulation is not None:
        evidence.append(
            _evidence(evaluation, "leverage_drag_pct", leverage_check.simulation.drag_pct)
        )

    size_fraction = (
        evaluation.tier.size_fraction * evaluation.context.gate_result.confidence_multiplier
    )

    return Setup(
        ticker=evaluation.ticker,
        setup_type=setup_type,
        decision=SetupDecision.CANDIDATE,
        expression_class=evaluation.score.expression_class,
        direction=direction,
        horizon_days=evaluation.horizon_days,
        horizon_label=evaluation.horizon_label,
        tier=evaluation.tier,
        posture=evaluation.posture,
        s_cte=evaluation.s_cte,
        instrument=instrument,
        alternative_instruments=alternatives,
        catalyst=evaluation.catalyst,
        invalidation=invalidation,
        scenario_table=evaluation.scenario_table,
        range_low=measured_range.one_sigma.low if measured_range else None,
        range_high=measured_range.one_sigma.high if measured_range else None,
        leverage_check=leverage_check,
        rationale=rationale,
        triggers=list(triggers),
        warnings=all_warnings,
        evidence=evidence,
        size_fraction=size_fraction,
    )


def _select_instrument(
    evaluation: _Evaluation, setup_type: SetupType
) -> tuple[Instrument | None, list[Instrument]]:
    """Platform-permitted instruments that can express this setup, best first.

    `gate_result.permitted_instruments` has already been narrowed to the broker's list,
    the class fit, and - when the catalyst is only Estimated - the unleveraged subset.
    """
    allowed = set(SETUP_INSTRUMENTS[setup_type])
    fit = [i for i in evaluation.context.gate_result.permitted_instruments if i in allowed]
    if not fit:
        return None, []
    ordered = sorted(
        fit,
        key=lambda instrument: (
            INSTRUMENT_PREFERENCE.index(instrument)
            if instrument in INSTRUMENT_PREFERENCE
            else len(INSTRUMENT_PREFERENCE)
        ),
    )
    return ordered[0], ordered[1:]


def _run_leverage_guard(evaluation: _Evaluation, invalidation: Invalidation) -> LeverageCheck:
    """Drag simulation plus the catalyst / stop / range preconditions."""
    settings = evaluation.settings
    measured_range = evaluation.measured_range
    leverage = evaluation.context.requested_leverage or settings.default_leverage
    days = measured_range.horizon_days if measured_range is not None else evaluation.horizon_days
    return check_leverage(
        leverage=leverage,
        daily_vol_pct=evaluation.daily_vol_pct,
        days=max(1, days),
        # A flat underlying isolates the reset cost from any directional assumption.
        total_move_pct=0.0,
        catalyst_confirmed=evaluation.catalyst is not None and evaluation.catalyst.is_confirmed,
        has_stop=invalidation is not None,
        has_measured_range=measured_range is not None,
        knockout_buffer=settings.leverage_knockout_buffer,
        max_window_drag_pct=settings.max_window_drag_pct,
    )


def _bearish_borrow_blocker(evaluation: _Evaluation) -> str | None:
    """The plan authorises a short/put expression only with borrow evidence."""
    if not evaluation.settings.require_borrow_for_bearish:
        return None
    if evaluation.borrow_verified:
        return None
    return (
        "a bearish expression needs verified borrow / short-interest evidence; "
        f"{evaluation.candidate.borrow_source or 'no source'} is unverified"
    )


def _unmodeled_catalysts(evaluation: _Evaluation) -> list[Catalyst]:
    """In-horizon events the measured range was not widened for."""
    explicit = list(evaluation.context.unmodeled_catalysts)
    measured_range = evaluation.measured_range
    modelled = measured_range is not None and measured_range.event_multiplier > 1.0
    if modelled:
        return explicit
    return explicit + list(evaluation.context.gate_result.catalysts_in_horizon)


def _already_priced_in(evaluation: _Evaluation) -> str | None:
    """State whether the options market has already paid for the move."""
    structure = evaluation.structure
    measured_range = evaluation.measured_range
    if structure is None or measured_range is None:
        return None
    front = structure.expected_moves.get("weekly") or structure.expected_moves.get("monthly")
    if front is None:
        return None
    if front.straddle_pct >= measured_range.adjusted_sigma_pct:
        return (
            f"move may be priced in: {front.straddle_pct:.2%} expected move vs "
            f"{measured_range.adjusted_sigma_pct:.2%} measured sigma"
        )
    return (
        f"options underprice the measured range: {front.straddle_pct:.2%} expected move vs "
        f"{measured_range.adjusted_sigma_pct:.2%} measured sigma"
    )


def _extra_failure_conditions(evaluation: _Evaluation, direction: Direction) -> list[str]:
    conditions: list[str] = []
    if direction is Direction.SHORT and evaluation.borrow_verified:
        conditions.append("borrow becomes unavailable or the fee rises materially")
    if evaluation.score.missing_required:
        conditions.append(
            "required component still missing: " + ", ".join(evaluation.score.missing_required)
        )
    return conditions


def _base_evidence(evaluation: _Evaluation, invalidation: Invalidation) -> list[SetupEvidence]:
    """The fields every emitted setup stands on, whatever rule produced it."""
    measured_range = evaluation.measured_range
    rows: list[SetupEvidence | None] = [
        _evidence(evaluation, "s_cte", evaluation.s_cte),
        _evidence(evaluation, "tier", evaluation.tier.value),
        _evidence(evaluation, "expression_class", evaluation.score.expression_class.value),
        _evidence(evaluation, "spot", evaluation.spot),
        _evidence(evaluation, "horizon_days", evaluation.horizon_days),
        _evidence(evaluation, "invalidation", invalidation.description),
    ]
    if evaluation.catalyst is not None:
        rows.append(
            _evidence(
                evaluation,
                "catalyst",
                evaluation.catalyst.label(),
                source=evaluation.catalyst.source or "declared",
                validation_status=evaluation.catalyst.status.value,
            )
        )
    if measured_range is not None:
        rows.extend(
            [
                _evidence(evaluation, "measured_sigma_low", measured_range.one_sigma.low),
                _evidence(evaluation, "measured_sigma_high", measured_range.one_sigma.high),
                _evidence(evaluation, "measured_sigma_pct", measured_range.adjusted_sigma_pct),
            ]
        )
    if evaluation.scenario_table is not None:
        rows.append(
            _evidence(
                evaluation,
                "probability_in_one_sigma",
                evaluation.scenario_table.probability_in_one_sigma,
                note=f"scenario source: {evaluation.scenario_table.source}",
            )
        )
    return [row for row in rows if row is not None]


def _evidence(
    evaluation: _Evaluation,
    field_name: str,
    value: Any,
    *,
    source: str = "computed",
    validation_status: str = "computed",
    note: str | None = None,
) -> SetupEvidence | None:
    """One evidence row, or `None` when the value is `n/a` and there is nothing to record."""
    if value is None:
        return None
    return SetupEvidence(
        field_name=field_name,
        field_value=str(value),
        source=source,
        venue=evaluation.candidate.venue,
        as_of=evaluation.structure.as_of if evaluation.structure else None,
        validation_status=validation_status,
        note=note,
    )


def _is_leveraged(instrument: Instrument) -> bool:
    from briefing_app.models.candidate import DEFAULT_LEVERAGED_INSTRUMENTS

    return instrument in DEFAULT_LEVERAGED_INSTRUMENTS


def _collect(
    evaluation: _Evaluation, outcomes: Sequence[Setup | SetupRejection]
) -> CandidateSetupResult:
    """Split rule outcomes, cap the per-ticker count, and always leave a verdict behind."""
    setups = [outcome for outcome in outcomes if isinstance(outcome, Setup)]
    rejections = [outcome for outcome in outcomes if isinstance(outcome, SetupRejection)]

    setups.sort(key=_conviction_sort_key, reverse=True)
    limit = evaluation.settings.max_setups_per_ticker
    if len(setups) > limit:
        for dropped in setups[limit:]:
            rejections.append(
                evaluation.reject(
                    dropped.setup_type,
                    RejectionCode.CLASS_RULE_NOT_MET,
                    f"only the top {limit} setups per ticker are emitted",
                )
            )
        setups = setups[:limit]

    if not setups:
        setups.append(_watchlist_setup(evaluation, rejections))

    return CandidateSetupResult(
        ticker=evaluation.ticker,
        expression_class=evaluation.score.expression_class,
        tier=evaluation.tier,
        tier_floors=list(evaluation.tier_floors),
        setups=setups,
        rejections=rejections,
    )


def _watchlist_setup(
    evaluation: _Evaluation, rejections: Sequence[SetupRejection]
) -> Setup:
    """The no-trade verdict, carrying every reason the name did not produce a setup."""
    measured_range = evaluation.measured_range
    reasons = "; ".join(rejection.label() for rejection in rejections)
    return Setup(
        ticker=evaluation.ticker,
        setup_type=SetupType.WATCHLIST_NO_TRADE,
        decision=SetupDecision.WATCHLIST,
        expression_class=evaluation.score.expression_class,
        direction=evaluation.candidate.direction,
        horizon_days=evaluation.horizon_days,
        horizon_label=evaluation.horizon_label,
        tier=evaluation.tier,
        posture=evaluation.posture,
        s_cte=evaluation.s_cte,
        catalyst=evaluation.catalyst,
        scenario_table=evaluation.scenario_table,
        range_low=measured_range.one_sigma.low if measured_range else None,
        range_high=measured_range.one_sigma.high if measured_range else None,
        rationale=reasons or "no rule fired",
        warnings=list(evaluation.tier_floors),
        size_fraction=0.0,
    )


def _conviction_sort_key(setup: Setup) -> tuple[float, float]:
    return (
        abs(setup.s_cte) if setup.s_cte is not None else 0.0,
        1.0 if setup.catalyst is not None and setup.catalyst.is_confirmed else 0.0,
    )
