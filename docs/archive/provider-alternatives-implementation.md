# Provider Alternatives — Implementation Tasks

The "how" for `docs/archive/provider-alternatives-wiring-tasks.md`, which holds the audit, the coverage
matrix and the research verdicts. Read that first; this file assumes its findings.

## Decisions already locked

| Decision | Answer | Consequence for these tickets |
|---|---|---|
| Spending | **Free tiers only** | No ticket adopts a paid tier. Where a paid option is clearly better, the ticket records cost and sub-score unblocked, then stops and asks. |
| Alpha Vantage | **Metered fallback only where useful** | The client, registry entries and normalizers stay for useful endpoints. The scheduled historical put/call path was removed because self-built P/C baselines make it redundant and it spends the 25/day budget. |
| Approved free signups | FRED, Finnhub, Twelve Data; Quiver optional | Updated 2026-09-02. **`FRED_API_KEY`, `FINNHUB_API_KEY`, and `TWELVE_DATA_API_KEY` are set and wired.** Twelve Data covers the six FMP-gated US price-history symbols; EU names remain paid-plan gated. **`QUIVER_API_KEY` is optional, not required** — PA6 found FMP's congressional feeds entitled on the existing key, so Quiver buys per-ticker depth rather than access. Tiingo dropped in favour of Twelve Data on coverage (PA4). |

## Ticket conventions

Every ticket that adds a source follows the existing contract — no new mechanisms:

1. Client in `src/briefing_app/providers/<provider>.py` extending `base.py`, declaring
   `provider_id`, `credential_env`, `base_url`, and `premium_endpoints` where the free
   tier gates anything.
2. Registry entries in `config/source_registry.yaml` — URL templates, cache slots, probe
   tier, `required` flag.
3. Normalizers in `providers/normalizers.py` producing the **existing** models. No new
   model unless the ticket says so.
4. Preflight is registry-driven, so a registry entry is probed automatically; the
   registry↔client assertions in `test_preflight.py` must still pass.
5. Consumption in `pipeline.py` with an explicit fallback chain.
6. Tests in `tests/test_provider_clients.py` and `test_provider_normalizers.py`, including
   the refusal taxonomy (endpoint-gate vs symbol-gate vs quota) and the
   **never-cache-a-refusal** assertion (`response.cache_path is None`).
7. Credential documented in `.env.example`, `README.md`, and the n8n/cloud runbooks.

**Definition of done for every ticket:** `pytest` green, `preflight` reports the new
endpoints with a true status, and the ticket states which coverage-matrix row it closed.

---

## Status — 2026-08-31, end of day (test count and Q6 rows refreshed 2026-09-03)

| Ticket | Status |
|---|---|
| **I0** fallback chains | ✅ Done — `ProvidersSettings`, 13 legs, modelled not `model_extra` |
| **I1** preflight metering | ✅ Done |
| **I2** EDGAR → S_I / S_F | ✅ **S_I done.** ⛔ S_F blocked by design (`docs/research/alternatives/pb1-13f-blocker.md`). The ticket assumed the normalizers worked; **both were scaffolding with 19 undefined helpers and no tests** |
| **I3** FINRA → borrow leg | ✅ Done, as a labelled short-**volume** proxy on its own field |
| **I4** FCA short positions | ⏭ Deferred — universe has zero UK names, and there is no FCA client to "wire" (`docs/research/alternatives/pb5-fca-deferred.md`) |
| **I5** FRED client | ✅ Done — client, 2 normalizers, 3 registry entries, tests |
| **I6** Finnhub client | ✅ Done — client, 2 normalizers, local tone scorer, 2 registry entries, tests. Probed live through the client 2026-09-01 |
| **I7** Quiver client | 🔄 **Superseded.** PA6 found FMP's congressional feeds entitled on the existing key; Quiver is optional, for per-ticker depth only |
| **I8** Tiingo *or* Twelve Data | ✅ Done — Twelve Data client, budget, registry entry and normalizer wired for daily OHLCV |
| **I9** news → Finnhub | ✅ Done — `news: [finnhub, alpha_vantage, fmp]`. The leg that had **no working source** now has one. Tone derived locally and labelled as such; ~50% of articles measurable |
| **I10** macro → FRED primary | ✅ **Done, both halves.** `macro: [fred, fmp]`, verified live. The readings landed 2026-08-31; the **calendar** landed 2026-09-02 from `release/dates` — the coverage-matrix row that never had a source (`docs/research/alternatives/p4-macro-calendar.md`) |
| **I11** analyst second feed | ✅ **Done for US names.** `analyst: [fmp, finnhub]`. Finnhub's free tier is US-only, so EU names stay sole-sourced on FMP — an honest partial close |
| **I12** political + retail | ✅ Done — FMP `senate-latest`/`house-latest` feed capped `political_flow`; ApeWisdom feeds `retail_momentum` |
| **I13** gated-symbol prices | ✅ Done for the US gap — `prices: [fmp, twelve_data, alpha_vantage]`; AVGO, ORCL, MU, QQQ, CRWV and AMAT now have a live fallback. RHM.DE and LDO.MI remain paid-plan gated and are covered by A2 |
| **I14** self-built trailing series | ✅ Done — `iv_history` and put/call, 20-session warm-up enforced. Historical AV P/C was removed from the scheduled path on 2026-09-02 |
| **PC1 sector exposures** | ✅ Done — shipped `sector_exposures` cover every sector in the 24-ticker live report, with `Defense` spelling normalized |
| **I15** explicit degradation | ✅ Done — structural `n/a` decisions are declared, component output exposes legs-scored-of-defined, absent legs and reasons, and the 09-03 dashboard now includes `S_O` sub-score detail per ticker. Remaining ledger rows are time/data/manual decisions, not silent-loss defects |
| **I16** regenerate documentation | ✅ Done — `docs/research/SOURCE_STATUS.md` header and summary table are refreshed from the 2026-09-03T13:10:58 deep preflight over 50 endpoints, and the coverage / Phase C docs point at the same 09-03 live evidence. Post-refresh FRED/AV registry tweaks will be proven by the next preflight |

