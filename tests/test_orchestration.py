"""T10 end-to-end orchestration over a 1-2 ticker fixture universe."""

from __future__ import annotations

import json
import io
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

import pytest
from sqlalchemy import create_engine, select

from briefing_app.options_math import (
    build_measured_sigma_range,
    days_to_expiry,
    implied_distribution,
    realized_volatility,
    trading_days_from_calendar_days,
)
from briefing_app.strategy.scenarios import build_scenario_table

from briefing_app.cli import build_parser, main
from briefing_app.config import AppConfig, ProvidersSettings
from briefing_app.http import HttpFetchResult
from briefing_app.models.market_data import (
    NewsArticle,
    NewsSentimentBatch,
    ValidationStatus,
)
from briefing_app.pipeline import (
    LiveDataSource,
    _previous_business_day,
    STATUS_PARTIAL,
    STATUS_SKIPPED,
    STATUS_SUCCEEDED,
    FixtureDataSource,
    is_market_day,
    run_daily,
)
from briefing_app.providers import ProviderDataError
from briefing_app.raw_cache import RawCache
from briefing_app.settings import AppSettings
from briefing_app.storage import (
    StorageRepository,
    briefing_run,
    candidate_gate,
    component_score,
    create_schema,
    daily_snapshot,
    evidence_ledger,
    setup_signal,
)


RUN_DATE = date(2026, 8, 28)


class FakeLiveFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        self.calls.append(url)
        if "cdn.cboe.com" in url:
            ticker = "SPY" if url.endswith("/SPY.json") else "NVDA"
            spot = 500.0 if ticker == "SPY" else 120.0
            return json_result(_cboe_payload(ticker, spot))
        if "cdn.finra.org" in url:
            return text_result(_finra_short_volume("NVDA"))
        if url.endswith("/files/company_tickers.json"):
            return json_result({"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA Corp"}})
        if "data.sec.gov/submissions/" in url:
            return json_result(_sec_submissions("NVDA"))
        if "/Archives/edgar/data/" in url:
            return text_result(_sec_form4_xml("NVDA"))
        if "senate-latest" in url:
            return json_result(
                [
                    {
                        "symbol": "NVDA",
                        "senateID": "S000001",
                        "disclosureDate": RUN_DATE.isoformat(),
                        "transactionDate": (RUN_DATE - timedelta(days=2)).isoformat(),
                        "office": "Example Senator",
                        "type": "Purchase",
                        "amount": "$100,001 - $250,000",
                        "link": "https://efdsearch.senate.gov/search/view/ptr/example",
                    }
                ]
            )
        if "house-latest" in url:
            return json_result(
                [
                    {
                        "symbol": "AAPL",
                        "houseID": "H000001",
                        "disclosureDate": RUN_DATE.isoformat(),
                        "transactionDate": (RUN_DATE - timedelta(days=2)).isoformat(),
                        "office": "Example Representative",
                        "type": "Sale",
                        "amount": "$15,001 - $50,000",
                    }
                ]
            )
        if "apewisdom.io/api/v1.0/filter/all-stocks/page/1" in url:
            return json_result(
                {
                    "results": [
                        {
                            "ticker": "NVDA",
                            "mentions": 254,
                            "mentions_24h_ago": 56,
                            "upvotes": 679,
                            "rank": 1,
                            "rank_24h_ago": 3,
                        }
                    ]
                }
            )
        if "historical-price-eod" in url:
            return json_result(_fmp_price_history("NVDA"))
        if "economic-indicators" in url:
            return json_result(_fmp_economic_indicator(url))
        if "treasury-rates" in url:
            return json_result(_fmp_treasury_rates())
        if "grades-consensus" in url:
            return json_result(
                [
                    {
                        "symbol": "NVDA",
                        "strongBuy": 12,
                        "buy": 20,
                        "hold": 5,
                        "sell": 1,
                        "strongSell": 0,
                        "consensus": "Buy",
                    }
                ]
            )
        if "price-target-consensus" in url:
            return json_result(
                [
                    {
                        "symbol": "NVDA",
                        "targetHigh": 200,
                        "targetLow": 110,
                        "targetConsensus": 150,
                        "targetMedian": 148,
                    }
                ]
            )
        if "earnings-calendar" in url:
            return json_result(
                [{"symbol": "NVDA", "date": "2026-08-31", "epsEstimated": 1.0}]
            )
        if "TIME_SERIES_DAILY_ADJUSTED" in url or "TIME_SERIES_DAILY" in url:
            return json_result(_alpha_vantage_price_history("NVDA"))
        if "HISTORICAL_PUT_CALL_RATIO" in url:
            return json_result(
                {
                    "data": [
                        {"date": "2026-08-24", "put_call_volume_ratio": 0.80},
                        {"date": "2026-08-25", "put_call_volume_ratio": 0.85},
                        {"date": "2026-08-26", "put_call_open_interest_ratio": 1.05},
                    ]
                }
            )
        if "NEWS_SENTIMENT" in url:
            return json_result(
                {
                    "feed": [
                        {
                            "title": "NVDA demand update",
                            "url": "https://example.test/nvda-demand",
                            "source": "Wire",
                            "time_published": "20260828T110000",
                            "overall_sentiment_score": "0.25",
                            "ticker_sentiment": [
                                {
                                    "ticker": "NVDA",
                                    "relevance_score": "0.90",
                                    "ticker_sentiment_score": "0.35",
                                }
                            ],
                        }
                    ]
                }
            )
        if "EARNINGS_CALENDAR" in url:
            text = (
                "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
                "NVDA,NVIDIA Corp,2026-08-31,2026-07-31,1.00,USD\n"
            )
            return text_result(text)
        if "INSIDER_TRANSACTIONS" in url:
            return json_result(
                {
                    "data": [
                        {
                            "transaction_date": "2026-08-20",
                            "executive": "A. Insider",
                            "executive_title": "Director",
                            "transaction_type": "P",
                            "shares": "1000",
                            "share_price": "120",
                        }
                    ]
                }
            )
        if "INSTITUTIONAL_HOLDINGS" in url:
            return json_result(
                {
                    "data": [
                        {
                            "date": "2026-06-30",
                            "institution": "Active Fund",
                            "type": "active",
                            "shares": "1000000",
                            "change": "100000",
                        }
                    ]
                }
            )
        if "economic_calendar" in url or "economic-calendar" in url:
            return json_result(
                [
                    {
                        "date": "2026-08-20 08:30:00",
                        "country": "US",
                        "event": "CPI",
                        "impact": "High",
                        "actual": "3.0%",
                        "estimate": "3.2%",
                    }
                ]
            )
        raise AssertionError(f"Unexpected live fetch URL: {url}")


class PriceFallbackFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        self.calls.append(url)
        if "historical-price-eod" in url:
            raise HTTPError(
                url,
                402,
                "Payment Required",
                {},
                io.BytesIO(
                    b"Premium Query Parameter: 'Special Endpoint : This value set for "
                    b"'symbol' is not available under your current subscription"
                ),
            )
        if "api.twelvedata.com/time_series" in url:
            return json_result(_twelve_data_price_history("AVGO"))
        if "TIME_SERIES_DAILY" in url:
            raise AssertionError("Alpha Vantage should not be reached after Twelve Data")
        raise AssertionError(f"Unexpected price fallback URL: {url}")


class ConfigurableNewsDataSource(LiveDataSource):
    def __init__(
        self,
        *,
        settings: AppSettings,
        fetcher: FakeLiveFetcher,
        finnhub_batch: NewsSentimentBatch | None = None,
        finnhub_error: ProviderDataError | None = None,
    ) -> None:
        super().__init__(settings=settings, fetcher=fetcher)
        self.finnhub_batch = finnhub_batch
        self.finnhub_error = finnhub_error
        self.news_provider_calls: list[str] = []

    def _finnhub_news_batch(
        self,
        ticker: str,
        *,
        run_date: date,
        raw_cache: RawCache,
        responses: list,
        raw_paths: list,
    ) -> NewsSentimentBatch | None:
        self.news_provider_calls.append("finnhub")
        if self.finnhub_error is not None:
            raise self.finnhub_error
        return self.finnhub_batch

    def _alpha_vantage(self, raw_cache: RawCache):
        self.news_provider_calls.append("alpha_vantage")
        return super()._alpha_vantage(raw_cache)


def _sec_submissions(ticker: str) -> dict:
    """EDGAR company submissions carrying two recent Form 4s.

    `primaryDocument` uses the real `xslF345X06/` prefix, which names EDGAR's HTML
    rendering; the pipeline is expected to strip it and fetch the underlying XML.
    """

    filed = [
        (RUN_DATE - timedelta(days=3)).isoformat(),
        (RUN_DATE - timedelta(days=20)).isoformat(),
    ]
    return {
        "cik": "1045810",
        "tickers": [ticker],
        "filings": {
            "recent": {
                "form": ["4", "4", "10-Q"],
                "accessionNumber": [
                    "0001045810-26-000101",
                    "0001045810-26-000090",
                    "0001045810-26-000077",
                ],
                "primaryDocument": [
                    "xslF345X06/form4.xml",
                    "xslF345X06/form4.xml",
                    "nvda-20260731.htm",
                ],
                "filingDate": [filed[0], filed[1], filed[1]],
                "reportDate": [filed[0], filed[1], filed[1]],
            }
        },
    }


def _sec_form4_xml(
    ticker: str,
    *,
    code: str = "P",
    shares: int = 5_000,
    price: str = "120.00",
    planned: str = "false",
) -> str:
    """A Form 4 ownership document, shaped from a real EDGAR payload.

    Defaults to an open-market purchase outside a 10b5-1 plan, which is exactly the
    activity S_I is supposed to count.
    """

    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0609</schemaVersion>
    <documentType>4</documentType>
    <periodOfReport>{(RUN_DATE - timedelta(days=3)).isoformat()}</periodOfReport>
    <issuer>
        <issuerCik>0001045810</issuerCik>
        <issuerName>NVIDIA Corp</issuerName>
        <issuerTradingSymbol>{ticker}</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0001780525</rptOwnerCik>
            <rptOwnerName>Example Insider</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isOfficer>true</isOfficer>
            <officerTitle>Chief Financial Officer</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <aff10b5One>{planned}</aff10b5One>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>{(RUN_DATE - timedelta(days=3)).isoformat()}</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>{code}</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>{shares}</value></transactionShares>
                <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>{'A' if code == 'P' else 'D'}</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>50000</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
            <ownershipNature>
                <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
            </ownershipNature>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>
