# Free Sources For Historical Option Chains

Research date: 2026-09-07/08. Closes **D12**, which was left open pending exactly this survey.

**This is also the PA2 "decision A5" revisit.** A5 said to revisit paid IV history *only if the
20-session warm-up proved unacceptable in practice*. It has: 3 of 20 sessions stored after five
days, `iv_rank` NULL on every stored row, and the free allowance implying two more weeks. The
condition is met, so the question is reopened here and answered.

**Verdict up front: no free source serves what the backfill needs, and $49.99 of Alpha Vantage
premium for one month is the cheapest path.** Two free candidates came genuinely close and both
fail on a specific, checkable ground, and — pointedly — on *opposite* grounds:

- **DoltHub** serves real past-dated chains with implied volatility, and has **no volume and no
  open-interest columns at all**, so `pc_ratio_vol` and `pc_ratio_oi` are uncomputable.
- **MarketData.app** serves real past-dated chains with volume, open interest *and* the
  underlying spot — verified live, keyless — and returns **`iv` null on every row whenever a
  past date is requested**, so `iv_atm` is uncomputable.

Between them they cover all five fields; neither covers them alone, and they are different
vendors' chains, so splicing them is not a serious proposal. The one field no free source
supplies historically is the one this whole exercise exists to obtain: **ATM implied volatility
on a past date.**

---

## The premise, stated precisely

`build_backfill_snapshot_row` (`backfill.py:258`) stores five values per (ticker, past date):
`iv_atm`, `expected_move_1w`, `expected_move_1m`, `pc_ratio_vol`, `pc_ratio_oi`. The last two are
**put/call ratios over volume and over open interest**. So the minimum viable record is a full
option chain *as it stood on a past date*, carrying per-contract strike, expiry, type, implied
volatility, **volume and open interest**, plus that date's spot.

**A live chain is not a historical chain.** Most free options data — CBOE and Tradier included,
both already known to this project — returns the chain as of now. Every row below is judged on
whether it serves a *past date*, and by which endpoint and parameter.

**Scope, from the tool's own dry run** (`backfill-iv --dry-run`, run 2026-09-07 against a
scratchpad `BRIEFING_DATA_DIR` so no shared counter was touched): 18 US tickers — SPY, QQQ, AAPL,
MSFT, META, AMZN, GOOGL, INTC, CRWV, AMAT, ORCL, LMT, XOM, MU, COST, JPM, FDX, GM — over 20
sessions ending 2026-09-04. 360 pairs; 344 remaining against the live database.

---

## I1 — `api.quiverquant.com`: no options data of any kind

Asked by name, so answered directly and first.

**Quiver does not serve option chains.** Its own OpenAPI schema is public and definitive:

```
GET https://api.quiverquant.com/docs/schema.json   -> HTTP 200, 211,118 bytes, 52 endpoints
```

Across all 52 paths the schema contains **zero** occurrences of `implied`, `strike`,
`expiration`, `open interest`, `greek` or `volatility`. The 24 hits for "option" are all
unrelated: an `options` boolean *query flag* on the congressional-trading endpoints (whether a
disclosure was a stock option), `StockAndOptionAwards` in executive compensation, and
`option_type` on top-shareholder grant entries.

Route probes confirm this is absence, not gating — the router answers `401` for paths it knows
and `404` for paths it does not:

| Path | Result |
|---|---|
| `/beta/historical/congresstrading/AAPL` | **401** `Authentication credentials were not provided` — route exists |
| `/beta/live/congresstrading` | **401** — route exists |
| `/beta/historical/options/AAPL` | **404** `Not Found` |
| `/beta/options/chain/AAPL` | **404** |
| `/v1/historical/options/AAPL` | **404** |

The published dataset list on `api.quiverquant.com` is congressional trades and holdings, insider
trades, politician net worth, government contracts, lobbying, corporate donors, patents, hedge
fund activity, executive compensation, top shareholders, off-exchange trading, app ratings and a
newsfeed. No market-data product at all. The API is also **paid from $30/month with no free API
tier**, so it would not have been free even if it had the data.

This matches what PA6 already found from a different angle — Quiver was rejected there for the
political leg because FMP already served it. It is rejected here for a harder reason: the data
does not exist on the platform. **`QUIVER_API_KEY` should stay empty.** Question closed.

---

## I2 — The survey

