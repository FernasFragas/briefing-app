from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import sqrt

import pytest

from briefing_app.config import GateSettings, StrategySettings
from briefing_app.models.candidate import Catalyst, Direction, Instrument
from briefing_app.models.scoring import ComponentScore, ConfidenceTier, ScoringResult
from briefing_app.options_math import (
    DistributionPoint,
    ExpectedMove,
    ImpliedDistribution,
    MeasuredSigmaRange,
    OiCluster,
    OptionQuote,
    OptionsStructureResult,
    RealizedVolatility,
    RiskReversal25D,
    ShortBorrowMetrics,
    build_measured_sigma_range,
    range_from_points,
)
from briefing_app.strategy import (
    InvalidationBasis,
    RejectionCode,
    SetupContext,
    SetupDecision,
    SetupType,
    build_invalidation,
    build_scenario_table,
    check_leverage,
    evaluate_candidate_setups,
    run_strategy_engine,
    to_setup_evidence_rows,
    to_setup_signal_rows,
)
from briefing_app.universe.gate import run_gate
from tests.conftest import RUN_DATE, make_candidate

AS_OF = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
EXPIRY = RUN_DATE + timedelta(days=7)


def test_scenario_table_uses_measured_branch_without_implied_distribution() -> None:
    table = build_scenario_table(
        ticker="TEST",
        measured_range=measured_range(),
        spot=100,
    )

    assert table.source == "measured_sigma"
    assert sum(row.probability for row in table.rows) == pytest.approx(1.0)
    assert table.probability_in_one_sigma > 0.60


def test_scenario_table_falls_back_when_implied_distribution_is_too_narrow() -> None:
    table = build_scenario_table(
        ticker="TEST",
        measured_range=measured_range(),
        spot=100,
        distribution=distribution(captured_mass=0.60),
    )

    assert table.source == "measured_sigma"
    assert "captured only" in table.diagnostics[0]
    assert all(row.implied_probability is None for row in table.rows)


def test_scenario_table_uses_well_covered_implied_distribution() -> None:
    table = build_scenario_table(
        ticker="TEST",
        measured_range=measured_range(),
        spot=100,
        distribution=distribution(captured_mass=0.95),
    )

    assert table.source == "implied_distribution"
    assert any(row.implied_probability is not None for row in table.rows)
    assert sum(row.probability for row in table.rows) == pytest.approx(1.0)


def test_invalidation_prefers_option_wall_inside_adverse_sigma_edge() -> None:
    wall = OiCluster(
        expiry=EXPIRY,
        strike=98,
        call_open_interest=100,
        put_open_interest=900,
        total_open_interest=1000,
        concentration=0.40,
    )

    invalidation = build_invalidation(
        direction=Direction.LONG,
        spot=100,
        measured_range=measured_range(event_multiplier=1.0),
        oi_clusters=[wall],
        catalyst=catalyst(),
        horizon_end=RUN_DATE + timedelta(days=10),
    )

    assert invalidation is not None
    assert invalidation.basis is InvalidationBasis.MIXED
    assert invalidation.primary_level == 98
    assert any("does not occur" in condition for condition in invalidation.conditions)


def test_leverage_guard_refuses_at_routine_move_boundary() -> None:
    common = {
        "leverage": 5.0,
        "days": 5,
        "catalyst_confirmed": True,
        "has_stop": True,
        "has_measured_range": True,
        "knockout_buffer": 0.5,
    }

    below = check_leverage(daily_vol_pct=9.99, **common)
    at_boundary = check_leverage(daily_vol_pct=10.0, **common)

    assert below.allowed is True
    assert below.simulation is not None and below.drag_pct is not None
    assert at_boundary.allowed is False
    assert "approaches" in at_boundary.blockers[0]


def test_short_premium_requires_iv_rank_strictly_above_threshold() -> None:
    at_boundary = evaluate_candidate_setups(
        context("V", 0.0, structure(iv_rank=70.0, vrp=0.05, event_multiplier=1.5)),
        run_date=RUN_DATE,
    )
    above_boundary = evaluate_candidate_setups(
        context("V", 0.0, structure(iv_rank=70.01, vrp=0.05, event_multiplier=1.5)),
        run_date=RUN_DATE,
    )

    assert RejectionCode.IV_RANK_OUT_OF_BAND in at_boundary.rejection_codes
    assert not at_boundary.tradeable_setups
    assert any(
        setup.setup_type is SetupType.SHORT_PREMIUM_IRON_CONDOR
        for setup in above_boundary.tradeable_setups
    )


