from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from briefing_app.models.market_data import (
    OptionFilterConfig,
    OptionType,
    ValidationStatus,
)
from briefing_app.providers.manual import (
    load_eu_major_holdings_csv,
    load_eu_mar_article_19_csv,
    load_eu_short_disclosures_csv,
    load_eurex_manual_options_capture,
)
from briefing_app.providers.normalizers import (
    NormalizationError,
    parse_date,
    parse_datetime,
    build_fred_macro_calendar,
    normalize_apewisdom_retail_momentum,
    normalize_alpha_vantage_daily,
    normalize_alpha_vantage_daily_adjusted,
    normalize_alpha_vantage_earnings_calendar_csv,
    normalize_alpha_vantage_economic_indicator,
    normalize_alpha_vantage_insider_transactions,
    normalize_alpha_vantage_institutional_holdings,
    normalize_alpha_vantage_news_sentiment,
    normalize_alpha_vantage_options_chain,
    normalize_alpha_vantage_put_call_ratio,
    normalize_alpha_vantage_quote,
    normalize_cboe_option_chain,
    normalize_finnhub_company_news,
    normalize_finnhub_recommendation_trends,
    normalize_finra_short_volume,
    normalize_fmp_analyst_ratings,
    normalize_fmp_balance_sheet_statement,
    normalize_fmp_cash_flow_statement,
    normalize_fmp_earnings_calendar,
    normalize_fmp_economic_calendar,
    normalize_fmp_economic_indicators,
    normalize_fmp_grades_consensus,
    normalize_fmp_congress_trades,
    normalize_fmp_historical_price_eod,
    normalize_fmp_income_statement,
    normalize_fmp_insider_trades,
    normalize_fmp_institutional_ownership,
    normalize_fmp_price_target_consensus,
    normalize_fmp_quote,
    normalize_fmp_sec_filings,
    normalize_fmp_stock_news,
    normalize_fmp_treasury_rates,
    normalize_fred_release_dates,
    normalize_fred_series_observations,
    normalize_sec_company_submissions,
    normalize_sec_company_tickers,
    normalize_sec_form4_ownership_document,
    normalize_twelve_data_time_series,
    parse_occ_contract,
)


def test_parse_occ_contract_extracts_expiry_type_and_strike() -> None:
    parsed = parse_occ_contract("BRK.B260904P00375000")
    assert parsed["underlying"] == "BRK.B"
    assert parsed["expiry"] == date(2026, 9, 4)
    assert parsed["option_type"] is OptionType.PUT
    assert parsed["strike"] == 375.0


def test_cboe_chain_normalizes_and_filters_illiquid_rows() -> None:
    payload = {
        "timestamp": "2026-08-29 05:20:00",
        "data": {
            "exchange_id": "CBOE",
            "current_price": 500.0,
            "last_trade_time": "2026-08-29T12:00:00",
            "options": [
                {
                    "option": "SPY260904C00500000",
                    "bid": 4.5,
                    "ask": 4.7,
                    "iv": 0.20,
                    "delta": 0.51,
                    "gamma": 0.02,
                    "volume": 25,
                    "open_interest": 500,
                    "last_trade_time": "2026-08-29T12:01:00",
                },
                {
                    "option": "SPY260904P00400000",
                    "bid": 0,
                    "ask": 0,
                    "volume": 0,
                    "open_interest": 0,
                },
            ],
        },
    }

    chain = normalize_cboe_option_chain(
        "SPY",
        payload,
        filters=OptionFilterConfig(min_open_interest=10, min_volume=1),
        endpoint_or_file="fixture.json",
    )

    assert chain.spot == 500
    assert len(chain.contracts) == 1
    assert chain.contracts[0].mid == 4.6
    assert chain.contracts[0].option_type is OptionType.CALL
    assert "filtered_option_rows" in {issue.code for issue in chain.diagnostics}


def test_cboe_chain_rejects_synthetic_payload() -> None:
    with pytest.raises(NormalizationError):
        normalize_cboe_option_chain(
            "TEST",
            {
                "data": [
                    {
                        "contractID": "XXYYZZ999999C00020000",
                        "expiration": "2099-99-99",
                        "open_interest": 100,
                    }
                ]
            },
        )


def test_alpha_vantage_quote_and_price_history_normalize() -> None:
    quote = normalize_alpha_vantage_quote(
        "IBM",
        {
            "Global Quote": {
                "01. symbol": "IBM",
                "02. open": "190.00",
                "03. high": "191.00",
                "04. low": "188.00",
                "05. price": "189.50",
                "06. volume": "123456",
                "07. latest trading day": "2026-08-28",
                "08. previous close": "188.25",
            }
        },
    )
    assert quote.price == 189.5
    assert quote.volume == 123456

    bars = normalize_alpha_vantage_daily_adjusted(
        "IBM",
        {
            "Time Series (Daily)": {
                "2026-08-28": {
                    "1. open": "190.00",
                    "2. high": "191.00",
                    "3. low": "188.00",
                    "4. close": "189.50",
                    "5. adjusted close": "189.00",
                    "6. volume": "123456",
                }
            }
        },
    )
    assert bars[0].date == date(2026, 8, 28)
    assert bars[0].adjusted_close == 189.0


