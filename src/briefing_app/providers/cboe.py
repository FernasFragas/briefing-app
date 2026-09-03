from __future__ import annotations

from datetime import date

from briefing_app.models.market_data import OptionChain, OptionFilterConfig
from briefing_app.providers.base import BaseProviderClient, ProviderResponse
from briefing_app.providers.normalizers import normalize_cboe_option_chain


class CboeOptionsClient(BaseProviderClient):
    provider_id = "cboe"
    base_url = "https://cdn.cboe.com/api/global/delayed_quotes/options"

    def fetch_options_chain(
        self,
        ticker: str,
        *,
        run_date: date,
        cache_only: bool = False,
        fail_on_invalid: bool = True,
    ) -> ProviderResponse:
        clean_ticker = ticker.strip().upper()
        url = f"{self.base_url}/{clean_ticker}.json"
        return self.fetch_json_url(
            endpoint="delayed_options_chain",
            target=clean_ticker,
            url=url,
            run_date=run_date,
            required_json_paths=("data.options",),
            validation_provider_id="cboe_delayed_options",
            cache_only=cache_only,
            fail_on_invalid=fail_on_invalid,
        )

    def get_options_chain(
        self,
        ticker: str,
        *,
        run_date: date,
        filters: OptionFilterConfig | None = None,
        cache_only: bool = False,
    ) -> OptionChain:
        response = self.fetch_options_chain(
            ticker, run_date=run_date, cache_only=cache_only, fail_on_invalid=True
        )
        return normalize_cboe_option_chain(
            ticker,
            response.payload,
            filters=filters,
            endpoint_or_file=response.cache_path or response.url or "",
        )
