from __future__ import annotations

from datetime import UTC, date, datetime
from math import sqrt

import pytest

from briefing_app.components.base import ComponentResult
from briefing_app.models.scoring import ConfidenceTier, Posture
from briefing_app.options_math import (
    ExpectedMove,
    MeasuredSigmaRange,
    OptionsStructureResult,
    PutCallMetrics,
    RealizedVolatility,
    RiskReversal25D,
    ShortBorrowMetrics,
    build_measured_sigma_range,
    range_from_points,
)
from briefing_app.scoring import (
    SCORING_COMPONENT,
    ScoringContext,
    build_scoring_result,
    run_scoring,
    score_candidate,
    to_component_score_rows,
    to_daily_snapshot_row,
    to_scoring_evidence_rows,
)
from tests.conftest import RUN_DATE, make_candidate, make_catalyst

AS_OF = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
EXPIRY = date(2026, 9, 5)


def test_us_formula_uses_declared_weights_exactly() -> None:
    result = build_scoring_result(
        make_candidate(expression_class="E"),
        [
            component("S_M", 0.50),
            component("S_S", -0.10),
            component("S_I", 0.40),
            component("S_F", 0.80),
        ],
        options_structure=structure(score=0.20),
        run_date=RUN_DATE,
    )

    expected = (0.30 * 0.50) + (0.25 * 0.20) + (0.20 * -0.10) + (0.15 * 0.40) + (0.10 * 0.80)
    assert result.s_cte == pytest.approx(expected)
    assert result.weights_used == pytest.approx(
        {"S_M": 0.30, "S_O": 0.25, "S_S": 0.20, "S_I": 0.15, "S_F": 0.10}
    )
    assert result.tier is ConfidenceTier.A
    assert result.posture is Posture.MODERATE_BULLISH


def test_eu_formula_uses_eu_weights() -> None:
    result = build_scoring_result(
        make_candidate(
            geography="EU",
            venue="XETRA",
            expression_class="P",
            permitted_instruments=["shares"],
        ),
        [
            component("S_M", 0.40),
            component("S_S", 0.20),
            component("S_I", 0.10),
            component("S_F", -0.30),
        ],
        options_structure=structure(score=0.60),
        run_date=RUN_DATE,
    )

    expected = (0.35 * 0.40) + (0.30 * 0.60) + (0.20 * 0.20) + (0.10 * 0.10) + (0.05 * -0.30)
    assert result.s_cte == pytest.approx(expected)
    assert result.weight_profile == "EU"
    assert result.weights_used["S_M"] == pytest.approx(0.35)
    assert result.weights_used["S_O"] == pytest.approx(0.30)


def test_missing_optional_components_are_dropped_and_do_not_pull_score_to_neutral() -> None:
    result = build_scoring_result(
        make_candidate(expression_class="V"),
        [component("S_M", 1.0)],
        options_structure=structure(score=1.0),
        run_date=RUN_DATE,
    )

    assert result.s_cte == pytest.approx(1.0)
    assert result.weights_used == pytest.approx({"S_M": 0.30 / 0.55, "S_O": 0.25 / 0.55})
    assert result.component("S_S").weight_used == 0.0
    assert result.component("S_I").missing_reason == "component not supplied"
    assert result.tier is ConfidenceTier.A
    assert any("re-normalized" in note for note in result.notes)


def test_missing_required_component_scores_but_floors_to_tier_c() -> None:
    result = build_scoring_result(
        make_candidate(expression_class="E"),
        [component("S_M", 0.50)],
        run_date=RUN_DATE,
        measured_sigma_available=True,
    )

    assert result.s_cte == pytest.approx(0.50)
    assert result.tier is ConfidenceTier.C
    assert result.posture is Posture.MODERATE_BULLISH
    assert "S_O" in result.missing_required
    assert any("S_O required component unavailable" in reason for reason in result.tier_reasons)


