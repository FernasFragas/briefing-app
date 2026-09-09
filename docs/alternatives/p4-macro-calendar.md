# P4 — The macro calendar has a source

Implemented 2026-09-02. Closes the one row of the coverage matrix that had **never** had
a source: FMP `economic-calendar` answers HTTP 402 on this plan, so until now the only
dated macro event that could reach the briefing was one a human typed into
`manual_catalysts`. Research verdict: `pa9-macro.md`.

`FredClient.fetch_release_dates` already existed and was already verified — the ticket
was that the pipeline never read it into `macro_calendar`. That was true, and the wiring
was small. What was not in the ticket is the shape of the answer, which is where the work
went.

---

## What was probed, and on which run

Probed **2026-09-02** through the shipping client rather than `curl`, so the evidence
covers URL construction, the validator and the normalizers as well as the entitlement.

Two premises the implementation depends on, neither of them safe to assume:

| Question | Answer |
|---|---|
| Does `realtime_start`/`realtime_end` bound the dates returned? | **Yes.** Release 18 answers **2,493** dates for a ten-year window and **22** for the next thirty days |
| Does a forward window return dates that have not happened yet? | **Yes.** 21 of those 22 are in the future; `include_release_dates_with_no_data=true` is what puts them there |

The `limit` on this endpoint defaults to 10,000 and the widest window asked for here
returns 2,493, so nothing is truncated at either end.

The join is the one the ageing fix already makes: declared factor → FRED series →
`series/release` → `release/dates`, asked forwards instead of backwards.

| Series | Release | Median gap | In the calendar? |
|---|---|---|---|
| `FEDFUNDS`, `DGS10`, `DGS2` | 18 — H.15 Selected Interest Rates | 1 day | dropped |
| `T10Y2Y` | 304 — Interest Rate Spreads | 1 day | dropped |
| `DFII10` | 18 — H.15 | 1 day | dropped |
| `BAMLH0A0HYM2` | 209 — ICE BofA Indices | 1 day | dropped |
| `DTWEXBGS` | 17 — H.10 Foreign Exchange Rates | **7 days** | dropped |
| `DCOILBRENTEU`, `DCOILWTICO` | 212 — Spot Prices | **7 days** | dropped |
| `DHHNGSP` | 342 — NYMEX Natural Gas | **7 days** | dropped |
| `CPIAUCSL` | 10 — Consumer Price Index | monthly | kept |
| `GDPC1` | 53 — Gross Domestic Product | quarterly | kept |
| `UNRATE` | 50 — Employment Situation | 28 days | kept |
| `RSAFS` | 9 — Advance Monthly Retail Sales | monthly | kept |
| `PCOPPUSDM` | 365 — Primary Commodity Prices | monthly | kept (none scheduled this window) |

The last seven rows arrived with P5 later the same day, and they moved the threshold —
see **The boundary was wrong**, below.

## A routine posting is not a catalyst

That table is the finding. Most of the declared factors sit on releases that publish daily
or weekly. Loaded whole, a thirty-day calendar carries forty-two H.15 rows, or — after P5 —
fourteen commodity and FX price postings, and buries the two releases that actually move a
name.

So `build_fred_macro_calendar` groups events by release, takes the median spacing of each,
and drops any release publishing weekly or more often — with the reason recorded as an
`info` diagnostic naming the release and its cadence, not silently.

### The boundary was wrong, and P5 measured it

The rule first cut at *below* seven days, on the reasoning that weekly jobless claims are a
catalyst even though a daily rate posting is not. P5 mapped seven more factors and the
assumption did not survive contact with them:

```
BEFORE P5: 4 releases,  2 kept events,  event_risk 0.4667
AFTER  P5: 9 releases, 16 kept events,  event_risk 1.0000   <- saturated
```

The three new weekly releases — H.10 Foreign Exchange Rates, Spot Prices, NYMEX Natural
Gas — land on **exactly 7 days** and passed the test by one day. Every one of them is a
*price posting*: FRED republishing a price the market can already see continuously. What
separates a catalyst from a posting is not cadence but whether publication carries
information — CPI is unknown until it prints, a spot price is not — and cadence cannot see
that difference at exactly 7 days.