def test_long_premium_requires_iv_rank_strictly_below_threshold() -> None:
    at_boundary = evaluate_candidate_setups(
        context("V", 0.0, structure(iv_rank=25.0, vrp=0.0, event_multiplier=1.5)),
        run_date=RUN_DATE,
    )
    below_boundary = evaluate_candidate_setups(
        context("V", 0.0, structure(iv_rank=24.99, vrp=0.0, event_multiplier=1.5)),
        run_date=RUN_DATE,
    )

    assert RejectionCode.IV_RANK_OUT_OF_BAND in at_boundary.rejection_codes
    assert any(
        setup.setup_type is SetupType.LONG_PREMIUM_STRADDLE
        for setup in below_boundary.tradeable_setups
    )


def test_event_directional_neutral_band_boundary_emits_vertical() -> None:
    neutral = evaluate_candidate_setups(
        context("E", 0.149, structure(event_multiplier=1.5)),
        run_date=RUN_DATE,
    )
    boundary = evaluate_candidate_setups(
        context("E", 0.15, structure(event_multiplier=1.5)),
        run_date=RUN_DATE,
    )

    assert RejectionCode.SCORE_TOO_WEAK in neutral.rejection_codes
    setup = only_tradeable(boundary)
    assert setup.setup_type is SetupType.EVENT_DIRECTIONAL_VERTICAL
    assert setup.horizon_days > 0
    assert setup.catalyst is not None and setup.catalyst.event_date == RUN_DATE + timedelta(days=3)
    assert setup.invalidation is not None
    assert setup.expression_class.value == "E"
    assert setup.tier is ConfidenceTier.A
    assert setup.instrument is Instrument.OPTIONS
    assert setup.evidence


def test_event_directional_strong_boundary_emits_long() -> None:
    result = evaluate_candidate_setups(
        context("E", 0.60, structure(event_multiplier=1.5)),
        run_date=RUN_DATE,
    )

    assert only_tradeable(result).setup_type is SetupType.EVENT_DIRECTIONAL_LONG


def test_event_vertical_respects_instrument_fit() -> None:
    result = evaluate_candidate_setups(
        context(
            "E",
            0.30,
            structure(event_multiplier=1.5),
            permitted_instruments=["shares"],
        ),
        run_date=RUN_DATE,
    )

    assert not result.tradeable_setups
    assert RejectionCode.NO_INSTRUMENT_FIT in result.rejection_codes


def test_borrow_dependent_short_requires_verified_borrow_evidence() -> None:
    result = evaluate_candidate_setups(
        context(
            "S",
            -0.30,
            structure(short_borrow=None, event_multiplier=1.5),
            direction="short",
            permitted_instruments=["shares"],
            borrow_source="IBKR shortable list",
        ),
        run_date=RUN_DATE,
    )

    assert not result.tradeable_setups
    assert RejectionCode.BORROW_EVIDENCE_MISSING in result.rejection_codes
    assert result.tier is ConfidenceTier.C


def test_borrow_dependent_short_emits_with_verified_borrow() -> None:
    result = evaluate_candidate_setups(
        context(
            "S",
            -0.30,
            structure(short_borrow=borrow_metrics(), event_multiplier=1.5),
            direction="short",
            permitted_instruments=["shares"],
            borrow_source="IBKR shortable list",
        ),
        run_date=RUN_DATE,
    )

    setup = only_tradeable(result)
    assert setup.setup_type is SetupType.BORROW_DEPENDENT_SHORT
    assert setup.direction is Direction.SHORT
    assert setup.instrument is Instrument.SHARES
    assert any(item.field_name == "borrow_verified" for item in setup.evidence)


def test_leveraged_event_setup_carries_drag_check() -> None:
    result = evaluate_candidate_setups(
        context(
            "E",
            0.75,
            structure(event_multiplier=1.5),
            permitted_instruments=["knock_out"],
        ),
        run_date=RUN_DATE,
    )

    setup = only_tradeable(result)
    assert setup.instrument is Instrument.KNOCK_OUT
    assert setup.leverage_check is not None and setup.leverage_check.allowed
    assert setup.leverage_check.simulation is not None
    assert any(item.field_name == "leverage_drag_pct" for item in setup.evidence)


