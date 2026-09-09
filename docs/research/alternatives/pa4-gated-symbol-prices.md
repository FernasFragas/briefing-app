# PA4 - Price History And Fundamentals For FMP-Gated Symbols

Research date: 2026-08-31.

**Verdict: adopt Twelve Data for the US gated-symbol price-history gap.** The original
verdict was conditional on a coverage probe; that probe is now recorded in `HANDOFF.md`
and the wiring landed on 2026-09-02. The gated-symbol list is larger than the task
recorded, and the reason matters.

## Implementation update — 2026-09-02

Twelve Data is wired into `prices: [fmp, twelve_data, alpha_vantage]`:

- `providers/twelve_data.py` calls `/time_series` with `interval=1day`,
  `start_date`, and `end_date`.
- `normalize_twelve_data_time_series` maps the response to the existing `PriceBar` model,
  oldest-first.
- `config/source_registry.yaml` probes `twelve_data.time_series` against AVGO, one of the
  symbols FMP gates on the free plan.
- `RequestBudget` uses 800 requests/day and 7.6s pacing for the Basic plan's 8
  credits/minute limit.

This closes AVGO, ORCL, MU, QQQ, CRWV and AMAT. RHM.DE and LDO.MI remain a separate A2
decision because Twelve Data returned the paid-plan message for both.

## Premise check: holds, and the list has grown

The task names four gated symbols (AVGO, ORCL, MU, QQQ). Probing during the universe work on
2026-08-31 found **two more**, and the same gate hits the new EU names:

| Symbol | FMP `stable/quote` | Note |
|---|---|---|
| INTC | **200** ($89.47, NASDAQ) | Covered |
| CRWV | **402** symbol gate | Newly added to the universe |
| AMAT | **402** symbol gate | Newly added to the universe |
| RHM.DE | **402** symbol gate | EU |
| LDO.MI | **402** symbol gate | EU |

The refusal body is `Premium Query Parameter: 'Special Endpoint : This value set for 'symbol'
is not available under your current subscription` — the **symbol** gate, not the endpoint
gate, so the endpoint keeps working for other names. That classification already exists in
`provider_validation.py` and must not be memoised as an endpoint-level gate.

**Resolved for the US six on 2026-09-02.** The fallback chain is now
`providers.prices: [fmp, twelve_data, alpha_vantage]`. Before that,
`providers.prices` was `[fmp, alpha_vantage]`, and Alpha Vantage was refusing every
function. Six universe symbols had **no price source at all** — no realized volatility,
no measured sigma range, and therefore the universal Tier C floor. That was the whole
reason CRWV and AMAT could not rise above Tier C.

## Candidates

| Candidate | Free-tier limit | Coverage | History depth | Verdict |
|---|---|---|---|---|
| **Twelve Data** | 800 req/day | **US six verified; EU two paid-plan gated** | ~30 years | **Adopt for the US price-history gap** — AVGO, ORCL, MU, QQQ, CRWV and AMAT resolve; RHM.DE/LDO.MI do not on the free tier |
| Tiingo | 1,000 req/day; 500 symbols/month | US-centric | 30+ years | Monitor — higher daily limit, but the symbol-per-month cap and US focus miss the EU half |
| Finnhub | 60 req/min | **US-only on free**; other exchanges premium-gated | 1 year per request on free | Reject for this task — cannot cover RHM.DE or LDO.MI, and 1-year depth is thin for a 60-day realized-vol read |
| Alpaca | Free with account | US equities | Good | Monitor — US-only, same gap as Tiingo |

**Twelve Data wins on the one axis that matters here.** The task says to rank on symbol
coverage first, and coverage is exactly what splits these: Tiingo's higher request ceiling is
irrelevant if it cannot serve the two EU names, and Finnhub is explicitly US-only on free.

## Original conditional note — A1 is now settled for the US gap

At research time no key existed for either candidate, so coverage was vendor-claimed rather
than verified. Phase A acceptance forbade resting an adopt verdict on an unprobed
entitlement, so the original verdict was explicitly conditional:

> **I8's first step is a probe, not code.** Check Twelve Data *and* Tiingo free keys against
> the six gated names — AVGO, ORCL, MU, QQQ, CRWV, AMAT — plus RHM.DE and LDO.MI, and report
> per-symbol coverage before writing a client.

That is now the observed result: Twelve Data covers the US six but not the EU two. The US
half is adopted and wired; the EU names fall to **A2**: adopt something else, or drop them
from the universe with a documented decision. Given `eu_options_track: C` already caps both
at Tier C for lack of an options chain, dropping them costs less than it appears — but that
is the user's call, not a wiring default.

## Fundamentals half

The task also asks about estimates and the earnings calendar. Lower priority, and partly
already answered: FMP `analyst-estimates` is entitled on the free key (probed 2026-08-31,
HTTP 200, `period=annual`), and the earnings calendar works on FMP after AV's failure. Price
history is the load-bearing half, exactly as the task says.

## Licensing

Both candidates permit personal, non-redistributed use on free tiers. Neither requires
commercial redistribution rights. Flag if output ever leaves this machine.

## Evidence

- Per-symbol FMP probes: run 2026-08-31 with the key in `.env`, results in the table above
  and in `config/universe.example.yaml`'s added-names comment block.
- Free-tier limits: vendor comparisons below. **Not** verified against a live key.

Sources: [Tiingo best stock price API](https://www.tiingo.com/blog/best-stock-price-api/), [Best Financial Data APIs 2026](https://www.nb-data.com/p/best-financial-data-apis-in-2026), [Finnhub rate limits](https://finnhub.io/docs/api/rate-limit)