def test_alpha_vantage_news_and_earnings_normalize() -> None:
    news = normalize_alpha_vantage_news_sentiment(
        "NVDA",
        {
            "feed": [
                {
                    "title": "Chip demand update",
                    "url": "https://example.test/nvda",
                    "source": "Wire",
                    "time_published": "20260829T120000",
                    "overall_sentiment_score": "0.10",
                    "ticker_sentiment": [
                        {
                            "ticker": "NVDA",
                            "relevance_score": "0.88",
                            "ticker_sentiment_score": "0.25",
                            "ticker_sentiment_label": "Bullish",
                        }
                    ],
                }
            ]
        },
    )
    assert news.articles[0].sentiment_score == 0.25
    assert news.articles[0].relevance_score == 0.88

    calendar = normalize_alpha_vantage_earnings_calendar_csv(
        "NVDA",
        "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
        "NVDA,NVIDIA Corp,2026-09-02,2026-07-31,1.00,USD\n",
    )
    assert calendar.events[0].event_date == date(2026, 9, 2)
    assert calendar.events[0].kind == "earnings"
    assert calendar.validation_status is ValidationStatus.VERIFIED
    assert calendar.absence_is_evidence is True


def test_alpha_vantage_options_put_call_macro_insider_and_ownership_normalize() -> None:
    options_payload = {
        "timestamp": "2026-08-29T13:30:00Z",
        "data": [
            {
                "contractID": "IBM260918C00200000",
                "expiration": "2026-09-18",
                "strike": "200",
                "type": "call",
                "bid": "2.00",
                "ask": "2.20",
                "volume": "40",
                "open_interest": "400",
                "implied_volatility": "0.30",
            },
            {
                "symbol": "IBM",
                "expiration": "2026-09-18",
                "strike": "190",
                "type": "put",
                "mark": "1.25",
                "volume": "60",
                "open_interest": "600",
            },
        ],
    }

    chain = normalize_alpha_vantage_options_chain("IBM", options_payload, spot=189.5)
    assert chain.call_count == 1
    assert chain.put_count == 1
    assert chain.contracts[0].mid == 2.1
    assert chain.contracts[1].contract_symbol == "IBM260918P00190000"

    put_call = normalize_alpha_vantage_put_call_ratio("IBM", options_payload)
    assert put_call[0].put_call_volume_ratio == 1.5
    assert put_call[0].put_call_open_interest_ratio == 1.5

    macro = normalize_alpha_vantage_economic_indicator(
        {"name": "CPI", "data": [{"date": "2026-08-01", "value": "313.7"}]}
    )
    assert macro[0].name == "CPI"
    assert macro[0].actual == "313.7"

    insider = normalize_alpha_vantage_insider_transactions(
        "IBM",
        {
            "data": [
                {
                    "transaction_date": "2026-08-20",
                    "executive": "A. Insider",
                    "executive_title": "Director",
                    "transaction_type": "Purchase",
                    "shares": "100",
                    "share_price": "10.5",
                }
            ]
        },
    )
    assert insider[0].value == 1050
    assert insider[0].title == "Director"

    ownership = normalize_alpha_vantage_institutional_holdings(
        "IBM",
        {
            "data": [
                {
                    "date": "2026-06-30",
                    "institution": "Fund A",
                    "shares": "1000000",
                    "change": "50000",
                    "change_percentage": "5",
                }
            ]
        },
    )
    assert ownership[0].institution == "Fund A"
    assert ownership[0].shares_delta == 50000


def test_fmp_quote_and_macro_calendar_normalize() -> None:
    quote = normalize_fmp_quote(
        "AAPL",
        [{"symbol": "AAPL", "price": 230.1, "exchangeShortName": "NASDAQ", "timestamp": 1788000000}],
    )
    assert quote.venue == "NASDAQ"
    assert quote.price == 230.1

    calendar = normalize_fmp_economic_calendar(
        [
            {
                "date": "2026-09-02 08:30:00",
                "country": "US",
                "event": "Nonfarm Payrolls",
                "impact": "High",
                "estimate": "150K",
            }
        ]
    )
    assert calendar.events[0].name == "Nonfarm Payrolls"
    assert calendar.events[0].importance == "High"
    assert calendar.validation_status is ValidationStatus.VERIFIED


