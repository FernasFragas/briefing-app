"""Catalyst-gate rules, tested at their boundaries."""

from __future__ import annotations

import json

from datetime import date, timedelta

import pytest

from briefing_app.config import GateSettings
from briefing_app.models.candidate import ExpressionClass, Instrument
from briefing_app.models.gate import (
    GateDecision,
    GateFlagCode,
    GateReasonCode,
    to_candidate_gate_rows,
)
from briefing_app.universe.gate import evaluate_candidate, run_gate
from briefing_app.universe.store import RejectionRecord
from tests.conftest import RUN_DATE, make_candidate, make_catalyst


def gate(candidate, settings, **kwargs):
    return evaluate_candidate(
        candidate, run_date=RUN_DATE, settings=settings, **kwargs
    )


# --- catalyst gate ------------------------------------------------------------------


def test_candidate_with_a_dated_catalyst_in_horizon_is_scored(settings) -> None:
    result = gate(make_candidate(), settings)
    assert result.decision is GateDecision.ACCEPTED
    assert result.is_scored is True
    assert result.reasons == []


def test_no_catalyst_in_horizon_is_demoted_to_watchlist(settings) -> None:
    result = gate(make_candidate(catalysts=[]), settings)
    assert result.decision is GateDecision.WATCHLIST
    assert result.is_scored is False
    assert GateReasonCode.NO_CATALYST_IN_HORIZON in result.reason_codes


@pytest.mark.parametrize(
    ("days_out", "expected"),
    [
        (0, GateDecision.ACCEPTED),  # today counts
        (10, GateDecision.ACCEPTED),  # last day of a 10d horizon counts
        (11, GateDecision.WATCHLIST),  # one day past the horizon does not
        (-1, GateDecision.WATCHLIST),  # yesterday does not
    ],
)
def test_horizon_window_boundaries(settings, days_out: int, expected) -> None:
    candidate = make_candidate(horizon_days=10, catalysts=[make_catalyst(days_out=days_out)])
    assert gate(candidate, settings).decision is expected


def test_horizon_falls_back_to_the_configured_default(settings) -> None:
    settings.default_horizon_days = 30
    candidate = make_candidate(horizon_days=None, catalysts=[make_catalyst(days_out=20)])
    result = gate(candidate, settings)
    assert result.horizon_days == 30
    assert result.window_end == RUN_DATE + timedelta(days=30)
    assert result.decision is GateDecision.ACCEPTED


def test_primary_catalyst_is_the_earliest_in_horizon_event(settings) -> None:
    candidate = make_candidate(
        horizon_days=20,
        catalysts=[
            make_catalyst(days_out=15, name="Later"),
            make_catalyst(days_out=2, name="First"),
            make_catalyst(days_out=40, name="Outside"),
        ],
    )
    result = gate(candidate, settings)
    assert result.primary_catalyst is not None
    assert result.primary_catalyst.name == "First"
    assert [c.name for c in result.catalysts_in_horizon] == ["First", "Later"]


def test_earnings_inside_the_window_is_flagged_for_the_range_builder(settings) -> None:
    candidate = make_candidate(catalysts=[make_catalyst(kind="earnings")])
    result = gate(candidate, settings)
    assert result.earnings_in_horizon is True
    assert GateFlagCode.EARNINGS_IN_HORIZON in result.flag_codes


# --- leverage guard -----------------------------------------------------------------


