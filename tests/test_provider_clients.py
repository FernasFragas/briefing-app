from __future__ import annotations

from datetime import date
import json
import tempfile
from pathlib import Path

import pytest

from briefing_app.http import HttpFetchResult
from briefing_app.providers import (
    AlphaVantageClient,
    ApeWisdomClient,
    CboeOptionsClient,
    FinnhubClient,
    FinraClient,
    FmpClient,
    ProviderDataError,
    TwelveDataClient,
)
from briefing_app.providers.budget import ProviderBudgetPolicy, RequestBudget
from briefing_app.providers.normalizers import normalize_alpha_vantage_put_call_ratio
from briefing_app.settings import AppSettings


class FakeFetcher:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        self.calls.append(url)
        body = json.dumps(self.payload).encode("utf-8")
        return HttpFetchResult(200, body, {"Content-Type": "application/json"}, url)


class FakeTextFetcher:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[str] = []

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        self.calls.append(url)
        return HttpFetchResult(
            200,
            self.text.encode("utf-8"),
            {"Content-Type": "text/plain"},
            url,
        )


class FailingFetcher:
    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        raise AssertionError("cache-only call should not hit network")


def test_cboe_client_fetches_writes_cache_and_replays() -> None:
    payload = {
        "timestamp": "2026-08-29 05:20:00",
        "data": {
            "current_price": 500,
            "options": [
                {
                    "option": "SPY260904C00500000",
                    "bid": 4,
                    "ask": 5,
                    "volume": 10,
                    "open_interest": 100,
                }
            ],
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp))
        client = CboeOptionsClient(settings=settings, fetcher=FakeFetcher(payload))
        response = client.fetch_options_chain("SPY", run_date=date(2026, 8, 29))
        assert response.validation.ok is True
        assert response.cache_path and Path(response.cache_path).exists()

        replay = CboeOptionsClient(settings=settings, fetcher=FailingFetcher()).get_options_chain(
            "SPY", run_date=date(2026, 8, 29), cache_only=True
        )
        assert replay.spot == 500
        assert len(replay.contracts) == 1


def test_alpha_vantage_client_requires_key_before_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = AlphaVantageClient(settings=make_settings(Path(tmp)))
        with pytest.raises(ProviderDataError) as exc:
            client.fetch_global_quote("IBM", run_date=date(2026, 8, 29))
        assert exc.value.status == "no_credentials"


def test_alpha_vantage_cache_only_replays_without_key() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp))
        client = AlphaVantageClient(settings=settings, fetcher=FailingFetcher())
        run_date = date(2026, 8, 29)
        client.cache.write_json(
            "alpha_vantage",
            "global_quote",
            run_date,
            "IBM",
            {"Global Quote": {"05. price": "189.50", "07. latest trading day": "2026-08-28"}},
        )

        response = client.fetch_global_quote("IBM", run_date=run_date, cache_only=True)

        assert response.validation.ok is True
        assert response.payload["Global Quote"]["05. price"] == "189.50"
        assert response.url and "apikey=" in response.url


def test_alpha_vantage_news_sentiment_requests_the_raised_limit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), alpha_vantage_api_key="av-key")
        fetcher = FakeFetcher({"feed": [{"title": "Nvidia expands platform"}]})
        client = AlphaVantageClient(settings=settings, fetcher=fetcher)

        response = client.fetch_news_sentiment("NVDA", run_date=date(2026, 8, 29))

        assert response.validation.ok is True
        assert "function=NEWS_SENTIMENT" in fetcher.calls[0]
        assert "tickers=NVDA" in fetcher.calls[0]
        assert "limit=1000" in fetcher.calls[0]


def test_fmp_cache_only_replays_without_key() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp))
        client = FmpClient(settings=settings, fetcher=FailingFetcher())
        run_date = date(2026, 8, 29)
        client.cache.write_json(
            "fmp",
            "quote",
            run_date,
            "AAPL",
            [{"symbol": "AAPL", "price": 230.1}],
        )

        response = client.fetch_quote("AAPL", run_date=run_date, cache_only=True)

        assert response.validation.ok is True
        assert response.payload[0]["price"] == 230.1
        assert response.url and "apikey=" in response.url