"""


def _finra_short_volume(ticker: str, *, short: int = 6_500, total: int = 10_000) -> str:
    """FINRA's consolidated daily file: pipe-delimited, one row per symbol.

    6,500 of 10,000 is a 0.65 short-volume ratio - elevated against the ~0.50 baseline,
    so the leg scores rather than sitting at zero.
    """

    stamp = _previous_business_day(RUN_DATE).strftime("%Y%m%d")
    return (
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        f"{stamp}|{ticker}|{short}|0|{total}|CNMS\n"
    )


def _fmp_price_history(ticker: str) -> list[dict[str, object]]:
    """Newest-first daily bars, the shape FMP `historical-price-eod/full` returns."""

    bars = []
    for offset in range(120):
        day = RUN_DATE - timedelta(days=offset)
        close = 120.0 + (offset % 7) - (offset % 3)
        bars.append(
            {
                "symbol": ticker,
                "date": day.isoformat(),
                "open": close - 0.5,
                "high": close + 1.2,
                "low": close - 1.4,
                "close": close,
                "volume": 1_000_000 + offset,
            }
        )
    return bars


def _twelve_data_price_history(ticker: str) -> dict[str, object]:
    """Daily bars in the Twelve Data `/time_series` shape."""

    values = []
    for offset in range(75):
        day = RUN_DATE - timedelta(days=offset)
        close = 300.0 + (offset % 5) - (offset * 0.15)
        values.append(
            {
                "datetime": day.isoformat(),
                "open": f"{close - 0.50:.2f}",
                "high": f"{close + 1.25:.2f}",
                "low": f"{close - 1.00:.2f}",
                "close": f"{close:.2f}",
                "volume": str(2_000_000 + offset),
            }
        )
    return {
        "meta": {"symbol": ticker, "interval": "1day", "exchange": "NASDAQ"},
        "values": values,
        "status": "ok",
    }


def _fmp_economic_indicator(url: str) -> list[dict[str, object]]:
    """A released series long enough for a release-change reading to have a scale."""

    name = "CPI" if "name=CPI" in url else "federalFunds"
    rows = []
    for offset in range(24):
        day = RUN_DATE - timedelta(days=30 * offset)
        rows.append(
            {"name": name, "date": day.isoformat(), "value": 300.0 - offset * 0.4}
        )
    return rows


def _fmp_treasury_rates() -> list[dict[str, object]]:
    rows = []
    for offset in range(90):
        day = RUN_DATE - timedelta(days=offset)
        rows.append(
            {
                "date": day.isoformat(),
                "year2": 3.5 + (offset % 5) * 0.01,
                "year10": 4.1 + (offset % 3) * 0.02,
            }
        )
    return rows


def test_fixture_chain_iv_and_price_bars_describe_the_same_security() -> None:
    """The fixture's implied vol and its realized vol must stay within a plausible VRP.

    They once did not: the chain quoted 36% IV against bars moving 4.6% annualized, a
    7.9x gap, so the implied distribution came out far wider than the measured-sigma
    range and `within 1 sigma` read 0.10 where the measured branch said 0.68. Every
    probability computed on a fixture run was wrong, which is worse than a fixture that
    fails outright - it silently validated nothing.
    """

    from briefing_app.pipeline import (
        _FIXTURE_CHAIN_IV,
        _fixture_price_bars,
    )

    bars = _fixture_price_bars(spot=120.0, run_date=RUN_DATE)
    assert bars[-1]["close"] == pytest.approx(120.0), "series must end on spot"

    for lookback in (20, 60):
        realized = realized_volatility(bars, lookback_days=lookback).annualized_vol
        premium = _FIXTURE_CHAIN_IV / realized
        assert 1.0 <= premium <= 2.0, (
            f"{lookback}d realized vol {realized:.4f} against chain IV "
            f"{_FIXTURE_CHAIN_IV} is a {premium:.2f}x premium; the fixture chain and "
            "its price history no longer describe the same security"
        )


def test_fixture_scenario_probabilities_do_not_flag_spurious_divergence() -> None:
    """A fixture run must not trip the implied-vs-measured divergence warning.

    The warning exists to mark a genuinely odd distribution. If ordinary fixture data
    trips it, the flag carries no information and the report's divergence penalty
    becomes a constant offset.
    """

    from briefing_app.pipeline import _fixture_option_quotes, _fixture_price_bars

    spot = 120.0
    expiry = RUN_DATE + timedelta(days=7)
    dte = days_to_expiry(RUN_DATE, expiry)
    bars = _fixture_price_bars(spot=spot, run_date=RUN_DATE)
    quotes = _fixture_option_quotes(
        "TEST", spot=spot, run_date=RUN_DATE, as_of=datetime(2026, 8, 28, 12, 0)
    )

    distribution = implied_distribution(quotes, spot=spot, as_of=RUN_DATE, expiry=expiry)
    assert distribution.captured_probability_mass >= 0.90

    measured = build_measured_sigma_range(
        spot=spot,
        realized_vol=realized_volatility(bars, lookback_days=20).annualized_vol,
        lookback_days=20,
        horizon_days=trading_days_from_calendar_days(dte),
        calendar_horizon_days=dte,
    )
    table = build_scenario_table(
        ticker="TEST",
        measured_range=measured,
        spot=spot,
        distribution=distribution,
        horizon_days=dte,
    )

    assert table.diverging_rows == ()
    # Implied sits a little wider than measured, which is what a variance risk premium
    # looks like - not the 0.10 the mismatched fixture used to produce.
    assert table.probability_in_one_sigma == pytest.approx(0.59, abs=0.06)


def test_daily_fixture_run_generates_dashboard_and_persists_rows(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    repo = StorageRepository(engine)
    old_run = repo.upsert_briefing_run(run_date=RUN_DATE - timedelta(days=1), status="succeeded")
    repo.upsert_daily_snapshot(
        {
            "run_id": old_run,
            "ticker": "NVDA",
            "snap_date": RUN_DATE - timedelta(days=1),
            "component_scores": {"S_M": 0.20},
            "cte_score": 0.31,
            "confidence_tier": "B",
            "expression_class": "E",
        }
    )

    output = run_daily(
        fixture_config(["NVDA"]),
        run_date=RUN_DATE,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        repository=repo,
    )

    assert output.status == STATUS_SUCCEEDED
    assert output.html_path is not None and output.html_path.exists()
    assert output.json_path is not None and output.json_path.exists()
    assert output.status_path is not None and output.status_path.exists()
    assert output.dashboard is not None
    assert output.dashboard.prior_scorecard[0].ticker == "NVDA"
    assert [row.ticker for row in output.dashboard.master_alpha_selection_matrix] == ["NVDA"]

    # Synthetic data floors the required S_O to tier C, so a fixture run reaches the
    # dashboard as a watchlist name and never as a tradeable call.
    assert output.scoring_report is not None
    assert output.scoring_report.results[0].tier.value == "C"
    assert output.setup_report is not None
    assert output.setup_report.tradeable_setups == []
    assert output.dashboard.tactical_execution_dashboard.top_long is None

    payload = json.loads(output.json_path.read_text(encoding="utf-8"))
    assert payload["data_mode"] == "fixture"
    assert payload["prior_scorecard"][0]["cte_score"] == 0.31
    assert payload["evidence_ledger"]

    status = json.loads(output.status_path.read_text(encoding="utf-8"))
    assert status["data_mode"] == "fixture"
    raw_paths = [
        row["endpoint_or_file"]
        for row in payload["evidence_ledger"]
        if "raw/fixture" in row["endpoint_or_file"]
    ]
    assert raw_paths
    for path_group in raw_paths:
        for raw_path in path_group.split("; "):
            assert Path(raw_path).exists()

    with engine.connect() as conn:
        run_row = conn.execute(
            select(briefing_run).where(briefing_run.c.id == output.storage_run_id)
        ).one()
        assert run_row._mapping["status"] == STATUS_SUCCEEDED
        assert len(conn.execute(select(candidate_gate)).all()) == 1
        assert len(conn.execute(select(component_score)).all()) == 5
        assert len(conn.execute(select(daily_snapshot)).all()) == 2
        assert len(conn.execute(select(evidence_ledger)).all()) > 0
        assert len(conn.execute(select(setup_signal)).all()) == 1


def test_daily_live_run_fetches_provider_payloads_and_scores(tmp_path) -> None:
    fetcher = FakeLiveFetcher()
    settings = AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=tmp_path / "settings-data",
        output_dir=tmp_path / "settings-output",
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key="av-key",
        fmp_api_key="fmp-key",
    )

    output = run_daily(
        fixture_config(["NVDA"], data_mode="live"),
        run_date=RUN_DATE,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        data_source=LiveDataSource(settings=settings, fetcher=fetcher),
    )

    assert output.status == STATUS_SUCCEEDED
    assert output.data_mode == "live"
    assert output.dashboard is not None and output.dashboard.data_mode == "live"
    assert output.scoring_report is not None
    result = output.scoring_report.results[0]
    assert result.ticker == "NVDA"
    assert result.s_cte is not None
    assert result.tier.value != "C"
    assert output.dashboard is not None
    assert output.dashboard.market_overview[0].source == "CBOE delayed options"

    cache_paths = [
        Path(row.endpoint_or_file)
        for row in output.dashboard.evidence_ledger
        if row.field_name.endswith("provider_status") and row.endpoint_or_file
    ]
    assert any("raw/cboe/delayed_options_chain" in str(path) for path in cache_paths)
    assert any("raw/fmp/historical_price_eod" in str(path) for path in cache_paths)
    assert any(path.exists() for path in cache_paths)
    assert any("cdn.cboe.com" in url for url in fetcher.calls)
    assert any("historical-price-eod" in url for url in fetcher.calls)
    assert not any("HISTORICAL_PUT_CALL_RATIO" in url for url in fetcher.calls)

    # Price history comes from FMP, whose EOD series is free and unmetered; Alpha
    # Vantage's adjusted series is premium-only and must not be reached for.
    assert not any("TIME_SERIES_DAILY_ADJUSTED" in url for url in fetcher.calls)

    # S_M scores from released indicator levels, because the dated economic calendar
    # with consensus estimates is plan-gated.
    macro = next(
        component
        for component in output.scoring_report.results[0].components
        if component.component == "S_M"
    )
    assert macro.score is not None
    assert any("economic-indicators" in url for url in fetcher.calls)

    sentiment_summary = next(
        component
        for component in next(
            section
            for section in output.dashboard.per_ticker_sections
            if section.ticker == "NVDA"
        ).components
        if component["component"] == "S_S"
    )
    sub_scores = {sub["name"]: sub for sub in sentiment_summary["sub_scores"]}
    assert sub_scores["retail_momentum"]["score"] is not None
    assert sub_scores["political_flow"]["score"] is not None
    assert sum("senate-latest" in url for url in fetcher.calls) == 1
    assert sum("house-latest" in url for url in fetcher.calls) == 1
    assert sum("apewisdom.io/api/v1.0/filter/all-stocks/page/1" in url for url in fetcher.calls) == 1


def test_price_history_falls_back_to_twelve_data_for_fmp_symbol_gate(tmp_path) -> None:
    fetcher = PriceFallbackFetcher()
    source = LiveDataSource(settings=_price_settings(tmp_path), fetcher=fetcher)
    responses: list = []
    raw_paths: list[Path] = []
    issues: list[str] = []
    config = fixture_config(["AVGO"], data_mode="live").model_copy(
        update={
            "providers": ProvidersSettings(
                prices=["fmp", "twelve_data", "alpha_vantage"]
            )
        }
    )

    bars = source._price_bars(
        "AVGO",
        config=config,
        run_date=RUN_DATE,
        raw_cache=RawCache(tmp_path / "data"),
        responses=responses,
        raw_paths=raw_paths,
        issues=issues,
    )

    assert bars
    assert bars[-1].source == "Twelve Data time_series"
    assert any("historical-price-eod" in url for url in fetcher.calls)
    assert any("api.twelvedata.com/time_series" in url for url in fetcher.calls)
    assert not any("TIME_SERIES_DAILY" in url for url in fetcher.calls)
    assert any("FMP historical price EOD unavailable" in issue for issue in issues)
    assert any("raw/twelve_data/time_series" in str(path) for path in raw_paths)


class FredCalendarFetcher:
    """FRED as it answered on 2026-09-02, through the shipping client.

    `fixture_config` declares sensitivities to `policy_rate` and `cpi`, which map to
    FEDFUNDS and CPIAUCSL - one series on a release that publishes every business day and
    one on a monthly release. That is exactly the pair the calendar has to tell apart.
    """

    #: Twenty-two H.15 dates in a thirty-day window, business days only.
    H15_DATES = [
        (RUN_DATE + timedelta(days=offset)).isoformat()
        for offset in range(0, 31)
        if (RUN_DATE + timedelta(days=offset)).weekday() < 5
    ]

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        self.calls.append(url)
        if "series/release?" in url:
            if "series_id=FEDFUNDS" in url:
                return json_result(
                    {"releases": [{"id": 18, "name": "H.15 Selected Interest Rates"}]}
                )
            if "series_id=CPIAUCSL" in url:
                return json_result({"releases": [{"id": 10, "name": "Consumer Price Index"}]})
            raise AssertionError(f"Unexpected series release URL: {url}")
        if "release/dates?" in url:
            forward = f"realtime_start={RUN_DATE.isoformat()}" in url
            if "release_id=18" in url:
                dates = self.H15_DATES if forward else ["2026-08-27", "2026-08-28"]
            else:
                dates = ["2026-09-11"] if forward else ["2026-07-15", "2026-08-12"]
            # FRED echoes the window it was asked about on every real answer, including
            # an empty one. The forward call's guard rests on that field.
            return json_result(
                {
                    "realtime_start": RUN_DATE.isoformat() if forward else "2016-08-28",
                    "count": len(dates),
                    "release_dates": [
                        {"release_id": 10, "date": day} for day in dates
                    ],
                }
            )
        if "series/observations" in url:
            return json_result({"observations": _fred_monthly_observations()})
        raise AssertionError(f"Unexpected FRED URL: {url}")


def _fred_monthly_observations() -> list[dict]:
    """Fourteen monthly prints, uneven enough to have a distribution to score against."""

    steps = [0.0, 0.2, -0.1, 0.3, 0.1, -0.2, 0.4, 0.0, 0.2, -0.3, 0.1, 0.2, -0.1, 0.3]
    value = 3.0
    rows = []
    for index, step in enumerate(steps):
        value += step
        month = 6 + index
        rows.append(
            {
                "date": date(2025 + (month - 1) // 12, (month - 1) % 12 + 1, 1).isoformat(),
                "value": f"{value:.2f}",
            }
        )
    return rows


def _fred_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=tmp_path / "settings-data",
        output_dir=tmp_path / "settings-output",
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key=None,
        fmp_api_key=None,
        fred_api_key="fred-key",
    )


def _fred_macro_config() -> AppConfig:
    return fixture_config(["NVDA"], data_mode="live").model_copy(
        update={"providers": ProvidersSettings(macro=["fred", "fmp"])}
    )


def test_macro_calendar_is_sourced_from_fred_release_dates(tmp_path) -> None:
    """The coverage-matrix row that never had a source: FMP's calendar is 402."""

    fetcher = FredCalendarFetcher()
    source = LiveDataSource(settings=_fred_settings(tmp_path), fetcher=fetcher)

    calendar, responses, issues = source._macro_calendar_for_run(
        config=_fred_macro_config(),
        run_date=RUN_DATE,
        generated_at=datetime(2026, 8, 28, 12, 0),
        raw_cache=RawCache(tmp_path / "data"),
    )

    assert calendar is not None
    assert calendar.source == "FRED release calendar"
    assert calendar.validation_status is ValidationStatus.VERIFIED
    assert calendar.requested_start == RUN_DATE
    assert calendar.requested_end == RUN_DATE + timedelta(days=30)

    # The monthly release is a catalyst; H.15's twenty-two business days are not.
    assert [event.name for event in calendar.events] == ["Consumer Price Index"]
    assert any(issue.code == "routine_release_excluded" for issue in calendar.diagnostics)

    # The chain stops at FRED, so the paywalled FMP calendar is never asked for.
    assert not any("economic-calendar" in url for url in fetcher.calls)
    assert issues == ()
    assert any("raw/fred/release_dates" in (r.cache_path or "") for r in responses)


