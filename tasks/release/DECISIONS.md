# Decision record — 2026-09-07

Eight product decisions, taken by the owner on 2026-09-07 against measured evidence from
live run `daily-2026-09-06-e270378b`. **Read-only once work starts.** A lane that believes
a decision is wrong records the objection in `CROSS-LANE.md`; it does not act against it.

---

## D1 — Ship target: **local, single reader**

The application runs on the owner's own machine, for the owner alone.

**Consequences that bind the lanes:**
- No public hosting workstream. No managed database, no object storage, no cloud scheduler.
- The unauthenticated HTTP endpoints are **still fixed** (Lane E), because the failure is
  fail-open by design and would become a live quota-drain the moment the app is ever
  exposed. It is a small fix; leaving a known fail-open default in place is not.
- Scheduling is local (`launchd`), which introduces its own failure mode: the run is
  skipped whenever the machine is asleep. Lane E must make a skipped run **visible**,
  because a silently missed day stalls the volatility baseline in D3.
- The bounded LLM prose layer is low value for one reader who can read the numbers. See
  Lane E task E4 for the recommended disposition.

## D2 — Grading scale: **ALIGN — drop the probability term entirely**

The grade becomes conviction alone: `100 x alignment`, for both the directional and the
neutral branch. The thesis probability is still computed and still **printed** beside the
grade as context; it is no longer an input to the score.

**The evidence this was taken on** (all 18 rows of the 2026-09-06 run; the recomputation
reproduced 18 of 18 published grades exactly before any variant was projected):

| Scale | directional range | neutral range | gap at the top |
|---|---|---|---|
| Today | 11.5 – 81.0 | **39.8** – 75.6 | +5.4 |
| N7 as filed | 5.1 – 81.0 | **39.8** – 75.6 | +5.4 |
| N8 as filed | 5.1 – 81.0 | 0.0 – 37.3 | **+43.7** |
| N8b (N8 + rebalanced neutral weights) | 5.1 – 81.0 | 0.0 – 68.4 | +12.6 |
| **ALIGN (chosen)** | 5.1 – 81.0 | 0.0 – 81.0 | **+0.0** |

Two findings drove it, neither recorded in `HANDOFF.md` before 2026-09-07:

- **`P` is inert for directional rows.** Across every directional row it spans
  0.453–0.504 — a flat ~10-point bonus that distinguishes nothing.
- **`P` is a tautology for neutral rows.** JPM's own composite signal is 0.208, *past* the
  0.15 neutral band, so its alignment is 0.000 — its signal contradicts its stated thesis.
  It still scored 41.0 (`D`), because `0.60 x 0.683 = 41` points are paid for the
  definition of the band. AMZN is identical. Under ALIGN both correctly score 0.0.
- **N8 as filed inverts the asymmetry rather than removing it.** It strips 41 points from
  neutral rows while leaving their alignment weight at 0.40, so neutral tops out at 37.3
  against directional's 81.0. This is not mentioned in the N8 write-up and is why N8 was
  not chosen.

**This supersedes `HANDOFF.md` N6, N7 and N8.** N6 stays closed. N7 and N8 are **withdrawn,
not deferred**: ALIGN subsumes N7 (the directional probability weight becomes irrelevant
when there is no probability term) and replaces N8's remedy with a simpler one.

## D3 — Volatility warm-up: **backfill from historical option chains**

Replay past option chains into `daily_snapshot` so the 20-session baseline already exists,
rather than waiting ~4 weeks of trading days for it to accumulate.

- `AlphaVantageClient.fetch_historical_options(ticker, option_date=...)` already exists
  (`providers/alpha_vantage.py:169`) and is registered (`config/source_registry.yaml:173`).
  This is wiring, not a new integration.
- **Cost:** ~360 requests for 18 tickers x 20 sessions. The free plan allows 25/day, so on
  the free plan the backfill itself takes ~15 days. A premium plan makes it minutes. The
  owner has not committed to a paid plan; Lane C must therefore make the backfill
  **resumable across days** and report its own progress.
- **The correctness trap, and it is the whole task:** a backfilled implied-volatility
  reading must be computed by *exactly* the same code path as a live one. If it is not,
  the percentile compares two different quantities and produces a confident, wrong answer.
  Lane C's acceptance criteria are built around proving this.