**Not in the original ticket list, landed anyway:**

- **Release-date ageing** (`MacroEvent.released_at`) plus the completed factor map. `S_M`
  was scoring **one factor out of eleven** because both providers date an observation by
  the period it measures. The 2026-09-02 macro-only verifier reads ten cached FRED factors.
- **Three defects** found while building the graded report: a fixture IV surface inconsistent
  with its own price bars (implied vol 7.9x realized), a float-noise crash in
  `density_from_call_prices`, and a divergence threshold that fired on ordinary VRP.

Test suite: **569 passing, zero failures** (verified 2026-09-03, after N1, N4, N5 and
I16).

## Ask me — open decisions

Do not guess these. Two are needed before the tickets that depend on them start; the rest
surface mid-implementation.

| # | Decision | When to ask | Why it can't be defaulted |
|---|---|---|---|
| **A1** | **Tiingo or Twelve Data** for gated-symbol prices | **Before I8** | ✅ **Closed for the US gap.** Twelve Data resolves all six FMP-gated US symbols on the verified key. EU names remain gated behind paid Twelve Data plans and are covered by A2. |
| **A2** | **FMP gated symbols: adopt an alternative, or drop them from the universe?** | **Before I13** | ⚠️ **Scope grew.** Six symbols now, not four: AVGO, ORCL, MU, QQQ **+ CRWV, AMAT**, plus both EU names. PA5 also found EU names are Tier C by construction regardless, which makes dropping them cheaper than it looks. |
| **A3** | `executive_tone` (0.35 of S_S): fund a transcript source, or declare it permanently `n/a` and redistribute the weight? | Closed 2026-09-02 (Q1) | Declared permanently `n/a`; free transcript sources were rejected and the printed `S_S` weights now show `executive_tone` at `0.00`. |
| **A4** | If a leg is permanently `n/a`, does its weight redistribute across survivors or shrink the component's confidence? | Closed 2026-09-03 (PC3) | Permanent `n/a` weights redistribute across live survivors, but the component output now names absent legs, `weight_used`, and the decision reason instead of hiding the move. |
| **A5** | `iv_history` warm-up: accept it, or buy history? | ~~At I15~~ | 🔶 **Implemented as self-build with a 20-session warm-up** (`SELF_BUILT_SERIES_MIN_SESSIONS`). Below that the series is withheld and the run reports "N of 20 sessions stored". Still open only if the wait proves unacceptable in practice — PA2 rejected buying history for a 0.10-weight leg. |
| **A6** | Quiver free-tier scope | ~~At I9~~ | ✅ **Moot.** Neither leg needs Quiver: FMP `senate-latest`/`house-latest` are entitled on the existing key, and ApeWisdom is keyless for retail. Stocktwits, the filed alternative, has an API **frozen to new developers** — it was never viable. |
| **A7** | Retail sentiment is noisy and easily gamed. Cap it below its nominal 0.20, or let it score at full weight? | At I14 | A signal-quality judgement about your own framework. |

