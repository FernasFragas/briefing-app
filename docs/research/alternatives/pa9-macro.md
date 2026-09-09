# PA9 - Macro Readings And Calendar Alternative

Research date: 2026-08-31.

Scope: docs/archive/provider-alternatives-wiring-tasks.md PA9. This is a research note only; no
pipeline implementation is included. Cached payloads under `data/raw` were not used
as entitlement evidence.

## Local Premise Check

The PA9 premise holds, with one wiring nuance:

- `S_M` is scored from dated macro readings plus declared sector sensitivities. The
  live call path collects `macro_calendar`, then `macro_readings`, then passes both
  to `build_macro_component` (`src/briefing_app/pipeline.py:1245-1355`).
- The current readings source is FMP only at the call site. `_macro_readings_for_run`
  loops over `FMP_MACRO_INDICATORS` and calls `FmpClient.fetch_economic_indicator`;
  it calls `FmpClient.fetch_treasury_rates` for treasury factors
  (`src/briefing_app/pipeline.py:1627-1709`).
- The current factor map is:

| Factor | Current FMP series name |
|---|---|
| `policy_rate` | `federalFunds` |
| `cpi` | `CPI` |
| `inflation` | `inflationRate` |
| `unemployment` | `unemploymentRate` |
| `real_gdp` | `realGDP` |
| `retail_sales` | `retailSales` |

- `TREASURY_FACTORS` is `{"treasury_10y", "yield_curve"}` and the FMP normalizer
  derives those from `year10` and `year2` (`src/briefing_app/pipeline.py:147-148`,
  `src/briefing_app/providers/normalizers.py:756-790`).
- Alpha Vantage has a registry macro slot and client method
  (`config/source_registry.yaml:191-202`, `src/briefing_app/providers/alpha_vantage.py:224-252`),
  but I do not find an implemented FMP -> Alpha Vantage fallback in the current
  macro readings call site. The practical risk is therefore stronger than the task
  row says: FMP is not merely the effective sole source because AV refused in the
  audit; FMP is the only source the live readings path calls today.
- The macro calendar gap is real. `_macro_calendar_for_run` calls only FMP
  `economic-calendar`; the registry marks FMP `economics` as `required: false` and
  notes it is restricted on the current plan (`src/briefing_app/pipeline.py:1590-1625`,
  `config/source_registry.yaml:245-259`). No other macro calendar source is wired.

## Verdict

Adopt FRED for U.S. macro readings. It covers every current FMP macro indicator with
official or near-official series, and it removes the FMP readings single point of
failure. Use the U.S. Treasury XML feed as the preferred primary source for the
Treasury curve, with FRED Treasury series acceptable as a simpler secondary path.

FRED also closes the current app's macro-calendar gap if the required calendar is a
date/time calendar of scheduled releases for the next 30 days. It does not close a
full FMP-equivalent economic calendar with consensus estimates, prior values, impact
labels, and actuals in one endpoint. The app already scores readings from released
series, so the FRED calendar is sufficient for event-risk/calendar display, not for
consensus-surprise scoring.

## FRED Evaluation

Base URL: `https://api.stlouisfed.org/fred`.

Endpoint shapes:

- Series observations:
  `GET /series/observations?series_id={series_id}&observation_start={yyyy-mm-dd}&observation_end={yyyy-mm-dd}&file_type=json&api_key={FRED_API_KEY}`
- Inflation transform:
  same endpoint with `series_id=CPIAUCSL&units=pc1` for percent change from year ago.
- Series release metadata:
  `GET /series/release?series_id={series_id}&file_type=json&api_key={FRED_API_KEY}`
- Release dates:
  `GET /release/dates?release_id={release_id}&include_release_dates_with_no_data=true&file_type=json&api_key={FRED_API_KEY}`
- Browser calendar fallback:
  `https://fred.stlouisfed.org/releases/calendar`

Credential: free FRED account API key, proposed env var `FRED_API_KEY`.

Free-tier limits: official docs confirm every web-service request needs an API key
and that rate limiting returns HTTP 429, but I did not find a fixed current numeric
daily or per-minute cap in official FRED docs. Treat it as free but rate-limited:
budget conservatively, honor 429/Retry-After if present, and avoid baking in a
vendor-like daily quota.