def test_leveraged_event_setup_rejects_estimated_catalyst_even_if_gate_allows_it() -> None:
    result = evaluate_candidate_setups(
        context(
            "E",
            0.75,
            structure(event_multiplier=1.5),
            permitted_instruments=["knock_out"],
            catalyst_status="estimated",
            gate_settings=GateSettings(allow_leverage_on_estimated_catalyst=True),
        ),
        run_date=RUN_DATE,
        settings=StrategySettings(require_confirmed_catalyst_for_event=False),
    )

    assert not result.tradeable_setups
    assert RejectionCode.LEVERAGE_REFUSED in result.rejection_codes


def test_tactical_dashboard_excludes_tier_c_watchlist_setups() -> None:
    report = run_strategy_engine(
        [
            context("E", 0.75, structure(event_multiplier=1.5), ticker="GOOD"),
            context("E", 0.75, structure(has_measured_range=False), ticker="MISS"),
        ],
        run_date=RUN_DATE,
        run_id="fixture-run",
    )

    dashboard = report.tactical_dashboard()
    assert dashboard["top_long"] is not None
    assert dashboard["top_long"].ticker == "GOOD"
    assert all(setup is None or setup.tier is not ConfidenceTier.C for setup in dashboard.values())


def test_setup_rows_and_evidence_rows_match_t3_shapes() -> None:
    report = run_strategy_engine(
        [context("E", 0.75, structure(event_multiplier=1.5), ticker="GOOD")],
        run_date=RUN_DATE,
        run_id="fixture-run",
    )

    signal_rows = to_setup_signal_rows(report, run_id=7)
    evidence_rows = to_setup_evidence_rows(report, run_id=7)

    assert signal_rows[0]["run_id"] == 7
    assert signal_rows[0]["setup_type"] == SetupType.EVENT_DIRECTIONAL_LONG.value
    assert signal_rows[0]["decision"] == SetupDecision.CANDIDATE.value
    assert signal_rows[0]["scenario_probabilities"]
    assert evidence_rows
    assert all(row["component"] == "SETUP" for row in evidence_rows)


def context(
    expression_class: str,
    s_cte: float | None,
    option_structure: OptionsStructureResult,
    *,
    ticker: str = "TEST",
    direction: str = "long",
    permitted_instruments: list[str] | None = None,
    borrow_source: str | None = None,
    catalyst_status: str = "confirmed",
    gate_settings: GateSettings | None = None,
) -> SetupContext:
    candidate = make_candidate(
        ticker=ticker,
        direction=direction,
        expression_class=expression_class,
        permitted_instruments=permitted_instruments or ["shares", "options"],
        borrow_source=borrow_source,
        catalysts=[make_catalyst(status=catalyst_status)],
    )
    gate_result = run_gate(
        [candidate],
        run_date=RUN_DATE,
        settings=gate_settings or GateSettings(),
        run_id="gate-fixture",
    ).results[0]
    return SetupContext(
        gate_result=gate_result,
        score=score(ticker, expression_class, s_cte),
        structure=option_structure,
        option_quotes=liquid_quotes(ticker=ticker),
        risk_reversal_history=[-0.02, -0.01, 0.0, 0.01, 0.02],
    )


def score(
    ticker: str,
    expression_class: str,
    s_cte: float | None,
    *,
    tier: ConfidenceTier = ConfidenceTier.A,
) -> ScoringResult:
    components = [
        ComponentScore(component=name, score=component_score, required=True)
        for name, component_score in {
            "S_M": s_cte,
            "S_O": s_cte,
            "S_S": s_cte,
            "S_I": s_cte,
            "S_F": s_cte,
        }.items()
    ]
    return ScoringResult(
        ticker=ticker,
        expression_class=expression_class,
        geography="US",
        s_cte=s_cte,
        tier=tier,
        components=components,
    )


