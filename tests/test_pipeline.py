"""End-to-end T2 stage against the shipped example config.

These assertions mirror the T2 acceptance criteria:
  - no-catalyst candidates are demoted before scoring;
  - an Estimated catalyst cannot authorise a leveraged expression;
  - rejected names are persisted and rendered so they are not rediscovered each cycle.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from briefing_app.components.macro import FACTOR_BUCKETS
from briefing_app.config import load_config
from briefing_app.models.candidate import Instrument
from briefing_app.models.gate import GateDecision, GateFlagCode, GateReasonCode
from briefing_app.universe.pipeline import run_candidate_gate
from briefing_app.providers.fred import FRED_MACRO_SERIES
from briefing_app.universe.store import JsonGateStore

EXAMPLE_CONFIG = Path("config/config.example.yaml")
RUN_DATE = date(2026, 8, 29)


@pytest.fixture
def config():
    return load_config(EXAMPLE_CONFIG)


@pytest.fixture
def output(config, tmp_path):
    return run_candidate_gate(
        config,
        run_date=RUN_DATE,
        store=JsonGateStore(tmp_path / "data"),
        output_dir=tmp_path / "output",
    )


def result_for(report, ticker):
    return next(r for r in report.results if r.ticker == ticker)


def test_example_universe_loads_without_errors(output) -> None:
    assert output.report.load_errors == []
    assert output.report.load_warnings == []
    counts = output.report.counts()
    # 15 fixed + 22 screen. Grew from 32 on 2026-08-31 with INTC, CRWV, AMAT,
    # RHM.DE and LDO.MI.
    assert counts["total"] == 37
    assert counts["accepted"] > 0 and counts["watchlist"] > 0 and counts["rejected"] > 0


def test_no_catalyst_in_horizon_is_demoted_before_scoring(output) -> None:
    for ticker in ("TSLA", "KO", "PG"):
        result = result_for(output.report, ticker)
        assert result.decision is GateDecision.WATCHLIST
        assert GateReasonCode.NO_CATALYST_IN_HORIZON in result.reason_codes
        assert result.is_scored is False
    assert {"TSLA", "KO", "PG"}.isdisjoint({r.ticker for r in output.report.accepted})


def test_estimated_catalyst_cannot_authorise_a_leveraged_expression(output) -> None:
    # AAPL keeps its unleveraged expressions but loses the knock-out.
    aapl = result_for(output.report, "AAPL")
    assert aapl.decision is GateDecision.ACCEPTED
    assert aapl.leverage_allowed is False
    assert Instrument.KNOCK_OUT not in aapl.permitted_instruments
    assert GateFlagCode.LEVERAGE_BLOCKED_ESTIMATED_CATALYST in aapl.flag_codes

    # SIE.DE can only be expressed with leverage, so it is demoted outright.
    sie = result_for(output.report, "SIE.DE")
    assert sie.decision is GateDecision.WATCHLIST
    assert GateReasonCode.LEVERAGE_REQUIRES_CONFIRMED_CATALYST in sie.reason_codes


def test_confirmed_catalyst_still_authorises_leverage(output) -> None:
    googl = result_for(output.report, "GOOGL")
    assert googl.decision is GateDecision.ACCEPTED
    assert googl.leverage_allowed is True


def test_non_us_options_names_degrade_instead_of_being_scored(output) -> None:
    for ticker in ("RHM.DE", "ASML.AS"):
        result = result_for(output.report, ticker)
        assert result.decision is GateDecision.WATCHLIST
        assert GateReasonCode.EU_OPTIONS_UNAVAILABLE in result.reason_codes


def test_classes_that_need_plan_gated_components_are_demoted(output) -> None:
    for ticker in ("BRK.B", "WBA", "CVNA"):
        result = result_for(output.report, ticker)
        assert result.decision is GateDecision.WATCHLIST
        assert GateReasonCode.CLASS_NOT_ENABLED in result.reason_codes
    assert GateReasonCode.BORROW_SOURCE_UNDECLARED in result_for(
        output.report, "CVNA"
    ).reason_codes


def test_duplicate_across_files_is_rejected_once_and_scored_once(output) -> None:
    nvda = [r for r in output.report.results if r.ticker == "NVDA"]
    assert [r.decision for r in nvda] == [GateDecision.ACCEPTED, GateDecision.REJECTED]
    assert GateReasonCode.DUPLICATE_TICKER in nvda[1].reason_codes


def test_run_writes_report_markdown_and_history(output, tmp_path) -> None:
    assert output.report_path == (
        tmp_path / "data" / "candidate_gate" / "2026-08-29" / "gate_report.json"
    )
    assert output.markdown_path == (
        tmp_path / "output" / "candidate_gate" / "2026-08-29" / "candidate_gate.md"
    )

    payload = json.loads(output.report_path.read_text(encoding="utf-8"))
    assert payload["run_date"] == "2026-08-29"
    # 15 fixed + 22 screen. Grew from 32 on 2026-08-31 with INTC, CRWV, AMAT,
    # RHM.DE and LDO.MI.
    assert len(payload["results"]) == 37

    markdown = output.markdown_path.read_text(encoding="utf-8")
    assert "## Scored candidates" in markdown and "## Rejected at gate" in markdown

    history = JsonGateStore(tmp_path / "data").load_history()
    assert "TSLA" in history and "NVDA" in history
    # A name that passed the gate is not in the rejection ledger.
    assert "GOOGL" not in history


def test_rejected_names_are_carried_and_marked_on_the_next_run(config, tmp_path) -> None:
    store = JsonGateStore(tmp_path / "data")
    kwargs = {"store": store, "output_dir": tmp_path / "output"}
    run_candidate_gate(config, run_date=RUN_DATE, **kwargs)
    second = run_candidate_gate(config, run_date=RUN_DATE + timedelta(days=3), **kwargs)

    tsla = result_for(second.report, "TSLA")
    assert tsla.is_repeat is True
    assert tsla.occurrences == 2
    assert tsla.first_flagged_on == RUN_DATE
    assert "**Carried from previous runs:**" in second.markdown
    assert "TSLA (2x since 2026-08-29)" in second.markdown


def test_persistence_can_be_switched_off(config, tmp_path) -> None:
    output = run_candidate_gate(
        config,
        run_date=RUN_DATE,
        store=JsonGateStore(tmp_path / "data"),
        output_dir=tmp_path / "output",
        persist=False,
    )
    assert output.report_path is None and output.markdown_path is None
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "output").exists()


def test_every_declared_sector_sensitivity_has_a_mapped_macro_series(config) -> None:
    """A factor a sector declares but no provider maps can never score.

    This was the P5 gap: seven sensitivities in the shipped config had no series behind
    them, so `_declared_macro_factors` named factors that nothing ever fetched and the
    commodity bucket scored for no sector at all. The failure is silent - an unmapped
    factor looks exactly like a factor that had nothing to say - so it is pinned here
    instead of being left for a live run to reveal.
    """

    declared = {
        factor
        for exposure in config.components.sector_exposures.values()
        for factor in exposure.sensitivities
    }
    assert declared, "the example config declares no sector sensitivities"
    assert declared <= set(FRED_MACRO_SERIES), (
        "sensitivities declared with no FRED series: "
        f"{sorted(declared - set(FRED_MACRO_SERIES))}"
    )
    assert declared <= set(FACTOR_BUCKETS), (
        "sensitivities declared with no factor bucket, which `_bucket_scores` skips: "
        f"{sorted(declared - set(FACTOR_BUCKETS))}"
    )