License/redistribution: FRED API terms allow API use but push data-rights compliance
to the user because series can be owned by third parties. The app must display the
FRED notice from the terms if exposed to users. Current U.S. government-source series
are generally tagged on FRED as public-domain/citation-requested, but the safest
implementation should store source/citation metadata per series and avoid redistributing
bulk FRED data outside this self-hosted personal app without checking series notes.

Endpoint stability: official REST API, JSON/XML/CSV/XLSX on observations, standard
HTTP errors, no anti-bot behavior found in docs. Terms allow the St. Louis Fed to
change/suspend API access or limits. Release calendar dates come from source agencies
and may not equal FRED availability.

FRED mapping for current factors:

| Current factor | FRED source | Adoptability |
|---|---|---|
| `policy_rate` | `FEDFUNDS` Federal Funds Effective Rate; monthly, H.15/Federal Reserve source. Optional `DFF` if daily effective fed funds is desired later. | Adopt. Matches current FMP `federalFunds` better than a target-rate series. |
| `cpi` | `CPIAUCSL`, Consumer Price Index for All Urban Consumers: All Items; monthly, BLS source. | Adopt. Direct substitute for a CPI index level. |
| `inflation` | `CPIAUCSL` with FRED `units=pc1`, or app-computed YoY from the same series. | Adopt. Prefer this over annual World Bank `FPCPITOTLZGUSA`, which is too stale for a 45-day macro bound. |
| `unemployment` | `UNRATE`; monthly, BLS Employment Situation source. | Adopt. Direct substitute. |
| `real_gdp` | `GDPC1`; quarterly, BEA source. | Adopt. Direct substitute, but the 45-day staleness rule may drop it between quarterly releases unless the component treats quarterly cadence separately. |
| `retail_sales` | `RSAFS`; monthly, Census source. | Adopt. Direct substitute for advance retail sales. |
| `treasury_10y` | `DGS10` via FRED, or Treasury XML `BC_10YEAR`. | Adopt. Prefer Treasury XML as primary for the curve; FRED is fine as fallback. |
| `yield_curve` | Compute 10y minus 2y from Treasury XML or FRED `DGS10`/`DGS2`; FRED `T10Y2Y` is also available. | Adopt. Prefer computed spread from primary inputs to avoid depending on a derived FRED copyrighted series. |

Calendar usability:

- The browser release calendar lists release times and states all times are U.S.
  Central Time.
- `fred/series/release` maps a series to its release ID; `fred/release/dates` can
  include release dates with no data, including future release dates available in
  the FRED release calendar.
- This supports a 30-day date/time macro calendar for the current factors. It does
  not provide FMP-like consensus estimates or impact labels. Importance can be a
  local allowlist over the adopted factors/releases (`CPI`, `Employment Situation`,
  `GDP`, `Retail Sales`, `H.15/Federal Funds`) rather than provider-supplied.

FRED verdict: **adopt** for U.S. readings and date/time release calendar. It closes
the readings sole-provider risk. It closes the current date-only macro-calendar gap,
but not a consensus/actual/forecast economic-calendar product.

## U.S. Treasury Curve Source

Base URL: `https://home.treasury.gov`.

Endpoint shapes:

- Year:
  `GET /resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={yyyy}`
- Month:
  `GET /resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month={yyyymm}`
- All years:
  `GET /resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=all&page={zero_based_page}`

Credential: none.

Free-tier limits: no numeric request quota found on the feed page. The feed accepts
GET and uses standard HTTP response codes. The first page of an all-years request
returns 300 rows by default, so the app should request the current year/month or page
explicitly and cache by run date.

License/redistribution: official U.S. Treasury public web data; cite Treasury in
evidence rows. No vendor redistribution license was identified on the feed page.
For public/commercial redistribution, verify Treasury website policy before shipping.

Endpoint stability: official XML feed with documented data keys and pagination.
Daily Treasury Par Yield Curve Rates are available from 1990. XML parsing is extra
work versus FRED JSON, but this is the primary source behind the curve.

Treasury verdict: **adopt** for `treasury_10y` and `yield_curve`, preferably ahead
of FRED derived spreads when wiring the curve.

## ECB Data Portal

Base URL: `https://data-api.ecb.europa.eu/service`.

Endpoint shapes:

- Data:
  `GET /data/{flowRef}/{key}?startPeriod={period}&endPeriod={period}&format=csvdata`