def test_twelve_data_time_series_fetches_writes_cache_and_replays_without_key() -> None:
    payload = {
        "meta": {"symbol": "AVGO", "interval": "1day"},
        "values": [
            {
                "datetime": "2026-08-28",
                "open": "300.10",
                "high": "305.20",
                "low": "299.00",
                "close": "304.50",
                "volume": "1234567",
            }
        ],
        "status": "ok",
    }
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), twelve_data_api_key="td-key")
        client = TwelveDataClient(settings=settings, fetcher=FakeFetcher(payload))
        run_date = date(2026, 8, 29)

        response = client.fetch_time_series(
            "AVGO",
            run_date=run_date,
            start_date=date(2026, 1, 1),
            end_date=run_date,
        )

        assert response.validation.ok is True
        assert response.cache_path and Path(response.cache_path).exists()
        assert "interval=1day" in response.url
        assert "start_date=2026-01-01" in response.url
        assert "end_date=2026-08-29" in response.url

        replay = TwelveDataClient(settings=make_settings(Path(tmp)), fetcher=FailingFetcher())
        cached = replay.fetch_time_series("AVGO", run_date=run_date, cache_only=True)

        assert cached.validation.ok is True
        assert cached.payload["values"][0]["close"] == "304.50"


def test_fmp_congress_latest_fetches_unfiltered_feeds() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        fetcher = FakeFetcher(
            [
                {
                    "symbol": "NVDA",
                    "type": "Purchase",
                    "transactionDate": "2026-08-20",
                }
            ]
        )
        client = FmpClient(settings=settings, fetcher=fetcher)
        run_date = date(2026, 8, 29)

        senate = client.fetch_senate_latest(run_date=run_date)
        house = client.fetch_house_latest(run_date=run_date)

        assert senate.validation.ok is True
        assert house.validation.ok is True
        assert "senate-latest?apikey=key" in fetcher.calls[0]
        assert "house-latest?apikey=key" in fetcher.calls[1]
        assert "symbol=" not in fetcher.calls[0] + fetcher.calls[1]
        assert "limit=" not in fetcher.calls[0] + fetcher.calls[1]
        assert "page=" not in fetcher.calls[0] + fetcher.calls[1]
        assert senate.cache_path and "senate_latest" in senate.cache_path
        assert house.cache_path and "house_latest" in house.cache_path


def test_apewisdom_client_fetches_writes_cache_and_replays() -> None:
    payload = {
        "results": [
            {
                "ticker": "NVDA",
                "mentions": 50,
                "mentions_24h_ago": 20,
                "upvotes": 120,
            }
        ]
    }
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp))
        run_date = date(2026, 8, 29)
        fetcher = FakeFetcher(payload)
        client = ApeWisdomClient(settings=settings, fetcher=fetcher)

        response = client.fetch_all_stocks(run_date=run_date)

        assert response.validation.ok is True
        assert fetcher.calls == [
            "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1"
        ]
        assert response.cache_path and Path(response.cache_path).exists()

        replay = ApeWisdomClient(settings=settings, fetcher=FailingFetcher()).fetch_all_stocks(
            run_date=run_date,
            cache_only=True,
        )
        assert replay.payload == payload


def test_finra_client_fetches_writes_cache_and_replays_short_volume() -> None:
    text = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260828|AAPL|1000|0|5000|Q\n"
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp))
        run_date = date(2026, 8, 29)
        fetcher = FakeTextFetcher(text)
        client = FinraClient(settings=settings, fetcher=fetcher)

        response = client.fetch_short_sale_volume(date(2026, 8, 28), run_date=run_date)
        assert response.validation.ok is True
        assert fetcher.calls[0].endswith("/CNMSshvol20260828.txt")

        replay = FinraClient(settings=settings, fetcher=FailingFetcher()).get_short_sale_volume(
            date(2026, 8, 28),
            run_date=run_date,
            cache_only=True,
        )
        assert replay[0].ticker == "AAPL"
        assert replay[0].short_volume == 1000


def make_settings(
    tmp: Path,
    *,
    alpha_vantage_api_key: str | None = None,
    fmp_api_key: str | None = None,
    fred_api_key: str | None = None,
    finnhub_api_key: str | None = None,
    twelve_data_api_key: str | None = None,
    provider_plans: dict[str, str] | None = None,
) -> AppSettings:
    return AppSettings(
        config_path=Path("config/config.example.yaml"),
        source_registry_path=Path("config/source_registry.yaml"),
        data_dir=tmp / "data",
        output_dir=tmp / "output",
        http_timeout_seconds=1,
        user_agent="briefing-app-test",
        alpha_vantage_api_key=alpha_vantage_api_key,
        fmp_api_key=fmp_api_key,
        fred_api_key=fred_api_key,
        finnhub_api_key=finnhub_api_key,
        twelve_data_api_key=twelve_data_api_key,
        provider_plans=provider_plans or {},
    )