---

## Wave 0 — Foundations

**Everything here is unblocked today.** I0 blocks most of Wave 2, so start it first.

### I0 — Make fallback chains real *(blocks I10–I14)*

Today `_provider_order` (`pipeline.py:2203-2209`) takes a preferred provider and appends a
**hardcoded** tail of `("alpha_vantage", "fmp")`. No new provider can enter a fallback
chain without changing this function. `_provider_choice` (`pipeline.py:2195-2200`) reads an
unmodelled `config.model_extra["providers"]` block that covers only five legs
(`config/config.example.yaml:109-114`): quotes, options, news, earnings, macro. Insider,
institutional, analyst, price history, put/call, political and retail have no knob at all —
their chains are hardcoded inside each `_pull_*` method.

- Replace `_provider_order(preferred)` with an ordered-list lookup: config supplies the
  full chain per leg, and the function returns it verbatim rather than appending a tail.
- Model the `providers:` block properly in `config.py` instead of `model_extra`, with a key
  per leg: `options, quotes, prices, news, earnings, macro, analyst, insider,
  institutional, put_call, political, retail, short_interest`.
- Each value is a list, e.g. `news: [finnhub, alpha_vantage]`. A single string still parses,
  for backward compatibility with the current example config.
- Unknown provider names fail **config load**, not the run — a typo must not silently drop a
  leg to no-source.
- Update `config/config.example.yaml` with the full block and comments.

**Acceptance:** a leg's chain is changed by editing config alone, with no pipeline edit. A
test asserts an unknown provider name raises at load, and that a chain of
`[finnhub, alpha_vantage]` calls Finnhub first and AV only on failure.

### I1 — Preflight must meter every request

`preflight.py:123` fetches through `UrlLibFetcher` and never touches `RequestBudget`, so
`budget.reserve` (`base.py:119`) is bypassed. The credentialed audit spent ~20 FMP and 1 AV
request and wrote no `data/provider_budget/2026-08-31.json` at all.

- Route metered probes through the client path, or call `budget.reserve` directly from the
  probe loop. Unmetered sources (CBOE, FINRA, EDGAR, FCA) must not gain a budget file.
- `--deep` must account for all twelve extra AV requests.

**Acceptance:** a probe against a metered provider increments that day's counter; a test
asserts the counter moves. Free sources still write nothing.

### I2 — Wire SEC EDGAR into S_I and S_F *(highest value in Wave 0)*

The audit made this critical path, not cleanup: with AV refusing and FMP `paywalled`, the
already-written EDGAR client is the **only** working source for both components, and the
pipeline never calls it.

- Add EDGAR to the `_insider_transactions` chain (`pipeline.py:1849-1874`) — Form 4 bodies
  via `company_submissions` → `filing_document`, normalized to `InsiderTransaction`.
- Add EDGAR 13F to `_ownership_changes` (`pipeline.py:1890-1915`), normalized to
  `OwnershipChange`.
- EDGAR leads both chains; AV and FMP fall in behind it.
- Fix `BRIEFING_USER_AGENT` — still the placeholder `contact@example.com`, which preflight
  flags and which EDGAR may block without warning.

**Acceptance:** a live run produces sourced S_I and S_F values with AV and FMP both
refusing. Evidence rows cite the EDGAR accession number.

### I3 — Wire FINRA into the S_O borrow leg

`pipeline.py:51` imports `ShortBorrowSnapshot` and nothing constructs one, so `short_borrow`
(weight 0.05) never scores. `normalize_finra_short_volume` (`normalizers.py:1433`) and the
client already exist and pass tests.

- Fetch FINRA short volume per ticker, normalize to `ShortInterestSnapshot`
  (`models/market_data.py:441`), and pass a `ShortBorrowSnapshot` into
  `build_options_structure`.
- **Label it honestly**: this is daily short *volume*, not short interest and not borrow
  fee. The evidence row and dashboard must not imply otherwise.
- Whether borrow fee/utilization can ever be sourced free is PA1's verdict; if not, that
  half stays `n/a` via I16.

**Acceptance:** `short_borrow` scores on a live run, sourced from FINRA, labelled as a
volume proxy.

### I4 — Wire FCA short positions

Fetchable and `ok` on the audit, just unconsumed. A 3.1 MB XLSX, no key or session.

