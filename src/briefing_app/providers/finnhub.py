from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

from briefing_app.providers.base import (
    PLAN_GATED,
    BaseProviderClient,
    ProviderDataError,
    ProviderResponse,
    require_credential,
)


#: Days of company news requested per ticker. `S_S` scores a 24-hour read against a
#: 7-day trailing baseline, so a shorter window would leave the baseline permanently
#: empty and the news leg permanently scored at level rather than delta.
COMPANY_NEWS_LOOKBACK_DAYS = 7


class FinnhubClient(BaseProviderClient):
    """Finnhub, on the free tier.

    Two endpoints, both probed against this project's key on 2026-08-31: company news
    returned HTTP 200 with 95 rows, and recommendation trends HTTP 200 with 4 rows.
    They serve two different gaps — the news leg had no working source at all, and the
    analyst leg had a single provider carrying the whole of `S_S`.

    The free tier does not score its own news. `normalize_finnhub_company_news` derives
    tone locally through `news_tone`, and labels it as locally derived.
    """

    provider_id = "finnhub"
    credential_env = "FINNHUB_API_KEY"
    base_url = "https://finnhub.io/api/v1"

    #: Probed HTTP 403 on the free key, 2026-08-31. No fetch method targets them; the
    #: set is what refuses one before a request if a method is ever added, and it is
    #: what preflight reads to report them as plan-gated rather than untried.
    premium_endpoints = frozenset({"news_sentiment", "price_target", "transcripts"})

    def fetch_company_news(
        self,
        ticker: str,
        *,
        run_date: date,
        lookback_days: int = COMPANY_NEWS_LOOKBACK_DAYS,
        cache_only: bool = False,
    ) -> ProviderResponse:
        """Company news for one ticker over a dated window.

        Articles carry no sentiment field on this tier; the normalizer supplies tone.
        """

        clean_ticker = self._require_us_symbol(ticker, "company_news")
        params = {
            "symbol": clean_ticker,
            "from": (run_date - timedelta(days=lookback_days)).isoformat(),
            "to": run_date.isoformat(),
        }
        return self._get(
            "company-news",
            endpoint="company_news",
            target=clean_ticker,
            run_date=run_date,
            params=params,
            cache_only=cache_only,
        )

    def fetch_recommendation_trends(
        self,
        ticker: str,
        *,
        run_date: date,
        cache_only: bool = False,
    ) -> ProviderResponse:
        """Analyst recommendation counts per bucket, newest month first.

        This is the second feed for the analyst leg. It reports buy/hold/sell counts,
        the same shape as FMP `grades-consensus` — not a vendor score, which would not
        be comparable with the feed it backs up. Finnhub's own price target is 403 on
        this tier, so target consensus stays sole-sourced on FMP.
        """

        clean_ticker = self._require_us_symbol(ticker, "recommendation_trends")
        return self._get(
            "stock/recommendation",
            endpoint="recommendation_trends",
            target=clean_ticker,
            run_date=run_date,
            params={"symbol": clean_ticker},
            cache_only=cache_only,
        )

    def _get(
        self,
        path: str,
        *,
        endpoint: str,
        target: str,
        run_date: date,
        params: dict[str, str],
        cache_only: bool = False,
    ) -> ProviderResponse:
        api_key = ""
        if not cache_only:
            api_key = require_credential(
                self.settings, self.credential_env, self.provider_id
            )
        query = urlencode({**params, "token": api_key})
        return self.fetch_json_url(
            endpoint=endpoint,
            target=target,
            url=f"{self.base_url}/{path.lstrip('/')}?{query}",
            run_date=run_date,
            required_json_paths=("root",),
            validation_provider_id=self.provider_id,
            cache_only=cache_only,
        )

    def _require_us_symbol(self, ticker: str, endpoint: str) -> str:
        """Refuse an exchange-suffixed symbol before the request is sent.

        The free tier is US-only: `stock/recommendation?symbol=RHM.DE` answered HTTP 403
        on 2026-08-31 while the same call for a US ticker returned 200. This is a
        permanent boundary rather than an outage, so spending a request to rediscover it
        every run buys nothing.

        Only a suffix longer than one character is treated as an exchange — US class
        shares are single letters (`BRK.B`), and refusing those would be a false
        positive. That leaves single-letter foreign suffixes such as London's `.L` to
        cost one request and report the provider's own refusal, which is the right way
        round: guard what is proven, never guess.

        The refusal is raised here rather than returned through `_response`, so it is
        never written to the plan-gate memo — the endpoint works, this symbol does not.
        """

        clean_ticker = ticker.strip().upper()
        _, separator, suffix = clean_ticker.rpartition(".")
        if separator and len(suffix) > 1:
            raise ProviderDataError(
                self.provider_id,
                endpoint,
                PLAN_GATED,
                (
                    f"Finnhub's free tier is US-only; {clean_ticker} carries the "
                    f"exchange suffix .{suffix} and is refused with HTTP 403. "
                    "Not requested.",
                ),
            )
        return clean_ticker
