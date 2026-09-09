"""End-to-end T2 stage against the shipped example config.

These assertions mirror the T2 acceptance criteria:
  - no-catalyst candidates are demoted before scoring;
  - an Estimated catalyst cannot authorise a leveraged expression;
  - rejected names are persisted and rendered so they are not rediscovered each cycle.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

from briefing_app.components.macro import FACTOR_BUCKETS
from briefing_app.config import AppConfig, load_config
from briefing_app.models.candidate import Instrument
from briefing_app.models.gate import GateDecision, GateFlagCode, GateReasonCode
from briefing_app.options_math import OptionQuote, build_options_structure
from briefing_app.pipeline import (
    ISSUE_SEVERITY_RULES,
    PROVIDER_STATUS_SEVERITY,
    SELF_BUILT_SERIES_MIN_SESSIONS,
    SEVERITY_DEGRADED,
    SEVERITY_NORMAL,
    SEVERITY_OUTAGE,
    STATUS_PARTIAL,
    LiveDataSource,
    _PROVIDER_UNAVAILABLE_RE,
    _aggregated_issue_diagnostics,
    _issue_severity,
    _unsupported_provider_message,
    run_daily,
)
from briefing_app.storage import StorageRepository, create_schema, daily_snapshot
from briefing_app.universe.pipeline import run_candidate_gate
from briefing_app.providers.fred import FRED_MACRO_SERIES
from briefing_app.universe.loader import load_universe
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
    # 17 fixed + 22 screen, minus the five inactive EU duplicate/source rows.
    assert counts["total"] == 32
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

    # SIE.DE is explicitly inactive while EU option-chain coverage is deferred, so it is
    # skipped before gate evaluation rather than emitted as another rejection.
    assert "SIE.DE" not in {result.ticker for result in output.report.results}


def test_confirmed_catalyst_still_authorises_leverage(output) -> None:
    googl = result_for(output.report, "GOOGL")
    assert googl.decision is GateDecision.ACCEPTED
    assert googl.leverage_allowed is True


def test_inactive_non_us_options_names_are_skipped_before_gate(config, output) -> None:
    loaded = load_universe(config)
    assert loaded.inactive_tickers.keys() >= {"RHM.DE", "LDO.MI", "ASML.AS", "SIE.DE"}

    emitted = {result.ticker for result in output.report.results}
    for ticker in ("RHM.DE", "LDO.MI", "ASML.AS", "SIE.DE"):
        assert ticker not in emitted


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
    # Inactive EU rows are retained in config but skipped before gate evaluation.
    assert len(payload["results"]) == 32

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


def test_fixture_daily_run_reports_snapshot_persistence_refusal(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    repo = StorageRepository(engine)

    output = run_daily(
        _lane_c_fixture_config(["NVDA"]),
        run_date=date(2026, 8, 28),
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        repository=repo,
    )

    assert output.status == STATUS_PARTIAL
    assert any("daily_snapshot persistence refused" in item for item in output.diagnostics)
    assert output.html_path is not None and output.html_path.exists()
    with engine.connect() as conn:
        assert conn.execute(select(daily_snapshot)).all() == []


def test_self_built_iv_rank_opens_after_twenty_stored_sessions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    repo = StorageRepository(engine)
    run_id = repo.upsert_briefing_run(
        run_date=date(2026, 8, 31),
        status="succeeded",
        details={"data_mode": "live"},
    )
    run_date = date(2026, 9, 1)

    for offset in range(1, SELF_BUILT_SERIES_MIN_SESSIONS):
        repo.upsert_daily_snapshot(
            {
                "run_id": run_id,
                "ticker": "NVDA",
                "snap_date": run_date - timedelta(days=offset),
                "iv_atm": 0.30 + (offset / 1000),
                "pc_ratio_vol": 0.80 + (offset / 1000),
                "pc_ratio_oi": 0.90 + (offset / 1000),
            }
        )

    source = LiveDataSource()
    issues: list[str] = []
    assert source._stored_option_series(
        "NVDA", run_date=run_date, repository=repo, issues=issues
    ) == ([], [], [])
    assert any(
        f"{SELF_BUILT_SERIES_MIN_SESSIONS - 1} of {SELF_BUILT_SERIES_MIN_SESSIONS} sessions stored"
        in issue
        for issue in issues
    )

    repo.upsert_daily_snapshot(
        {
            "run_id": run_id,
            "ticker": "NVDA",
            "snap_date": run_date - timedelta(days=SELF_BUILT_SERIES_MIN_SESSIONS),
            "iv_atm": 0.29,
            "pc_ratio_vol": 0.79,
            "pc_ratio_oi": 0.89,
        }
    )

    issues = []
    iv_history, pc_vol_history, pc_oi_history = source._stored_option_series(
        "NVDA", run_date=run_date, repository=repo, issues=issues
    )
    assert len(iv_history) == SELF_BUILT_SERIES_MIN_SESSIONS
    assert len(pc_vol_history) == SELF_BUILT_SERIES_MIN_SESSIONS
    assert len(pc_oi_history) == SELF_BUILT_SERIES_MIN_SESSIONS
    assert issues == []

    structure = build_options_structure(
        ticker="NVDA",
        spot=100.0,
        as_of=datetime(2026, 9, 1, 12, tzinfo=UTC),
        option_quotes=_lane_c_option_quotes(date(2026, 9, 8)),
        iv_history=iv_history,
        pc_ratio_vol_history=pc_vol_history,
        pc_ratio_oi_history=pc_oi_history,
    )
    assert structure.iv_rank is not None
    assert structure.put_call is not None
    assert structure.put_call.volume_percentile is not None


def _lane_c_fixture_config(tickers: list[str]) -> AppConfig:
    return AppConfig.model_validate(
        {
            "universe": {
                "mode": "fixed",
                "fixed_min": 0,
                "fixed_max": max(2, len(tickers)),
                "screen_min": 0,
                "screen_max": 0,
                "fixed": [_lane_c_candidate(ticker) for ticker in tickers],
            },
            "gate": {
                "default_horizon_days": 10,
                "enabled_expression_classes": ["E"],
                "require_thesis_source": True,
            },
            "components": {
                "sector_exposures": {
                    "Semiconductors": {
                        "sensitivities": {"policy_rate": -0.7, "cpi": -0.5},
                        "policy_stance": 0.2,
                    }
                }
            },
            "pipeline": {"data_mode": "fixture", "skip_non_market_days": True},
        }
    )


def _lane_c_candidate(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "venue": "NASDAQ",
        "geography": "US",
        "sector": "Semiconductors",
        "direction": "long",
        "thesis": "Fixture event directional setup.",
        "horizon_days": 10,
        "expression_class": "E",
        "broker": "IBKR",
        "permitted_instruments": ["shares", "options"],
        "catalysts": [
            {
                "name": "Quarterly results",
                "date": date(2026, 8, 31),
                "status": "confirmed",
                "kind": "earnings",
                "source": "Company IR",
            }
        ],
        "thesis_sources": [{"label": "Company IR", "kind": "company_ir"}],
    }


def _lane_c_option_quotes(expiry: date) -> list[OptionQuote]:
    return [
        OptionQuote(
            ticker="NVDA",
            expiry=expiry,
            strike=100,
            option_type="C",
            bid=2.40,
            ask=2.60,
            iv=0.45,
            volume=200,
            open_interest=1000,
            delta=0.52,
            gamma=0.02,
        ),
        OptionQuote(
            ticker="NVDA",
            expiry=expiry,
            strike=100,
            option_type="P",
            bid=2.10,
            ask=2.30,
            iv=0.45,
            volume=160,
            open_interest=900,
            delta=-0.48,
            gamma=0.02,
        ),
    ]


# ---------------------------------------------------------------------------------------
# Lane G / D9 - run health.
#
# `ISSUE_SEVERITY_POINTS` is the table in `docs/RUN-HEALTH.md`, one row per
# `issues.append` in `pipeline.py`, keyed by the source line so the two can be diffed.
# It exists so the classification is argued with here rather than rediscovered by a
# reader wondering why yesterday's run said `partial`.
# ---------------------------------------------------------------------------------------

ISSUE_SEVERITY_POINTS: tuple[tuple[int, str, str], ...] = (
    (1885, "FMP historical price EOD normalization failed: bad rows", SEVERITY_DEGRADED),
    (1907, "Twelve Data time series normalization failed: bad rows", SEVERITY_DEGRADED),
    (1936, "Alpha Vantage daily normalization failed: bad rows", SEVERITY_DEGRADED),
    (1941, _unsupported_provider_message("polygon", "prices"), SEVERITY_NORMAL),
    (1973, _unsupported_provider_message("polygon", "macro calendar"), SEVERITY_NORMAL),
    (1994, "FMP economic calendar normalization failed: bad rows", SEVERITY_DEGRADED),
    (2072, "FRED release 10 upcoming dates normalization failed: bad", SEVERITY_DEGRADED),
    (2129, _unsupported_provider_message("polygon", "macro readings"), SEVERITY_NORMAL),
    (2149, "FMP economic indicator CPI normalization failed: bad", SEVERITY_DEGRADED),
    (2176, "FMP treasury rates normalization failed: bad", SEVERITY_DEGRADED),
    (2227, "Alpha Vantage earnings normalization failed: bad", SEVERITY_DEGRADED),
    (2253, "FMP earnings normalization failed: bad", SEVERITY_DEGRADED),
    (2255, _unsupported_provider_message("polygon", "earnings"), SEVERITY_NORMAL),
    (2287, "Alpha Vantage news normalization failed: bad", SEVERITY_DEGRADED),
    (2303, "FMP stock news normalization failed: bad", SEVERITY_DEGRADED),
    (2315, "Finnhub company news unavailable (network_error): timeout", SEVERITY_OUTAGE),
    (2318, _unsupported_provider_message("polygon", "news"), SEVERITY_NORMAL),
    (2370, _unsupported_provider_message("polygon", "political"), SEVERITY_NORMAL),
    (2400, "FMP senate latest normalization failed: bad", SEVERITY_DEGRADED),
    (2426, _unsupported_provider_message("polygon", "retail"), SEVERITY_NORMAL),
    (2458, "ApeWisdom retail momentum page 2 normalization failed: bad", SEVERITY_DEGRADED),
    (2500, _unsupported_provider_message("polygon", "analyst"), SEVERITY_NORMAL),
    (2539, "FMP grades consensus normalization failed: bad", SEVERITY_DEGRADED),
    (2589, "FRED series CPIAUCSL reported no release id", SEVERITY_DEGRADED),
    (2645, "FRED release 10 dates normalization failed: bad", SEVERITY_DEGRADED),
    (2716, "FRED series CPIAUCSL normalization failed: bad", SEVERITY_DEGRADED),
    (
        2743,
        "self-built IV and put/call baselines need persistence; no database is "
        "configured for this run",
        SEVERITY_DEGRADED,
    ),
    (2768, "iv_rank baseline still building: 3 of 20 sessions stored", SEVERITY_NORMAL),
    (2798, _unsupported_provider_message("polygon", "short_interest"), SEVERITY_NORMAL),
    (2838, "finra short volume normalization failed: bad", SEVERITY_DEGRADED),
    (
        2870,
        "SEC EDGAR Form 4 index unavailable (network_error): connection reset",
        SEVERITY_OUTAGE,
    ),
    (2905, "sec_edgar Form 4 0001-24-000123 normalization failed: bad", SEVERITY_DEGRADED),
    (2954, _unsupported_provider_message("polygon", "insider"), SEVERITY_NORMAL),
    (2962, "fmp insider normalization failed: bad", SEVERITY_DEGRADED),
    (2977, "FMP historical price EOD unavailable (budget_exhausted): spent", SEVERITY_OUTAGE),
    (3559, "cached FMP senate_latest 2026-09-01 ignored: bad json", SEVERITY_DEGRADED),
)


def test_every_issue_recording_point_has_a_declared_severity() -> None:
    """Every `issues.append` in the pipeline is classified, and the table covers them all."""

    source = Path("src/briefing_app/pipeline.py").read_text(encoding="utf-8").splitlines()
    recording_lines = {
        number
        for number, line in enumerate(source, start=1)
        if "issues.append" in line
    }
    documented = {line for line, _, _ in ISSUE_SEVERITY_POINTS}

    assert recording_lines == documented, (
        "docs/RUN-HEALTH.md and this table must be updated together with pipeline.py; "
        f"undocumented: {sorted(recording_lines - documented)}, "
        f"stale: {sorted(documented - recording_lines)}"
    )

    for line, message, expected in ISSUE_SEVERITY_POINTS:
        assert _issue_severity(message) == expected, f"pipeline.py:{line}: {message}"


def test_no_recording_point_relies_on_the_unclassified_default() -> None:
    """The `degraded` fallback is a safety net, not the classification of a known point.

    A point that reached its severity by falling through would silently change meaning the
    day the default changes, and the table in the document would be describing nothing.
    """

    for line, message, _ in ISSUE_SEVERITY_POINTS:
        matched_status = _PROVIDER_UNAVAILABLE_RE.search(message)
        matched_rule = any(marker in message for marker, _ in ISSUE_SEVERITY_RULES)
        assert (
            matched_status is not None and matched_status.group(1) in PROVIDER_STATUS_SEVERITY
        ) or matched_rule, f"pipeline.py:{line} falls through to the default: {message}"


def test_entitlement_refusals_are_normal_and_unreached_sources_are_an_outage() -> None:
    """The dividing line D9 turns on, stated as one assertion.

    A key the owner never bought and a plan they never paid for are standing facts,
    identical every run. A spent allowance, a throttle and a dead socket are a source that
    should have answered and did not.
    """

    for status in ("no_credentials", "plan_gated", "paywalled"):
        assert _issue_severity(f"FMP earnings unavailable ({status}): x") == SEVERITY_NORMAL
    for status in ("budget_exhausted", "throttled", "network_error"):
        assert _issue_severity(f"FMP earnings unavailable ({status}): x") == SEVERITY_OUTAGE
    for status in ("missing", "malformed", "truncated", "placeholder", "repeat_refusal"):
        assert _issue_severity(f"FMP earnings unavailable ({status}): x") == SEVERITY_DEGRADED

    # An issue nobody classified is assumed to be a real gap: a wrong `degraded` is visible
    # and gets corrected, a wrong `normal` is the defect D9 exists to close.
    assert _issue_severity("something new nobody wrote a rule for") == SEVERITY_DEGRADED


def test_eighteen_names_missing_prices_is_one_diagnostic_naming_the_eighteen() -> None:
    """Aggregation. A diagnostics list nobody can read is the same failure in a costume."""

    tickers = [f"T{index:02d}" for index in range(18)]
    issue = "FMP historical price EOD unavailable (budget_exhausted): allowance spent"
    warm_up = "iv_rank baseline still building: 3 of 20 sessions stored"

    diagnostics = _aggregated_issue_diagnostics(
        {ticker: (issue, warm_up) for ticker in tickers}, attempted=18
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].startswith("outage: ")
    assert "allowance spent" in diagnostics[0]
    assert "all 18 names" in diagnostics[0]

    # A subset names its members, so a reader can tell two names from eighteen.
    partial = _aggregated_issue_diagnostics(
        {ticker: (issue,) for ticker in tickers[:2]}, attempted=18
    )
    assert len(partial) == 1
    assert "2 of 18 names: T00, T01" in partial[0]
