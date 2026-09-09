# Provider Alternatives Research And Wiring Tasks

Source plan: `options-briefing-system-plan.md` — see also `implementation-tasks.md`, `docs/SOURCE_STATUS.md`, `config/source_registry.yaml`.

**Implementation tickets live in `provider-alternatives-implementation.md`.** This file is the audit, the coverage matrix and the research verdicts — the *why*. That one is the *how*.

Baseline: provider-readiness audit completed 2026-08-30. Implemented and wired: CBOE delayed options, Alpha Vantage, FMP, FINRA, SEC EDGAR, FRED, ApeWisdom, and FMP congressional feeds. Implemented but pipeline-orphaned: FCA (probe-only), Eurex/EU OAM manual loaders. Quiver is superseded for `political_flow`.

Phase A premises re-verified against the code and a live probe on 2026-08-31. PA2 and PA5 were filed on premises that no longer hold and have been rewritten. PA7 is now closed without a provider: historical Alpha Vantage put/call was removed from the registry/client and the percentile history is self-built from persisted CBOE-derived snapshots.

## Status — 2026-08-31, end of day

**Phase A is complete.** All ten tasks have an evaluation in `docs/alternatives/` with a
verdict. **Phase B is complete for everything that needs no new credential**; the remaining
provider tickets have verified keys but still need wiring, and one is blocked by design.

Landed today, all verified against live providers rather than fixtures:

| Work | Result |
|---|---|
| **PB1** FINRA → `short_borrow` | Wired. Scores as a labelled short-**volume** proxy on its own field |
| **PB1** SEC EDGAR → `S_I` | Wired, Form 4 from the primary record. **The two EDGAR normalizers were non-functional scaffolding** — 19 helpers referenced, none defined, zero tests. Implemented and verified against a real Apple Form 4 |
| **PB2 / PB7** self-built IV and put/call series | Wired. No vendor: the pipeline already persisted `iv_atm` and the P/C ratios and never read them back. 20-session warm-up enforced explicitly |
| **I5 / PB9 (macro half)** FRED | Client, normalizers, registry entries, wired as macro **primary**. The current sector map uses FRED-backed factor readings only |
| **Release-date ageing and factor map** | `MacroEvent.released_at` plus the added mapped factors moved `S_M` from one usable factor to ten cached readings on the 2026-09-02 verification |
| **Phase C sector exposure close** | `config/config.example.yaml` now covers every sector used by the 24-ticker live report, and `Defense` spelling is normalized in the fixed universe |
| Fixture IV surface, float-noise crash, divergence threshold | Three defects fixed; see the graded-report work in `tasks/todo.md` |

`LIVE_UNSCORABLE_LEGS` is down from five entries to two: `executive_tone`,
`risk_reversal_history`. Historical 08-31 verification was **467 passing**; the refreshed
09-03 provider pass is tracked in the Phase C section below.

**Two findings that changed the plan:**

1. **Quiver is not required.** FMP `senate-latest` and `house-latest` are entitled on the
   existing free key (probed 2026-08-31), so `political_flow` needs no new credential.
   Retail momentum needs none either — ApeWisdom is keyless. **PB6 is now wired.**
2. **`S_M` was scoring on one factor out of eleven**, on both FMP and FRED, because both
   date an observation by the period it measures rather than by when it was published.
   Fixed via the release calendar, which only a keyed FRED serves.

## Audit — 2026-08-31, credentialed

> **Historical record.** Kept as filed; resolutions are marked inline. See the status
> section above for the current state.

Full preflight against live keys, 42 endpoints. `ok`: CBOE chain, FINRA, SEC EDGAR (all three), FCA, and 15 FMP endpoints. `paywalled`: 5 FMP (`economics`, `stock_news`, `insider_trades`, `institutional_ownership`, `form_13f`). `browser_required` / `manual_required`: 4 EU. **Alpha Vantage: every function refused.** Three findings change the plan:

- ⚠️ **Superseded 2026-09-02.** Original finding: `GLOBAL_QUOTE`, `HISTORICAL_PUT_CALL_RATIO`, `REALTIME_PUT_CALL_RATIO` and `CONGRESS_TRADES`, probed 3 s apart at 00:15 UTC, all returned the daily-cap notice. Later probes showed the quota does reset and AV is not dead; the actionable fix was to remove the redundant historical P/C path from the scheduled run.
- ✅ **RESOLVED (PB8).** ~~Preflight spends quota without metering it.~~ `preflight.py` now reserves budget before probing. Original finding: **Preflight spends quota without metering it.** `preflight.py:123` fetches through `UrlLibFetcher` directly and never touches `RequestBudget`, so the `budget.reserve` call at `base.py:119` is bypassed. Today's credentialed run spent ~20 FMP and 1 AV request and wrote **no** `data/provider_budget/2026-08-31.json` at all. The ledger the pipeline consults to decide whether it can afford a call is a floor, not a count — which is how a 25/day key was drained invisibly and how the 47 purged entries got written.
- ⚠️ **PARTLY RESOLVED.** Of the four legs with no live feed, **insider (S_I) is now sourced from SEC EDGAR**, **the put/call percentiles (S_O) from a self-built series**, and **news sentiment (S_S) from Finnhub with locally derived tone**. Institutional (S_F) is blocked by design. Original finding: with AV refusing and the FMP equivalents `paywalled`, all four had zero working sources — not a degraded one.

