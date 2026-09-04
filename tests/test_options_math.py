from __future__ import annotations

from datetime import date, timedelta
from math import log, sqrt
from statistics import stdev

import pytest

from briefing_app.options_math import (
    DEALER_GAMMA_ASSUMPTION,
    DistributionError,
    OptionQuote,
    PriceBar,
    build_measured_sigma_range,
    build_options_structure,
    compute_expected_move,
    days_to_expiry,
    density_from_call_prices,
    gamma_by_strike,
    implied_distribution,
    probability_above,
    probability_below,
    put_call_metrics,
    realized_volatility,
    risk_reversal_25d,
    select_atm_straddle,
    trading_days_from_calendar_days,
)
from briefing_app.models.market_data import OptionChain, OptionContract


AS_OF = date(2026, 8, 29)
WEEKLY = AS_OF + timedelta(days=7)
MONTHLY = AS_OF + timedelta(days=30)


def q(
    expiry: date,
    strike: float,
    option_type: str,
    bid: float,
    ask: float,
    *,
    iv: float = 0.30,
    delta: float | None = None,
    gamma: float = 0.02,
    oi: int = 100,
    volume: int = 50,
) -> OptionQuote:
    return OptionQuote(
        ticker="TEST",
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        bid=bid,
        ask=ask,
        iv=iv,
        delta=delta,
        gamma=gamma,
        open_interest=oi,
        volume=volume,
    )


def fixture_chain() -> list[OptionQuote]:
    rows: list[OptionQuote] = []
    weekly_specs = [
        (90, 10.2, 10.6, 0.33, 0.92, 0.018, 300, 80, 0.35, 0.45, -0.08, 0.019, 500, 140),
        (95, 6.1, 6.5, 0.31, 0.70, 0.024, 900, 180, 1.05, 1.25, -0.25, 0.023, 1700, 420),
        (100, 2.02, 2.18, 0.30, 0.51, 0.030, 2200, 760, 1.98, 2.12, -0.49, 0.031, 2300, 780),
        (105, 0.92, 1.08, 0.31, 0.26, 0.025, 1400, 530, 5.8, 6.2, -0.70, 0.024, 1200, 410),
        (110, 0.35, 0.45, 0.34, 0.10, 0.017, 600, 150, 10.0, 10.5, -0.90, 0.018, 700, 210),
    ]
    for (
        strike,
        cbid,
        cask,
        civ,
        cdelta,
        cgamma,
        coi,
        cvol,
        pbid,
        pask,
        pdelta,
        pgamma,
        poi,
        pvol,
    ) in weekly_specs:
        rows.append(
            q(WEEKLY, strike, "C", cbid, cask, iv=civ, delta=cdelta, gamma=cgamma, oi=coi, volume=cvol)
        )
        rows.append(
            q(WEEKLY, strike, "P", pbid, pask, iv=civ + 0.02, delta=pdelta, gamma=pgamma, oi=poi, volume=pvol)
        )

    for strike in (90, 95, 100, 105, 110):
        call_intrinsic = max(100 - strike, 0)
        put_intrinsic = max(strike - 100, 0)
        rows.append(
            q(
                MONTHLY,
                strike,
                "C",
                call_intrinsic + 3.4,
                call_intrinsic + 3.8,
                iv=0.34,
                delta=0.50 if strike == 100 else None,
                oi=500,
                volume=100,
            )
        )
        rows.append(
            q(
                MONTHLY,
                strike,
                "P",
                put_intrinsic + 3.2,
                put_intrinsic + 3.6,
                iv=0.35,
                delta=-0.50 if strike == 100 else None,
                oi=550,
                volume=110,
            )
        )
    return rows


def price_bars(count: int = 70) -> list[PriceBar]:
    closes = []
    value = 90.0
    for index in range(count):
        # Alternating log returns produce a stable non-zero realized volatility.
        value *= 1.004 if index % 2 == 0 else 0.997
        closes.append(PriceBar(bar_date=AS_OF - timedelta(days=count - index), close=value))
    return closes


