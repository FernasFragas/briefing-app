# Source Status

Snapshot from `output/preflight/preflight-2026-09-03T131058.260942Z0000.json`,
generated `2026-09-03T13:10:58.260942Z` by a credentialed **deep** run over all
50 registered endpoints. Status counts: 35 `ok`, 5 `paywalled`, 3 `synthetic`,
3 `registered`, 3 `browser_required`, 1 `manual_required`. Required hard failures: 0.

Two same-day code changes landed after that preflight and will be proven by the next
credentialed run: `alpha_vantage.realtime_put_call_ratio` is now optional because live
`S_O` uses CBOE plus persisted snapshots, and `fred.release_dates` /
`fred.series_release` are probe-enabled instead of only registered.

> ## Update — 2026-09-02: Alpha Vantage is **not** dead. Withdraw the headline below.
>
> Every AV claim in this file descends from one 2026-08-31 observation: four functions
> probed at 00:15 UTC all returned the 25/day notice, and the key had not reset. That was
> read as "AV refuses every function". **It was a spent daily quota, and the quota does
> reset** — which this file said had never been verified.
>
> Re-probed through the shipping client on 2026-09-02, one ticker (AAPL), after the reset:
>
> | Function | Result |
> |---|---|
> | `GLOBAL_QUOTE` | ✅ HTTP 200 |
> | `NEWS_SENTIMENT` | ✅ 50 articles, **all 50 vendor-scored**, per-ticker relevance |
> | `INSIDER_TRANSACTIONS` | ✅ 7,146 rows |
> | `INSTITUTIONAL_HOLDINGS` | ✅ 6,479 holdings |
> | `TIME_SERIES_DAILY` | ✅ 100 bars, newest 2026-09-01 |
> | `REALTIME_PUT_CALL_RATIO` | ✅ full chain 0.52, normalizes cleanly |
> | `EARNINGS_CALENDAR` | ⛔ the **only** refusal — degenerate CSV, correctly caught |
>
> So "**Alpha Vantage is down, not degraded**" below is withdrawn: it was degraded, on
> quota, and it recovered. The four "dead legs" attributed to AV need re-reading — their
> source is answering.
>
> **Q0 is closed.** `HISTORICAL_PUT_CALL_RATIO` returned a top-level sentinel
> `"date": "latest"`, but the endpoint contributes nothing over the app's self-built
> put/call baselines and spends one AV request per ticker. The scheduled path was removed
> from the config, source registry and Alpha Vantage client on 2026-09-02. The realtime
> variant is unaffected and remains separately registered.
>
> **Sector exposures are also closed for the PC1 live report.** The shipped
> `components.sector_exposures` now covers every sector used by the 24-ticker live report,
> and the fixed universe uses `Defense` consistently. Macro-only verification against the
> cached FRED raw data returned `s_m_unavailable=0` and `s_m_partial=0`.
>
> See `Q6` in `HANDOFF.md` for the remaining AV policy question.

> ## Update — 2026-08-31, end of day
>
> **Historical note, superseded by the regenerated 2026-09-03 table below.** The endpoint
> statuses below were accurate for the 2026-08-31 morning snapshot, but the *pipeline*
> changed substantially during the day and three claims went out of date:
>
> | Claim below | Now |
> |---|---|
> | "Preflight spends quota without metering it" | ✅ **Fixed.** `preflight.py` reserves budget before probing |
> | "SEC EDGAR ... the pipeline does not call it" | ✅ **Fixed for S_I.** EDGAR leads the insider chain, Form 4 from the primary record. S_F is still unwired and blocked by design |
> | "FINRA ... wired into nothing" | ✅ **Fixed.** FINRA leads `short_interest`; `short_borrow` scores as a labelled volume proxy |
>
> **FRED was new and not in the old 2026-08-31 table.** Added, wired as macro **primary**. The current
> shipped sector map uses only factors covered by `FRED_MACRO_SERIES`. Three registry endpoints
> (`series_observations`, `release_dates`, `series_release`); the first is probed on every
> preflight. A keyless path serving the same series is documented in
> `docs/research/alternatives/pa9-macro-keyless-alternative.md`.
>
> **Also fixed today:** `S_M` originally scored **one declared factor out of eleven** because
> both FMP and FRED date an observation by the period it measures rather than by when it was
> published — a CPI print two weeks old read as two months stale. Readings are now aged from
> the release calendar, the missing factor mappings have landed, and the 2026-09-02
> macro-only verifier read ten cached FRED factors.
>
> **~~Still true and still the headline:~~ Withdrawn 2026-09-02** — see the banner above.
> AV was on a spent daily quota, not refusing. `S_F` still has no working source, and that
> part is unchanged.
>
> This warning is now historical; the active summary table is regenerated from the
> 2026-09-03 deep preflight.

