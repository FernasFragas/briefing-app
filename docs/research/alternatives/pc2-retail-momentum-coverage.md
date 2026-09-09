# PC2 — `S_S.retail_momentum` coverage (PC1-LIVE-05)

Date: 2026-09-03. Ledger row: `PC1-LIVE-05` in `still-failing.md`.

**Verdict: no source adopted. The premise was wrong.** `retail_momentum` was not missing
for want of a provider; the pipeline was reading page 1 of a nine-page feed. Six of the
eight names were already in the data the app pays nothing for.

## The row as it stood

`S_S.retail_momentum` returned `no retail or social momentum reading supplied` for eight
of 23 scored tickers on live run `daily-2026-09-03-c7e82663`: COST, CRWV, DE, FDX, GM,
JPM, LMT, XOM. The same eight on the 2026-09-02 run. Read as a coverage gap — ApeWisdom
ranks Reddit attention, and large industrials are not what Reddit discusses — the
disposition was "search for a broader free retail/social feed".

## Premise check, and it fails

ApeWisdom's own response says how much of the feed the app is looking at:

```
GET https://apewisdom.io/api/v1.0/filter/all-stocks/page/1   → HTTP 200
{"count": 863, "pages": 9, "current_page": 1, "results": [ …100 rows… ]}
```

`ApeWisdomClient.fetch_all_stocks` takes a `page` argument that defaults to 1, and
`pipeline._retail_momentum_for_run` never passed one. So the app saw the top 100 of 863
tickers and recorded the other 763 as unsourced.

Fetching all nine pages the same day:

| Ticker | Page | mentions | 24h ago | rank |
|---|---:|---:|---:|---:|
| CRWV | 1 | 10 | 1 | 50 |
| COST | 2 | 1 | 2 | 184 |
| LMT | 2 | 1 | 2 | 190 |
| DE | 3 | 1 | 1 | 220 |
| JPM | 3 | 1 | 4 | 277 |
| XOM | 3 | 1 | 2 | 278 |
| FDX | — | absent | | |
| GM | — | absent | | |

Six of eight were in the feed. The fix is a loop.

## The second finding, which matters more than the first

**Five of those six carry one mention.** Wiring pagination alone would have closed the
`n/a` by scoring `1 mention against 2` as retail momentum — replacing an honest gap with
a fabricated measurement, on the leg the codebase already calls "the noisiest, most
gameable" one.

The existing floor of 10 in the momentum denominator damps the *magnitude* of a thin
read (1 against 2 scores −0.10, not −0.50) but cannot give it meaning. So pagination
ships with a mention floor: below `RETAIL_MIN_MENTIONS` on both sides of the comparison,
the leg is `n/a` and says so with the counts in the reason.

Net effect on the eight: **CRWV scores** (10 vs 1, comfortably above the floor); COST,
DE, JPM, LMT and XOM keep an `n/a` whose reason changes from "no reading supplied" to
"too thin to read: 1 mentions vs 2 24h ago, below the 5-mention floor"; FDX and GM keep
"no reading supplied" because they really are absent. **One row closed by data, five
closed by an honest reason, two still genuinely uncovered — and no vendor.**

## Candidates searched, in the documented cost order

### 1. An endpoint on an already-entitled provider — rejected, probed

**Finnhub `stock/social-sentiment`.** Reddit and Twitter mention counts with a bullish /
bearish split, which is strictly more than ApeWisdom returns, on a key this project
already holds. Probed 2026-09-03 against the live key:

```
GET /api/v1/stock/social-sentiment?symbol=COST  → HTTP 403 {"error":"You don't have access to this resource."}
GET /api/v1/stock/social-sentiment?symbol=XOM   → HTTP 403
GET /api/v1/stock/social-sentiment?symbol=JPM   → HTTP 403
```

Premium, consistent with the free tier's other 403s (`news-sentiment`,
`stock/price-target`, `stock/transcripts/list` — `pb3-finnhub-news-and-analyst.md`).
**Rejected: entitlement.** Re-open only if Finnhub's free tier changes, with a date.

### 2. A source of a different shape — rejected, anti-bot

**StockTwits `api/2/streams/symbol/<T>.json`.** A finance-specific social network, so
coverage of large caps is far better than a Reddit-derived feed, and historically a
public JSON API. Probed 2026-09-03 with the project user agent:

```
GET https://api.stocktwits.com/api/2/streams/symbol/COST.json  → HTTP 403
<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
```

Cloudflare interstitial for COST, XOM and LMT alike. **Rejected: anti-bot.** The PC2 rule
puts anti-bot rejections out of scope for re-litigation, so this one is closed rather than
queued.

### 3. Scored-sentiment vendors — not evaluated, and deliberately

A survey turned up free tiers at StockGeist (10,000 credits/month), Adanos (250
requests/month) and SentiSense (1,000 requests/month), all offering *scored* sentiment
rather than raw mentions. None was probed, because none addresses this row: the gap was
coverage, the coverage existed, and adopting a keyed vendor to replace a keyless feed
that already had the data would be a new credential, a new client and a new failure mode
bought for nothing. If the leg is ever upgraded from *attention* to *sentiment* — a
different task, and a real one, since the component's own docstring notes ApeWisdom
measures attention and not sentiment — this is where to start.

### 4. A paid tier — not specced

Not reached. A paid option is specced when a free one does not exist; here one did.

## What shipped

- `pipeline.RETAIL_MOMENTUM_PAGES = 9`, and `_retail_momentum_for_run` reads to the end
  of the feed, stopping early on the first page that answers nothing. Earlier pages rank
  higher, so an earlier row wins a duplicate. ApeWisdom is keyless and declares no daily
  allowance, so the extra pages cost no quota.
- `components/sentiment.RETAIL_MIN_MENTIONS = 5`, with an `n/a` reason carrying both
  counts and the floor.
- Tests: `tests/test_components_sentiment.py` (floor honoured, and a name at the floor
  still reads), `tests/test_orchestration.py` (the feed is read past page 1, and an empty
  page ends it rather than costing all nine requests).

## What was not verified

- Whether FDX and GM are permanently absent from ApeWisdom or absent on one day. One
  observation is not a pattern; if they are still missing after a week of runs, that is a
  coverage finding worth its own row.
- The mention floor of 5 is a judgement, not a measurement. It is set where a single post
  cannot move the leg and a genuine small-cap conversation still can. Worth revisiting
  once the paginated feed has produced a few runs of distribution to look at.

## Sources

- [Finnhub social sentiment API](https://finnhub.io/docs/api/social-sentiment)
- [ApeWisdom alternatives (2026), Adanos](https://adanos.org/insights/blog/apewisdom-alternatives-2026/)
- [Best stock sentiment APIs in 2026, Adanos](https://adanos.org/insights/blog/best-stock-sentiment-apis-2026/)
- [Sentiment & social APIs — StockTwits, Reddit, Twitter](https://articles.dailytickers.com/series/finance-apis/part3-sentiment/)
