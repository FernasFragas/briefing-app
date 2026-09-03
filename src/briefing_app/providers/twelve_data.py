from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from briefing_app.providers.base import BaseProviderClient, ProviderResponse, require_credential


class TwelveDataClient(BaseProviderClient):
    """Twelve Data daily OHLCV client.

    This is the price-history fallback for FMP's free-plan symbol gates. The Basic plan
    is still metered, so requests go through `BaseProviderClient` and `RequestBudget`
    like the other keyed providers.
    """

    provider_id = "twelve_data"
    credential_env = "TWELVE_DATA_API_KEY"
    base_url = "https://api.twelvedata.com"

    def fetch_time_series(
        self,
        ticker: str,
        *,
        run_date: date,
        start_date: date | None = None,
        end_date: date | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        """Daily OHLCV history from `/time_series`."""

        clean_ticker = ticker.strip().upper()
        api_key = ""
        if not cache_only:
            api_key = require_credential(self.settings, self.credential_env, self.provider_id)
        params = {
            "symbol": clean_ticker,
            "interval": "1day",
            "apikey": api_key,
        }
        if start_date is not None:
            params["start_date"] = start_date.isoformat()
        if end_date is not None:
            params["end_date"] = end_date.isoformat()
        return self.fetch_json_url(
            endpoint="time_series",
            target=clean_ticker,
            url=f"{self.base_url}/time_series?{urlencode(params)}",
            run_date=run_date,
            required_json_paths=("values",),
            validation_provider_id=self.provider_id,
            cache_only=cache_only,
        )
