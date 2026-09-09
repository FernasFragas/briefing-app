# Still failing — PC1 ledger

**Generated 2026-09-03 from the reports named below.** This supersedes the 2026-09-02
edition in full; the previous edition is preserved in git history and its closure notes
are folded into [§6](#6-closure-register). This file is the Phase C gate: PC2, PC3 and
PC4 work must cite a row ID that is still **OPEN** here.

## Source reports

| | Report | Identity |
|---|---|---|
| Preflight | `output/preflight/latest.json` (`preflight-2026-09-03T131058.260942Z0000.json`) | `generated_at` `2026-09-03T13:10:58.260942+00:00`, `run_date` `2026-09-03`, `registry_version` 2, **50 endpoints**, `cache_only` false. Run with `--deep`, so the Alpha Vantage rows are proven entitlements rather than `registered` placeholders. |
| Live run | `data/runs/2026-09-03/daily-2026-09-03-c7e82663.json` + `output/dashboard/2026-09-03/dashboard-daily-2026-09-03-c7e82663.json` (preserved; `dashboard.json` now holds the later verification run) | `run_id` `daily-2026-09-03-c7e82663`, `data_mode` `live`, 14:02:11 → 14:07:35 UTC, `status` **succeeded**, `storage_run_id` 1. |

Live run shape: 35 universe tickers, 14 rejected at gate, **23 scored**, 23 Tier A / 0 B /
0 C, 23 setups, **4 tradeable / 19 watchlist**, 39 setup rejections, 2,180 evidence rows,
0 failures, 0 diagnostics.

Preflight status spread: **35 `ok`**, 5 `paywalled`, 3 `synthetic`, 3 `registered`,
1 `manual_required`, 3 `browser_required`.

Excluded from evidence: `daily-2026-09-03-74970df5` (14:01, `partial`, 23 cache-path
failures) and `daily-2026-09-03-fb78f201` (13:05, pre-N4). Both are superseded by the
14:02 run.

> ### Premise correction — PC1-LIVE-03 is not the largest open row; it is closed
>
> The Phase C queue was carried forward believing `S_F` was still an open sourcing
> problem. It is not. `Q4` closed it on 2026-09-02 as a **deliberate permanent `n/a`**,
> and the 09-03 run emits that decision as the component's own reason for all 23 names
> (`pipeline.py:164`, `config.py:343`, `config/config.example.yaml:277`,
> `docs/SOURCE_STATUS.md:192`). The chain is `institutional: []` — nothing is fetched and
> nothing is probed. `S_F` therefore needs no PC2 search and no PC4 wiring; it is already
> closed the PC3 way. See [PC1-LIVE-03](#closed-rows) in §6.
>
> The same applies to `S_S.executive_tone` (`Q1`, `components/sentiment.py:87`).
>
> **The largest genuinely open rows on this run are the two adopted-source regressions in
> [§5](#5-adopted-source-regressions)**, which cost 15 of 23 names their analyst coverage
> and cost every name its credit-spread and dollar macro release dating.

> ### PC2/PC3/PC4 pass, 2026-09-03 — what this file's rows became
>
> Eleven rows were closed in the same session that regenerated this file. Row states below
> are current; §6 carries the register.
>
> - **PC4 (wiring).** `PC1-RAW-15` FRED timeouts → bounded retry on transport faults only.
>   `PC1-RAW-16` FMP 429 → the budget module now *learns* the day's ceiling from the
>   provider's own refusal instead of trusting a configured 250. `PC1-RAW-17` AV's
>   repeatable `malformed` → parked for the run after two refusals. `PC1-RAW-18` /
>   `PC1-RAW-19` close as consequences of those three.
> - **PC3 (closure).** `PC1-LIVE-07`, `PC1-RAW-09`, `PC1-RAW-20`, `PC1-RAW-22` → index and
>   fund candidates carry no analyst or insider leg at all, declared rather than
>   rediscovered, and the requests are no longer sent. `PC1-LIVE-14` → `S_S`'s weight table
>   restated from `0.45 / 0.35 / 0.20` to `0.80 / 0.00 / 0.20`, which is what
>   re-normalization was already producing; the printed weights are now the ones used.
> - **PC2 (search).** `PC1-LIVE-05` → **premise disproven, no source adopted.** The feed
>   was nine pages and the pipeline read one. `docs/alternatives/pc2-retail-momentum-coverage.md`.

---

## 1. Preflight — `required` endpoints not `ok`

Rows from `results[] | select(.required == true and .status != "ok")`. Six rows were in
the 13:10 report, down from fifteen on 2026-09-02: the `--deep` probe resolved the nine
Alpha Vantage rows. Two FRED rows were code-closed after that report by enabling pinned
registry probes; they remain here until the next preflight proves the new status.

| ID | Endpoint | Status | Component | Scope from report | State | Phase C disposition |
|---|---|---|---|---|---|---|
| PC1-PF-10 | `fred.release_dates` | `registered` | S_M | Probe was disabled in the 13:10 preflight because it needed a `release_id` resolved from `series_release` first. Answered HTTP 200 with 9,558 dates on 2026-08-31 and is exercised by every live run. | **CODE-CLOSED 2026-09-03 — pending next preflight** | Registry now probes pinned release `10` directly. Next preflight should move it from `registered` to `ok`. |
| PC1-PF-11 | `fred.series_release` | `registered` | S_M | Probe was disabled in the 13:10 preflight. Verified 2026-08-31: `CPIAUCSL` → `release_id` 10. | **CODE-CLOSED 2026-09-03 — pending next preflight** | Registry now probes `CPIAUCSL` directly. Next preflight should move it from `registered` to `ok`. |
| PC1-PF-12 | `manual_eurex_capture.options_chain_capture` | `manual_required` | S_O | No capture files under `data/manual/eurex/manual_options_capture`. Schema exists (`schemas/eurex_options_manual_capture.csv`). | **OPEN** | PC3 candidate. Structurally rejected in `pa5-eu-sources.md`; per-strike EU OI needs browser, manual or paid feed. Gates `eu_options_unavailable` for ASML.AS, LDO.MI, RHM.DE, SIE.DE (§4). |
| PC1-PF-13 | `bundesanzeiger_fca.bundesanzeiger_net_shorts` | `browser_required` | S_O | Register answers a bare fetch with a session redirect. No captures under `data/manual/bundesanzeiger/net_short_positions`. | **OPEN** | PC3 candidate — anti-bot rejection, explicitly not re-litigable under the PC2 rule. |
| PC1-PF-14 | `eu_filings.mar_article_19` | `browser_required` | S_I | No pan-EU API; each national OAM publishes separately. No captures under `data/manual/eu_oam/mar_article_19`. | **OPEN** | PC3 candidate. No EU name currently reaches scoring, so the leg has no live consumer. |
| PC1-PF-15 | `eu_filings.major_holdings` | `browser_required` | S_F | Event-driven, per-register. No captures under `data/manual/eu_oam/major_holdings`. | **OPEN** | PC3 — subsumed by the `S_F` permanent `n/a` (PC1-LIVE-03). Should be de-`required` or closed alongside it. |

## 2. Preflight — soft gates and entitlement refusals

`required: false`, so they do not fail preflight, but they explain live behaviour and must
not be rediscovered from scratch.

| ID | Endpoint | Status | Component | Scope from report | State |
|---|---|---|---|---|---|
| PC1-PF-SOFT-01 | `fmp.economics` | `paywalled` | S_M | HTTP 402 `Restricted Endpoint`. Endpoint-level gate. | **CLOSED** — FRED is the adopted macro-calendar source (`p4-macro-calendar.md`). |
| PC1-PF-SOFT-02 | `fmp.stock_news` | `paywalled` | S_S | HTTP 402 `Restricted Endpoint`. | **CLOSED** — Finnhub leads news, AV shortlist second (`pb3-finnhub-news-and-analyst.md`, `q6-alpha-vantage-allocation.md`). |
| PC1-PF-SOFT-03 | `fmp.insider_trades` | `paywalled` | S_I | HTTP 402 `Restricted Endpoint`. | **CLOSED** — SEC EDGAR is primary, AV is the fallback and now probes `ok`. |
| PC1-PF-SOFT-04 | `fmp.institutional_ownership` | `paywalled` | S_F | HTTP 402 `Restricted Endpoint`. | **CLOSED** — subsumed by the `S_F` permanent `n/a`. |
| PC1-PF-SOFT-05 | `fmp.form_13f` | `paywalled` | S_F | HTTP 402 `Restricted Endpoint`. | **CLOSED** — same. |
| PC1-PF-SOFT-06 | `alpha_vantage.realtime_options` | **`synthetic`** | S_O | Now proven, not assumed: the deep probe got HTTP 200 carrying AV's artificial sample schema. Premium entitlement not held. | **CLOSED** — `synthetic` is in `ENTITLEMENT_STATUSES`, so the endpoint retires itself. CBOE carries S_O. |
| PC1-PF-SOFT-07 | `alpha_vantage.daily_adjusted` | **`synthetic`** | price_history | Deep probe returned the premium notice. | **CLOSED** — unadjusted `daily` plus FMP/Twelve Data carry price history. |
| PC1-PF-SOFT-08 | `alpha_vantage.historical_options` | **`synthetic`** | S_O | Deep probe returned the premium notice. | **CLOSED** — IV-rank history is self-built (PB2); revisit only as a paid decision. |
| PC1-PF-SOFT-09 | `sec_edgar.form_13f` | `registered` | S_F | Derived endpoint, probe disabled by design. | **CLOSED** — subsumed by the `S_F` permanent `n/a`. |

## 3. Live component and sub-score gaps

From `per_ticker_sections[].components` and their `sub_scores` on the 23 scored names.
Component-level spread this run: `S_M` 23 verified, `S_O` 23 verified, `S_S` 21 partial /
2 unavailable, `S_I` 11 verified / 12 unavailable, `S_F` 23 unavailable (by declaration).

| ID | Live gap | Count | Tickers | Report reason | State | Phase C disposition |
|---|---|---:|---|---|---|---|
| PC1-LIVE-05 | `S_S.retail_momentum` n/a | 8 | COST, CRWV, DE, FDX, GM, JPM, LMT, XOM | `no retail or social momentum reading supplied` | **CLOSED 2026-09-03 — premise disproven** | The feed was never missing these names; the pipeline read page 1 of 9 (`count: 863`). Six of eight were on pages 2–3 the same day. Pagination wired, plus a 5-mention floor so the five one-mention rows keep an honest `n/a` instead of being scored off noise. CRWV now scores; FDX and GM are genuinely absent. **No source adopted.** `pc2-retail-momentum-coverage.md`. |
| PC1-LIVE-06 | `S_S.political_flow` n/a | 18 | AMAT, AMD, AMZN, CRWV, DE, FDX, GM, INTC, LMT, META, MSFT, MU, ORCL, PLTR, QQQ, SMCI, SPY, XOM | 17 × `no congressional disclosure rows matched this ticker`; 1 × `matched congressional rows were stale, non-directional, or exchanges` | **OPEN** | PC3 — this is a data-state `n/a`, not a provider outage: the two market-wide FMP feeds returned `ok`. Make the scoring treatment explicit (absent vs. neutral) rather than searching for a second source. Was 15 on 09-02; the rise is universe/date drift, not regression. |
| PC1-LIVE-07 | `S_S.institutional` n/a → whole component `unavailable` | 2 | QQQ, SPY | Component: `the only measurable channel is retail_momentum, which is weight-capped and may not carry S_S alone`. Sub-score: `no analyst ratings, target revisions, or scored news in the window` | **CLOSED 2026-09-03 — declared** | PC3. An index has no issuer, so nothing publishes ratings about it: `Candidate.is_index_or_etf` now drives a structural `n/a` on the analyst leg and on `S_S`, with the weight redistributed and a named reason — the same treatment `S_F` and `executive_tone` already have. The analyst requests are no longer sent for these names. |
| PC1-LIVE-08 | `S_I` component `unavailable` | 12 | QQQ, SPY, XOM (`no Form 4 transactions available`); AAPL, AMZN, CRWV, DE, GM, JPM, ORCL, PLTR, SMCI (`no open-market insider trades in the last 90 days; N filings were plan, grant, or exercise activity`) | Component `validation_status=unavailable` | **PARTLY CLOSED 2026-09-03** | The ETF half (QQQ, SPY) is closed with PC1-LIVE-07: a fund has no officers, so `S_I` is structurally `n/a` and no Form 4 lookup is attempted. XOM and the nine plan/grant/exercise names remain **OPEN** as a data-state row whose reason already names the filing counts. |
| PC1-LIVE-09 | `S_I.seniority` n/a | 6 | AMD, COST, FDX, GOOGL, LMT, META | `no CEO, CFO, or senior-officer open-market trades in the window` | **OPEN** | PC3 — decide whether zero senior activity is *neutral* or *absent*. Pure data-state; no search warranted. |
| PC1-LIVE-12 | `S_O.iv_extreme` n/a | 23 | all scored names | `iv_extreme unavailable: self-built IV baseline is unavailable or still warming up` | **OPEN — time-blocked, not source-blocked** | Successor to the closed PC1-LIVE-11. Persistence works (`storage_run_id: 1`); the baseline reports **0 of 20 sessions stored**. ~20 trading sessions from 2026-09-03 ⇒ **early October**. This single dependency holds the six best-graded names (MSFT, FDX, XOM, JPM, QQQ, SPY) out of `TRADEABLE`. No PC2 search; PC4 only if a paid IV-history backfill is bought. |
| PC1-LIVE-13 | `S_O.skew` n/a | 2 | GM, LMT | `25-delta risk reversal unavailable for the selected expiry` | **OPEN — NEW** | New row on this run. Chain-shape, not provider outage: CBOE returned `ok` for both. PC3 — confirm the reason survives to the briefing output and decide whether a fallback expiry is worth it. Related to the declared `LIVE_UNSCORABLE_LEGS` entry `risk_reversal_history`. |
| PC1-LIVE-14 | `S_S` scores on a minority of its legs | 20 of 23 | 2 names on 0 of 4 legs (QQQ, SPY); 6 on 1 of 4; 12 on 2 of 4; only 3 on 3 of 4 | `legs_summary` on the `S_S` component | **CLOSED 2026-09-03 — weight decision recorded** | PC3's "weight table gets honest" item. `executive_tone`'s 0.35 is now declared as 0.00 rather than re-normalized away on every run, and the institutional leg carries the stated 0.80. **No score changes** — 0.80/0.20 is exactly what the cap and re-normalization already produced — but the printed table is now the one the score used. `components/sentiment.py` module docstring carries the decision and how to reverse it. |

## 4. Live provider issue rows

From `evidence_ledger[] | select(.field_name == "live_provider_issue")` — 304 rows,
grouped. Cite the row ID when deciding whether a gap is source, quota, fallback or
data-state.

| ID | Provider issue | Count | Tickers | State | Phase C disposition |
|---|---|---:|---|---|---|
| PC1-RAW-15 | **FRED `series_release` / `release_dates` read timeouts** — `network_error: The read operation timed out` on `BAMLH0A0HYM2`, `DTWEXBGS`, and upcoming dates for releases 10, 53, 304 | 115 (5 calls × 23) | all scored names | **CLOSED 2026-09-03 — wired** | `providers/base.py` now retries transport faults (`TimeoutError`, `URLError`) with doubling backoff, default 2 extra attempts via `BRIEFING_NETWORK_RETRIES`. HTTP refusals are never retried — a refusal is the provider's considered reply. Every attempt reserves budget, so a retry meters (PB8). |
| PC1-RAW-16 | **FMP HTTP 429 `Limit Reach`** on `grades_consensus` and `price_target_consensus` (15 names), `earnings_calendar` and `historical_price_eod` (14 names) | 58 | AMAT, AVGO, COST, CRWV, DE, FDX, GM, INTC, JPM, LMT, MU, ORCL, PLTR, SMCI, XOM | **CLOSED 2026-09-03 — wired** | `budget.note_quota_exhausted` records the refusal beside the day's counter, and `reserve()` then stops at the provider's number rather than the configured 250. It is day-scoped and written to disk, so a second same-day run inherits it — one wasted request to rediscover the limit instead of 57. Providers whose limit is a per-minute rate (`daily_requests=None`: Finnhub, FRED) are paced, never retired. See [§5](#5-adopted-source-regressions). |
| PC1-RAW-17 | Alpha Vantage `earnings_calendar` `malformed` — `Delimited body has no row wider than one character per column … I,n,f,o,r,m,a` | 4 | AMAT, AVGO, LMT, ORCL | **CLOSED 2026-09-03 — wired** | The memo `q6-alpha-vantage-allocation.md` §1 asked for. After `REPEAT_REFUSAL_THRESHOLD` (2) refusals with a status in `REPEATABLE_REFUSAL_STATUSES` (`malformed` only), the endpoint is parked for the run and refused in the guard, before any request. In-memory and per-client, so it dies with the run — a genuinely transient body costs one wasted run, never a retired source. `missing` is excluded on purpose: an empty root is a property of QQQ and SPY, not of the endpoint. |
| PC1-RAW-18 | Alpha Vantage daily budget exhausted (25/25) — `earnings_calendar` (9), `news_sentiment` (2), `insider_transactions` (1) not sent | 12 | COST, DE, FDX, GM, JPM, MU, PLTR, SMCI, XOM, AVGO, ORCL | **CLOSED 2026-09-03 — as a consequence** | Never had a cause of its own: FMP 429'd, AV is the earnings fallback, and the AV refusal was re-sent per ticker. All three inputs are now wired (PC1-RAW-16, -17), so the cascade cannot start the same way. Worth re-measuring on the next clean run rather than assuming: the AV ledger should show `earnings_calendar` at 2, not 6. |
| PC1-RAW-19 | Alpha Vantage `news_sentiment` throttled — `standard API rate limit is 25 requests per day` | 2 | AVGO, ORCL | **CLOSED 2026-09-03 — as a consequence** | The shortlist Q6 bought vendor-scored news for was exactly the set that lost it, because earnings had already spent the key. With PC1-RAW-17 capping the earnings refusal at 2 requests, the shortlist's 4 fit inside the allowance. AV also now records its own throttle (PC1-RAW-16 machinery applies to any provider with a declared daily count), so the remaining calls stop instead of being refused one by one. |
| PC1-RAW-20 | Alpha Vantage `insider_transactions` `missing` — `Required JSON path is missing or empty: data` | 2 | QQQ, SPY | **CLOSED 2026-09-03 — no longer requested** | Closed with PC1-LIVE-07: a fund has no officers to file, so the insider chain is not entered for index candidates at all. |
| PC1-RAW-10 | FMP `insider_trades` `plan_gated` — `FMP_PLAN is 'free'` | 3 | QQQ, SPY, XOM | **CLOSED** | Refused before the request, as designed. SEC EDGAR remains primary. |
| PC1-RAW-21 | FMP symbol paywall (HTTP 402 `Premium Query Parameter`) on `historical_price_eod`, `grades_consensus`, `price_target_consensus` | 3 | QQQ | **OPEN, NARROWED** | Was 8 symbols on 09-02 (PC1-RAW-04..06); Twelve Data and the universe change reduced it to QQQ alone. Keep as a known symbol gate. |
| PC1-RAW-22 | FMP `grades_consensus` / `price_target_consensus` `missing` — `Root payload is empty` | 2 | SPY | **CLOSED 2026-09-03 — no longer requested** | Closed with PC1-LIVE-07. |
| PC1-RAW-09 | Finnhub `recommendation_trends` `missing` — `Root payload is empty` | 2 | QQQ, SPY | **CLOSED 2026-09-03 — no longer requested** | The third provider agreeing that ETFs have no analyst coverage, and the evidence that made PC1-LIVE-07 a policy question rather than a sourcing one. |
| PC1-RAW-13 | SEC Form 4 document carried no non-derivative transaction rows | 29 filings | AAPL, AMD, CRWV, INTC, JPM, LMT, MSFT, MU, ORCL, PLTR, SMCI | **OPEN** | Was 34 on 09-02. Filing-shape outcome (derivative-only Form 4s) rather than a source outage. Keep visible; escalate only if evidence shows the normalizer drops valid rows. |
| PC1-RAW-12 | SEC EDGAR Form 4 timeout | 0 | — | **CLOSED** | Did not recur on this run. Reopen if it returns. |

## 5. Adopted-source regressions

Unlike 2026-09-02 — when no adopted source regressed — **this run has two.** Both are
throughput failures on sources whose entitlement is fine, and both are invisible in the
preflight report because preflight makes one request per endpoint.

> **Both were wired on 2026-09-03** and are recorded as closed in §4. The analysis below
> is kept because it is the evidence the fixes were built from, and because the next
> regression of this shape will be diagnosed the same way: preflight cannot see a
> throughput failure, so only a live run's `live_provider_issue` rows will show it.

### PC1-RAW-15 — FRED read timeouts

Five distinct FRED calls timed out for **every** scored ticker: `series_release` for
`BAMLH0A0HYM2` (high-yield credit spreads) and `DTWEXBGS` (broad dollar index), and
`release/dates` lookahead for releases 10, 53 and 304.

- FRED is the **adopted macro primary** (PB9) and preflight reports its probed endpoints
  `ok`, so this is a per-run throughput regression, not an entitlement change.
- Day's ledger: `release_dates` 32, `series_observations` 21, `series_release` 20 — 73
  requests, well inside any FRED limit. The failure mode is `The read operation timed
  out`, not a 429.
- Blast radius is bounded but real: `S_M` still reports `verified` for all 23 names on
  5–7 macro readings, and `macro_calendar_events` came back 1–2 per ticker. So the
  component degraded rather than failed — but **credit spreads and the dollar lost their
  release dating**, and the macro calendar lost three releases' lookahead.
- This is the row PC4 should act on: the client has no retry/backoff on
  `network_error` for FRED, so a single slow response costs the reading for the whole
  universe.

### PC1-RAW-16 — FMP HTTP 429 with local budget headroom remaining

FMP returned `HTTP 429: Too Many Requests — Limit Reach . Please upgrade your plan` for
15 of 23 names on the analyst endpoints and 14 of 23 on earnings and price history.

The important detail is in the budget ledger,
`data/provider_budget/fmp/2026-09-03.json`:

```
count: 208        daily_requests: 250
analyst_ratings: 47   earnings_calendar: 47
historical_price_eod: 47   price_target_consensus: 47
```

**The local ceiling did not protect the run.** `providers/budget.py:57` sets
`fmp: daily_requests=250`; the module believed 42 requests of headroom remained while the
provider was already refusing. Whatever FMP is actually metering, 250/day is not it.

The 47-per-endpoint figure is **not** a retry — there is no retry anywhere in the stack
(`http.py` is a bare `urlopen`; `providers/base.py` has no backoff path). It is 23 tickers
× **two full live runs on the same day**, plus one preflight request:

| Time (UTC) | Run | Outcome |
|---|---|---|
| 13:05–13:09 | `daily-2026-09-03-fb78f201` | `succeeded`, 23 scored — spent the day's real FMP allowance |
| 13:10 | `preflight --deep` | one request per FMP endpoint |
| 14:01 | `daily-2026-09-03-74970df5` | `partial`, 23 failures on missing caches |
| 14:02–14:07 | `daily-2026-09-03-c7e82663` | `succeeded` — **this run**, and the one that took the 429s |

The raw cache confirms which half landed: `earnings_calendar` 24 files cached against 47
requests, `analyst_ratings` 14 against 47, `historical_price_eod` 15 against 47. Run one
cached; run two was refused.

So there are two distinct wire-able findings, and the second matters more:

1. `daily_requests=250` does not match what FMP enforces. The previous day closed at
   240/250 with no 429 at all, so the ceiling is not merely stale — the provider's window
   and the module's window disagree in a way one number cannot express.
2. **Nothing stops the full pipeline running twice against a metered provider.** The
   budget module meters *requests*, not *runs*, and a second same-day run is
   indistinguishable from the first until the provider refuses. That is the actual defect
   behind this row, and it is the reason PC1-RAW-18's Alpha Vantage exhaustion happened
   too.

Cascade: FMP 429 on `earnings_calendar` → AV becomes the live earnings fallback →
AV spends its 25/day (PC1-RAW-18) → the four `news_alpha_vantage_shortlist` names that
`Q6` bought vendor-scored news for lost it to throttling (PC1-RAW-19). **One provider's
throughput regression disabled two others' legs.**

Every other adopted source reports `ok` at provider-status level on this run: CBOE
delayed options (24 rows), SEC EDGAR filing documents (242 rows), FINRA short volume,
Finnhub company news (48) and recommendation trends (27), FMP congressional feeds
(`senate_latest` 3, `house_latest` 3), ApeWisdom retail momentum, Twelve Data price
fallback, and FRED `series_observations`.

## 6. Closure register

Rows closed since the ledger was first written. Recorded so PC2 does not re-search them
and PC3 does not re-decide them.

### Closed rows

| ID | Gap | Closed | How |
|---|---|---|---|
| PC1-LIVE-01 | `S_M` unavailable — no sector exposure (15 names) | 2026-09-02 | Config: exposures declared for the report-missing sectors. Verified `s_m_unavailable=0`; the 09-03 run has `S_M` **verified for all 23**. |
| PC1-LIVE-02 | `S_M` partial — missing macro sub-legs (JPM, QQQ, SPY, XOM) | 2026-09-02 | Config: sector-policy and bucket gaps filled. Verified `s_m_partial=0`; confirmed live on 09-03. |
| **PC1-LIVE-03** | **`S_F` unavailable, all names** | **2026-09-02 (Q4)** | **Declared permanently `n/a`, the PC3 way.** A curated filer universe, a new table and a two-quarter diff are not justified by 0.10 of the US weight (`pb1-13f-blocker.md`), and an aggregator was rejected because EDGAR is the primary record. The weight is **redistributed, not scored neutral**. Chain is `institutional: []`. Recorded in `docs/SOURCE_STATUS.md:192`. **Do not reopen as a sourcing task.** |
| PC1-LIVE-04 | `S_S.executive_tone` n/a, all names | 2026-09-02 (Q1) | Declared permanently `n/a`: transcripts are unsourceable on every free tier reachable here (FMP 402, Finnhub 403 — `pa10-executive-tone.md`). Its 0.35 is redistributed across surviving legs. `components/sentiment.py:87`. |
| PC1-LIVE-10 | `S_O` component detail absent from per-ticker sections | 2026-09-03 | The 09-03 run emits five components per ticker — `S_M, S_S, S_I, S_F, S_O`. |
| PC1-LIVE-11 / PC1-RAW-14 | Self-built IV and put/call baselines could not persist | 2026-09-03 | Operationally closed: `storage_run_id: 1`, message is now `0 of 20 sessions stored`. The remaining wait is tracked as the new PC1-LIVE-12. |
| PC1-PF-10 / PC1-PF-11 | FRED release endpoints registered because probes were disabled | 2026-09-03 | Registry probes are now enabled against pinned `release_id` 10 and `series_id` `CPIAUCSL`. The next preflight is the proof step. |
| PC1-PF-01 … PC1-PF-07, PC1-PF-09 | Eight Alpha Vantage `required` endpoints reading `registered` | 2026-09-03 | `preflight --deep` proved them: `global_quote`, `daily`, `news_sentiment`, `earnings_calendar`, `insider_transactions`, `institutional_holdings`, `realtime_put_call_ratio`, `macro` all `ok` with raw caches under `data/raw/alpha_vantage/…/2026-09-03/`. |
| PC1-PF-08 | `alpha_vantage.historical_put_call_ratio` | 2026-09-02 (Q0) | Removed from the registry and the scheduled path. Absent from the 09-03 preflight's 50 endpoints, as required. |
| PC1-RAW-01 / -02 / -03 | AV earnings / institutional / insider budget exhausted | 2026-09-03 | Closed **as stated** — the cause named on 09-02 (the historical put/call spend) is gone. Budget exhaustion recurred for a different reason and is re-filed as PC1-RAW-18. |
| PC1-RAW-04 / -05 / -06 | FMP symbol paywall on 8 US symbols | 2026-09-03 | Narrowed to QQQ alone; re-filed as PC1-RAW-21. The rest is now a 429 problem, not a 402 one (PC1-RAW-16). |
| PC1-RAW-07 / -08 | FMP analyst rows missing for SPY | 2026-09-03 | Re-filed unchanged as PC1-RAW-22 under the ETF policy question. |
| PC1-RAW-11 | FMP `institutional_ownership` plan-gated, 24 names | 2026-09-03 | Subsumed by PC1-LIVE-03. Nothing is requested any more. |

### Closed by the PC2/PC3/PC4 pass, 2026-09-03

| ID | Closed how |
|---|---|
| PC1-LIVE-05 | PC2 — premise disproven, pagination wired, mention floor added. **No source adopted.** |
| PC1-LIVE-07, PC1-RAW-09, PC1-RAW-20, PC1-RAW-22 | PC3 — index/fund candidates declared to have no analyst or insider leg; the requests are not sent. |
| PC1-LIVE-08 (ETF half) | PC3 — same declaration. The issuer half stays open. |
| PC1-LIVE-14 | PC3 — `S_S` weights restated `0.80 / 0.00 / 0.20`; no score change. |
| PC1-RAW-15 | PC4 — bounded retry on transport faults, metered per attempt. |
| PC1-RAW-16 | PC4 — the day's ceiling is learned from the provider's own refusal. |
| PC1-RAW-17 | PC4 — repeatable non-entitlement refusals parked for the run. |
| PC1-RAW-18, PC1-RAW-19 | PC4 — closed as consequences of the three above. |

### Open rows, in priority order

1. **PC1-LIVE-12** — IV-rank warm-up; time-blocked until early October. Gates 6 of the best-graded names, and nothing but elapsed time will move it.
2. **PC1-LIVE-06**, **PC1-LIVE-09**, **PC1-LIVE-13** — data-state `n/a` treatments (`political_flow` 18 names, `S_I.seniority` 6, `S_O.skew` 2). Each needs a decision on whether absence is *neutral* or *absent*, not a search.
3. **PC1-LIVE-08 (issuer half)**, **PC1-RAW-13** — Form 4 shape: XOM plus nine names whose only filings were plan/grant/exercise, and 29 filings with no non-derivative rows. Escalate only if evidence shows the normalizer drops valid rows.
4. **PC1-PF-12** … **PC1-PF-15** — EU manual/browser captures. PC3 closures, not searches; the rejections in `pa5-eu-sources.md` and `pb5-fca-deferred.md` are structural and not time-dependent.
5. **PC1-RAW-21** — FMP symbol paywall, now QQQ alone. A known gate with a working fallback.
6. **PC1-LIVE-05 residue** — FDX and GM were absent from all nine ApeWisdom pages. One observation is not a pattern; worth a row of its own only if it persists across a week of runs.

## 7. Verification run, 2026-09-03 17:14 UTC

The PC2/PC3/PC4 changes were verified against live providers by
`daily-2026-09-03-06a2dfb4` (17:14:00 → 17:19 UTC), which finished **succeeded** with the
same shape as the run this ledger is built from: 23 scored, 23 Tier A, 4 tradeable, 19
watchlist, 39 setup rejections, 0 failures.

| Fix | Row | Verified live | Evidence |
|---|---|---|---|
| FMP ceiling learned from the refusal | PC1-RAW-16 | ✅ **Proven** | **One** HTTP 429 in the whole run, against 58 on `c7e82663`. `data/provider_budget/fmp/2026-09-03.json` records `quota_exhausted` at `observed_count: 209`, `configured_limit: 250`, endpoint `historical_price_eod`. The counter then froze at 209 while 133 further FMP calls were refused **in the guard, before being sent**. |
| ApeWisdom read to the end of the feed | PC1-LIVE-05 | ✅ **Proven** | 9 requests on `retail_momentum` (was 1). CRWV now scores `+0.90` on `10 mentions vs 1`. |
| Mention floor on thin retail rows | PC1-LIVE-05 | ✅ **Proven** | COST, DE, JPM, LMT and XOM read `retail attention is too thin to read: 1 mentions vs 2 24h ago, below the 5-mention floor`. FDX and GM keep `no retail or social momentum reading supplied` — still genuinely absent from all nine pages. |
| Index/fund legs declared n/a | PC1-LIVE-07, PC1-RAW-09/-20/-22 | ✅ **Proven** | QQQ and SPY carry the declared `S_S` and `S_I` reasons, and the run contains **no** FMP grades/price-target, Finnhub recommendation-trend, or AV insider row for either name. Nothing was asked. |
| `S_S` weight table restated | PC1-LIVE-14 | ✅ **Proven, and no score changed** | MSFT `S_S`, before: `institutional weight=0.45, weight_used=0.80`. After: `weight=0.80, weight_used=0.80`. `weight_used` is identical in both runs — the printed table changed, the arithmetic did not. |
| FRED retry on transport faults | PC1-RAW-15 | ⚠️ **Not exercised** | Zero FRED issues this run: no timeout occurred, so the retry never fired. A timeout cannot be provoked on demand against a live source. Covered by unit tests (`tests/test_provider_resilience.py`). |
| AV repeatable-refusal memo | PC1-RAW-17 | ⚠️ **Not exercised** | Alpha Vantage was already 25/25 spent when the run began, so the budget guard refused `earnings_calendar` 23 times before any request left the process — the malformed body never arrived. Covered by unit tests. Re-check on an unspent day: the AV ledger should show `earnings_calendar` at **2**, not 6. |

**Caveat on the verification run itself.** It was FMP-starved from its first request, because
three live runs and a deep preflight had already shared the day's allowance. So it is not a
steady-state measurement, and its analyst coverage is thinner than a clean day's would be.
What it does establish is that the fallback chains hold under that condition: with FMP cut
off at request one and Alpha Vantage fully spent, Finnhub, Twelve Data, FRED, CBOE, FINRA,
SEC EDGAR and ApeWisdom still produced 23 scored names and 4 tradeable setups — the same
counts as the run that had FMP for its first half.

### Caveat on this run's evidence

PC1-RAW-16 and PC1-RAW-18 mean 15 of 23 names were scored **without** analyst input and
4 without their intended vendor-scored news. Sub-score counts in §3 that depend on those
legs — PC1-LIVE-07 in particular — are therefore a floor, not a steady-state measurement.
A clean re-run on an unthrottled day is the right evidence before any of those rows is
closed as permanently unavailable.