def test_fmp_news_calendar_insiders_analysts_statements_ownership_and_filings_normalize() -> None:
    news = normalize_fmp_stock_news(
        "AAPL",
        [
            {
                "title": "Product cycle update",
                "publishedDate": "2026-08-29 09:30:00",
                "site": "Newswire",
                "url": "https://example.test/aapl",
            }
        ],
    )
    assert news.articles[0].source == "Newswire"

    congress = normalize_fmp_congress_trades(
        [
            {
                "symbol": "GS",
                "senateID": "M001243",
                "disclosureDate": "2026-08-27",
                "transactionDate": "2026-07-28",
                "firstName": "Dave",
                "lastName": "McCormick",
                "office": "Dave McCormick",
                "district": "PA",
                "owner": "Spouse",
                "assetType": "Corporate Bond",
                "type": "Purchase",
                "amount": "$100,001 - $250,000",
                "link": "https://efdsearch.senate.gov/search/view/ptr/example",
            }
        ],
        chamber="senate",
    )
    assert congress[0].ticker == "GS"
    assert congress[0].politician_id == "M001243"
    assert congress[0].amount_min == 100001
    assert congress[0].amount_max == 250000
    assert congress[0].source_url == "https://efdsearch.senate.gov/search/view/ptr/example"

    retail = normalize_apewisdom_retail_momentum(
        {
            "results": [
                {
                    "ticker": "NVDA",
                    "mentions": 254,
                    "upvotes": 679,
                    "rank": 1,
                    "rank_24h_ago": 3,
                    "mentions_24h_ago": 56,
                }
            ]
        },
        as_of=date(2026, 8, 29),
    )
    assert retail[0].ticker == "NVDA"
    assert retail[0].mentions == 254
    assert retail[0].mentions_24h_ago == 56

    earnings = normalize_fmp_earnings_calendar(
        "AAPL",
        [{"symbol": "AAPL", "date": "2026-10-28", "epsEstimated": 1.4}],
    )
    assert earnings.events[0].kind == "earnings"
    assert earnings.absence_is_evidence is True

    insiders = normalize_fmp_insider_trades(
        "AAPL",
        [
            {
                "transactionDate": "2026-08-20",
                "reportingName": "B. Insider",
                "transactionType": "S-Sale",
                "securitiesTransacted": 50,
                "price": 200,
                "securitiesOwned": 1000,
            }
        ],
    )
    assert insiders[0].value == 10000
    assert insiders[0].shares_owned == 1000

    analysts = normalize_fmp_analyst_ratings(
        "AAPL",
        [
            {
                "publishedDate": "2026-08-21",
                "analystCompany": "Broker A",
                "analystName": "Analyst One",
                "rating": "Buy",
                "priceTarget": 250,
            }
        ],
    )
    assert analysts[0].firm == "Broker A"
    assert analysts[0].price_target == 250

    income = normalize_fmp_income_statement(
        "AAPL",
        [{"date": "2026-06-30", "period": "Q3", "revenue": 100, "netIncome": 20, "eps": 1.2}],
    )
    balance = normalize_fmp_balance_sheet_statement(
        "AAPL",
        [{"date": "2026-06-30", "totalAssets": 300, "totalLiabilities": 150}],
    )
    cash_flow = normalize_fmp_cash_flow_statement(
        "AAPL",
        [{"date": "2026-06-30", "operatingCashFlow": 30, "capitalExpenditure": -5}],
    )
    assert income[0].net_income == 20
    assert balance[0].assets == 300
    assert cash_flow[0].capital_expenditure == -5

    ownership = normalize_fmp_institutional_ownership(
        "AAPL",
        [
            {
                "date": "2026-06-30",
                "holder": "Fund B",
                "shares": 2000,
                "changeInSharesNumber": 100,
            }
        ],
    )
    assert ownership[0].institution == "Fund B"
    assert ownership[0].shares_delta == 100

    filings = normalize_fmp_sec_filings(
        "AAPL",
        [
            {
                "symbol": "AAPL",
                "cik": "0000320193",
                "type": "4",
                "fillingDate": "2026-08-28",
                "periodOfReport": "2026-08-27",
                "finalLink": "https://example.test/form4",
            }
        ],
    )
    assert filings[0].form == "4"
    assert filings[0].url == "https://example.test/form4"


def test_finra_and_sec_normalizers() -> None:
    rows = normalize_finra_short_volume(
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        "20260828|AAPL|1000|0|5000|Q\n"
    )
    assert rows[0].ticker == "AAPL"
    assert rows[0].short_volume == 1000
    assert rows[0].total_volume == 5000

    filings = normalize_sec_company_submissions(
        "AAPL",
        {
            "cik": "0000320193",
            "filings": {
                "recent": {
                    "form": ["4", "13F-HR"],
                    "filingDate": ["2026-08-28", "2026-08-15"],
                    "reportDate": ["2026-08-27", "2026-06-30"],
                    "accessionNumber": ["0000320193-26-000001", "0000000000-26-000002"],
                    "primaryDocument": ["xslF345X05/doc.xml", "form13f.xml"],
                }
            },
        },
    )
    assert [filing.form for filing in filings] == ["4", "13F-HR"]
    assert filings[0].url and "Archives/edgar/data/320193" in filings[0].url

    ticker_map = normalize_sec_company_tickers(
        {"0": {"ticker": "AAPL", "cik_str": 320193}, "1": {"ticker": "MSFT", "cik_str": 789019}}
    )
    assert ticker_map["AAPL"] == 320193


