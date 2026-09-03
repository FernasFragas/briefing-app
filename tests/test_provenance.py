"""Regression tests for provenance: a chain must never be promoted past its source.

Rule 1/3 of the plan puts primary feeds above pasted or partial captures, and Stage 3A
caps a manual Eurex capture at Tier B. These tests pin the paths where a degraded chain
could quietly acquire a clean `verified` badge on its way through the pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from briefing_app.components.base import ComponentResult, SubScore
from briefing_app.config import AppConfig, load_config
from briefing_app.models.candidate import Geography
from briefing_app.models.market_data import (
    OptionChain,
    OptionContract,
    OptionFilterConfig,
    OptionType,
    ValidationStatus,
)
from briefing_app.options_math import OptionsStructureResult
from briefing_app.pipeline import (
    DECLARED_UNSCORABLE_COMPONENTS,
    LIVE_UNSCORABLE_LEGS,
    FixtureDataSource,
    FixtureFabricationError,
    TickerData,
    _refuse_fabricated_legs,
    run_daily,
)
from briefing_app.providers.manual import load_eurex_manual_options_capture

CAPTURE_HEADER = "venue,as_of,expiry,strike,type,settlement,open_interest,volume\n"


def contract(strike: float, *, oi: int = 500, volume: int = 40) -> OptionContract:
    return OptionContract(
        underlying="RHM.DE",
        contract_symbol=f"RHM-{strike:g}-C",
        expiry=date(2026, 9, 18),
        strike=strike,
        option_type=OptionType.CALL,
        venue="EUREX",
        source="manual capture",
        bid=41.9,
        ask=42.3,
        mid=42.1,
        open_interest=oi,
        volume=volume,
    )


def chain_with(status: ValidationStatus, *, contracts: list[OptionContract]) -> OptionChain:
    return OptionChain(
        ticker="RHM.DE",
        venue="EUREX",
        as_of=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        spot=1780,
        source="manual capture",
        validation_status=status,
        contracts=contracts,
    )


def test_filtering_never_promotes_a_partial_chain_to_verified() -> None:
    chain = chain_with(ValidationStatus.PARTIAL, contracts=[contract(1800)])
    filtered = chain.filtered(OptionFilterConfig(min_open_interest=1, min_volume=1))

    assert filtered.contracts, "the liquid row should survive the filter"
    assert filtered.validation_status is ValidationStatus.PARTIAL


def test_filtering_preserves_a_verified_chain() -> None:
    chain = chain_with(ValidationStatus.VERIFIED, contracts=[contract(1800)])
    filtered = chain.filtered(OptionFilterConfig(min_open_interest=1, min_volume=1))

    assert filtered.validation_status is ValidationStatus.VERIFIED


def test_filtering_everything_out_marks_the_chain_unavailable() -> None:
    chain = chain_with(ValidationStatus.VERIFIED, contracts=[contract(1800, oi=1)])
    filtered = chain.filtered(OptionFilterConfig(min_open_interest=500, min_volume=1))

    assert filtered.contracts == []
    assert filtered.validation_status is ValidationStatus.UNAVAILABLE


def test_manual_eurex_capture_is_partial_not_verified(tmp_path: Path) -> None:
    path = tmp_path / "eurex.csv"
    path.write_text(
        CAPTURE_HEADER + "EUREX,2026-08-29T12:00:00,2026-09-18,1800,C,42.10,1240,85\n",
        encoding="utf-8",
    )

    chain = load_eurex_manual_options_capture(path, ticker="RHM.DE", spot=1780)

    assert chain.validation_status is ValidationStatus.PARTIAL
    codes = {issue.code for issue in chain.diagnostics}
    assert "manual_options_capture" in codes


def test_manual_capture_stays_partial_after_the_liquidity_filter(tmp_path: Path) -> None:
    path = tmp_path / "eurex.csv"
    path.write_text(
        CAPTURE_HEADER + "EUREX,2026-08-29T12:00:00,2026-09-18,1800,C,42.10,1240,85\n",
        encoding="utf-8",
    )

    chain = load_eurex_manual_options_capture(
        path,
        ticker="RHM.DE",
        spot=1780,
        filters=OptionFilterConfig(min_open_interest=1, min_volume=1),
    )

    assert chain.contracts
    assert chain.validation_status is ValidationStatus.PARTIAL


def test_capture_without_a_timestamp_discloses_the_substitution(tmp_path: Path) -> None:
    path = tmp_path / "eurex.csv"
    path.write_text(
        "venue,expiry,strike,type,settlement,open_interest,volume\n"
        "EUREX,2026-09-18,1800,C,42.10,1240,85\n",
        encoding="utf-8",
    )

    chain = load_eurex_manual_options_capture(path, ticker="RHM.DE", spot=1780)

    codes = {issue.code for issue in chain.diagnostics}
    assert "missing_capture_timestamp" in codes


def test_short_rows_in_a_hand_made_capture_do_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "eurex.csv"
    path.write_text(
        CAPTURE_HEADER
        + "EUREX,2026-08-29T12:00:00,2026-09-18,1800,C,42.10,1240,85\n"
        + "EUREX,2026-08-29T12:00:00,2026-09-18,1850,C\n",
        encoding="utf-8",
    )

    chain = load_eurex_manual_options_capture(path, ticker="RHM.DE", spot=1780)

    assert [c.strike for c in chain.contracts] == [1800, 1850]
    assert chain.contracts[1].open_interest is None


# --- Fixture provenance ------------------------------------------------------------------
#
# A fixture run is only worth reading as a rehearsal of the live run. These pin the two
# ways it could stop being one: by badging invented rows `verified`, and by scoring a leg
# no live source feeds.

FIXTURE_RUN_DATE = date(2026, 8, 28)


@pytest.fixture
def fixture_run(tmp_path: Path):
    """One real end-to-end run of the fixture data source."""

    config = AppConfig.model_validate(
        {
            "universe": {
                "mode": "fixed",
                "fixed_min": 0,
                "fixed_max": 2,
                "screen_min": 0,
                "screen_max": 0,
                "fixed": [
                    {
                        "ticker": "NVDA",
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
                                "date": FIXTURE_RUN_DATE + timedelta(days=3),
                                "status": "confirmed",
                                "kind": "earnings",
                                "source": "Company IR",
                            }
                        ],
                        "thesis_sources": [{"label": "Company IR", "kind": "company_ir"}],
                    }
                ],
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
    return run_daily(
        config,
        run_date=FIXTURE_RUN_DATE,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
    )


def structure(**overrides: object) -> OptionsStructureResult:
    defaults = dict(
        ticker="NVDA",
        as_of=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        spot=120.0,
        available=True,
        score=0.4,
    )
    return OptionsStructureResult(**{**defaults, **overrides})  # type: ignore[arg-type]


def tone_component(name: str) -> ComponentResult:
    return ComponentResult(
        component="S_S",
        ticker="NVDA",
        as_of=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        geography=Geography.US,
        available=True,
        score=0.5,
        validation_status="synthetic",
        source_quality="fixture",
        sub_scores=(SubScore(name=name, weight=0.35, score=0.6),),
    )


def test_fixture_preflight_rows_are_synthetic_not_verified() -> None:
    rows = FixtureDataSource().preflight_rows(
        run_id=None,
        tickers=["NVDA"],
        run_date=date(2026, 8, 28),
        checked_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )

    assert rows
    assert {row["validation_status"] for row in rows} == {"synthetic"}
    assert {row["details"]["data_mode"] for row in rows} == {"fixture"}


def test_fixture_run_labels_every_row_it_sources_synthetic(fixture_run) -> None:
    ledger = json.loads(fixture_run.json_path.read_text(encoding="utf-8"))["evidence_ledger"]
    sourced = [row for row in ledger if "fixture" in row["source"]]

    assert sourced, "the fixture run should have written rows of its own"
    assert {row["validation_status"] for row in sourced} == {"synthetic"}


def test_a_synthetic_chain_cannot_reach_the_tradeable_path(fixture_run) -> None:
    assert fixture_run.scoring_report.results[0].tier.value == "C"
    assert fixture_run.setup_report.tradeable_setups == []


def test_fixture_mode_leaves_legs_the_live_path_cannot_score_unscored(fixture_run) -> None:
    ledger = json.loads(fixture_run.json_path.read_text(encoding="utf-8"))["evidence_ledger"]
    scored = {row["field_name"] for row in ledger}

    # `iv_rank` is the row an invented iv_history would write, and a fabricated transcript
    # tone reading writes its sub-score as `s_s_executive_tone`.
    assert "iv_rank" not in scored
    assert "s_s_executive_tone" not in scored
    assert not any(name.endswith("short_borrow") for name in scored)

    # The skew leg stays, because the live path computes rr_25d from the chain it pulls.
    assert "rr_25d" in scored


def test_a_fabricated_options_leg_is_refused() -> None:
    """`risk_reversal_history` still has no live source, so a fixture must not score it.

    `iv_extreme` used to sit here. It moved off the unscorable list when the self-built
    IV baseline landed: the live path now stores `iv_atm` each run and ranks against it,
    so a fixture scoring it is no longer claiming something live cannot do.
    """

    data = TickerData(
        option_structure=structure(sub_scores={"risk_reversal_history": 0.8, "skew": 0.2}),
        option_quotes=(),
        components=(),
    )

    with pytest.raises(FixtureFabricationError) as error:
        _refuse_fabricated_legs("NVDA", data)

    assert "risk_reversal_history" in str(error.value)
    assert "skew" not in str(error.value), "skew is computed from the chain the live path pulls"


def test_iv_extreme_is_no_longer_treated_as_unscorable_on_the_live_path() -> None:
    """The self-built baseline made this leg real; the guard must not still refuse it."""

    from briefing_app.pipeline import LIVE_UNSCORABLE_LEGS

    assert "iv_extreme" not in LIVE_UNSCORABLE_LEGS
    assert "short_borrow" not in LIVE_UNSCORABLE_LEGS
    assert "retail_momentum" not in LIVE_UNSCORABLE_LEGS
    _refuse_fabricated_legs(
        "NVDA",
        TickerData(
            option_structure=structure(sub_scores={"iv_extreme": 0.8, "short_borrow": 0.1}),
            option_quotes=(),
            components=(),
        ),
    )


def test_a_fabricated_component_leg_is_refused() -> None:
    data = TickerData(
        option_structure=structure(),
        option_quotes=(),
        components=(tone_component("executive_tone"),),
    )

    with pytest.raises(FixtureFabricationError) as error:
        _refuse_fabricated_legs("NVDA", data)

    assert "executive_tone" in str(error.value)


def test_a_fabricated_declared_unscorable_component_is_refused() -> None:
    """Q4. `S_F` is declined, not missing, so a fixture score for it is fiction."""

    data = TickerData(
        option_structure=structure(),
        option_quotes=(),
        components=(
            ComponentResult(
                component="S_F",
                ticker="NVDA",
                as_of=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
                geography=Geography.US,
                available=True,
                score=0.4,
                validation_status="synthetic",
                source_quality="fixture",
            ),
        ),
    )

    with pytest.raises(FixtureFabricationError) as error:
        _refuse_fabricated_legs("NVDA", data)

    assert "S_F" in str(error.value)
    assert "permanently n/a" in str(error.value)


def test_both_run_modes_leave_s_f_na_with_the_same_declared_reason(fixture_run) -> None:
    """Q4. The reason is a decision, not a fetch that came back empty."""

    payload = json.loads(fixture_run.json_path.read_text(encoding="utf-8"))
    reason = DECLARED_UNSCORABLE_COMPONENTS["S_F"]

    for section in payload["per_ticker_sections"]:
        institutional = next(
            component
            for component in section["components"]
            if component["component"] == "S_F"
        )
        assert institutional["score"] is None
        assert institutional["na_reason"] == reason

    for row in payload["master_alpha_selection_matrix"]:
        assert row["component_scores"]["S_F"] is None
        assert "S_F" in row["missing_components"]


def test_s_f_weight_is_redistributed_rather_than_scored_as_neutral(fixture_run) -> None:
    """Q4. Its 0.10 lifts the components that did score; it never drags toward zero."""

    result = fixture_run.scoring_report.results[0]
    original = result.original_weights
    used = result.weights_used

    assert "S_F" not in used
    assert sum(used.values()) == pytest.approx(1.0)
    survivors = sum(original[name] for name in used)
    for name, weight in used.items():
        assert weight == pytest.approx(original[name] / survivors)
        assert weight > original[name], "a dropped component's weight goes somewhere"


def test_declaring_s_f_na_pins_expression_classes_p_and_s_to_tier_c() -> None:
    """Q4's cost, stated rather than discovered later.

    `S_F` is in the required set for `P` and `S`, so neither can leave Tier C while the
    decision stands. `enabled_expression_classes` is `[V, E]`, which is why the shipped
    universe is unaffected - if that changes, this is what changes with it.
    """

    from briefing_app.models.scoring import REQUIRED_COMPONENTS
    from briefing_app.models.candidate import ExpressionClass

    assert "S_F" in REQUIRED_COMPONENTS[ExpressionClass.P]
    assert "S_F" in REQUIRED_COMPONENTS[ExpressionClass.S]
    assert "S_F" not in REQUIRED_COMPONENTS[ExpressionClass.V]
    assert "S_F" not in REQUIRED_COMPONENTS[ExpressionClass.E]

    config = load_config(Path("config/config.example.yaml"))
    assert [c.value for c in config.gate.enabled_expression_classes] == ["V", "E"]
    assert config.providers.institutional == [], "no request is spent on a declined leg"


def test_an_invented_risk_reversal_history_is_refused() -> None:
    data = TickerData(
        option_structure=structure(),
        option_quotes=(),
        components=(),
        risk_reversal_history=(-0.02, -0.01, 0.0, 0.01, 0.02),
    )

    with pytest.raises(FixtureFabricationError) as error:
        _refuse_fabricated_legs("NVDA", data)

    assert "risk_reversal_history" in str(error.value)