- Examples:
  `GET /data/EXR/D.USD.EUR.SP00.A?startPeriod=2009-05-01&endPeriod=2009-05-31`
  and `GET /data/{flowRef}/{key}?lastNObservations=2`
- Metadata discovery:
  `GET /dataflow` and SDMX metadata resources under `/service/{resource}/...`

Credential: none for API data retrieval. An ECB Data Portal account is optional for
saved lists, dashboards, and notifications.

Free-tier limits: no fixed numeric rate limit found in official ECB Data Portal API
docs. The reuse policy says access can be restricted in exceptional circumstances,
so implement filtered requests and no unnecessary bulk polling.

License/redistribution: publicly available ESCB statistics may be reused free of
charge if the source is quoted and statistics/metadata are not modified. The policy
does not cover confidential data or third-party data without permission.

Endpoint stability: official SDMX REST service. It supports `startPeriod`,
`endPeriod`, `updatedAfter`, `lastNObservations`, `detail`, `includeHistory`, and
specific formats. ECB notes the older SDW redirection path was ending in 2025, so use
`data-api.ecb.europa.eu` directly.

Coverage: useful for future euro-area macro factors (`ecb_rate`, euro short-term
rate, euro-area GDP/unemployment/key indicators), but it is not a U.S. fallback for
the current PA9 factor set.

ECB verdict: **monitor** for EU macro expansion and eventual `ecb_rate` support.
Do not adopt as the PA9 U.S. readings fallback.

## Eurostat

Base URL: `https://ec.europa.eu/eurostat/api/dissemination`.

Endpoint shapes:

- Statistics API:
  `GET /statistics/1.0/data/{datasetCode}?lang=EN&lastTimePeriod={n}&{dimension}={code}`
- Example shape from docs:
  `GET /statistics/1.0/data/DEMO_R_D3DENS?lang=EN`
- SDMX 3.0:
  `GET /sdmx/3.0/data/dataflow/ESTAT/{datasetCode}/1.0?...`
- Async status/data for large extractions:
  `GET /1.0/async/status/{id}` and `GET /1.0/async/data/{id}`

Credential: none.

Free-tier limits: no key or numeric per-minute quota found. Eurostat documents
extraction-size limits: below 500,000 cells can be synchronous; 500,000 to 5,000,000
cells can be asynchronous; above 5,000,000 cells returns 413 and requires more
filtering. Fair-use rules can force async based on concurrent requests, request
counts, and cumulative extraction cost, so the app should request only narrow
country/aggregate/series windows.

License/redistribution: Eurostat authorizes commercial and non-commercial reuse of
statistical data, metadata, publications, and tools if the source is acknowledged,
subject to listed exceptions and individual copyright notices.

Endpoint stability: official EU API replacing older Eurostat web services; supports
JSON-stat, SDMX, TSV/CSV, and async extraction. The main operational risk is overly
broad queries, not anti-bot behavior.

Coverage: strong for EU/EA HICP, unemployment, GDP, and retail-trade readings. It
does not cover U.S. Federal Funds or U.S. Treasury curve, and it is not a dated
macro release calendar with consensus estimates.

Eurostat verdict: **monitor** for EU macro readings. Do not adopt as the PA9 U.S.
readings fallback; pair with ECB Data Portal when EU candidates need macro scoring.

## Dated Macro Calendar Candidate

Candidate: FRED Release Calendar.

Base URLs:

- Web: `https://fred.stlouisfed.org/releases/calendar`
- API: `https://api.stlouisfed.org/fred/series/release` plus
  `https://api.stlouisfed.org/fred/release/dates`

Credential: web calendar does not require an app credential; API calls require
`FRED_API_KEY`.

Free-tier limits: same as FRED API above; no fixed numeric limit found in official
docs, but HTTP 429 is documented.

License/redistribution: same FRED terms and series-owner caveat. Calendar output
should be cited as FRED/source-agency release calendar, not vendor consensus data.

Endpoint stability: official St. Louis Fed calendar. The web page has times; the
API release-dates endpoint is date-centric, so a robust implementation may need to
combine API release IDs with the calendar page or accept date-only events.

Verdict: **adopt** for the current 30-day macro event-risk calendar if date-only or
date/time events are enough. **Reject** as a substitute for FMP's full economic
calendar if consensus/forecast/previous/actual fields are required.