def test_dte_and_annualization_conventions_are_explicit() -> None:
    assert days_to_expiry(AS_OF, WEEKLY) == 7

    move = compute_expected_move(fixture_chain(), spot=100, as_of=AS_OF, target_dte=7)
    assert move.dte == 7
    assert move.iv_pct == pytest.approx(move.iv_atm * sqrt(7 / 365))

    rv = realized_volatility(price_bars(25), lookback_days=20)
    window = price_bars(25)[-21:]
    returns = [log(window[index].close / window[index - 1].close) for index in range(1, len(window))]
    assert rv.annualized_vol == pytest.approx(stdev(returns) * sqrt(252))


def test_atm_selection_mid_price_and_expected_move_ranges_are_stable() -> None:
    chain = fixture_chain()
    atm = select_atm_straddle(chain, spot=101.2, as_of=AS_OF, expiry=WEEKLY)
    assert atm.strike == 100
    assert atm.call.mid == pytest.approx(2.10)
    assert atm.put.mid == pytest.approx(2.05)

    move = compute_expected_move(chain, spot=100, as_of=AS_OF, target_dte=7)
    assert move.expiry == WEEKLY
    assert move.atm_strike == 100
    assert move.straddle_points == pytest.approx(4.15)
    assert move.straddle_pct == pytest.approx(0.0415)
    assert move.one_sigma_straddle.low == pytest.approx(95.85)
    assert move.one_sigma_straddle.high == pytest.approx(104.15)
    assert move.two_sigma_straddle.low == pytest.approx(91.70)
    assert move.two_sigma_straddle.high == pytest.approx(108.30)


def test_expected_move_method_divergence_is_surfaced() -> None:
    chain = [
        q(WEEKLY, 100, "C", 4.9, 5.1, iv=0.20, delta=0.50),
        q(WEEKLY, 100, "P", 4.9, 5.1, iv=0.20, delta=-0.50),
    ]

    move = compute_expected_move(
        chain,
        spot=100,
        as_of=AS_OF,
        target_dte=7,
        divergence_threshold=0.25,
    )

    assert move.divergence_exceeds_threshold is True
    assert any("divergence exceeds threshold" in item for item in move.diagnostics)


def test_measured_sigma_range_uses_realized_vol_trading_day_scaling() -> None:
    measured = build_measured_sigma_range(
        spot=100,
        realized_vol=0.30,
        lookback_days=20,
        horizon_days=5,
        event_multiplier=1.5,
    )

    assert measured.sigma_pct == pytest.approx(0.30 * sqrt(5 / 252))
    assert measured.adjusted_sigma_pct == pytest.approx(0.30 * sqrt(5 / 252) * 1.5)
    assert measured.one_sigma.low == pytest.approx(100 - (100 * measured.adjusted_sigma_pct))
    assert measured.two_sigma.high == pytest.approx(100 + (2 * 100 * measured.adjusted_sigma_pct))


def test_positioning_metrics_detect_skew_oi_put_call_and_gamma() -> None:
    chain = fixture_chain()

    rr = risk_reversal_25d(chain, expiry=WEEKLY)
    assert rr is not None
    assert rr.call_strike == 105
    assert rr.put_strike == 95
    assert rr.rr_25d == pytest.approx(0.31 - 0.33)

    pc = put_call_metrics(
        chain,
        expiry=WEEKLY,
        volume_history=[0.55, 0.65, 0.75, 0.85, 0.95],
        open_interest_history=[0.70, 0.80, 0.90, 1.00, 1.10],
    )
    assert pc.volume_ratio == pytest.approx(1960 / 1700)
    assert pc.open_interest_ratio == pytest.approx(6400 / 5400)
    assert pc.volume_percentile == pytest.approx(100.0)

    gamma = gamma_by_strike(chain, expiry=WEEKLY)
    assert gamma
    assert gamma[0].assumption == DEALER_GAMMA_ASSUMPTION