def test_manual_eurex_and_eu_short_capture_loaders(tmp_path: Path) -> None:
    chain_path = tmp_path / "eurex.csv"
    chain_path.write_text(
        "venue,as_of,expiry,strike,type,settlement,open_interest,volume\n"
        "EUREX,2026-08-29T12:00:00,2026-09-18,1800,C,42.10,1240,85\n",
        encoding="utf-8",
    )
    chain = load_eurex_manual_options_capture(
        chain_path,
        ticker="RHM.DE",
        spot=1780,
        filters=OptionFilterConfig(min_open_interest=1, min_volume=1),
    )
    assert chain.venue == "EUREX"
    assert chain.contracts[0].open_interest == 1240

    shorts_path = tmp_path / "shorts.csv"
    shorts_path.write_text(
        "ticker,isin,issuer,holder,position_date,net_short_position\n"
        "RHM.DE,DE0007030009,Rheinmetall AG,Fund A,2026-08-28,0.62\n",
        encoding="utf-8",
    )
    disclosures = load_eu_short_disclosures_csv(shorts_path)
    assert disclosures[0].isin == "DE0007030009"
    assert disclosures[0].disclosed_net_short_pct == 0.62

    mar_path = tmp_path / "mar.csv"
    mar_path.write_text(
        "ticker,transaction_date,person,role,transaction_type,shares,price\n"
        "RHM.DE,2026-08-27,Executive A,CEO,Purchase,10,500\n",
        encoding="utf-8",
    )
    mar_rows = load_eu_mar_article_19_csv(mar_path)
    assert mar_rows[0].ticker == "RHM.DE"
    assert mar_rows[0].value == 5000

    holdings_path = tmp_path / "holdings.csv"
    holdings_path.write_text(
        "ticker,notification_date,holder,shares,percent_delta\n"
        "RHM.DE,2026-08-26,Fund C,100000,3.1\n",
        encoding="utf-8",
    )
    holdings = load_eu_major_holdings_csv(holdings_path)
    assert holdings[0].institution == "Fund C"
    assert holdings[0].percent_delta == 3.1


def test_fmp_historical_price_eod_normalizes_oldest_first() -> None:
    """FMP answers newest-first; realized-vol windows read oldest-first."""

    bars = normalize_fmp_historical_price_eod(
        "AAPL",
        [
            {"symbol": "AAPL", "date": "2026-08-28", "open": 316.8, "high": 322.3,
             "low": 315.4, "close": 319.7, "volume": 38649398},
            {"symbol": "AAPL", "date": "2026-08-27", "open": 310.0, "high": 317.5,
             "low": 309.1, "close": 316.85, "volume": 30111222},
        ],
    )

    assert [bar.date.isoformat() for bar in bars] == ["2026-08-27", "2026-08-28"]
    assert bars[-1].close == 319.7
    assert bars[-1].source == "FMP historical-price-eod"


def test_twelve_data_time_series_normalizes_oldest_first() -> None:
    bars = normalize_twelve_data_time_series(
        "AVGO",
        {
            "meta": {"symbol": "AVGO", "interval": "1day"},
            "values": [
                {
                    "datetime": "2026-08-28",
                    "open": "300.10",
                    "high": "305.20",
                    "low": "299.00",
                    "close": "304.50",
                    "volume": "1234567",
                },
                {
                    "datetime": "2026-08-27",
                    "open": "297.00",
                    "high": "301.25",
                    "low": "296.50",
                    "close": "300.10",
                    "volume": "1200000",
                },
            ],
            "status": "ok",
        },
    )

    assert [bar.date.isoformat() for bar in bars] == ["2026-08-27", "2026-08-28"]
    assert bars[-1].close == 304.5
    assert bars[-1].volume == 1234567
    assert bars[-1].source == "Twelve Data time_series"


def test_twelve_data_time_series_refuses_error_payload() -> None:
    with pytest.raises(NormalizationError):
        normalize_twelve_data_time_series(
            "RHM.DE",
            {
                "code": 404,
                "message": "symbol not found: RHM.DE",
                "status": "error",
            },
        )


def test_fmp_grades_and_price_target_consensus_normalize() -> None:
    grades = normalize_fmp_grades_consensus(
        "AAPL",
        [{"symbol": "AAPL", "strongBuy": 1, "buy": 70, "hold": 32, "sell": 9,
          "strongSell": 0, "consensus": "Buy"}],
    )
    assert grades[0].rating == "Buy"
    assert grades[0].source == "FMP grades-consensus"

    targets = normalize_fmp_price_target_consensus(
        "AAPL",
        [{"symbol": "AAPL", "targetHigh": 400, "targetLow": 245, "targetConsensus": 330}],
    )
    assert targets[0].price_target == 330


def test_fmp_grades_consensus_refuses_an_empty_body_rather_than_scoring_it() -> None:
    """FMP answers [] for an ETF, and identically for a truncated or refused call.

    The two are indistinguishable from the payload, so the call fails and `S_S` is
    re-weighted as unavailable. Reading [] as "no analyst is bearish" would invent a
    consensus out of a provider gap.
    """

    with pytest.raises(NormalizationError):
        normalize_fmp_grades_consensus("SPY", [])


