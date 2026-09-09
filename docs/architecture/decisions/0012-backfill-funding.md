# 0012 — Backfill funding: OPEN, deferred pending research

| | |
|---|---|
| **Status** | **Closed by [0013](0013-volatility-threshold-ten-sessions.md).** Left deliberately open pending research; the research is at [`historical-options-sources.md`](../../research/alternatives/historical-options-sources.md) and its recommendation to buy one paid month was read and declined. |
| **Date** | 2026-09-07 |
| **Round** | 2 |
| **Original identifier** | `D12` — cited by that name throughout the task documents |

---

**No option was chosen.** The owner declined to pick between paying for an Alpha Vantage
premium plan, waiting 14 days on the free allowance, or backfilling a reduced set of names,
and instead asked for **a research task to find free alternatives that can supply this
data, explicitly including a check of `https://api.quiverquant.com`.**

Measured position, straight from the tool's own dry run
(`briefing-app.cli backfill-iv --dry-run`, 2026-09-07):

```
requested_pairs:              360     (18 tickers x 20 sessions)
already_stored:                16
remaining:                    344
estimated_days_at_allowance:   14     (Alpha Vantage free tier, 25 requests/day)
```

**Lane I performs the research and reports. Lane J does not execute a full backfill until
this decision is closed.** Lane J may — and should — run the correctness reproduction test
first, because that costs a handful of requests and gates everything else regardless of
which source wins.

---

# Round 3 — decisions of 2026-09-08 (owner, against measured store state)

Taken after round 2 closed. The evidence base is the live SQLite store
(`data/briefing.sqlite3`), read directly at the time of the decision:

```
daily_snapshot rows:              59
distinct sessions stored:          3     (2026-09-03, 2026-09-06, 2026-09-07)
rows with iv_atm populated:       51
rows with iv_rank populated:       0
SELF_BUILT_SERIES_MIN_SESSIONS:   20     (pipeline.py:215)
```

Same rule as rounds 1 and 2: **read-only once work starts.** A lane that believes one of
these is wrong records the objection in `CROSS-LANE.md`; it does not act against it.
