# PA10 - Executive Tone (S_S leg, weight 0.35)

Research date: 2026-08-31.

**Verdict: reject as a standalone vendor task. Fold the one viable candidate into the Finnhub
signup PA3 already requires, and if that fails, close the leg through PC3 with a weight
decision.** The task predicted a reject; the probes largely confirm it, with one opening.

## Premise check

Holds exactly as filed. `sentiment.py` states the reason in code: earnings-call transcripts
are not fetched by this stack. `executive_tone` is in `LIVE_UNSCORABLE_LEGS` with
"no transcript source is wired into LiveDataSource", and the live
`build_sentiment_component` call never passes it. **S_S has been scoring on one of its three
channels since it was written**, and this is the larger of the two missing channels.

## Rule 2 first: the already-keyed provider

**Probed on the existing FMP free key, 2026-08-31 — all refused:**

| Endpoint | Result |
|---|---|
| `earning-call-transcript?symbol=AAPL&year=2026&quarter=2` | HTTP 402 `Restricted Endpoint` |
| `earning-call-transcript-latest?limit=1` | HTTP 402 `Restricted Endpoint` |
| `earnings-call-transcript-list?symbol=AAPL` | HTTP 404 |

`Restricted Endpoint` is the **endpoint** gate in this API's taxonomy (per
`docs/SOURCE_STATUS.md`), so falling back is correct and no amount of parameter fiddling
opens it. FMP transcripts are out on the free plan.

Alpha Vantage `EARNINGS_CALL_TRANSCRIPT` is not adopted: it would sit inside the same
25/day bucket, and executive tone remains a PC3 weight/source decision rather than a reason
to spend scarce AV quota.

## Candidates

| Candidate | Free-tier | Entitlement | Licensing | Verdict |
|---|---|---|---|---|
| **Finnhub transcripts** | Free tier is 60 req/min, **US-only**; transcript endpoint's tier **not verified without a key** | Documented transcript API; some sources describe transcripts as free-tier "alternative data", which is not proof | Standard API terms | **Monitor — test at Finnhub signup.** Costs nothing extra: PA3 already adopted Finnhub, so this is one probe, not a new vendor |
| EarningsCall.dev | Free browser reading; "low-cost" REST API | Speaker segments, full-text search | Unverified | Monitor — a paid API is a paid API, however cheap |
| API Ninjas | Freemium | 8,000+ companies, history from 2005 | Unverified | Monitor |
| Apify earnings-call scraper | Metered credits | Scraper, not a first-party feed | Scraping terms | **Reject** — an anti-bot/ToS surface, the class PA3 already rejected for RSS |
| Seeking Alpha / Koyfin / MarketBeat | Free to read | No API; Koyfin free plan is 45-day history in-app | Redistribution restricted | **Reject** — human-readable, not machine-readable |

## The larger problem: retrieval is only half the leg

Even a free transcript feed does not score `executive_tone`. The leg needs **tone extraction**
on top of retrieval — a model pass over the transcript producing a bounded score — which is
new machinery this stack does not have, and which sits awkwardly against the project's own
rule that the LLM never produces numbers. That constraint is why the honest verdict is reject
rather than "adopt pending a feed": the feed is the cheap half.

## Recommendation

1. **At Finnhub signup (I6), probe the transcript endpoint.** One request settles it. If it is
   free-tier entitled, PA10 reopens as a retrieval + scoring design question.
2. **If it is gated, close through PC3**: record `executive_tone` permanently `n/a` in
   `docs/SOURCE_STATUS.md`, make it degrade with a named reason rather than renormalizing
   silently, and put its **0.35 weight up for redistribution** — decisions **A3** and **A4**,
   both still open and both the user's to make.

Leaving a third of a component structurally absent while the score reads as complete is the
exact dishonesty this whole document exists to remove.

## Evidence

- FMP transcript probes: `scratchpad/fmp_probe.py`, run 2026-08-31 against the key in `.env`.
- Finnhub free-tier shape (60 req/min, US-only, 1 year history per request): search results
  below; the transcript endpoint's own tier remains **unverified** and is not claimed here.

Sources: [Finnhub transcripts API](https://finnhub.io/docs/api/earnings-call-transcripts-api), [Finnhub rate limits](https://finnhub.io/docs/api/rate-limit), [EarningsCalls.dev](https://earningscalls.dev/), [API Ninjas transcripts](https://api-ninjas.com/api/earningscalltranscript)
