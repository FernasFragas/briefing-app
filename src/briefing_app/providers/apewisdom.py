from __future__ import annotations

from datetime import date

from briefing_app.providers.base import BaseProviderClient, ProviderResponse


class ApeWisdomClient(BaseProviderClient):
    """Public ApeWisdom attention feed used for retail momentum."""

    provider_id = "apewisdom"
    base_url = "https://apewisdom.io/api/v1.0"

    def fetch_all_stocks(
        self,
        *,
        run_date: date,
        page: int = 1,
        cache_only: bool = False,
    ) -> ProviderResponse:
        return self.fetch_json_url(
            endpoint="retail_momentum",
            target=f"all_stocks_page_{page}",
            url=f"{self.base_url}/filter/all-stocks/page/{page}",
            run_date=run_date,
            required_json_paths=("results",),
            validation_provider_id=self.provider_id,
            cache_only=cache_only,
        )