> ## Update — 2026-09-01
>
> **Finnhub was new and not in the old 2026-08-31 table.** Two registry endpoints, both probed
> through the shipping client on 2026-09-01: `company_news` (HTTP 200, 247 rows for NVDA)
> and `recommendation_trends` (HTTP 200, 4 monthly rows). Free tier is a rate limit
> (60/min) rather than a daily allowance, and is **US-only** — the client refuses an
> exchange-suffixed symbol before spending a request.
>
> | Leg | Now |
> |---|---|
> | News sentiment (`S_S`) | ✅ **Sourced.** Finnhub leads `news: [finnhub, alpha_vantage, fmp]`. The free tier does not score its own articles (`/news-sentiment` is 403), so tone is derived locally by `providers/news_tone.py` and labelled `local tone`. ~50% of articles carry a measurable score; the rest are excluded from the mean, never counted as neutral |
> | Analyst (`S_S`) | ✅ **No longer sole-provider for US names.** `analyst: [fmp, finnhub]`. Finnhub answers only when FMP produces nothing — merging would double-count the same analysts. EU names stay sole-sourced on FMP, which 402s both of them |
>
> Finnhub's `price-target`, `news-sentiment` and transcripts are 403 on this tier and are
> declared in `premium_endpoints`, so preflight reports them as plan-gated rather than
> untried. Full evidence: `docs/research/alternatives/pb3-finnhub-news-and-analyst.md`.

> ## Update — 2026-09-02
>
> **Twelve Data was new and not in the old 2026-08-31 table.** Registry endpoint
> `twelve_data.time_series` is wired for daily OHLCV after FMP and before Alpha Vantage:
> `prices: [fmp, twelve_data, alpha_vantage]`.
>
> The 2026-08-31 coverage probe recorded in `HANDOFF.md` settled A1 for the US gap:
> AVGO, ORCL, MU, QQQ, CRWV and AMAT resolve on the verified Twelve Data key. RHM.DE and
> LDO.MI returned the paid-plan message, so the EU remainder stays an A2 universe
> decision rather than a wiring task.
>
> The code now includes `providers/twelve_data.py`,
> `normalize_twelve_data_time_series`, a `RequestBudget` policy for 800 requests/day with
> 7.6s pacing, and a registry probe against AVGO. The 2026-09-03 deep preflight now
> includes this source in the active table.
>
> **The macro calendar now has a source, for the first time.** FMP `economic-calendar` is
> 402 and stays 402; `macro_calendar` is now built from FRED `release/dates`, which was
> verified months ago and simply never read. `fred.release_dates` is asked twice per
> release — backwards to date a reading, forwards for what is scheduled next — and caches
> as `<release_id>` and `<release_id>_upcoming`.
>
> What it does **not** carry is a consensus estimate, so it feeds event risk and the dated
> calendar table and contributes nothing to `S_M`'s score; the readings path still does all
> the scoring. The mapped daily/weekly releases are excluded from the calendar as routine
> postings with the cadence recorded by name as a diagnostic. Live on 2026-09-02 the window
> held two entries: CPI on 09-11 and GDP on 09-30, `event_risk` 0.47, no issues logged.
> FRED also gained a budget policy — no daily cap, since FRED publishes none, and 0.5s
> pacing. Evidence:
> `docs/research/alternatives/p4-macro-calendar.md`.