def test_alpha_vantage_put_call_ratio_fetch_normalizes_from_cache() -> None:
    """The P/C normalizer had no fetcher producing its payload; this closes the pair."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp))
        run_date = date(2026, 8, 29)
        client = AlphaVantageClient(settings=settings, fetcher=FailingFetcher())
        client.cache.write_json(
            "alpha_vantage",
            "realtime_put_call_ratio",
            run_date,
            "NVDA",
            {
                "data": [
                    {
                        "date": "2026-08-28",
                        "put_volume": 900,
                        "call_volume": 1800,
                    }
                ]
            },
        )

        response = client.fetch_put_call_ratio("NVDA", run_date=run_date, cache_only=True)
        assert response.validation.ok is True

        snapshots = normalize_alpha_vantage_put_call_ratio("NVDA", response.payload)
        assert snapshots[0].ticker == "NVDA"
        assert snapshots[0].put_call_volume_ratio == pytest.approx(0.5)


def test_plan_gated_fmp_payload_fails_the_call_instead_of_returning_no_rows() -> None:
    """FMP answers a plan-gated endpoint with `Error Message: ACCESS DENIED` and HTTP 200."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        client = FmpClient(settings=settings, fetcher=FakeFetcher({"Error Message": "ACCESS DENIED"}))

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_institutional_ownership("AAPL", run_date=date(2026, 8, 29))

        assert exc.value.status == "paywalled"


def test_every_client_endpoint_is_declared_in_the_source_registry() -> None:
    """Preflight probes the registry, so an unregistered endpoint is never entitlement-checked.

    Data access is plan- and quota-gated and the failures are silent, so any endpoint a
    client can call must appear in the registry with its component and staleness bound -
    even when `probe_enabled` is false to protect a request budget.
    """
    import re

    import yaml

    registry = yaml.safe_load(Path("config/source_registry.yaml").read_text(encoding="utf-8"))
    registered = {
        endpoint.get("cache_endpoint", endpoint["id"])
        for source in registry["sources"]
        for endpoint in source.get("endpoints", [])
    }

    provider_dir = Path("src/briefing_app/providers")
    missing: list[str] = []
    for module in ("alpha_vantage", "apewisdom", "fmp", "cboe", "finra", "sec_edgar"):
        source = (provider_dir / f"{module}.py").read_text(encoding="utf-8")
        used = set(re.findall(r'cache_endpoint="(\w+)"', source))
        used |= set(re.findall(r'endpoint="(\w+)"', source))
        missing += [f"{module}.{name}" for name in sorted(used - registered)]

    assert missing == [], f"client endpoints absent from the source registry: {missing}"


def test_registry_endpoints_declare_a_component_and_cache_slot() -> None:
    import yaml

    registry = yaml.safe_load(Path("config/source_registry.yaml").read_text(encoding="utf-8"))
    incomplete = [
        f"{source['id']}.{endpoint['id']}"
        for source in registry["sources"]
        for endpoint in source.get("endpoints", [])
        if not endpoint.get("component") or not endpoint.get("cache_endpoint", endpoint.get("id"))
    ]
    assert incomplete == [], f"registry entries missing a component: {incomplete}"


def test_daily_request_budget_refuses_the_call_before_it_is_sent() -> None:
    """A spent quota must cost nothing and be named, not spent on a refusal notice."""

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), alpha_vantage_api_key="key")
        budget = RequestBudget(
            Path(tmp) / "budget",
            policies={"alpha_vantage": ProviderBudgetPolicy(daily_requests=2)},
        )
        fetcher = FakeFetcher({"Time Series (Daily)": {"2026-08-28": {"4. close": "10"}}})
        client = AlphaVantageClient(settings=settings, fetcher=fetcher, budget=budget)
        run_date = date(2026, 8, 29)

        client.fetch_daily("AAPL", run_date=run_date)
        client.fetch_daily("MSFT", run_date=run_date)

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_daily("NVDA", run_date=run_date)

        assert exc.value.status == "budget_exhausted"
        assert len(fetcher.calls) == 2, "the refused call must never reach the network"
        assert budget.remaining("alpha_vantage") == 0


def test_cache_only_replay_does_not_spend_the_request_budget() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp))
        budget = RequestBudget(
            Path(tmp) / "budget",
            policies={"alpha_vantage": ProviderBudgetPolicy(daily_requests=1)},
        )
        client = AlphaVantageClient(
            settings=settings, fetcher=FailingFetcher(), budget=budget
        )
        run_date = date(2026, 8, 29)
        client.cache.write_json(
            "alpha_vantage",
            "daily",
            run_date,
            "AAPL",
            {"Time Series (Daily)": {"2026-08-28": {"4. close": "10"}}},
        )

        for _ in range(3):
            client.fetch_daily("AAPL", run_date=run_date, cache_only=True)

        assert budget.spent("alpha_vantage") == 0


