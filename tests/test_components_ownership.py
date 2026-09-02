"""`S_I` insider velocity and `S_F` institutional flow.

Acceptance: the insider parser excludes non-open-market noise, and EU substitutes carry
EU notes rather than silently borrowing US assumptions.
"""

from __future__ import annotations

from datetime import date

import pytest

from briefing_app.components import (
    COHORT_ACTIVE,
    COHORT_PASSIVE,
    COHORT_SOVEREIGN,
    build_insider_component,
    build_institutional_component,
    classify_cohort,
    classify_transaction,
    extract_activity,
    role_weight,
)
from briefing_app.models.market_data import InsiderTransaction, OwnershipChange

RUN_DATE = date(2026, 8, 29)
RECENT = date(2026, 8, 1)


def insider(**overrides) -> InsiderTransaction:
    record = {
        "ticker": "NVDA",
        "as_of": RECENT,
        "source": "SEC Form 4",
        "insider": "Jane Roe",
        "title": "Chief Executive Officer",
        "transaction_type": "P-Purchase",
        "shares": 10_000,
        "price": 100.0,
    }
    record.update(overrides)
    return InsiderTransaction(**record)


def holding(**overrides) -> OwnershipChange:
    record = {
        "ticker": "NVDA",
        "institution": "Tiger Global",
        "as_of": date(2026, 6, 30),
        "source": "SEC Form 13F",
        "shares": 1_000_000,
        "shares_delta": 100_000,
    }
    record.update(overrides)
    return OwnershipChange(**record)


# --- S_I: the exclusion rules -------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"raw": {"footnote": "Sold under a Rule 10b5-1 trading plan"}}, "10b5-1 automated plan"),
        ({"transaction_type": "F"}, "tax withholding"),
        ({"transaction_type": "M"}, "option exercise"),
        ({"transaction_type": "A"}, "grant or award"),
        ({"transaction_type": "G"}, "gift"),
        ({"transaction_type": "X"}, "in-the-money option exercise"),
        ({"transaction_type": "Restricted stock vesting"}, "vesting"),
    ],
)
def test_non_open_market_activity_is_excluded(overrides: dict, expected_reason: str) -> None:
    direction, reason = classify_transaction(insider(**overrides))
    assert direction is None
    assert reason == expected_reason


@pytest.mark.parametrize(
    ("transaction_type", "expected"),
    [("P", "buy"), ("P-Purchase", "buy"), ("S", "sell"), ("S - Sale", "sell")],
)
def test_open_market_codes_are_scored(transaction_type: str, expected: str) -> None:
    direction, reason = classify_transaction(insider(transaction_type=transaction_type))
    assert direction == expected
    assert reason is None


def test_unrecognized_type_is_excluded_rather_than_guessed() -> None:
    direction, reason = classify_transaction(insider(transaction_type="Z-Something"))
    assert direction is None
    assert "not recognized" in (reason or "")


def test_excluded_rows_are_reported_not_discarded_silently() -> None:
    activity = extract_activity(
        [
            insider(),
            insider(insider="Plan Seller", transaction_type="S", shares=50_000,
                    raw={"footnote": "Rule 10b5-1 plan"}),
            insider(insider="Vesting", transaction_type="F", shares=3_000),
        ],
        run_date=RUN_DATE,
    )

    assert len(activity.buys) == 1 and activity.sells == ()
    assert {row.reason for row in activity.excluded} == {
        "10b5-1 automated plan",
        "tax withholding",
    }
    # The plan sale was 5x the size of the buy; counting it would have flipped the sign.
    assert activity.net_value == pytest.approx(1_000_000.0)


def test_transactions_outside_the_window_are_excluded() -> None:
    activity = extract_activity(
        [insider(as_of=date(2026, 1, 1)), insider()], run_date=RUN_DATE, window_days=90
    )
    assert len(activity.buys) == 1
    assert any("outside the 90-day window" in row.reason for row in activity.excluded)