def structure(
    *,
    iv_rank: float = 50.0,
    vrp: float = 0.01,
    rr: float = 0.0,
    short_borrow: ShortBorrowMetrics | None = None,
    event_multiplier: float = 1.0,
    has_measured_range: bool = True,
) -> OptionsStructureResult:
    return OptionsStructureResult(
        ticker="TEST",
        as_of=AS_OF,
        spot=100,
        available=True,
        score=0.1,
        expected_moves={"weekly": expected_move()},
        realized_volatility={
            20: RealizedVolatility(
                lookback_days=20,
                trading_days=252,
                sample_count=20,
                daily_stdev=0.18 / sqrt(252),
                annualized_vol=0.18,
            )
        },
        measured_range=measured_range(event_multiplier=event_multiplier)
        if has_measured_range
        else None,
        iv_rank=iv_rank,
        variance_risk_premium=vrp,
        risk_reversal_25d=RiskReversal25D(
            expiry=EXPIRY,
            call_strike=105,
            put_strike=95,
            call_delta=0.25,
            put_delta=-0.25,
            call_iv=0.30,
            put_iv=0.30 - rr,
            rr_25d=rr,
        ),
        oi_clusters=(
            OiCluster(
                expiry=EXPIRY,
                strike=98,
                call_open_interest=100,
                put_open_interest=900,
                total_open_interest=1000,
                concentration=0.40,
            ),
        ),
        short_borrow=short_borrow,
    )


def measured_range(event_multiplier: float = 1.0) -> MeasuredSigmaRange:
    return build_measured_sigma_range(
        spot=100,
        realized_vol=0.20,
        lookback_days=20,
        horizon_days=5,
        event_multiplier=event_multiplier,
    )


def expected_move() -> ExpectedMove:
    return ExpectedMove(
        target_dte=7,
        expiry=EXPIRY,
        dte=7,
        atm_strike=100,
        call_mid=2,
        put_mid=2,
        iv_atm=0.20,
        straddle_points=4,
        straddle_pct=0.04,
        iv_points=3,
        iv_pct=0.03,
        divergence_pct=0.25,
        divergence_exceeds_threshold=False,
        one_sigma_straddle=range_from_points(100, 4),
        two_sigma_straddle=range_from_points(100, 8),
        one_sigma_iv=range_from_points(100, 3),
        two_sigma_iv=range_from_points(100, 6),
    )


def liquid_quotes(*, ticker: str = "TEST") -> list[OptionQuote]:
    quotes: list[OptionQuote] = []
    for index in range(10):
        strike = 80 + (index * 5)
        for option_type in ("C", "P"):
            quotes.append(
                OptionQuote(
                    ticker=ticker,
                    expiry=EXPIRY,
                    strike=strike,
                    option_type=option_type,
                    bid=1.0,
                    ask=1.1,
                    iv=0.25,
                    delta=0.25 if option_type == "C" else -0.25,
                    gamma=0.01,
                    open_interest=100,
                    volume=10,
                    as_of=AS_OF,
                )
            )
    return quotes


def distribution(*, captured_mass: float) -> ImpliedDistribution:
    points = tuple(
        DistributionPoint(
            strike=strike,
            density=0.01,
            cdf=cdf,
            probability_above=1.0 - cdf,
        )
        for strike, cdf in (
            (80.0, 0.05),
            (90.0, 0.20),
            (95.0, 0.35),
            (100.0, 0.50),
            (105.0, 0.65),
            (110.0, 0.80),
            (120.0, 0.95),
        )
    )
    return ImpliedDistribution(
        expiry=EXPIRY,
        dte=7,
        time_years=7 / 365,
        points=points,
        mean=100,
        forward=100,
        total_probability=1.0,
        captured_probability_mass=captured_mass,
        strike_low=80,
        strike_high=120,
    )


def catalyst() -> Catalyst:
    return Catalyst(
        name="Quarterly results",
        date=RUN_DATE + timedelta(days=3),
        status="confirmed",
        kind="earnings",
        source="Company IR",
    )


def make_catalyst(*, status: str = "confirmed") -> dict[str, object]:
    return {
        "name": "Quarterly results",
        "date": RUN_DATE + timedelta(days=3),
        "status": status,
        "kind": "earnings",
        "source": "Company IR",
    }


def borrow_metrics() -> ShortBorrowMetrics:
    return ShortBorrowMetrics(
        verified=True,
        score=-0.2,
        squeeze_risk_score=0.4,
        inputs_used=("short_interest_pct_float", "borrow_fee_pct"),
    )


def only_tradeable(result):
    assert len(result.tradeable_setups) == 1, result.rejection_summary()
    return result.tradeable_setups[0]