| Provider | Past-date chains? | IV / volume / OI? | Free-tier limit | Coverage of the 18 | Credential | Verdict |
|---|---|---|---|---|---|---|
| **Alpha Vantage** `HISTORICAL_OPTIONS` | **Yes** — `date=` parameter | **All three** | 25 req/**day** free | 18/18 (wired, proven) | Have it | **Incumbent.** Only wired source that serves a past date |
| **DoltHub** `post-no-preference/options` | **Yes** — `where date='...'` | IV + greeks; **no volume, no OI** | Keyless, unmetered | **16/18** (no QQQ, no CRWV) | **None** | **Reject** — fails 2 of 5 fields outright, and truncates the other 3 |
| **Tradier** sandbox | **No** — verified by route probe | IV/greeks on the *live* chain | Free sandbox token | n/a | Signup | **Reject for backfill.** Stays adopted as PA2's *live* failover |
| **Polygon.io** (now `massive.com`) | Partially, per-contract only | Snapshot has IV+OI but is *as-of-now* | **5 req/min**, 2y history | Unverified | Signup | **Reject** — arithmetically impossible, see below |
| **Databento** | Yes (MBO/definition history) | Yes, from raw feed | Trial credit, then metered | Unverified | Signup | **Unverified** — needs an account; priced per GB, not free |
| **Intrinio** | Yes (paid options add-on) | Yes | No self-serve free tier | Unverified | Sales contact | **Unverified** — gated behind a sales conversation |
| **MarketData.app** | **Yes — verified**, `?date=YYYY-MM-DD` | volume + OI + spot **verified**; **`iv` null on every past-date row** | AAPL keyless; free token = 100 credits/day, 1y history | AAPL verified; **all others 401 without a token** | Signup (except AAPL) | **Reject for `iv_atm`.** Serves 4 of 5 fields. See below |
| **ORATS** | Yes (historical add-on) | Yes | Trial only | Unverified | Signup + card | **Reject** — already rejected as paid by PA2(a) |
| **CBOE** (wired) | **No** — delayed *live* CDN chain | IV, volume, OI | Keyless | 18/18 | None | Live only. Not a backfill source |
| **OpenBB** | — | — | — | — | — | **Not re-proposed.** PA2 rejected it: a normalisation layer, not a source |

### DoltHub `post-no-preference/options` — the near miss, and why it fails

This is the only genuinely free, genuinely keyless, genuinely *past-dated* option-chain source
found. It deserves the detail because it comes closer than anything else and still loses.

Queried live over DoltHub's public SQL API, no credential, HTTP 200 throughout:

```
GET https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master?q=<sql>
```

`show tables` returns `option_chain` and `volatility_history`. The schema of `option_chain`,
read from `describe`, is the whole argument:

```
date, act_symbol, expiration, strike, call_put, bid, ask, vol, delta, gamma, theta, vega, rho
```

**There is no `volume` column and no `open_interest` column.** `vol` is *volatility* — a
`decimal(5,4)` implied-vol figure sitting between `ask` and `delta` — not traded volume. So
`pc_ratio_vol` and `pc_ratio_oi` cannot be computed from this dataset at all, by any amount of
work. Two of the five stored values are simply absent, and the `put_call` leg carries weight
0.25 — more than twice the 0.10 on `iv_extreme` that this whole exercise is about.

Three further defects, each independently disqualifying:

1. **The chain is truncated to four expirations.** AAPL on 2026-08-10 returns 188 rows across
   exactly 4 expirations: 2026-08-24, 2026-09-04, 2026-09-18, 2026-09-25. Every one of the 16
   covered tickers returns the same shape (158–216 rows, 4 expirations). The real chain has
   thousands of contracts. PA2 recorded CBOE returning **13,160** contracts for SPY alone.
2. **The nearest expiry is not a weekly.** On 2026-08-10 the front expiration is 2026-08-24 —
   **14 days out**. `horizons.weekly_target_dte` is 7 and `monthly_target_dte` is 30. So
   `expected_move_1w` would be filled from a 14-DTE straddle while every live row fills it from
   a true ~7-DTE straddle. That is not a small inaccuracy: `iv_rank` is a *percentile of the
   stored series*, so a backfilled history on one convention and a live reading on another
   produces a rank that measures the convention change rather than the volatility. It would be
   worse than the NULL it replaces, because it would look like a number.
3. **Coverage is 16 of 18.** QQQ and CRWV returned no rows for 2026-08-10. CRWV is a 2025
   listing, and QQQ's absence is unexplained. A follow-up query to establish whether they exist
   on other dates **timed out** (`context deadline exceeded`) and is recorded here as
   **unverified**.

The strike ladder is also sparse and irregular — the AAPL 2026-09-04 calls run 215, 230, 245,
255, 260, 270, 275, 285, 290, 295, 300, 305, 310, 315, 320, 325, 335, 340, 345, 355, 360, 370,
385, 400. Usable for an ATM read (spot was ~$310 and there are strikes either side), but it is a
sampled ladder, not the chain. There is no underlying-spot column either; spot would have to be
joined from a price provider.

**One salvageable thing, noted and not recommended.** The sibling `volatility_history` table runs
**2019-02-09 to 2026-09-04** and carries `iv_current`, `iv_year_high`, `iv_year_low`,
`hv_current` per symbol per date — an off-the-shelf IV percentile, free and keyless, with seven
years of depth rather than twenty sessions. It is tempting and it is still wrong for this
purpose: it is a *different vendor's* ATM IV definition, so splicing it under the app's own
`iv_atm` series reintroduces defect 2 above at a larger scale. If the owner ever wants an
`iv_rank` that is deep rather than exact, this is where to look — but it is a different feature,
a code change on a 0.10-weighted leg, and explicitly **not** what is recommended here.

### Tradier — the highest-value question, answered no

PA2(b) adopted Tradier sandbox as the *live* CBOE failover and left open whether it also serves a
past date. **It does not.** Verified by unauthenticated route probe against
`https://sandbox.tradier.com`, using the same 401-vs-404 discrimination as the Quiver check:

| Path | Result |
|---|---|
| `/v1/markets/options/chains?symbol=AAPL&expiration=...&greeks=true` | **401** `Invalid access token` — route exists |
| `/v1/markets/options/expirations`, `/options/strikes`, `/markets/history`, `/markets/timesales` | **401** — routes exist |
| `/v1/markets/options/historical?symbol=AAPL&date=2026-08-10` | **404** `Resource not found` |
| `/v1/markets/options/chains/historical?...` | **404** |
| `/v1/markets/historical/options/chains?...` | **404** |

There is no historical-chain route in the namespace, and `/markets/options/chains` takes
`symbol` and `expiration` — an expiration is the contract's expiry, **not an as-of date**. The
only historical surface Tradier offers is `/markets/history`, which returns daily OHLCV and would
have to be walked one OCC contract at a time; it yields no implied volatility and no open
interest. Tradier remains correctly adopted as the live failover PA2 made it, and is not a
backfill source. *Caveat: probed without a token, so this establishes the route table, not the
response bodies. A token would not create a route that returns 404.*

### MarketData.app — the closest miss, and the one field it will not give up

This is the strongest free result in the survey and it deserves the detail, because it is the
only source found that serves a **correct** past-dated chain: right dates, right expirations,
real strike ladder, real volume, real open interest, and the underlying spot in the same payload.

It also needs **no credential at all for AAPL**, which is how it was verified. The following ran
from this machine with no token:

```
GET https://api.marketdata.app/v1/options/chain/AAPL/?date=2026-08-10   -> HTTP 203, "s":"ok"
```

HTTP 203 is their documented "non-authoritative / delayed" status, not an error. 190 contracts
came back for the 2026-08-21 expiry, and the payload carries exactly the field set the backfill
needs:

```
optionSymbol, underlying, expiration, side, strike, dte, updated, bid, ask, mid, last,
openInterest, volume, underlyingPrice, iv, delta, gamma, theta, vega
```

`updated` is `2026-08-10T20:00:00` — the close of the requested past session, not now.
`underlyingPrice` is `308.26` for every row, which is AAPL's spot on that date. Volume and open
interest are real and populated: 104 of 190 contracts traded, 637,984 contracts of open interest
across the chain. The near-money ladder is dense and correct — 2.50-point strikes through the
money, e.g. the 310 call at `bid 4.45 / ask 4.60, volume 7,631, OI 26,161`.

Widening the expiry window returns the whole chain, and the *right* expirations:

```
GET .../chain/AAPL/?date=2026-08-10&from=2026-08-14&to=2026-09-30
   -> 1,336 contracts across 10 expirations, starting 2026-08-14
```

2026-08-14 is 4 DTE and 2026-09-11 is 32 DTE, so unlike DoltHub this source *does* carry a true
weekly and a true monthly against `weekly_target_dte: 7` and `monthly_target_dte: 30`. One
request per (ticker, date) returns everything needed. `pc_ratio_vol`, `pc_ratio_oi`,
`expected_move_1w` and `expected_move_1m` are all computable from this payload today, for free.

**And `iv` is `null` on all 190 rows. So are `delta`, `gamma`, `theta` and `vega`.**

This is not a stale-data artefact or a recency cutoff, and it is worth being precise about how
that was established, because it is the finding the recommendation turns on. The *same* endpoint,
for the *same* session, returns implied volatility when the date is not requested as history:

| Request | Contracts | `iv` non-null | `updated` |
|---|---|---|---|
| `?dte=30` (no `date=`) | 122 | **122 of 122** | 2026-09-04T20:00:00 |
| `?date=2026-09-04&dte=30` | 122 | **0 of 122** | 2026-09-04T20:00:00 |
| `?date=2026-09-03&dte=30` | 122 | 0 of 122 | 2026-09-03T20:00:00 |
| `?date=2026-09-01&dte=30` | 122 | 0 of 122 | 2026-09-01T20:00:00 |
| `?date=2026-08-28&dte=30` | 122 | 0 of 122 | 2026-08-28T20:00:00 |
| `?date=2026-08-20&dte=30` | 186 | 0 of 186 | 2026-08-20T20:00:00 |

The first two rows are the experiment. **Same session, same 122 contracts, same close: implied
volatility present without `date=`, absent with it.** So this is a property of the past-date
request mode, not a boundary in how far back the greeks reach. Every historical date tested
behaves identically.

Two further limits, both verified:

- **AAPL is the only keyless symbol.** `SPY`, `QQQ` and `CRWV` all return
  `401 {"s":"error","errmsg":"Invalid token header. No credentials provided."}`. AAPL is their
  open demo symbol; the other 17 names need a token this lane may not create.
- **The free tier is 100 credits/day with 1 year of history and a 24-hour delay** (documented,
  not measured — and the per-request credit cost of a 1,336-contract chain is not established,
  so 360 requests may well cost more than 360 credits).

**Verdict: reject, for `iv_atm` specifically.** Four of the five stored fields are free and
verified; the fifth is the one the 20-session warm-up exists to build. It cannot be salvaged by
computing IV locally from the mids either — the live path takes vendor IV from the CBOE chain, so
a backfilled series of locally-inverted Black-Scholes IV under a live series of vendor IV
reintroduces exactly the convention mismatch that disqualified DoltHub, and it would be a code
change on top.

**The one open question left in this entire survey** is whether a registered MarketData.app token
populates `iv` on a past-date request. This lane could not answer it without creating an account
for the owner. The boundary test above predicts it will not — the null is uniform across every
historical date rather than tapering with age, which reads as an endpoint property rather than a
plan gate — but that inference is labelled as such, and it is the one thing worth ten minutes
before paying.

### Polygon.io — entitlement still unverified, but the question no longer matters

PA2 left this as "free tier options entitlement not verified". It is still unverified, and the
reason is a constraint on this lane rather than on the provider: **a free key requires signing up
with an email address, and this lane is not permitted to register the owner for services.** What
was established by probe is only that the routes exist and are key-gated:

```
GET https://api.polygon.io/v3/snapshot/options/AAPL                    -> 401 "API Key was not provided"
   ... with a junk key                                                 -> 401 "Unknown API Key"
GET https://api.polygon.io/v3/reference/options/contracts?...&as_of=   -> 401 (same pair)
GET https://api.polygon.io/v2/aggs/ticker/O:AAPL260904C00310000/...    -> 401 (same pair)
```

The entitlement question is nonetheless **moot**, on structure rather than on plan:

- `v3/snapshot/options/{underlying}` is where implied volatility and open interest live, and it
  is an **as-of-now** snapshot. There is no as-of-date parameter. It cannot serve 2026-08-10.
- The genuinely historical surfaces are `v3/reference/options/contracts?as_of=` — which returns
  contract *definitions*, no IV, no OI, no volume — and `v2/aggs/ticker/O:...`, which is **one
  request per contract per day** and returns OHLCV, so volume but still no IV and no OI.
- The free tier is **5 requests per minute** (documented; the domain has since redirected to
  `massive.com`). Reconstructing even a *sampled* 200-contract chain for 18 tickers over 20
  sessions is 72,000 requests — **240 hours** at 5/min. Reconstructing SPY's real chain alone,
  at PA2's measured 13,160 contracts, is 263,200 requests for one ticker.

So Polygon cannot supply this data on the free tier under any entitlement, and would still be
missing implied volatility and open interest if it could. **The PA2 "monitor" flag can be
retired: Polygon is not a candidate for historical chain backfill.** Its per-contract aggregates
remain a perfectly good source for something else, just not for this.

### The rest — labelled unverified, with the reason

**Databento**, **Intrinio** and **ORATS** all require account creation before any request can be
made, and this lane cannot create accounts on the owner's behalf. None of the three was probed
and no claim about their responses is made here. ORATS was already rejected as paid by PA2(a);
Intrinio's options product sits behind a sales conversation with no self-serve free tier; and
Databento is metered per GB from a trial credit, so it is not free in the sense this lane needs.

---

## I3 — Costed against doing nothing

| Option | Cost | Time to a complete 20-session baseline | Coverage |
|---|---|---|---|
| **Alpha Vantage premium, one month** | **$49.99, cancel anytime** | **~5 minutes** (344 requests at 75/min) | 18/18, same source and convention as live |
| Alpha Vantage free, run daily | free | **14 days at best, realistically longer** | 18/18 eventually |
| Reduced ticker set (5 names) on free | free | ~4–5 days | 5/18 — the other 13 stay NULL |
| DoltHub | free | ~1 hour of query work | **Unusable** — 2 of 5 fields absent, 16/18 names |
| MarketData.app free tier | free | ~1 day (100 credits/day, 360 requests) | **Unusable for `iv_atm`** — 4 of 5 fields only |

Verified: Alpha Vantage's cheapest monthly premium tier is **$49.99/month for 75 requests/minute
with no daily limit**, and the page states "Cancel anytime — no questions asked". At 75/min the
entire 344-pair remainder completes in about five minutes, after which the plan can be cancelled.
The real cost of a complete baseline is therefore **one month, once** — not a subscription.

**The 14-day figure is optimistic, and the config shows why.** `providers.quotes` is
`[alpha_vantage]`, so the live daily run spends Alpha Vantage budget every single day before the
backfill gets any; `news` and `insider` list it too, and `news_alpha_vantage_shortlist` routes
four named tickers to it deliberately. The backfill does not get 25 requests a day, it gets
whatever the live run leaves. Any day the machine is asleep — a failure mode D1 explicitly flags
for the local `launchd` schedule — contributes zero and the clock does not stop. Fourteen days is
a floor, not an estimate.

**And the waiting is not free.** For however long it runs, `iv_rank` is NULL on every row, the
`iv_extreme` leg does not score, and the `put_call` percentile terms are withheld by the same
20-session rule. That is 0.10 + 0.25 of the weight producing nothing, on a product whose whole
output is the grade.

---

## Recommendation

**Buy one month of Alpha Vantage premium at $49.99, run the backfill to completion, cancel.**

The reasoning, plainly:

1. **No free source clears the bar, and the gap is always `iv_atm`.** MarketData.app gives volume,
   open interest, spot and a full correctly-dated chain for free, and withholds implied volatility
   on exactly the past-date requests that matter. DoltHub gives implied volatility and withholds
   volume and open interest. Tradier has no past-date route. Polygon cannot reach the data at 5
   requests a minute even if entitled. Quiver has no options data at all.
2. **It is a purchase, not a subscription.** Five minutes of requests, then cancel. PA2(a)
   rejected paid IV history on the grounds that it was "a subscription to remove a 20-session
   wait" — that objection was correct about a *recurring* cost and does not apply to a one-off
   $50 that is cancelled the same afternoon. This is what changed since A5, along with the
   warm-up proving unacceptable exactly as A5 anticipated.
3. **It is the only option that keeps one convention.** The backfill and the live path would use
   the same provider, the same endpoint and the same normaliser
   (`normalize_alpha_vantage_options_chain`), so the percentile compares like with like. Every
   free alternative splices a second vendor's IV definition under the app's own series and makes
   `iv_rank` measure the splice.
4. **The alternative is fourteen-plus days of a product that does not score.**

**One caveat, honestly stated:** Lane J's correctness reproduction test has not landed. Do not
pay until it has. If `HISTORICAL_OPTIONS` on a paid key does not reproduce a known-good live row,
the $50 buys nothing, and that check costs a handful of free requests.

---

## What the owner must decide

D12 stays open until one of these is chosen:

1. **Pay $49.99 for one month of Alpha Vantage premium, backfill in five minutes, cancel.**
   *This is the recommendation.* Condition: Lane J's reproduction test passes first.
2. **Spend ten minutes checking one thing on MarketData.app first** — *only if you want to be
   thorough; the evidence predicts it fails.* Sign up for the free token this lane could not
   create, and re-run `GET /v1/options/chain/AAPL/?date=2026-08-10`. The single open question is
   whether `iv` comes back populated **with a token**. Everything else about that request is
   already verified working keyless. If `iv` populates, MarketData.app supplies all five fields
   for free and option 1 becomes unnecessary; if it stays null — which the boundary test predicts
   — option 1 is unchanged.
3. **Keep waiting on the free tier** — accept 14+ days with `iv_rank` NULL and 0.35 of the
   scoring weight inert, and accept that a missed run extends it.
4. **Backfill a reduced set** — ~5 names in ~5 days, and live with 13 of 18 rows permanently
   lacking a baseline.

**No free source was found that can do this job.** If the answer is "not paying", then option 3
is the honest one and the product produces no `iv_rank` for another fortnight; option 4 is not
recommended, because a baseline that exists for 5 names and not for 13 makes the grades
incomparable across the report, which is worse than a column that is uniformly empty.

---

## Evidence

Every request below was made from this machine on 2026-09-07/08 and its response recorded. No
Alpha Vantage quota was spent: the only local command run was `backfill-iv --dry-run`, with
`BRIEFING_DATA_DIR` pointed at a scratchpad, and its own diagnostic confirms
`"dry run only: no provider requests sent and no daily_snapshot rows written"`.

- Quiver OpenAPI schema: `GET https://api.quiverquant.com/docs/schema.json` → 200, 52 paths,
  parsed and searched. Route probes 401/404 as tabulated.
- Tradier route table: 9 unauthenticated probes against `https://sandbox.tradier.com`, 401/404
  as tabulated.
- DoltHub: `show tables`, `describe option_chain`, `describe volatility_history`, plus
  per-ticker and per-expiration counts for 2026-08-10, all HTTP 200 over the public SQL API with
  no credential. Two aggregate queries over the full `option_chain` table returned
  `context deadline exceeded` and are marked unverified where cited.
- Polygon: 6 probes (3 endpoints x {no key, junk key}), all 401 with the two distinct error
  strings quoted.
- MarketData.app: 12 unauthenticated requests to `api.marketdata.app/v1/options/chain/`, every
  response parsed field by field, including the live-versus-historical IV boundary test across
  five separate dates.
- Alpha Vantage pricing: `https://www.alphavantage.co/premium/`, read 2026-09-08.
- Scope and remainder: `backfill-iv --dry-run`, 2026-09-07. D12 records 344 remaining against
  the live database.

**Explicitly unverified, with reasons:** Polygon free-tier options entitlement (needs a signup
this lane may not perform); Databento, Intrinio and ORATS response shapes (same); **whether a
MarketData.app token populates `iv` on a past-date request** — the one genuinely open lead, and
the boundary test predicts it will not; MarketData.app's per-request credit cost, so "100
credits/day = 100 requests" is documentation, not measurement; DoltHub coverage of QQQ and CRWV
on dates other than 2026-08-10 (query timeout); DoltHub provenance and licensing terms (not
established — would need checking before any use anyway).

Sources: [Quiver API](https://api.quiverquant.com/), [Tradier API docs](https://docs.tradier.com/),
[DoltHub post-no-preference/options](https://www.dolthub.com/repositories/post-no-preference/options),
[Alpha Vantage premium](https://www.alphavantage.co/premium/),
[MarketData.app option chain](https://www.marketdata.app/docs/api/options/chain/),
[MarketData.app Free Forever plan](https://www.marketdata.app/docs/account/plans/free-forever/)