@pytest.mark.parametrize(
    ("title", "expected_label"),
    [
        ("Chief Executive Officer", "ceo"),
        ("CFO", "cfo"),
        ("Chief Operating Officer", "operating_officer"),
        ("Director", "director"),
        ("10% Owner", "ten_percent_owner"),
        (None, "other_insider"),
    ],
)
def test_role_weighting_tiers_by_seniority(title: str | None, expected_label: str) -> None:
    weight, label = role_weight(title)
    assert label == expected_label
    assert 0.0 < weight <= 1.0


def test_insider_component_reports_score_subscores_sources_and_dates() -> None:
    result = build_insider_component(
        ticker="NVDA",
        geography="US",
        transactions=[insider(), insider(insider="John Doe", title="Director",
                                         transaction_type="S", shares=2_000)],
        run_date=RUN_DATE,
    )

    assert result.component == "S_I"
    assert result.available and result.score is not None
    assert {s.name for s in result.sub_scores} == {"net_flow", "breadth", "seniority"}
    assert result.source_rows and all("as_of" in row for row in result.source_rows)
    assert all(row["component"] == "S_I" for row in result.evidence_rows)
    assert result.score > 0, "a CEO buy against a small director sale reads bullish"


def test_only_excluded_activity_is_na_with_the_count_in_the_reason() -> None:
    result = build_insider_component(
        ticker="NVDA",
        geography="US",
        transactions=[insider(transaction_type="M"), insider(transaction_type="F")],
        run_date=RUN_DATE,
    )

    assert result.available is False
    assert result.score is None
    assert "no open-market insider trades" in (result.na_reason or "")
    assert "2 filings" in (result.na_reason or "")


def test_no_data_is_na_not_zero() -> None:
    result = build_insider_component(
        ticker="NVDA", geography="US", transactions=[], run_date=RUN_DATE
    )
    assert result.score is None
    assert result.available is False
    assert result.validation_status == "unavailable"


# --- S_I: the EU substitute ---------------------------------------------------------


def test_eu_insider_uses_article_19_and_says_so() -> None:
    result = build_insider_component(
        ticker="RHM.DE",
        geography="EU",
        transactions=[insider(ticker="RHM.DE", source="BaFin Art. 19 PDMR")],
        run_date=RUN_DATE,
    )

    assert result.eu_substitutes, "an EU result must declare its substitute"
    assert "Article 19" in result.eu_substitutes[0]
    assert any("Article 19" in d for d in result.diagnostics)
    assert result.weight_profile == "EU"
    # EU disclosure is hand-collected here, so it cannot claim primary quality.
    assert result.source_quality != "primary"


def test_eu_insider_absence_names_the_eu_source() -> None:
    result = build_insider_component(
        ticker="RHM.DE", geography="EU", transactions=[], run_date=RUN_DATE
    )
    assert "MAR Article 19" in (result.na_reason or "")


# --- S_F: cohorts -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("institution", "declared", "expected", "inferred"),
    [
        ("Vanguard Group", None, COHORT_PASSIVE, True),
        ("BlackRock Fund Advisors", None, COHORT_PASSIVE, True),
        ("Norges Bank", None, COHORT_SOVEREIGN, True),
        ("State Teachers Retirement System", None, COHORT_SOVEREIGN, True),
        ("Tiger Global", None, COHORT_ACTIVE, True),
        ("Vanguard Group", "active", COHORT_ACTIVE, False),
    ],
)
def test_cohort_classification_prefers_a_declared_cohort(
    institution: str, declared: str | None, expected: str, inferred: bool
) -> None:
    cohort, was_inferred = classify_cohort(
        holding(institution=institution, cohort=declared)
    )
    assert cohort == expected
    assert was_inferred is inferred


