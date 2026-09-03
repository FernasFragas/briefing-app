from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from briefing_app.providers.base import BaseProviderClient, ProviderResponse, require_credential


#: Factor to FRED series id, mirroring `FMP_MACRO_INDICATORS` so the two providers are
#: interchangeable behind the same `release_change_reading` call.
#:
#: Verified entitled on a free key, 2026-08-31: all eight returned HTTP 200 with full
#: history. `inflation` reuses `CPIAUCSL` with `units=pc1`, which is why it shares a series
#: id with `cpi` - FRED computes the year-over-year rate rather than making the app derive
#: it from the index level.
#:
#: The seven added 2026-09-02 close the last gap between what a sector declares a
#: sensitivity to and what any provider maps. Until then the commodity bucket had no
#: series behind it at all and could not score for any sector, and the policy bucket ran
#: on `policy_rate` and `yield_curve` alone.
#:
#: Verified by scoring rather than by status code: each was pulled through
#: `normalize_fred_series_observations` and `release_change_reading` and returned a real
#: trend. The distinction is load-bearing for `copper` - `PCOPPUSDM` is monthly, its
#: newest period was 63 days old against a 45-day bound, and it scores only because the
#: release-date join ages it from its 2026-08-17 publication instead of its period. On
#: HTTP 200 alone it would have been mapped here and then silently never scored.
FRED_MACRO_SERIES: dict[str, str] = {
    "policy_rate": "FEDFUNDS",
    "cpi": "CPIAUCSL",
    "inflation": "CPIAUCSL",
    "unemployment": "UNRATE",
    "real_gdp": "GDPC1",
    "retail_sales": "RSAFS",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "yield_curve": "T10Y2Y",
    # Added 2026-09-02. Releases 18, 209, 17, 212, 212, 365 and 342 respectively; brent
    # and wti share release 212, so the release-date join costs one request, not two.
    # Cadence measured rather than assumed, because it decides whether a factor also
    # appears as a dated event: 18 and 209 publish daily, and 17, 212 and 342 every
    # seven days, so the calendar drops all five as routine postings. Six of the seven
    # therefore score in `S_M` and never appear as calendar events - intended, not a
    # missing event. Only 365 (copper) can appear, and being monthly it often has no
    # date at all inside a 30-day window.
    "real_yields": "DFII10",
    "credit_spreads": "BAMLH0A0HYM2",
    "dollar": "DTWEXBGS",
    "brent": "DCOILBRENTEU",
    "wti": "DCOILWTICO",
    "copper": "PCOPPUSDM",
    "natural_gas": "DHHNGSP",
}

#: Factors requested as a year-over-year percentage change rather than a level.
FRED_PERCENT_CHANGE_FACTORS: frozenset[str] = frozenset({"inflation"})


class FredClient(BaseProviderClient):
    """Federal Reserve Bank of St. Louis FRED.

    Official primary data rather than an aggregator, which is what upgrades `S_M`'s
    source-quality label. Free with an account; the API advertises no rate-limit headers,
    so requests are kept to one per series per run and cached like every other source.

    There is also a keyless path (`fredgraph.csv`) serving the same series, documented in
    `docs/alternatives/pa9-macro-keyless-alternative.md`. It is not used here because a key
    is configured, and because only the keyed API serves the release calendar.
    """

    provider_id = "fred"
    credential_env = "FRED_API_KEY"
    base_url = "https://api.stlouisfed.org/fred"

    def _get(
        self,
        path: str,
        *,
        endpoint: str,
        target: str,
        run_date: date,
        params: dict[str, str],
        required_json_paths: tuple[str, ...],
        cache_only: bool = False,
    ) -> ProviderResponse:
        api_key = ""
        if not cache_only:
            api_key = require_credential(self.settings, self.credential_env, self.provider_id)
        query = urlencode({**params, "api_key": api_key, "file_type": "json"})
        return self.fetch_json_url(
            endpoint=endpoint,
            target=target,
            url=f"{self.base_url}/{path.lstrip('/')}?{query}",
            run_date=run_date,
            required_json_paths=required_json_paths,
            validation_provider_id=self.provider_id,
            cache_only=cache_only,
        )

    def fetch_series_observations(
        self,
        series_id: str,
        *,
        run_date: date,
        observation_start: date | None = None,
        units: str | None = None,
        cache_only: bool = False,
    ) -> ProviderResponse:
        """One macro series, oldest-first.

        `units="pc1"` asks FRED for the year-over-year percentage change, which is how
        `inflation` is sourced without deriving it from the CPI index locally.
        """

        params: dict[str, str] = {"series_id": series_id, "sort_order": "asc"}
        if observation_start is not None:
            params["observation_start"] = observation_start.isoformat()
        if units:
            params["units"] = units
        target = f"{series_id}_{units}" if units else series_id
        return self._get(
            "series/observations",
            endpoint="series_observations",
            target=target,
            run_date=run_date,
            params=params,
            required_json_paths=("observations",),
            cache_only=cache_only,
        )

    def fetch_release_dates(
        self,
        release_id: int | str,
        *,
        run_date: date,
        start: date | None = None,
        end: date | None = None,
        window: str | None = None,
        allow_empty: bool = False,
        cache_only: bool = False,
    ) -> ProviderResponse:
        """Scheduled dates for one release - the macro calendar FMP leaves paywalled.

        The realtime period bounds the dates returned, verified 2026-09-02: release 18
        (H.15) answers 2,493 dates for a ten-year window and 22 for the next thirty days,
        21 of them still in the future. So the same endpoint serves two different
        questions - which past publication carried a reading, and what is scheduled next -
        and `window` gives each its own cache slot, the way `units` does for observations.
        Without it the forward window would overwrite the historical one for the same
        release on the same run date.

        `allow_empty` is what makes those two questions differ in more than direction. A
        ten-year window with no release dates is not a plausible answer, so the historical
        call requires the list to be populated. A *thirty-day* window with none is routine
        - a monthly release like Primary Commodity Prices simply has no date this month,
        and FRED says so with `{"count": 0, "release_dates": []}`. Requiring a populated
        list there reports "nothing is scheduled" as a provider failure.

        The guard is moved rather than dropped: `realtime_start` is echoed by every real
        response including the empty one, and is absent from FRED's error body, so a
        genuine failure still raises instead of reading as an empty calendar.
        """

        params: dict[str, str] = {
            "release_id": str(release_id),
            "sort_order": "asc",
            "include_release_dates_with_no_data": "true",
        }
        if start is not None:
            params["realtime_start"] = start.isoformat()
        if end is not None:
            params["realtime_end"] = end.isoformat()
        return self._get(
            "release/dates",
            endpoint="release_dates",
            target=f"{release_id}_{window}" if window else str(release_id),
            run_date=run_date,
            params=params,
            required_json_paths=("realtime_start",) if allow_empty else ("release_dates",),
            cache_only=cache_only,
        )

    def fetch_series_release(
        self,
        series_id: str,
        *,
        run_date: date,
        cache_only: bool = False,
    ) -> ProviderResponse:
        """The release a series belongs to, so calendar entries can be joined to factors."""

        return self._get(
            "series/release",
            endpoint="series_release",
            target=series_id,
            run_date=run_date,
            params={"series_id": series_id},
            required_json_paths=("releases",),
            cache_only=cache_only,
        )
