from __future__ import annotations

from datetime import UTC, datetime

from briefing_app.models.market_data import (
    OptionContract,
    OptionFilterConfig,
    OptionType,
)


def test_option_contract_derives_midpoint() -> None:
    contract = OptionContract(
        underlying="SPY",
        contract_symbol="SPY260904C00500000",
        expiry="2026-09-04",
        strike=500,
        option_type="call",
        venue="CBOE",
        source="fixture",
        bid=4.5,
        ask=4.7,
        volume=100,
        open_interest=200,
    )

    assert contract.option_type is OptionType.CALL
    assert contract.mid == 4.6


def test_liquidity_filter_reports_specific_reasons() -> None:
    contract = OptionContract(
        underlying="SPY",
        contract_symbol="SPY260904P00500000",
        expiry="2026-09-04",
        strike=500,
        option_type="P",
        venue="CBOE",
        source="fixture",
        bid=1,
        ask=2,
        volume=0,
        open_interest=2,
        last_trade_time=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )

    issues = contract.liquidity_issues(
        OptionFilterConfig(
            min_open_interest=10,
            min_volume=1,
            max_bid_ask_width_pct=0.25,
            max_quote_age_minutes=30,
        ),
        reference_time=datetime(2026, 8, 29, 13, 0, tzinfo=UTC),
    )

    assert {issue.code for issue in issues} == {
        "low_open_interest",
        "low_volume",
        "wide_bid_ask",
        "stale_option_trade",
    }
