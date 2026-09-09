# PA9 addendum - Macro Without A FRED API Key

Research date: 2026-08-31. Extends `pa9-macro.md`, which adopted FRED. This note answers a
narrower question: **what if no FRED account is available?**

**Verdict: adopt `fredgraph.csv` as the keyless drop-in for readings. It is the same FRED
data from the same host with no account. The trade is that it is an undocumented download
path rather than a governed API, and it does not carry the release calendar.**

## First, the stakes are lower than they look

FMP `economic_indicators` and `treasury_rates` are both `ok` on the current key and are what
`S_M` scores from today. FRED was adopted for two reasons, neither of which is "the leg is
broken":

1. **Redundancy** - the only fallback in `providers.macro` is the dead Alpha Vantage slot.
2. **Source quality** - official primary data instead of an aggregator, which upgrades the
   `S_M` label.

So a FRED substitute is a second feed, not a rescue. Nothing regresses while this is open.

## Probed keyless, 2026-08-31

Every candidate below was requested without any account or key.

| Source | Result | Covers |
|---|---|---|
| **`fredgraph.csv`** | **HTTP 200** on all 8 adopted series | Everything PA9 adopted |
| **BLS public API v1** | **HTTP 200**, `REQUEST_SUCCEEDED` | CPI, unemployment |
| **US Treasury daily rates CSV** | **HTTP 200**, 168 rows, full curve | Treasury curve |
| **ECB Data Portal** | **HTTP 200**, SDMX-JSON | EU policy rate |
| DBnomics `/v22/series/FRED/{id}` | HTTP 404 | — (URL shape wrong; not pursued once FRED's own path worked) |

### `fredgraph.csv` in detail

```
GET https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL
observation_date,CPIAUCSL
...
2026-07-01,332.813
```

| Series | Factor | Rows | Latest observation |
|---|---|---|---|
| `FEDFUNDS` | `policy_rate` | 865 | 2026-07-01 = 3.63 |
| `CPIAUCSL` | `cpi`, `inflation` | 955 | 2026-07-01 = 332.813 |
| `UNRATE` | `unemployment` | 943 | 2026-07-01 = 4.1 |
| `GDPC1` | `real_gdp` | 318 | 2026-04-01 = 24269.613 |
| `RSAFS` | `retail_sales` | 415 | 2026-07-01 = 763602 |
| `DGS10` | `treasury_10y` | 16,869 | 2026-08-28 = 4.73 |
| `DGS2` | curve input | 13,109 | 2026-08-28 = 4.34 |
| `T10Y2Y` | `yield_curve` | 13,110 | 2026-08-31 = 0.41 |

That is a complete substitution for the readings half of PA9, with full history depth.

## What you give up, stated plainly

1. **It is not the documented API.** `fredgraph.csv` is the CSV download behind FRED's graph
   UI. It is not covered by the FRED API terms of use, carries no version guarantee, and can
   change without notice. It is a workaround with an unusually good risk profile - same host,
   same data, and it degrades *loudly* (an HTML error page or 404, not silent truncation) -
   but it is a workaround.
2. **No metadata.** The API returns units, frequency, seasonal adjustment and vintages;
   the CSV returns two columns. `inflation` as a year-over-year rate must be computed from
   `CPIAUCSL` locally rather than requested with `units=pc1`.
3. **No release calendar.** This is the real loss. PA9 wanted FRED partly to close the macro
   **calendar** gap that FMP's `paywalled` `economic-calendar` leaves. `fredgraph.csv` cannot
   serve `release/dates`, so **the calendar row of the coverage matrix stays open** on this
   path. See below.
4. **No rate limit is published**, because it is not a documented API. Treat it as a courtesy
   endpoint: one request per series per run, cached like every other source, never polled.

## The more-governed alternative

If depending on an undocumented path is unacceptable, the same coverage is reachable from
official APIs - it just takes three sources instead of one:

| Factor | Source | Keyless? |
|---|---|---|
| `cpi`, `inflation`, `unemployment` | **BLS public API v1** | Yes. v2 needs a free key and raises limits; v1 does not |
| `treasury_10y`, `treasury_2y`, `yield_curve` | **US Treasury daily rates CSV** | Yes - and `pa9-macro.md` already preferred Treasury as primary for the curve |
| `policy_rate`, `real_gdp`, `retail_sales` | Fed H.15 / BEA / Census | BEA needs a free key; the others are downloadable |
| EU leg | **ECB Data Portal** | Yes |

BLS v1 is documented as significantly more limited than v2 (fewer queries per day, shorter
history per request, no calculated series). **Those specific numbers were not verified in
this pass** and must be confirmed before wiring, per Phase A acceptance.

**Recommendation: `fredgraph.csv` for the readings, Treasury CSV for the curve.** Two keyless
sources, both official hosts, and the curve half is on a documented download that PA9 already
preferred anyway. Add BLS v1 later only if the FRED CSV path ever breaks.

## The calendar gap

Unchanged and still open on every keyless path. No free, dated, pan-agency macro calendar was
found without an account. The per-agency schedules (BLS, BEA, FOMC) are published as HTML
pages, so covering this means scraping several sites - the anti-bot/fragility class PA3
already rejected for RSS.

**Honest position: the macro calendar has no source.** It should be recorded as such via PC3
rather than left looking sourceable. A FRED account would close it (`release/dates` is a real
endpoint), which is the one concrete thing a key still buys.

## If you do get a FRED key later

Nothing here is wasted. The series ids are identical, so a `fredgraph.csv` client and a
FRED API client differ only in transport and metadata. Moving up is a client swap behind the
same normalizer, and it adds the release calendar.

## Evidence

- All statuses above from `scratchpad/macro_probe.py` and a follow-up per-series run,
  executed 2026-08-31 with no credentials in the request.
- FRED API docs were **not** reachable from this environment (403 to the fetcher, and `curl`
  could not connect to `stlouisfed.org` hosts at all), so the API's own terms and limits are
  cited from `pa9-macro.md`'s earlier research rather than re-verified here.
