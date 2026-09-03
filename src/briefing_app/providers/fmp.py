from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from briefing_app.providers.base import BaseProviderClient, ProviderResponse, require_credential


#: The free plan rejects `limit` above 5 on the statement endpoints with an HTTP 402 that
#: names the parameter, not the endpoint — so an over-large default looks exactly like a
#: gated endpoint and silently removes fundamentals from every run.
STATEMENT_LIMIT_FREE_PLAN = 5


class FmpClient(BaseProviderClient):
    """Financial Modeling Prep, on the `stable` API.

    The legacy `/api/v3` and `/api/v4` bases answer HTTP 403 for keys issued after the
    `stable` migration, so every endpoint here targets `stable` and uses its query-string
    symbol convention rather than the old path-segment one.
    """

    provider_id = "fmp"
    credential_env = "FMP_API_KEY"
    base_url = "https://financialmodelingprep.com/stable"
    #: Retired bases, kept only so a stale registry entry is recognisable in a diff.
    v3_base_url = "https://financialmodelingprep.com/api/v3"
    v4_base_url = "https://financialmodelingprep.com/api/v4"

    #: Verified against a free key: these answer `Restricted Endpoint` on HTTP 402.
    premium_endpoints = frozenset(
        {
            "economics",
            "stock_news",
            "insider_trades",
            "institutional_ownership",
            "form_13f",
            "sec_filings",
        }
    )

    def fetch_path(
        self,
        path: str,
        *,
        target: str,
        run_date: date,
        version: str = "stable",
        params: dict[str, str] | None = None,
        cache_endpoint: str | None = None,
        required_json_paths: tuple[str, ...] = ("root",),
        cache_only: bool = False,
        fail_on_invalid: bool = True,
    ) -> ProviderResponse:
        api_key = ""
        if not cache_only:
            api_key = require_credential(self.settings, self.credential_env, self.provider_id)
        base = {"v3": self.v3_base_url, "v4": self.v4_base_url}.get(version, self.base_url)
        query = urlencode({**(params or {}), "apikey": api_key})
        clean_path = path.lstrip("/")
        url = f"{base}/{clean_path}?{query}"
        endpoint = cache_endpoint or clean_path.replace("/", "_")
        return self.fetch_json_url(
            endpoint=endpoint,
            target=target,
            url=url,
            run_date=run_date,
            required_json_paths=required_json_paths,
            validation_provider_id=self.provider_id,
            cache_only=cache_only,
            fail_on_invalid=fail_on_invalid,
        )

    def fetch_quote(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "quote",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="quote",
            cache_only=cache_only,
        )

    def fetch_historical_price_eod(
        self,
        ticker: str,
        *,
        run_date: date,
        from_date: date | None = None,
        to_date: date | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        """Daily OHLCV history.

        This is the free-plan price-history path. Alpha Vantage's adjusted daily series
        is a premium endpoint, and its free daily series costs one of only 25 requests a
        day, so FMP leads for price bars.
        """

        clean_ticker = ticker.strip().upper()
        params = {"symbol": clean_ticker}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        if to_date is not None:
            params["to"] = to_date.isoformat()
        return self.fetch_path(
            "historical-price-eod/full",
            target=clean_ticker,
            run_date=run_date,
            params=params,
            cache_endpoint="historical_price_eod",
            cache_only=cache_only,
        )

    def fetch_economic_calendar(self, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        """Dated macro event calendar. Restricted on the free plan."""

        return self.fetch_path(
            "economic-calendar",
            target="macro",
            run_date=run_date,
            cache_endpoint="economics",
            cache_only=cache_only,
        )

    def fetch_economic_indicator(
        self, name: str, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        """One macro indicator series, e.g. `CPI`, `federalFunds`, `unemploymentRate`.

        Free-plan substitute for the restricted economic calendar: released values with
        their dates, which is what a macro surprise reading needs.
        """

        clean_name = name.strip()
        return self.fetch_path(
            "economic-indicators",
            target=clean_name.lower(),
            run_date=run_date,
            params={"name": clean_name},
            cache_endpoint="economic_indicators",
            cache_only=cache_only,
        )

    def fetch_treasury_rates(
        self,
        *,
        run_date: date,
        from_date: date | None = None,
        to_date: date | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        params: dict[str, str] = {}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        if to_date is not None:
            params["to"] = to_date.isoformat()
        return self.fetch_path(
            "treasury-rates",
            target="treasury",
            run_date=run_date,
            params=params,
            cache_endpoint="treasury_rates",
            cache_only=cache_only,
        )

    def fetch_stock_news(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "news/stock",
            target=clean_ticker,
            run_date=run_date,
            params={"symbols": clean_ticker, "limit": "50"},
            cache_endpoint="stock_news",
            cache_only=cache_only,
        )

    def fetch_senate_latest(
        self, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        return self.fetch_path(
            "senate-latest",
            target="all",
            run_date=run_date,
            cache_endpoint="senate_latest",
            cache_only=cache_only,
        )

    def fetch_house_latest(
        self, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        return self.fetch_path(
            "house-latest",
            target="all",
            run_date=run_date,
            cache_endpoint="house_latest",
            cache_only=cache_only,
        )

    def fetch_insider_trades(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "insider-trading/search",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="insider_trades",
            cache_only=cache_only,
        )

    def fetch_sec_filings(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "sec-filings-search/symbol",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="sec_filings",
            cache_only=cache_only,
        )

    def fetch_earnings_calendar(
        self,
        ticker: str,
        *,
        run_date: date,
        from_date: date | None = None,
        to_date: date | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        params = {"symbol": clean_ticker}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        if to_date is not None:
            params["to"] = to_date.isoformat()
        return self.fetch_path(
            "earnings-calendar",
            target=clean_ticker,
            run_date=run_date,
            params=params,
            cache_endpoint="earnings_calendar",
            cache_only=cache_only,
        )

    def fetch_analyst_estimates(
        self,
        ticker: str,
        *,
        run_date: date,
        # `period=quarter` is a gated parameter value on the free plan and 402s the whole
        # call; annual estimates are served. The statement endpoints accept quarter.
        period: str = "annual",
        limit: int = 10,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "analyst-estimates",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker, "period": period, "limit": str(limit)},
            cache_endpoint="analyst_estimates",
            cache_only=cache_only,
        )

    def fetch_analyst_ratings(
        self, ticker: str, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        """Aggregated buy/hold/sell counts across covering analysts."""

        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "grades-consensus",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="analyst_ratings",
            cache_only=cache_only,
        )

    def fetch_price_target_consensus(
        self, ticker: str, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        """Consensus price target. Pairs with the grade consensus for one S_S reading."""

        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "price-target-consensus",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="price_target_consensus",
            cache_only=cache_only,
        )

    def fetch_price_targets(
        self, ticker: str, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "price-target-summary",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="price_targets",
            cache_only=cache_only,
        )

    def fetch_income_statement(
        self,
        ticker: str,
        *,
        run_date: date,
        period: str = "quarter",
        limit: int = STATEMENT_LIMIT_FREE_PLAN,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "income-statement",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker, "period": period, "limit": str(limit)},
            cache_endpoint="income_statement",
            cache_only=cache_only,
        )

    def fetch_balance_sheet_statement(
        self,
        ticker: str,
        *,
        run_date: date,
        period: str = "quarter",
        limit: int = STATEMENT_LIMIT_FREE_PLAN,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "balance-sheet-statement",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker, "period": period, "limit": str(limit)},
            cache_endpoint="balance_sheet_statement",
            cache_only=cache_only,
        )

    def fetch_cash_flow_statement(
        self,
        ticker: str,
        *,
        run_date: date,
        period: str = "quarter",
        limit: int = STATEMENT_LIMIT_FREE_PLAN,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "cash-flow-statement",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker, "period": period, "limit": str(limit)},
            cache_endpoint="cash_flow_statement",
            cache_only=cache_only,
        )

    def fetch_institutional_ownership(
        self,
        ticker: str,
        *,
        run_date: date,
        limit: int = 100,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_path(
            "institutional-ownership/symbol-positions-summary",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker, "limit": str(limit)},
            cache_endpoint="institutional_ownership",
            cache_only=cache_only,
        )

    def fetch_13f_filings(
        self,
        cik: str,
        *,
        run_date: date,
        report_date: date | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_cik = str(cik).strip().lstrip("0") or str(cik).strip()
        params = {"cik": clean_cik}
        if report_date is not None:
            params["date"] = report_date.isoformat()
        target = f"{clean_cik}_{report_date.isoformat()}" if report_date else clean_cik
        return self.fetch_path(
            "institutional-ownership/extract",
            target=target,
            run_date=run_date,
            params=params,
            cache_endpoint="form_13f",
            cache_only=cache_only,
        )
