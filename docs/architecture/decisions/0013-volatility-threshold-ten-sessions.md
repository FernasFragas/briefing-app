# 0013 — Volatility baseline: lower the threshold from 20 sessions to 10 — closes D12

| | |
|---|---|
| **Status** | Accepted. Closes 0012 and supersedes 0003. |
| **Date** | 2026-09-08 |
| **Round** | 3 |
| **Original identifier** | `D13` — cited by that name throughout the task documents |

---

**D12 is hereby closed. The answer is not to pay and not to backfill in bulk.**
`SELF_BUILT_SERIES_MIN_SESSIONS` drops from 20 to 10, and a percentile computed on fewer
than 20 sessions is published as **provisional** rather than as a settled reading.

Three legs are gated by this one constant (`pipeline.py:2762-2775`), not one:
`iv_rank`, `put/call volume percentile`, `put/call open-interest percentile`.

**What this buys, in real numbers.** The store holds 3 sessions. At 20 the first
percentile appears after **17 more weekday runs** — about three and a half calendar weeks,
and only if not one day is missed. At 10 it appears after **7 more weekday runs**, roughly
a week and a half. Nothing is paid and nothing is spliced: every session in the window
comes from the same vendor (CBOE) captured the same way, so the percentile compares like
with like and is correct by construction.

**The cost the owner accepted, which Lane K must manage rather than hide.** A percentile
over 10 observations resolves only to the nearest tenth: "IV rank 80" means "second highest
of ten" and nothing finer. Ten sessions is about two calendar weeks of market history and
may not span a single volatility regime. **A provisional reading must therefore be visibly
provisional** — in the stored row, in `dashboard.json` and on the page. Publishing a
10-session percentile with the same authority as a 20-session one would convert an accepted
trade-off into a silent misrepresentation, which is the failure mode this project has now
corrected twice.

**Rejected, and why each:**
- *Buy one month of Alpha Vantage premium ($49.99), backfill 344 pairs, cancel.* This was
  Lane I's written recommendation and it is declined. Real money for a personal tool, and
  round 2 established that it does not straightforwardly work anyway: the backfilled rows
  are Alpha Vantage session-close chains while every stored row and every future run is a
  CBOE intraday chain, so the money buys a series that D14 then has to rule on.
- *Wait for 20 at the current rate.* Correct but slow: 17 more runs with 0.35 of the
  options component inert throughout.
- *Drop the three legs permanently and redistribute their weight.* Rejected: unlike
  `executive_tone` and `S_F`, this data is not unsourceable — it arrives free every day and
  merely has not accumulated yet. Declaring it permanently unavailable would discard a
  genuinely tradeable signal to avoid a nine-day wait.