def test_passive_flow_is_discounted_against_active_flow() -> None:
    active = build_institutional_component(
        ticker="NVDA",
        geography="US",
        ownership_changes=[holding(institution="Tiger Global", cohort="active")],
        run_date=RUN_DATE,
    )
    passive = build_institutional_component(
        ticker="NVDA",
        geography="US",
        ownership_changes=[holding(institution="Vanguard Group", cohort="passive")],
        run_date=RUN_DATE,
    )

    assert active.score is not None and passive.score is not None
    assert active.score > passive.score, "index tracking is not a conviction signal"


def test_inferred_cohorts_are_disclosed() -> None:
    result = build_institutional_component(
        ticker="NVDA",
        geography="US",
        ownership_changes=[holding(institution="Some Capital Partners")],
        run_date=RUN_DATE,
    )
    assert any("classified by name" in d for d in result.diagnostics)


def test_stale_ownership_is_na_not_neutral() -> None:
    result = build_institutional_component(
        ticker="NVDA",
        geography="US",
        ownership_changes=[holding(as_of=date(2025, 6, 30))],
        run_date=RUN_DATE,
    )
    assert result.score is None
    assert "release cadence bound" in (result.na_reason or "")
    assert "stale ownership is n/a, not neutral" in (result.na_reason or "")


def test_institutional_component_reports_subscores_and_evidence() -> None:
    result = build_institutional_component(
        ticker="NVDA",
        geography="US",
        ownership_changes=[
            holding(institution="Tiger Global", cohort="active"),
            holding(institution="Vanguard Group", cohort="passive", shares=9_000_000,
                    shares_delta=50_000),
            holding(institution="Bridgewater", cohort="active", shares=500_000,
                    shares_delta=-20_000),
        ],
        run_date=RUN_DATE,
    )

    assert result.component == "S_F"
    assert {s.name for s in result.sub_scores} == {"weighted_flow", "breadth", "active_share"}
    assert len(result.source_rows) == 3
    assert all(row["component"] == "S_F" for row in result.evidence_rows)
    fields = {row["field_name"] for row in result.evidence_rows}
    assert {"institutional_holders", "institutional_weighted_delta", "s_f"} <= fields


# --- S_F: the EU substitute ---------------------------------------------------------


def test_eu_ownership_scores_threshold_crossings_and_declares_the_difference() -> None:
    result = build_institutional_component(
        ticker="RHM.DE",
        geography="EU",
        ownership_changes=[
            OwnershipChange(ticker="RHM.DE", institution="Fund A", as_of=date(2026, 8, 10),
                            source="Bundesanzeiger", percent_delta=1.2),
            OwnershipChange(ticker="RHM.DE", institution="Fund B", as_of=date(2026, 8, 12),
                            source="Bundesanzeiger", percent_delta=0.8),
        ],
        run_date=RUN_DATE,
    )

    assert result.score is not None
    assert {s.name for s in result.sub_scores} == {"threshold_crossings"}
    assert "not a quarterly accumulation wave" in (result.sub_scores[0].detail or "")
    assert result.eu_substitutes
    assert "major-holdings" in result.eu_substitutes[0].lower()
    assert any("threshold-crossing" in d for d in result.diagnostics)


def test_eu_ownership_uses_the_eu_staleness_bound() -> None:
    """A 100-day-old EU notification is history; the same age is fine for a US 13F."""
    old = date(2026, 5, 1)
    eu = build_institutional_component(
        ticker="RHM.DE",
        geography="EU",
        ownership_changes=[
            OwnershipChange(ticker="RHM.DE", institution="Fund A", as_of=old,
                            source="Bundesanzeiger", percent_delta=1.0)
        ],
        run_date=RUN_DATE,
    )
    us = build_institutional_component(
        ticker="NVDA",
        geography="US",
        ownership_changes=[holding(as_of=old)],
        run_date=RUN_DATE,
    )

    assert eu.score is None and "90-day release cadence" in (eu.na_reason or "")
    assert us.score is not None