class EmptyForwardWindowFetcher(FredCalendarFetcher):
    """The CPI release with nothing scheduled inside the window - release 365's shape."""

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        if (
            "release/dates?" in url
            and "release_id=10" in url
            and f"realtime_start={RUN_DATE.isoformat()}" in url
        ):
            self.calls.append(url)
            return json_result(
                {"realtime_start": RUN_DATE.isoformat(), "count": 0, "release_dates": []}
            )
        return super().fetch(url, timeout_seconds, headers)


def test_nothing_scheduled_is_not_reported_as_a_provider_failure(tmp_path) -> None:
    """A monthly release has no date in most 30-day windows; FRED says so with `count: 0`.

    Reading that as a failed call writes "fred.release_dates failed validation: missing"
    into the run issues for a release that is working perfectly.
    """

    fetcher = EmptyForwardWindowFetcher()
    source = LiveDataSource(settings=_fred_settings(tmp_path), fetcher=fetcher)

    calendar, _, issues = source._macro_calendar_for_run(
        config=_fred_macro_config(),
        run_date=RUN_DATE,
        generated_at=datetime(2026, 8, 28, 12, 0),
        raw_cache=RawCache(tmp_path / "data"),
    )

    assert issues == (), "an empty window is an answer, not an issue to log"
    assert calendar is not None
    # Nothing left but H.15, which is routine - so the window holds no catalyst, and that
    # is partial rather than a clean "nothing is scheduled".
    assert calendar.events == []
    assert calendar.validation_status is ValidationStatus.PARTIAL