def test_fmp_economic_indicators_carry_the_preceding_release_as_previous() -> None:
    events = normalize_fmp_economic_indicators(
        [
            {"name": "CPI", "date": "2026-07-01", "value": 324.0},
            {"name": "CPI", "date": "2026-05-01", "value": 322.0},
            {"name": "CPI", "date": "2026-06-01", "value": 323.0},
        ],
        indicator="CPI",
    )

    assert [event.event_date.date().isoformat() for event in events] == [
        "2026-05-01",
        "2026-06-01",
        "2026-07-01",
    ]
    assert events[0].previous is None
    assert events[-1].actual == "324.0"
    assert events[-1].previous == "323.0"
    # No consensus is published on this endpoint, so no surprise may be implied.
    assert all(event.estimate is None for event in events)


def test_fmp_treasury_rates_split_into_the_ten_year_and_the_curve() -> None:
    series = normalize_fmp_treasury_rates(
        [
            {"date": "2026-08-27", "year2": 3.5, "year10": 4.1},
            {"date": "2026-08-28", "year2": 3.6, "year10": 4.3},
        ]
    )

    assert [event.actual for event in series["treasury_10y"]] == ["4.1", "4.3"]
    assert [event.actual for event in series["yield_curve"]] == ["0.6", "0.7"]


def test_alpha_vantage_put_call_ratio_reads_the_whole_chain_shape() -> None:
    """The live payload has no `data` key; the reading is the whole-chain ratio."""

    snapshots = normalize_alpha_vantage_put_call_ratio(
        "AAPL",
        {
            "symbol": "AAPL",
            "date": "2026-08-28",
            "put_call_ratio_full_chain": 0.74,
            "put_call_ratio_by_expiration": [{"date": "2026-09-04", "value": 0.61}],
        },
    )

    assert len(snapshots) == 1
    assert snapshots[0].put_call_ratio == 0.74
    assert snapshots[0].as_of.isoformat() == "2026-08-28"


def test_alpha_vantage_institutional_holdings_reads_the_holdings_key() -> None:
    changes = normalize_alpha_vantage_institutional_holdings(
        "AAPL",
        {
            "symbol": "AAPL",
            "holdings": [
                {
                    "holder_name": "Vanguard Group Inc",
                    "shares_held": "1380000000",
                    "shares_changed": "12000000",
                    "shares_changed_percentage": "0.88",
                    "change_type": "increase",
                    "last_reported": "2026-06-30",
                }
            ],
        },
    )

    assert changes[0].institution == "Vanguard Group Inc"
    assert changes[0].shares == 1380000000
    assert changes[0].shares_delta == 12000000
    assert changes[0].as_of.isoformat() == "2026-06-30"


def test_alpha_vantage_daily_and_daily_adjusted_share_one_bar_builder() -> None:
    payload = {
        "Time Series (Daily)": {
            "2026-08-27": {"1. open": "310.0", "4. close": "316.85", "6. volume": "30111222"},
            "2026-08-28": {"1. open": "316.8", "4. close": "319.7", "6. volume": "38649398"},
        }
    }

    bars = normalize_alpha_vantage_daily("AAPL", payload)

    assert [bar.close for bar in bars] == [316.85, 319.7]
    assert bars[0].source == "Alpha Vantage TIME_SERIES_DAILY"
    assert normalize_alpha_vantage_daily_adjusted("AAPL", payload)[0].source.endswith(
        "TIME_SERIES_DAILY_ADJUSTED"
    )


def test_a_throttle_notice_never_normalizes_into_an_empty_series() -> None:
    """Alpha Vantage answers a spent quota with HTTP 200 and an `Information` body."""

    throttled = {
        "Information": (
            "We have detected your API key as X and our standard API rate limit is "
            "25 requests per day."
        )
    }
    for normalizer, args in (
        (normalize_alpha_vantage_daily, ("AAPL", throttled)),
        (normalize_alpha_vantage_put_call_ratio, ("AAPL", throttled)),
        (normalize_alpha_vantage_institutional_holdings, ("AAPL", throttled)),
    ):
        with pytest.raises(NormalizationError):
            normalizer(*args)


def _form4_xml(
    *,
    code: str = "P",
    planned: str = "false",
    shares: str = "5000",
    price: str = "120.00",
) -> str:
    """Form 4 ownership document shaped from a real EDGAR payload (AAPL, X0609)."""

    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0609</schemaVersion>
    <documentType>4</documentType>
    <periodOfReport>2026-08-25</periodOfReport>
    <issuer>
        <issuerCik>0000320193</issuerCik>
        <issuerTradingSymbol>AAPL</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0001780525</rptOwnerCik>
            <rptOwnerName>Newstead Jennifer</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isOfficer>true</isOfficer>
            <officerTitle>SVP, GC and Secretary</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <aff10b5One>{planned}</aff10b5One>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>2026-08-25</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>{code}</transactionCode>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>{shares}</value></transactionShares>
                <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <postTransactionAmounts>
                <sharesOwnedFollowingTransaction><value>37229</value></sharesOwnedFollowingTransaction>
            </postTransactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>