def test_free_plan_refuses_a_premium_endpoint_without_spending_a_request() -> None:
    """`TIME_SERIES_DAILY_ADJUSTED` is premium; asking anyway wastes 1 of 25 daily calls."""

    with tempfile.TemporaryDirectory() as tmp:
        settings = AppSettings(
            config_path=Path("config/config.example.yaml"),
            source_registry_path=Path("config/source_registry.yaml"),
            data_dir=Path(tmp) / "data",
            output_dir=Path(tmp) / "output",
            http_timeout_seconds=1,
            user_agent="briefing-app-test",
            alpha_vantage_api_key="key",
            fmp_api_key=None,
            provider_plans={"alpha_vantage": "free"},
        )
        budget = RequestBudget(Path(tmp) / "budget")
        fetcher = FakeFetcher({"Time Series (Daily)": {}})
        client = AlphaVantageClient(settings=settings, fetcher=fetcher, budget=budget)

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_daily_adjusted("AAPL", run_date=date(2026, 8, 29))

        assert exc.value.status == "plan_gated"
        assert fetcher.calls == []
        assert budget.spent("alpha_vantage") == 0


def test_observed_plan_gate_is_remembered_but_a_symbol_level_402_is_not() -> None:
    """A gated endpoint is worth never retrying; a 402 for one symbol is not.

    FMP answers both with HTTP 402, and its free plan serves some symbols and refuses
    others, so memoising a bare 402 would disable an endpoint that works elsewhere.
    """

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        budget = RequestBudget(Path(tmp) / "budget")
        run_date = date(2026, 8, 29)

        gated = FmpClient(
            settings=settings,
            fetcher=FakeFetcher(
                {"Error Message": "Restricted Endpoint: not available under your current subscription"}
            ),
            budget=budget,
        )
        with pytest.raises(ProviderDataError):
            gated.fetch_quote("AAPL", run_date=run_date)
        assert "quote" in budget.plan_gated_endpoints("fmp")

        other_budget = RequestBudget(Path(tmp) / "budget-2")
        symbol_gated = FmpClient(
            settings=settings, fetcher=HttpErrorFetcher(402), budget=other_budget
        )
        with pytest.raises(ProviderDataError) as exc:
            symbol_gated.fetch_quote("AVGO", run_date=run_date)
        assert exc.value.status == "paywalled"
        assert other_budget.plan_gated_endpoints("fmp") == set()


def test_fmp_targets_the_stable_api_not_the_retired_v3_and_v4_bases() -> None:
    """Keys issued after the `stable` migration get HTTP 403 on `/api/v3` and `/api/v4`."""

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        fetcher = FakeFetcher([{"symbol": "AAPL", "price": 1.0}])
        client = FmpClient(settings=settings, fetcher=fetcher, budget=RequestBudget(Path(tmp) / "b"))
        run_date = date(2026, 8, 29)

        client.fetch_quote("AAPL", run_date=run_date)
        client.fetch_historical_price_eod("AAPL", run_date=run_date)
        client.fetch_economic_indicator("CPI", run_date=run_date)
        client.fetch_analyst_ratings("AAPL", run_date=run_date)

        assert fetcher.calls, "no request was issued"
        for url in fetcher.calls:
            assert "/stable/" in url
            assert "/api/v3" not in url and "/api/v4" not in url


def test_fmp_statement_limit_stays_within_the_free_plan_ceiling() -> None:
    """`limit` above 5 is refused with a 402 that names the parameter, not the endpoint."""

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        fetcher = FakeFetcher([{"symbol": "AAPL", "date": "2026-06-30"}])
        client = FmpClient(settings=settings, fetcher=fetcher, budget=RequestBudget(Path(tmp) / "b"))
        run_date = date(2026, 8, 29)

        client.fetch_income_statement("AAPL", run_date=run_date)
        client.fetch_balance_sheet_statement("AAPL", run_date=run_date)
        client.fetch_cash_flow_statement("AAPL", run_date=run_date)
        # `period=quarter` is itself gated on analyst estimates, unlike the statements.
        client.fetch_analyst_estimates("AAPL", run_date=run_date)

        for url in fetcher.calls[:3]:
            assert "limit=5" in url
        assert "period=annual" in fetcher.calls[3]


class HttpErrorFetcher:
    def __init__(self, code: int) -> None:
        self.code = code

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        from urllib.error import HTTPError

        raise HTTPError(url, self.code, "Payment Required", {}, None)


class HttpErrorBodyFetcher:
    """Raises like `urlopen` does: the explanatory body hangs off the exception."""

    def __init__(self, code: int, body: str) -> None:
        self.code = code
        self.body = body

    def fetch(self, url: str, timeout_seconds: float, headers: dict[str, str]) -> HttpFetchResult:
        import io
        from urllib.error import HTTPError

        raise HTTPError(url, self.code, "Payment Required", {}, io.BytesIO(self.body.encode()))


