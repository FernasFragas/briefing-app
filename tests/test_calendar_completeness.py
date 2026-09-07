"""T4 acceptance: truncated calendars and gated endpoints are partial, never zero.

A calendar is the one place where absence is itself a claim. "No earnings in the
window" decides whether T2 gates a name, whether T5 widens the range for an event day,
and whether T8's unmodelled-earnings reject fires. FMP's calendar was observed
truncated (4 companies for a 9-day window) and Alpha Vantage answers CSV endpoints
with a JSON error body when throttled - both of which a naive reader turns into an
empty list. These tests pin the difference between "nothing scheduled" and "we could
not find out".
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from briefing_app.models.market_data import ValidationStatus
from briefing_app.providers.normalizers import (
    NormalizationError,
    build_fred_macro_calendar,
    normalize_alpha_vantage_earnings_calendar_csv,
    normalize_fmp_earnings_calendar,
    normalize_fmp_economic_calendar,
    normalize_fred_release_dates,
)

CSV_HEADER = "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
AAPL_ROW = "AAPL,Apple Inc,2026-10-28,2026-09-26,1.40,USD\n"


# --- a calendar that genuinely answered ---------------------------------------------


def test_populated_calendar_is_verified_and_absence_can_be_trusted() -> None:
    calendar = normalize_fmp_earnings_calendar(
        "AAPL",
        [{"symbol": "AAPL", "date": "2026-10-28", "eps": 1.4}],
        requested_start=date(2026, 10, 1),
        requested_end=date(2026, 11, 30),
    )

    assert calendar.validation_status is ValidationStatus.VERIFIED
    assert calendar.absence_is_evidence is True
    assert [event.event_date for event in calendar.events] == [date(2026, 10, 28)]
    assert calendar.events_between(date(2026, 10, 1), date(2026, 10, 31))
    assert calendar.events_between(date(2026, 11, 1), date(2026, 11, 30)) == []


def test_requested_window_is_recorded_so_consumers_know_what_was_asked() -> None:
    calendar = normalize_fmp_earnings_calendar(
        "AAPL",
        [{"symbol": "AAPL", "date": "2026-10-28"}],
        requested_start=date(2026, 10, 1),
        requested_end=date(2026, 10, 31),
    )

    assert calendar.covers(date(2026, 10, 15)) is True
    assert calendar.covers(date(2026, 12, 1)) is False


# --- the truncation cases -----------------------------------------------------------


def test_ticker_missing_from_a_market_wide_calendar_is_partial_not_empty() -> None:
    """The observed FMP failure: the calendar answered, just not about our name."""

    calendar = normalize_fmp_earnings_calendar(
        "AAPL",
        [
            {"symbol": "MSFT", "date": "2026-10-27"},
            {"symbol": "GOOGL", "date": "2026-10-29"},
        ],
    )

    assert calendar.events == []
    assert calendar.validation_status is ValidationStatus.PARTIAL
    assert calendar.absence_is_evidence is False
    codes = {issue.code for issue in calendar.diagnostics}
    assert "ticker_absent_from_calendar" in codes


def test_completely_empty_calendar_is_unavailable_not_a_clean_no() -> None:
    calendar = normalize_fmp_earnings_calendar("AAPL", [])

    assert calendar.validation_status is ValidationStatus.UNAVAILABLE
    assert calendar.absence_is_evidence is False
    assert "empty_calendar" in {issue.code for issue in calendar.diagnostics}


def test_row_limit_downgrades_even_a_populated_calendar() -> None:
    calendar = normalize_fmp_earnings_calendar(
        "AAPL",
        [{"symbol": "AAPL", "date": "2026-10-28"}],
        row_limit_reached=True,
    )

    assert calendar.events, "the row we did get is still returned"
    assert calendar.validation_status is ValidationStatus.PARTIAL
    assert calendar.absence_is_evidence is False
    assert "calendar_row_limit_reached" in {i.code for i in calendar.diagnostics}


def test_macro_calendar_follows_the_same_contract() -> None:
    populated = normalize_fmp_economic_calendar(
        [{"date": "2026-09-02 08:30:00", "event": "Nonfarm Payrolls", "country": "US"}]
    )
    assert populated.validation_status is ValidationStatus.VERIFIED
    assert populated.absence_is_evidence is True
    assert populated.events_between(date(2026, 9, 1), date(2026, 9, 30))

    empty = normalize_fmp_economic_calendar([])
    assert empty.validation_status is ValidationStatus.UNAVAILABLE
    assert empty.absence_is_evidence is False


def test_fred_release_calendar_follows_the_same_contract() -> None:
    """The macro calendar's actual source, now FMP's is 402. Same rules apply to it."""

    populated = build_fred_macro_calendar(
        normalize_fred_release_dates(
            {"release_dates": [{"release_id": 10, "date": "2026-09-11"}]},
            release_name="Consumer Price Index",
        ),
        requested_start=date(2026, 9, 2),
        requested_end=date(2026, 10, 2),
    )
    assert populated.validation_status is ValidationStatus.VERIFIED
    assert populated.absence_is_evidence is True
    assert populated.events_between(date(2026, 9, 1), date(2026, 9, 30))

    empty = build_fred_macro_calendar([])
    assert empty.validation_status is ValidationStatus.UNAVAILABLE
    assert empty.absence_is_evidence is False


# --- gated / trap payloads ----------------------------------------------------------


def test_plan_gated_macro_calendar_raises_instead_of_returning_no_events() -> None:
    with pytest.raises(NormalizationError):
        normalize_fmp_economic_calendar({"Error Message": "ACCESS DENIED"})


def test_trap_payload_on_the_earnings_calendar_raises() -> None:
    with pytest.raises(NormalizationError):
        normalize_fmp_earnings_calendar(
            "AAPL", {"Information": "premium endpoint", "data": []}
        )


@pytest.mark.parametrize(
    "body",
    [
        '{"Information": "Our standard API rate limit is 25 requests per day."}',
        '{"Note": "Thank you for using Alpha Vantage!"}',
        "<html><body>Access Denied</body></html>",
        "   ",
    ],
)
def test_non_csv_body_is_a_failed_call_not_an_empty_calendar(body: str) -> None:
    """A JSON error body parses as CSV into zero rows. That must not read as "no earnings"."""

    with pytest.raises(NormalizationError):
        normalize_alpha_vantage_earnings_calendar_csv("NVDA", body)


def test_alpha_vantage_csv_calendar_still_parses_real_rows() -> None:
    calendar = normalize_alpha_vantage_earnings_calendar_csv(
        "AAPL",
        CSV_HEADER + AAPL_ROW,
        as_of=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        endpoint_or_file="data/raw/alpha_vantage/earnings_calendar/2026-08-29/AAPL.json",
    )

    assert calendar.ticker == "AAPL"
    assert calendar.validation_status is ValidationStatus.VERIFIED
    assert calendar.events[0].event_date == date(2026, 10, 28)
    assert calendar.events[0].status == "confirmed"
    assert calendar.as_of == datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    assert "alpha_vantage" in calendar.endpoint_or_file


def test_alpha_vantage_csv_without_our_ticker_is_partial() -> None:
    calendar = normalize_alpha_vantage_earnings_calendar_csv(
        "NVDA",
        CSV_HEADER + AAPL_ROW,
    )

    assert calendar.events == []
    assert calendar.validation_status is ValidationStatus.PARTIAL
    assert calendar.absence_is_evidence is False