**Headline (withdrawn 2026-09-02): Alpha Vantage is refusing every function.** It was
throttled, on a spent daily quota, and it recovered when the quota reset — see the banner
at the top of this file. Kept here because the reasoning that produced it is instructive:
a quota refusal and an entitlement refusal are indistinguishable from one probe. Read
[Alpha Vantage is down, not degraded](#alpha-vantage-is-down-not-degraded) before
trusting any AV row elsewhere in this file.

## How to read a status

| Status | Meaning |
|---|---|
| `ok` | Reached, and the payload passed validation. |
| `registered` | Configured but not probed on this run: either the probe is disabled, or the endpoint is `probe_tier: deep` and the run was routine. |
| `paywalled` | Reached, and the provider refused it on the current plan. Read the notes: the refusal names whether the gate is on the **endpoint**, the **symbol**, or a **query parameter**. |
| `throttled` | Reached, and the provider refused it on quota or rate. Usually clears on its own; the Alpha Vantage section below is a historical example of why reset assumptions must be verified. |
| `manual_required` / `browser_required` | No fetchable endpoint exists; a capture file is the only path in. |

Endpoints carry a `required` flag. `required: false` marks one the current plan is not
expected to cover: it is still probed and still reports its true status, it just does not
fail preflight, so a known entitlement ceiling cannot mask a regression on a source the
pipeline actually depends on. `hard_failure_count` counts only `required` endpoints.

## Summary

| Source | Current status | Meaning | Fix or next step |
|---|---|---|---|
| CBOE delayed options | `ok` | Primary US per-strike options chain reached and validated. | No fix needed. CBOE carries live `S_O`; Tradier remains only a lower-priority failover candidate. |
| Alpha Vantage required endpoints | `ok` | Deep preflight verified `symbol_search`, `global_quote`, `daily`, `news_sentiment`, `earnings_calendar`, `insider_transactions`, `institutional_holdings`, `realtime_put_call_ratio`, and `macro`. | AV is alive but scarce: 25 requests/day. N4 keeps it as a metered fallback and promotes `NEWS_SENTIMENT` only for `news_alpha_vantage_shortlist`. |
| Alpha Vantage premium endpoints | `synthetic` (`required: false`) | `realtime_options`, `daily_adjusted`, and `historical_options` returned premium/sample payloads and were not cached. | Leave optional on the free plan. The live options and price paths have non-AV sources. |
| FRED | `ok` + `registered` | `series_observations` validated. `release_dates` and `series_release` were registered in this snapshot because probes were disabled then, while the live run exercised them. | Registry probes are now enabled for known CPI release ids; next preflight should move those two rows out of `registered`. |
| Finnhub | `ok` | `company_news` and `recommendation_trends` validated. | Carries broad-universe news/local tone and US analyst fallback. Free tier remains US-only. |
| Twelve Data | `ok` | `time_series` validated against AVGO, one of the FMP-gated US symbols. | Wired as the price-history fallback after FMP and before AV for AVGO, ORCL, MU, QQQ, CRWV, and AMAT. |
| FMP core | `ok` | Quote, historical EOD prices, economic indicators, treasury rates, SEC filings, analyst endpoints, statements, congressional feeds, and earnings calendar validated where entitled. | Still symbol-gated for several universe names; Twelve Data and Finnhub absorb the current US fallback paths. |
| FMP restricted | `paywalled` (`required: false`) | `economics`, `stock_news`, `insider_trades`, `institutional_ownership`, and `form_13f` are plan-gated on the current key. | FRED, Finnhub, and SEC EDGAR cover live macro/news/insider paths. `S_F` is declared permanently `n/a` rather than fetched. |
| ApeWisdom | `ok` | Keyless retail-attention feed validated. | Carries `retail_momentum` where the ticker appears; absence is a data-state `n/a`, not a provider outage. |
| FINRA short sale volume | `ok` | Consolidated daily short-volume file reached and validated. | Wired into `short_borrow` as a labelled short-volume proxy; still not short interest or borrow fee. |
| SEC EDGAR | `ok` | Ticker to CIK, company submissions, and a Form 4 document reached and validated. | Leads `S_I`. Set a real `BRIEFING_USER_AGENT`; the placeholder is still flagged in preflight notes. |
| SEC EDGAR 13F | `registered` (`required: false`) | Derived rather than a URL of its own: 13F bodies are assembled from filer submissions plus document fetches. | Blocked by design for `S_F`; see `docs/research/alternatives/pb1-13f-blocker.md`. |
| FCA short positions (UK) | `ok` | Plain XLSX download validated. | Deferred because the current universe has zero UK issuers. |
| Bundesanzeiger net shorts | `browser_required` | German net-short register still requires browser/manual capture. | Drop a capture into `data/manual/bundesanzeiger/net_short_positions/`. |
| Eurex manual options capture | `manual_required` | No capture files are present for EU per-strike options. | Fill `schemas/eurex_options_manual_capture.csv` and drop captures into `data/manual/eurex/manual_options_capture/`. |
| EU filings (MAR Art. 19, major holdings) | `browser_required` | No pan-EU API is available; issuer/register captures remain required. | Drop captures into `data/manual/eu_oam/mar_article_19/` and `.../major_holdings/`. |

## Alpha Vantage is down, not degraded

Four functions probed three seconds apart at 00:15 UTC — `GLOBAL_QUOTE`,
`HISTORICAL_PUT_CALL_RATIO`, `REALTIME_PUT_CALL_RATIO`, `CONGRESS_TRADES` — all returned
the same body:

```text
We have detected your API key as ... and our standard API rate limit is 25 requests
per day. Please subscribe to any of the premium plans ...
```

Spacing the calls matters: fired back to back, AV answers with a *different* notice about
the one-request-per-second burst limit, which reads like a pacing problem rather than an
exhausted key. Three seconds apart, all four return the daily cap. The key is spent.

**It did not reset at UTC midnight.** This probe ran at 00:15 UTC on 2026-08-31, a fresh
UTC day, with the last request this app recorded at `2026-08-30T14:57Z`. A previous
version of this file promised "quota resets at UTC midnight"; that claim is withdrawn. A
rolling 24-hour window fits the evidence, but the honest statement is that the reset
behaviour is **unverified**, and nothing — not a cron schedule, not a preflight cadence —
may be built on an assumption about when the key comes back.

### Remaining legs with no live source

Several originally documented fallbacks were either the same spent AV quota or a
`paywalled` FMP endpoint. The rows below track what remains after the provider wiring pass:

| Leg | Primary | Fallback | Result (morning) | Now |
|---|---|---|---|---|
| News sentiment (S_S) | AV `NEWS_SENTIMENT` | FMP `news/stock` | both refused — **no source** | ✅ **sourced** — Finnhub `company-news` leads; tone scored locally, ~50% of articles measurable |
| Insider (S_I) | AV `INSIDER_TRANSACTIONS` | FMP `insider-trading/search` | both refused; SEC EDGAR works but is unwired | ✅ **sourced** — EDGAR leads the chain |
| Institutional (S_F) | AV `INSTITUTIONAL_HOLDINGS` | FMP `institutional-ownership` | both refused; EDGAR 13F derived but unwired | ⛔ **declared permanently `n/a` 2026-09-02 (Q4)** — blocked by design, and now also declined rather than pending. Nothing is fetched and nothing is probed; the chain is `institutional: []` |
| Put/call percentiles (S_O) | AV `HISTORICAL_PUT_CALL_RATIO` | none — the call site returned `[]` | **no source** | ✅ **sourced** — self-built series, 20-session warm-up. Historical AV P/C removed from the scheduled path |
| Retail momentum (S_S) | none | none | no source and no call-site input | ✅ **sourced** — ApeWisdom keyless attention feed, **all 9 pages since 2026-09-03** (PC2) |
| Political flow (S_S) | none | none | no source | ✅ **sourced** — FMP `senate-latest`/`house-latest`, capped overlay |

The put/call *level* always computed: it is summed from the CBOE chain, not fetched. The
percentile baseline is now self-built from the app's own persisted snapshots rather than
fetched from anyone, and the historical Alpha Vantage P/C endpoint is no longer registered
or exposed by the client.

## Preflight spends quota without metering it — ✅ RESOLVED 2026-08-31

> Fixed: `preflight.py` now reserves against `RequestBudget` before probing, and a test
> asserts a metered probe increments the day's counter. The section below is kept as the
> record of what the defect was.

`preflight.py` fetches through `UrlLibFetcher` directly and never touches `RequestBudget`,
so the `budget.reserve` call in `providers/base.py` is bypassed. The credentialed run
behind this snapshot spent roughly 20 FMP requests and 1 Alpha Vantage request and wrote
**no** `data/provider_budget/2026-08-31.json` at all.

Consequences, in order of how much they cost:

- The budget ledger is a **floor, not a count**. `budget.remaining()` can report headroom
  on a key that is already dead, which is exactly what happened here.
- A metered key can be drained by preflight without a single recorded request. A
  `--deep` run costs twelve more Alpha Vantage requests of twenty-five.
- Any scheduling built on "the pipeline has N requests left today" is guessing.

Until this is fixed, read `data/provider_budget/` as a lower bound on spend, and treat a
live probe as the only evidence of whether a key can still answer.

## `ok` is an entitlement result, not a per-ticker promise

FMP's free plan gates **by symbol as well as by endpoint**, and answers HTTP 402 for
both. Verified in the same second on `quote` and `historical-price-eod/full`:

```text
200: AAPL MSFT NVDA LMT XOM SPY TSLA AMD GOOGL META JPM
402: AVGO ORCL MU QQQ
```

Two consequences:

- Every per-symbol FMP probe pins `probe_symbol: AAPL`, so it measures the entitlement
  rather than whether one ticker happens to be covered. An `ok` here does **not** mean
  every name in the universe resolves — the configured screen universe contains AVGO,
  ORCL and MU, all of which 402.
- A bare HTTP 402 must never be memoised as an endpoint-level plan gate. Preflight reads
  the refusal body and classifies it, because the three cases read identically from the
  status line alone:

| Provider body | Gate is on | What to do |
|---|---|---|
| `Restricted Endpoint: this endpoint is not available...` | the endpoint | Fall back to another source. |
| `Premium Query Parameter: ... this value set for 'symbol' ...` | the symbol | Nothing; the endpoint works for other names. |
| `Premium Query Parameter: ... 'limit' must be between 0 and 5` | a parameter | Fix the request, not the source. |
| `Error Message: Limit Reach . Please upgrade your plan` | **nothing** | A spent daily budget wearing plan-gate language. Reported as `throttled`, and it clears on its own — though FMP's reset timing has not been verified any more than Alpha Vantage's was. |

That last row is the trap: FMP describes an exhausted quota with the same "upgrade your
plan" wording it uses for a real entitlement ceiling. Quota phrasing is therefore tested
**before** any plan-gate classification, so a spent budget can never be recorded as a
permanent gate and retire a working source.

The status line is not authoritative either. The same endpoint has now shown four
meanings across two codes, so when the code says `paywalled` but the body names a quota,
the body wins and the status is downgraded to `throttled`. The reconciliation runs one
way only: a body never promotes a refusal *to* `paywalled`, because the costly error is
retiring a source that works, not retrying one that is genuinely gated.

**The status decides, the wording only narrows.** A refusal reaches a reader as both a
status and an explanation, and getting one of them right is not getting the refusal
right. So the two are derived together from a single decision: an HTTP 429 is a rate
signal by definition, and no wording in its body can make it read as a reason to retire
an endpoint. Relying on phrasing alone is what let "upgrade your plan" mean two opposite
things. The six shapes this API actually produces are pinned as a test:

| Code | Body | Status | Does the note say to fall back? |
|---|---|---|---|
| 402 | `Restricted Endpoint: ...` | `paywalled` | **Yes** — the only one |
| 402 | `... 'symbol' is not available` | `paywalled` | No — other tickers work |
| 402 | `... 'limit' must be between 0 and 5` | `paywalled` | No — fix the request |
| 429 | `Limit Reach . Please upgrade your plan` | `throttled` | No |
| 402 | `Limit Reach . Please upgrade your plan` | `throttled` | No |
| 429 | `Too Many Requests. Upgrade your plan for higher limits.` | `throttled` | No |

Rows 2 and 3 stay `paywalled` deliberately: a symbol or parameter gate really is an
entitlement refusal *for that call*, it just must not generalise to the endpoint.

## A fallback is not a fallback until it has been probed

The 2026-08-31 audit's real lesson is not that one provider broke. It is that the
fallback chains recorded in `config/source_registry.yaml` had never all been exercised on
the same day. Every note saying "Alpha Vantage carries this leg" was written while AV was
answering, and none of them survived contact with a key that stopped.

Of the sixteen legs the report reads, exactly **one** — filings — had two sources answer
on this run, and it is the only leg with redundancy left. The earnings calendar still
works, but only because FMP answered after AV failed: its redundancy is spent, not
intact. Everything else is single-sourced, unwired, or dead.

One of the sixteen base legs has never had a live source: `executive_tone` (0.35 of S_S).
Preflight cannot surface a leg that never scores, because it never fails a probe — it
renormalized its weight away in silence. **That silence is closed (Q1, 2026-09-02):** the
leg carries a permanent `n/a` reason naming the 402/403 behind it, and `S_S` states on
every run that it has no first-party issuer voice. The weight is still redistributed —
that was the decision, not the default — but redistribution can no longer promote a leg
past its nominal weight: `retail_momentum` is capped at 0.20 (Q3) and the news read is
capped at 0.25 of the institutional leg (Q1b). `retail_momentum` is now sourced from
ApeWisdom, and `political_flow` is sourced from FMP congressional disclosures as a capped
overlay.
The task list in
`docs/archive/provider-alternatives-wiring-tasks.md` carries the full coverage matrix and the work to
close it.

So: a registry note claiming a fallback is a hypothesis. It becomes a fact on the run
where both the primary and the fallback are probed and both answer.

## Permanently unavailable, by declaration (PC3)

Four legs are recorded here as **not going to be sourced**, so that a later audit stops
re-searching them. Each degrades with a named reason in the run output, and each has its
weight redistributed across the surviving components rather than scored as neutral. None
of them is a probe failure; three are not probed at all.

| Leg | Scope | Declared | Why it is permanent |
|---|---|---|---|
| `S_F` — 13F institutional flow | every ticker | 2026-09-02 (Q4) | A curated filer universe, a new table and a two-quarter diff are not justified by 0.10 of the US weight, and an aggregator was rejected because EDGAR is the primary record. Chain is `institutional: []` — nothing fetched, nothing probed. `pb1-13f-blocker.md` |
| `S_S.executive_tone` | every ticker | 2026-09-02 (Q1) | Earnings-call transcripts answer 402 on FMP and 403 on Finnhub on every free tier reachable here. Its framework weight of 0.35 is now **declared as 0.00** rather than re-normalized away per run, so the printed `S_S` table is the one the score uses. `pa10-executive-tone.md` |
| `S_S.institutional` — index and fund candidates | QQQ, SPY | 2026-09-03 (PC3) | Ratings, target revisions and price targets are published *about companies*. A basket has no issuer to publish them. Three providers agreed independently on 2026-09-03: FMP returned an empty root for SPY and HTTP 402 for QQQ, Finnhub an empty root for both. The requests are no longer sent. |
| `S_I` — index and fund candidates | QQQ, SPY | 2026-09-03 (PC3) | Form 4 and MAR Article 19 disclosures are filed by a company's own officers and directors, and a fund has none. "No Form 4 transactions available" read like a quiet filing week; it was a category error. No Form 4 lookup is attempted for these names. |

Index and fund candidates are recognised by `Candidate.is_index_or_etf` — a candidate
tradeable as `etf` but not as `shares` — so no universe file needs an edit to get this
treatment, and `S_S` for such a candidate is itself declared `n/a` (its only remaining
leg, retail attention, is capped at 0.20 and may not carry the component alone, per Q3).

## Throughput, which preflight cannot see

Preflight sends one request per endpoint, so it reports an entitlement and nothing else.
Live run `daily-2026-09-03-c7e82663` failed twice in a way no preflight would ever catch,
and both are now handled in `providers/base.py` and `providers/budget.py`:

| Failure | What happened | What was wired |
|---|---|---|
| **FMP HTTP 429 `Limit Reach`** | 15 of 23 names lost analyst coverage while the local counter read 208 of a configured 250 — and the previous day had closed at 240/250 with no refusal at all. Two full live runs plus a deep preflight shared one day's allowance. | The day's ceiling is **learned from the provider's own refusal** (`budget.note_quota_exhausted`) and written beside the counter, so the rest of the run — and any later run the same day — stops at the provider's number. Providers whose limit is a per-minute rate (`daily_requests=None`: Finnhub, FRED) are paced, never retired. |
| **FRED read timeouts** | Five calls timed out and all 23 scored names lost the reading: credit spreads and the dollar went undated, three releases lost their calendar lookahead. FRED's own budget showed 73 requests against no published cap, so nothing but the absence of a retry caused it. | Bounded retry with doubling backoff on transport faults only (`TimeoutError`, `URLError`). An HTTP refusal is never retried — it is the provider's considered reply. Every attempt reserves budget, so a retry meters (PB8). |
| **Alpha Vantage `EARNINGS_CALENDAR` malformed** | A degenerate CSV every time on a free key, re-sent per ticker because `malformed` is deliberately outside `ENTITLEMENT_STATUSES`. It spent the 25/day allowance that the news shortlist then needed. | After two identical refusals with a repeatable status, the endpoint is **parked for the run** and refused in the guard, before any request. In-memory and per-client, so it dies with the run. `missing` is excluded on purpose: an empty root is a property of QQQ and SPY, not of the endpoint. |

The cascade is the thing to remember: FMP's throughput limit disabled Alpha Vantage's
news leg, because AV was the earnings fallback and spent its day answering for FMP. **A
budget that meters requests but not runs will do this again with a different provider.**

## Provider limits worth knowing

- **Alpha Vantage free key: 25 requests/day, ~1 request/second.** Crossing either returns
  HTTP 200 with an `Information` notice, not an error status. The two notices differ —
  the daily cap names the key and the 25/day limit, the burst limit asks you to spread
  requests out — and only the first means the key is spent. **Reset timing is
  unverified**; see above.
- **A throttled Alpha Vantage CSV endpoint returns HTTP 200 and valid-looking CSV.** The
  header is genuine; the single data row holds the refusal text one character per column,
  truncated to the header's width, so `Information` arrives as `I,n,f,o,r,m,a`. It parses
  cleanly and no keyword check sees it, which would make a refusal read as "no earnings
  scheduled". Validation rejects any delimited body whose every data row is entirely
  single characters.
- **Alpha Vantage premium endpoints answer HTTP 200 with an artificial sample schema.**
  `REALTIME_OPTIONS`, `HISTORICAL_OPTIONS` and `TIME_SERIES_DAILY_ADJUSTED` are not on the
  free tier and return plausible-looking sample data, which validation reports as
  synthetic. CBOE covers US options; `TIME_SERIES_DAILY` covers price history.
- **A refusal is never cached.** Providers answer a spent quota with HTTP 200, so writing
  the cache before validating would replace the day's good payload with the notice — and
  that slot is what `--cache-only` replays. Preflight writes only on a passing validation
  and records `Not cached: a failed probe must not overwrite the day's payload.` The
  guard lives in `providers/base.py`; it was added after 47 invalid entries had already
  been written, which were purged on 2026-08-31.
- **~~`data/raw/alpha_vantage/` is empty.~~ No longer true (2026-09-02).** The purge did
  remove every entry — 37 throttle notices, 7 degenerate-CSV refusals, 3 premium sample
  payloads — but a later run repopulated it with **25 genuine payloads** (24
  `historical_put_call_ratio`, 1 `symbol_search`). Those are real data, not refusals, but
  the historical P/C payloads are now historical artifacts only: the endpoint has been
  removed from the scheduled path. The standing rule still holds and matters more now, not
  less: a cached payload is not evidence of entitlement unless its validation passed on the
  run that wrote it.
- **FMP free key: 250 requests/day.** Once spent, every endpoint answers
  `Error Message: Limit Reach`, which preflight reports as `throttled`, not `paywalled`.
- **Twelve Data Basic: 800 requests/day and 8 API credits/minute.** The wired
  `time_series` call requests one symbol at a time, so the default budget paces at 7.6s
  and reserves one request before each fallback call.
- **FMP `limit` caps at 5** on the three statement endpoints, and `analyst-estimates` is
  gated on `period`: `period=quarter` refuses at any limit, `period=annual` works at
  `limit=10`. Both refusals are HTTP 402 `Premium Query Parameter`, which looks like the
  whole endpoint is gated when only the request is.
- **Analyst ratings read `grades-consensus`, not `ratings-snapshot`.** The latter returns
  a vendor scoring model (`{rating: "B", overallScore, ...}`); S_S wants the actual
  analyst buy/hold/sell counts that `grades-consensus` returns.
- **FMP `/api/v3` and `/api/v4` are retired.** They answer HTTP 403 `Legacy Endpoint`
  regardless of key for subscriptions created after 2025-08-31. Every registry entry is
  on the `stable` API; a test asserts no probe targets the legacy bases.
- **SEC EDGAR wants a real contact.** `BRIEFING_USER_AGENT` is still the placeholder
  `contact@example.com`. EDGAR may throttle or block without warning, and it is currently
  the only working source for two components.

## Manual capture drop points

Manual and browser sources report whether their schema and a capture file exist, so the
status is actionable rather than only descriptive. Captures live under:

```text
data/manual/<cache_provider>/<cache_endpoint>/
```

`data/manual/` does not exist yet — no capture has ever been dropped.

## Local n8n Assistant Services

Not market-data sources, and **not re-verified in this run** — carried over from the
2026-08-30 audit:

| Service | Status as of 2026-08-30 | Fix or next step |
|---|---|---|
| n8n sandbox API | reachable and healthy from n8n | Use `http://sandbox-api:8080` and `N8N_SANDBOX_SERVICE_API_KEY`. |
| n8n sandbox runner | registered and executed a test command | Keep `sandbox-runner-1` internal and never expose its ports. |
| SearXNG | reachable from n8n and returns JSON results | Use `http://searxng:8080`. If upstream engines show CAPTCHA/rate-limit errors, tune SearXNG engines or use Brave Search. |
| Local Ollama for n8n Assistant | works only when host Ollama is running | Use `http://host.docker.internal:11434/v1`, API key `ollama`, and a model from `ollama list`. |

## Commands

`.env` holds **container** paths (`BRIEFING_DATA_DIR=/app/data`,
`BRIEFING_OUTPUT_DIR=/app/output`), so sourcing it wholesale before a local run sends the
report to a directory that does not exist on the host and silently leaves
`output/preflight/latest.json` untouched. Export only the keys:

```bash
export ALPHA_VANTAGE_API_KEY=$(grep '^ALPHA_VANTAGE_API_KEY=' .env | cut -d= -f2-)
export FMP_API_KEY=$(grep '^FMP_API_KEY=' .env | cut -d= -f2-)
```

Without those exported, every keyed endpoint reports `no_credentials` — which looks like a
configuration failure but only means the shell had no keys.

Routine preflight — note that this spends real quota without recording it:

```bash
PYTHONPATH=src .venv/bin/python -m briefing_app.cli preflight
```

Deep preflight — also probes endpoints on metered keys, spending twelve more of Alpha
Vantage's twenty-five:

```bash
PYTHONPATH=src .venv/bin/python -m briefing_app.cli preflight --deep
```

Inspect the latest report:

```bash
jq -r '.results[] | [.source_id,.endpoint_id,.status] | @tsv' output/preflight/latest.json
```

Only the endpoints that would fail a run:

```bash
jq -r '.results[] | select(.required and (.status | IN("ok","registered","no_credentials","manual_required","browser_required","skipped") | not)) | "\(.source_id).\(.endpoint_id) \(.status)"' output/preflight/latest.json
```

Check n8n Assistant services:

```bash
docker compose exec n8n wget -qO- http://sandbox-api:8080/healthz
docker compose exec n8n wget -qO- "http://searxng:8080/search?q=n8n&format=json"
```
