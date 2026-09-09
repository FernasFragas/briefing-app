# PA8 - Analyst Signals Second Feed (S_S institutional leg, weight 0.45)

Research date: 2026-08-31.

**Verdict: adopt Finnhub as the second feed, with a stated limitation — it cannot cover the
EU names, so this closes the sole-provider risk for US names only.**

> **Implemented 2026-09-01 (ticket I11).** `analyst: [fmp, finnhub]`. Two things this note
> left open were settled by the live probe: recommendation trends **are** entitled (HTTP
> 200, 4 monthly rows), and price targets are **not** (403), so target consensus stays
> sole-sourced on FMP. Finnhub is a fallback rather than a merge — both report the same
> buy/hold/sell counts, so running both would double-weight one quarter's consensus.
> Outcome: `docs/research/alternatives/pb3-finnhub-news-and-analyst.md`.

## Premise check: holds, and it is the sharpest single-point-of-failure in the report

| Claim | Verified | Finding |
|---|---|---|
| Analyst signals come only from FMP | ✅ | `providers.analyst` is `[fmp]` — a one-element chain, no fallback in code. |
| It is the only S_S leg that scores at all | ✅ | `executive_tone` and `retail_momentum` are both in `LIVE_UNSCORABLE_LEGS`. **S_S currently rests entirely on this one provider's two endpoints.** |
| FMP already gates elsewhere | ✅ | Five endpoints answer 402 `Restricted Endpoint`, and the symbol gate hits six universe names (PA4). |

So a single FMP entitlement change takes out 100% of S_S, not 45% of it. That is a materially
worse exposure than the coverage matrix's "sole provider" label conveys, and it is why this
task should not sit below the failing-source tasks.

## Candidates

| Candidate | Free-tier | Analyst entitlement | Symbol coverage | Verdict |
|---|---|---|---|---|
| **Finnhub** | 60 req/min | Recommendation trends and price targets documented on the free tier | **US-only on free** | **Adopt for US** |
| Tiingo | 1,000 req/day, 500 symbols/month | No first-party analyst consensus product | US-centric | Reject — wrong product |
| Twelve Data | 800 req/day | Analyst estimates exist; free-tier entitlement unverified | 90+ exchanges | Monitor — the only candidate that could also cover EU, worth probing at the PA4 signup since it is the same key |

## The limitation, stated rather than buried

The task says to *"rank on symbol coverage first — an alternative that shares FMP's gated-
symbol problem is not redundancy."* Finnhub does not share FMP's *specific* gated list, but it
has its own boundary: **free tier is US-only.**

So adopting Finnhub gives S_S genuine redundancy for the US names, and **none at all** for
RHM.DE and LDO.MI. Those two remain single-sourced on FMP — which currently 402s both of them
anyway, so in practice their analyst leg is already `n/a` and this changes nothing for them.

That is an honest partial close, not a full one. The matrix row should read "second feed for
US names; EU still sole-sourced" rather than being marked closed.

## Why not just accept FMP

Because the 2026-08-31 audit is the argument the whole document rests on: Alpha Vantage went
from metered to spent in one day and took four legs with it, because every documented
fallback was either the same metered key or a gated endpoint. FMP answering today is not
evidence it will answer tomorrow, and this leg carries an entire component.

## Adopt specification

- Base: `https://finnhub.io/api/v1`
- Endpoints: `/stock/recommendation?symbol={t}`, `/stock/price-target?symbol={t}`
- Credential: `FINNHUB_API_KEY` — **the same key PA3 already requires**, so this costs a
  registry entry and a normalizer, not a new vendor relationship. That is rule 2 working.
- Chain becomes `analyst: [fmp, finnhub]`. FMP stays first: `grades-consensus` returns actual
  buy/hold/sell counts, which is what S_S wants, and it is entitled today.
- Source-quality label stays **aggregator** either way — neither is the primary record.

## Note carried from SOURCE_STATUS

FMP analyst ratings must read `grades-consensus`, not `ratings-snapshot`; the latter returns a
vendor scoring model rather than analyst counts. Any Finnhub normalizer must map to the same
buy/hold/sell shape, not to a vendor score, or the two feeds will not be comparable.

## Evidence

- `providers.analyst` single-element chain: `config/config.example.yaml`, verified 2026-08-31.
- FMP `analyst-estimates` entitled on the free key: probed 2026-08-31, HTTP 200, 5 rows.
- Finnhub free-tier terms: sources below. Endpoint-level entitlement for recommendation trends
  is **documented but not key-verified**; probe at signup.

Sources: [Finnhub rate limits](https://finnhub.io/docs/api/rate-limit), [Finnhub API 2026 overview](https://www.freeapisforyou.in/api/finnhub), [Best Financial Data APIs 2026](https://www.nb-data.com/p/best-financial-data-apis-in-2026)