"""


def test_form4_xml_normalizes_transaction_code_price_and_owner() -> None:
    rows = normalize_sec_form4_ownership_document(
        "AAPL", _form4_xml(), filing_date=date(2026, 8, 27), accession_number="0001140361-26-034741"
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == "AAPL"
    assert row.insider == "Newstead Jennifer"
    # A childless relationship element is falsy, so the title only survives if the
    # normalizer avoids guarding the lookup on truthiness.
    assert row.title == "SVP, GC and Secretary"
    assert row.raw["transactionCode"] == "P"
    assert row.shares == 5000.0 and row.price == 120.0
    assert row.value == pytest.approx(600_000.0)
    assert row.accession_number == "0001140361-26-034741"


def test_form4_10b5_1_flag_reaches_the_row_so_the_component_can_exclude_it() -> None:
    """The Rule 10b5-1 indicator is document-level, but exclusion reads per-row text.

    Without it being attached to the row, a planned sale scores as a discretionary
    open-market sale - the exact misread S_I exists to avoid.
    """

    from briefing_app.components.insider import classify_transaction

    planned = normalize_sec_form4_ownership_document(
        "AAPL", _form4_xml(code="S", planned="true"), filing_date=date(2026, 8, 27)
    )[0]
    assert "10b5-1" in (planned.raw.get("footnote") or "")
    assert classify_transaction(planned) == (None, "10b5-1 automated plan")

    discretionary = normalize_sec_form4_ownership_document(
        "AAPL", _form4_xml(code="S", planned="false"), filing_date=date(2026, 8, 27)
    )[0]
    assert classify_transaction(discretionary) == ("sell", None)


def test_form4_rendered_html_is_refused_rather_than_scraped() -> None:
    """A rendered body must raise, not return zero rows.

    EDGAR serves the source XML at the same accession path; scraping the rendering would
    emit insider numbers that look sourced.
    """

    with pytest.raises(NormalizationError, match="was not XML"):
        normalize_sec_form4_ownership_document(
            "AAPL", "<html><body><table><tr><td>Common Stock</td></tr></table></body></html>"
        )


def test_empty_form4_body_raises_instead_of_reading_as_no_activity() -> None:
    with pytest.raises(NormalizationError, match="empty"):
        normalize_sec_form4_ownership_document("AAPL", "   ")


def _fred_observations(rows: list[tuple[str, str]]) -> dict:
    return {
        "realtime_start": "2026-08-31",
        "observation_start": "1776-07-04",
        "count": len(rows),
        "observations": [
            {"realtime_start": "2026-08-31", "date": d, "value": v} for d, v in rows
        ],
    }


def test_fred_observations_normalize_with_previous_chained() -> None:
    events = normalize_fred_series_observations(
        _fred_observations([("2026-05-01", "331.0"), ("2026-06-01", "332.0"), ("2026-07-01", "332.8")]),
        series_id="CPIAUCSL",
    )
    assert [e.actual for e in events] == ["331.0", "332.0", "332.8"]
    # Each release carries the preceding one, which is what release_change_reading diffs.
    assert [e.previous for e in events] == [None, "331.0", "332.0"]
    assert events[0].source == "FRED" and events[0].country == "US"
    assert all(e.estimate is None for e in events), "FRED publishes no consensus estimate"


def test_fred_missing_observation_dot_is_skipped_not_read_as_zero() -> None:
    """FRED writes an absent observation as the literal string ".".

    Daily series carry these on market holidays. Coercing one to 0.0 would inject a
    fabricated rate collapse into the series a trend is computed from.
    """

    events = normalize_fred_series_observations(
        _fred_observations([("2026-08-27", "4.73"), ("2026-08-28", "."), ("2026-08-31", "4.75")]),
        series_id="DGS10",
    )
    assert [e.actual for e in events] == ["4.73", "4.75"]
    assert all(e.actual != "0.0" for e in events)


def test_fred_payload_without_observations_raises() -> None:
    """A malformed body must not read as an empty series."""

    with pytest.raises(NormalizationError):
        normalize_fred_series_observations({"error_code": 400}, series_id="CPIAUCSL")


def test_fred_release_dates_normalize_into_dated_calendar_events() -> None:
    events = normalize_fred_release_dates(
        {
            "count": 2,
            "release_dates": [
                {"release_id": 10, "date": "2026-09-10", "release_name": "Consumer Price Index"},
                {"release_id": 10, "date": "2026-08-12", "release_name": "Consumer Price Index"},
            ]
        }
    )
    assert [e.event_date.date().isoformat() for e in events] == ["2026-08-12", "2026-09-10"]
    assert events[0].name == "Consumer Price Index"
    assert events[0].importance == "scheduled"
    # Calendar entries carry no value - they are dates, not readings.
    assert all(e.actual is None for e in events)


def test_fred_single_release_rows_are_named_from_the_release_lookup() -> None:
    """A single-release query answers `{"release_id": 10, "date": ...}` with no name.

    The name has to come from `series/release`, or every calendar row reads "FRED
    release 10" - a number the reader cannot act on.
    """

    events = normalize_fred_release_dates(
        {"release_dates": [{"release_id": 10, "date": "2026-09-11"}]},
        release_name="Consumer Price Index",
    )

    assert [e.name for e in events] == ["Consumer Price Index"]


def _release_dates(name: str, *days: str) -> list:
    return normalize_fred_release_dates(
        {"release_dates": [{"release_id": "1", "date": day} for day in days]},
        release_name=name,
    )


def test_fred_macro_calendar_keeps_episodic_releases_and_drops_daily_ones() -> None:
    """H.15 publishes every business day. Twenty-one rows of it is not a catalyst list.

    Observed live 2026-09-02: release 18 schedules 21 future dates in a 30-day window
    while the CPI schedules one. Keeping both would bury the release that moves a name.
    """

    events = [
        *_release_dates("Consumer Price Index", "2026-09-11"),
        *_release_dates(
            "H.15 Selected Interest Rates",
            "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-08", "2026-09-09",
        ),
    ]

    calendar = build_fred_macro_calendar(
        events,
        as_of=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
        requested_start=date(2026, 9, 2),
        requested_end=date(2026, 10, 2),
    )

    assert [e.name for e in calendar.events] == ["Consumer Price Index"]
    assert calendar.validation_status is ValidationStatus.VERIFIED
    assert calendar.absence_is_evidence is True
    assert calendar.requested_start == date(2026, 9, 2)
    assert calendar.requested_end == date(2026, 10, 2)
    dropped = [i for i in calendar.diagnostics if i.code == "routine_release_excluded"]
    assert len(dropped) == 1
    assert "H.15 Selected Interest Rates" in dropped[0].detail


def test_fred_macro_calendar_with_nothing_fetched_is_unavailable() -> None:
    calendar = build_fred_macro_calendar([])

    assert calendar.validation_status is ValidationStatus.UNAVAILABLE
    assert calendar.absence_is_evidence is False
    assert "empty_calendar" in {issue.code for issue in calendar.diagnostics}


def test_fred_macro_calendar_of_only_routine_releases_is_partial_not_empty() -> None:
    """The provider answered; this reader declined to count the answer. Not a clean no."""

    calendar = build_fred_macro_calendar(
        _release_dates("H.15 Selected Interest Rates", "2026-09-03", "2026-09-04")
    )

    assert calendar.events == []
    assert calendar.validation_status is ValidationStatus.PARTIAL
    assert calendar.absence_is_evidence is False
    assert "all_releases_routine" in {issue.code for issue in calendar.diagnostics}


def test_fred_macro_calendar_drops_a_weekly_price_posting() -> None:
    """The boundary case, measured on 2026-09-02 rather than guessed.

    H.10 Foreign Exchange Rates, Spot Prices and NYMEX Natural Gas publish every 7 days.
    A weekly posting of a price the market can already see is the same category of thing
    as a daily one; keeping them put 14 rows in a 30-day window and pushed `event_risk`
    from 0.47 to its 1.0 ceiling.
    """

    calendar = build_fred_macro_calendar(
        _release_dates("Spot Prices", "2026-09-02", "2026-09-10", "2026-09-16", "2026-09-23")
    )

    assert calendar.events == []
    assert calendar.validation_status is ValidationStatus.PARTIAL
    assert "all_releases_routine" in {issue.code for issue in calendar.diagnostics}


def test_fred_macro_calendar_keeps_a_release_spaced_wider_than_a_week() -> None:
    """The Employment Situation lands twice in a 30-day window, 28 days apart."""

    calendar = build_fred_macro_calendar(
        _release_dates("Employment Situation", "2026-09-04", "2026-10-02")
    )

    assert len(calendar.events) == 2
    assert calendar.validation_status is ValidationStatus.VERIFIED


def test_fred_release_dates_empty_list_is_no_events_not_a_failure() -> None:
    """A monthly release simply has no date in most 30-day windows.

    FRED answers that with `count: 0` and an empty list. Reading it as a failed call puts
    "fred.release_dates failed validation" in the run log for a release that is fine.
    """

    assert normalize_fred_release_dates(
        {"realtime_start": "2026-09-02", "count": 0, "release_dates": []},
        release_name="Primary Commodity Prices",
    ) == []


def test_fred_release_dates_without_the_key_is_still_a_failed_call() -> None:
    """FRED's error body is a mapping with no `release_dates` at all. Not an empty calendar."""

    with pytest.raises(NormalizationError):
        normalize_fred_release_dates({"error_code": 400, "error_message": "Bad Request"})


