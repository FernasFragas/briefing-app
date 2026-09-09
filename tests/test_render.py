"""Markdown and dashboard HTML rendering."""

from __future__ import annotations

from datetime import UTC, date, datetime
from html.parser import HTMLParser

from briefing_app.dashboard.models import (
    ConditionalityRow,
    DashboardPayload,
    EvidenceLedgerRow,
    MarketOverviewPoint,
    MasterAlphaRow,
    PerTickerSection,
    PriorScorecardRow,
    RejectedGateRow,
    RunHealth,
    TacticalDashboard,
    TradingIdeaRow,
)
from briefing_app.dashboard.render import render_dashboard_html
from briefing_app.models.gate import GateDecision, GateReasonCode
from briefing_app.universe.gate import run_gate
from briefing_app.universe.render import (
    render_accepted_table,
    render_gate_markdown,
    render_rejected_table,
)
from briefing_app.universe.store import RejectionRecord
from tests.conftest import RUN_DATE, make_candidate, make_catalyst

DASHBOARD_NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


class DashboardHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._tag_stack: list[str] = []
        self._current_section: str | None = None
        self._current_row: list[str] | None = None
        self._current_cell_parts: list[str] | None = None
        self.section_order: list[str] = []
        self.sections_in_details: set[str] = set()
        self.rows_by_section: dict[str, list[list[str]]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "section":
            section_id = attrs_dict.get("id")
            if section_id:
                self._current_section = section_id
                self.section_order.append(section_id)
                if "details" in self._tag_stack:
                    self.sections_in_details.add(section_id)
        elif tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell_parts = []
        self._tag_stack.append(tag)

    def handle_data(self, data: str) -> None:
        if self._current_cell_parts is not None:
            text = data.strip()
            if text:
                self._current_cell_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_row is not None:
            cell_text = " ".join(" ".join(self._current_cell_parts or []).split())
            self._current_row.append(cell_text)
            self._current_cell_parts = None
        elif tag == "tr" and self._current_row is not None:
            if self._current_section:
                self.rows_by_section.setdefault(self._current_section, []).append(
                    self._current_row
                )
            self._current_row = None
        elif tag == "section":
            self._current_section = None

        for index in range(len(self._tag_stack) - 1, -1, -1):
            if self._tag_stack[index] == tag:
                del self._tag_stack[index:]
                break


def parse_dashboard_html(html: str) -> DashboardHTMLParser:
    parser = DashboardHTMLParser()
    parser.feed(html)
    return parser


def dashboard_payload(
    *, trading_ideas: list[TradingIdeaRow] | None = None
) -> DashboardPayload:
    if trading_ideas is None:
        trading_ideas = [
            TradingIdeaRow(
                ticker="NVDA",
                setup_type="EVENT_DIRECTIONAL_LONG",
                grade_letter="B+",
                grade_score=77.4,
                posture="moderate_bullish",
                composite_score=0.62,
                thesis_probability=0.68,
                thesis_band="beyond +1 sigma",
                direction="long",
                s_cte=0.62,
                tier="A",
                status="TRADEABLE",
                catalyst={
                    "name": "Quarterly results",
                    "date": "2026-09-01",
                    "status": "confirmed",
                },
                headline="NVDA event-directional long",
            )
        ]
    return DashboardPayload(
        run_id="dashboard-render-test",
        run_date=RUN_DATE,
        generated_at=DASHBOARD_NOW,
        data_mode="fixture",
        trading_ideas=trading_ideas,
        prior_scorecard=[
            PriorScorecardRow(
                ticker="NVDA",
                snap_date="2026-08-28",
                cte_score=0.62,
                confidence_tier="A",
                expression_class="directional",
                component_scores={"S_S": 0.4},
            )
        ],
        market_overview=[
            MarketOverviewPoint(
                label="VIX",
                value=14.2,
                source="CBOE fixture",
                as_of="2026-08-29",
            )
        ],
        master_alpha_selection_matrix=[
            MasterAlphaRow(
                ticker="NVDA",
                gate_decision="accepted",
                expression_class="directional",
                direction="long",
                s_cte=0.62,
                tier="A",
                posture="risk-on",
                top_setup="EVENT_DIRECTIONAL_LONG",
            )
        ],
        rejected_at_gate=[
            RejectedGateRow(
                ticker="TSLA",
                decision="rejected",
                reason_codes=["no_catalyst_in_horizon"],
                detail="No near catalyst.",
            )
        ],
        evidence_ledger=[
            EvidenceLedgerRow(
                ticker="NVDA",
                component="S_S",
                field_name="sentiment",
                field_value="0.4",
                source="fixture",
                as_of="2026-08-29",
            )
        ],
        tactical_execution_dashboard=TacticalDashboard(
            top_long={
                "ticker": "NVDA",
                "setup_type": "EVENT_DIRECTIONAL_LONG",
                "instrument": "call spread",
                "tier": "A",
                "s_cte": 0.62,
                "horizon_label": "1w",
                "invalidation": {"description": "below 95"},
            }
        ),
        conditionality_table=[
            ConditionalityRow(
                ticker="NVDA",
                setup_type="EVENT_DIRECTIONAL_LONG",
                decision="TRADEABLE",
                catalyst={
                    "name": "Quarterly results",
                    "date": "2026-09-01",
                    "status": "confirmed",
                },
                invalidation={"description": "below 95"},
                triggers=["breakout"],
            )
        ],
        per_ticker_sections=[
            PerTickerSection(
                ticker="NVDA",
                gate={"decision": "ACCEPTED"},
                score={"s_cte": 0.62},
                components=[
                    {
                        "component": "S_S",
                        "score": 0.4,
                        "validation_status": "partial",
                        "source_quality": "mixed",
                        "legs_summary": "1 of 3 legs",
                        "leg_count_note": (
                            "fixture leg counts describe the fixture, not live sourcing"
                        ),
                        "absent_legs": [
                            {
                                "name": "executive_tone",
                                "reason": "no transcript source available",
                            }
                        ],
                        "na_reason": None,
                    }
                ],
                setups=[
                    {
                        "setup_type": "EVENT_DIRECTIONAL_LONG",
                        "decision": "TRADEABLE",
                        "instrument": "call spread",
                        "tier": "A",
                        "horizon_label": "1w",
                        "invalidation": {"description": "below 95"},
                    }
                ],
                prose="NVDA setup.",
            )
        ],
    )


def build_report(settings, **kwargs):
    candidates = [
        make_candidate(ticker="NVDA", catalysts=[make_catalyst(days_out=4, kind="earnings")]),
        make_candidate(ticker="KO", catalysts=[]),
        make_candidate(
            ticker="NKE", expression_class="V", permitted_instruments=["shares"]
        ),
    ]
    return run_gate(candidates, run_date=RUN_DATE, settings=settings, **kwargs)


def test_scored_and_gated_out_names_land_in_different_tables(settings) -> None:
    report = build_report(settings)
    accepted = render_accepted_table(report)
    rejected = render_rejected_table(report)

    assert "NVDA" in accepted and "KO" not in accepted and "NKE" not in accepted
    assert "KO" in rejected and "NKE" in rejected and "NVDA" not in rejected
    assert "no_catalyst_in_horizon" in rejected
    assert GateReasonCode.NO_INSTRUMENT_FIT.value in rejected


def test_accepted_row_carries_catalyst_instruments_and_flags(settings) -> None:
    report = build_report(settings)
    row = [line for line in render_accepted_table(report).splitlines() if "NVDA" in line][0]
    assert "2026-09-02 (confirmed)" in row
    assert "shares, options" in row
    assert "earnings_in_horizon" in row


def test_hard_rejections_sort_above_demotions(settings) -> None:
    lines = render_rejected_table(build_report(settings)).splitlines()
    tickers = [line.split("|")[1].strip() for line in lines[2:]]
    assert tickers == ["NKE", "KO"]


def test_empty_table_renders_as_none_rather_than_an_empty_grid(settings) -> None:
    report = run_gate([make_candidate()], run_date=RUN_DATE, settings=settings)
    assert render_rejected_table(report).strip() == "_none_"


def test_missing_catalyst_renders_as_na(settings) -> None:
    report = run_gate(
        [make_candidate(ticker="KO", catalysts=[])], run_date=RUN_DATE, settings=settings
    )
    report.results[0].decision = GateDecision.ACCEPTED
    assert "n/a" in render_accepted_table(report)


def test_extra_catalysts_in_horizon_are_counted(settings) -> None:
    candidate = make_candidate(
        horizon_days=20,
        catalysts=[make_catalyst(days_out=2), make_catalyst(days_out=9, name="Second")],
    )
    report = run_gate([candidate], run_date=RUN_DATE, settings=settings)
    assert "+1" in render_accepted_table(report)


def test_pipe_characters_in_free_text_do_not_break_the_table(settings) -> None:
    candidate = make_candidate(ticker="KO", catalysts=[], venue="XETRA | Tradegate")
    report = run_gate([candidate], run_date=RUN_DATE, settings=settings)
    report.results[0].decision = GateDecision.ACCEPTED
    row = [line for line in render_accepted_table(report).splitlines() if "KO" in line][0]
    assert "XETRA \\| Tradegate" in row
    # The escaped pipe must not add a column: 10 headers means 11 cell delimiters.
    assert row.replace("\\|", "").count("|") == 11
    assert len(render_accepted_table(report).splitlines()[0].split("|")) == len(
        row.replace("\\|", "").split("|")
    )


def test_full_markdown_carries_header_counts_repeats_and_diagnostics(settings) -> None:
    history = {
        "KO": RejectionRecord(
            ticker="KO",
            decision=GateDecision.WATCHLIST,
            first_flagged_on=date(2026, 7, 1),
            last_flagged_on=date(2026, 8, 22),
            occurrences=3,
        )
    }
    report = build_report(
        settings,
        history=history,
        load_warnings=["Fixed universe: 3 candidates loaded, expected at least 8."],
        load_errors=["watchlist.csv:4: row has no ticker."],
    )
    markdown = render_gate_markdown(report)

    assert f"# Candidate Gate - {RUN_DATE.isoformat()}" in markdown
    assert "Scored: 1" in markdown and "Watchlist: 1" in markdown and "Rejected: 1" in markdown
    assert "## Scored candidates" in markdown
    assert "## Rejected at gate" in markdown
    assert "**Carried from previous runs:** KO (4x since 2026-07-01)" in markdown
    assert "## Load warnings" in markdown
    assert "expected at least 8" in markdown
    assert "## Load errors" in markdown
    assert "row has no ticker" in markdown


def test_dashboard_html_orders_primary_sections_and_preserves_prior_sections() -> None:
    html = render_dashboard_html(dashboard_payload())
    parser = parse_dashboard_html(html)

    assert parser.section_order[:3] == [
        "trading-ideas",
        "per-ticker-sections",
        "market-overview",
    ]
    assert parser.section_order.index("trading-ideas") == 0
    assert {
        "prior-scorecard",
        "market-overview",
        "master-alpha-selection-matrix",
        "rejected-at-gate",
        "tactical-execution-dashboard",
        "conditionality-table",
        "per-ticker-sections",
        "evidence-ledger",
    }.issubset(parser.section_order)


def test_dashboard_html_wraps_detail_sections_in_details() -> None:
    parser = parse_dashboard_html(render_dashboard_html(dashboard_payload()))

    assert {
        "master-alpha-selection-matrix",
        "prior-scorecard",
        "conditionality-table",
        "rejected-at-gate",
        "evidence-ledger",
    }.issubset(parser.sections_in_details)
    assert "trading-ideas" not in parser.sections_in_details
    assert "per-ticker-sections" not in parser.sections_in_details
    assert "market-overview" not in parser.sections_in_details


def test_dashboard_html_trading_ideas_empty_state_is_explicit() -> None:
    html = render_dashboard_html(dashboard_payload(trading_ideas=[]))

    assert "no scored ideas this run" in html
    assert 'class="ideas-table"' not in html


def test_dashboard_html_renders_index_market_context_fields() -> None:
    payload = dashboard_payload()
    payload.market_overview = [
        MarketOverviewPoint(
            label="SPY market context",
            value=None,
            fields={
                "spot": 500.0,
                "implied_volatility_pct": 22.0,
                "expected_move_pct": 1.5,
                "expected_move_points": 7.5,
                "composite_score": 0.31,
                "tier": "B",
            },
            source="CBOE fixture",
            as_of="2026-08-29T12:00:00+00:00",
            note=(
                "Index/fund candidate shown as market context because baskets have no "
                "issuer, analyst-coverage, or insider-filing legs."
            ),
        )
    ]
    html = render_dashboard_html(payload)

    assert "SPY market context" in html
    assert "implied volatility pct" in html
    assert "expected move points" in html
    assert "baskets have no issuer" in html
    assert '<dl class="metric-fields">' in html


def test_dashboard_html_ideas_table_scrolls_and_separates_the_two_scales() -> None:
    """Conviction and certainty are separate display values, never a combined grade."""

    html = render_dashboard_html(dashboard_payload())
    parser = parse_dashboard_html(html)
    ideas_rows = parser.rows_by_section["trading-ideas"]

    assert 'class="table-scroll" role="region" aria-label="Trading ideas"' in html
    assert ".table-scroll" in html
    assert "overflow-x: auto;" in html
    assert "overflow-x: hidden;" in html
    assert "Tier" not in ideas_rows[0]
    assert ideas_rows[0][1:7] == [
        "Status",
        "Setup",
        "Thesis",
        "Data reads",
        "Conviction",
        "Certainty",
    ]
    assert ideas_rows[1][1:7] == [
        "TRADEABLE",
        "EVENT_DIRECTIONAL_LONG",
        "long",
        "moderate_bullish (+0.62)",
        "77.4",
        "B+",
    ]
    assert "1 of 3 legs" in html
    assert "fixture leg counts describe the fixture, not live sourcing" in html
    assert "executive_tone: no transcript source available" in html


def test_dashboard_html_publishes_the_declared_thesis_direction() -> None:
    """`alignment()` branches on direction, and `beyond +/-1 sigma` does not imply it.

    Without this column a skew structure carrying a real LONG direction and a NEUTRAL
    straddle publish identical HTML rows and grade differently, so the rendered page
    alone cannot be reconciled.
    """
    rows = [
        TradingIdeaRow(
            ticker="NVDA",
            status="TRADEABLE",
            direction="long",
            thesis_band="beyond +1 sigma",
            grade_letter="B+",
            grade_score=77.4,
        ),
        TradingIdeaRow(
            ticker="MSFT",
            status="TRADEABLE",
            direction="neutral",
            thesis_band="beyond +1 sigma",
            grade_letter="C",
            grade_score=54.0,
        ),
        TradingIdeaRow(ticker="TSLA", status="UNSCORED"),
    ]
    parser = parse_dashboard_html(
        render_dashboard_html(dashboard_payload(trading_ideas=rows))
    )
    table = parser.rows_by_section["trading-ideas"]
    column = table[0].index("Thesis")

    assert [row[column] for row in table[1:]] == ["long", "neutral", "unavailable"]
    # Same band, same grade columns to a reader's eye - only direction separates them.
    thesis = table[0].index("P(thesis band)")
    assert table[1][thesis] == table[2][thesis]


def test_dashboard_html_presents_probability_as_context_not_grade_formula() -> None:
    html = render_dashboard_html(dashboard_payload())
    parser = parse_dashboard_html(html)

    assert "P(thesis band)" in parser.rows_by_section["trading-ideas"][0]
    assert "probability with alignment" not in html.lower()
    assert "grade combines" not in html.lower()


def mixed_formula_ideas() -> list[TradingIdeaRow]:
    """Three rows whose composites rest on different component sets.

    Mirrors the shape of a real run: unsourceable components are dropped and the
    remaining weights renormalised, so these three grades are not the same quantity.
    """
    return [
        TradingIdeaRow(
            ticker="CRWV",
            grade_letter="B",
            grade_score=67.89,
            tier="A",
            status="TRADEABLE",
            scored_components=["S_M", "S_O"],
            missing_components=["S_S", "S_I", "S_F"],
            weight_profile="US",
        ),
        TradingIdeaRow(
            ticker="ORCL",
            grade_letter="F",
            grade_score=34.75,
            tier="A",
            status="TRADEABLE",
            scored_components=["S_M", "S_O", "S_S"],
            missing_components=["S_I", "S_F"],
            weight_profile="US",
        ),
        TradingIdeaRow(
            ticker="MSFT",
            grade_letter="A",
            grade_score=83.82,
            tier="A",
            status="TRADEABLE",
            scored_components=["S_M", "S_O", "S_S", "S_I"],
            missing_components=["S_F"],
            weight_profile="US",
        ),
    ]


def ideas_row_html(html: str, ticker: str) -> str:
    body = html.split('class="ideas-table"', 1)[1]
    rows = body.split("<tr")
    return next(fragment for fragment in rows if f">{ticker}</td>" in fragment)


def test_dashboard_html_component_coverage_is_visible_beside_conviction() -> None:
    """A reader must see that CRWV's conviction has 2 components and MSFT's has 4."""
    parser = parse_dashboard_html(
        render_dashboard_html(dashboard_payload(trading_ideas=mixed_formula_ideas()))
    )
    header = parser.rows_by_section["trading-ideas"][0]
    conviction_column = header.index("Conviction")
    component_column = header.index("Components")
    convictions = {
        row[0]: row[conviction_column]
        for row in parser.rows_by_section["trading-ideas"][1:]
    }
    components = {
        row[0]: row[component_column]
        for row in parser.rows_by_section["trading-ideas"][1:]
    }

    assert convictions == {"CRWV": "67.89", "ORCL": "34.75", "MSFT": "83.82"}
    assert "2/5" in components["CRWV"]
    assert "3/5" in components["ORCL"]
    assert "4/5" in components["MSFT"]


def test_dashboard_html_flags_rows_graded_on_fewer_than_three_components() -> None:
    html = render_dashboard_html(dashboard_payload(trading_ideas=mixed_formula_ideas()))

    assert 'class="thin-evidence"' in ideas_row_html(html, "CRWV")
    assert "comp-count thin" in ideas_row_html(html, "CRWV")
    for ticker in ("ORCL", "MSFT"):
        assert "thin-evidence" not in ideas_row_html(html, ticker)
        assert "comp-count thin" not in ideas_row_html(html, ticker)
    assert ".comp-count.thin" in html and "tr.thin-evidence" in html


def test_dashboard_html_explains_the_component_count_in_a_legend() -> None:
    html = render_dashboard_html(dashboard_payload(trading_ideas=mixed_formula_ideas()))

    assert "remaining weights renormalised" in html
    assert "fewer than 3 components are highlighted" in html


def test_dashboard_html_omits_the_component_count_for_an_unscored_row() -> None:
    """A row that never produced a score has no composite to describe."""
    parser = parse_dashboard_html(
        render_dashboard_html(
            dashboard_payload(
                trading_ideas=[TradingIdeaRow(ticker="TSLA", status="UNSCORED")]
            )
        )
    )
    header = parser.rows_by_section["trading-ideas"][0]
    row = parser.rows_by_section["trading-ideas"][1]

    assert row[header.index("Conviction")] == "unavailable"
    assert row[header.index("Certainty")] == "unavailable"
    assert row[header.index("Components")] == "unavailable"


def test_dashboard_html_explains_and_renders_conviction_and_certainty_separately() -> None:
    row = TradingIdeaRow(
        ticker="INTC",
        status="WATCHLIST",
        direction="long",
        posture="moderate_bullish",
        composite_score=0.465,
        grade_score=100.0,
        grade_letter="C",
    )
    html = render_dashboard_html(dashboard_payload(trading_ideas=[row]))
    table = parse_dashboard_html(html).rows_by_section["trading-ideas"]
    header = table[0]

    assert table[1][header.index("Conviction")] == "100.0"
    assert table[1][header.index("Certainty")] == "C"
    assert "C (100.0)" not in html
    assert "Conviction" in html and "Certainty" in html
    assert "data-quality letter" in html


def test_dashboard_html_marks_only_theses_that_disagree_with_the_data_reading() -> None:
    rows = [
        TradingIdeaRow(
            ticker="GOOGL",
            status="WATCHLIST",
            direction="long",
            posture="neutral",
            composite_score=-0.094,
            grade_score=0.0,
            grade_letter="C",
        ),
        TradingIdeaRow(
            ticker="INTC",
            status="WATCHLIST",
            direction="long",
            posture="moderate_bullish",
            composite_score=0.465,
            grade_score=100.0,
            grade_letter="C",
        ),
    ]
    table = parse_dashboard_html(
        render_dashboard_html(dashboard_payload(trading_ideas=rows))
    ).rows_by_section["trading-ideas"]
    header = table[0]
    readings = {row[0]: row[header.index("Data reads")] for row in table[1:]}

    assert "thesis disagrees with data" in readings["GOOGL"]
    assert "thesis disagrees with data" not in readings["INTC"]


def test_dashboard_html_renders_partial_run_health_banner() -> None:
    payload = dashboard_payload()
    payload.run_health = RunHealth(
        components_scored=14,
        components_defined=16,
        names_scored=17,
        names_gated=18,
        providers_answered=["fmp"],
        providers_expected=["fmp", "finnhub"],
    )

    html = render_dashboard_html(payload)

    assert 'id="run-health"' in html
    assert "Partial run: the report is incomplete." in html
    assert "Scored 14 of 16 components and 17 of 18 gated names." in html
    assert "2 components; 1 gated names; providers finnhub did not answer." in html
    assert "DATA PROVIDER OUTAGE" not in html


def test_dashboard_html_renders_total_provider_outage_banner() -> None:
    payload = dashboard_payload()
    payload.run_health = RunHealth(
        components_scored=0,
        components_defined=16,
        names_scored=0,
        names_gated=18,
        providers_answered=[],
        providers_expected=["fmp", "finnhub", "alpha_vantage"],
        total_provider_outage=True,
    )

    html = render_dashboard_html(payload)

    assert "DATA PROVIDER OUTAGE: no expected provider answered." in html
    assert "built without live provider data" in html
    assert "must not be treated as a normal daily briefing" in html


def test_dashboard_html_omits_run_health_banner_for_a_clean_or_legacy_run() -> None:
    legacy_html = render_dashboard_html(dashboard_payload())
    clean_payload = dashboard_payload()
    clean_payload.run_health = RunHealth(
        components_scored=16,
        components_defined=16,
        names_scored=18,
        names_gated=18,
        providers_answered=["fmp", "finnhub"],
        providers_expected=["fmp", "finnhub"],
    )

    assert 'id="run-health"' not in legacy_html
    assert 'id="run-health"' not in render_dashboard_html(clean_payload)