def test_fred_calendar_and_ageing_share_one_release_lookup(tmp_path) -> None:
    """Both paths need series -> release. Resolving it twice would double the requests.

    The forward and historical windows of `release/dates` must still be two calls, and
    must land in two cache slots - the ageing join reads the historical one.
    """

    fetcher = FredCalendarFetcher()
    source = LiveDataSource(settings=_fred_settings(tmp_path), fetcher=fetcher)
    config = _fred_macro_config()
    raw_cache = RawCache(tmp_path / "data")

    source._macro_calendar_for_run(
        config=config,
        run_date=RUN_DATE,
        generated_at=datetime(2026, 8, 28, 12, 0),
        raw_cache=raw_cache,
    )
    readings, _, issues = source._macro_readings_for_run(
        config=config, run_date=RUN_DATE, raw_cache=raw_cache
    )

    series_release_calls = [url for url in fetcher.calls if "series/release?" in url]
    assert len(series_release_calls) == 2, "one lookup per declared series, not per caller"

    upcoming = {
        url for url in fetcher.calls
        if "release/dates?" in url and f"realtime_start={RUN_DATE.isoformat()}" in url
    }
    historical = {
        url for url in fetcher.calls
        if "release/dates?" in url and f"realtime_start={RUN_DATE.isoformat()}" not in url
    }
    assert len(upcoming) == 2 and len(historical) == 2
    cache_root = tmp_path / "data" / "raw" / "fred" / "release_dates" / RUN_DATE.isoformat()
    assert {path.name for path in cache_root.iterdir()} == {
        "10.json",
        "18.json",
        "10_upcoming.json",
        "18_upcoming.json",
    }
    # Both declared factors scored from FRED, so the chain never reached FMP - which is
    # only true if the ageing join still reads the historical window. The newest print is
    # dated 2026-07-01 and would be 58 days stale on its period; release 2026-08-12
    # carries it, and 16 days clears the 45-day bound.
    assert {reading.name for reading in readings} == {"policy_rate", "cpi"}
    assert issues == ()


