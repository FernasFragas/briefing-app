# Follow-up prompts — from the 2026-09-09 ship audit

Two tasks the audit opened. **They are independent and can run in parallel** — Prompt A
touches only Lane M's files, Prompt B writes no source at all.

Both take the shared preamble from [`AGENT-PROMPTS.md`](AGENT-PROMPTS.md). Both are
**offline**: make no live provider requests.

---

## Prompt A — Correct the item 19 vendor-gap attribution

Fixes a wrong causal claim in a document that a future decision will be made against. Lane M
owns these files; this is a continuation of Lane M, not a new lane.

```text
[SHARED PREAMBLE FROM tasks/AGENT-PROMPTS.md]

YOUR TASK: correct the attribution of the measured put/call gaps in
docs/research/alternatives/vendor-consistency.md, and make the measurement reproducible.

You own exactly the Lane M file set:
  docs/research/alternatives/vendor-consistency.md
  ops/measure_vendor_gap.py
  tests/test_vendor_gap.py
  docs/operations/IV-BACKFILL.md
Do not write anything else. src/briefing_app/dashboard/grading.py stays locked.

=== WHAT IS WRONG, AND IT IS AN INTERPRETATION ERROR, NOT AN ARITHMETIC ONE ===

The document's M1 table reports three comparisons of CBOE-derived put/call ratios against a
MarketData.app chain, and presents the variation as evidence about TWO VENDORS:

  stored 2026-09-03 vs MarketData 2026-09-03 : volume  8.93%,  open interest   3.92%
  stored 2026-09-06 vs MarketData 2026-09-04 : volume  0.00%,  open interest   0.00%
  stored 2026-09-07 vs MarketData 2026-09-04 : volume 55.38%,  open interest 146.34%

The numbers are right. I verified the CBOE side reproduces exactly from the store. The
CONCLUSION drawn from them does not follow, for this reason:

  data/raw/cboe/delayed_options_chain/2026-09-06/AAPL.json  last_trade_time 2026-09-04T16:00:00, 3140 contracts
  data/raw/cboe/delayed_options_chain/2026-09-07/AAPL.json  last_trade_time 2026-09-04T16:00:00, 3260 contracts

Both stored rows are CBOE reads of THE SAME 2026-09-04 exchange session. They differ from
EACH OTHER by 146% on open interest. And this is not an AAPL quirk: every one of the 18
tickers captured on 2026-09-06 and on 2026-09-07 reports last_trade_time 2026-09-04.

So row 3 does not measure a disagreement between two vendors. It measures CBOE's own
delayed-chain capture of one session differing from itself when fetched a day later. Row 2
points the same way from the other side: when CBOE's capture is stable, the two vendors agree
to sixteen significant figures — which is itself better explained by shared upstream exchange
data than by independent agreement, and your document should say which it thinks it is.

=== WHAT TO DO ===

1. Rewrite the M1 interpretation so the causal claim matches the evidence. State plainly that
   rows 2 and 3 compare the same exchange session, that they disagree with each other, and
   that this is intra-CBOE capture variation rather than a vendor definitional gap.

2. Say what the evidence DOES establish about the vendor question, which is less than the
   document currently claims. Row 1 is the only comparison of two vendors on a session each
   captured on its own day: 8.93% and 3.92%. That is your actual vendor measurement, from a
   single ticker on a single day. Describe it with that much confidence and no more.

3. D14's conclusion does NOT change. The splice stays refused. Do not weaken it — if
   anything the evidence is now stronger, because a series that is unstable within one vendor
   cannot absorb a second one. Make the recommendation follow from the corrected reasoning
   rather than leaving a right answer attached to a wrong argument.

4. Make it reproducible. ops/measure_vendor_gap.py already accepts --payload to replay a
   saved MarketData.app JSON instead of fetching it. The audit could not replay anything
   because no payload was retained. Change the script so a fetched payload is SAVED by
   default, to a path the document names, and record in the document exactly which command
   plus which saved file reproduces each row. A measurement nobody can rerun is a claim.

5. Add a test to tests/test_vendor_gap.py that pins the corrected reading: given two chain
   payloads carrying the same last_trade_time, the tool reports them as the same session
   rather than as two independent observations. Make sure it can fail — write it, watch it
   fail against the current behaviour, then make it pass.

=== SCOPE BOUNDARY ===

You have found the edge of a bigger question: whether the volatility baseline should count
calendar snapshot dates or distinct exchange sessions. That is Prompt B and it is a decision
for the owner, not for you. Cross-reference it; do not implement it, do not change
option_metric_history, and do not touch pipeline.py.

=== BUDGET ===

Zero live requests, including MarketData.app. Everything you need is in the repository:
the store, data/raw/cboe/, and the existing document. If you conclude a fresh probe is
required, say so and stop.

=== WHEN YOU FINISH ===

Append a completion entry to tasks/CROSS-LANE.md stating what the corrected interpretation
is, what the vendor measurement now claims, and that D14 is unchanged.
```

