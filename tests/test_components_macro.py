"""`S_M` macro context and the 30-day catalyst calendar.

Acceptance: macro direction comes only from declared sector sensitivities, stale or
undeclared factors are n/a, and the calendar carries confirmed/estimated status without
being folded into the directional score.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from briefing_app.components import (
    BUCKET_WEIGHTS,
    CalendarEntry,
    MacroReading,
    SectorExposure,
    build_catalyst_calendar,
    build_macro_component,
    event_risk,
    parse_macro_number,
    release_change_reading,
    release_surprise,
)
from briefing_app.models.candidate import Catalyst
from briefing_app.models.market_data import (
    CatalystCalendar,
    CatalystEvent,
    MacroCalendar,
    MacroEvent,
)

RUN_DATE = date(2026, 8, 29)
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def macro_event(**overrides) -> MacroEvent:
    record = {
        "name": "CPI",
        "event_date": datetime(2026, 9, 2, 8, 30, tzinfo=UTC),
        "source": "FMP economic calendar",
        "country": "US",
        "importance": "high",
    }
    record.update(overrides)
    return MacroEvent(**record)


def macro_calendar(*events: MacroEvent) -> MacroCalendar:
    return MacroCalendar(source="FMP economic calendar", as_of=NOW, events=list(events))


def catalyst_calendar(*events: CatalystEvent) -> CatalystCalendar:
    return CatalystCalendar(
        ticker="NVDA", source="FMP earnings calendar", as_of=NOW, events=list(events)
    )


def exposure() -> SectorExposure:
    return SectorExposure(
        sector="Semiconductors",
        sensitivities={
            "policy_rate": -0.7,
            "cpi": -0.5,
            "brent": 0.2,
        },
        policy_stance=0.2,
        policy_note="Export-control regime is the dominant policy variable.",
        policy_source="Federal Register / BIS",
    )


def test_macro_number_and_release_surprise_parsing() -> None:
    assert parse_macro_number("150K") == pytest.approx(150_000)
    assert parse_macro_number("1.5M") == pytest.approx(1_500_000)
    assert parse_macro_number("3.2%") == pytest.approx(3.2)
    assert parse_macro_number(None) is None

    event = macro_event(
        event_date=datetime(2026, 8, 28, 8, 30, tzinfo=UTC),
        actual="3.3%",
        estimate="3.0%",
    )
    assert release_surprise(event) == pytest.approx(0.10)


def test_catalyst_calendar_reports_confirmed_and_estimated_events() -> None:
    entries = build_catalyst_calendar(
        run_date=RUN_DATE,
        macro_calendar=macro_calendar(
            macro_event(name="Nonfarm Payrolls", event_date=datetime(2026, 9, 4, 8, 30))
        ),
        catalyst_calendar=catalyst_calendar(
            CatalystEvent(
                ticker="NVDA",
                name="Quarterly results",
                event_date=date(2026, 9, 2),
                status="confirmed",
                kind="earnings",
                source="Company IR",
            )
        ),
        manual_catalysts=[
            Catalyst(
                name="Product launch",
                date=date(2026, 9, 15),
                status="estimated",
                kind="product",
                source="manual",
                note="cadence-inferred",
            )
        ],
    )

    assert [entry.name for entry in entries] == [
        "Quarterly results",
        "Nonfarm Payrolls",
        "Product launch",
    ]
    assert [entry.status for entry in entries] == ["confirmed", "confirmed", "estimated"]
    assert {entry.scope for entry in entries} == {"macro", "single_name"}


def test_event_risk_is_reported_beside_the_score() -> None:
    entries = [
        CalendarEntry(
            name="CPI",
            event_date=RUN_DATE + timedelta(days=2),
            status="confirmed",
            kind="macro",
            scope="macro",
            source="FMP",
            importance="high",
        ),
        CalendarEntry(
            name="Earnings",
            event_date=RUN_DATE + timedelta(days=4),
            status="confirmed",
            kind="earnings",
            scope="single_name",
            source="IR",
        ),
    ]

    assert event_risk(entries, horizon_days=30) == pytest.approx(2 / (30 / 7))


def test_macro_component_scores_only_declared_fresh_sensitivities() -> None:
    result = build_macro_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        readings=[
            MacroReading(
                name="policy_rate",
                trend=0.6,
                as_of=date(2026, 8, 20),
                source="Federal Reserve",
                detail="hawkish path",
            ),
            MacroReading(
                name="dollar",
                trend=1.0,
                as_of=date(2026, 8, 20),
                source="ICE",
            ),
            MacroReading(
                name="brent",
                trend=0.5,
                as_of=date(2026, 6, 1),
                source="ICE",
            ),
        ],
        exposure=exposure(),
        macro_calendar=macro_calendar(
            macro_event(
                name="CPI",
                event_date=datetime(2026, 8, 28, 8, 30, tzinfo=UTC),
                actual="3.3%",
                estimate="3.0%",
            ),
            macro_event(name="Nonfarm Payrolls"),
        ),
        as_of=NOW,
    )

    assert result.component == "S_M"
    assert result.available and result.score is not None
    assert {sub.name for sub in result.sub_scores} == {
        "policy_path",
        "growth_inflation",
        "commodity",
        "sector_policy",
    }

    policy = result.sub_score("policy_path")
    growth = result.sub_score("growth_inflation")
    commodity = result.sub_score("commodity")
    sector_policy = result.sub_score("sector_policy")
    assert policy is not None and policy.score == pytest.approx(-0.42)
    assert growth is not None and growth.score == pytest.approx(-0.5)
    assert commodity is not None and commodity.score is None
    assert sector_policy is not None and sector_policy.score == pytest.approx(0.2)

    used_total = (
        BUCKET_WEIGHTS["policy_path"]
        + BUCKET_WEIGHTS["growth_inflation"]
        + BUCKET_WEIGHTS["sector_policy"]
    )
    expected = (
        -0.42 * BUCKET_WEIGHTS["policy_path"] / used_total
        + -0.5 * BUCKET_WEIGHTS["growth_inflation"] / used_total
        + 0.2 * BUCKET_WEIGHTS["sector_policy"] / used_total
    )
    assert result.score == pytest.approx(expected)
    assert result.weights_used["commodity"] == 0.0
    assert any("dollar has no declared" in d for d in result.diagnostics)
    assert any("beyond the 45-day bound" in d for d in result.diagnostics)

    fields = {row["field_name"] for row in result.evidence_rows}
    assert {"macro_event_risk", "s_m", "s_m_policy_path"} <= fields
    assert result.source_rows
    assert all("status" in row and "date" in row for row in result.source_rows)


def test_macro_without_declared_exposure_is_na_but_calendar_is_still_reported() -> None:
    result = build_macro_component(
        ticker="NVDA",
        geography="US",
        run_date=RUN_DATE,
        readings=[
            MacroReading(name="policy_rate", trend=0.5, as_of=RUN_DATE, source="Fed")
        ],
        exposure=None,
        macro_calendar=macro_calendar(macro_event()),
        as_of=NOW,
    )

    assert result.available is False
    assert result.score is None
    assert "no sector exposure declared" in (result.na_reason or "")
    assert any("dated events" in d for d in result.diagnostics)


def test_release_change_reading_scores_a_move_against_the_series_own_scale() -> None:
    """Free macro feeds publish levels without a consensus, so a surprise is impossible.

    A release-over-release change is still sourced and dated. It is scored in standard
    deviations of that series' own changes, so an ordinary move reads weak.
    """

    # A series that drifts up with ordinary month-to-month variation.
    levels = [300.0, 300.4, 300.5, 301.0, 300.9, 301.4, 301.8, 301.7, 302.3, 302.5, 303.1, 303.4]
    events = [
        MacroEvent(
            name="CPI",
            event_date=datetime(2026, month, 1, tzinfo=UTC),
            source="FMP economic-indicators",
            actual=str(level),
        )
        for month, level in enumerate(levels, start=1)
    ]
    ordinary = release_change_reading(
        events, factor="cpi", run_date=date(2026, 12, 15)
    )
    assert ordinary is not None
    assert 0 < ordinary.trend < 0.6
    assert "not a consensus surprise" in ordinary.detail

    jumped = events + [
        MacroEvent(
            name="CPI",
            event_date=datetime(2026, 12, 20, tzinfo=UTC),
            source="FMP economic-indicators",
            actual="309.0",
        )
    ]
    spike = release_change_reading(jumped, factor="cpi", run_date=date(2026, 12, 28))
    assert spike is not None and spike.trend == 1.0


def test_release_change_reading_returns_none_rather_than_a_neutral_zero() -> None:
    """Too little history, a flat series, or a stale print must not read as neutral."""

    def series(values, start_month=1):
        return [
            MacroEvent(
                name="CPI",
                event_date=datetime(2026, start_month + offset, 1, tzinfo=UTC),
                source="FMP economic-indicators",
                actual=str(value),
            )
            for offset, value in enumerate(values)
        ]

    run_date = date(2026, 12, 15)
    assert release_change_reading(series([300.0, 301.0]), factor="cpi", run_date=run_date) is None
    assert release_change_reading(series([300.0] * 12), factor="cpi", run_date=run_date) is None
    # A perfectly regular series has no distribution to judge a move against; its
    # deviation is floating-point noise, not a scale.
    assert release_change_reading(
        series([300.0 + i * 0.2 for i in range(12)]), factor="cpi", run_date=run_date
    ) is None
    stale = series([300.0, 300.4, 300.5, 301.0, 300.9, 301.4, 301.8, 301.7, 302.3, 302.5, 303.1, 303.4])
    assert release_change_reading(
        stale, factor="cpi", run_date=date(2027, 6, 1), max_age_days=45
    ) is None


def _monthly_series(*, released: bool, count: int = 12) -> list[MacroEvent]:
    """Monthly prints ending with July 2026, each published on the 12th of the next month.

    Mirrors CPI: period 2026-07-01, released 2026-08-12.
    """

    periods = [relativedelta_months(index) for index in range(count)]
    events: list[MacroEvent] = []
    previous: float | None = None
    for index, period in enumerate(periods):
        publish = relativedelta_months(1, anchor=period).replace(day=12)
        value = 320.0 + index * 1.2 + (0.4 if index % 3 == 0 else 0.0)
        events.append(
            MacroEvent(
                name="CPIAUCSL",
                event_date=datetime.combine(period, time.min, tzinfo=UTC),
                released_at=(
                    datetime.combine(publish, time.min, tzinfo=UTC) if released else None
                ),
                source="FRED",
                actual=str(value),
                previous=None if previous is None else str(previous),
            )
        )
        previous = value
    return events


def relativedelta_months(months: int, *, anchor: date = date(2025, 8, 1)) -> date:
    total = anchor.month - 1 + months
    return date(anchor.year + total // 12, total % 12 + 1, 1)


def test_monthly_reading_is_aged_from_its_release_not_its_period() -> None:
    """CPI for July is dated 2026-07-01 but printed 2026-08-12.

    Ageing from the period start makes a print under three weeks old read as two months
    stale against the 45-day bound, which dropped cpi, policy_rate and real_gdp out of
    S_M entirely - the heaviest component in the formula, scoring on one factor.
    """

    run_date = date(2026, 8, 31)
    with_release = release_change_reading(
        _monthly_series(released=True), factor="cpi", run_date=run_date, max_age_days=45
    )
    assert with_release is not None
    assert with_release.as_of == date(2026, 8, 12)
    assert "for the period beginning" in with_release.detail

    # Without a release date the previous behaviour stands: the period start is 61 days
    # before the run, so the reading is dropped as stale.
    without_release = release_change_reading(
        _monthly_series(released=False), factor="cpi", run_date=run_date, max_age_days=45
    )
    assert without_release is None


def test_release_ageing_still_drops_a_genuinely_stale_print() -> None:
    """The bound is still enforced - a real gap is not papered over by the release date."""

    events = _monthly_series(released=True)
    assert (
        release_change_reading(
            events, factor="cpi", run_date=date(2026, 12, 31), max_age_days=45
        )
        is None
    )