- Consume the existing FCA probe path in the pipeline for EU/UK names; normalize to
  `ShortInterestSnapshot` via the existing `manual.py` loader shape.
- Independent of every EU research task — it does not wait on PA5.

**Parallelism in Wave 0:** I0 and I1 are independent of each other and of everything else.
**I2, I3 and I4 all edit `pipeline.py`** — parallel-safe in review but they will conflict in
that one file, so either land them in sequence or expect a merge. I2 first, it carries the
most value.

---

## Wave 1 — New provider clients

**Fully parallel.** Each ticket is a new file plus append-only additions to
`source_registry.yaml` and `normalizers.py`. No ticket here touches `pipeline.py`, so none
of them conflict. All four depend on nothing except their signup.

### I5 — FRED client (macro)

The strongest candidate in the audit: official primary data replacing a sole aggregator,
which also upgrades S_M's source-quality label.

- Client `providers/fred.py`, `credential_env = FRED_API_KEY`, base
  `https://api.stlouisfed.org/fred`.
- Cover every series in `FMP_MACRO_INDICATORS` (`pipeline.py:123-130`) — policy rate, CPI,
  inflation, unemployment, real GDP, retail sales — plus the Treasury curve behind
  `TREASURY_FACTORS`.
- One cache slot per series, following the FMP `economic_indicators` pattern
  (`cache_target_template` = the series id).
- Normalize to the existing `MacroEvent` / macro reading models. **No new model.**
- Confirm the free-tier terms permit self-hosted personal use; record it in the ticket.

**Also closes the macro-calendar gap** if FRED's release calendar is usable — FMP's
`economic-calendar` is `paywalled` and that row currently has no source at all.

### I6 — Finnhub client (news + analyst) — ✅ Done

Implemented 2026-09-01. Full evidence: `docs/research/alternatives/pb3-finnhub-news-and-analyst.md`.

- `providers/finnhub.py`, `credential_env = FINNHUB_API_KEY`. Two endpoints, both probed
  **through the shipping client** on 2026-09-01: `company-news` (HTTP 200, 247 rows) and
  `stock/recommendation` (HTTP 200, 4 monthly rows).
- **Price targets are not part of it.** Finnhub's is 403 on the free tier, so target
  consensus stays sole-sourced on FMP. `news_sentiment`, `price_target` and `transcripts`
  are declared in `premium_endpoints` so preflight reports them plan-gated, not untried.
- Normalized to the existing `NewsArticle` / `NewsSentimentBatch` and `AnalystSignal`. No
  new model.
- **Free tier is a rate limit, not a daily allowance**: 60 req/min, a 30/second ceiling in
  the terms, no published daily cap. The budget policy paces at 1.05s and declares
  `daily_requests=None` rather than inventing a number the provider never stated.
- **Free tier is US-only.** `RHM.DE` answers 403, so the client refuses an
  exchange-suffixed symbol before spending a request — and raises it directly rather than
  through `_response`, so a symbol boundary is never memoised as an endpoint plan gate.
  Only a suffix longer than one character counts, so `BRK.B` is not falsely refused.
- **Tone is derived locally**, since `/news-sentiment` is 403 exactly as PA3 predicted.
  `providers/news_tone.py` is a lexicon on Alpha Vantage's scale and bands; the batch names
  itself `local tone`. An unmatched headline scores `None`, never `0.0` — a neutral zero
  would be averaged in and dilute a real signal. ~50% of live articles score.

### I7 — Quiver client (political + retail)

Verified 2026-08-31: `api.quiverquant.com/beta/historical/congresstrading/{ticker}` is live
and key-gated (HTTP 401, clean JSON), so T13's endpoint pattern holds.

- Client `providers/quiver.py`, `credential_env = QUIVER_API_KEY`,
  `Authorization: Bearer`.
- Congressional trades by ticker → new normalized model per T13 (representative, politician
  id, transaction type, transaction date, report date, amount range, owner/party, source).
- WSB/retail dataset if the free key returns it → **A6**.
- Missing key must report `no_credentials`, never failure — T13 acceptance.
- **Do not add insider or institutional endpoints.** EDGAR is the primary record and is
  free and working; an aggregator there downgrades source quality for no gain.

### I8 — Tiingo *or* Twelve Data client (prices) — ✅ Done

Twelve Data was selected after the free-key probe recorded in `HANDOFF.md`: AVGO, ORCL,
MU, QQQ, CRWV and AMAT resolve; RHM.DE and LDO.MI are available only starting with a paid
Twelve Data plan.