---

## Prompt B — The session-counting decision brief

**Produces a decision, not a change.** The agent writes no source file. Output is a brief the
owner reads and answers, plus a draft decision record they can accept or reject.

```text
[SHARED PREAMBLE FROM tasks/AGENT-PROMPTS.md]

YOUR TASK: produce a DECISION BRIEF on how the volatility baseline should count sessions.
You are not implementing anything. Write no file under src/, tests/, ops/ or config/.

Deliverables, and only these:
  - docs/architecture/decisions/0017-session-counting.md  — a DRAFT record, marked
    "Status: PROPOSED — awaiting owner decision", laying out the options
  - a completion entry in tasks/CROSS-LANE.md

=== THE PROBLEM, WITH THE EVIDENCE THAT ESTABLISHES IT ===

The baseline counts stored snapshot dates. It does not count distinct exchange sessions, and
the two are not the same thing.

Verified 2026-09-09, all commands offline:

  - docs/architecture/VOLATILITY-BASELINE.md line 43 already SAYS this: "distinct exchange
    sessions: weekend and holiday runs can capture the same trading session." The limitation
    was documented. No code enforces it.
  - StorageRepository.option_metric_history selects on snap_date with no trading-day filter
    and no de-duplication.
  - is_market_day exists at pipeline.py:511 but is used ONLY at pipeline.py:628, to decide
    whether to run at all, and --force bypasses it.
  - In the current store, of three snapshot dates for the eighteen report tickers:
        2026-09-03 (Thu) : 21 tickers from session 09-03, 2 tickers from session 09-02
        2026-09-06 (Sun) : all 18 tickers from session 09-04
        2026-09-07 (Mon, holiday) : all 18 tickers from session 09-04
    So there are TWO distinct exchange sessions, and 09-04 is counted twice.

Note the detail on 2026-09-03 carefully, because it kills the obvious fix: two of
twenty-three tickers carried a STALE chain on a normal trading day. A calendar filter that
skips weekends and holidays would not have caught those. Any rule that works has to key on
each chain's own last_trade_time, per ticker, not on the run date.

=== WHY THIS MATTERS, STATED ONCE ===

The publication floor of ten is the headline of decision 0013. If duplicate reads of one
session count toward it, the floor is reached early and the percentile is computed over a
series containing repeated observations. An IV rank is a position within a distribution;
duplicating a point moves that position. The number would publish, look settled, and mean
something other than what the document says it means. That is the failure class decisions
0003 and 0014 exist to prevent — this time inside one vendor rather than between two.

=== WHAT THE BRIEF MUST CONTAIN ===

Develop at least these options. Add others if you find them; discard any you can show to be
strictly worse, and say why.

  A. Leave it. Count snapshot dates, document the caveat harder.
  B. De-duplicate on the chain's own last_trade_time, per ticker, when reading history.
  C. Refuse to STORE a snapshot whose session is already stored for that ticker.
  D. Filter history to exchange trading days by calendar.
  E. Change the floor to compensate for expected duplication.

FOR EACH OPTION YOU MUST GIVE, and this is the part that makes the brief useful:

  1. What the stored series would contain TODAY under that option. Real numbers from the
     real store, per ticker where they differ — not an illustration.
  2. When the first provisional rank would publish under it, assuming the briefing runs each
     weekday from the date you write the brief. Give a date.
  3. What the published number would then MEAN, in one sentence a reader would understand.
  4. What happens to the three rows already stored. Are they kept, re-labelled, or dropped?
     Dropping stored data is a real cost and must be named as one.
  5. The good side and the bad side. Both. An option with no downside is one you have not
     finished analysing.
  6. Whether it can be implemented without touching a file another lane owns, and roughly
     how big it is.

=== HOW TO WRITE IT ===

The owner reads these to decide, so: spell out every abbreviation on first use, including
IV, ATM, OI and OPRA. No option gets recommended without its cost stated in the same
paragraph. Project every option onto the actual store rather than onto a hypothetical.
Where you do not know something, write that you do not know it — a brief that hides a gap
produces a decision made on a gap.

End with a single recommendation and the one question the owner must answer to close this.
State explicitly whether this blocks shipping or can ship open, and justify it.

=== BUDGET ===

Zero live requests. The store, data/raw/cboe/ and the code answer every question here.
```

---

## Why these are separate

Prompt A corrects a claim about **two vendors disagreeing**. Prompt B addresses **one vendor
disagreeing with itself**. A found B, but merging them would let a documentation correction
quietly become a change to how every published percentile is computed — which is a decision
the owner has not yet made.