## D4 — Catalysts: **inferred dates may score, but may not anchor an event trade**

A catalyst date inferred from a company's historical reporting cadence is good enough to
justify scoring and ranking a name, and **not** good enough to structure a trade whose
payoff depends on the event landing before expiry.

- Today the rule is all-or-nothing and rejects outright. On 2026-09-06 it rejected INTC,
  which graded B+ at 76.6 and ranks joint-first under the chosen ALIGN scale.
- 8 of 26 gated names ran on inferred dates.
- The gate already records the distinction: `flags: ["estimated_catalyst_only"]`.
- Lane D must write down which setup types genuinely depend on the date. That list is a
  judgement call and belongs in `docs/GATE-POLICY.md`, not buried in a condition.

## D5 — Score ceiling: **re-cut the grade letters against the reachable range**

No row can currently reach the top confidence tier, because the sentiment component is
`aggregator` quality by construction, so every score is clamped at 81 and the top fifth of
the scale is dead. Under ALIGN three of the best rows tie at exactly 81.0.

**Explicitly rejected:** relabelling the sentiment component's source quality to unlock
Tier A. Adjusting a data-quality label to obtain better-looking grades is the change
`HANDOFF.md` warns against most directly, and it makes every future inconvenient label
negotiable.

> ### Refinement found while planning — Lane A must confirm or reject it
>
> The obvious reading of D5 — rescale the letter bands by 0.81 — **is wrong, and breaks the
> tier system.** Measured on the real rows: three Tier B rows would read `A+` and the
> Tier C row SPY would read `B`. That is precisely what the ceiling exists to prevent.
>
> The mechanism that satisfies D5's intent is different: **make the tier cap the displayed
> letter rather than clamp the score.** The score then keeps its full resolution for
> ranking — ORCL 93.1, AMAT 84.5, INTC 83.6 instead of three rows tied at 81.0 — while a
> Tier B row still cannot *display* above `B+` and a Tier C row still cannot display above
> `C`. Under it the existing letter bands may need no re-cut at all.
>
> One consequence to check: the score column and the letter column can then disagree on
> ordering (a Tier C row scoring 79.0 displays `C` while a Tier B row scoring 64.6 displays
> `B+`). After D6 removes SPY and QQQ from the table, every remaining row on the last run
> is Tier B and shares one cap, so the conflict does not arise today — but Lane A must
> decide what happens when it does.
>
> **Lane A owns this call.** Implement it, or reject it in writing in `CROSS-LANE.md`.

## D6 — Index funds: **move SPY and QQQ to market context**

They stop appearing as trading ideas and appear instead in the market overview as a read on
market conditions.

- An index has no issuer, so it can have no analyst coverage and no insider filings, fails
  a required-component check, and is floored at the bottom tier permanently. It occupies a
  row that can never produce a trade. Nobody chose this; it emerged from rules combining.
- The market overview currently holds a **single** line ("SPY implied weekly move"), so it
  needs the content.
- **Explicitly rejected:** exempting indexes from the components they cannot have. It would
  make them tradeable but graded on two components against four for every other row, in the
  same column, which quietly breaks comparability.

## D7 — Universe: **mark the European names inactive; fix the duplicates**

- `RHM.DE`, `LDO.MI`, `ASML.AS` and `SIE.DE` are rejected every run with
  `eu_options_unavailable`. No free source covers European options and that work is
  deferred indefinitely (`docs/alternatives/pa5-eu-sources.md`, `pb5-fca-deferred.md`).
- They stay in the configuration behind an explicit `inactive` flag, so the intent to cover
  Europe survives in the file, and the gate skips them **without emitting a rejection**.
- `RHM.DE` and `NVDA` are each listed twice. That is a straightforward mistake.
- The universe is otherwise working as designed: 35 configured, 18 reaching the report, and
  the shortfall is the candidate gate correctly dropping names with no catalyst in the
  horizon window. **That is not a bug and no lane should "fix" it.**

## D8 — Agent arrangement: **one working tree, strict file ownership**

See `README.md` in this directory. The partition, the unowned files, and the escalation
path through `CROSS-LANE.md` are all binding.