The threshold is now `<= 7`. The cost is stated rather than hidden: a genuinely traded
weekly *statistical* release would be excluded too. None is mapped today, and the trigger
to revisit — with a named exception list rather than another threshold — is the first one
that is.

## An empty window is an answer

Release 365 (Primary Commodity Prices, monthly) has no scheduled date inside most 30-day
windows, and FRED says so precisely:

```json
{"realtime_start": "2026-09-02", "realtime_end": "2026-10-02", "count": 0, "release_dates": []}
```

`validate_payload` counts an empty list as a missing required path, so this well-formed
answer raised `ProviderDataError` and every run logged
`fred.release_dates failed validation: missing` for a release that is working perfectly.
That is the exact confusion this repo exists to prevent, pointed the other way: not absence
mistaken for evidence, but evidence of absence mistaken for failure.

The guard is moved rather than dropped. The forward call requires `realtime_start`, which
every real response echoes and FRED's error body (`error_code` / `error_message`) does not,
so a genuine failure still raises. The historical ten-year window keeps the strict
`release_dates` requirement, because zero dates over ten years is not a plausible answer.
`normalize_fred_release_dates` draws the same line `_calendar_rows` draws: an empty list is
content, a missing key is a failed call.

The completeness contract is the same one the FMP calendar answers to. Nothing fetched is
`unavailable`; a window where every release was routine is `partial`, because the provider
answered and this reader chose not to count the answer.

## What the live path now produces

Run through `LiveDataSource._macro_calendar_for_run` on 2026-09-02 with
`config.example.yaml`, re-measured after P5 mapped all eleven series:

```
calendar: FRED release calendar   status: verified   window: 2026-09-02 -> 2026-10-02
  2026-09-11  Consumer Price Index
  2026-09-30  Gross Domestic Product
  [info] routine_release_excluded: H.15 Selected Interest Rates … every 1 day(s)
  [info] routine_release_excluded: Interest Rate Spreads … every 1 day(s)
  [info] routine_release_excluded: ICE BofA Indices … every 1 day(s)
  [info] routine_release_excluded: H.10 Foreign Exchange Rates … every 7 day(s)
  [info] routine_release_excluded: Spot Prices … every 7 day(s)
  [info] routine_release_excluded: Natural Gas Spot and Futures Prices (NYMEX) … every 7 day(s)
requests: series_release ×11, release_dates ×9   issues: none   event_risk: 0.4667
```

Nine of eleven series resolve to six routine releases and are excluded by name; two dated
catalysts remain. `event_risk` lands mid-scale rather than pegged — which it would not
without the cadence filter, since `event_risk` counts every macro entry as heavy regardless
of importance and saturates at roughly five entries in a 30-day horizon.

## Two things this does not close

1. **No consensus estimate.** FRED publishes a schedule, not a survey. `_surprise_readings`
   needs `actual` against `estimate`, and a release-date row carries neither, so it
   contributes nothing to `S_M`'s score — the readings path still does all the scoring.
   The calendar is for event risk and the dated table. This is exactly what `pa9-macro.md`
   predicted, and it is not a defect to fix later on a free plan.
2. **US only.** Every release here is a US agency's. EU names still have no macro calendar,
   which is the same wall PA5 hit.

## Two requests per release, not one

`release/dates` is now asked twice for the same release on the same run date — backwards
over ten years to date a reading by its publication, forwards over thirty days for what is
scheduled next. They cache as `<release_id>.json` and `<release_id>_upcoming.json`; the
`window` argument on the client exists for exactly that, because without it the forward
window would overwrite the historical one and the ageing join would read a file containing
only future dates.

The historical window still stops at the run date on purpose. A future release date
reaching back into `normalize_fred_series_observations` would stamp an already-published
reading with a publication that has not happened, and a negative age never reads as stale.

The `series/release` half of the join is resolved once per run date and shared by both
paths, so adding the calendar cost four requests, not eight. FRED now has a budget policy
(`daily_requests=None`, 0.5s pacing) — no daily quota is invented, because FRED publishes
none; the pacing is the conservative budgeting `pa9-macro.md` asked for.