def _finnhub_article(headline: str, *, summary: str = "", **overrides) -> dict:
    row = {
        "category": "company news",
        "datetime": 1756425600,
        "headline": headline,
        "id": 1,
        "related": "NVDA",
        "source": "Reuters",
        "summary": summary,
        "url": "https://example.test/article",
    }
    row.update(overrides)
    return row


def test_finnhub_company_news_scores_tone_locally_and_says_so() -> None:
    batch = normalize_finnhub_company_news(
        "nvda",
        [
            _finnhub_article("Nvidia beats estimates and raises guidance"),
            _finnhub_article("Nvidia cuts guidance on weak demand", id=2),
        ],
    )

    assert batch.ticker == "NVDA"
    assert "local tone" in batch.source, "a lexicon read must not pass as a vendor score"
    assert batch.articles[0].sentiment_score is not None
    assert batch.articles[0].sentiment_score > 0
    assert batch.articles[0].sentiment_label == "Bullish"
    assert batch.articles[1].sentiment_score < 0
    assert batch.articles[1].sentiment_label == "Bearish"
    assert batch.validation_status is ValidationStatus.VERIFIED


def test_finnhub_article_with_no_measurable_tone_scores_none_not_zero() -> None:
    """`_mean_sentiment` skips None and averages 0.0, so a neutral zero would dilute."""

    batch = normalize_finnhub_company_news(
        "NVDA", [_finnhub_article("Nvidia to present at a conference on Thursday")]
    )

    assert batch.articles[0].sentiment_score is None
    assert batch.articles[0].sentiment_label is None