def test_http_error_body_reaches_the_failure_notes() -> None:
    """`urlopen` raises on 402, so the provider's explanation is on the exception.

    Without it every refusal collapses to a bare status code, and FMP answers a gated
    endpoint, an uncovered symbol, a bad parameter and a spent quota all with one code.
    """

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        client = FmpClient(
            settings=settings,
            fetcher=HttpErrorBodyFetcher(
                402, "Restricted Endpoint: not available under your current subscription"
            ),
            budget=RequestBudget(Path(tmp) / "b"),
        )

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_stock_news("AAPL", run_date=date(2026, 8, 29))

        assert exc.value.status == "paywalled"
        assert any("Restricted Endpoint" in note for note in exc.value.notes)


def test_only_an_endpoint_gate_is_remembered_across_runs() -> None:
    """A symbol gate, a parameter gate and a spent quota must all stay retryable.

    FMP's free plan serves AAPL and refuses AVGO on the same endpoint, caps `limit` at 5
    on the statements, and answers an exhausted quota with a body that invites an upgrade.
    Remembering any of those would retire an endpoint that works.
    """

    forgettable = (
        ("symbol", "Premium Query Parameter: 'Special Endpoint : This value set for "
                   "'symbol' is not available under your current subscription"),
        ("parameter", "Premium Query Parameter: 'Special Parameters : The values for "
                      "'limit' must be between 0 and 5 based on your current subscription"),
        ("quota", "Error Message: Limit Reach . Please upgrade your plan"),
    )
    for label, body in forgettable:
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(Path(tmp), fmp_api_key="key")
            budget = RequestBudget(Path(tmp) / "budget")
            client = FmpClient(
                settings=settings, fetcher=HttpErrorBodyFetcher(402, body), budget=budget
            )
            with pytest.raises(ProviderDataError):
                client.fetch_quote("AVGO", run_date=date(2026, 8, 29))
            assert budget.plan_gated_endpoints("fmp") == set(), f"{label} gate was remembered"

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        budget = RequestBudget(Path(tmp) / "budget")
        client = FmpClient(
            settings=settings,
            fetcher=HttpErrorBodyFetcher(402, "Restricted Endpoint: not in your subscription"),
            budget=budget,
        )
        with pytest.raises(ProviderDataError):
            client.fetch_quote("AAPL", run_date=date(2026, 8, 29))
        assert budget.plan_gated_endpoints("fmp") == {"quote"}


def test_a_quota_refusal_sent_as_402_is_reported_as_throttled_not_paywalled() -> None:
    """The body outranks the status code when the two disagree.

    FMP reuses 402 for a gated endpoint, an uncovered symbol and a bad parameter, so the
    code alone cannot say whether a refusal clears on its own. Labelling a spent quota
    `paywalled` tells a reader to retire a source that works again at midnight.
    """

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        budget = RequestBudget(Path(tmp) / "budget")
        client = FmpClient(
            settings=settings,
            fetcher=HttpErrorBodyFetcher(
                402, '{"Error Message": "Limit Reach . Please upgrade your plan"}'
            ),
            budget=budget,
        )

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_quote("AAPL", run_date=date(2026, 8, 29))

        assert exc.value.status == "throttled"
        assert budget.plan_gated_endpoints("fmp") == set()


def test_a_throttled_response_never_retires_an_endpoint_however_it_is_worded() -> None:
    """Only an entitlement refusal may retire an endpoint; a rate refusal never can.

    A 429 body that upsells ("Upgrade your plan for higher limits") matches the plan-gate
    phrases without naming any quota term, so wording alone would remember it and disable
    a working endpoint until a human deleted the memo. HTTP 429 is a rate signal by
    definition, so the status decides.
    """

    bodies = (
        "Too Many Requests. Upgrade your plan for higher limits.",
        "Restricted Endpoint: not available under your current subscription",
    )
    for body in bodies:
        with tempfile.TemporaryDirectory() as tmp:
            settings = make_settings(Path(tmp), fmp_api_key="key")
            budget = RequestBudget(Path(tmp) / "budget")
            client = FmpClient(
                settings=settings, fetcher=HttpErrorBodyFetcher(429, body), budget=budget
            )

            with pytest.raises(ProviderDataError) as exc:
                client.fetch_quote("AAPL", run_date=date(2026, 8, 29))

            assert exc.value.status == "throttled", body
            assert budget.plan_gated_endpoints("fmp") == set(), body


#: Alpha Vantage answers a throttled CSV endpoint with HTTP 200, the genuine header, and
#: one row holding the refusal text spread a character per column and cut to the header's
#: width. It parses as valid CSV and contains no keyword any text check would catch.
THROTTLED_CSV = (
    "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\r\n"
    "I,n,f,o,r,m,a\r\n"
)