**Raw-cache purge, 2026-08-31.** 47 invalid entries were removed, every one under `data/raw/alpha_vantage/`: 37 `throttled` (rate-limit notices returned as HTTP 200), 7 `malformed` (the `I,n,f,o,r,m,a` degenerate-CSV refusals), 3 `paywalled` (premium sample payloads on `daily_adjusted` and `historical_options`). The Alpha Vantage cache directory is now gone, so `--cache-only` has nothing to replay for AV and every AV question must be settled live. The entries are residue, not a live bug: `base.py:230-252` already validates before writing and `provider_validation.py` classifies all three shapes. Do not reopen it as a defect.

## Source Coverage Matrix

Every source the report actually reads, with the chain the code really has — not the one the
registry notes imply. Rewritten 2026-08-31 evening: "Chain in code today" is the live
`providers:` block in `config/config.example.yaml`, verified by loading it, not the registry's
intent.

| Report leg | Chain in code today | State | What is left |
|---|---|---|---|
| Options chain — S_O skew, gamma, liquidity, P/C **level** | `[cboe, alpha_vantage]` | ✅ works; CBOE carries the live path | **Open**: one unauthenticated CDN carries the heaviest component. PA2(b) adopts Tradier sandbox as failover |
| P/C percentiles — S_O `put_call` (0.25) | **self-built series** from `daily_snapshot` | ✅ **closed** | Warm-up: 20 sessions. Historical AV P/C is not scheduled, registered, or exposed by the client |
| IV rank — S_O `iv_extreme` (0.10) | **self-built series** from `daily_snapshot` | ✅ **closed** | Warm-up: 20 sessions |
| Borrow — S_O `short_borrow` (0.05) | `[finra]` | ✅ **closed**, as a labelled volume proxy | Short **interest** unprobed; borrow fee has no free source (PA1) |
| Price history | `[fmp, twelve_data, alpha_vantage]` | ✅ **closed for the six FMP-gated US symbols** | Twelve Data backs up AVGO, ORCL, MU, QQQ, CRWV and AMAT. RHM.DE/LDO.MI remain paid-plan gated and are covered by the EU universe decision |
| Earnings calendar | `[fmp, alpha_vantage]` | ✅ works on FMP, with AV as metered fallback | N4a moved AV behind FMP because `EARNINGS_CALENDAR` returns the repeatable degenerate-CSV refusal on this key and otherwise spends the 25/day quota per ticker. |
| News sentiment — S_S | `[finnhub, alpha_vantage, fmp]` | ✅ **closed**, on a locally scored feed | Finnhub does not score its own news, so tone is a lexicon read labelled `local tone`; ~50% of articles measurable. Signal quality is below a working AV key and far above the nothing it replaced |
| Analyst signals — S_S (0.45) | `[fmp, finnhub]` | ⚠️ **second feed for US names only** | Finnhub's free tier is US-only, so `RHM.DE` and `LDO.MI` stay sole-sourced on FMP — which 402s both. An honest partial close, not a full one |
| Executive tone — S_S (0.35) | none | ❌ never scores | PA10 = reject. FMP transcripts 402. Close via PC3 with a weight decision (**A3**/**A4**) |
| Retail momentum — S_S (0.20) | `[apewisdom]` | ✅ **closed**, as attention momentum not sentiment | A7 still open: whether to cap the noisy retail signal below nominal weight |
| Political flow — S_S sub-score | `[fmp senate_latest, fmp house_latest]` | ✅ **closed**, capped +/-0.05 overlay | Sparse per ticker; STOCK Act lag labelled as context, not edge |
| Insider — S_I | `[sec_edgar, alpha_vantage, fmp]` | ✅ **closed**, on the primary record | 10b5-1, exercises and tax withholding excluded per T6 |
| Institutional — S_F | `[alpha_vantage, fmp]` | ❌ no working source | **Blocked by design** — needs a filer universe and a two-quarter diff. See `docs/alternatives/pb1-13f-blocker.md` |
| Macro readings — S_M | `[fred, fmp]` | ✅ **closed**, FRED primary | All factors declared by the shipped sector exposure map are mapped to FRED series |
| Sector exposures — S_M config | `components.sector_exposures` | ✅ **closed 2026-09-02** | The 24-ticker report now has zero `S_M` unavailable and zero `S_M` partial in macro-only verification |
| Macro calendar | FRED `release/dates` | ✅ **wired 2026-09-02** | Scheduled release dates, US only, no consensus estimate — feeds event risk and the dated table, not `S_M`'s score. Releases publishing weekly or more often are excluded as routine postings, named with their cadence — daily (H.15, Interest Rate Spreads, ICE BofA) and weekly price postings (H.10 FX, Spot Prices, NYMEX Nat Gas) (`docs/alternatives/p4-macro-calendar.md`) |
| Filings | SEC EDGAR + FMP | ✅ two sources answer | — |
| EU options / shorts / insider | manual and browser captures | ❌ capture-gated | PA5 = **structural reject**. No free EU per-strike chain exists; EU names are Tier C by construction |

**Eleven report source paths are closed; the price-history gap is closed for the six US
gated symbols; sector exposure config is closed for the PC1 live report; one source path is
blocked by design; the EU remainder is a structural universe decision.**

S_S is still weak because `executive_tone` is structurally absent, and its news read is a
lexicon rather than a vendor's scored feed. But it no longer rests on one provider, and no
longer has a leg with no source at all.

## Objective

**Every source the report reads needs a working alternative** — not only the ones failing today. The 2026-08-31 audit is the argument: Alpha Vantage went from "metered" to a spent quota in one day and took four legs down with it, because their documented fallbacks were either the same metered key or a `paywalled` FMP endpoint. A source that works is not a source that is safe; it is a single point of failure that has not failed yet.

So the scope is three kinds of gap, not one: sources that **fail today** (PA1–PA7); sources that **answer but are sole** (PA8–PA9, PA2(b)), so no leg rests on one provider; and legs that have **never had a source at all**. PA6 closed the retail/political half; PA10 (`executive_tone`) remains because a leg that never scores never fails a probe — it just quietly renormalizes its weight away.

Phases A and B are the first pass. **Phase C is the standing loop**: whatever still fails, plus anything that regresses later, goes back through search and wiring until it is either sourced or explicitly declared unavailable.

## Phase A - Research: An Alternative For Every Source In The Report Path

PA1–PA7 cover sources that fail today. PA8–PA9 cover sources that answered on the audit but have no second feed — same deliverable, same acceptance, and no lower priority: the legs AV took down on 2026-08-31 were all `ok` the day before.

Each search task must produce a short written evaluation in `docs/` (one file per task, e.g. `docs/alternatives/<task-id>.md`) covering: free-tier limits (calls/min, calls/day), data entitlement (EOD vs delayed vs real-time, Greeks, history depth), licensing/redistribution constraints, endpoint stability (anti-bot behavior, 429 traps), and a verdict (adopt / reject / monitor). Reuse the web-search evaluation criteria already applied to Stooq/Yahoo (rejected as anti-bot/429 traps) and optioncharts.io (rejected as paywalled) — do not re-litigate those.

Three rules govern every task, because the first pass at this table broke all three:

1. **Verify the premise before searching.** Each row states a gap read off the audit, not re-proven. Confirm it against `config/source_registry.yaml`, the provider client, and the live call site in `pipeline.py` first. A row whose premise turns out to be false is closed with that finding written up — never with an adopted source. PA2 is the worked example: filed as "CBOE carries no Greeks", disproven by one `curl`.
   **A cached payload is not evidence of anything.** 47 bodies under `data/raw/alpha_vantage/` were refusals wearing HTTP 200, and they sat there looking like data. Entitlement is proven by a probe whose validation passed on the run that wrote it, never by a file's existence.
2. **Check the entitled providers before searching for a new one.** CBOE, Alpha Vantage, FMP, FINRA and SEC EDGAR are already wired, keyed and budgeted. An endpoint one of them already serves costs a registry entry; a new vendor costs a client, a normalizer, a probe, a credential and a budget line.
3. **Separate "no source" from "sourced but unsupplied".** Several legs score `None` today because the pipeline never passes an argument it already has the data for, not because no provider sells it. That is a Phase B wiring bug, and no amount of vendor research fixes it. Say which one a gap is before naming candidates.

**All ten complete as of 2026-08-31.** Verdicts below; the full evaluations, with probe
evidence and rejected candidates, are in `docs/alternatives/`.

| Task | Verdict | Evaluation |
|---|---|---|
| **PA1** | Adopt FINRA daily short **volume** as a labelled proxy on its own field. Short interest unprobed; borrow fee has **no free source** — permanently `n/a` | `pa1-borrow.md` |
| **PA2** | (a) **Closed on disproof** — self-built IV series, no vendor. (b) Adopt **Tradier sandbox** as CBOE failover (Greeks via ORATS) | `pa2-iv-history-and-chain-failover.md` |
| **PA3** | Adopt **Finnhub** company news; 60 req/min against AV's 25/day. Tiingo monitor; RSS/SearXNG reject | `pa3-news.md` |
| **PA4** | Adopt **Twelve Data** for the six US gated-symbol price-history gap. The probe showed RHM.DE/LDO.MI are paid-plan gated, so EU stays with A2 | `pa4-gated-symbol-prices.md` |
| **PA5** | **Structural reject.** Eurex sells market data and gives away reference data; ESMA's SSR dataset is an *exemption* register. No free EU per-strike chain exists | `pa5-eu-sources.md` |
| **PA6** | Adopt **FMP `senate-latest`/`house-latest`** (already entitled) for political flow and **ApeWisdom** (keyless) for retail. **Quiver not required.** Stocktwits API is frozen to new developers | `pa6-political-and-retail.md` |
| **PA7** | **Closed on disproof** — self-built series only. The AV historical P/C endpoint was removed after Q0 because it adds no useful data and spends quota | `pa7-put-call-history.md` |
| **PA8** | Adopt **Finnhub** as a second analyst feed — **US names only**, so EU stays sole-sourced. Exposure is worse than filed: with the other two S_S legs dark, one FMP change takes out 100% of S_S | `pa8-analyst-signals.md` |
| **PA9** | Adopt **FRED**. Wired and live. A **keyless** path (`fredgraph.csv`) serves the same series if a key is ever unavailable | `pa9-macro.md`, `pa9-macro-keyless-alternative.md` |
| **PA10** | **Reject** as a vendor task — FMP transcripts 402 on all three endpoints. Probe Finnhub's at signup; otherwise close via PC3 and redistribute the 0.35 weight | `pa10-executive-tone.md` |

<details>
<summary>Original task table, kept for the search criteria and notes each row carried</summary>

| Task | Failing source / gap | Search for | Notes |
|---|---|---|---|
| **PA1** | Borrow leg of S_O (`short_borrow`, weight 0.05) never scores: `pipeline.py:51` imports `ShortBorrowSnapshot` and no code path ever constructs one. The FINRA client exists but is unwired, and it carries short **volume** only | Keep the three data types apart, because only one of them is genuinely missing: daily short **volume** (FINRA CNMS — already fetched, `ok`), bi-weekly short **interest** and days-to-cover (FINRA equity short interest files, exchange-published files, SEC Reg SHO threshold lists), and **borrow fee / utilization** (no known free source) | Verdict must say which of the three the leg can ever score on. Spec paid upgrades (S3, Ortex, IBKR) for a future decision — no purchase. If borrow fee has no free source, the honest verdict is "short interest only, fee leg permanently `n/a`" |
| **PA2** | **Premise corrected — do not search for a Greeks provider.** CBOE delayed chains already carry per-strike Greeks: verified 2026-08-31, `SPY.json` returned 13,160 contracts with `iv, delta, gamma, theta, vega, rho, theo` (13,064 with non-zero delta), and `normalizers.py:220-225` already maps all six onto `OptionContract`. The real gaps are (a) no **IV history**, so `iv_rank` is always `None` in live mode — `build_options_structure` is called at `pipeline.py:1263` without `iv_history`, and the `iv_extreme` leg (weight 0.10) never scores; (b) CBOE is a single unauthenticated CDN with no failover for the heaviest component | (a) Evaluate **self-building** the trailing IV series by persisting each run's ATM IV from the chain already fetched, against buying history (Tradier/ORATS, Market Chameleon) — compare on history depth and time-to-first-usable-rank; (b) a second delayed US chain with Greeks purely as CBOE failover: Tradier delayed (`greeks=true`), Schwab API, OpenBB as a normalization layer | Self-building needs storage, not a provider, and is the leading candidate — evaluate it first and reject vendors against it. Tradier is now the **failover** candidate, not the Greeks fix. Shares its answer with PA7: one stored series of chain-derived metrics serves both |
| **PA3** | News sentiment (S_S) rests on Alpha Vantage alone; FMP `news/stock` is plan-gated (`required: false`). The 25 req/day ceiling is not theoretical: a live probe hit it on 2026-08-31, and 37 of the 47 purged cache entries were rate-limit notices. The quota is breached routinely, not occasionally | Free financial news APIs: Finnhub company/market news (60 req/min free), Tiingo news, Benzinga free tier, RSS feeds from major outlets via SearXNG | **Raise this above PA1/PA4 in priority** — the purge shows AV's ceiling is the binding constraint on the whole AV surface, not just news. Rank candidates on requests/day headroom first; quality second. A source that merely matches 25/day is a reject |
| **PA4** | FMP free-tier **symbol** gates (AVGO, ORCL, MU, QQQ → HTTP 402) hit `quote` and `historical-price-eod/full` — the registry's **primary** daily OHLCV source — as well as estimates and the calendar. For those names the only fallback is Alpha Vantage `daily`, which draws on the same 25/day bucket the purge showed is already being exhausted — so the documented fallback is not a real one | Free daily OHLCV with no symbol gate (Tiingo EOD, Twelve Data, Alpaca) **and** free fundamentals/estimates (Finnhub earnings calendar + EPS surprises, Tiingo fundamentals) | Price history for the gated names is the load-bearing half — a candidate ranked on estimates coverage alone would miss it. Must cover the gated symbols or justify removing them from the universe |
| **PA5** | **Premise corrected.** FCA UK shorts is fetchable and `ok` (plain XLSX, no key or session) — it is unwired, not unavailable, so it belongs to PB5, not to research. The genuinely capture-gated sources are Bundesanzeiger (`browser_required`), Eurex per-strike chains and EU OAM insider/holdings (`manual_required`). `data/manual/` still does not exist | Fetchable EU sources: Eurex delayed data endpoints, ESMA short-position registers, national OAM APIs beyond Bundesanzeiger, any EU per-strike chain source with a real API | The loaders are already written — the goal is any source that removes the manual-capture dependency. Do not re-evaluate FCA |
| **PA6** | **The two alternative-data legs of S_S, neither sourced.** (a) Political flow: Quiver planned (T13 in `implementation-tasks.md`) but zero code, no key, no registry entry. (b) `retail_momentum` (weight 0.20) has never scored — the live pipeline never passes it and no registry provider carries retail or social sentiment. Neither leg is served by any primary or regulator source, which is why one vendor may end up covering both | (a) AV `CONGRESS_TRADES` is **blocked**, not untested: it returned the daily-cap notice on the 2026-08-31 audit like every other AV function. Try FMP senate/house trading, then Quiver, then direct Senate/House disclosure feeds. (b) Retail: Quiver's WallStreetBets dataset, Stocktwits, Reddit-derived aggregators, ApeWisdom. Verified 2026-08-31 — `api.quiverquant.com/beta/historical/congresstrading/{ticker}` is live and key-gated (HTTP 401, clean JSON error), so T13's endpoint pattern holds and free-tier **scope** is the only open question | Evaluate both legs against the same vendor before adopting either. Quiver is the one candidate that plausibly serves both, which is also the risk — do not let it become the next single point of failure. **Do not route S_I or S_F through Quiver**: SEC EDGAR is the primary record, free, and `ok` today, so an aggregator there downgrades source quality for no gain (PB1 is that fix). Disclosure lag is real — STOCK Act filings can lag 45 days against a ~14-day horizon — so cap the leg per T13 and label it context, not edge |
| **PA10** | Executive tone — S_S leg (0.35) has never scored. `sentiment.py:254-257` states the reason plainly: earnings-call transcripts are not fetched by this stack | Probe FMP's transcript endpoint for a free-tier gate first, since FMP is already keyed. Do not spend scarce AV quota on a transcript endpoint unless PC3 chooses to fund/restore this leg. Then company IR transcript pages, and any free transcript API | Most likely a **reject**: transcripts are widely paywalled, and the leg needs tone extraction on top of retrieval, not just a feed. If so, close it through PC3 — record it permanently `n/a` and put the 0.35 weight up for redistribution rather than leaving a third of S_S structurally absent |
| **PA7** | **Premise narrowed.** The P/C **level** is computed from the CBOE chain itself (`options_math.py:626-654` sums put/call volume and OI from the quotes) — Alpha Vantage supplies only the **history** behind the two percentile terms (`pipeline.py:1540`). That entitlement has never been verified with a key: both P/C endpoints are `probe_tier: deep`, they are absent from the client's `premium_endpoints`, and the last preflight ran `cache_only`. So the 0.25-weight `put_call` leg assumes an entitlement nobody has tested | One deep probe with a key **first**. Then, as with PA2, compare self-building the trailing ratio series from chains already fetched against CBOE's published P/C CSVs and other exchange sentiment indicators | The probe decides the task: either "find a cheaper P/C history" or "the percentile terms have no live feed at all". Not a web-search task until it runs. Same stored-series answer as PA2 — evaluate them together |
| **PA8** | **Sole provider, currently `ok`.** Analyst signals (S_S) come only from FMP `grades-consensus` and `price-target-consensus` (`pipeline.py:1811-1821`), with no fallback in code. FMP already answers 402 on five other endpoints and gates four universe symbols, so the plan that carries this leg is one entitlement change away from taking it out | Free analyst/recommendation data: Finnhub recommendation trends and price targets (free tier), Tiingo, Twelve Data. Also check whether the gated symbols resolve on the alternative, since FMP's symbol gate already bites elsewhere | Rank on symbol coverage first — an alternative that shares FMP's gated-symbol problem is not redundancy. Aggregator-sourced either way, so the S_S label stays "aggregator" |
| **PA9** | **Sole provider plus a hard gap.** Macro readings (S_M) rest on FMP `economic_indicators` + `treasury_rates`, whose only fallback is the dead AV `macro` slot; the macro **calendar** has no source at all, since FMP `economic-calendar` is `paywalled` | **FRED first** — free, official, generous limits, and it carries every series in `FMP_MACRO_INDICATORS` (`pipeline.py:123-130`) plus the Treasury curve. Then ECB Data Portal and Eurostat for the EU leg, and a free dated macro calendar for the gap FMP leaves | FRED is the strongest single candidate in this whole table: official primary data rather than an aggregator, which also upgrades the source-quality label on S_M. Its API key is free — confirm terms for self-hosted personal use |

</details>

**Phase A acceptance:**

- Every task PA1–PA10 has an evaluation file in `docs/alternatives/` with a verdict.
- Every row of the coverage matrix ends with a named alternative or a recorded reason why none exists. A leg whose only source is `ok` today is still an open row.
- Each factual claim names the date and the exact probe behind it (URL, `curl`, or CLI command), so a stale verdict is re-checked rather than re-argued.
- Each "adopt" verdict names: base URLs, endpoint shapes, free-tier limits, required credential env var, and license constraints.
- Rejected candidates are listed with the reason (anti-bot, paywalled, insufficient history, licensing), so future audits do not redo the search.
- A task whose premise is disproven is closed with the disproof and the code reference that settles it — no source is adopted to fill a gap that does not exist.
- No evaluation cites a file under `data/raw/` as evidence of an entitlement. 47 such files were refusals returned as HTTP 200; entitlement is established only by a probe whose validation passed on the run that fetched it, and the evaluation names that run.
- Where the gap is an unsupplied argument rather than a missing provider (PA2's `iv_history`, PA1's `short_borrow`), the evaluation says so and hands the task to Phase B wiring instead of naming a vendor.
- No evaluation depends on a source that requires commercial redistribution rights, since the app is self-hosted personal use — flag any that do.

## Phase B - Wiring: Integrate Adopted Sources

All wiring follows the existing contracts — no new mechanisms:

- Client in `src/briefing_app/providers/<provider>.py` extending the base class (`base.py`), with entitlement/plan gating like `fmp.py:31-40` where the free tier gates endpoints or symbols.
- Registry entries in `config/source_registry.yaml` (URL templates, cache slots, probe tiers, `required` flags).
- Normalizers in `providers/normalizers.py` producing the existing normalized models.
- Preflight probes in `preflight.py` so the new source is covered by `test_preflight.py` registry↔client assertions.
- Consumption in `pipeline.py` with a defined fallback chain and Tier degradation behavior.
- Budget/plan learning via `budget.py` and `ENTITLEMENT_STATUSES` if the provider meters.
- Tests in `tests/test_provider_clients.py` / `test_provider_normalizers.py`, including refusal taxonomy (endpoint-gate vs symbol-gate vs quota).

Status column added 2026-08-31 evening.

| Task | Work | Status |
|---|---|---|
| **PB1** | Wire the **existing FINRA client** into `pipeline.py` so `ShortInterestSnapshot` (`models/market_data.py:441`) finally has a production caller; wire SEC EDGAR client into the S_I path | ✅ **Done** (FINRA + EDGAR insider). ⛔ 13F half blocked by design. The premise "code already exists and passes tests" was **wrong for EDGAR**: both normalizers were scaffolding with 19 undefined helpers and no tests |
| **PB2** | Close the PA2 gap: supply `iv_history` to `build_options_structure` on the live path so `iv_extreme` scores | ✅ **Done** — self-built from `daily_snapshot`, no vendor. 20-session warm-up enforced |
| **PB3** | Adopt one PA3 winner as a second news source: client + normalizer + pipeline merge so news sentiment survives an Alpha Vantage quota outage | ✅ **Done 2026-09-01.** Finnhub leads the chain; tone derived locally because the free tier does not score its own articles. `docs/alternatives/pb3-finnhub-news-and-analyst.md` |
| **PB4** | Resolve the FMP 402 symbol gates — now **six** US symbols, not four: AVGO, ORCL, MU, QQQ, CRWV, AMAT, plus both EU names | ✅ **Done for the US gap.** Twelve Data is wired into `prices: [fmp, twelve_data, alpha_vantage]`. RHM.DE/LDO.MI remain paid-plan gated and are covered by **A2** |
| **PB5** | Wire FCA shorts; adopt any PA5 source removing the manual-capture dependency | ⏭ **Deferred with reason.** FCA covers UK issuers and the universe has **zero UK names**; there is also no FCA client to "wire". PA5 is a structural reject. See `docs/alternatives/pb5-fca-deferred.md` |
| **PB6** | Implement `political_flow` and `retail_momentum` | ✅ **Done** — FMP congressional feeds are fetched once per run, accumulated from prior raw caches and filtered locally; ApeWisdom feeds retail attention momentum |
| **PB7** | Give the `put_call` percentile terms a verified history source | ✅ **Done** — self-built series only; historical Alpha Vantage P/C was removed from the scheduled path |
| **PB8** | **Make every request meter.** Route preflight's metered probes through the client path | ✅ **Done** — `preflight.py` reserves budget before probing |
| **PB9** | Adopt the PA8 and PA9 winners as second feeds for analyst and macro | ✅ **Both halves done.** FRED is macro primary, FMP demoted to fallback. Finnhub is the analyst second feed **for US names**; EU stays sole-sourced on FMP |

**Phase B acceptance:**

- `pytest` green including the registry↔client bidirectional coverage assertions.
- `python -m briefing_app.preflight` reports every new source `ok` with raw caches landing under `data/raw/<provider>/<endpoint>/`.
- A live-mode run of the daily pipeline exercises each new source end-to-end, and every score component that previously degraded to `n/a` for a live ticker now carries a sourced value.
- `docs/SOURCE_STATUS.md` regenerated to reflect the new source set.
- Failing sub-scores degrade explicitly (Tier C or `n/a` with a reason), never silently.
- Each new client carries a regression test asserting that a refusal writes **nothing** to the raw cache — `response.cache_path is None` for a throttle notice, a degenerate-CSV body, and a premium sample payload. The invariant lives in `base.py:230-252` and is currently tested only through preflight (`test_preflight.py:396`), which is not the path that wrote the 47 purged entries.

## Phase C - Second Pass: Re-search And Wire Whatever Still Fails

Phase A searched once, against a list written from one audit. Phase C is the standing loop that closes the remainder: sources still failing after Phase B, adopted sources that later regress, and gaps Phase A closed with "no free source exists". It runs after Phase B lands and again at every provider audit, appending to the same ledger rather than starting over.

| Task | Work | Notes |
|---|---|---|
| **PC1** | Build the failure list from evidence: run routine preflight plus one live pipeline run, then record in `docs/alternatives/still-failing.md` (a) every `required` endpoint not `ok`, (b) every sub-score still `n/a` or silently absent for a live ticker, (c) every adopted source that regressed since its Phase A verdict. Stamp each entry with the run id and date | ✅ **Done 2026-09-02.** `PC1-LIVE-01` and `PC1-LIVE-02` were then closed by the sector-exposure config update; the remaining Phase C queue starts from the other PC1 rows |
| **PC2** | ✅ **Done 2026-09-03.** After regenerating the ledger, exactly one row had a genuine search behind it — `PC1-LIVE-05`, retail-momentum coverage — and **its premise was disproven**: ApeWisdom answers 863 tickers over 9 pages and the pipeline was reading page 1. No source adopted. Finnhub `social-sentiment` rejected on entitlement (403, probed), StockTwits rejected on anti-bot (Cloudflare, probed). `docs/alternatives/pc2-retail-momentum-coverage.md`. Original brief: search again for each entry, but only past the ledger: candidates already rejected in `docs/alternatives/` are re-opened **only** when the rejection reason was time-dependent (a new free tier, a pricing change, an endpoint that did not exist before) and the change is cited with a date. Anti-bot and licensing rejections are not re-litigated | Widen the net in cost order: (1) an endpoint on an already-entitled provider the first pass missed; (2) a source of a **different shape** — bulk file, exchange CSV, regulator register, RSS — since most first-pass survivors fail because the search assumed a JSON API; (3) a normalization layer (OpenBB) carrying a provider the search missed; (4) a paid tier, specced with monthly cost and the sub-score it unblocks, for a decision and not a purchase |
| **PC3** | ✅ **Done for the rows this pass covered, 2026-09-03.** Index and fund candidates are declared to have no analyst leg and no insider leg — `Candidate.is_index_or_etf`, recorded in `docs/SOURCE_STATUS.md` under *Permanently unavailable, by declaration* — closing `PC1-LIVE-07` and the ETF half of `PC1-LIVE-08`, and stopping the requests. **The weight table got honest:** `S_S` is now `0.80 / 0.00 / 0.20` instead of `0.45 / 0.35 / 0.20` re-normalized away every run, which is exactly what the arithmetic already produced. Data-state treatments (`political_flow`, `S_I.seniority`, `S_O.skew`) and the EU capture rows remain open — see the ledger's priority list. Original brief: close the dead ends explicitly. Where the second pass finds nothing, mark the entry permanently unavailable in `docs/SOURCE_STATUS.md`, make the sub-score degrade with a named reason instead of silently renormalizing, and where a leg can never score, propose dropping its weight rather than leaving a term that is structurally always absent | A permanent `n/a` recorded once is cheaper than a search repeated at every audit. This is also where the weight table gets honest: `iv_extreme` and `short_borrow` currently vanish into a renormalized denominator |
| **PC4** | ✅ **Done 2026-09-03.** The rows that needed wiring were regressions, not adoptions: FMP 429 with local headroom → the day's ceiling is learned from the provider's own refusal and persisted beside the counter (`PC1-RAW-16`); FRED read timeouts → bounded retry on transport faults only, metered per attempt (`PC1-RAW-15`); Alpha Vantage's repeatable `malformed` → parked for the run after two refusals (`PC1-RAW-17`, the ticket `q6-alpha-vantage-allocation.md` §1 asked for). `PC1-RAW-18`/`-19` close as consequences. 27 new tests; suite 567 green on that pass, then 569 green after N5/I16. Original brief: wire every Phase C adoption through the Phase B contracts — client, registry entry, normalizer, preflight probe, pipeline consumption, budget/plan learning, tests — each landing with its fallback chain defined | No new mechanisms. A source adopted without a fallback chain just moves the next failure somewhere less visible |

Entries expected on the PC1 list if Phase B changes nothing else: Bundesanzeiger net shorts (`browser_required`), Eurex per-strike chains and EU OAM insider/holdings (`manual_required`), the FMP restricted set (`economics`, `stock_news`, `insider_trades`, `institutional_ownership`, `form_13f`) which stays 402 on the free plan, and borrow fee/utilization if PA1's verdict is "no free source".

**Phase C acceptance:**

- `docs/alternatives/still-failing.md` exists, is dated, and was generated from a preflight report plus a live run.
- Every entry is closed exactly one of three ways: adopted and wired, deferred with a paid option specced and costed, or declared permanently unavailable with the reason.
- No entry is closed by re-rejecting a candidate Phase A already rejected for a reason that has not changed.
- `pytest` green; preflight `ok` for every newly adopted source; `docs/SOURCE_STATUS.md` regenerated.
- Every remaining `n/a` sub-score names its reason in the briefing output, and any leg that can never score has a recorded weight decision.

## Ordering

The original ordering (PB1 → PB8 → PA3/PA9 → the rest) is **complete**. What follows is the
remaining queue as of 2026-09-02, after Twelve Data closed the US price-history gap, Q0
dropped historical put/call, and the sector-exposure rows closed the live `S_M` gap.

**Recently closed, no new credential needed:**

1. ~~**Wire the macro calendar.**~~ ✅ **Done 2026-09-02.** `macro_calendar` is built from
   FRED `release/dates`, closing the one matrix row that never had a source. The premise
   check that mattered: the realtime period does bound what comes back, and the
   high-frequency mapped releases are excluded as routine postings
   (`docs/alternatives/p4-macro-calendar.md`).
2. ~~**Map the seven unmapped macro factors**~~ ✅ **Done 2026-09-02.** The shipped sector
   exposure map uses only factors covered by `FRED_MACRO_SERIES`.
3. ~~**Declare the missing sector exposures**~~ ✅ **Done 2026-09-02.** Macro-only
   verification against the PC1 live-report tickers returned `s_m_unavailable=0` and
   `s_m_partial=0`.
4. ~~**Expose `S_O` in per-ticker sections.**~~ ✅ **Done 2026-09-03.** The live dashboard
   now emits the options component with its six defined legs, absent reasons and
   diagnostics, closing `PC1-LIVE-10`.
5. ~~**Persist self-built baselines locally.**~~ ✅ **Done 2026-09-03.** Local runs use
   `$BRIEFING_DATA_DIR/briefing.sqlite3` when `DATABASE_URL` is unset, so
   `PC1-LIVE-11` is operationally closed and the remaining `iv_extreme` gap is just the
   20-session warm-up tracked as `PC1-LIVE-12`.
6. ~~**Regenerate `docs/SOURCE_STATUS.md`.**~~ ✅ **Done 2026-09-03.** Header and summary
   table now come from the `2026-09-03T13:10:58` deep preflight over 50 endpoints.

**Deferred or blocked, each with a written reason:**

7. **PB4 EU remainder** — Twelve Data gates RHM.DE/LDO.MI behind paid plans; A2 decides
   whether they stay as context rows or leave the universe.
8. **PB1's 13F half** — blocked by design, not by wiring (`pb1-13f-blocker.md`).
9. **PB5 / PA5** — FCA has no UK names to serve; EU chains are a structural reject.
10. **PA2(b)** — Tradier failover for CBOE. Redundancy for a source that has not failed, so
   it ranks below every leg above that has no source at all.

**Phase C has run once end to end.** `docs/alternatives/still-failing.md` was regenerated
from live run `daily-2026-09-03-c7e82663` plus the `2026-09-03T13:10:58` deep preflight,
and PC2/PC3/PC4 executed against it on the same day. Eleven rows closed.

The regeneration corrected a premise the queue had been carrying: **`PC1-LIVE-03` was not
the largest open row.** `S_F` was already closed on 2026-09-02 by Q4 as a deliberate
permanent `n/a`, with `institutional: []` and the decision emitted as the component's own
reason. So was `S_S.executive_tone` (Q1). What the regenerated ledger found instead were
two **adopted-source regressions** — FMP throughput and FRED timeouts — that no preflight
could ever have surfaced, because preflight sends one request per endpoint and both
failures are about the hundredth.

The next items must cite rows still **OPEN** in the ledger. The largest is `PC1-LIVE-12`,
and it is blocked on elapsed time rather than on work: roughly 20 trading sessions of
persisted snapshots from 2026-09-03, so early October, before `iv_rank` exists and the six
best-graded names can become tradeable.

> **Amended 2026-09-06 — "the six best-graded names" no longer identifies a set, and IV
> rank is no longer the only thing between them and a trade.** That phrase named the six
> `A`/`B+` `WATCHLIST` rows of live run `daily-2026-09-03-c7e82663`. Two things have moved
> since. **Grade ordering changed** (`G2`/`G2b` in `HANDOFF.md`): the directional branch of
> `alignment()` was on the wrong scale, so the old ranking sorted by setup type rather than
> by quality and the names at the top were not the ones the fix leaves at the top.
> **And two of that set can no longer become tradeable at all**: `REQUIRED_COMPONENTS` for
> `V`/`E` now includes `S_S`, which is structurally `unavailable` for an index, so QQQ and
> SPY are Tier C and `ConfidenceTier.C.is_tradeable` is false — `iv_rank` arriving in
> October does not lift them. Everything about `PC1-LIVE-12` itself stands: the blocker is
> still elapsed time, and it still gates every `iv_rank`-dependent row.
