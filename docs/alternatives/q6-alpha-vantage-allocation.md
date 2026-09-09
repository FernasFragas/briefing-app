# Q6 / N4 — which legs Alpha Vantage should carry

Plan, 2026-09-02. Implemented 2026-09-03 after N1 confirmed the current config live and
`preflight --deep` confirmed Alpha Vantage was alive.

Implemented outcome:

- `earnings: [fmp, alpha_vantage]` so AV does not spend the daily slot on per-ticker
  earnings.
- AV `NEWS_SENTIMENT` now requests `limit=1000`.
- News allocation is **C - hybrid shortlist**: Finnhub remains first for the broad
  universe; shortlisted names move Alpha Vantage to the front for vendor-scored news.

---

## 0. The constraint that makes this a plan rather than a switch

**A free AV key allows 25 requests per day. The universe is 24 tickers.**

Every candidate leg is per-ticker, so each one costs 24 requests — 96% of the daily
allowance. **Alpha Vantage can carry at most one per-ticker leg per day**, with a single
request to spare.

Q6 is therefore not "AV is alive, so turn it on". It is an allocation with one slot, and
spending it on the wrong leg silently disables every other AV fallback for the rest of the
day via `BudgetExhausted`.

This is also why the sequencing matters: whichever AV leg the pipeline reaches *first*
takes the budget, regardless of which one deserves it.

---

## 1. Step one, and it is free: stop spending the slot on a guaranteed refusal

**Do this before the N1 live run.** It is the highest-value item in Q6 and it costs
nothing to decide.

`earnings: [alpha_vantage, fmp]` puts AV **first**, and `EARNINGS_CALENDAR` is the single
function that refuses — a degenerate CSV body, correctly caught by
`validate_text_data_payload` as `malformed`.

The refusal is **not memoised**:

```
ENTITLEMENT_STATUSES = {paywalled, plan_gated, synthetic}
AV EARNINGS_CALENDAR status = malformed        -> not in the set -> never retired
data/provider_budget/alpha_vantage/plan_gated.json -> does not exist
```

Only an entitlement status retires an endpoint. `malformed` is deliberately excluded,
because a malformed body is usually transient — but this one is not, it is how AV's free
tier refuses this function. So the call is re-sent **for every ticker, on every run**: up
to 24 requests per day spent on a call that cannot succeed, ahead of the leg that would
actually benefit.

It did not show up in the 2026-09-02 budget file only because the now-dropped historical
put/call path exhausted the key first (24 `historical_put_call_ratio` + 1 `symbol_search`).
**With that path gone, `earnings` becomes the primary AV consumer on the next live run.**
That is a concrete, falsifiable prediction: check
`data/provider_budget/alpha_vantage/<date>.json` after N1 and expect
`earnings_calendar` near 24.

**Action:** `earnings: [fmp, alpha_vantage]`. FMP's earnings calendar is reached and
validated (`SOURCE_STATUS.md`, FMP core row). Risk: none — it only reorders a fallback.

**Implemented 2026-09-03.** The N1 live run spent zero AV requests on per-ticker
earnings. After the live run plus `preflight --deep`, the AV budget file showed
`earnings_calendar: 1`, which came from the deep probe, not from the 23 live earnings
calendar calls.

**Open sub-question:** should a repeatable `malformed` on a known endpoint be retirable at
all? Widening `ENTITLEMENT_STATUSES` is wrong (it would retire genuinely transient
failures), but a per-run "this endpoint already refused, do not re-ask for 23 more tickers"
memo would have capped this at 1 request instead of 24. Worth a ticket either way, since
the same shape will recur with any provider whose refusal is not an entitlement status.

---

## 2. The news question, with the numbers corrected and re-measured

The original Q6 framing compared Finnhub on NVDA with Alpha Vantage on AAPL and left AV
at its default 50-row limit. N4b closed both caveats on 2026-09-03: same ticker, same run
date, and AV `limit=1000`.

| | Finnhub + local lexicon | AV `NEWS_SENTIMENT` |
|---|---|---|
| Probe | NVDA, `2026-09-03`, 7-day company-news window | NVDA, `2026-09-03`, `limit=1000` |
| Articles returned | **250** | **1000** |
| Scored | 111 (44.4%) | 1000 (100%) |
| **Net scored articles** | **111** | **1000** |
| Scoring | local lexicon, AV's scale and bands | vendor |
| Per-ticker relevance | none | yes, `relevance_score` + `ticker_sentiment_score` |
| Mean score | +0.1131 | +0.1885 |
| AV requests/day if universal first | 0 | **up to 24** |