def test_a_csv_shaped_refusal_fails_instead_of_reading_as_an_empty_calendar() -> None:
    """An empty calendar is a claim about the world; this is a provider that said no.

    Reading the refusal as data would report "no earnings scheduled" for every ticker in
    the run, which is exactly the absence-is-not-evidence invariant the gate depends on.
    """

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), alpha_vantage_api_key="key")
        client = AlphaVantageClient(
            settings=settings,
            fetcher=FakeTextFetcher(THROTTLED_CSV),
            budget=RequestBudget(Path(tmp) / "b"),
        )

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_earnings_calendar("NVDA", run_date=date(2026, 8, 29))

        assert exc.value.status != "ok"


def test_a_throttled_text_body_is_not_accepted_as_data() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), alpha_vantage_api_key="key")
        client = AlphaVantageClient(
            settings=settings,
            fetcher=FakeTextFetcher("Our standard API rate limit is 25 requests per day"),
            budget=RequestBudget(Path(tmp) / "b"),
        )

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_earnings_calendar("NVDA", run_date=date(2026, 8, 29))

        assert exc.value.status == "throttled"


def test_a_refusal_never_overwrites_the_days_cached_payload() -> None:
    """The cache is the cache-only replay source, so a later refusal must not replace it.

    Providers answer a spent quota with HTTP 200, so an afternoon run on an exhausted
    budget would otherwise destroy the morning's good payload and replay the notice.
    """

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), alpha_vantage_api_key="key")
        run_date = date(2026, 8, 29)
        good = {"Time Series (Daily)": {"2026-08-28": {"4. close": "319.70"}}}

        morning = AlphaVantageClient(
            settings=settings,
            fetcher=FakeFetcher(good),
            budget=RequestBudget(Path(tmp) / "b1"),
        )
        morning.fetch_daily("AAPL", run_date=run_date)
        cached = morning.cache.path("alpha_vantage", "daily", run_date, "AAPL")
        assert cached.exists()

        afternoon = AlphaVantageClient(
            settings=settings,
            cache=morning.cache,
            fetcher=FakeFetcher({"Information": "Our standard API rate limit is 25 per day"}),
            budget=RequestBudget(Path(tmp) / "b2"),
        )
        with pytest.raises(ProviderDataError):
            afternoon.fetch_daily("AAPL", run_date=run_date)

        assert json.loads(cached.read_text()) == good, "the refusal overwrote good data"

        replayed = AlphaVantageClient(
            settings=settings, cache=morning.cache, fetcher=FailingFetcher()
        ).fetch_daily("AAPL", run_date=run_date, cache_only=True)
        assert replayed.payload == good


#: Every distinct refusal this project has actually seen from a provider, and what each
#: of the four consumers of a refusal must do with it.
#:
#: A refusal reaches four places here: the status, the notes, the plan-gate memo, and the
#: cache. Three separate bugs in this area were each a fix to one consumer mistaken for a
#: fix to the refusal, so they are asserted together rather than in four places.
#:
#: `http_code` is None for the bodies providers send with HTTP 200.
REFUSAL_SHAPES = (
    # label, http_code, body, status, retires_endpoint
    (
        "fmp endpoint gate",
        402,
        "Restricted Endpoint: not available under your current subscription",
        "paywalled",
        True,
    ),
    (
        "fmp symbol gate",
        402,
        "Premium Query Parameter: 'Special Endpoint : This value set for 'symbol' is "
        "not available under your current subscription",
        "paywalled",
        False,
    ),
    (
        "fmp parameter gate",
        402,
        "Premium Query Parameter: 'Special Parameters : The values for 'limit' must be "
        "between 0 and 5 based on your current subscription",
        "paywalled",
        False,
    ),
    ("fmp quota", 429, "Error Message: Limit Reach . Please upgrade your plan", "throttled", False),
    ("fmp quota sent as 402", 402, "Error Message: Limit Reach . Please upgrade your plan", "throttled", False),
    ("upsell worded 429", 429, "Too Many Requests. Upgrade your plan for higher limits.", "throttled", False),
)


@pytest.mark.parametrize(
    "label,http_code,body,status,retires", REFUSAL_SHAPES, ids=[s[0] for s in REFUSAL_SHAPES]
)
def test_every_refusal_shape_agrees_across_all_four_consumers(
    label, http_code, body, status, retires
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fmp_api_key="key")
        budget = RequestBudget(Path(tmp) / "budget")
        client = FmpClient(
            settings=settings,
            fetcher=HttpErrorBodyFetcher(http_code, body),
            budget=budget,
        )
        run_date = date(2026, 8, 29)

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_quote("AAPL", run_date=run_date)

        # 1. Status: what kind of refusal this is.
        assert exc.value.status == status, label
        # 2. Notes: the provider's own words survive, so a human can see the reasoning.
        assert any(body[:30] in note for note in exc.value.notes), label
        # 3. Memo: only a true endpoint gate may retire an endpoint until a human intervenes.
        assert bool(budget.plan_gated_endpoints("fmp")) is retires, label
        # 4. Cache: a refusal never occupies the cache-only replay slot.
        assert not client.cache.exists("fmp", "quote", run_date, "AAPL"), label


