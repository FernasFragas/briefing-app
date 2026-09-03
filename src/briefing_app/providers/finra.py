from __future__ import annotations

from datetime import date

from briefing_app.providers.base import BaseProviderClient, ProviderResponse
from briefing_app.providers.normalizers import normalize_finra_short_volume


class FinraClient(BaseProviderClient):
    provider_id = "finra"
    base_url = "https://cdn.finra.org/equity/regsho/daily"

    def fetch_short_sale_volume(
        self,
        trade_date: date,
        *,
        run_date: date,
        market: str = "CNMS",
        cache_only: bool = False,
    ) -> ProviderResponse:
        clean_market = market.strip().upper()
        trade_stamp = trade_date.strftime("%Y%m%d")
        filename = f"{clean_market}shvol{trade_stamp}.txt"
        return self.fetch_text_url(
            endpoint="short_sale_volume",
            target=f"{clean_market}_{trade_stamp}",
            url=f"{self.base_url}/{filename}",
            run_date=run_date,
            cache_only=cache_only,
        )

    def get_short_sale_volume(
        self,
        trade_date: date,
        *,
        run_date: date,
        market: str = "CNMS",
        cache_only: bool = False,
    ):
        response = self.fetch_short_sale_volume(
            trade_date,
            run_date=run_date,
            market=market,
            cache_only=cache_only,
        )
        return normalize_finra_short_volume(response.payload)