def test_political_trades_for_run_accumulates_prior_raw_cache(tmp_path) -> None:
    fetcher = FakeLiveFetcher()
    source = LiveDataSource(settings=_live_settings(), fetcher=fetcher)
    raw_cache = RawCache(tmp_path / "data")
    prior_date = RUN_DATE - timedelta(days=3)
    raw_cache.write_json(
        "fmp",
        "senate_latest",
        prior_date,
        "all",
        [
            {
                "symbol": "NVDA",
                "senateID": "S000002",
                "disclosureDate": prior_date.isoformat(),
                "transactionDate": (prior_date - timedelta(days=2)).isoformat(),
                "office": "Prior Senator",
                "type": "Sale",
                "amount": "$15,001 - $50,000",
                "link": "https://efdsearch.senate.gov/search/view/ptr/prior",
            }
        ],
    )

    trades, responses, issues = source._political_trades_for_run(
        config=fixture_config(["NVDA"], data_mode="live"),
        run_date=RUN_DATE,
        raw_cache=raw_cache,
    )

    assert issues == ()
    assert len(responses) == 2
    assert {trade.politician for trade in trades if trade.ticker == "NVDA"} == {
        "Example Senator",
        "Prior Senator",
    }
    assert sum("senate-latest" in url for url in fetcher.calls) == 1
    assert sum("house-latest" in url for url in fetcher.calls) == 1


def test_configured_news_chain_stops_after_finnhub_returns_articles(tmp_path) -> None:
    fetcher = FakeLiveFetcher()
    source = ConfigurableNewsDataSource(
        settings=_news_settings(tmp_path),
        fetcher=fetcher,
        finnhub_batch=_finnhub_news_batch(has_articles=True),
    )
    config = _news_chain_config()
    responses: list = []
    raw_paths: list[Path] = []
    issues: list[str] = []

    batch = source._news_batch(
        "NVDA",
        config=config,
        run_date=RUN_DATE,
        raw_cache=RawCache(tmp_path / "data"),
        responses=responses,
        raw_paths=raw_paths,
        issues=issues,
    )

    assert batch is not None
    assert batch.source == "Finnhub company_news"
    assert source.news_provider_calls == ["finnhub"]
    assert fetcher.calls == []
    assert issues == []


@pytest.mark.parametrize("finnhub_mode", ["empty", "failure"])
def test_configured_news_chain_falls_back_to_alpha_vantage_on_failure_or_no_data(
    tmp_path,
    finnhub_mode: str,
) -> None:
    fetcher = FakeLiveFetcher()
    source = ConfigurableNewsDataSource(
        settings=_news_settings(tmp_path),
        fetcher=fetcher,
        finnhub_batch=_finnhub_news_batch(has_articles=False)
        if finnhub_mode == "empty"
        else None,
        finnhub_error=ProviderDataError(
            "finnhub", "company_news", "network_error", ("down",)
        )
        if finnhub_mode == "failure"
        else None,
    )
    responses: list = []
    raw_paths: list[Path] = []
    issues: list[str] = []

    batch = source._news_batch(
        "NVDA",
        config=_news_chain_config(),
        run_date=RUN_DATE,
        raw_cache=RawCache(tmp_path / "data"),
        responses=responses,
        raw_paths=raw_paths,
        issues=issues,
    )

    assert batch is not None
    assert batch.source == "Alpha Vantage NEWS_SENTIMENT"
    assert source.news_provider_calls == ["finnhub", "alpha_vantage"]
    assert any("NEWS_SENTIMENT" in url for url in fetcher.calls)
    assert not any("financialmodelingprep" in url for url in fetcher.calls)
    if finnhub_mode == "failure":
        assert any("Finnhub company news unavailable" in issue for issue in issues)


def test_failed_ticker_is_diagnostic_but_run_still_renders(tmp_path) -> None:
    output = run_daily(
        fixture_config(["NVDA", "FAIL"]),
        run_date=RUN_DATE,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        data_source=FixtureDataSource(failing_tickers={"FAIL"}),
    )

    assert output.status == STATUS_PARTIAL
    assert output.html_path is not None and output.html_path.exists()
    assert output.dashboard is not None
    assert any(failure.ticker == "FAIL" for failure in output.failures)
    assert any("FAIL data_pull_normalize_compute failed" in item for item in output.diagnostics)
    assert "NVDA" in {row.ticker for row in output.dashboard.master_alpha_selection_matrix}


def test_market_day_guard_skips_weekends_without_force(tmp_path) -> None:
    saturday = date(2026, 8, 29)
    assert is_market_day(RUN_DATE) is True
    assert is_market_day(saturday) is False

    output = run_daily(
        fixture_config(["NVDA"]),
        run_date=saturday,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
    )

    assert output.status == STATUS_SKIPPED
    assert output.dashboard is None
    assert output.status_path is not None and output.status_path.exists()


def test_cli_run_daily_command_generates_dashboard_for_fixture_config(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
timezone: Europe/Lisbon
universe:
  mode: fixed
  fixed_min: 0
  fixed_max: 2
  screen_min: 0
  screen_max: 0
  fixed:
    - ticker: NVDA
      venue: NASDAQ
      geography: US
      sector: Semiconductors
      direction: long
      thesis: Fixture event directional setup.
      horizon_days: 10
      expression_class: E
      broker: IBKR
      permitted_instruments: [shares, options]
      catalysts:
        - name: Quarterly results
          date: 2026-08-31
          status: confirmed
          kind: earnings
          source: Company IR
      thesis_sources:
        - label: Company IR
          kind: company_ir
gate:
  default_horizon_days: 10
  enabled_expression_classes: [E]
  require_thesis_source: true
components:
  sector_exposures:
    Semiconductors:
      sensitivities:
        policy_rate: -0.7
        cpi: -0.5
      policy_stance: 0.2
pipeline:
  data_mode: fixture
  skip_non_market_days: true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "run-daily",
            "--config",
            str(config_path),
            "--run-date",
            RUN_DATE.isoformat(),
            "--data-dir",
            str(tmp_path / "data"),
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )

    assert exit_code == 0
    dashboard = tmp_path / "output" / "dashboard" / RUN_DATE.isoformat() / "dashboard.json"
    assert dashboard.exists()
    payload = json.loads(dashboard.read_text(encoding="utf-8"))
    assert payload["data_mode"] == "fixture"
    assert [row["ticker"] for row in payload["master_alpha_selection_matrix"]] == ["NVDA"]