def test_a_two_hundred_bodied_refusal_agrees_across_the_same_four_consumers() -> None:
    """The HTTP 200 path must reach the same conclusions as the HTTP error path.

    Alpha Vantage sends a spent quota as HTTP 200 with an `Information` body, so this is
    the common case, not the exotic one.
    """

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), alpha_vantage_api_key="key")
        budget = RequestBudget(Path(tmp) / "budget")
        quota = "We have detected your API key as X and our standard API rate limit is 25 requests per day."
        client = AlphaVantageClient(
            settings=settings, fetcher=FakeFetcher({"Information": quota}), budget=budget
        )
        run_date = date(2026, 8, 29)

        with pytest.raises(ProviderDataError) as exc:
            client.fetch_daily("AAPL", run_date=run_date)

        assert exc.value.status == "throttled"
        assert any("25 requests per day" in note for note in exc.value.notes)
        assert budget.plan_gated_endpoints("alpha_vantage") == set()
        assert not client.cache.exists("alpha_vantage", "daily", run_date, "AAPL")


def test_fred_client_requests_observations_with_key_and_units() -> None:
    """`units=pc1` asks FRED for year-over-year inflation rather than deriving it here."""

    from briefing_app.providers.fred import FRED_MACRO_SERIES, FredClient

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fred_api_key="fred-key")
        fetcher = FakeFetcher({"observations": [{"date": "2026-07-01", "value": "3.3"}]})
        client = FredClient(settings=settings, fetcher=fetcher)
        client.fetch_series_observations(
            "CPIAUCSL", run_date=date(2026, 8, 31), units="pc1"
        )

    url = fetcher.calls[-1]
    assert "series_id=CPIAUCSL" in url
    assert "units=pc1" in url
    assert "api_key=fred-key" in url and "file_type=json" in url
    # inflation and cpi deliberately share a series id; `units` is the only difference,
    # so the cache target must not collide between them.
    assert FRED_MACRO_SERIES["inflation"] == FRED_MACRO_SERIES["cpi"]


def test_fred_units_variant_uses_its_own_cache_slot() -> None:
    from briefing_app.providers.fred import FredClient

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fred_api_key="fred-key")
        client = FredClient(
            settings=settings,
            fetcher=FakeFetcher({"observations": [{"date": "2026-07-01", "value": "3.3"}]}),
        )
        level = client.fetch_series_observations("CPIAUCSL", run_date=date(2026, 8, 31))
        pct = client.fetch_series_observations(
            "CPIAUCSL", run_date=date(2026, 8, 31), units="pc1"
        )

    assert level.cache_path != pct.cache_path, (
        "cpi level and inflation rate share a series id; one must not overwrite the other"
    )


def test_fred_release_dates_forward_window_uses_its_own_cache_slot() -> None:
    """One endpoint, two questions: which release carried a reading, and what is next.

    Both are `release/dates` for the same release id on the same run date, so without a
    distinct cache slot the forward window would overwrite the historical one and the
    ageing join would read a file containing only future dates.
    """

    from briefing_app.providers.fred import FredClient

    run_date = date(2026, 9, 2)
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fred_api_key="fred-key")
        fetcher = FakeFetcher({"release_dates": [{"release_id": 10, "date": "2026-09-11"}]})
        client = FredClient(settings=settings, fetcher=fetcher)
        history = client.fetch_release_dates(
            "10", run_date=run_date, start=date(2016, 9, 3), end=run_date
        )
        upcoming = client.fetch_release_dates(
            "10",
            run_date=run_date,
            start=run_date,
            end=date(2026, 10, 2),
            window="upcoming",
        )

    assert history.cache_path != upcoming.cache_path
    assert "realtime_start=2026-09-02" in fetcher.calls[-1]
    assert "realtime_end=2026-10-02" in fetcher.calls[-1]
    # A future date is only returned when FRED is asked to include dates with no data yet.
    assert "include_release_dates_with_no_data=true" in fetcher.calls[-1]


def test_fred_forward_window_accepts_an_empty_release_schedule() -> None:
    """A monthly release with no date this month is an answer, not an outage.

    The ten-year historical window keeps the strict guard, because zero dates there is not
    a plausible answer. Both still reject a payload that never reached the endpoint.
    """

    from briefing_app.providers.fred import FredClient

    run_date = date(2026, 9, 2)
    empty = {"realtime_start": "2026-09-02", "count": 0, "release_dates": []}
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), fred_api_key="fred-key")
        client = FredClient(settings=settings, fetcher=FakeFetcher(empty))
        upcoming = client.fetch_release_dates(
            "365", run_date=run_date, start=run_date, window="upcoming", allow_empty=True
        )
        assert upcoming.validation.ok

        with pytest.raises(ProviderDataError):
            client.fetch_release_dates("365", run_date=run_date, start=run_date)

    with tempfile.TemporaryDirectory() as tmp:
        gated = FredClient(
            settings=make_settings(Path(tmp), fred_api_key="fred-key"),
            fetcher=FakeFetcher({"error_code": 400, "error_message": "Bad Request"}),
        )
        with pytest.raises(ProviderDataError):
            gated.fetch_release_dates(
                "365", run_date=run_date, start=run_date, window="upcoming", allow_empty=True
            )