The raised-limit probe reverses the earlier article-count argument. AV is better on both
net scored article count and scoring quality for the probed ticker. The budget constraint
still rules out universal AV-first: it would spend essentially the entire free daily
allowance before other AV fallbacks can fire.

So the choice is not A versus B. It is A versus C: keep AV unused except fallback, or spend
it on a small decision shortlist.

Decision: **C - hybrid shortlist.**

Implementation is an explicit config shortlist, not a dynamic two-pass classifier. Phase C
in `provider-alternatives-wiring-tasks.md` is the policy anchor for refreshing it: build the
failure list from preflight plus one live run, append required endpoint failures, live
`n/a` or silent sub-score gaps, and adopted-source regressions to
`docs/alternatives/still-failing.md`, then wire any adoption through the Phase B contracts.
The pipeline still fetches news before scoring and setup evaluation, so "tradeable and
near-tradeable from this same run" cannot be known at news-fetch time without a larger
two-pass design. The current config seeds the shortlist from N1's 2026-09-03 tradeable
names: `DE`, `ORCL`, `AVGO`, `PLTR`.

### Options

- **A — status quo.** `[finnhub, alpha_vantage, fmp]`. Costs no AV budget and keeps AV
  free for genuine fallbacks. Rejected for the current config because AV's raised-limit
  same-ticker result is materially better on scored article count and relevance.
- **B — AV first.** `[alpha_vantage, finnhub, fmp]`. Vendor scoring and relevance for every
  name, at the cost of the whole AV budget. Still rejected.
- **C — hybrid.** Finnhub for the universe; AV only for a shortlist (the tradeable and
  near-tradeable names). Keeps breadth, buys vendor scoring where a decision actually
  turns on it, and leaves most of the budget intact. **Selected and implemented** as
  `providers.news_alpha_vantage_shortlist`.

---

## 3. Legs where AV should *not* take the slot

| Leg | Current | Why not AV |
|---|---|---|
| `insider` | `[sec_edgar, alpha_vantage, fmp]` | EDGAR is the **primary record** and Form 4 is parsed from the source XML. Routing round an aggregator downgrades source quality on the one component whose value is reading the original filing — the same objection as `pb1-13f-blocker.md`. Keep AV as the fallback it already is. |
| `institutional` | `[]` | AV answers with 6,479 holder rows, but `pb1-13f-blocker.md` rejects an aggregator for `S_F` on source-quality grounds, and the endpoint working does not touch that objection. Q4, not Q6. |
| `prices` | `[fmp, twelve_data, alpha_vantage]` | Already covered twice over; Twelve Data closed the six FMP-gated symbols. AV is correctly last. |
| `options` | `[cboe, alpha_vantage]` | CBOE carries it. The AV path costs **2** requests per ticker (`GLOBAL_QUOTE` + `REALTIME_OPTIONS`), so it is the most expensive fallback in the file — and `realtime_options` is in `premium_endpoints`, refused before the request on a free plan. Leave as an unreachable fallback; do not promote. |

Note that `quotes: [alpha_vantage]` reads like an AV-only leg but is not a standalone
spend — `fetch_global_quote` is called only inside `_pull_alpha_vantage_chain`, so it costs
nothing unless the AV options fallback fires.

---

## 4. Order of work

1. ✅ **`earnings: [fmp, alpha_vantage]`** — frees up to 24 requests/day, no risk.
2. ✅ **Run N1** — live run `daily-2026-09-03-fb78f201`; deep preflight
   `preflight-2026-09-03T131058.260942Z0000`.
3. ✅ **Raise the AV news `limit`** and re-probe Finnhub and AV on the same ticker.
4. ✅ **Choose A or C** — chose C, explicit shortlist.
5. ⏭ **Ticket the non-memoised repeatable refusal** (§1 sub-question).

Nothing in §3 changes.

---

## What was not verified

- A fully dynamic same-run C allocation would require a two-pass run, because
  setup/tradeability is known only after news has already been fetched and scored.
- The shortlist refresh policy is Phase C in `provider-alternatives-wiring-tasks.md`. The
  current config seed is still only the 2026-09-03 tradeable names.
- The repeatable non-entitlement refusal memo is still only a ticket idea.