def test_required_partial_or_aggregator_component_is_tier_b_not_tier_c() -> None:
    partial = build_scoring_result(
        make_candidate(expression_class="V"),
        [
            component("S_M", 0.20),
            component("S_O", 0.30, validation_status="partial", source_quality="primary"),
        ],
        run_date=RUN_DATE,
        measured_sigma_available=True,
    )
    aggregator = build_scoring_result(
        make_candidate(expression_class="V"),
        [
            component("S_M", 0.20),
            component("S_O", 0.30, source_quality="aggregator"),
        ],
        run_date=RUN_DATE,
        measured_sigma_available=True,
    )

    assert partial.tier is ConfidenceTier.B
    assert aggregator.tier is ConfidenceTier.B
    assert all(result.s_cte is not None for result in (partial, aggregator))


def test_unavailable_required_component_and_universal_floors_are_tier_c() -> None:
    no_sigma = build_scoring_result(
        make_candidate(expression_class="V"),
        [component("S_M", 0.20), component("S_O", 0.30)],
        run_date=RUN_DATE,
        measured_sigma_available=False,
    )
    no_catalyst = build_scoring_result(
        make_candidate(expression_class="P", catalysts=[], permitted_instruments=["shares"]),
        [
            component("S_M", 0.20),
            component("S_S", 0.10),
            component("S_I", 0.10),
            component("S_F", 0.10),
        ],
        run_date=RUN_DATE,
        measured_sigma_available=True,
    )
    no_invalidation = build_scoring_result(
        make_candidate(expression_class="V"),
        [component("S_M", 0.20), component("S_O", 0.30)],
        run_date=RUN_DATE,
        measured_sigma_available=True,
        invalidation_available=False,
    )

    assert no_sigma.tier is ConfidenceTier.C
    assert no_catalyst.tier is ConfidenceTier.C
    assert no_invalidation.tier is ConfidenceTier.C
    assert any("missing measured sigma" in reason for reason in no_sigma.tier_reasons)
    assert any("missing dated catalyst" in reason for reason in no_catalyst.tier_reasons)
    assert any("missing invalidation" in reason for reason in no_invalidation.tier_reasons)


def test_short_class_requires_verified_borrow_or_short_interest() -> None:
    missing_borrow = build_scoring_result(
        make_candidate(
            expression_class="S",
            direction="short",
            permitted_instruments=["shares"],
            borrow_source="IBKR shortable list",
        ),
        required_fundamental_components(-0.30),
        options_structure=structure(short_borrow=None),
        run_date=RUN_DATE,
    )
    verified_borrow = build_scoring_result(
        make_candidate(
            expression_class="S",
            direction="short",
            permitted_instruments=["shares"],
            borrow_source="IBKR shortable list",
        ),
        required_fundamental_components(-0.30),
        options_structure=structure(short_borrow=ShortBorrowMetrics(
            verified=True,
            score=-0.20,
            squeeze_risk_score=0.40,
            inputs_used=("borrow_fee_pct",),
        )),
        run_date=RUN_DATE,
    )

    assert missing_borrow.tier is ConfidenceTier.C
    assert any("missing borrow" in reason for reason in missing_borrow.tier_reasons)
    assert verified_borrow.tier is ConfidenceTier.A


@pytest.mark.parametrize(
    ("score", "posture"),
    [
        (0.60, Posture.STRONG_BULLISH),
        (0.15, Posture.MODERATE_BULLISH),
        (0.149, Posture.NEUTRAL),
        (-0.149, Posture.NEUTRAL),
        (-0.15, Posture.MODERATE_BEARISH),
        (-0.60, Posture.STRONG_BEARISH),
        (None, Posture.WATCHLIST),
    ],
)
def test_score_interpretation_boundaries(score: float | None, posture: Posture) -> None:
    assert Posture.from_score(score) is posture


def test_component_result_and_score_candidate_alias_are_supported() -> None:
    macro = ComponentResult(
        component="S_M",
        ticker="TEST",
        as_of=AS_OF,
        geography="US",
        available=True,
        score=0.25,
        validation_status="verified",
        source_quality="primary",
    )

    result = score_candidate(
        make_candidate(expression_class="V"),
        [macro],
        options_structure=structure(score=0.50),
        run_date=RUN_DATE,
    )

    assert result.score_of("S_M") == 0.25
    assert result.score_of("S_O") == 0.50
    assert result.tier is ConfidenceTier.A