def test_cli_parser_accepts_live_data_mode() -> None:
    args = build_parser().parse_args(["run-daily", "--data-mode", "live"])
    assert args.data_mode == "live"


def _news_chain_config() -> AppConfig:
    return fixture_config(["NVDA"], data_mode="live").model_copy(
        update={"providers": ProvidersSettings(news=["finnhub", "alpha_vantage"])}
    )


def _news_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=tmp_path / "settings-data",
        output_dir=tmp_path / "settings-output",
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key="av-key",
        fmp_api_key=None,
    )


def _price_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=tmp_path / "settings-data",
        output_dir=tmp_path / "settings-output",
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key="av-key",
        fmp_api_key="fmp-key",
        twelve_data_api_key="td-key",
    )


def _finnhub_news_batch(*, has_articles: bool) -> NewsSentimentBatch:
    as_of = datetime(2026, 8, 28, 11, 0)
    articles = [
        NewsArticle(
            ticker="NVDA",
            title="NVDA demand update",
            source="Finnhub",
            published_at=as_of,
            url="https://example.test/finnhub-nvda",
            relevance_score=0.9,
            sentiment_score=0.4,
        )
    ] if has_articles else []
    return NewsSentimentBatch(
        ticker="NVDA",
        as_of=as_of,
        source="Finnhub company_news",
        articles=articles,
        validation_status=ValidationStatus.VERIFIED
        if articles
        else ValidationStatus.PARTIAL,
    )


def fixture_config(tickers: list[str], *, data_mode: str = "fixture") -> AppConfig:
    return AppConfig.model_validate(
        {
            "universe": {
                "mode": "fixed",
                "fixed_min": 0,
                "fixed_max": max(2, len(tickers)),
                "screen_min": 0,
                "screen_max": 0,
                "fixed": [_candidate(ticker) for ticker in tickers],
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
            "pipeline": {"data_mode": data_mode, "skip_non_market_days": True},
        }
    )


def _candidate(ticker: str) -> dict:
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
                "date": RUN_DATE + timedelta(days=3),
                "status": "confirmed",
                "kind": "earnings",
                "source": "Company IR",
            }
        ],
        "thesis_sources": [{"label": "Company IR", "kind": "company_ir"}],
    }


def json_result(payload: object) -> HttpFetchResult:
    return HttpFetchResult(
        200,
        json.dumps(payload).encode("utf-8"),
        {"Content-Type": "application/json"},
        "https://provider.test",
    )


def text_result(text: str) -> HttpFetchResult:
    return HttpFetchResult(
        200,
        text.encode("utf-8"),
        {"Content-Type": "text/plain"},
        "https://provider.test",
    )


def _cboe_payload(ticker: str, spot: float) -> dict:
    options = []
    for expiry in (date(2026, 9, 4), date(2026, 9, 25)):
        for offset in range(-20, 25, 5):
            strike = spot + offset
            for option_type, delta in (("C", 0.45), ("P", -0.45)):
                distance = abs(offset)
                type_boost = 50 if option_type == "C" else 25
                options.append(
                    {
                        "option": _occ_symbol(ticker, expiry, option_type, strike),
                        "bid": 2.00,
                        "ask": 2.20,
                        "iv": 0.32,
                        "delta": delta,
                        "gamma": 0.015,
                        "volume": 100 + distance + type_boost,
                        "open_interest": 1000 + (distance * 10) + type_boost,
                        "last_trade_time": "2026-08-28T19:00:00Z",
                    }
                )
    return {
        "timestamp": "2026-08-28T20:00:00Z",
        "data": {"current_price": spot, "options": options},
    }


def _occ_symbol(ticker: str, expiry: date, option_type: str, strike: float) -> str:
    stamp = expiry.strftime("%y%m%d")
    strike_code = f"{int(strike * 1000):08d}"
    return f"{ticker}{stamp}{option_type}{strike_code}"


def _alpha_vantage_price_history(ticker: str) -> dict:
    series = {}
    start = RUN_DATE - timedelta(days=75)
    for index in range(75):
        day = start + timedelta(days=index)
        close = 105 + (index * 0.20) + ((index % 5) * 0.30)
        series[day.isoformat()] = {
            "1. open": f"{close - 0.50:.2f}",
            "2. high": f"{close + 1.00:.2f}",
            "3. low": f"{close - 1.00:.2f}",
            "4. close": f"{close:.2f}",
            "5. adjusted close": f"{close:.2f}",
            "6. volume": "1000000",
        }
    return {"Meta Data": {"2. Symbol": ticker}, "Time Series (Daily)": series}