def test_implied_distribution_normalizes_and_answers_probability_queries() -> None:
    distribution = implied_distribution(
        fixture_chain(),
        spot=100,
        as_of=AS_OF,
        expiry=WEEKLY,
        grid_size=81,
    )

    assert distribution.total_probability == pytest.approx(1.0)
    assert len(distribution.points) == 79
    assert probability_below(distribution, 100) == pytest.approx(0.5, abs=0.18)
    assert probability_above(distribution, 100) == pytest.approx(
        1 - probability_below(distribution, 100)
    )


def test_unrepaired_negative_density_is_rejected() -> None:
    with pytest.raises(DistributionError, match="negative implied density"):
        density_from_call_prices(
            [90, 100, 110, 120],
            [12, 14, 6, 2],
            time_years=7 / 365,
            repair_negative=False,
        )


def test_call_price_at_float_noise_below_zero_is_clamped_not_rejected() -> None:
    """Black-Scholes returns ~-3e-14 for worthless deep-OTM strikes.

    Refusing those rejected entire legitimate strike windows even though every fitted
    IV was positive, so sub-epsilon negatives are clamped to zero instead.
    """

    points, _, total, _ = density_from_call_prices(
        [90, 100, 110, 120],
        [12.0, 6.0, 1.0, -3.4e-14],
        time_years=7 / 365,
    )
    assert points
    assert total == pytest.approx(1.0)


def test_genuinely_negative_call_price_still_raises() -> None:
    with pytest.raises(ValueError, match="call_price must be non-negative"):
        density_from_call_prices(
            [90, 100, 110, 120],
            [12.0, 6.0, 1.0, -0.5],
            time_years=7 / 365,
        )


def test_build_options_structure_produces_metrics_score_and_evidence_rows() -> None:
    result = build_options_structure(
        ticker="test",
        spot=100,
        as_of=AS_OF,
        option_quotes=fixture_chain(),
        price_bars=price_bars(),
        expression_class="V",
        chain_verified=True,
        iv_history=[0.20, 0.25, 0.28, 0.30, 0.35],
        pc_ratio_vol_history=[0.70, 0.90, 1.00, 1.10, 1.30],
        pc_ratio_oi_history=[0.80, 0.95, 1.05, 1.15, 1.30],
        short_borrow={
            "verified": True,
            "short_interest_pct_float": 12,
            "days_to_cover": 4,
            "borrow_fee_pct": 8,
            "utilization_pct": 70,
        },
        run_id=7,
        source="fixture",
        venue="CBOE",
        endpoint_or_file="fixtures/options/test.json",
        validation_status="verified",
    )

    assert result.available is True
    assert result.expected_moves["weekly"].straddle_points == pytest.approx(4.15)
    assert result.expected_moves["monthly"].dte == 30
    assert result.realized_volatility[20].sample_count == 20
    assert result.measured_range is not None
    assert result.iv_rank == pytest.approx(80.0)
    assert result.variance_risk_premium is not None
    assert result.risk_reversal_25d is not None
    assert result.oi_clusters[0].total_open_interest >= result.oi_clusters[-1].total_open_interest
    assert result.put_call is not None
    assert result.gamma_by_strike
    assert result.implied_distribution is not None
    assert result.short_borrow is not None
    assert result.score is not None and -1.0 <= result.score <= 1.0
    fields = {row["field_name"] for row in result.evidence_rows}
    assert {
        "spot",
        "weekly_expected_move_straddle_pct",
        "monthly_expected_move_straddle_pct",
        "realized_vol_20d",
        "iv_rank",
        "variance_risk_premium",
        "rr_25d",
        "pc_ratio_volume",
        "s_o",
    }.issubset(fields)
    assert all(row["component"] == "S_O" for row in result.evidence_rows)


def test_build_options_structure_accepts_normalized_provider_chain_models() -> None:
    contracts = [
        OptionContract(
            underlying="TEST",
            contract_symbol=f"TEST260905{option_type}00100000",
            expiry=WEEKLY,
            strike=100,
            option_type=option_type,
            venue="CBOE",
            source="fixture",
            bid=bid,
            ask=ask,
            implied_volatility=0.30,
            delta=delta,
            gamma=0.02,
            open_interest=100,
            volume=50,
        )
        for option_type, bid, ask, delta in (("C", 2.0, 2.2, 0.50), ("P", 1.9, 2.1, -0.50))
    ]
    chain = OptionChain(
        ticker="TEST",
        venue="CBOE",
        as_of="2026-08-29T12:00:00Z",
        spot=100,
        source="fixture",
        contracts=contracts,
    )

    result = build_options_structure(
        ticker=chain.ticker,
        spot=chain.spot,
        as_of=chain.as_of,
        option_quotes=chain,
        expression_class="V",
        chain_verified=True,
    )

    assert result.available is True
    assert result.expected_moves["weekly"].straddle_points == pytest.approx(4.1)


