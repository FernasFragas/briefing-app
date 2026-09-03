"""End-to-end orchestration for T10.

The pipeline can run against deterministic fixtures for local acceptance tests or
against live provider clients after the candidate gate. In both modes provider payloads
are cached before normalization, then converted into typed inputs for component scoring,
setup rules, dashboard rendering, and persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date as date_type, datetime, timedelta
from math import exp, sin, sqrt
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Protocol, Sequence
import json
import os
import uuid

from briefing_app.components import (
    ComponentResult,
    MacroReading,
    POLITICAL_FLOW_WINDOW_DAYS,
    SectorExposure,
    build_insider_component,
    build_macro_component,
    build_sentiment_component,
    release_change_reading,
    unavailable_component,
)
from briefing_app.config import AppConfig, load_config
from briefing_app.dashboard import DashboardPayload, MarketOverviewPoint, build_dashboard_payload
from briefing_app.dashboard.render import write_dashboard_artifacts
from briefing_app.http import Fetcher
from briefing_app.models.candidate import Geography
from briefing_app.models.market_data import (
    AnalystSignal,
    CatalystCalendar,
    InsiderTransaction,
    MacroCalendar,
    MacroEvent,
    NewsArticle,
    NewsSentimentBatch,
    OptionFilterConfig,
    PoliticalTrade,
    RetailMomentumSnapshot,
    ShortInterestSnapshot,
    ValidationStatus,
)
from briefing_app.options_math import (
    OptionQuote,
    OptionsStructureResult,
    ShortBorrowSnapshot,
    build_options_structure,
    normalize_option_quotes,
)
from briefing_app.provider_validation import MALFORMED, OK, SYNTHETIC
from briefing_app.providers.alpha_vantage import AlphaVantageClient
from briefing_app.providers.apewisdom import ApeWisdomClient
from briefing_app.providers.base import ProviderDataError, ProviderResponse
from briefing_app.providers.budget import RequestBudget
from briefing_app.providers.cboe import CboeOptionsClient
from briefing_app.providers.finnhub import FinnhubClient
from briefing_app.providers.finra import FinraClient
from briefing_app.providers.fmp import FmpClient
from briefing_app.providers.fred import (
    FRED_MACRO_SERIES,
    FRED_PERCENT_CHANGE_FACTORS,
    FredClient,
)
from briefing_app.providers.sec_edgar import SecEdgarClient
from briefing_app.providers.twelve_data import TwelveDataClient
from briefing_app.providers.normalizers import (
    NormalizationError,
    normalize_apewisdom_retail_momentum,
    normalize_alpha_vantage_daily,
    normalize_alpha_vantage_daily_adjusted,
    normalize_alpha_vantage_earnings_calendar_csv,
    normalize_alpha_vantage_insider_transactions,
    normalize_alpha_vantage_news_sentiment,
    normalize_alpha_vantage_options_chain,
    normalize_alpha_vantage_quote,
    normalize_cboe_option_chain,
    normalize_finnhub_company_news,
    normalize_finnhub_recommendation_trends,
    normalize_fmp_analyst_ratings,
    normalize_fmp_earnings_calendar,
    normalize_fmp_economic_calendar,
    normalize_finra_short_volume,
    normalize_fmp_economic_indicators,
    normalize_fmp_grades_consensus,
    normalize_fmp_congress_trades,
    normalize_fmp_historical_price_eod,
    normalize_fmp_insider_trades,
    normalize_fmp_price_target_consensus,
    normalize_fmp_stock_news,
    normalize_fmp_treasury_rates,
    build_fred_macro_calendar,
    normalize_fred_release_dates,
    normalize_fred_series_observations,
    normalize_sec_form4_ownership_document,
    normalize_twelve_data_time_series,
)
from briefing_app.raw_cache import RawCache
from briefing_app.scoring import (
    ScoringReport,
    build_scoring_result,
    to_component_score_rows,
    to_daily_snapshot_rows,
    to_scoring_evidence_rows,
)
from briefing_app.settings import AppSettings
from briefing_app.storage import StorageRepository
from briefing_app.strategy import SetupContext, evaluate_candidate_setups, to_setup_signal_rows
from briefing_app.strategy.models import CandidateSetupResult, SetupReport, to_setup_evidence_rows
from briefing_app.universe.gate import run_gate
from briefing_app.universe.loader import load_universe
from briefing_app.universe.render import render_gate_markdown
from briefing_app.universe.store import GateStore, JsonGateStore


RunType = Literal["daily", "weekly"]
DataMode = Literal["fixture", "live"]

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

#: What a fixture-sourced row reports instead of `verified`. A fixture payload is invented,
#: so its provenance stops at "synthetic": a `verified` badge on a fixture row makes a
#: fixture run indistinguishable from a live one in the evidence ledger and preflight table.
STATUS_SYNTHETIC = SYNTHETIC

#: Legs `LiveDataSource` has no code to feed, mapped to why. A fixture run that scores one
#: of these is scoring something a live run cannot, which is exactly the comparison a
#: fixture run exists to support. Drop an entry when the live path grows a real source.
LIVE_UNSCORABLE_LEGS = {
    "executive_tone": "no transcript source is wired into LiveDataSource",
    "risk_reversal_history": "LiveDataSource returns the default empty risk-reversal history",
}

#: Components this project has decided not to score, mapped to why (Q4).
#:
#: `LIVE_UNSCORABLE_LEGS` above records a source that does not exist. This records the
#: other kind of gap: a source that does exist and was declined. `S_F` is scored off 13F
#: position changes, and closing it needs a curated filer universe, a table and migration,
#: and a two-quarter diff - a project, for 0.10 of the US formula and 0.05 of the EU one.
#: Routing it through an aggregator instead was rejected on source quality: EDGAR is the
#: primary record and the whole value of the component is reading the original filing.
#:
#: Recording it here rather than letting the fetch come back empty is the point. An empty
#: fetch reads as an outage that might clear tomorrow; this reads as the decision it is,
#: it costs no provider requests, and both run modes report the same reason.
#:
#: Two consequences, deliberately not hidden. `S_F` is in `REQUIRED_COMPONENTS` for
#: expression classes `P` and `S`, so both are pinned to Tier C for as long as this
#: stands - `enabled_expression_classes` is `[V, E]`, so nothing in the shipped universe
#: is affected today. And `S_I` is now the only holdings-derived component left.
DECLARED_UNSCORABLE_COMPONENTS = {
    "S_F": (
        "13F institutional flow is declared permanently n/a: a curated filer universe, a "
        "new table and a two-quarter diff are not justified by 0.10 of the US weight, and "
        "an aggregator was rejected because EDGAR is the primary record. Its weight is "
        "redistributed across the available components, not scored as neutral"
    ),
}

DASHBOARD_SUBDIR = "dashboard"

#: Sessions to walk back looking for FINRA's consolidated short-volume file. It lands on
#: a T+1 schedule, so the most recent weekday is routinely a 404 rather than an outage.
FINRA_LOOKBACK_SESSIONS = 5

#: Form 4 bodies fetched per ticker per run. Each is its own request because EDGAR indexes
#: filings without their contents, and an active large-cap files more in 90 days than the
#: insider component can use.
EDGAR_FORM4_MAX_FILINGS = 20

#: Stored sessions required before a self-built series is ranked against.
#:
#: The IV and put/call baselines are built from the app's own persisted snapshots rather
#: than bought, so they start empty and fill one session per run. A percentile computed
#: from a handful of points is not a weak reading, it is a meaningless one - so below this
#: the series is withheld entirely and the leg reports why.
SELF_BUILT_SERIES_MIN_SESSIONS = 20

#: Trailing window pulled for daily bars. Long enough for a realized-volatility read and
#: an IV-rank baseline without asking a provider for a full history every run.
PRICE_HISTORY_DAYS = 400
#: Trailing window for the treasury curve, sized for the release-change scale.
TREASURY_HISTORY_DAYS = 400
#: Trailing window pulled per macro series. `release_change_reading` scores the latest
#: change against the series' own historical changes and asks for at least 8 releases, so a
#: quarterly series like real GDP needs several years to clear that bar.
MACRO_HISTORY_DAYS = 3650

#: Macro factors this pipeline scores, mapped to the FMP `economic-indicators` series that
#: publishes them. Only factors a sector declares a sensitivity to are ever fetched, so a
#: name is never given macro credit for a factor nobody wrote a sensitivity down for.
FMP_MACRO_INDICATORS = {
    "policy_rate": "federalFunds",
    "cpi": "CPI",
    "inflation": "inflationRate",
    "unemployment": "unemploymentRate",
    "real_gdp": "realGDP",
    "retail_sales": "retailSales",
}

#: Factors derived from the treasury curve rather than a named indicator series.
TREASURY_FACTORS = frozenset({"treasury_10y", "yield_curve"})

#: Client classes, so preflight can read the declared plan gates without a live call.
PROVIDER_CLIENTS = {
    "alpha_vantage": AlphaVantageClient,
    "apewisdom": ApeWisdomClient,
    "cboe": CboeOptionsClient,
    "finnhub": FinnhubClient,
    "fmp": FmpClient,
    "fred": FredClient,
}
STATUS_REGISTERED = "registered"
STATUS_NO_CREDENTIALS = "no_credentials"
STATUS_UNAVAILABLE = "unavailable"
STATUS_PLAN_GATED = "plan_gated"
STATUS_BUDGET_EXHAUSTED = "budget_exhausted"


class FixtureFabricationError(RuntimeError):
    """Fixture mode was asked to score a leg the live path has no source for."""


@dataclass(frozen=True)
class StageFailure:
    """One isolated ticker/stage failure that did not hide the rest of the run."""

    ticker: str
    stage: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"ticker": self.ticker, "stage": self.stage, "message": self.message}


@dataclass(frozen=True)
class TickerData:
    """Normalized and computed data for one accepted ticker."""

    option_structure: OptionsStructureResult
    option_quotes: tuple[OptionQuote, ...]
    components: tuple[ComponentResult, ...]
    risk_reversal_history: tuple[float, ...] = ()
    raw_paths: tuple[Path, ...] = ()
    evidence_rows: tuple[dict[str, Any], ...] = ()


class PipelineDataSource(Protocol):
    """Data source used by the orchestrator after the gate."""

    #: Reported on the run status and dashboard, so a reader can tell fixture from live.
    data_mode: DataMode

    def preflight_rows(
        self,
        *,
        run_id: int | None,
        tickers: Sequence[str],
        run_date: date_type,
        checked_at: datetime,
    ) -> list[dict[str, Any]]:
        ...

    def market_overview(
        self,
        *,
        run_id: int | None,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
    ) -> tuple[list[MarketOverviewPoint], list[dict[str, Any]]]:
        ...

    def pull_ticker(
        self,
        *,
        gate_result: Any,
        config: AppConfig,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
        run_id: int | None,
        repository: "StorageRepository | None" = None,
    ) -> TickerData:
        ...


@dataclass
class PipelineRunOutput:
    """Return value from a daily or weekly orchestration run."""

    run_id: str
    run_type: RunType
    run_date: date_type
    status: str
    started_at: datetime
    data_mode: DataMode = "fixture"
    finished_at: datetime | None = None
    storage_run_id: int | None = None
    dashboard: DashboardPayload | None = None
    scoring_report: ScoringReport | None = None
    setup_report: SetupReport | None = None
    gate_report: Any | None = None
    html_path: Path | None = None
    json_path: Path | None = None
    status_path: Path | None = None
    gate_markdown_path: Path | None = None
    diagnostics: list[str] = field(default_factory=list)
    failures: list[StageFailure] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "storage_run_id": self.storage_run_id,
            "run_type": self.run_type,
            "run_date": self.run_date.isoformat(),
            "status": self.status,
            "data_mode": self.data_mode,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "html_path": str(self.html_path) if self.html_path else None,
            "json_path": str(self.json_path) if self.json_path else None,
            "status_path": str(self.status_path) if self.status_path else None,
            "gate_markdown_path": (
                str(self.gate_markdown_path) if self.gate_markdown_path else None
            ),
            "diagnostics": list(self.diagnostics),
            "failures": [failure.to_dict() for failure in self.failures],
            "dashboard_counts": self.dashboard.counts if self.dashboard else None,
            "scoring_counts": self.scoring_report.counts() if self.scoring_report else None,
            "setup_counts": self.setup_report.counts() if self.setup_report else None,
        }


def make_run_id(run_type: RunType, run_date: date_type) -> str:
    return f"{run_type}-{run_date.isoformat()}-{uuid.uuid4().hex[:8]}"


def is_market_day(day: date_type, *, holidays: Iterable[date_type] = ()) -> bool:
    """Market-day guard. Weekends and supplied exchange holidays are skipped."""
    return day.weekday() < 5 and day not in set(holidays)


def run_daily(
    config: AppConfig | None = None,
    *,
    run_date: date_type | None = None,
    mode: str | None = None,
    data_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    store: GateStore | None = None,
    repository: StorageRepository | None = None,
    data_source: PipelineDataSource | None = None,
    data_mode: DataMode = "fixture",
    persist: bool = True,
    force: bool = False,
    max_tickers: int | None = None,
) -> PipelineRunOutput:
    return run_pipeline(
        config,
        run_type="daily",
        run_date=run_date,
        mode=mode,
        data_dir=data_dir,
        output_dir=output_dir,
        store=store,
        repository=repository,
        data_source=data_source,
        data_mode=data_mode,
        persist=persist,
        force=force,
        max_tickers=max_tickers,
    )


def run_weekly(
    config: AppConfig | None = None,
    *,
    run_date: date_type | None = None,
    mode: str | None = None,
    data_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    store: GateStore | None = None,
    repository: StorageRepository | None = None,
    data_source: PipelineDataSource | None = None,
    data_mode: DataMode = "fixture",
    persist: bool = True,
    force: bool = False,
    max_tickers: int | None = None,
) -> PipelineRunOutput:
    return run_pipeline(
        config,
        run_type="weekly",
        run_date=run_date,
        mode=mode,
        data_dir=data_dir,
        output_dir=output_dir,
        store=store,
        repository=repository,
        data_source=data_source,
        data_mode=data_mode,
        persist=persist,
        force=force,
        max_tickers=max_tickers,
    )


def run_pipeline(
    config: AppConfig | None = None,
    *,
    run_type: RunType,
    run_date: date_type | None = None,
    mode: str | None = None,
    data_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    store: GateStore | None = None,
    repository: StorageRepository | None = None,
    data_source: PipelineDataSource | None = None,
    data_mode: DataMode = "fixture",
    persist: bool = True,
    force: bool = False,
    max_tickers: int | None = None,
) -> PipelineRunOutput:
    """Run the full deterministic pipeline for one date."""
    loaded_config = config or load_config()
    effective_date = run_date or date_type.today()
    started_at = datetime.now(UTC)
    run_id = make_run_id(run_type, effective_date)
    data_root = Path(data_dir or os.getenv("BRIEFING_DATA_DIR") or "data")
    output_root = Path(output_dir or os.getenv("BRIEFING_OUTPUT_DIR") or "output")
    raw_cache = RawCache(data_root)
    repo = repository or _repository_from_env()
    source = data_source or _data_source_for_mode(data_mode)
    effective_data_mode = getattr(source, "data_mode", data_mode)
    output = PipelineRunOutput(
        run_id=run_id,
        run_type=run_type,
        run_date=effective_date,
        status=STATUS_RUNNING,
        started_at=started_at,
        data_mode=effective_data_mode,
    )

    try:
        if repo is not None and persist:
            output.storage_run_id = repo.upsert_briefing_run(
                run_date=effective_date,
                run_type=run_type,
                status=STATUS_RUNNING,
                started_at=started_at,
                details={"pipeline_run_id": run_id, "data_mode": effective_data_mode},
            )

        if not force and not is_market_day(effective_date):
            output.status = STATUS_SKIPPED
            output.diagnostics.append(
                f"{effective_date.isoformat()} is not a market day; run skipped."
            )
            return _finish_output(output, repo, output_root, data_root, persist=persist)

        loaded = load_universe(loaded_config, mode)
        history_store = store or JsonGateStore(data_root)
        history = history_store.active_history(
            effective_date, loaded_config.gate.rejection_cooldown_days
        )
        gate_report = run_gate(
            loaded.candidates,
            run_date=effective_date,
            settings=loaded_config.gate,
            history=history,
            run_id=f"{run_id}-gate",
            load_warnings=loaded.warnings,
            load_errors=loaded.errors,
        )
        output.gate_report = gate_report
        output.diagnostics.extend(f"load warning: {warning}" for warning in loaded.warnings)
        output.diagnostics.extend(f"load error: {error}" for error in loaded.errors)

        accepted = gate_report.accepted
        if max_tickers is not None:
            accepted = accepted[:max_tickers]
        accepted_tickers = [result.ticker for result in accepted]

        if repo is not None and persist:
            for row in _candidate_gate_rows(gate_report, output.storage_run_id):
                repo.upsert_candidate_gate(_json_field_safe_mapping(row))
            for row in source.preflight_rows(
                run_id=output.storage_run_id,
                tickers=accepted_tickers,
                run_date=effective_date,
                checked_at=started_at,
            ):
                repo.upsert_source_preflight(_json_field_safe_mapping(row))

        ticker_data: dict[str, TickerData] = {}
        component_results: list[ComponentResult] = []
        score_results = []
        setup_contexts: list[SetupContext] = []
        explicit_evidence: list[dict[str, Any]] = []

        market_points, market_evidence = source.market_overview(
            run_id=output.storage_run_id,
            run_date=effective_date,
            generated_at=started_at,
            raw_cache=raw_cache,
        )
        explicit_evidence.extend(market_evidence)

        for gate_result in accepted:
            try:
                data = source.pull_ticker(
                    gate_result=gate_result,
                    config=loaded_config,
                    run_date=effective_date,
                    generated_at=started_at,
                    raw_cache=raw_cache,
                    run_id=output.storage_run_id,
                    repository=repo,
                )
                ticker_data[gate_result.ticker] = data
                component_results.extend(data.components)
                explicit_evidence.extend(data.option_structure.evidence_rows)
                explicit_evidence.extend(data.evidence_rows)

                score = build_scoring_result(
                    gate_result,
                    data.components,
                    options_structure=data.option_structure,
                    run_date=effective_date,
                )
                score_results.append(score)
                setup_contexts.append(
                    SetupContext(
                        gate_result=gate_result,
                        score=score,
                        structure=data.option_structure,
                        option_quotes=data.option_quotes,
                        risk_reversal_history=data.risk_reversal_history,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - isolate ticker failures by design.
                output.failures.append(
                    StageFailure(
                        ticker=gate_result.ticker,
                        stage="data_pull_normalize_compute",
                        message=str(exc),
                    )
                )
                output.diagnostics.append(
                    f"{gate_result.ticker} data_pull_normalize_compute failed: {exc}"
                )

        scoring_report = ScoringReport(
            run_id=f"{run_id}-scoring",
            run_date=effective_date,
            generated_at=started_at,
            results=score_results,
        )
        output.scoring_report = scoring_report
        explicit_evidence.extend(
            to_scoring_evidence_rows(
                scoring_report, run_id=output.storage_run_id, as_of=started_at
            )
        )

        setup_results: list[CandidateSetupResult] = []
        for context in setup_contexts:
            try:
                setup_results.append(
                    evaluate_candidate_setups(
                        context,
                        run_date=effective_date,
                        settings=loaded_config.strategy,
                        filters=loaded_config.option_filters,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - isolate ticker failures by design.
                output.failures.append(
                    StageFailure(
                        ticker=context.ticker,
                        stage="setup_rules",
                        message=str(exc),
                    )
                )
                output.diagnostics.append(f"{context.ticker} setup_rules failed: {exc}")

        setup_report = SetupReport(
            run_id=f"{run_id}-setups",
            run_date=effective_date,
            generated_at=started_at,
            results=setup_results,
        )
        output.setup_report = setup_report

        setup_evidence = to_setup_evidence_rows(setup_report, run_id=output.storage_run_id)
        dashboard_evidence = [*explicit_evidence, *setup_evidence]
        prior_scorecards = (
            repo.prior_scorecards(before_date=effective_date, limit=20)
            if repo is not None and persist
            else []
        )
        dashboard = build_dashboard_payload(
            run_id=run_id,
            run_date=effective_date,
            generated_at=started_at,
            data_mode=effective_data_mode,
            gate_report=gate_report,
            scores=score_results,
            component_results=component_results,
            setup_report=setup_report,
            evidence_rows=dashboard_evidence,
            prior_scorecards=prior_scorecards,
            market_overview=market_points,
            diagnostics=output.diagnostics,
        )
        output.dashboard = dashboard

        if repo is not None and persist:
            for row in to_component_score_rows(scoring_report, run_id=output.storage_run_id):
                repo.upsert_component_score(_json_field_safe_mapping(row))
            for row in to_daily_snapshot_rows(
                scoring_report,
                snap_date=effective_date,
                run_id=output.storage_run_id,
                options_structures={
                    ticker: data.option_structure for ticker, data in ticker_data.items()
                },
            ):
                repo.upsert_daily_snapshot(_json_field_safe_mapping(row))
            repo.upsert_evidence_rows(_with_run_id(dashboard_evidence, output.storage_run_id))
            for row in to_setup_signal_rows(setup_report, run_id=output.storage_run_id):
                repo.upsert_setup_signal(_json_field_safe_mapping(row))

        if persist:
            dashboard_dir = output_root / DASHBOARD_SUBDIR / effective_date.isoformat()
            output.html_path, output.json_path = write_dashboard_artifacts(
                dashboard, dashboard_dir
            )
            output.gate_markdown_path = _write_gate_markdown(
                gate_report, output_root, effective_date
            )
            history_store.save_report(gate_report)
            history_store.update_history(gate_report, loaded_config.gate.rejection_cooldown_days)

        output.status = _final_status(output)
        return _finish_output(output, repo, output_root, data_root, persist=persist)
    except Exception as exc:  # noqa: BLE001 - persist run failure before re-raising.
        output.status = STATUS_FAILED
        output.failures.append(StageFailure(ticker="*", stage="pipeline", message=str(exc)))
        output.diagnostics.append(f"pipeline failed: {exc}")
        _finish_output(output, repo, output_root, data_root, persist=persist)
        raise


class FixtureDataSource:
    """Deterministic fixture data source for local full-pipeline runs.

    Fixture payloads are invented, so they are labelled `synthetic` rather than `verified`,
    and the source refuses to feed any leg in `LIVE_UNSCORABLE_LEGS`: a fixture run that
    scored one would look better than the live run it is supposed to be compared against.
    """

    data_mode: DataMode = "fixture"

    def __init__(self, failing_tickers: Iterable[str] = ()) -> None:
        self.failing_tickers = {ticker.strip().upper() for ticker in failing_tickers}

    def preflight_rows(
        self,
        *,
        run_id: int | None,
        tickers: Sequence[str],
        run_date: date_type,
        checked_at: datetime,
    ) -> list[dict[str, Any]]:
        endpoints = ("market_overview", "options_chain", "price_history", "news", "macro")
        rows: list[dict[str, Any]] = []
        for endpoint in endpoints:
            targets = ["*"] if endpoint == "market_overview" else list(tickers)
            for target in targets:
                rows.append(
                    {
                        "run_id": run_id,
                        "source": "fixture",
                        "endpoint": endpoint,
                        "target": target,
                        "status": "ok",
                        "entitlement_status": "fixture",
                        "venue": "*",
                        "checked_at": checked_at,
                        "as_of": checked_at,
                        "validation_status": STATUS_SYNTHETIC,
                        "note": "invented fixture payload; nothing here was fetched",
                        "details": {
                            "run_date": run_date.isoformat(),
                            "data_mode": "fixture",
                        },
                    }
                )
        return rows

    def market_overview(
        self,
        *,
        run_id: int | None,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
    ) -> tuple[list[MarketOverviewPoint], list[dict[str, Any]]]:
        payload = {
            "label": "SPX implied weekly move",
            "value": 1.8,
            "unit": "percent",
            "as_of": generated_at.isoformat(),
        }
        path = raw_cache.write_json("fixture", "market_overview", run_date, "SPX", payload)
        point = MarketOverviewPoint(
            label=payload["label"],
            value=payload["value"],
            source="fixture raw cache",
            as_of=payload["as_of"],
            note="synthetic market overview for deterministic pipeline acceptance",
        )
        evidence = [
            _evidence_row(
                run_id=run_id,
                ticker="*",
                component="MARKET",
                field_name="spx_implied_weekly_move_pct",
                field_value=payload["value"],
                source="fixture raw cache",
                as_of=generated_at,
                endpoint_or_file=str(path),
                validation_status=STATUS_SYNTHETIC,
                note="Displayed in Market Overview.",
            )
        ]
        return [point], evidence

    def pull_ticker(
        self,
        *,
        gate_result: Any,
        config: AppConfig,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
        run_id: int | None,
        repository: "StorageRepository | None" = None,
    ) -> TickerData:
        ticker = gate_result.ticker
        if ticker in self.failing_tickers:
            raw_cache.write_json(
                "fixture",
                "failed_payload",
                run_date,
                ticker,
                {"ticker": ticker, "error": "forced fixture failure"},
            )
            raise RuntimeError("forced fixture data failure")

        candidate = gate_result.candidate
        spot = float(100 + (sum(ord(char) for char in ticker) % 35))
        raw_paths: list[Path] = []

        quotes = _fixture_option_quotes(ticker, spot=spot, run_date=run_date, as_of=generated_at)
        bars = _fixture_price_bars(spot=spot, run_date=run_date)
        options_path = raw_cache.write_json(
            "fixture",
            "options_chain",
            run_date,
            ticker,
            [_quote_payload(quote) for quote in quotes],
        )
        price_path = raw_cache.write_json(
            "fixture", "price_history", run_date, ticker, bars
        )
        raw_paths.extend([options_path, price_path])
        option_structure = build_options_structure(
            ticker=ticker,
            spot=spot,
            as_of=generated_at,
            option_quotes=quotes,
            price_bars=bars,
            expression_class=candidate.expression_class,
            chain_verified=True,
            # No iv_history: the live path stores none, so iv_rank is n/a there and here.
            pc_ratio_vol_history=[0.80, 0.85, 0.90, 0.95, 1.00],
            pc_ratio_oi_history=[0.90, 0.95, 1.00, 1.05, 1.10],
            event_multiplier=config.strategy.event_day_multiplier
            if gate_result.earnings_in_horizon
            else 1.0,
            run_id=run_id,
            source="fixture raw cache",
            venue=candidate.venue,
            endpoint_or_file=f"{options_path}; {price_path}",
            validation_status=STATUS_SYNTHETIC,
        )

        macro_path = raw_cache.write_json(
            "fixture",
            "macro",
            run_date,
            ticker,
            {
                "readings": [
                    {"name": "policy_rate", "trend": -0.50},
                    {"name": "cpi", "trend": -0.40},
                ],
                "calendar": [{"name": "CPI", "date": (run_date + timedelta(days=4)).isoformat()}],
            },
        )
        raw_paths.append(macro_path)
        exposure = _sector_exposure(config, candidate.sector)
        macro = build_macro_component(
            ticker=ticker,
            geography=candidate.geography,
            run_date=run_date,
            readings=[
                MacroReading(
                    name="policy_rate",
                    trend=-0.50,
                    as_of=run_date,
                    source="fixture raw cache",
                    detail="fixture policy path easing",
                ),
                MacroReading(
                    name="cpi",
                    trend=-0.40,
                    as_of=run_date,
                    source="fixture raw cache",
                    detail="fixture inflation surprise cooling",
                ),
            ],
            exposure=exposure,
            macro_calendar=MacroCalendar(
                source="fixture raw cache",
                as_of=generated_at,
                events=[
                    MacroEvent(
                        name="CPI",
                        event_date=datetime.combine(
                            run_date + timedelta(days=4), datetime.min.time(), tzinfo=UTC
                        ),
                        source="fixture raw cache",
                        country="US",
                        importance="high",
                    )
                ],
            ),
            manual_catalysts=gate_result.catalysts_in_horizon,
            as_of=generated_at,
            max_age_days=config.components.macro_max_age_days,
            endpoint_or_file=str(macro_path),
            run_id=run_id,
        )

        news_path = raw_cache.write_json(
            "fixture",
            "news",
            run_date,
            ticker,
            {
                "articles": [
                    {"title": f"{ticker} catalyst setup improves", "sentiment": 0.65},
                    {"title": f"{ticker} baseline update", "sentiment": 0.10},
                ]
            },
        )
        raw_paths.append(news_path)
        news_batch = NewsSentimentBatch(
            ticker=ticker,
            as_of=generated_at,
            source="fixture raw cache",
            articles=[
                NewsArticle(
                    ticker=ticker,
                    title=f"{ticker} catalyst setup improves",
                    source="fixture wire",
                    published_at=generated_at - timedelta(hours=2),
                    url=f"https://fixture.local/{ticker}/fresh",
                    sentiment_score=0.65,
                ),
                NewsArticle(
                    ticker=ticker,
                    title=f"{ticker} baseline update",
                    source="fixture wire",
                    published_at=generated_at - timedelta(days=3),
                    url=f"https://fixture.local/{ticker}/baseline",
                    sentiment_score=0.10,
                ),
            ],
        )
        sentiment = build_sentiment_component(
            ticker=ticker,
            geography=candidate.geography,
            run_date=run_date,
            news=news_batch,
            analyst_signals=[
                AnalystSignal(
                    ticker=ticker,
                    as_of=run_date,
                    source="fixture analyst file",
                    firm="Fixture Research",
                    rating="Buy",
                    previous_rating="Hold",
                    action="upgrade",
                    price_target=spot * 1.25,
                    previous_price_target=spot * 1.05,
                )
            ],
            spot=spot,
            # No executive_tone fixture: the live path still has no transcript source.
            as_of=generated_at,
            max_age_days=config.components.sentiment_max_age_days,
            endpoint_or_file=str(news_path),
            run_id=run_id,
        )

        insider_path = raw_cache.write_json(
            "fixture",
            "insider",
            run_date,
            ticker,
            {"transactions": [{"type": "P", "shares": 15000, "price": spot}]},
        )
        raw_paths.append(insider_path)
        insider = build_insider_component(
            ticker=ticker,
            geography=candidate.geography,
            transactions=[
                InsiderTransaction(
                    ticker=ticker,
                    as_of=run_date - timedelta(days=7),
                    source="fixture raw cache",
                    insider="Jane Roe",
                    title="Chief Executive Officer",
                    transaction_type="P",
                    shares=15_000,
                    price=spot,
                ),
                InsiderTransaction(
                    ticker=ticker,
                    as_of=run_date - timedelta(days=5),
                    source="fixture raw cache",
                    insider="Plan Seller",
                    title="Director",
                    transaction_type="S",
                    shares=30_000,
                    price=spot,
                    raw={"footnote": "Sold under Rule 10b5-1 plan"},
                ),
            ],
            run_date=run_date,
            as_of=generated_at,
            window_days=config.components.insider_window_days,
            source="fixture raw cache",
            endpoint_or_file=str(insider_path),
            run_id=run_id,
        )

        # No ownership fixture: S_F is declared permanently n/a, so a fixture run that
        # scored it would be rehearsing a component the live run does not compute.
        institutional = _declared_unavailable_component(
            "S_F",
            ticker=ticker,
            geography=candidate.geography,
            as_of=generated_at,
        )

        extra_evidence = [
            _evidence_row(
                run_id=run_id,
                ticker=ticker,
                component="RAW",
                field_name="raw_cache_paths",
                field_value="; ".join(str(path) for path in raw_paths),
                source="fixture raw cache",
                as_of=generated_at,
                endpoint_or_file="; ".join(str(path) for path in raw_paths),
                validation_status=STATUS_SYNTHETIC,
                note="Raw payloads written before normalization and computation.",
            )
        ]

        data = TickerData(
            option_structure=option_structure,
            option_quotes=tuple(quotes),
            components=tuple(
                _as_synthetic(component)
                for component in (macro, sentiment, insider, institutional)
            ),
            # No risk_reversal_history: the live path supplies none, so the skew rule has to
            # reject for want of history in fixture mode exactly as it does live.
            raw_paths=tuple(raw_paths),
            evidence_rows=tuple(extra_evidence),
        )
        _refuse_fabricated_legs(ticker, data)
        return data


class LiveDataSource:
    """Provider-backed data source for post-gate daily and weekly runs."""

    data_mode: DataMode = "live"

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        fetcher: Fetcher | None = None,
        cache_only: bool | None = None,
        budget: RequestBudget | None = None,
    ) -> None:
        self.settings = settings or AppSettings.from_env()
        self.fetcher = fetcher
        self.cache_only = (
            _truthy(os.getenv("BRIEFING_LIVE_CACHE_ONLY"))
            if cache_only is None
            else cache_only
        )
        self._macro_calendar: dict[
            date_type, tuple[MacroCalendar | None, tuple[ProviderResponse, ...], tuple[str, ...]]
        ] = {}
        self._macro_readings: dict[
            date_type, tuple[tuple[MacroReading, ...], tuple[ProviderResponse, ...], tuple[str, ...]]
        ] = {}
        #: series id -> (release id, release name), resolved once and shared by the macro
        #: calendar and the macro readings, which both need the same join.
        self._fred_series_releases_by_run: dict[date_type, dict[str, tuple[str, str]]] = {}
        self._political_trades: dict[
            date_type, tuple[tuple[PoliticalTrade, ...], tuple[ProviderResponse, ...], tuple[str, ...]]
        ] = {}
        self._retail_momentum: dict[
            date_type,
            tuple[dict[str, RetailMomentumSnapshot], tuple[ProviderResponse, ...], tuple[str, ...]],
        ] = {}
        #: Shared by every client this source builds, so one run honours one budget.
        self._budget = budget or RequestBudget(self.settings.data_dir)

    def preflight_rows(
        self,
        *,
        run_id: int | None,
        tickers: Sequence[str],
        run_date: date_type,
        checked_at: datetime,
    ) -> list[dict[str, Any]]:
        rows = [
            _live_preflight_row(
                run_id=run_id,
                provider="cboe",
                endpoint="delayed_options_chain",
                target="SPY",
                component="MARKET",
                status=STATUS_REGISTERED,
                entitlement="free_delayed",
                checked_at=checked_at,
                run_date=run_date,
                note="Market overview source for SPY implied move.",
            )
        ]
        optional_endpoints = (
            ("fmp", "historical_price_eod", "price_history", "FMP_API_KEY"),
            ("fmp", "economic_indicators", "S_M", "FMP_API_KEY"),
            ("fmp", "treasury_rates", "S_M", "FMP_API_KEY"),
            ("fmp", "earnings_calendar", "catalyst", "FMP_API_KEY"),
            ("fmp", "analyst_ratings", "S_S", "FMP_API_KEY"),
            ("fmp", "price_target_consensus", "S_S", "FMP_API_KEY"),
            ("fmp", "senate_latest", "S_S", "FMP_API_KEY"),
            ("fmp", "house_latest", "S_S", "FMP_API_KEY"),
            ("finnhub", "company_news", "S_S", "FINNHUB_API_KEY"),
            ("finnhub", "recommendation_trends", "S_S", "FINNHUB_API_KEY"),
            ("twelve_data", "time_series", "price_history", "TWELVE_DATA_API_KEY"),
            ("alpha_vantage", "news_sentiment", "S_S", "ALPHA_VANTAGE_API_KEY"),
            ("alpha_vantage", "insider_transactions", "S_I", "ALPHA_VANTAGE_API_KEY"),
            ("alpha_vantage", "daily", "price_history", "ALPHA_VANTAGE_API_KEY"),
            ("alpha_vantage", "daily_adjusted", "price_history", "ALPHA_VANTAGE_API_KEY"),
            ("fmp", "economics", "S_M", "FMP_API_KEY"),
            ("fmp", "stock_news", "S_S", "FMP_API_KEY"),
            ("fmp", "insider_trades", "S_I", "FMP_API_KEY"),
        )
        market_wide = {
            "economic_indicators",
            "treasury_rates",
            "economics",
            "senate_latest",
            "house_latest",
        }
        for ticker in tickers:
            rows.append(
                _live_preflight_row(
                    run_id=run_id,
                    provider="cboe",
                    endpoint="delayed_options_chain",
                    target=ticker,
                    component="S_O",
                    status=STATUS_REGISTERED,
                    entitlement="free_delayed",
                    checked_at=checked_at,
                    run_date=run_date,
                    note="Primary US per-strike options chain source.",
                )
            )
            for provider, endpoint, component, credential_env in optional_endpoints:
                status, note = self._endpoint_availability(provider, endpoint, credential_env)
                rows.append(
                    _live_preflight_row(
                        run_id=run_id,
                        provider=provider,
                        endpoint=endpoint,
                        target="*" if endpoint in market_wide else ticker,
                        component=component,
                        status=status,
                        entitlement="key_required_plan_gated",
                        checked_at=checked_at,
                        run_date=run_date,
                        note=note,
                    )
                )
            rows.append(
                _live_preflight_row(
                    run_id=run_id,
                    provider="apewisdom",
                    endpoint="retail_momentum",
                    target="*",
                    component="S_S",
                    status=STATUS_REGISTERED,
                    entitlement="keyless_public_api",
                    checked_at=checked_at,
                    run_date=run_date,
                    note=(
                        "Keyless public all-stocks attention feed; fetched once per run "
                        "and filtered locally."
                    ),
                )
            )
        return rows

    def _endpoint_availability(
        self, provider: str, endpoint: str, credential_env: str
    ) -> tuple[str, str]:
        """Report why an endpoint will or will not be reachable on this run.

        Preflight is what a reader consults before trusting a score, so a plan gate and a
        spent request budget have to be visible here rather than surfacing later as an
        unexplained `n/a`.
        """

        if self.cache_only:
            return STATUS_REGISTERED, "Available from cache-only mode."
        if not self.settings.credential(credential_env):
            return STATUS_NO_CREDENTIALS, f"Requires {credential_env}."

        client = PROVIDER_CLIENTS.get(provider)
        premium = getattr(client, "premium_endpoints", frozenset())
        if self.settings.provider_plan(provider) == "free" and endpoint in premium:
            return (
                STATUS_PLAN_GATED,
                f"{provider}.{endpoint} needs a paid plan; {provider.upper()}_PLAN is 'free'.",
            )
        if endpoint in self._budget.plan_gated_endpoints(provider):
            return (
                STATUS_PLAN_GATED,
                f"{provider}.{endpoint} was refused as plan-gated for this key.",
            )

        remaining = self._budget.remaining(
            provider, plan=self.settings.provider_plan(provider)
        )
        if remaining is not None and remaining <= 0:
            return (
                STATUS_BUDGET_EXHAUSTED,
                f"{provider} daily request budget is spent; resets tomorrow.",
            )
        if remaining is not None:
            return STATUS_REGISTERED, f"{remaining} of today's {provider} requests remain."
        return STATUS_REGISTERED, f"Reachable with {credential_env}."

    def market_overview(
        self,
        *,
        run_id: int | None,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
    ) -> tuple[list[MarketOverviewPoint], list[dict[str, Any]]]:
        try:
            response = self._cboe(raw_cache).fetch_options_chain(
                "SPY", run_date=run_date, cache_only=self.cache_only
            )
            chain = normalize_cboe_option_chain(
                "SPY",
                response.payload,
                filters=OptionFilterConfig(),
                endpoint_or_file=response.cache_path or response.url or "",
            )
            structure = build_options_structure(
                ticker="SPY",
                spot=chain.spot,
                as_of=chain.as_of or generated_at,
                option_quotes=chain,
                price_bars=(),
                chain_verified=_chain_is_verified(chain),
                run_id=run_id,
                source=chain.source,
                venue=chain.venue,
                endpoint_or_file=chain.endpoint_or_file,
                validation_status=chain.validation_status.value,
            )
            weekly = structure.expected_moves.get("weekly")
            if weekly is None:
                raise RuntimeError(
                    "SPY CBOE chain did not contain a usable weekly straddle."
                )
            point = MarketOverviewPoint(
                label="SPY implied weekly move",
                value=round(weekly.straddle_pct * 100.0, 4),
                source=chain.source,
                as_of=(chain.as_of or generated_at).isoformat(),
                note="Computed from CBOE delayed options straddle.",
            )
            evidence = [
                _provider_response_evidence(
                    response, run_id=run_id, component="MARKET", field_name="provider_status"
                ),
                _evidence_row(
                    run_id=run_id,
                    ticker="SPY",
                    component="MARKET",
                    field_name="spy_implied_weekly_move_pct",
                    field_value=point.value,
                    source=chain.source,
                    as_of=chain.as_of or generated_at,
                    endpoint_or_file=chain.endpoint_or_file,
                    validation_status=chain.validation_status.value,
                    note="Displayed in Market Overview.",
                ),
            ]
            return [point], evidence
        except Exception as exc:  # noqa: BLE001 - market overview must not kill the run.
            return [], [
                _evidence_row(
                    run_id=run_id,
                    ticker="SPY",
                    component="MARKET",
                    field_name="market_overview_status",
                    field_value=STATUS_UNAVAILABLE,
                    source="live providers",
                    as_of=generated_at,
                    endpoint_or_file="",
                    validation_status=STATUS_UNAVAILABLE,
                    note=f"SPY market overview unavailable: {exc}",
                )
            ]

    def pull_ticker(
        self,
        *,
        gate_result: Any,
        config: AppConfig,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
        run_id: int | None,
        repository: "StorageRepository | None" = None,
    ) -> TickerData:
        ticker = gate_result.ticker.strip().upper()
        candidate = gate_result.candidate
        responses: list[ProviderResponse] = []
        issues: list[str] = []
        raw_paths: list[Path] = []

        chain = self._pull_option_chain(
            ticker,
            config=config,
            run_date=run_date,
            generated_at=generated_at,
            raw_cache=raw_cache,
            responses=responses,
            raw_paths=raw_paths,
        )
        quote_source = chain.endpoint_or_file
        price_bars = self._price_bars(
            ticker,
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
            responses=responses,
            raw_paths=raw_paths,
            issues=issues,
        )
        short_borrow = self._short_borrow(
            ticker,
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
            responses=responses,
            raw_paths=raw_paths,
            issues=issues,
        )
        stored_iv, stored_pc_vol, stored_pc_oi = self._stored_option_series(
            ticker,
            run_date=run_date,
            repository=repository,
            issues=issues,
        )
        macro_calendar, macro_responses, macro_issues = self._macro_calendar_for_run(
            config=config,
            run_date=run_date,
            generated_at=generated_at,
            raw_cache=raw_cache,
        )
        for response in macro_responses:
            _record_response(response, responses, raw_paths)
        issues.extend(macro_issues)
        macro_readings, reading_responses, reading_issues = self._macro_readings_for_run(
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
        )
        for response in reading_responses:
            _record_response(response, responses, raw_paths)
        issues.extend(reading_issues)
        catalyst_calendar = self._catalyst_calendar(
            ticker,
            config=config,
            run_date=run_date,
            generated_at=generated_at,
            raw_cache=raw_cache,
            responses=responses,
            raw_paths=raw_paths,
            issues=issues,
        )
        news = self._news_batch(
            ticker,
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
            responses=responses,
            raw_paths=raw_paths,
            issues=issues,
        )
        analyst_signals = self._analyst_signals(
            ticker,
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
            responses=responses,
            raw_paths=raw_paths,
            issues=issues,
        )
        political_trades, political_responses, political_issues = self._political_trades_for_run(
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
        )
        for response in political_responses:
            _record_response(response, responses, raw_paths)
        issues.extend(political_issues)
        retail_by_ticker, retail_responses, retail_issues = self._retail_momentum_for_run(
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
        )
        for response in retail_responses:
            _record_response(response, responses, raw_paths)
        issues.extend(retail_issues)
        insiders = self._insider_transactions(
            ticker,
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
            responses=responses,
            raw_paths=raw_paths,
            issues=issues,
        )
        option_structure = build_options_structure(
            ticker=ticker,
            spot=chain.spot,
            as_of=chain.as_of or generated_at,
            option_quotes=chain,
            price_bars=price_bars,
            expression_class=candidate.expression_class,
            chain_verified=_chain_is_verified(chain),
            # Put/call baselines are self-built from the app's persisted option snapshots.
            pc_ratio_vol_history=stored_pc_vol,
            pc_ratio_oi_history=stored_pc_oi,
            iv_history=stored_iv,
            short_borrow=short_borrow,
            event_multiplier=config.strategy.event_day_multiplier
            if gate_result.earnings_in_horizon
            else 1.0,
            run_id=run_id,
            source=chain.source,
            venue=chain.venue,
            endpoint_or_file=quote_source,
            validation_status=chain.validation_status.value,
        )

        macro = build_macro_component(
            ticker=ticker,
            geography=candidate.geography,
            run_date=run_date,
            readings=macro_readings,
            exposure=_declared_sector_exposure(config, candidate.sector),
            macro_calendar=macro_calendar,
            catalyst_calendar=catalyst_calendar,
            manual_catalysts=gate_result.catalysts_in_horizon,
            calendar_days=config.components.catalyst_calendar_days,
            as_of=generated_at,
            max_age_days=config.components.macro_max_age_days,
            endpoint_or_file=(
                macro_calendar.endpoint_or_file
                if macro_calendar
                else _endpoint_group(responses, {"economic_indicators", "treasury_rates"})
            ),
            run_id=run_id,
        )
        sentiment = build_sentiment_component(
            ticker=ticker,
            geography=candidate.geography,
            run_date=run_date,
            news=news,
            analyst_signals=analyst_signals,
            spot=chain.spot,
            retail_momentum=retail_by_ticker.get(ticker),
            political_flow=political_trades,
            as_of=generated_at,
            max_age_days=config.components.sentiment_max_age_days,
            endpoint_or_file=_endpoint_group(
                responses,
                {"news_sentiment", "stock_news", "senate_latest", "house_latest", "retail_momentum"},
            ),
            run_id=run_id,
        )
        insider = build_insider_component(
            ticker=ticker,
            geography=candidate.geography,
            transactions=insiders,
            run_date=run_date,
            as_of=generated_at,
            window_days=config.components.insider_window_days,
            endpoint_or_file=_endpoint_group(responses, {"insider_transactions", "insider_trades"}),
            run_id=run_id,
        )
        institutional = _declared_unavailable_component(
            "S_F",
            ticker=ticker,
            geography=candidate.geography,
            as_of=generated_at,
        )

        extra_evidence = [
            _provider_response_evidence(response, run_id=run_id)
            for response in responses
        ]
        extra_evidence.extend(
            _provider_issue_evidence(
                issue,
                run_id=run_id,
                ticker=ticker,
                as_of=generated_at,
            )
            for issue in issues
        )
        if raw_paths:
            extra_evidence.append(
                _evidence_row(
                    run_id=run_id,
                    ticker=ticker,
                    component="RAW",
                    field_name="raw_cache_paths",
                    field_value="; ".join(str(path) for path in raw_paths),
                    source="live providers",
                    as_of=generated_at,
                    endpoint_or_file="; ".join(str(path) for path in raw_paths),
                    note="Raw live provider payloads written before normalization.",
                )
            )

        return TickerData(
            option_structure=option_structure,
            option_quotes=tuple(normalize_option_quotes(chain)),
            components=(macro, sentiment, insider, institutional),
            raw_paths=tuple(raw_paths),
            evidence_rows=tuple(extra_evidence),
        )

    def _pull_option_chain(
        self,
        ticker: str,
        *,
        config: AppConfig,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
    ):
        filters = _option_filter_config(config)
        first_error: Exception | None = None
        last_error: Exception | None = None
        for provider in _provider_order(config, "options"):
            if provider == "alpha_vantage":
                try:
                    return self._pull_alpha_vantage_chain(
                        ticker,
                        filters=filters,
                        run_date=run_date,
                        generated_at=generated_at,
                        raw_cache=raw_cache,
                        responses=responses,
                        raw_paths=raw_paths,
                    )
                except (ProviderDataError, NormalizationError) as exc:
                    first_error = first_error or exc
                    last_error = exc
                    continue
            elif provider == "cboe":
                try:
                    response = self._cboe(raw_cache).fetch_options_chain(
                        ticker, run_date=run_date, cache_only=self.cache_only
                    )
                    _record_response(response, responses, raw_paths)
                    return normalize_cboe_option_chain(
                        ticker,
                        response.payload,
                        filters=filters,
                        endpoint_or_file=response.cache_path or response.url or "",
                    )
                except (ProviderDataError, NormalizationError) as exc:
                    first_error = first_error or exc
                    last_error = exc
                    continue
            else:
                exc = RuntimeError(f"unsupported live options provider: {provider}")
                first_error = first_error or exc
                last_error = exc
        if last_error is not None:
            raise first_error or last_error
        raise RuntimeError("no live options providers configured")

    def _pull_alpha_vantage_chain(
        self,
        ticker: str,
        *,
        filters: OptionFilterConfig,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
    ):
        client = self._alpha_vantage(raw_cache)
        quote_response = client.fetch_global_quote(
            ticker, run_date=run_date, cache_only=self.cache_only
        )
        _record_response(quote_response, responses, raw_paths)
        quote = normalize_alpha_vantage_quote(ticker, quote_response.payload)
        options_response = client.fetch_realtime_options(
            ticker, run_date=run_date, cache_only=self.cache_only
        )
        _record_response(options_response, responses, raw_paths)
        return normalize_alpha_vantage_options_chain(
            ticker,
            options_response.payload,
            spot=quote.price,
            filters=filters,
            endpoint_or_file=options_response.cache_path or options_response.url or "",
            reference_time=generated_at,
        )

    def _price_bars(
        self,
        ticker: str,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
        issues: list[str],
    ):
        """Daily bars for realized vol and expected-move context.

        FMP leads when the symbol is covered. Twelve Data backs up FMP's free-plan symbol
        gates for the six US names verified in PA4; Alpha Vantage stays last because the
        current key refuses every function and its free daily series costs one of 25
        daily requests when it answers.
        """

        for provider in _provider_order(config, "prices"):
            if provider == "fmp":
                response = self._optional_response(
                    "FMP historical price EOD",
                    lambda: self._fmp(raw_cache).fetch_historical_price_eod(
                        ticker,
                        run_date=run_date,
                        from_date=run_date - timedelta(days=PRICE_HISTORY_DAYS),
                        to_date=run_date,
                        cache_only=self.cache_only,
                    ),
                    issues,
                )
                if response is None:
                    continue
                _record_response(response, responses, raw_paths)
                try:
                    bars = normalize_fmp_historical_price_eod(ticker, response.payload)
                except NormalizationError as exc:
                    issues.append(f"FMP historical price EOD normalization failed: {exc}")
                    continue
                if bars:
                    return bars
            elif provider == "twelve_data":
                response = self._optional_response(
                    "Twelve Data time series",
                    lambda: self._twelve_data(raw_cache).fetch_time_series(
                        ticker,
                        run_date=run_date,
                        start_date=run_date - timedelta(days=PRICE_HISTORY_DAYS),
                        end_date=run_date,
                        cache_only=self.cache_only,
                    ),
                    issues,
                )
                if response is None:
                    continue
                _record_response(response, responses, raw_paths)
                try:
                    bars = normalize_twelve_data_time_series(ticker, response.payload)
                except NormalizationError as exc:
                    issues.append(f"Twelve Data time series normalization failed: {exc}")
                    continue
                if bars:
                    return bars
            elif provider == "alpha_vantage":
                attempts = (
                    (
                        "Alpha Vantage daily",
                        lambda: self._alpha_vantage(raw_cache).fetch_daily(
                            ticker, run_date=run_date, cache_only=self.cache_only
                        ),
                        normalize_alpha_vantage_daily,
                    ),
                    (
                        "Alpha Vantage daily adjusted",
                        lambda: self._alpha_vantage(raw_cache).fetch_daily_adjusted(
                            ticker, run_date=run_date, cache_only=self.cache_only
                        ),
                        normalize_alpha_vantage_daily_adjusted,
                    ),
                )
                for label, fetch, normalizer in attempts:
                    response = self._optional_response(label, fetch, issues)
                    if response is None:
                        continue
                    _record_response(response, responses, raw_paths)
                    try:
                        bars = normalizer(ticker, response.payload)
                    except NormalizationError as exc:
                        issues.append(f"{label} normalization failed: {exc}")
                        continue
                    if bars:
                        return bars
            else:
                issues.append(_unsupported_provider_message(provider, "prices"))
        return []

    def _macro_calendar_for_run(
        self,
        *,
        config: AppConfig,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
    ) -> tuple[MacroCalendar | None, tuple[ProviderResponse, ...], tuple[str, ...]]:
        cached = self._macro_calendar.get(run_date)
        if cached is not None:
            return cached

        responses: list[ProviderResponse] = []
        issues: list[str] = []
        calendar = None
        for provider in _provider_order(config, "macro"):
            if provider == "fred":
                calendar = self._fred_macro_calendar(
                    config=config,
                    run_date=run_date,
                    generated_at=generated_at,
                    raw_cache=raw_cache,
                    responses=responses,
                    issues=issues,
                )
                if calendar is not None:
                    break
                continue
            if provider != "fmp":
                issues.append(_unsupported_provider_message(provider, "macro calendar"))
                continue
            response = self._optional_response(
                "FMP economic calendar",
                lambda: self._fmp(raw_cache).fetch_economic_calendar(
                    run_date=run_date, cache_only=self.cache_only
                ),
                issues,
            )
            if response is None:
                continue
            responses.append(response)
            try:
                calendar = normalize_fmp_economic_calendar(
                    response.payload,
                    as_of=generated_at,
                    requested_start=run_date - timedelta(days=45),
                    requested_end=run_date + timedelta(days=30),
                    endpoint_or_file=response.cache_path or response.url or "",
                )
            except NormalizationError as exc:
                issues.append(f"FMP economic calendar normalization failed: {exc}")
                continue
            break
        result = (calendar, tuple(responses), tuple(issues))
        self._macro_calendar[run_date] = result
        return result

    def _fred_macro_calendar(
        self,
        *,
        config: AppConfig,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        issues: list[str],
    ) -> MacroCalendar | None:
        """Scheduled US macro releases for the calendar horizon, from FRED.

        This is the row of the coverage matrix that never had a source: FMP's
        `economic-calendar` answers 402 on a free plan, so until now the only dated macro
        events in the briefing were whatever a manual catalyst declared.

        FRED does not sell a calendar either - it publishes each *release's* schedule - so
        the join is the same one the ageing fix already makes: declared factor -> series
        -> `series/release` -> `release/dates`, this time asked forward instead of back.
        What comes back is a date and a name with no consensus estimate, which is enough
        for event risk and the calendar table and not enough for surprise scoring; the
        readings path already covers the scoring half.

        `None` rather than an empty calendar when no release answered, so the provider
        chain falls through to FMP instead of recording "nothing is scheduled".
        """

        releases = self._fred_series_releases(
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
            responses=responses,
            issues=issues,
        )
        if not releases:
            return None

        client = self._fred(raw_cache)
        window_end = run_date + timedelta(days=config.components.catalyst_calendar_days)
        events: list[MacroEvent] = []
        answered = False
        seen: set[str] = set()
        for release_id, release_name in releases.values():
            if release_id in seen:
                continue
            seen.add(release_id)
            response = self._optional_response(
                f"FRED upcoming release dates for release {release_id}",
                lambda rid=release_id: client.fetch_release_dates(
                    rid,
                    run_date=run_date,
                    start=run_date,
                    end=window_end,
                    window="upcoming",
                    # A monthly release with no date this month answers with an empty
                    # list. That is the calendar's answer, not a failed call.
                    allow_empty=True,
                    cache_only=self.cache_only,
                ),
                issues,
            )
            if response is None:
                continue
            responses.append(response)
            try:
                events.extend(
                    normalize_fred_release_dates(
                        response.payload, release_name=release_name
                    )
                )
            except NormalizationError as exc:
                issues.append(
                    f"FRED release {release_id} upcoming dates normalization failed: {exc}"
                )
                continue
            answered = True

        if not answered:
            return None
        return build_fred_macro_calendar(
            events,
            as_of=generated_at,
            requested_start=run_date,
            requested_end=window_end,
            endpoint_or_file=_endpoint_group(responses, {"release_dates"}),
        )

    def _macro_readings_for_run(
        self,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
    ) -> tuple[tuple[MacroReading, ...], tuple[ProviderResponse, ...], tuple[str, ...]]:
        """Factor trends from released macro series.

        The dated economic calendar with consensus estimates is a paid endpoint. Released
        indicator levels are not, and a release-over-release change on a factor's own
        scale is still a sourced, dated reading — so `S_M` scores on a free plan instead
        of degrading to `n/a` for every name.

        Fetched once per run date and shared across tickers; macro is not per-ticker.
        """

        cached = self._macro_readings.get(run_date)
        if cached is not None:
            return cached

        readings: list[MacroReading] = []
        responses: list[ProviderResponse] = []
        issues: list[str] = []

        wanted = _declared_macro_factors(config)
        for provider in _provider_order(config, "macro"):
            if provider == "fred":
                fred_readings, fred_responses = self._fred_macro_readings(
                    config=config,
                    wanted=wanted,
                    run_date=run_date,
                    raw_cache=raw_cache,
                    issues=issues,
                )
                responses.extend(fred_responses)
                if fred_readings:
                    readings.extend(fred_readings)
                    break
                continue
            if provider != "fmp":
                issues.append(_unsupported_provider_message(provider, "macro readings"))
                continue
            for factor, indicator in FMP_MACRO_INDICATORS.items():
                if factor not in wanted:
                    continue
                response = self._optional_response(
                    f"FMP economic indicator {indicator}",
                    lambda indicator=indicator: self._fmp(raw_cache).fetch_economic_indicator(
                        indicator, run_date=run_date, cache_only=self.cache_only
                    ),
                    issues,
                )
                if response is None:
                    continue
                responses.append(response)
                try:
                    events = normalize_fmp_economic_indicators(
                        response.payload, indicator=indicator
                    )
                except NormalizationError as exc:
                    issues.append(
                        f"FMP economic indicator {indicator} normalization failed: {exc}"
                    )
                    continue
                reading = release_change_reading(events, factor=factor, run_date=run_date)
                if reading is not None:
                    readings.append(reading)

            treasury = (
                self._optional_response(
                    "FMP treasury rates",
                    lambda: self._fmp(raw_cache).fetch_treasury_rates(
                        run_date=run_date,
                        from_date=run_date - timedelta(days=TREASURY_HISTORY_DAYS),
                        to_date=run_date,
                        cache_only=self.cache_only,
                    ),
                    issues,
                )
                if wanted & TREASURY_FACTORS
                else None
            )
            if treasury is not None:
                responses.append(treasury)
                try:
                    series = normalize_fmp_treasury_rates(treasury.payload)
                except NormalizationError as exc:
                    issues.append(f"FMP treasury rates normalization failed: {exc}")
                else:
                    for factor, events in series.items():
                        if factor not in wanted:
                            continue
                        reading = release_change_reading(
                            events, factor=factor, run_date=run_date
                        )
                        if reading is not None:
                            readings.append(reading)
            if readings:
                break

        result = (tuple(readings), tuple(responses), tuple(issues))
        self._macro_readings[run_date] = result
        return result

    def _catalyst_calendar(
        self,
        ticker: str,
        *,
        config: AppConfig,
        run_date: date_type,
        generated_at: datetime,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
        issues: list[str],
    ) -> CatalystCalendar | None:
        for provider in _provider_order(config, "earnings"):
            if provider == "alpha_vantage":
                response = self._optional_response(
                    "Alpha Vantage earnings calendar",
                    lambda: self._alpha_vantage(raw_cache).fetch_earnings_calendar(
                        ticker, run_date=run_date, cache_only=self.cache_only
                    ),
                    issues,
                )
                if response is None:
                    continue
                _record_response(response, responses, raw_paths)
                try:
                    return normalize_alpha_vantage_earnings_calendar_csv(
                        ticker,
                        response.payload,
                        as_of=generated_at,
                        requested_start=run_date,
                        requested_end=run_date + timedelta(days=90),
                        endpoint_or_file=response.cache_path or response.url or "",
                    )
                except NormalizationError as exc:
                    issues.append(f"Alpha Vantage earnings normalization failed: {exc}")
            elif provider == "fmp":
                response = self._optional_response(
                    "FMP earnings calendar",
                    lambda: self._fmp(raw_cache).fetch_earnings_calendar(
                        ticker,
                        run_date=run_date,
                        from_date=run_date,
                        to_date=run_date + timedelta(days=90),
                        cache_only=self.cache_only,
                    ),
                    issues,
                )
                if response is None:
                    continue
                _record_response(response, responses, raw_paths)
                try:
                    return normalize_fmp_earnings_calendar(
                        ticker,
                        response.payload,
                        as_of=generated_at,
                        requested_start=run_date,
                        requested_end=run_date + timedelta(days=90),
                        endpoint_or_file=response.cache_path or response.url or "",
                    )
                except NormalizationError as exc:
                    issues.append(f"FMP earnings normalization failed: {exc}")
            else:
                issues.append(_unsupported_provider_message(provider, "earnings"))
        return None

    def _news_batch(
        self,
        ticker: str,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
        issues: list[str],
    ) -> NewsSentimentBatch | None:
        last_batch: NewsSentimentBatch | None = None
        for provider in _provider_order(config, "news"):
            if provider == "alpha_vantage":
                response = self._optional_response(
                    "Alpha Vantage news sentiment",
                    lambda: self._alpha_vantage(raw_cache).fetch_news_sentiment(
                        ticker, run_date=run_date, cache_only=self.cache_only
                    ),
                    issues,
                )
                if response is None:
                    continue
                _record_response(response, responses, raw_paths)
                try:
                    last_batch = normalize_alpha_vantage_news_sentiment(
                        ticker, response.payload
                    )
                except NormalizationError as exc:
                    issues.append(f"Alpha Vantage news normalization failed: {exc}")
                    continue
            elif provider == "fmp":
                response = self._optional_response(
                    "FMP stock news",
                    lambda: self._fmp(raw_cache).fetch_stock_news(
                        ticker, run_date=run_date, cache_only=self.cache_only
                    ),
                    issues,
                )
                if response is None:
                    continue
                _record_response(response, responses, raw_paths)
                try:
                    last_batch = normalize_fmp_stock_news(ticker, response.payload)
                except NormalizationError as exc:
                    issues.append(f"FMP stock news normalization failed: {exc}")
                    continue
            elif provider == "finnhub":
                try:
                    last_batch = self._finnhub_news_batch(
                        ticker,
                        run_date=run_date,
                        raw_cache=raw_cache,
                        responses=responses,
                        raw_paths=raw_paths,
                    )
                except ProviderDataError as exc:
                    issues.append(_provider_error_message("Finnhub company news", exc))
                    continue
            else:
                issues.append(_unsupported_provider_message(provider, "news"))
                continue
            if last_batch is not None and last_batch.articles:
                return last_batch
        return last_batch

    def _finnhub_news_batch(
        self,
        ticker: str,
        *,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
    ) -> NewsSentimentBatch | None:
        """Finnhub company news, with tone derived locally by the normalizer.

        Raises rather than returning `None` on a failure so the caller records which
        provider refused and why before it falls through the chain — a silent `None`
        would read as "no news", which is a different claim.
        """

        response = self._finnhub(raw_cache).fetch_company_news(
            ticker, run_date=run_date, cache_only=self.cache_only
        )
        _record_response(response, responses, raw_paths)
        try:
            return normalize_finnhub_company_news(ticker, response.payload)
        except NormalizationError as exc:
            raise ProviderDataError(
                "finnhub",
                "company_news",
                MALFORMED,
                (f"Finnhub news normalization failed: {exc}",),
            ) from exc

    def _political_trades_for_run(
        self,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
    ) -> tuple[tuple[PoliticalTrade, ...], tuple[ProviderResponse, ...], tuple[str, ...]]:
        cached = self._political_trades.get(run_date)
        if cached is not None:
            return cached

        trades: list[PoliticalTrade] = []
        responses: list[ProviderResponse] = []
        issues: list[str] = []
        for provider in _provider_order(config, "political"):
            if provider != "fmp":
                issues.append(_unsupported_provider_message(provider, "political"))
                continue

            client = self._fmp(raw_cache)
            attempts = (
                (
                    "FMP senate latest",
                    "senate",
                    lambda: client.fetch_senate_latest(
                        run_date=run_date, cache_only=self.cache_only
                    ),
                ),
                (
                    "FMP house latest",
                    "house",
                    lambda: client.fetch_house_latest(
                        run_date=run_date, cache_only=self.cache_only
                    ),
                ),
            )
            for label, chamber, fetch in attempts:
                response = self._optional_response(label, fetch, issues)
                if response is None:
                    continue
                responses.append(response)
                try:
                    trades.extend(
                        normalize_fmp_congress_trades(response.payload, chamber=chamber)
                    )
                except NormalizationError as exc:
                    issues.append(f"{label} normalization failed: {exc}")
            if trades:
                break

        trades.extend(_cached_fmp_political_trades(raw_cache, run_date=run_date, issues=issues))
        trades = _dedupe_political_trades(trades)
        result = (tuple(trades), tuple(responses), tuple(issues))
        self._political_trades[run_date] = result
        return result

    def _retail_momentum_for_run(
        self,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
    ) -> tuple[dict[str, RetailMomentumSnapshot], tuple[ProviderResponse, ...], tuple[str, ...]]:
        cached = self._retail_momentum.get(run_date)
        if cached is not None:
            return cached

        snapshots: dict[str, RetailMomentumSnapshot] = {}
        responses: list[ProviderResponse] = []
        issues: list[str] = []
        for provider in _provider_order(config, "retail"):
            if provider != "apewisdom":
                issues.append(_unsupported_provider_message(provider, "retail"))
                continue

            response = self._optional_response(
                "ApeWisdom retail momentum",
                lambda: self._apewisdom(raw_cache).fetch_all_stocks(
                    run_date=run_date, cache_only=self.cache_only
                ),
                issues,
            )
            if response is None:
                continue
            responses.append(response)
            try:
                rows = normalize_apewisdom_retail_momentum(
                    response.payload, as_of=run_date
                )
            except NormalizationError as exc:
                issues.append(f"ApeWisdom retail momentum normalization failed: {exc}")
                continue
            snapshots = {row.ticker: row for row in rows}
            if snapshots:
                break

        result = (snapshots, tuple(responses), tuple(issues))
        self._retail_momentum[run_date] = result
        return result

    def _analyst_signals(
        self,
        ticker: str,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
        issues: list[str],
    ) -> list[AnalystSignal]:
        """Analyst signals from FMP's consensus endpoints, with Finnhub behind them.

        FMP's dated per-firm ratings feed is plan-gated, so the grade consensus and the
        consensus price target are collected together: both are free, and each carries a
        different half of the signal.

        Finnhub is a fallback, not a merge. It reports the same buy/hold/sell counts, so
        running both would double-weight one quarter's consensus by counting it twice
        under two labels. It only answers when FMP produced nothing — which is the whole
        point of the second feed, since this leg carried all of `S_S` on its own. It
        cannot cover EU names: the free tier is US-only, so those stay sole-sourced.
        """

        for provider in _provider_order(config, "analyst"):
            if provider not in {"fmp", "finnhub"}:
                issues.append(_unsupported_provider_message(provider, "analyst"))
                continue
            signals: list[AnalystSignal] = []
            attempts: tuple[tuple[str, Any, Any], ...]
            if provider == "finnhub":
                attempts = (
                    (
                        "Finnhub recommendation trends",
                        lambda: self._finnhub(raw_cache).fetch_recommendation_trends(
                            ticker, run_date=run_date, cache_only=self.cache_only
                        ),
                        normalize_finnhub_recommendation_trends,
                    ),
                )
            else:
                attempts = (
                    (
                        "FMP grades consensus",
                        lambda: self._fmp(raw_cache).fetch_analyst_ratings(
                            ticker, run_date=run_date, cache_only=self.cache_only
                        ),
                        normalize_fmp_grades_consensus,
                    ),
                    (
                        "FMP price target consensus",
                        lambda: self._fmp(raw_cache).fetch_price_target_consensus(
                            ticker, run_date=run_date, cache_only=self.cache_only
                        ),
                        normalize_fmp_price_target_consensus,
                    ),
                )
            for label, fetch, normalizer in attempts:
                response = self._optional_response(label, fetch, issues)
                if response is None:
                    continue
                _record_response(response, responses, raw_paths)
                try:
                    signals.extend(normalizer(ticker, response.payload))
                except NormalizationError as exc:
                    issues.append(f"{label} normalization failed: {exc}")
            if signals:
                return signals
        return []

    def _fred_series_releases(
        self,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        issues: list[str],
    ) -> dict[str, tuple[str, str]]:
        """Which release publishes each declared macro series, as (id, name).

        The same join answers two questions - which past publication carried a reading,
        and what is scheduled next - so it is resolved once per run date and shared by the
        readings path and the calendar. The eight adopted series map onto six releases,
        since the whole Treasury curve comes from H.15.

        Only the first caller is handed the responses. Both consumers are memoised per run
        date and both record what they are given into the evidence ledger, so returning
        them twice would enter each `series/release` request in the ledger twice.
        """

        cached = self._fred_series_releases_by_run.get(run_date)
        if cached is not None:
            return cached

        client = self._fred(raw_cache)
        wanted = _declared_macro_factors(config)
        releases: dict[str, tuple[str, str]] = {}
        for factor, series_id in FRED_MACRO_SERIES.items():
            if factor not in wanted or series_id in releases:
                continue
            response = self._optional_response(
                f"FRED series release for {series_id}",
                lambda s=series_id: client.fetch_series_release(
                    s, run_date=run_date, cache_only=self.cache_only
                ),
                issues,
            )
            if response is None:
                continue
            responses.append(response)
            entries = (response.payload or {}).get("releases") or []
            entry = entries[0] if entries else {}
            release_id = str((entry or {}).get("id") or "")
            if not release_id:
                issues.append(f"FRED series {series_id} reported no release id")
                continue
            name = str((entry or {}).get("name") or "").strip() or f"FRED release {release_id}"
            releases[series_id] = (release_id, name)

        self._fred_series_releases_by_run[run_date] = releases
        return releases

    def _fred_release_dates(
        self,
        series_id: str,
        *,
        client: FredClient,
        run_date: date_type,
        releases: Mapping[str, tuple[str, str]],
        dates_by_release: dict[str, list[date_type]],
        responses: list[ProviderResponse],
        issues: list[str],
    ) -> list[date_type]:
        """Past publication dates for the release that carries a series.

        One request the first time a release is seen, then reused. An empty list is a
        valid answer - the caller then ages that series from its period, which is the
        previous behaviour rather than a failure.

        The window stops at the run date on purpose. A future date reached back into
        `normalize_fred_series_observations` would stamp an already-published reading with
        a release that has not happened yet, and a negative age never reads as stale.
        """

        resolved = releases.get(series_id)
        if resolved is None:
            return []
        release_id = resolved[0]

        if release_id in dates_by_release:
            return dates_by_release[release_id]

        dates_response = self._optional_response(
            f"FRED release dates for release {release_id}",
            lambda: client.fetch_release_dates(
                release_id,
                run_date=run_date,
                start=run_date - timedelta(days=MACRO_HISTORY_DAYS),
                end=run_date,
                cache_only=self.cache_only,
            ),
            issues,
        )
        if dates_response is None:
            dates_by_release[release_id] = []
            return []
        responses.append(dates_response)
        try:
            events = normalize_fred_release_dates(dates_response.payload)
        except NormalizationError as exc:
            issues.append(f"FRED release {release_id} dates normalization failed: {exc}")
            dates_by_release[release_id] = []
            return []
        dates_by_release[release_id] = [event.event_date.date() for event in events]
        return dates_by_release[release_id]

    def _fred_macro_readings(
        self,
        *,
        config: AppConfig,
        wanted: set[str],
        run_date: date_type,
        raw_cache: RawCache,
        issues: list[str],
    ) -> tuple[list[MacroReading], list[ProviderResponse]]:
        """Macro readings from FRED, one request per declared factor.

        FRED is the primary publisher rather than an aggregator, which is the point of
        leading with it. `inflation` is requested with `units=pc1` so the year-over-year
        rate comes from FRED rather than being derived here from the CPI index.
        """

        readings: list[MacroReading] = []
        responses: list[ProviderResponse] = []
        client = self._fred(raw_cache)
        start = run_date - timedelta(days=MACRO_HISTORY_DAYS)
        releases = self._fred_series_releases(
            config=config,
            run_date=run_date,
            raw_cache=raw_cache,
            responses=responses,
            issues=issues,
        )
        release_dates_by_series: dict[str, list[date_type]] = {}
        dates_by_release: dict[str, list[date_type]] = {}

        for factor, series_id in FRED_MACRO_SERIES.items():
            if factor not in wanted:
                continue
            units = "pc1" if factor in FRED_PERCENT_CHANGE_FACTORS else None
            if series_id not in release_dates_by_series:
                release_dates_by_series[series_id] = self._fred_release_dates(
                    series_id,
                    client=client,
                    run_date=run_date,
                    releases=releases,
                    dates_by_release=dates_by_release,
                    responses=responses,
                    issues=issues,
                )
            response = self._optional_response(
                f"FRED series {series_id}" + (f" ({units})" if units else ""),
                lambda s=series_id, u=units: client.fetch_series_observations(
                    s,
                    run_date=run_date,
                    observation_start=start,
                    units=u,
                    cache_only=self.cache_only,
                ),
                issues,
            )
            if response is None:
                continue
            responses.append(response)
            try:
                events = normalize_fred_series_observations(
                    response.payload,
                    series_id=series_id,
                    release_dates=release_dates_by_series.get(series_id),
                )
            except NormalizationError as exc:
                issues.append(f"FRED series {series_id} normalization failed: {exc}")
                continue
            reading = release_change_reading(events, factor=factor, run_date=run_date)
            if reading is not None:
                readings.append(reading)
        return readings, responses

    def _stored_option_series(
        self,
        ticker: str,
        *,
        run_date: date_type,
        repository: "StorageRepository | None",
        issues: list[str],
    ) -> tuple[list[float], list[float], list[float]]:
        """Trailing ATM IV and put/call ratios built from this app's own snapshots.

        No vendor sells this: the pipeline already persists `iv_atm`, `pc_ratio_vol` and
        `pc_ratio_oi` to `daily_snapshot` every run, so the baselines the `iv_extreme` and
        `put_call` legs need are a query away rather than a subscription.

        The cost is a warm-up. Until `SELF_BUILT_SERIES_MIN_SESSIONS` sessions are stored
        the series is withheld and the reason is recorded, because a percentile over three
        points would read as a rank while meaning nothing.
        """

        if repository is None:
            issues.append(
                "self-built IV and put/call baselines need persistence; "
                "no database is configured for this run"
            )
            return [], [], []

        rows = repository.option_metric_history(ticker, before_date=run_date)
        iv_history = [
            float(row["iv_atm"]) for row in rows if row.get("iv_atm") is not None
        ]
        pc_vol_history = [
            float(row["pc_ratio_vol"]) for row in rows if row.get("pc_ratio_vol") is not None
        ]
        pc_oi_history = [
            float(row["pc_ratio_oi"]) for row in rows if row.get("pc_ratio_oi") is not None
        ]

        withheld: list[float] = []
        result = []
        for name, series in (
            ("iv_rank", iv_history),
            ("put/call volume percentile", pc_vol_history),
            ("put/call open-interest percentile", pc_oi_history),
        ):
            if len(series) < SELF_BUILT_SERIES_MIN_SESSIONS:
                issues.append(
                    f"{name} baseline still building: {len(series)} of "
                    f"{SELF_BUILT_SERIES_MIN_SESSIONS} sessions stored"
                )
                result.append(withheld)
            else:
                result.append(series)
        return result[0], result[1], result[2]

    def _short_borrow(
        self,
        ticker: str,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
        issues: list[str],
    ) -> ShortBorrowSnapshot | None:
        """Short/borrow inputs for the `short_borrow` leg of S_O.

        FINRA's consolidated file carries daily short **volume** only, so the snapshot it
        produces sets `short_volume_ratio` and leaves short interest, days-to-cover and
        borrow fee `None`. Those three have no free source; see
        `docs/alternatives/pa1-borrow.md`.
        """

        for provider in _provider_order(config, "short_interest"):
            if provider != "finra":
                issues.append(_unsupported_provider_message(provider, "short_interest"))
                continue
            snapshot = self._finra_short_volume(
                ticker,
                run_date=run_date,
                raw_cache=raw_cache,
                responses=responses,
                raw_paths=raw_paths,
                issues=issues,
            )
            if snapshot is not None:
                return snapshot
        return None

    def _finra_short_volume(
        self,
        ticker: str,
        *,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
        issues: list[str],
    ) -> ShortBorrowSnapshot | None:
        # The consolidated file lands T+1, so the most recent weekday is routinely a 404
        # rather than an outage. Walk back the same way preflight does.
        trade_date = _previous_business_day(run_date)
        for _ in range(FINRA_LOOKBACK_SESSIONS):
            response = self._optional_response(
                f"FINRA short sale volume {trade_date.isoformat()}",
                lambda day=trade_date: self._finra(raw_cache).fetch_short_sale_volume(
                    day, run_date=run_date, cache_only=self.cache_only
                ),
                issues,
            )
            if response is not None:
                _record_response(response, responses, raw_paths)
                try:
                    rows = normalize_finra_short_volume(response.payload)
                except NormalizationError as exc:
                    issues.append(f"finra short volume normalization failed: {exc}")
                    return None
                return _short_borrow_from_finra(ticker, rows)
            trade_date = _previous_business_day(trade_date)
        return None

    def _sec_edgar_insider(
        self,
        ticker: str,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
        issues: list[str],
    ) -> list[InsiderTransaction]:
        """Form 4 transactions straight from the primary record.

        EDGAR indexes filings but not their contents, so each Form 4 body is a separate
        fetch. The window and the filing cap keep that bounded: an active large-cap files
        far more Form 4s in 90 days than the insider component needs, and EDGAR asks for
        modest request rates.
        """

        window_start = run_date - timedelta(days=config.components.insider_window_days)
        client = self._sec_edgar(raw_cache)
        try:
            filings = client.get_recent_filings(
                ticker, run_date=run_date, forms={"4"}, cache_only=self.cache_only
            )
        except ProviderDataError as exc:
            issues.append(_provider_error_message("SEC EDGAR Form 4 index", exc))
            return []

        recent = [
            filing
            for filing in filings
            if filing.filed_at >= window_start and filing.accession_number
        ][:EDGAR_FORM4_MAX_FILINGS]

        transactions: list[InsiderTransaction] = []
        for filing in recent:
            document = _edgar_raw_document(filing.primary_document)
            if not document or not filing.cik:
                continue
            response = self._optional_response(
                f"SEC EDGAR Form 4 {filing.accession_number}",
                lambda f=filing, d=document: client.fetch_filing_document(
                    f.cik, f.accession_number, d, run_date=run_date, cache_only=self.cache_only
                ),
                issues,
            )
            if response is None:
                continue
            _record_response(response, responses, raw_paths)
            try:
                transactions.extend(
                    normalize_sec_form4_ownership_document(
                        ticker,
                        response.payload,
                        filing_date=filing.filed_at,
                        accession_number=filing.accession_number,
                        primary_document=document,
                    )
                )
            except NormalizationError as exc:
                issues.append(
                    f"sec_edgar Form 4 {filing.accession_number} normalization failed: {exc}"
                )
        return transactions

    def _insider_transactions(
        self,
        ticker: str,
        *,
        config: AppConfig,
        run_date: date_type,
        raw_cache: RawCache,
        responses: list[ProviderResponse],
        raw_paths: list[Path],
        issues: list[str],
    ) -> list[InsiderTransaction]:
        for provider in _provider_order(config, "insider"):
            if provider == "sec_edgar":
                transactions = self._sec_edgar_insider(
                    ticker,
                    config=config,
                    run_date=run_date,
                    raw_cache=raw_cache,
                    responses=responses,
                    raw_paths=raw_paths,
                    issues=issues,
                )
                if transactions:
                    return transactions
                continue
            if provider == "alpha_vantage":
                response = self._optional_response(
                    "Alpha Vantage insider transactions",
                    lambda: self._alpha_vantage(raw_cache).fetch_insider_transactions(
                        ticker, run_date=run_date, cache_only=self.cache_only
                    ),
                    issues,
                )
                normalizer = normalize_alpha_vantage_insider_transactions
            elif provider == "fmp":
                response = self._optional_response(
                    "FMP insider trades",
                    lambda: self._fmp(raw_cache).fetch_insider_trades(
                        ticker, run_date=run_date, cache_only=self.cache_only
                    ),
                    issues,
                )
                normalizer = normalize_fmp_insider_trades
            else:
                issues.append(_unsupported_provider_message(provider, "insider"))
                continue
            if response is None:
                continue
            _record_response(response, responses, raw_paths)
            try:
                transactions = normalizer(ticker, response.payload)
            except NormalizationError as exc:
                issues.append(f"{provider} insider normalization failed: {exc}")
                continue
            if transactions:
                return transactions
        return []

    def _optional_response(
        self,
        label: str,
        fetch: Any,
        issues: list[str],
    ) -> ProviderResponse | None:
        try:
            return fetch()
        except ProviderDataError as exc:
            issues.append(_provider_error_message(label, exc))
            return None

    def _cboe(self, raw_cache: RawCache) -> CboeOptionsClient:
        return CboeOptionsClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )

    def _fred(self, raw_cache: RawCache) -> FredClient:
        return FredClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )

    def _finra(self, raw_cache: RawCache) -> FinraClient:
        return FinraClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )

    def _sec_edgar(self, raw_cache: RawCache) -> SecEdgarClient:
        return SecEdgarClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )

    def _alpha_vantage(self, raw_cache: RawCache) -> AlphaVantageClient:
        return AlphaVantageClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )

    def _apewisdom(self, raw_cache: RawCache) -> ApeWisdomClient:
        return ApeWisdomClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )

    def _finnhub(self, raw_cache: RawCache) -> FinnhubClient:
        return FinnhubClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )

    def _fmp(self, raw_cache: RawCache) -> FmpClient:
        return FmpClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )

    def _twelve_data(self, raw_cache: RawCache) -> TwelveDataClient:
        return TwelveDataClient(
            settings=self.settings,
            cache=raw_cache,
            fetcher=self.fetcher,
            budget=self._budget,
        )


def _as_synthetic(component: ComponentResult) -> ComponentResult:
    """Re-label a component computed from fixture payloads, itself and every row it emits.

    The component builders mark a fully-measured component `verified`, which is true of the
    arithmetic and false of the inputs. Scoring already reads `synthetic` as unverifiable,
    so this is what keeps a fixture run off the tradeable path.
    """

    return replace(
        component,
        validation_status=STATUS_SYNTHETIC,
        evidence_rows=tuple(
            {**row, "validation_status": STATUS_SYNTHETIC} for row in component.evidence_rows
        ),
    )


def _declared_unavailable_component(
    component: str,
    *,
    ticker: str,
    geography: Geography,
    as_of: datetime,
) -> ComponentResult:
    """An `n/a` component carrying the decision that made it so, not a fetch that failed.

    Both run modes build it the same way, so fixture and live report the same reason and a
    fixture run cannot rehearse a component the live run declines to compute.
    """

    return unavailable_component(
        component=component,
        ticker=ticker,
        geography=geography,
        as_of=as_of,
        reason=DECLARED_UNSCORABLE_COMPONENTS[component],
    )


def _refuse_fabricated_legs(ticker: str, data: TickerData) -> None:
    """Fail a fixture pull that scored a leg the live path cannot score.

    Checked on the built result rather than on the inputs, so a leg cannot reach a score
    through a route this guard does not know about. A fixture run is only worth reading as
    a rehearsal of the live run, and a leg live has no source for makes it something else.

    A declared-unscorable *component* is the same failure one level up: the live path will
    not compute it whatever a provider returns, so a fixture score for it is fiction too.
    """

    scored = [name for name in data.option_structure.sub_scores if name in LIVE_UNSCORABLE_LEGS]
    scored.extend(
        sub.name
        for component in data.components
        for sub in component.sub_scores
        if sub.available and sub.name in LIVE_UNSCORABLE_LEGS
    )
    if data.risk_reversal_history:
        scored.append("risk_reversal_history")

    declared = [
        component.component
        for component in data.components
        if component.available and component.component in DECLARED_UNSCORABLE_COMPONENTS
    ]
    if declared:
        detail = "; ".join(
            f"{name}: {DECLARED_UNSCORABLE_COMPONENTS[name]}" for name in sorted(set(declared))
        )
        raise FixtureFabricationError(
            f"{ticker} fixture data scored {len(set(declared))} component(s) this project "
            f"has declared permanently n/a ({detail}). Leave the component n/a in fixture "
            "mode, or reverse the decision first."
        )

    if not scored:
        return
    detail = "; ".join(f"{leg}: {LIVE_UNSCORABLE_LEGS[leg]}" for leg in sorted(set(scored)))
    raise FixtureFabricationError(
        f"{ticker} fixture data scored {len(set(scored))} leg(s) the live path cannot score "
        f"({detail}). Leave the leg n/a in fixture mode, or wire a live source for it first."
    )


def _data_source_for_mode(data_mode: DataMode) -> PipelineDataSource:
    if data_mode == "fixture":
        return FixtureDataSource()
    if data_mode == "live":
        return LiveDataSource()
    raise ValueError(f"unsupported pipeline data mode: {data_mode}")


def _repository_from_env() -> StorageRepository | None:
    if not os.getenv("DATABASE_URL"):
        return None
    return StorageRepository.from_env()


def _final_status(output: PipelineRunOutput) -> str:
    if output.failures or output.diagnostics:
        return STATUS_PARTIAL
    return STATUS_SUCCEEDED


def _finish_output(
    output: PipelineRunOutput,
    repo: StorageRepository | None,
    output_root: Path,
    data_root: Path,
    *,
    persist: bool,
) -> PipelineRunOutput:
    output.finished_at = datetime.now(UTC)
    if persist:
        output.status_path = _status_file_path(output, data_root)
        _write_status_file(output, output.status_path)
    if repo is not None and persist and output.storage_run_id is not None:
        repo.finish_briefing_run(
            output.storage_run_id,
            status=output.status,
            finished_at=output.finished_at,
            output_html_path=str(output.html_path) if output.html_path else None,
            output_json_path=str(output.json_path) if output.json_path else None,
            error={"failures": [f.to_dict() for f in output.failures]}
            if output.status == STATUS_FAILED
            else None,
            details={
                "pipeline_run_id": output.run_id,
                "data_mode": output.data_mode,
                "diagnostics": output.diagnostics,
                "failures": [failure.to_dict() for failure in output.failures],
                "status_path": str(output.status_path) if output.status_path else None,
            },
        )
    return output


def _status_file_path(output: PipelineRunOutput, data_root: Path) -> Path:
    return data_root / "runs" / output.run_date.isoformat() / f"{output.run_id}.json"


def _write_status_file(output: PipelineRunOutput, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_gate_markdown(gate_report: Any, output_root: Path, run_date: date_type) -> Path:
    path = output_root / "candidate_gate" / run_date.isoformat() / "candidate_gate.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_gate_markdown(gate_report), encoding="utf-8")
    return path


def _candidate_gate_rows(gate_report: Any, run_id: int | None) -> list[dict[str, Any]]:
    from briefing_app.models.gate import to_candidate_gate_rows

    return [dict(row, run_id=run_id) for row in to_candidate_gate_rows(gate_report, run_id=run_id)]


def _with_run_id(
    rows: Sequence[Mapping[str, Any]], run_id: int | None
) -> list[dict[str, Any]]:
    return [{**dict(row), "run_id": run_id} for row in rows]


def _json_field_safe_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(row)
    for key in ("component_scores", "details", "raw", "scenario_probabilities"):
        if key in values:
            values[key] = json.loads(json.dumps(values[key], default=str))
    return values


def _evidence_row(
    *,
    run_id: int | None,
    ticker: str,
    component: str,
    field_name: str,
    field_value: Any,
    source: str,
    as_of: datetime,
    endpoint_or_file: str,
    validation_status: str = "verified",
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "ticker": ticker,
        "component": component,
        "field_name": field_name,
        "field_value": str(field_value),
        "source": source,
        "venue": "*",
        "as_of": as_of,
        "endpoint_or_file": endpoint_or_file,
        "validation_status": validation_status,
        "note": note,
    }


def _live_preflight_row(
    *,
    run_id: int | None,
    provider: str,
    endpoint: str,
    target: str,
    component: str,
    status: str,
    entitlement: str,
    checked_at: datetime,
    run_date: date_type,
    note: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "source": provider,
        "endpoint": endpoint,
        "target": target,
        "status": status,
        "entitlement_status": entitlement,
        "venue": "*",
        "checked_at": checked_at,
        "as_of": None,
        "validation_status": status,
        "note": note,
        "details": {"run_date": run_date.isoformat(), "data_mode": "live"},
    }


def _provider_response_evidence(
    response: ProviderResponse,
    *,
    run_id: int | None,
    component: str | None = None,
    field_name: str = "provider_status",
) -> dict[str, Any]:
    status = response.validation.status or OK
    note = "; ".join(response.validation.notes) if response.validation.notes else None
    return {
        "run_id": run_id,
        "ticker": response.target,
        "component": component or _component_for_endpoint(response.endpoint),
        "field_name": f"{response.provider}_{response.endpoint}_{field_name}",
        "field_value": status,
        "source": response.provider,
        "venue": "*",
        "as_of": response.fetched_at,
        "endpoint_or_file": response.cache_path or response.url or "",
        "validation_status": status,
        "note": note,
    }


def _provider_issue_evidence(
    issue: str,
    *,
    run_id: int | None,
    ticker: str,
    as_of: datetime,
) -> dict[str, Any]:
    return _evidence_row(
        run_id=run_id,
        ticker=ticker,
        component="RAW",
        field_name="live_provider_issue",
        field_value=issue,
        source="live providers",
        as_of=as_of,
        endpoint_or_file="",
        validation_status=STATUS_UNAVAILABLE,
        note=issue,
    )


def _provider_error_message(label: str, exc: ProviderDataError) -> str:
    notes = "; ".join(exc.notes)
    suffix = f": {notes}" if notes else ""
    return f"{label} unavailable ({exc.status}){suffix}"


def _record_response(
    response: ProviderResponse,
    responses: list[ProviderResponse],
    raw_paths: list[Path],
) -> None:
    responses.append(response)
    if response.cache_path:
        raw_paths.append(Path(response.cache_path))


def _endpoint_group(
    responses: Sequence[ProviderResponse],
    endpoints: set[str],
) -> str:
    paths = [
        response.cache_path or response.url or ""
        for response in responses
        if response.endpoint in endpoints and (response.cache_path or response.url)
    ]
    return "; ".join(paths)


def _cached_fmp_political_trades(
    raw_cache: RawCache,
    *,
    run_date: date_type,
    issues: list[str],
) -> list[PoliticalTrade]:
    trades: list[PoliticalTrade] = []
    for endpoint, chamber in (
        ("senate_latest", "senate"),
        ("house_latest", "house"),
    ):
        root = raw_cache.data_dir / "raw" / "fmp" / endpoint
        if not root.exists():
            continue
        for day_dir in root.iterdir():
            if not day_dir.is_dir():
                continue
            try:
                cache_date = date_type.fromisoformat(day_dir.name)
            except ValueError:
                continue
            age = (run_date - cache_date).days
            if age <= 0 or age > POLITICAL_FLOW_WINDOW_DAYS:
                continue
            cache_path = day_dir / "all.json"
            if not cache_path.exists():
                continue
            try:
                payload = raw_cache.read_json("fmp", endpoint, cache_date, "all")
                trades.extend(normalize_fmp_congress_trades(payload, chamber=chamber))
            except (OSError, NormalizationError) as exc:
                issues.append(f"cached FMP {endpoint} {cache_date.isoformat()} ignored: {exc}")
    return trades


def _dedupe_political_trades(trades: Sequence[PoliticalTrade]) -> list[PoliticalTrade]:
    deduped: list[PoliticalTrade] = []
    seen: set[str] = set()
    for trade in trades:
        key = trade.source_url or "|".join(
            str(value or "")
            for value in (
                trade.source,
                trade.ticker,
                trade.chamber,
                trade.politician_id,
                trade.politician,
                trade.transaction_date,
                trade.transaction_type,
                trade.amount_range,
            )
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(trade)
    return deduped


def _component_for_endpoint(endpoint: str) -> str:
    mapping = {
        "delayed_options_chain": "S_O",
        "realtime_options": "S_O",
        "historical_options": "S_O",
        "realtime_put_call_ratio": "S_O",
        "daily_adjusted": "price_history",
        "time_series": "price_history",
        "global_quote": "quote",
        "news_sentiment": "S_S",
        "stock_news": "S_S",
        "company_news": "S_S",
        "recommendation_trends": "S_S",
        "senate_latest": "S_S",
        "house_latest": "S_S",
        "retail_momentum": "S_S",
        "analyst_ratings": "S_S",
        "earnings_calendar": "catalyst",
        "economics": "S_M",
        "insider_transactions": "S_I",
        "insider_trades": "S_I",
        "institutional_holdings": "S_F",
        "institutional_ownership": "S_F",
    }
    return mapping.get(endpoint, "RAW")


def _provider_order(config: AppConfig, name: str) -> tuple[str, ...]:
    return tuple(getattr(config.providers, name))


def _unsupported_provider_message(provider: str, leg: str) -> str:
    return f"{provider} is configured for {leg}, but no live provider hook is wired"


def _previous_business_day(day: date_type) -> date_type:
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def _edgar_raw_document(primary_document: str | None) -> str | None:
    """Strip EDGAR's XSL rendering prefix to reach the underlying XML.

    Submissions name a Form 4's primary document as `xslF345X06/form4.xml`, which serves
    an HTML rendering. The same accession also serves `form4.xml` - the source XML the
    normalizer parses properly, instead of falling back to scraping a rendered table.
    """

    if not primary_document:
        return None
    document = primary_document.strip()
    head, separator, tail = document.rpartition("/")
    if separator and head.lower().startswith("xsl"):
        return tail or None
    return document or None


def _short_borrow_from_finra(
    ticker: str, rows: Sequence[ShortInterestSnapshot]
) -> ShortBorrowSnapshot | None:
    """Build the S_O borrow snapshot from FINRA's consolidated daily file.

    Only `short_volume_ratio` is set. FINRA reports the share of the day's *volume* that
    printed short; short interest, days-to-cover and borrow fee are different quantities
    with no free source, and writing the volume ratio into any of their fields would read
    an ordinary tape as extreme squeeze risk.
    """

    clean = ticker.strip().upper()
    row = next((item for item in rows if (item.ticker or "").upper() == clean), None)
    if row is None or not row.total_volume or row.short_volume is None:
        return None
    return ShortBorrowSnapshot(
        verified=True,
        short_volume_ratio=row.short_volume / row.total_volume,
        source=row.source,
        as_of=row.as_of,
    )


def _option_filter_config(config: AppConfig) -> OptionFilterConfig:
    return OptionFilterConfig.model_validate(config.option_filters.model_dump())


def _chain_is_verified(chain: Any) -> bool:
    return (
        getattr(chain, "validation_status", None) is ValidationStatus.VERIFIED
        and bool(getattr(chain, "contracts", ()))
    )


def _declared_macro_factors(config: AppConfig) -> set[str]:
    """Every macro factor some sector declares a sensitivity to.

    A factor no sector is sensitive to cannot move any score, so it is never fetched.
    """

    return {
        factor
        for exposure in config.components.sector_exposures.values()
        for factor in exposure.sensitivities
    }


def _declared_sector_exposure(config: AppConfig, sector: str | None) -> SectorExposure | None:
    configured = config.components.exposure_for(sector)
    if configured is None:
        return None
    return SectorExposure(
        sector=sector or "configured",
        sensitivities=configured.sensitivities,
        policy_stance=configured.policy_stance,
        policy_note=configured.policy_note,
        policy_source=configured.policy_source,
    )


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _sector_exposure(config: AppConfig, sector: str | None) -> SectorExposure:
    configured = config.components.exposure_for(sector)
    if configured is not None:
        return SectorExposure(
            sector=sector or "configured",
            sensitivities=configured.sensitivities,
            policy_stance=configured.policy_stance,
            policy_note=configured.policy_note,
            policy_source=configured.policy_source,
        )
    return SectorExposure(
        sector=sector or "fixture",
        sensitivities={"policy_rate": -0.6, "cpi": -0.5},
        policy_stance=0.1,
        policy_note="fixture policy context",
        policy_source="fixture",
    )


#: ATM implied volatility the fixture chain quotes. Paired with `_FIXTURE_ANNUAL_VOL`:
#: the two must stay within a plausible variance risk premium of each other, or the
#: implied distribution and the measured-sigma range describe different securities.
_FIXTURE_CHAIN_IV: float = 0.36


def _fixture_option_quotes(
    ticker: str,
    *,
    spot: float,
    run_date: date_type,
    as_of: datetime,
) -> list[OptionQuote]:
    quotes: list[OptionQuote] = []
    for expiry in (run_date + timedelta(days=7), run_date + timedelta(days=30)):
        for offset in range(-20, 25, 5):
            strike = round(spot + offset, 2)
            distance = abs(offset) / max(spot, 1.0)
            base = max(0.50, spot * (0.055 - distance * 0.70))
            call_iv = _FIXTURE_CHAIN_IV
            put_iv = _FIXTURE_CHAIN_IV - 0.04
            call_delta = max(0.05, min(0.95, 0.50 - (offset / 40.0)))
            put_delta = -max(0.05, min(0.95, 0.50 + (offset / 40.0)))
            quotes.append(
                OptionQuote(
                    ticker=ticker,
                    expiry=expiry,
                    strike=strike,
                    option_type="C",
                    bid=round(base, 2),
                    ask=round(base + 0.10, 2),
                    iv=call_iv,
                    delta=call_delta,
                    gamma=0.01,
                    open_interest=1_200 + int(abs(offset) * 8),
                    volume=240,
                    as_of=as_of,
                    venue="fixture",
                )
            )
            quotes.append(
                OptionQuote(
                    ticker=ticker,
                    expiry=expiry,
                    strike=strike,
                    option_type="P",
                    bid=round(base * 0.75, 2),
                    ask=round((base * 0.75) + 0.10, 2),
                    iv=put_iv,
                    delta=put_delta,
                    gamma=0.01,
                    open_interest=720 + int(abs(offset) * 6),
                    volume=130,
                    as_of=as_of,
                    venue="fixture",
                )
            )
    return quotes


#: Annualized realized volatility the fixture price series is built to exhibit.
#:
#: The fixture chain quotes IV at `_FIXTURE_CHAIN_IV`, so this leaves a variance risk
#: premium of about 1.2x - the ordinary relationship between implied and realized.
#: The previous curve moved ~0.4% a day, about 4.6% annualized against a chain quoting
#: 36%, so the implied distribution came out ~7.9x wider than the measured sigma range
#: and `within 1 sigma` collapsed from 0.68 to 0.10. Every fixture-run probability was
#: wrong, and a fixture that cannot agree with itself cannot validate anything
#: probability-shaped.
_FIXTURE_ANNUAL_VOL: float = 0.30
_FIXTURE_TRADING_DAYS: int = 252
_FIXTURE_BAR_COUNT: int = 75


def _fixture_price_bars(*, spot: float, run_date: date_type) -> list[dict[str, Any]]:
    """Deterministic daily closes whose realized volatility matches the fixture chain.

    Built from explicit daily log returns rather than from a price curve, so the vol the
    pipeline measures is the one declared in `_FIXTURE_ANNUAL_VOL` rather than an
    accident of a sine amplitude. The shocks are three incommensurate sines, standardized
    to the target daily sigma: deterministic, mean-zero, and not periodic on any single
    frequency. The series is rescaled so the final close lands exactly on `spot`, which
    leaves the log returns - and therefore the realized vol - untouched.
    """

    daily_sigma = _FIXTURE_ANNUAL_VOL / sqrt(_FIXTURE_TRADING_DAYS)
    raw = [
        sin(index * 1.1) + 0.6 * sin(index * 2.7 + 0.4) + 0.8 * sin(index * 0.37 + 1.3)
        for index in range(_FIXTURE_BAR_COUNT)
    ]
    mean = sum(raw) / len(raw)
    centered = [value - mean for value in raw]
    variance = sum(value * value for value in centered) / (len(centered) - 1)
    scale = daily_sigma / sqrt(variance)

    levels: list[float] = []
    level = 1.0
    for value in centered:
        level *= exp(value * scale)
        levels.append(level)

    to_spot = spot / levels[-1]
    start = run_date - timedelta(days=_FIXTURE_BAR_COUNT)
    return [
        {"date": start + timedelta(days=index), "close": round(level * to_spot, 4)}
        for index, level in enumerate(levels)
    ]


def _quote_payload(quote: OptionQuote) -> dict[str, Any]:
    return {
        "ticker": quote.ticker,
        "expiry": quote.expiry.isoformat(),
        "strike": quote.strike,
        "option_type": quote.option_type,
        "bid": quote.bid,
        "ask": quote.ask,
        "iv": quote.iv,
        "delta": quote.delta,
        "gamma": quote.gamma,
        "open_interest": quote.open_interest,
        "volume": quote.volume,
        "as_of": quote.as_of.isoformat() if quote.as_of else None,
        "venue": quote.venue,
    }
