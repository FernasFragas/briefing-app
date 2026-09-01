"""The candidate contract: parsing, normalisation, and validation."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from briefing_app.models.candidate import (
    Candidate,
    Catalyst,
    CatalystStatus,
    ExpressionClass,
    Geography,
    Instrument,
    SourceKind,
    ThesisSource,
)
from tests.conftest import make_candidate, make_catalyst


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("US", Geography.US),
        ("usa", Geography.US),
        ("Germany", Geography.EU),
        ("United Kingdom", Geography.UK),
    ],
)
def test_geography_accepts_aliases(raw: str, expected: Geography) -> None:
    assert Geography(raw) is expected


def test_geography_weight_profile_splits_us_from_everything_else() -> None:
    assert Geography.US.weight_profile == "US"
    assert Geography.EU.weight_profile == "EU"
    assert Geography.UK.weight_profile == "EU"
    assert Geography.OTHER.weight_profile == "EU"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("vol", ExpressionClass.V),
        ("Event", ExpressionClass.E),
        ("positional", ExpressionClass.P),
        ("short", ExpressionClass.S),
    ],
)
def test_expression_class_accepts_aliases(raw: str, expected: ExpressionClass) -> None:
    assert ExpressionClass(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stock", Instrument.SHARES),
        ("Option", Instrument.OPTIONS),
        ("knock-out", Instrument.KNOCK_OUT),
        ("factor certificate", Instrument.FACTOR_CERTIFICATE),
    ],
)
def test_instrument_accepts_aliases(raw: str, expected: Instrument) -> None:
    assert Instrument(raw) is expected


def test_unknown_enum_value_still_fails() -> None:
    with pytest.raises(ValueError):
        Instrument("perpetual_swap")


def test_ticker_is_normalised_and_instruments_deduped() -> None:
    candidate = make_candidate(
        ticker="  nvda ", permitted_instruments=["stock", "options", "shares"]
    )
    assert candidate.ticker == "NVDA"
    assert candidate.permitted_instruments == [Instrument.SHARES, Instrument.OPTIONS]


def test_catalysts_sort_earliest_first_with_confirmed_ahead_of_estimated() -> None:
    same_day = date(2026, 9, 4)
    candidate = make_candidate(
        catalysts=[
            {"name": "Late", "date": date(2026, 9, 9), "status": "confirmed"},
            {"name": "Estimated", "date": same_day, "status": "estimated"},
            {"name": "Confirmed", "date": same_day, "status": "confirmed"},
        ]
    )
    assert [c.name for c in candidate.catalysts] == ["Confirmed", "Estimated", "Late"]


def test_catalysts_between_is_inclusive_at_both_ends() -> None:
    candidate = make_candidate(
        catalysts=[
            make_catalyst(days_out=0, name="Today"),
            make_catalyst(days_out=10, name="Edge"),
            make_catalyst(days_out=11, name="Outside"),
        ]
    )
    window = candidate.catalysts_between(date(2026, 8, 29), date(2026, 9, 8))
    assert [c.name for c in window] == ["Today", "Edge"]


def test_effective_horizon_falls_back_to_the_gate_default() -> None:
    assert make_candidate(horizon_days=None).effective_horizon_days(14) == 14
    assert make_candidate(horizon_days=5).effective_horizon_days(14) == 5


def test_primary_thesis_support_requires_a_non_aggregator_source() -> None:
    aggregator = make_candidate(thesis_sources=[{"label": "Screen", "kind": "aggregator"}])
    assert aggregator.has_primary_thesis_support is False
    assert make_candidate().has_primary_thesis_support is True


def test_catalyst_accepts_the_yaml_date_alias_and_flags_earnings() -> None:
    catalyst = Catalyst.model_validate(
        {"name": "Q3", "date": "2026-09-02", "status": "Conf", "kind": "Earnings"}
    )
    assert catalyst.event_date == date(2026, 9, 2)
    assert catalyst.status is CatalystStatus.CONFIRMED
    assert catalyst.is_earnings is True
    assert Catalyst.model_validate(
        {"name": "CPI", "date": "2026-09-10", "status": "confirmed", "kind": "macro"}
    ).is_earnings is False


def test_thesis_source_kinds_split_primary_from_aggregator() -> None:
    assert ThesisSource(label="EDGAR", kind=SourceKind.REGULATOR).is_primary is True
    assert ThesisSource(label="Screen", kind=SourceKind.AGGREGATOR).is_primary is False
    assert ThesisSource(label="Unknown").is_primary is False


def test_unknown_field_is_rejected_so_yaml_typos_surface() -> None:
    with pytest.raises(ValidationError):
        make_candidate(tickr="NVDA")


@pytest.mark.parametrize(
    "overrides",
    [
        {"ticker": "   "},
        {"thesis": ""},
        {"permitted_instruments": []},
        {"horizon_days": 0},
    ],
)
def test_required_fields_are_enforced(overrides: dict) -> None:
    with pytest.raises(ValidationError):
        make_candidate(**overrides)


def test_candidate_round_trips_through_json() -> None:
    candidate = make_candidate()
    restored = Candidate.model_validate_json(candidate.model_dump_json())
    assert restored == candidate