def test_estimated_catalyst_withdraws_leveraged_instruments(settings) -> None:
    candidate = make_candidate(
        permitted_instruments=["shares", "options", "knock_out", "factor_certificate"],
        catalysts=[make_catalyst(status="estimated")],
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.ACCEPTED
    assert result.leverage_allowed is False
    assert result.permitted_instruments == [Instrument.SHARES, Instrument.OPTIONS]
    assert result.blocked_instruments == [Instrument.KNOCK_OUT, Instrument.FACTOR_CERTIFICATE]
    assert GateFlagCode.LEVERAGE_BLOCKED_ESTIMATED_CATALYST in result.flag_codes
    assert GateFlagCode.ESTIMATED_CATALYST_ONLY in result.flag_codes


def test_confirmed_catalyst_authorises_leverage(settings) -> None:
    candidate = make_candidate(
        permitted_instruments=["shares", "knock_out"],
        catalysts=[make_catalyst(status="confirmed")],
    )
    result = gate(candidate, settings)
    assert result.leverage_allowed is True
    assert Instrument.KNOCK_OUT in result.permitted_instruments
    assert result.blocked_instruments == []


def test_one_confirmed_catalyst_among_estimated_ones_authorises_leverage(settings) -> None:
    candidate = make_candidate(
        horizon_days=20,
        permitted_instruments=["shares", "knock_out"],
        catalysts=[
            make_catalyst(days_out=3, status="estimated"),
            make_catalyst(days_out=8, status="confirmed"),
        ],
    )
    assert gate(candidate, settings).leverage_allowed is True


def test_leverage_only_platform_with_an_estimated_catalyst_is_demoted(settings) -> None:
    candidate = make_candidate(
        broker="Trade Republic",
        permitted_instruments=["knock_out", "factor_certificate"],
        catalysts=[make_catalyst(status="estimated")],
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.WATCHLIST
    assert GateReasonCode.LEVERAGE_REQUIRES_CONFIRMED_CATALYST in result.reason_codes
    assert GateReasonCode.NO_INSTRUMENT_FIT not in result.reason_codes


def test_leverage_guard_can_be_disabled_explicitly(settings) -> None:
    settings.allow_leverage_on_estimated_catalyst = True
    candidate = make_candidate(
        permitted_instruments=["knock_out"], catalysts=[make_catalyst(status="estimated")]
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.ACCEPTED
    assert result.leverage_allowed is True


def test_leveraged_instrument_set_is_configurable(settings) -> None:
    settings.leveraged_instruments = [Instrument.FACTOR_CERTIFICATE]
    candidate = make_candidate(
        permitted_instruments=["knock_out", "factor_certificate"],
        catalysts=[make_catalyst(status="estimated")],
    )
    result = gate(candidate, settings)
    assert result.permitted_instruments == [Instrument.KNOCK_OUT]
    assert result.blocked_instruments == [Instrument.FACTOR_CERTIFICATE]


# --- instrument fit -----------------------------------------------------------------


def test_class_with_no_tradeable_instrument_is_rejected(settings) -> None:
    candidate = make_candidate(
        expression_class="V", broker="Cash account", permitted_instruments=["shares"]
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.REJECTED
    assert GateReasonCode.NO_INSTRUMENT_FIT in result.reason_codes


def test_instrument_fit_map_is_configurable(settings) -> None:
    settings.class_instrument_fit[ExpressionClass.V] = [Instrument.OPTIONS, Instrument.FUTURES]
    candidate = make_candidate(expression_class="V", permitted_instruments=["futures"])
    assert gate(candidate, settings).decision is GateDecision.ACCEPTED


# --- expression class availability --------------------------------------------------


@pytest.mark.parametrize("expression_class", ["P", "S"])
def test_class_disabled_for_the_run_is_demoted(settings, expression_class: str) -> None:
    settings.enabled_expression_classes = [ExpressionClass.V, ExpressionClass.E]
    candidate = make_candidate(
        expression_class=expression_class, borrow_source="IBKR shortable list"
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.WATCHLIST
    assert GateReasonCode.CLASS_NOT_ENABLED in result.reason_codes


# --- non-US options degradation -----------------------------------------------------


@pytest.mark.parametrize("expression_class", ["V", "E"])
def test_non_us_options_class_is_demoted_when_no_chain_track_exists(
    settings, expression_class: str
) -> None:
    settings.eu_options_track = "C"
    candidate = make_candidate(
        expression_class=expression_class, geography="EU", venue="XETRA"
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.WATCHLIST
    assert GateReasonCode.EU_OPTIONS_UNAVAILABLE in result.reason_codes


def test_manual_eu_chain_capture_is_flagged_not_blocked(settings) -> None:
    settings.eu_options_track = "B"
    result = gate(make_candidate(geography="EU", venue="XETRA"), settings)
    assert result.decision is GateDecision.ACCEPTED
    assert GateFlagCode.EU_OPTIONS_MANUAL_CAPTURE in result.flag_codes


def test_browser_eu_chain_capture_passes_clean(settings) -> None:
    settings.eu_options_track = "A"
    result = gate(make_candidate(geography="EU", venue="XETRA"), settings)
    assert result.decision is GateDecision.ACCEPTED
    assert GateFlagCode.EU_OPTIONS_MANUAL_CAPTURE not in result.flag_codes


def test_us_names_are_unaffected_by_the_eu_options_track(settings) -> None:
    settings.eu_options_track = "C"
    assert gate(make_candidate(geography="US"), settings).decision is GateDecision.ACCEPTED


def test_non_us_positional_class_does_not_need_a_chain(settings) -> None:
    settings.eu_options_track = "C"
    candidate = make_candidate(
        expression_class="P", geography="EU", venue="XETRA", permitted_instruments=["shares"]
    )
    result = gate(candidate, settings)
    assert GateReasonCode.EU_OPTIONS_UNAVAILABLE not in result.reason_codes


# --- borrow-dependent shorts --------------------------------------------------------


def test_short_without_a_declared_borrow_source_is_demoted(settings) -> None:
    candidate = make_candidate(
        expression_class="S", direction="short", borrow_source=None
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.WATCHLIST
    assert GateReasonCode.BORROW_SOURCE_UNDECLARED in result.reason_codes


def test_short_with_a_borrow_source_carries_a_verification_obligation(settings) -> None:
    candidate = make_candidate(
        expression_class="S", direction="short", borrow_source="IBKR shortable list"
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.ACCEPTED
    assert result.requires_borrow_verification is True
    assert GateFlagCode.REQUIRES_BORROW_VERIFICATION in result.flag_codes


def test_non_short_classes_carry_no_borrow_obligation(settings) -> None:
    assert gate(make_candidate(), settings).requires_borrow_verification is False


# --- thesis sourcing and crowding ---------------------------------------------------


def test_aggregator_only_thesis_is_flagged_by_default(settings) -> None:
    candidate = make_candidate(thesis_sources=[{"label": "Screen", "kind": "aggregator"}])
    result = gate(candidate, settings)
    assert result.decision is GateDecision.ACCEPTED
    assert GateFlagCode.UNVERIFIED_THESIS in result.flag_codes


def test_aggregator_only_thesis_can_be_configured_to_demote(settings) -> None:
    settings.unverified_thesis_action = "watchlist"
    candidate = make_candidate(thesis_sources=[])
    result = gate(candidate, settings)
    assert result.decision is GateDecision.WATCHLIST
    assert GateReasonCode.UNVERIFIED_THESIS in result.reason_codes


def test_thesis_source_check_can_be_switched_off(settings) -> None:
    settings.require_thesis_source = False
    result = gate(make_candidate(thesis_sources=[]), settings)
    assert GateFlagCode.UNVERIFIED_THESIS not in result.flag_codes


def test_crowded_consensus_trade_cuts_confidence_without_blocking(settings) -> None:
    candidate = make_candidate(
        crowding="consensus", catalysts=[make_catalyst(telegraphed=True)]
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.ACCEPTED
    assert result.confidence_multiplier == settings.crowded_confidence_multiplier
    assert GateFlagCode.CROWDED_CONSENSUS_TRADE in result.flag_codes


def test_crowding_without_a_telegraphed_catalyst_keeps_full_confidence(settings) -> None:
    result = gate(make_candidate(crowding="consensus"), settings)
    assert result.confidence_multiplier == 1.0
    assert GateFlagCode.CROWDED_CONSENSUS_TRADE not in result.flag_codes


# --- decision resolution and repeat detection ---------------------------------------


def test_every_applicable_reason_is_reported_and_the_worst_one_decides(settings) -> None:
    settings.enabled_expression_classes = [ExpressionClass.E]
    candidate = make_candidate(
        expression_class="V", permitted_instruments=["shares"], catalysts=[]
    )
    result = gate(candidate, settings)
    assert result.decision is GateDecision.REJECTED
    assert set(result.reason_codes) == {
        GateReasonCode.CLASS_NOT_ENABLED,
        GateReasonCode.NO_CATALYST_IN_HORIZON,
        GateReasonCode.NO_INSTRUMENT_FIT,
    }


def test_prior_rejection_history_marks_a_repeat(settings) -> None:
    history = {
        "TEST": RejectionRecord(
            ticker="TEST",
            decision=GateDecision.WATCHLIST,
            reason_codes=[GateReasonCode.NO_CATALYST_IN_HORIZON],
            first_flagged_on=date(2026, 7, 1),
            last_flagged_on=date(2026, 8, 22),
            occurrences=3,
        )
    }
    result = gate(make_candidate(catalysts=[]), settings, history=history)
    assert result.is_repeat is True
    assert result.first_flagged_on == date(2026, 7, 1)
    assert result.occurrences == 4


def test_accepted_candidate_carries_no_rejection_bookkeeping(settings) -> None:
    result = gate(make_candidate(), settings)
    assert result.is_repeat is False
    assert result.occurrences == 0
    assert result.first_flagged_on is None


# --- whole-universe pass ------------------------------------------------------------


def test_duplicate_tickers_keep_the_first_record_and_reject_the_rest(settings) -> None:
    first = make_candidate(ticker="NVDA", origin="universe.yaml")
    duplicate = make_candidate(ticker="NVDA", origin="watchlist.csv")
    report = run_gate([first, duplicate], run_date=RUN_DATE, settings=settings)
    assert [r.decision for r in report.results] == [
        GateDecision.ACCEPTED,
        GateDecision.REJECTED,
    ]
    assert "universe.yaml" in report.results[1].reason_summary()


def test_report_separates_scored_names_from_gated_out_names(settings) -> None:
    report = run_gate(
        [
            make_candidate(ticker="AAA"),
            make_candidate(ticker="BBB", catalysts=[]),
            make_candidate(ticker="CCC", expression_class="V", permitted_instruments=["shares"]),
        ],
        run_date=RUN_DATE,
        settings=settings,
    )
    assert [r.ticker for r in report.accepted] == ["AAA"]
    assert [r.ticker for r in report.watchlist] == ["BBB"]
    assert [r.ticker for r in report.rejected] == ["CCC"]
    assert [r.ticker for r in report.gated_out] == ["BBB", "CCC"]
    assert report.counts() == {
        "total": 3,
        "accepted": 1,
        "watchlist": 1,
        "rejected": 1,
        "repeat": 0,
    }


def test_gate_rows_match_the_candidate_gate_table_shape(settings) -> None:
    report = run_gate(
        [make_candidate(ticker="AAA"), make_candidate(ticker="BBB", catalysts=[])],
        run_date=RUN_DATE,
        settings=settings,
    )
    rows = to_candidate_gate_rows(report, run_id=42)
    assert [row["ticker"] for row in rows] == ["AAA", "BBB"]
    assert {k: v for k, v in rows[0].items() if k != "details"} == {
        "run_id": 42,
        "ticker": "AAA",
        "decision": "accepted",
        "reason": None,
        "catalyst_name": "Quarterly results",
        "catalyst_date": date(2026, 9, 1),
        "catalyst_status": "confirmed",
        "expression_class": "E",
    }
    assert rows[0]["details"]["reason_codes"] == []
    assert rows[0]["details"]["permitted_instruments"] == ["shares", "options"]
    assert rows[1]["catalyst_name"] is None
    assert "no dated catalyst" in rows[1]["reason"]
    assert rows[1]["details"]["reason_codes"] == ["no_catalyst_in_horizon"]


def test_gate_rows_collapse_duplicates_onto_the_kept_record(settings) -> None:
    """`candidate_gate` is keyed by (run_id, ticker), so one ticker means one row."""
    report = run_gate(
        [make_candidate(ticker="NVDA"), make_candidate(ticker="NVDA")],
        run_date=RUN_DATE,
        settings=settings,
    )
    rows = to_candidate_gate_rows(report, run_id=7)
    assert len(rows) == 1
    assert rows[0]["decision"] == "accepted"
    assert rows[0]["details"]["duplicate_entries"] == 1


def test_gate_rows_are_json_serialisable_for_a_jsonb_column(settings) -> None:
    report = run_gate([make_candidate()], run_date=RUN_DATE, settings=settings)
    row = to_candidate_gate_rows(report)[0]
    assert json.loads(json.dumps(row["details"]))["horizon_days"] == 10


def test_run_id_and_load_diagnostics_are_carried_on_the_report(settings) -> None:
    report = run_gate(
        [make_candidate()],
        run_date=RUN_DATE,
        settings=settings,
        run_id="gate-fixture",
        load_warnings=["only 1 candidate"],
        load_errors=["bad row 7"],
    )
    assert report.run_id == "gate-fixture"
    assert report.run_date == RUN_DATE
    assert report.load_warnings == ["only 1 candidate"]
    assert report.load_errors == ["bad row 7"]