def test_required_options_class_is_na_without_verified_per_strike_chain() -> None:
    result = build_options_structure(
        ticker="TEST",
        spot=100,
        as_of=AS_OF,
        option_quotes=[],
        expression_class="V",
        chain_verified=False,
        run_id=9,
        source="fixture",
        validation_status="missing",
    )

    assert result.available is False
    assert result.score is None
    assert result.na_reason is not None
    assert "verified per-strike option chain is required" in result.na_reason
    assert result.evidence_rows[0]["field_name"] == "s_o"
    assert result.evidence_rows[0]["field_value"] == "n/a"


def test_calendar_days_convert_to_trading_days_before_scaling() -> None:
    assert trading_days_from_calendar_days(7) == 5
    assert trading_days_from_calendar_days(30) == 21
    assert trading_days_from_calendar_days(1) == 1
    with pytest.raises(ValueError):
        trading_days_from_calendar_days(0)


def test_measured_sigma_horizon_is_trading_days_not_option_dte() -> None:
    """A 252-day annualized vol must not be scaled by a calendar DTE.

    Scaling by calendar days overstates a weekly band by about sqrt(365/252) ~ 20%,
    which would push 1-sigma containment well above the 68% calibration target.
    """

    result = build_options_structure(
        ticker="TEST",
        spot=100,
        as_of=AS_OF,
        option_quotes=fixture_chain(),
        price_bars=price_bars(),
        chain_verified=True,
    )

    measured = result.measured_range
    assert measured is not None
    assert result.expected_moves["weekly"].dte == 7
    assert measured.calendar_horizon_days == 7
    assert measured.horizon_days == 5
    assert measured.trading_days == 252

    annualized = result.realized_volatility[20].annualized_vol
    assert measured.sigma_pct == pytest.approx(annualized * sqrt(5 / 252))
    assert measured.sigma_pct < annualized * sqrt(7 / 252)


def test_explicit_measured_horizon_is_taken_as_trading_days() -> None:
    result = build_options_structure(
        ticker="TEST",
        spot=100,
        as_of=AS_OF,
        option_quotes=fixture_chain(),
        price_bars=price_bars(),
        chain_verified=True,
        measured_horizon_days=10,
    )

    measured = result.measured_range
    assert measured is not None
    assert measured.horizon_days == 10
    assert measured.calendar_horizon_days is None


def test_distribution_reports_the_mass_its_strike_range_actually_covers() -> None:
    """Normalizing to 1.0 is not evidence the chain spans the distribution."""

    wide = implied_distribution(fixture_chain(), spot=100, as_of=AS_OF, expiry=WEEKLY)
    assert wide.total_probability == pytest.approx(1.0)
    assert wide.captured_probability_mass > 0.90
    assert wide.strike_low == 90 and wide.strike_high == 110
    assert not any("capture only" in item for item in wide.diagnostics)

    # Strikes 99-101 on a name whose 1-sigma week is about +/-4 points.
    narrow = [
        q(WEEKLY, 99, "C", 1.6, 1.8, iv=0.30, delta=0.60),
        q(WEEKLY, 100, "C", 1.1, 1.3, iv=0.30, delta=0.50),
        q(WEEKLY, 101, "C", 0.7, 0.9, iv=0.30, delta=0.40),
    ]
    thin = implied_distribution(narrow, spot=100, as_of=AS_OF, expiry=WEEKLY)
    assert thin.total_probability == pytest.approx(1.0)
    assert thin.captured_probability_mass < 0.50
    assert any("capture only" in item for item in thin.diagnostics)