Implemented 2026-09-02:

- `providers/twelve_data.py`, `credential_env = TWELVE_DATA_API_KEY`,
  `https://api.twelvedata.com/time_series`.
- `normalize_twelve_data_time_series` maps daily OHLCV to the existing `PriceBar` model,
  oldest-first.
- Registry entry `twelve_data.time_series` probes AVGO, one of the FMP-gated US symbols.
- `RequestBudget` defaults to 800 requests/day with 7.6s pacing, matching the Basic
  plan's 8 credits/minute limit for one-symbol `time_series` calls.

---

## Wave 2 — Wire the alternatives into legs

**Serialized on `pipeline.py`.** Every ticket here edits the same file, so treat the wave as
a queue, not a fan-out. All depend on **I0**; each also depends on its Wave 1 client.

Order by how much of the report is dark: news, macro and the two never-scored S_S legs
first.

### I9 — News leg → Finnhub primary, AV fallback *(needs I0, I6)* — ✅ Done

`_news_batch` chain is `[finnhub, alpha_vantage, fmp]`. Closes the matrix row that had
**no working source** at all.

The AV scored feed is no longer the selected primary, so what the leg now reports is a
locally derived tone over the half of the articles a lexicon can read. That is a real
downgrade in signal quality against a working AV feed, and a large upgrade against the
nothing it replaced.

### I10 — Macro leg → FRED primary *(needs I0, I5)* — ✅ Done

`_macro_readings_for_run` leads with FRED; FMP becomes fallback; AV stays last. Upgrades
the S_M source-quality label from aggregator to primary.

The **calendar** half landed 2026-09-02. `_macro_calendar_for_run` gained a FRED branch
ahead of FMP's 402, joining declared factor → series → `series/release` → `release/dates`
asked forwards. Three things the ticket did not anticipate:

- **A routine posting is not a catalyst.** Nine of the eleven mapped series sit on releases
  that publish daily or weekly, which would put 42 rows — or, after P5, 16 — in a 30-day
  calendar. Releases publishing weekly or more often are dropped, with the cadence recorded
  as a diagnostic. The threshold moved from `<` to `<=` once P5 measured what the weekly
  releases actually are: price postings, which carry no information at publication.
- **`release/dates` now answers two questions**, so it is asked twice per release and needs
  two cache slots: `<release_id>` for the historical window that dates a reading,
  `<release_id>_upcoming` for the forward one.
- **No consensus estimate.** FRED publishes a schedule, not a survey, so the calendar feeds
  event risk and the dated table and adds nothing to `S_M`'s score.

### I11 — Analyst leg → second feed *(needs I0, I6)* — ✅ Done for US names

`_analyst_signals` gains Finnhub behind FMP: `analyst: [fmp, finnhub]`.

- **Fallback, not merge.** Finnhub answers only when FMP produced nothing. Both report the
  same buy/hold/sell counts, so running both would double-weight one quarter's consensus
  by counting the same analysts twice under two labels.
- **Counts, not a vendor score** — the note `SOURCE_STATUS` carries about FMP's
  `ratings-snapshot`, applied to the other provider. A second feed whose numbers cannot be
  compared with the first is not redundancy.
- **EU names are not covered.** Finnhub's free tier is US-only, so `RHM.DE` and `LDO.MI`
  stay sole-sourced on FMP — which 402s both, so their analyst leg was `n/a` before and is
  `n/a` now. The matrix row reads "second feed for US names", not "closed".

### I12 — `political_flow` + `retail_momentum` *(needs I0, I7)* — ✅ Done

Implemented with the PA6 replacements for Quiver:

- FMP `senate-latest` and `house-latest` are fetched once per run with no symbol, limit or
  page params, cached, combined with prior cached rows inside the 90-day scoring window,
  de-duplicated, then filtered locally against each ticker.
- `political_flow` is a capped +/-0.05 `S_S` overlay. Purchases score bullish, sales
  bearish, exchange/unknown rows are `n/a`, and the score is weighted by recency,
  disclosed amount range and disclosure lag.
- ApeWisdom `all-stocks/page/1` is fetched once per run and feeds `retail_momentum` from
  `mentions - mentions_24h_ago`. It is labelled as attention, not sentiment.
- `build_sentiment_component` now receives both live inputs at the call site.
- Dashboard shows recent congressional buys/sells per ticker with staleness marked; never a
  standalone recommendation.
