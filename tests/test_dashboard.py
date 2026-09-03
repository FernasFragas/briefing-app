"""T9 dashboard schema, rendering, prompt guardrails, and LLM wrapper."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from briefing_app.config import GateSettings
from briefing_app.components import (
    ComponentResult,
    SENTIMENT,
    STATUS_VERIFIED,
    QUALITY_AGGREGATOR,
    QUALITY_PRIMARY,
    SubScore,
)
from briefing_app.dashboard import (
    BriefingLLM,
    LLMProvider,
    LLMProviderError,
    MarketOverviewPoint,
    NumericGuardError,
    assert_authorized_numbers,
    build_dashboard_payload,
    market_overview_messages,
    render_dashboard_html,
    render_dashboard_json,
    ticker_prose_context,
    ticker_prose_messages,
)
from briefing_app.dashboard.models import DashboardPayload, TradingIdeaRow
from briefing_app.models.candidate import Direction, ExpressionClass, Geography, Instrument
from briefing_app.models.gate import GateDecision
from briefing_app.models.scoring import ComponentScore, ConfidenceTier, Posture, ScoringResult
from briefing_app.strategy import (
    CandidateSetupResult,
    Invalidation,
    InvalidationBasis,
    RejectionCode,
    Setup,
    SetupDecision,
    SetupEvidence,
    SetupRejection,
    SetupReport,
    SetupType,
)
from briefing_app.strategy.scenarios import ScenarioRow, ScenarioTable
from briefing_app.universe.gate import run_gate
from tests.conftest import RUN_DATE, make_candidate

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def test_dashboard_payload_has_all_required_sections() -> None:
    payload = fixture_payload()
    data = json.loads(render_dashboard_json(payload))

    assert data["schema_version"] == "dashboard.v2"
    assert {row["ticker"] for row in data["trading_ideas"]} == {"NVDA"}
    assert data["prior_scorecard"][0]["ticker"] == "NVDA"
    assert data["market_overview"][0]["source"] == "CBOE fixture"
    assert data["master_alpha_selection_matrix"][0]["ticker"] == "NVDA"
    assert data["rejected_at_gate"][0]["ticker"] == "TSLA"
    assert data["evidence_ledger"], "component/setup evidence is carried into the ledger"
    assert data["tactical_execution_dashboard"]["top_long"]["ticker"] == "NVDA"
    assert data["conditionality_table"][0]["invalidation"]["primary_level"] == 95.0
    assert data["per_ticker_sections"][0]["components"][0]["component"] == "S_S"


def test_dashboard_payload_v2_preserves_old_shape_construction() -> None:
    payload = DashboardPayload(
        run_id="legacy-shape",
        run_date=RUN_DATE,
        generated_at=NOW,
    )

    assert payload.schema_version == "dashboard.v2"
    assert payload.trading_ideas == []


def test_audit_json_emits_trading_ideas_without_expanding_counts() -> None:
    payload = DashboardPayload(
        run_id="ideas-shape",
        run_date=RUN_DATE,
        generated_at=NOW,
        trading_ideas=[
            TradingIdeaRow(
                ticker="NVDA",
                setup_type="EVENT_DIRECTIONAL_LONG",
                grade_letter="B+",
                grade_score=77.4,
                thesis_probability=0.68,
                thesis_band="beyond +1 sigma",
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
        ],
    )

    data = json.loads(payload.audit_json())

    assert data["trading_ideas"] == [
        {
            "ticker": "NVDA",
            "setup_type": "EVENT_DIRECTIONAL_LONG",
            "grade_letter": "B+",
            "grade_score": 77.4,
            "thesis_probability": 0.68,
            "thesis_band": "beyond +1 sigma",
            "s_cte": 0.62,
            "tier": "A",
            "status": "TRADEABLE",
            "catalyst": {
                "name": "Quarterly results",
                "date": "2026-09-01",
                "status": "confirmed",
            },
            "blocked_reason": None,
            "grade_penalties": [],
            "headline": "NVDA event-directional long",
        }
    ]
    assert set(payload.counts) == {
        "matrix",
        "rejected_at_gate",
        "evidence_rows",
        "conditionality_rows",
        "tickers",
    }


def test_fixture_dashboard_build_emits_sorted_trading_ideas() -> None:
    payload = fixture_payload()
    rows = payload.trading_ideas

    assert [row.ticker for row in rows] == ["NVDA"]
    assert [row.ticker for row in payload.rejected_at_gate] == ["TSLA"]
    assert rows[0].grade_score is not None

    nvda = _idea_row(rows, "NVDA")
    assert nvda.status == "TRADEABLE"
    assert nvda.grade_letter is not None
    assert nvda.grade_score is not None
    assert nvda.grade_score <= _tier_ceiling(nvda.tier)
    assert nvda.blocked_reason is None

    scored = [row.grade_score for row in rows if row.grade_score is not None]
    assert scored == sorted(scored, reverse=True)
    assert all(
        row.grade_score is None
        for row in rows[len(scored):]
    )
    assert all(
        row.status == "TRADEABLE" or row.blocked_reason
        for row in rows
    )
    for row in rows:
        if row.grade_score is not None:
            assert row.grade_score <= _tier_ceiling(row.tier)


def test_gate_accepted_without_scoring_result_is_unscored_and_ungraded() -> None:
    gate_report = run_gate(
        [
            make_candidate(
                ticker="AMD",
                catalysts=[
                    {
                        "name": "Product launch",
                        "date": RUN_DATE + timedelta(days=2),
                        "status": "confirmed",
                        "kind": "launch",
                        "source": "Company IR",
                    }
                ],
            )
        ],
        run_date=RUN_DATE,
        settings=GateSettings(),
        run_id="unscored-gate",
    )
    assert gate_report.results[0].decision is GateDecision.ACCEPTED

    payload = build_dashboard_payload(
        run_id="unscored-dashboard",
        run_date=RUN_DATE,
        generated_at=NOW,
        gate_report=gate_report,
    )

    row = payload.trading_ideas[0]
    assert row.ticker == "AMD"
    assert row.status == "UNSCORED"
    assert row.grade_letter is None
    assert row.grade_score is None
    assert row.blocked_reason == "missing scoring result"


def test_watchlist_blocked_reason_prefers_score_cause_over_tier_c_code() -> None:
    score = ScoringResult(
        ticker="MSFT",
        expression_class=ExpressionClass.E,
        geography=Geography.US,
        s_cte=0.90,
        tier=ConfidenceTier.C,
        components=[
            ComponentScore(
                component="S_M",
                score=0.80,
                original_weight=0.30,
                weight_used=1.0,
                validation_status="verified",
                source_quality="primary",
                required=True,
                as_of=RUN_DATE,
            ),
            ComponentScore(
                component="S_O",
                score=None,
                original_weight=0.25,
                weight_used=0.0,
                validation_status="unavailable",
                source_quality="none",
                required=True,
                missing_reason="no verified option chain",
                as_of=RUN_DATE,
            ),
        ],
        tier_reasons=[
            "S_O required component unavailable/unverifiable: no verified option chain"
        ],
    )
    setup = Setup(
        ticker="MSFT",
        setup_type=SetupType.WATCHLIST_NO_TRADE,
        decision=SetupDecision.WATCHLIST,
        expression_class=ExpressionClass.E,
        direction=Direction.LONG,
        horizon_days=10,
        horizon_label="10d",
        tier=ConfidenceTier.C,
        posture=Posture.STRONG_BULLISH,
        s_cte=0.90,
        scenario_table=_scenario_table(ticker="MSFT", above=0.95, within=0.05),
        rationale="tier floor",
    )
    setup_report = SetupReport(
        run_id="watchlist-setups",
        run_date=RUN_DATE,
        generated_at=NOW,
        results=[
            CandidateSetupResult(
                ticker="MSFT",
                expression_class=ExpressionClass.E,
                tier=ConfidenceTier.C,
                tier_floors=["universal Tier C floor: missing invalidation level"],
                setups=[setup],
                rejections=[
                    SetupRejection(
                        ticker="MSFT",
                        setup_type=SetupType.WATCHLIST_NO_TRADE,
                        code=RejectionCode.TIER_C,
                        detail="tier_c",
                    )
                ],
            )
        ],
    )

    payload = build_dashboard_payload(
        run_id="watchlist-dashboard",
        run_date=RUN_DATE,
        generated_at=NOW,
        scores=[score],
        setup_report=setup_report,
    )

    row = payload.trading_ideas[0]
    assert row.status == "WATCHLIST"
    assert row.grade_score is not None
    assert row.grade_score <= _tier_ceiling(row.tier)
    assert "missing required component: S_O" in (row.blocked_reason or "")
    assert "missing invalidation level" in (row.blocked_reason or "")
    assert "tier_c" not in (row.blocked_reason or "")


def test_ticker_section_component_discloses_leg_counts_and_absent_legs() -> None:
    component = ComponentResult(
        component=SENTIMENT,
        ticker="NVDA",
        as_of=NOW,
        geography=Geography.US,
        available=True,
        score=0.40,
        validation_status=STATUS_VERIFIED,
        source_quality=QUALITY_AGGREGATOR,
        sub_scores=(
            SubScore(
                name="analyst_revision",
                weight=0.50,
                score=0.40,
                source="broker note fixture",
                as_of=RUN_DATE,
                sample_size=3,
            ),
            SubScore(
                name="executive_tone",
                weight=0.25,
                score=None,
                na_reason="no transcript source available",
            ),
            SubScore(
                name="retail_momentum",
                weight=0.25,
                score=None,
                na_reason="no retail momentum source available",
            ),
        ),
        weights_used={
            "analyst_revision": 1.0,
            "executive_tone": 0.0,
            "retail_momentum": 0.0,
        },
        diagnostics=(
            "retail_momentum skipped because no source was configured",
        ),
    )

    payload = build_dashboard_payload(
        run_id="component-dashboard",
        run_date=RUN_DATE,
        generated_at=NOW,
        data_mode="fixture",
        component_results=[component],
    )

    section = payload.per_ticker_sections[0]
    summary = section.components[0]
    rendered_section = json.dumps(section.model_dump(mode="json"), sort_keys=True)

    assert summary["score"] == 0.40
    assert summary["source_quality"] == QUALITY_AGGREGATOR
    assert summary["legs_scored"] == 1
    assert summary["legs_defined"] == 3
    assert summary["legs_summary"] == "1 of 3 legs"
    assert {
        item["name"]: item["reason"]
        for item in summary["absent_legs"]
    } == {
        "executive_tone": "no transcript source available",
        "retail_momentum": "no retail momentum source available",
    }
    assert "1 of 3 legs" in rendered_section
    assert "executive_tone" in rendered_section
    assert "retail_momentum" in rendered_section
    assert "fixture leg counts describe the fixture, not live sourcing" in rendered_section


def test_html_renders_unavailable_and_has_no_external_dependencies() -> None:
    payload = fixture_payload()
    html = render_dashboard_html(payload)

    assert "<!doctype html>" in html
    assert "Prior Scorecard" in html
    assert "Master Alpha Selection Matrix" in html
    assert "Evidence Ledger" in html
    assert "unavailable" in html
    assert "http://" not in html and "https://" not in html
    assert "<script src=" not in html and "<link" not in html


def test_prompt_context_contains_computed_values_and_source_labels_only() -> None:
    payload = fixture_payload()
    context = ticker_prose_context(payload, "NVDA")
    serialized = json.dumps(context, sort_keys=True)
    ticker_messages = ticker_prose_messages(payload, "NVDA")
    market_messages = market_overview_messages(payload)
    idea = context["trading_idea"]

    assert idea is not None
    assert idea["grade_score"] == payload.trading_ideas[0].grade_score
    assert idea["grade_letter"] == payload.trading_ideas[0].grade_letter
    assert idea["thesis_probability"] == payload.trading_ideas[0].thesis_probability
    assert idea["status"] == payload.trading_ideas[0].status
    assert "s_cte" in serialized
    assert "0.62" in serialized
    assert "computed" in serialized
    assert "Event directional into a dated catalyst" not in serialized
    assert "Write the per-ticker prose" in ticker_messages[1]["content"]
    assert "market overview" in market_messages[1]["content"].lower()


def test_prompt_context_authorizes_computed_grade_score() -> None:
    payload = fixture_payload()
    context = ticker_prose_context(payload, "NVDA")
    grade_score = payload.trading_ideas[0].grade_score

    assert grade_score is not None
    assert_authorized_numbers(f"NVDA grade score is {grade_score}.", context)


def test_prompt_context_rejects_absent_grade_score() -> None:
    context = ticker_prose_context(fixture_payload(), "NVDA")

    with pytest.raises(NumericGuardError) as error:
        assert_authorized_numbers("NVDA grade score is 99.9.", context)

    assert error.value.violations[0].token == "99.9"


def test_numeric_guard_rejects_invented_numbers() -> None:
    context = {
        "ticker": "NVDA",
        "score": 0.62,
        "run_date": "2026-08-29",
        "source": "SEC Form 13F",
    }

    assert_authorized_numbers("NVDA score 0.62 on 2026-08-29 from SEC Form 13F.", context)
    with pytest.raises(NumericGuardError) as error:
        assert_authorized_numbers("NVDA score 0.62 with a 123 target.", context)
    assert error.value.violations[0].token == "123"


def test_openai_wrapper_uses_temperature_zero_and_numeric_guard() -> None:
    client = FakeOpenAI("NVDA score 0.62.")
    llm = BriefingLLM(
        provider=LLMProvider.OPENAI,
        model="gpt-test",
        openai_client=client,
    )

    response = llm.complete(
        [{"role": "user", "content": "write"}],
        allowed_context={"ticker": "NVDA", "score": 0.62},
    )

    assert response.text == "NVDA score 0.62."
    assert client.calls[0]["temperature"] == 0

    client.text = "NVDA score 0.62 and target 123."
    with pytest.raises(NumericGuardError):
        llm.complete(
            [{"role": "user", "content": "write"}],
            allowed_context={"ticker": "NVDA", "score": 0.62},
        )


def test_claude_wrapper_uses_temperature_zero() -> None:
    client = FakeClaude("NVDA score 0.62.")
    llm = BriefingLLM(
        provider=LLMProvider.CLAUDE,
        model="claude-test",
        anthropic_client=client,
    )

    response = llm.complete(
        [{"role": "system", "content": "system"}, {"role": "user", "content": "write"}],
        allowed_context={"ticker": "NVDA", "score": 0.62},
    )

    assert response.text == "NVDA score 0.62."
    assert client.calls[0]["temperature"] == 0
    assert client.calls[0]["system"] == "system"


def test_ollama_provider_can_be_selected_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")

    llm = BriefingLLM.from_env(ollama_client=FakeOllama("NVDA score 0.62."))

    assert llm.provider is LLMProvider.OLLAMA
    assert llm.model == "gpt-oss:120b"


def test_llm_from_env_defaults_to_ollama(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")

    llm = BriefingLLM.from_env(ollama_client=FakeOllama("NVDA score 0.62."))

    assert llm.provider is LLMProvider.OLLAMA


def test_ollama_wrapper_sends_cloud_auth_and_deterministic_options() -> None:
    client = FakeOllama("NVDA score 0.62.")
    llm = BriefingLLM(
        provider="ollama",
        model="gpt-oss:120b",
        max_tokens=123,
        ollama_client=client,
        ollama_base_url="https://ollama.com",
        ollama_api_key="ollama-key",
    )

    response = llm.complete(
        [{"role": "system", "content": "system"}, {"role": "user", "content": "write"}],
        allowed_context={"ticker": "NVDA", "score": 0.62},
    )

    call = client.calls[0]
    payload = call["payload"]

    assert response.provider is LLMProvider.OLLAMA
    assert response.text == "NVDA score 0.62."
    assert call["url"] == "https://ollama.com/api/chat"
    assert call["headers"]["Authorization"] == "Bearer ollama-key"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_predict"] == 123
    assert payload["messages"][0]["role"] == "system"


def test_ollama_local_relay_does_not_require_cloud_api_key() -> None:
    client = FakeOllama("NVDA score 0.62.")
    llm = BriefingLLM(
        provider=LLMProvider.OLLAMA,
        model="gpt-oss:120b-cloud",
        ollama_client=client,
        ollama_base_url="http://host.docker.internal:11434",
    )

    llm.complete(
        [{"role": "user", "content": "write"}],
        allowed_context={"ticker": "NVDA", "score": 0.62},
    )

    assert client.calls[0]["url"] == "http://host.docker.internal:11434/api/chat"
    assert "Authorization" not in client.calls[0]["headers"]


def test_ollama_wrapper_uses_numeric_guard() -> None:
    client = FakeOllama("NVDA score 0.62 and target 123.")
    llm = BriefingLLM(
        provider=LLMProvider.OLLAMA,
        model="gpt-oss:120b",
        ollama_client=client,
        ollama_base_url="https://ollama.com",
        ollama_api_key="ollama-key",
    )

    with pytest.raises(NumericGuardError):
        llm.complete(
            [{"role": "user", "content": "write"}],
            allowed_context={"ticker": "NVDA", "score": 0.62},
        )


def test_ollama_cloud_requires_api_key_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    client = FakeOllama("NVDA score 0.62.")
    llm = BriefingLLM(
        provider=LLMProvider.OLLAMA,
        model="gpt-oss:120b",
        ollama_client=client,
        ollama_base_url="https://ollama.com",
    )

    with pytest.raises(LLMProviderError) as exc:
        llm.complete(
            [{"role": "user", "content": "write"}],
            allowed_context={"ticker": "NVDA", "score": 0.62},
        )

    assert "OLLAMA_API_KEY" in str(exc.value)
    assert client.calls == []


def test_ollama_unreachable_or_malformed_response_is_provider_error() -> None:
    broken = BrokenOllama()
    llm = BriefingLLM(
        provider=LLMProvider.OLLAMA,
        model="gpt-oss:120b-cloud",
        ollama_client=broken,
        ollama_base_url="http://host.docker.internal:11434",
    )

    with pytest.raises(LLMProviderError) as exc:
        llm.complete(
            [{"role": "user", "content": "write"}],
            allowed_context={"ticker": "NVDA", "score": 0.62},
        )

    assert "Ollama request failed" in str(exc.value)

    malformed = FakeOllama("NVDA score 0.62.", malformed=True)
    llm = BriefingLLM(
        provider=LLMProvider.OLLAMA,
        model="gpt-oss:120b",
        ollama_client=malformed,
        ollama_base_url="https://ollama.com",
        ollama_api_key="ollama-key",
    )

    with pytest.raises(LLMProviderError) as malformed_exc:
        llm.complete(
            [{"role": "user", "content": "write"}],
            allowed_context={"ticker": "NVDA", "score": 0.62},
        )

    assert "message content" in str(malformed_exc.value)


def _idea_row(rows: list[TradingIdeaRow], ticker: str) -> TradingIdeaRow:
    return next(row for row in rows if row.ticker == ticker)


def _tier_ceiling(tier: str | None) -> float:
    assert tier is not None
    return {"A": 100.0, "B": 81.0, "C": 57.0}[tier]


def _scenario_table(
    *,
    ticker: str = "NVDA",
    below: float = 0.15,
    within: float = 0.15,
    above: float = 0.70,
) -> ScenarioTable:
    return ScenarioTable(
        ticker=ticker,
        spot=100.0,
        horizon_days=10,
        rows=(
            _scenario_row("below 2 sigma", 0.0),
            _scenario_row("1 to 2 sigma down", below),
            _scenario_row("within 1 sigma", within),
            _scenario_row("1 to 2 sigma up", above),
            _scenario_row("above 2 sigma", 0.0),
        ),
        source="fixture",
    )


def _scenario_row(label: str, probability: float) -> ScenarioRow:
    return ScenarioRow(
        label=label,
        lower=None,
        upper=None,
        probability=probability,
        implied_probability=None,
        measured_probability=None,
        source="fixture",
    )


def fixture_payload():
    gate_report = run_gate(
        [
            make_candidate(
                ticker="NVDA",
                thesis="Event directional into a dated catalyst.",
                catalysts=[
                    {
                        "name": "Quarterly results",
                        "date": RUN_DATE + timedelta(days=3),
                        "status": "confirmed",
                        "kind": "earnings",
                        "source": "Company IR",
                    }
                ],
            ),
            make_candidate(ticker="TSLA", catalysts=[]),
        ],
        run_date=RUN_DATE,
        settings=GateSettings(),
        run_id="gate-fixture",
    )
    gate_result = next(result for result in gate_report.results if result.ticker == "NVDA")
    score = ScoringResult(
        ticker="NVDA",
        expression_class=ExpressionClass.E,
        geography=Geography.US,
        s_cte=0.62,
        tier=ConfidenceTier.A,
        components=[
            ComponentScore(
                component="S_M",
                score=0.40,
                original_weight=0.30,
                weight_used=0.30,
                validation_status="verified",
                source_quality="primary",
                required=True,
                as_of=RUN_DATE,
            ),
            ComponentScore(
                component="S_S",
                score=0.55,
                original_weight=0.20,
                weight_used=0.20,
                validation_status="verified",
                source_quality="primary",
                required=False,
                as_of=RUN_DATE,
            ),
            ComponentScore(
                component="S_F",
                score=None,
                original_weight=0.10,
                weight_used=0.0,
                validation_status="unavailable",
                source_quality="none",
                required=False,
                missing_reason="no 13F ownership data available",
                as_of=RUN_DATE,
            ),
        ],
    )
    component = ComponentResult(
        component=SENTIMENT,
        ticker="NVDA",
        as_of=NOW,
        geography=Geography.US,
        available=True,
        score=0.55,
        validation_status=STATUS_VERIFIED,
        source_quality=QUALITY_PRIMARY,
        sub_scores=(
            SubScore(
                name="institutional",
                weight=0.45,
                score=0.55,
                source="analyst coverage and news sentiment",
                as_of=RUN_DATE,
                sample_size=4,
            ),
        ),
        weights_used={"institutional": 1.0},
        source_rows=(
            {
                "title": "Quarterly setup improves",
                "source": "Reuters",
                "published_at": NOW.isoformat(),
            },
        ),
        evidence_rows=(
            {
                "ticker": "NVDA",
                "component": "S_S",
                "field_name": "s_s",
                "field_value": "0.55",
                "source": "Alpha Vantage NEWS_SENTIMENT",
                "venue": "*",
                "as_of": NOW,
                "validation_status": "verified",
            },
        ),
    )
    setup = Setup(
        ticker="NVDA",
        setup_type=SetupType.EVENT_DIRECTIONAL_LONG,
        decision=SetupDecision.CANDIDATE,
        expression_class=ExpressionClass.E,
        direction=Direction.LONG,
        horizon_days=10,
        horizon_label="10d",
        tier=ConfidenceTier.A,
        posture=Posture.STRONG_BULLISH,
        s_cte=0.62,
        instrument=Instrument.SHARES,
        catalyst=gate_result.primary_catalyst,
        scenario_table=_scenario_table(),
        invalidation=Invalidation(
            direction=Direction.LONG,
            basis=InvalidationBasis.MEASURED_SIGMA,
            description="close below the measured 1 sigma edge at 95.00",
            lower_level=95.0,
            conditions=("Quarterly results does not occur on 2026-09-01",),
            sources=("measured sigma fixture",),
        ),
        range_low=95.0,
        range_high=110.0,
        rationale="deterministic setup rule",
        triggers=["S_CTE >= 0.60"],
        warnings=["S_F unavailable"],
        evidence=[
            SetupEvidence(
                field_name="s_cte",
                field_value="0.62",
                source="computed",
                as_of=NOW,
                validation_status="verified",
            )
        ],
        size_fraction=1.0,
    )
    setup_report = SetupReport(
        run_id="setups-fixture",
        run_date=RUN_DATE,
        generated_at=NOW,
        results=[
            CandidateSetupResult(
                ticker="NVDA",
                expression_class=ExpressionClass.E,
                tier=ConfidenceTier.A,
                setups=[setup],
                rejections=[
                    SetupRejection(
                        ticker="NVDA",
                        setup_type=SetupType.SKEW_STRUCTURE,
                        code=RejectionCode.CLASS_RULE_NOT_MET,
                        detail="class E does not evaluate skew structures",
                    )
                ],
            )
        ],
    )
    return build_dashboard_payload(
        run_id="dashboard-fixture",
        run_date=RUN_DATE,
        generated_at=NOW,
        gate_report=gate_report,
        scores=[score],
        component_results=[component],
        setup_report=setup_report,
        prior_scorecards=[
            {
                "ticker": "NVDA",
                "snap_date": date(2026, 8, 28),
                "component_scores": {"S_M": 0.25},
                "cte_score": 0.41,
                "confidence_tier": "B",
                "expression_class": "E",
            }
        ],
        market_overview=[
            MarketOverviewPoint(
                label="SPX implied weekly move",
                value=1.8,
                source="CBOE fixture",
                as_of=NOW.isoformat(),
            )
        ],
    )


class FakeOpenAI:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self.text)),
            ]
        )


class FakeClaude:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)])


class FakeOllama:
    def __init__(self, text: str, *, malformed: bool = False) -> None:
        self.text = text
        self.malformed = malformed
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.malformed:
            return {"message": {}}
        return {"message": {"role": "assistant", "content": self.text}, "done": True}


class BrokenOllama:
    def chat(self, **kwargs):
        raise OSError("connection refused")