def test_fred_client_requires_key_before_network() -> None:
    from briefing_app.providers.fred import FredClient

    with tempfile.TemporaryDirectory() as tmp:
        client = FredClient(settings=make_settings(Path(tmp)), fetcher=FailingFetcher())
        with pytest.raises(ProviderDataError):
            client.fetch_series_observations("CPIAUCSL", run_date=date(2026, 8, 31))


def test_finnhub_company_news_requests_a_dated_window_and_caches() -> None:
    payload = [
        {
            "headline": "Chipmaker beats estimates",
            "summary": "Revenue ahead of consensus.",
            "source": "Reuters",
            "datetime": 1756425600,
            "url": "https://example.test/a",
            "related": "NVDA",
        }
    ]
    fetcher = FakeFetcher(payload)
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), finnhub_api_key="fh-key")
        client = FinnhubClient(settings=settings, fetcher=fetcher)
        response = client.fetch_company_news("NVDA", run_date=date(2026, 8, 31))

        replay = FinnhubClient(settings=settings, fetcher=FailingFetcher()).fetch_company_news(
            "NVDA", run_date=date(2026, 8, 31), cache_only=True
        )

    url = fetcher.calls[-1]
    assert "company-news?symbol=NVDA" in url
    assert "from=2026-08-24" in url and "to=2026-08-31" in url
    assert "token=fh-key" in url
    assert response.validation.ok
    assert replay.payload == payload


def test_finnhub_refuses_an_exchange_suffixed_symbol_before_spending_a_request() -> None:
    """The free tier is US-only, and RHM.DE 403s. Rediscovering that costs a request."""

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), finnhub_api_key="fh-key")
        client = FinnhubClient(settings=settings, fetcher=FailingFetcher())
        with pytest.raises(ProviderDataError) as excinfo:
            client.fetch_company_news("RHM.DE", run_date=date(2026, 8, 31))

    assert excinfo.value.status == "plan_gated"
    assert "US-only" in "; ".join(excinfo.value.notes)


def test_finnhub_still_serves_a_us_class_share_with_a_dot() -> None:
    """`BRK.B` is a US class share, not an exchange suffix. Refusing it is a false gate."""

    fetcher = FakeFetcher([{"headline": "Berkshire gains", "datetime": 1756425600}])
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), finnhub_api_key="fh-key")
        client = FinnhubClient(settings=settings, fetcher=fetcher)
        client.fetch_company_news("BRK.B", run_date=date(2026, 8, 31))

    assert "symbol=BRK.B" in fetcher.calls[-1]


def test_finnhub_recommendation_trends_url_and_cache_slot() -> None:
    fetcher = FakeFetcher(
        [{"symbol": "NVDA", "period": "2026-08-01", "strongBuy": 30, "buy": 10, "hold": 4}]
    )
    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(Path(tmp), finnhub_api_key="fh-key")
        client = FinnhubClient(settings=settings, fetcher=fetcher)
        response = client.fetch_recommendation_trends("NVDA", run_date=date(2026, 8, 31))

    assert "stock/recommendation?symbol=NVDA" in fetcher.calls[-1]
    assert response.endpoint == "recommendation_trends"
    assert response.cache_path is not None and "recommendation_trends" in response.cache_path


def test_finnhub_premium_endpoints_are_refused_on_a_free_plan() -> None:
    """`/news-sentiment`, `/price-target` and transcripts all answered 403 on the key."""

    with tempfile.TemporaryDirectory() as tmp:
        settings = make_settings(
            Path(tmp), finnhub_api_key="fh-key", provider_plans={"finnhub": "free"}
        )
        client = FinnhubClient(settings=settings, fetcher=FailingFetcher())
        for endpoint in ("news_sentiment", "price_target", "transcripts"):
            with pytest.raises(ProviderDataError) as excinfo:
                client._guard_request(endpoint)
            assert excinfo.value.status == "plan_gated"


def test_finnhub_client_requires_key_before_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        client = FinnhubClient(settings=make_settings(Path(tmp)), fetcher=FailingFetcher())
        with pytest.raises(ProviderDataError):
            client.fetch_company_news("NVDA", run_date=date(2026, 8, 31))