def test_self_built_series_is_withheld_until_the_warm_up_completes() -> None:
    """A percentile over a handful of points is meaningless, not merely weak.

    The baselines fill one session per run, so until `SELF_BUILT_SERIES_MIN_SESSIONS`
    sessions exist the series is withheld and the run says how far along it is.
    """

    from sqlalchemy import create_engine

    from briefing_app.pipeline import SELF_BUILT_SERIES_MIN_SESSIONS
    from briefing_app.storage import StorageRepository, create_schema

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    create_schema(engine)
    repo = StorageRepository(engine)
    run_id = repo.upsert_briefing_run(run_date=RUN_DATE, status="succeeded")

    def store(sessions: int) -> None:
        for offset in range(1, sessions + 1):
            repo.upsert_daily_snapshot(
                {
                    "run_id": run_id,
                    "ticker": "NVDA",
                    "snap_date": RUN_DATE - timedelta(days=offset),
                    "iv_atm": 0.30,
                    "pc_ratio_vol": 0.80,
                    "pc_ratio_oi": 0.90,
                }
            )

    source = LiveDataSource(settings=_live_settings(), fetcher=FakeLiveFetcher())

    store(SELF_BUILT_SERIES_MIN_SESSIONS - 1)
    issues: list[str] = []
    iv, pc_vol, pc_oi = source._stored_option_series(
        "NVDA", run_date=RUN_DATE, repository=repo, issues=issues
    )
    assert (iv, pc_vol, pc_oi) == ([], [], [])
    assert any("baseline still building" in issue for issue in issues)
    assert any(f"of {SELF_BUILT_SERIES_MIN_SESSIONS} sessions" in issue for issue in issues)

    store(SELF_BUILT_SERIES_MIN_SESSIONS)
    issues = []
    iv, pc_vol, pc_oi = source._stored_option_series(
        "NVDA", run_date=RUN_DATE, repository=repo, issues=issues
    )
    assert len(iv) == SELF_BUILT_SERIES_MIN_SESSIONS
    assert len(pc_vol) == SELF_BUILT_SERIES_MIN_SESSIONS
    assert issues == []


def test_no_database_means_no_self_built_baseline_and_says_so() -> None:
    source = LiveDataSource(settings=_live_settings(), fetcher=FakeLiveFetcher())
    issues: list[str] = []
    assert source._stored_option_series(
        "NVDA", run_date=RUN_DATE, repository=None, issues=issues
    ) == ([], [], [])
    assert any("no database is configured" in issue for issue in issues)


def _live_settings() -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=Path("/tmp/briefing-series-test-data"),
        output_dir=Path("/tmp/briefing-series-test-output"),
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key="av-key",
        fmp_api_key="fmp-key",
    )


class FinnhubLiveFetcher:
    """Serves Finnhub and Alpha Vantage news, and records everything requested."""

    def __init__(self, *, finnhub_status: int = 200) -> None:
        self.calls: list[str] = []
        self.finnhub_status = finnhub_status

    def fetch(self, url: str, timeout_seconds: float, headers: dict) -> HttpFetchResult:
        self.calls.append(url)
        if "finnhub.io" in url and "company-news" in url:
            return json_result(
                [
                    {
                        "category": "company news",
                        "datetime": int(
                            datetime(2026, 8, 28, 11, 0).timestamp()
                        ),
                        "headline": "NVDA beats estimates and raises guidance",
                        "id": 1,
                        "related": "NVDA",
                        "source": "Reuters",
                        "summary": "Data centre revenue ahead of consensus.",
                        "url": "https://example.test/finnhub-nvda",
                    }
                ]
            )
        if "finnhub.io" in url and "stock/recommendation" in url:
            return json_result(
                [
                    {
                        "buy": 20,
                        "hold": 5,
                        "period": (RUN_DATE - timedelta(days=3)).isoformat(),
                        "sell": 1,
                        "strongBuy": 12,
                        "strongSell": 0,
                        "symbol": "NVDA",
                    }
                ]
            )
        if "grades-consensus" in url or "price-target-consensus" in url:
            return json_result([])
        if "NEWS_SENTIMENT" in url:
            return json_result({"feed": []})
        raise AssertionError(f"Unexpected live fetch URL: {url}")


def _finnhub_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=tmp_path / "settings-data",
        output_dir=tmp_path / "settings-output",
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key="av-key",
        fmp_api_key="fmp-key",
        finnhub_api_key="fh-key",
    )


def test_live_news_leg_reads_finnhub_and_scores_tone_locally(tmp_path) -> None:
    """The leg that had no working source at all now produces scored articles."""

    fetcher = FinnhubLiveFetcher()
    source = LiveDataSource(settings=_finnhub_settings(tmp_path), fetcher=fetcher)
    issues: list[str] = []

    batch = source._news_batch(
        "NVDA",
        config=_news_chain_config(),
        run_date=RUN_DATE,
        raw_cache=RawCache(tmp_path / "data"),
        responses=[],
        raw_paths=[],
        issues=issues,
    )

    assert batch is not None and batch.articles
    assert "local tone" in batch.source
    assert batch.articles[0].sentiment_score > 0
    assert any("company-news" in call for call in fetcher.calls)
    assert not any("NEWS_SENTIMENT" in call for call in fetcher.calls)
    assert issues == []


def test_eu_ticker_skips_finnhub_without_a_request_and_falls_through(tmp_path) -> None:
    """Finnhub's free tier is US-only. Rediscovering that every run costs a request."""

    fetcher = FinnhubLiveFetcher()
    source = LiveDataSource(settings=_finnhub_settings(tmp_path), fetcher=fetcher)
    issues: list[str] = []

    source._news_batch(
        "RHM.DE",
        config=_news_chain_config(),
        run_date=RUN_DATE,
        raw_cache=RawCache(tmp_path / "data"),
        responses=[],
        raw_paths=[],
        issues=issues,
    )

    assert not any("finnhub.io" in call for call in fetcher.calls)
    assert any("NEWS_SENTIMENT" in call for call in fetcher.calls)
    assert any("US-only" in issue for issue in issues)


def test_analyst_leg_falls_back_to_finnhub_when_fmp_returns_nothing(tmp_path) -> None:
    """Ends the sole-provider exposure on the only S_S leg that scores."""

    fetcher = FinnhubLiveFetcher()
    source = LiveDataSource(settings=_finnhub_settings(tmp_path), fetcher=fetcher)
    issues: list[str] = []

    signals = source._analyst_signals(
        "NVDA",
        config=fixture_config(["NVDA"], data_mode="live").model_copy(
            update={"providers": ProvidersSettings(analyst=["fmp", "finnhub"])}
        ),
        run_date=RUN_DATE,
        raw_cache=RawCache(tmp_path / "data"),
        responses=[],
        raw_paths=[],
        issues=issues,
    )

    assert [s.source for s in signals] == ["Finnhub recommendation-trends"]
    assert signals[0].rating == "buy"
    assert any("grades-consensus" in call for call in fetcher.calls)
