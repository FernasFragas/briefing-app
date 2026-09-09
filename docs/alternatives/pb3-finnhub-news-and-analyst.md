# PB3 — Finnhub wired: news leg sourced, analyst leg no longer sole-provider

Implemented 2026-09-01. Closes tickets **I6** (client), **I9** (news leg) and **I11**
(analyst second feed). Research verdicts: `pa3-news.md`, `pa8-analyst-signals.md`.

**Two outcomes, and they are not the same size.** The news leg went from *no working
source at all* to a live one. The analyst leg went from one provider to two — for US
names only.

---

## What was probed, and on which run

Both endpoints were probed with this project's key on **2026-09-01**, through the client
being shipped rather than through `curl`, so the evidence covers the URL construction,
the validator and the normalizers as well as the entitlement:

| Ticker | Endpoint | Result |
|---|---|---|
| NVDA | `company-news` | ✅ HTTP 200, **247 rows**, all normalized |
| NVDA | `stock/recommendation` | ✅ HTTP 200, **4 monthly rows**, all normalized |
| RHM.DE | both | ⛔ **refused before the request was sent** — see US-only, below |

This confirms the 2026-08-31 probes and adds what those could not: that the payloads
survive `validate_payload` and reach the models intact.

## The free tier does not score its own news — PA3 called this correctly

`/news-sentiment` is 403. `S_S` reads `NewsArticle.sentiment_score`, so an article feed
with an empty score field contributes exactly nothing. Tone is therefore derived locally
in `providers/news_tone.py`, and the batch names itself
`Finnhub company_news (local tone)` so the report never presents a lexicon read as a
vendor's scored feed.

Four rules keep the substitution honest:

1. **An unmatched headline scores `None`, never `0.0`.** `_mean_sentiment` skips `None`
   and averages `0.0`, so a neutral zero would quietly pull a real signal toward the
   middle. This is the same rule the components already apply to an unmeasured leg.
2. **The longest phrase wins and consumes its span.** "profit warning" is strongly
   bearish and contains "profit", which alone is mildly bullish.
3. **The headline outranks the summary.** Summary terms score at 0.4× and their total is
   capped at ±0.4, so a long body can shade a headline but never overrule it.
4. **The scale is Alpha Vantage's.** Same `[-1, 1]` range and same five label bands, so a
   run that falls back from Finnhub to Alpha Vantage mid-chain does not silently change
   what a given score means.

### What the probe changed about the lexicon

Scoring the 247 live NVDA headlines is what exposed the first version's real defect:
**headlines are written in the past tense.** "Stock Tumbled on Tuesday" matched nothing,
because the lexicon held `tumbles` and matches on exact word boundaries. That is the
quietest possible failure — it reads as a thin news day, not as a gap.

Adding the inflections took measured coverage from **47% to 50% of articles scored**
(117 → 124 of 247), with the distribution spread across all five bands and a mean of
`+0.03`. A regression test pins it.

**50% is the honest number, and it is a limitation, not a milestone.** Half the feed is
descriptive copy a lexicon cannot read. Those articles are excluded from the mean rather
than counted as neutral, so the leg reports on the half it can measure.

One further limitation the probe surfaced and the code does not fix: Finnhub tags sector
roundups to every symbol they mention, so a headline naming three companies falling
scores as bearish for a ticker that is merely one of the three. Deduplication and the
24h/7d averaging dilute it; nothing removes it.

## US-only: refused before the request, not after

Finnhub's free tier serves US listings only. `RHM.DE` and `LDO.MI` answer HTTP 403, and
that is a permanent boundary rather than an outage — so `FinnhubClient` refuses an
exchange-suffixed symbol **before spending a request**, and reports why.

Two details matter:

- **Only a suffix longer than one character counts as an exchange.** `BRK.B` is a US
  class share, and refusing it would be a false gate. A single-letter foreign suffix such
  as London's `.L` therefore costs one request and reports the provider's own refusal —
  guard what is proven, never guess.
- **The refusal is raised directly, never returned through `_response`.** That keeps it
  out of the plan-gate memo. The endpoint works; this symbol does not. Memoising it would
  retire `company_news` for every US name in the universe.

## Analyst: a second feed, not a merge

`analyst: [fmp, finnhub]`. FMP stays first — `grades-consensus` returns analyst counts
*and* a consensus price target, and Finnhub's price target is 403 on this tier, so target
consensus stays sole-sourced on FMP either way.

Finnhub answers only when FMP produced nothing. Running both and merging would
double-weight one quarter's consensus by counting the same analysts twice under two
labels, which is not redundancy — it is a heavier number that looks like more evidence.

`normalize_finnhub_recommendation_trends` maps to buy/hold/sell **counts**, matching
`normalize_fmp_grades_consensus`. Mapping to a vendor score instead would give the leg a
second feed whose numbers cannot be compared with the first. This is the note carried
from `SOURCE_STATUS.md` about `ratings-snapshot`, applied to the other provider.

Every dated monthly row is kept rather than only the newest: the rows are monthly, the
component ages them itself, and consecutive months are what make a rating *change*
visible — the signal the level alone does not carry.

**The honest scope.** PA8's premise was that a single FMP entitlement change takes out
100% of `S_S`, not 45% of it. After this, that is true for US names only. `RHM.DE` and
`LDO.MI` remain sole-sourced on FMP, which already 402s both — so in practice their
analyst leg was `n/a` before and is `n/a` now. The matrix row reads "second feed for US
names; EU still sole-sourced", not "closed".

## Rate limit, not a daily allowance

60 requests/minute, a separate 30/second ceiling in the terms, and **no published daily
cap** — which is the entire point of the source, since Alpha Vantage's 25/day could not
serve a multi-ticker run at all. The budget policy therefore paces at 1.05s and declares
`daily_requests=None` rather than inventing a number the provider never stated.

`premium_endpoints` records `news_sentiment`, `price_target` and `transcripts`. No fetch
method targets them; the set is what refuses one before a request if a method is ever
added, and what makes preflight report them as plan-gated rather than untried.

## Not closed by this

- **`executive_tone`** — Finnhub transcripts are 403 (PA10). Still in
  `LIVE_UNSCORABLE_LEGS`, still Q1 in the handoff.
- **Price targets** — FMP only.
- **EU analyst and EU news** — no free source. PA5 remains a structural reject.