def test_finnhub_company_news_drops_a_row_about_another_ticker_only() -> None:
    batch = normalize_finnhub_company_news(
        "NVDA",
        [
            _finnhub_article("Nvidia gains", related="NVDA,AMD"),
            _finnhub_article("Intel slides", related="INTC", id=2),
            _finnhub_article("Sector note", related="", id=3),
        ],
    )

    assert [a.title for a in batch.articles] == ["Nvidia gains", "Sector note"]


def test_finnhub_company_news_rejects_a_refusal_body() -> None:
    with pytest.raises(NormalizationError):
        normalize_finnhub_company_news(
            "NVDA", {"error": "You don't have access to this resource."}
        )


def test_finnhub_recommendation_trends_map_to_buy_hold_sell_counts() -> None:
    signals = normalize_finnhub_recommendation_trends(
        "NVDA",
        [
            {
                "buy": 12,
                "hold": 4,
                "period": "2026-08-01",
                "sell": 1,
                "strongBuy": 30,
                "strongSell": 0,
                "symbol": "NVDA",
            },
            {
                "buy": 10,
                "hold": 9,
                "period": "2026-07-01",
                "sell": 2,
                "strongBuy": 8,
                "strongSell": 1,
                "symbol": "NVDA",
            },
        ],
    )

    assert [s.as_of.isoformat() for s in signals] == ["2026-08-01", "2026-07-01"]
    assert signals[0].rating == "strong buy"
    assert signals[1].rating == "buy"
    assert signals[0].source == "Finnhub recommendation-trends"
    # A vendor score would not be comparable with the FMP feed this backs up.
    assert signals[0].action == "consensus"


def test_finnhub_recommendation_trends_skip_an_all_zero_month() -> None:
    signals = normalize_finnhub_recommendation_trends(
        "NVDA",
        [
            {"buy": 0, "hold": 0, "period": "2026-08-01", "sell": 0, "strongBuy": 0,
             "strongSell": 0, "symbol": "NVDA"},
            {"buy": 3, "hold": 1, "period": "2026-07-01", "sell": 0, "strongBuy": 2,
             "strongSell": 0, "symbol": "NVDA"},
        ],
    )

    assert [s.as_of.isoformat() for s in signals] == ["2026-07-01"]


# --- unparseable provider dates ------------------------------------------------------


def test_parse_date_raises_the_catchable_error_on_a_provider_sentinel() -> None:
    """Alpha Vantage answers `HISTORICAL_PUT_CALL_RATIO` with `"date": "latest"`.

    A bare `ValueError` from `fromisoformat` escapes every `except NormalizationError`
    in the pipeline and fails the whole ticker. The per-site `if not as_of` guards do
    not catch it either, because these are all truthy strings.
    """

    for sentinel in ("latest", "N/A", "-", "None", "0000-00-00"):
        with pytest.raises(NormalizationError) as excinfo:
            parse_date(sentinel)
        assert repr(sentinel) in str(excinfo.value)


def test_parse_datetime_raises_the_catchable_error_on_a_provider_sentinel() -> None:
    for sentinel in ("latest", "N/A", "-", "None", "0000-00-00"):
        with pytest.raises(NormalizationError) as excinfo:
            parse_datetime(sentinel)
        assert "unparseable datetime" in str(excinfo.value)
        assert repr(sentinel) in str(excinfo.value)


def test_parse_date_still_accepts_every_real_shape_and_absent_values() -> None:
    """The guard must not narrow what already parsed."""

    assert parse_date("2026-09-01") == date(2026, 9, 1)
    assert parse_date("2026-09-01 00:00:00") == date(2026, 9, 1)
    assert parse_date("20260901") == date(2026, 9, 1)
    assert parse_date("2026") == date(2026, 12, 31)
    assert parse_date(date(2026, 9, 1)) == date(2026, 9, 1)
    assert parse_date(datetime(2026, 9, 1, 12, tzinfo=UTC)) == date(2026, 9, 1)
    # Absent stays "today" - a row with no date is a shape callers already guard.
    assert parse_date(None) == datetime.now(UTC).date()
    assert parse_date("") == datetime.now(UTC).date()


def test_the_av_put_call_sentinel_now_degrades_the_leg_instead_of_the_ticker() -> None:
    """End to end: the real payload shape reaches the caller's `except NormalizationError`."""

    payload = {
        "symbol": "AAPL",
        "date": "latest",
        "put_call_ratio_full_chain": 0.47,
        "put_call_ratio_by_expiration": [{"date": "2026-09-04", "value": "0.25"}],
    }
    with pytest.raises(NormalizationError):
        normalize_alpha_vantage_put_call_ratio("AAPL", payload)