- Evidence ledger rows per trade, per T13.
- Note in the output that STOCK Act filings can lag 45 days against a ~14-day horizon: this
  is context, not edge.

### I13 — Price history for gated symbols *(needs I0, I8)* — ✅ Done for US

`_price_bars` chain is `[fmp, twelve_data, alpha_vantage]`, so FMP's symbol-gated US
names resolve before the metered Alpha Vantage fallback is touched. This closes the US half
of A2; RHM.DE and LDO.MI remain a separate universe decision because Twelve Data gates
them behind paid plans and the free EU options-chain search was a structural reject.

### I14 — Self-built trailing series: `iv_history` and put/call *(needs I0)* — **A5**

One mechanism serves two matrix rows, and needs no vendor — only storage.

- Persist each run's ATM IV and put/call volume/OI ratios, both already computed from the
  CBOE chain the pipeline fetches anyway (`options_math.py:626-654` for the ratios).
- Feed the stored series into `build_options_structure` as `iv_history`
  and into the `pc_ratio_vol_history` / `pc_ratio_oi_history` inputs to
  `build_options_structure`.
- Revives `iv_extreme` (0.10) — which has **never** scored — and makes the `put_call`
  percentiles (0.25) independent of Alpha Vantage quota and entitlement.
- Warm-up is real: the series starts empty. Until it fills, both legs must report `n/a`
  with "building baseline, N sessions of M" — never a rank computed from three points.

---

## Wave 3 — Honesty and documentation

### I15 — Explicit degradation, no silent renormalization *(needs Wave 2)* — ✅ Done

`standardize_so_score` (`options_math.py:945-1001`) and `combine_sub_scores` renormalize
over whatever legs are present, so a missing leg vanishes into the denominator and the
score looks complete unless the report exposes the denominator. That contradicted the
acceptance criterion that failing sub-scores degrade explicitly.

Implemented 2026-09-03:

- Every absent leg reports `n/a` with a named reason in the briefing output.
- A leg that can never score gets a recorded weight decision — **A3** and **A4** are closed.
- Per-ticker sections include `S_O` with its six defined legs, `weight_used`,
  `absent_legs`, sample-size details and diagnostics.
- Evidence-ledger cache targets no longer manufacture fake ticker sections.
- Local runs persist by default to `$BRIEFING_DATA_DIR/briefing.sqlite3`, so self-built
  IV and put/call baselines can warm up without `DATABASE_URL`.
- Add a test that a component with a missing leg exposes the absence rather than
  redistributing it silently.

### I16 — Regenerate documentation *(needs Wave 2)* — ✅ Done

- `docs/research/SOURCE_STATUS.md` header and active summary table now come from the fresh
  credentialed deep preflight:
  `output/preflight/preflight-2026-09-03T131058.260942Z0000.json`.
- `docs/archive/provider-alternatives-wiring-tasks.md` and `docs/archive/still-failing.md` name the
  09-03 live run and split closed rows from open Phase C rows.
- `.env.example` and `README.md` document the default local SQLite persistence that keeps
  self-built baselines alive outside Postgres.
- Follow-up: the next preflight should prove the two registry changes made after the
  snapshot, `fred.release_dates` / `fred.series_release` probe enablement and demotion of
  `alpha_vantage.realtime_put_call_ratio` to optional.

---

## Parallelism summary

```text
Wave 0   I0 ──┐   (blocks I9–I14)
         I1   │   independent
         I2 ──┤   \
         I3   │    >  same file: pipeline.py — land in sequence, I2 first
         I4 ──┘   /

Wave 1   I5  I6  I7  I8      fully parallel — new files, no shared edits
                             (I8 opens with a probe, then asks A1)

Wave 2   I9 → I10 → I11 → I12 → I13 → I14
                             all edit pipeline.py — a queue, not a fan-out
                             each needs I0 plus its own Wave 1 client

Wave 3   I15 ✓  I16 ✓        complete
```

**Genuine parallelism** is Wave 1: four independent clients, four independent signups. Wave 0
can run alongside Wave 1 throughout. Wave 2 is the bottleneck by construction — one file,
one queue.

**Current remaining path:** only the open Phase C rows from
`docs/archive/still-failing.md`.

**Highest value per hour from here:** do not reopen `S_F`; it is closed by decision. The
largest open row is `PC1-LIVE-12`, which needs elapsed sessions for the IV baseline unless
a paid backfill is bought. The actionable queue is the data-state decisions for
`political_flow`, `S_I.seniority`, and `S_O.skew`.