def test_scoring_report_matrix_and_storage_rows() -> None:
    result = build_scoring_result(
        make_candidate(expression_class="E"),
        [
            component("S_M", 0.50),
            component("S_S", 0.10),
            component("S_I", 0.10),
            component("S_F", 0.10),
        ],
        options_structure=structure(score=0.40),
        run_date=RUN_DATE,
    )
    report = run_scoring(
        [
            ScoringContext(
                subject=make_candidate(ticker="ALT", expression_class="V"),
                components=[component("S_M", 0.20)],
                options_structure=structure(score=0.30),
            )
        ],
        run_date=RUN_DATE,
        run_id="scoring-fixture",
    )

    component_rows = to_component_score_rows(result, run_id=7)
    evidence_rows = to_scoring_evidence_rows(result, run_id=7, as_of=AS_OF)
    snapshot = to_daily_snapshot_row(
        result,
        snap_date=RUN_DATE,
        run_id=7,
        options_structure=structure(score=0.40),
    )

    assert len(component_rows) == 5
    assert next(row for row in component_rows if row["component"] == "S_O")["required"] is True
    assert any(
        row["component"] == SCORING_COMPONENT
        and row["field_name"] == "expression_class"
        and row["source"] == "candidate declaration"
        for row in evidence_rows
    )
    assert snapshot["cte_score"] == result.s_cte
    assert snapshot["confidence_tier"] == "A"
    assert snapshot["expression_class"] == "E"
    assert snapshot["iv_rank"] == 80.0
    assert snapshot["component_scores"]["S_O"] == 0.40
    assert report.counts()["tickers"] == 1
    assert report.matrix()[0]["required_set_verdict"] == "verified"


def component(
    name: str,
    score: float | None,
    *,
    validation_status: str = "verified",
    source_quality: str = "primary",
    missing_reason: str | None = None,
) -> dict[str, object]:
    return {
        "component": name,
        "score": score,
        "validation_status": validation_status,
        "source_quality": source_quality,
        "missing_reason": missing_reason,
        "as_of": RUN_DATE,
    }


def required_fundamental_components(value: float) -> list[dict[str, object]]:
    return [
        component("S_M", value),
        component("S_S", value),
        component("S_I", value),
        component("S_F", value),
    ]


def structure(
    *,
    score: float = 0.20,
    short_borrow: ShortBorrowMetrics | None = None,
) -> OptionsStructureResult:
    return OptionsStructureResult(
        ticker="TEST",
        as_of=AS_OF,
        spot=100,
        available=True,
        score=score,
        expected_moves={"weekly": expected_move(7), "monthly": expected_move(30)},
        realized_volatility={
            20: RealizedVolatility(
                lookback_days=20,
                trading_days=252,
                sample_count=20,
                daily_stdev=0.20 / sqrt(252),
                annualized_vol=0.20,
            )
        },
        measured_range=measured_range(),
        iv_rank=80.0,
        variance_risk_premium=0.05,
        risk_reversal_25d=RiskReversal25D(
            expiry=EXPIRY,
            call_strike=105,
            put_strike=95,
            call_delta=0.25,
            put_delta=-0.25,
            call_iv=0.32,
            put_iv=0.30,
            rr_25d=0.02,
        ),
        put_call=PutCallMetrics(
            expiry=EXPIRY,
            put_volume=100,
            call_volume=200,
            put_open_interest=1000,
            call_open_interest=800,
            volume_ratio=0.5,
            open_interest_ratio=1.25,
            volume_percentile=20,
            open_interest_percentile=80,
        ),
        short_borrow=short_borrow,
    )


def measured_range() -> MeasuredSigmaRange:
    return build_measured_sigma_range(
        spot=100,
        realized_vol=0.20,
        lookback_days=20,
        horizon_days=5,
    )


def expected_move(dte: int) -> ExpectedMove:
    expiry = date(2026, 9, 5) if dte == 7 else date(2026, 9, 28)
    return ExpectedMove(
        target_dte=dte,
        expiry=expiry,
        dte=dte,
        atm_strike=100,
        call_mid=2,
        put_mid=2,
        iv_atm=0.25,
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
