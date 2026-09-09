# PA6 - Political Flow And Retail Momentum

Research date: 2026-08-31. Both legs of S_S that have never had a source.

**Two adopt verdicts, and neither one is Quiver.** Rule 2 paid off on both halves: the
political leg is served by a provider already keyed, and the retail leg by a keyless API.

## PA6(a) - Political flow: adopt FMP, not Quiver

**Probed on the existing FMP free key, 2026-08-31:**

| Endpoint | Result |
|---|---|
| `senate-latest` | **HTTP 200**, 100 rows |
| `house-latest` | **HTTP 200**, 100 rows |
| `senate-trades?symbol=AAPL` | HTTP 402 `Restricted Endpoint` |
| `house-trades?symbol=AAPL` | HTTP 402 `Restricted Endpoint` |

The **unfiltered** feeds are entitled; only the per-symbol variants are gated. A sample row
carries everything T13 asks for:

```json
{"symbol": "GS", "senateID": "M001243", "disclosureDate": "2026-08-27",
 "transactionDate": "2026-07-28", "firstName": "Dave", "lastName": "McCormick",
 "office": "Dave McCormick", "district": "PA", "owner": "Spouse",
 "assetType": "Corporate Bond", "type": "Purchase",
 "amount": "$100,001 - $250,000",
 "link": "https://efdsearch.senate.gov/search/view/ptr/..."}
```

Note `link` points at the **original Senate eFD disclosure**, so the aggregator is backed by
the primary record — which is exactly the source-quality condition T13 sets for treating this
as better than a bare aggregator feed.

**Free-tier shape, measured not assumed:**

- `limit` is capped at 25 (`Premium Query Parameter: ... must be between 0 and 25`), and
  `page` is gated entirely. **No pagination.**
- With **no parameters at all**, the endpoint returns **100 rows** — more than the explicit
  limit permits. A quirk, but a stable and useful one.
- Observed transaction dates span 2024-03-12 to 2026-08-19: a rolling window over the most
  recent disclosures across all of Congress.

**Consequences for wiring (PB6):**

1. **Two requests per run, not per ticker.** Fetch both feeds once, filter locally against
   the universe. That is far cheaper than the per-symbol design T13 assumed.
2. **Coverage per ticker is sparse.** 100 rows across all of Congress will often contain
   nothing for a given name. The leg must report `n/a` for the ordinary case, not zero.
3. **Persist each run's rows.** The same self-built pattern as PA2(a)/PA7: accumulating the
   rolling window is the only way to build per-ticker depth, since pagination is gated.
4. **Disclosure lag is real** — the sample shows a 30-day gap between transaction and
   disclosure, and the STOCK Act permits up to 45 against a ~14-day horizon. Cap the
   sub-score and label it context, not edge, exactly as T13 requires.

**Quiver: reject for this leg.** It is live and key-gated (verified 2026-08-31, HTTP 401 with
a clean JSON error), but it would cost a new credential and a new vendor dependency to obtain
data an already-keyed provider serves. Rule 2 is explicit about that trade. Quiver also
remains the single-point-of-failure risk the task itself flagged.

**Alpha Vantage `CONGRESS_TRADES`: reject for this leg.** Even after the 2026-09-02 reset
probe showed AV is not dead, adding another optional leg to the 25/day bucket recreates the
failure mode PA3 documented. FMP already serves the congressional feed on the existing key.

## PA6(b) - Retail momentum: adopt ApeWisdom

**Probed 2026-08-31, keyless:**

```
GET https://apewisdom.io/api/v1.0/filter/all-stocks/page/1   -> HTTP 200, 664 stocks
GET https://apewisdom.io/api/v1.0/filter/wallstreetbets/page/1 -> HTTP 200, 521 stocks
{"rank": 1, "ticker": "SPY", "mentions": 254, "upvotes": 679,
 "rank_24h_ago": 1, "mentions_24h_ago": 56}
```

| Candidate | Free-tier | Entitlement | Verdict |
|---|---|---|---|
| **ApeWisdom** | **Keyless, no signup, no quota published** | Mention counts and upvotes, plus `rank_24h_ago` / `mentions_24h_ago` | **Adopt** |
| Stocktwits | — | **API frozen to new developers** | **Reject** — cannot be onboarded |
| Quiver WSB dataset | Paid key | Would serve both legs | Reject — see above |
| Reddit API direct | Free tier exists | Raw posts; needs its own scoring and moderation handling | Reject — more operational surface than the leg is worth at weight 0.20 |

**Why ApeWisdom fits the leg specifically:** `retail_momentum` needs *momentum*, not level,
and the API ships `mentions_24h_ago` alongside `mentions`. The delta is directly computable
rather than requiring a self-built series first — the one leg here that works on day one.

**Label it honestly.** These are mention counts, not sentiment: the API returns no bullish/
bearish score. The leg measures *attention*, and the evidence row must say so. Retail signal
is also noisy and gameable, which is decision **A7** (cap below its nominal 0.20) — still open
and still the user's call.

**Licensing:** ApeWisdom publishes a public keyless API without documented redistribution
terms. Fine for self-hosted personal use; **flag before any output is published**.

## Evidence

- FMP probes: `scratchpad/fmp_probe.py`, run 2026-08-31 against the key in `.env`.
- ApeWisdom: `curl` 2026-08-31, both endpoints HTTP 200 with parsed row counts above.
- Quiver 401: recorded in the task file from the 2026-08-31 check.

Sources: [ApeWisdom API](https://apewisdom.io/api/), [Best Stock Sentiment APIs 2026](https://adanos.org/insights/blog/best-stock-sentiment-apis-2026/)