Non-free monitor: Trading Economics has a complete economic calendar API shape with
country/date filters, event, actual, previous, forecast, importance, and iCalendar
future exports. Current official docs require an API subscription; pricing showed a
paid Standard plan with 500 API requests/month and economic-calendar access. This is
not a free PA9 answer, but it is the clean paid fallback if FRED's calendar proves
too thin.

## Adoption Notes For PB9/I5/I10

- Add `providers/fred.py` with `credential_env = FRED_API_KEY` and cache one slot per
  FRED `series_id`, matching the current FMP one-slot-per-indicator pattern.
- Use FRED observations for the six current FMP indicators. Keep FMP as fallback and
  remove the misleading impression that Alpha Vantage is a live macro fallback unless
  a real AV macro path is added.
- Wire Treasury XML for curve factors or compute the spread from FRED `DGS10` and
  `DGS2`. Avoid using only FRED `T10Y2Y` when a primary-source curve can be parsed.
- Add a local release allowlist for event importance because FRED does not provide
  FMP-style impact labels.
- Revisit `macro_max_age_days` for quarterly GDP. The current 45-day bound is fine
  for monthly CPI/unemployment/retail sales and daily Treasury, but quarterly GDP can
  be structurally stale under that rule before the next release.

## Sources Checked

Local:

- `docs/archive/provider-alternatives-wiring-tasks.md`
- `docs/archive/provider-alternatives-implementation.md`
- `config/source_registry.yaml`
- `config/config.example.yaml`
- `src/briefing_app/pipeline.py`
- `src/briefing_app/providers/fmp.py`
- `src/briefing_app/providers/alpha_vantage.py`
- `src/briefing_app/providers/normalizers.py`
- `src/briefing_app/components/macro.py`

Web:

- FRED API keys: https://fred.stlouisfed.org/docs/api/api_key.html
- FRED API terms: https://fred.stlouisfed.org/docs/api/terms_of_use.html
- FRED API errors/rate limiting: https://fred.stlouisfed.org/docs/api/fred/errors.html
- FRED observations endpoint: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- FRED series release endpoint: https://fred.stlouisfed.org/docs/api/fred/series_release.html
- FRED release dates endpoint: https://fred.stlouisfed.org/docs/api/fred/release_dates.html
- FRED release calendar: https://fred.stlouisfed.org/releases/calendar
- FRED `FEDFUNDS`: https://fred.stlouisfed.org/series/FEDFUNDS
- FRED `CPIAUCSL`: https://fred.stlouisfed.org/series/CPIAUCSL
- FRED `UNRATE`: https://fred.stlouisfed.org/series/UNRATE
- FRED `GDPC1`: https://fred.stlouisfed.org/series/GDPC1
- FRED `FPCPITOTLZGUSA`: https://fred.stlouisfed.org/series/FPCPITOTLZGUSA
- FRED `RSAFS`: https://fred.stlouisfed.org/series/RSAFS
- FRED `DGS10`: https://fred.stlouisfed.org/series/DGS10
- FRED `T10Y2Y`: https://fred.stlouisfed.org/series/T10Y2Y
- U.S. Treasury daily interest-rate XML feed:
  https://home.treasury.gov/treasury-daily-interest-rate-xml-feed
- ECB Data Portal data API:
  https://data.ecb.europa.eu/help/api/data
- ECB Data Portal examples:
  https://data.ecb.europa.eu/help/api/data-examples
- ECB Data Portal content negotiation:
  https://data.ecb.europa.eu/help/api/content-negotiation
- ECB reuse policy:
  https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html
- Eurostat API getting started:
  https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started
- Eurostat Statistics API guide:
  https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started/api
- Eurostat asynchronous API and fair use:
  https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-detailed-guidelines/asynchronous-api
- Eurostat copyright/free reuse:
  https://ec.europa.eu/eurostat/help/copyright-notice
- Trading Economics calendar by country:
  https://docs.tradingeconomics.com/economic_calendar/country/
- Trading Economics iCalendar export:
  https://docs.tradingeconomics.com/economic_calendar/icalendar/
- Trading Economics get started/authentication:
  https://docs.tradingeconomics.com/get_started/
- Trading Economics rate limits:
  https://docs.tradingeconomics.com/get_started/rate-limits/
- Trading Economics pricing:
  https://tradingeconomics.com/api/pricing.aspx?source=basic-pricing-list
