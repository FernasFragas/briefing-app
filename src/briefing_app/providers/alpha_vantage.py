from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from briefing_app.providers.base import BaseProviderClient, ProviderResponse, require_credential


class AlphaVantageClient(BaseProviderClient):
    """Alpha Vantage, treated as a metered source.

    A free key allows 25 requests per day across all endpoints, so every call here is
    reserved against `RequestBudget` before it is sent. Endpoints observed to need a paid
    plan are refused up front rather than spending a request to be told so.
    """

    provider_id = "alpha_vantage"
    base_url = "https://www.alphavantage.co/query"
    credential_env = "ALPHA_VANTAGE_API_KEY"

    #: Verified against a free key: answers `This is a premium endpoint`. Endpoints that
    #: turn out to be plan-gated at runtime are learned and remembered by the budget, so
    #: this set only needs the ones worth never trying once.
    premium_endpoints = frozenset(
        {"daily_adjusted", "realtime_options", "historical_options"}
    )

    def fetch_function(
        self,
        function: str,
        *,
        target: str,
        run_date: date,
        params: dict[str, str] | None = None,
        cache_endpoint: str | None = None,
        required_json_paths: tuple[str, ...] = (),
        cache_only: bool = False,
        fail_on_invalid: bool = True,
        text: bool = False,
    ) -> ProviderResponse:
        api_key = ""
        if not cache_only:
            api_key = require_credential(self.settings, self.credential_env, self.provider_id)
        query = {"function": function, **(params or {}), "apikey": api_key}
        url = f"{self.base_url}?{urlencode(query)}"
        endpoint = cache_endpoint or function.lower()
        if text:
            return self.fetch_text_url(
                endpoint=endpoint,
                target=target,
                url=url,
                run_date=run_date,
                cache_only=cache_only,
                fail_on_invalid=fail_on_invalid,
            )
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

    def fetch_symbol_search(self, keywords: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        return self.fetch_function(
            "SYMBOL_SEARCH",
            target=keywords,
            run_date=run_date,
            params={"keywords": keywords},
            cache_endpoint="symbol_search",
            required_json_paths=("bestMatches",),
            cache_only=cache_only,
        )

    def fetch_global_quote(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "GLOBAL_QUOTE",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="global_quote",
            required_json_paths=("Global Quote",),
            cache_only=cache_only,
        )

    def fetch_daily(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        """Unadjusted daily OHLCV. The free-plan counterpart to `fetch_daily_adjusted`.

        Realized-volatility and expected-move maths run on close-to-close returns over a
        short window, where split/dividend adjustment rarely moves the reading, so this
        is a usable substitute when the adjusted series is out of plan.
        """

        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "TIME_SERIES_DAILY",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker, "outputsize": "compact"},
            cache_endpoint="daily",
            required_json_paths=("Time Series (Daily)",),
            cache_only=cache_only,
        )

    def fetch_daily_adjusted(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        """Split/dividend-adjusted daily series. Premium-only on Alpha Vantage."""

        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "TIME_SERIES_DAILY_ADJUSTED",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker, "outputsize": "compact"},
            cache_endpoint="daily_adjusted",
            required_json_paths=("Time Series (Daily)",),
            cache_only=cache_only,
        )

    def fetch_news_sentiment(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "NEWS_SENTIMENT",
            target=clean_ticker,
            run_date=run_date,
            params={"tickers": clean_ticker},
            cache_endpoint="news_sentiment",
            required_json_paths=("feed",),
            cache_only=cache_only,
        )

    def fetch_earnings_calendar(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "EARNINGS_CALENDAR",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker, "horizon": "3month"},
            cache_endpoint="earnings_calendar",
            cache_only=cache_only,
            text=True,
        )

    def fetch_realtime_options(self, ticker: str, *, run_date: date, cache_only: bool = False) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "REALTIME_OPTIONS",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="realtime_options",
            required_json_paths=("data",),
            cache_only=cache_only,
        )

    def fetch_historical_options(
        self,
        ticker: str,
        *,
        run_date: date,
        option_date: date | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        params = {"symbol": clean_ticker}
        if option_date is not None:
            params["date"] = option_date.isoformat()
        target = f"{clean_ticker}_{option_date.isoformat()}" if option_date else clean_ticker
        return self.fetch_function(
            "HISTORICAL_OPTIONS",
            target=target,
            run_date=run_date,
            params=params,
            cache_endpoint="historical_options",
            required_json_paths=("data",),
            cache_only=cache_only,
        )

    def fetch_put_call_ratio(
        self, ticker: str, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        """Current put/call ratio. Only meaningful as a percentile of its own history."""

        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "REALTIME_PUT_CALL_RATIO",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="realtime_put_call_ratio",
            # No `data` key on the real payload; the normalizer validates the shape.
            required_json_paths=(),
            cache_only=cache_only,
        )

    def fetch_economic_indicator(
        self,
        function: str,
        *,
        run_date: date,
        interval: str | None = None,
        maturity: str | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        params: dict[str, str] = {}
        if interval:
            params["interval"] = interval
        if maturity:
            params["maturity"] = maturity
        clean_function = function.strip().upper()
        target_parts = [clean_function]
        if interval:
            target_parts.append(interval)
        if maturity:
            target_parts.append(maturity)
        return self.fetch_function(
            clean_function,
            target="_".join(target_parts).lower(),
            run_date=run_date,
            params=params,
            cache_endpoint="macro",
            required_json_paths=("data",),
            cache_only=cache_only,
        )

    def fetch_insider_transactions(
        self, ticker: str, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "INSIDER_TRANSACTIONS",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="insider_transactions",
            required_json_paths=("data",),
            cache_only=cache_only,
        )

    def fetch_institutional_holdings(
        self, ticker: str, *, run_date: date, cache_only: bool = False
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        return self.fetch_function(
            "INSTITUTIONAL_HOLDINGS",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_endpoint="institutional_holdings",
            # No `data` key on the real payload; the normalizer validates the shape.
            required_json_paths=(),
            cache_only=cache_only,
        )
