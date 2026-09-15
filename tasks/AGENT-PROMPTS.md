# Agent prompts — round 3

Copy-paste prompts for launching the round-3 lanes. One **fresh session per lane**, all in
this same working tree.

## How to run them

**The gate is satisfied.** The baseline is committed at `545e9e3`, the tree is clean, and
the suite is **671 passing, zero failures**. Nothing is blocking a start.

1. Open four terminals in `/Users/fernando/personal-projects/briefing-app`.
2. Start **K, L, M and N together** — they share no files and no lane blocks another.
3. Start **O only after all four have reported completion** in `CROSS-LANE.md`.

The one coordination point: **Lane K needs a field on a model Lane L owns.** K proposes the
name in `CROSS-LANE.md`, L confirms and adds it. Both prompts say so. If K reaches that
point before L is running, K should write the proposal and continue with its other tasks.

> **Why separate sessions rather than subagents.** Each lane does substantial independent
> work across many files and must own its own context. Subagents would re-derive the same
> repository knowledge five times and cannot hold a lane's file ownership discipline across
> a long edit sequence.

---

## Shared preamble — paste this at the top of every lane prompt

```text
You are working in /Users/fernando/personal-projects/briefing-app, a Python options
briefing application. Several agents work in this one tree at the same time, partitioned by
strict file ownership.

READ FIRST, IN THIS ORDER:
1. HANDOFF.md — the traps you cannot infer from the code. Do not skip it; every item in it
   has already cost someone time.
2. docs/architecture/decisions/README.md — the sixteen decisions that bind this work.
3. tasks/README.md — the lane map, file ownership, and the definition of done.
4. Your own lane document, named in your task below.
5. tasks/CROSS-LANE.md — what other lanes have already settled. Read the entries from
   2026-09-08 onward.

THE RULES, ALL OF THEM BINDING:

- FILE OWNERSHIP. Your lane document lists the files you own. You may READ anything. You may
  WRITE only files in your own Owns list. This is a convention, not a tool guarantee: if you
  write outside your lane the other agent's work is silently destroyed, with no conflict
  marker and no warning. Before editing any file, confirm it appears in your Owns list.
- If you genuinely need a file another lane owns, STOP and append an entry to
  tasks/CROSS-LANE.md saying which file, which task, and why. Do not edit it.
- src/briefing_app/dashboard/grading.py is owned by NOBODY this round, deliberately. No
  grade may change as a result of round 3. Do not touch it.
- Do not re-litigate a decision. If you believe one is wrong, record the objection in
  tasks/CROSS-LANE.md and proceed as decided.
- tasks/CROSS-LANE.md is APPEND-ONLY. Never edit or delete another lane's entry.
- LIVE REQUESTS: your allowance is stated in your lane document. The Alpha Vantage free
  allowance is 25 requests per day, shared with the daily briefing. Exceeding it produces
  exactly the provider-less run that round 2 existed to fix.
- TEST BASELINE: 671 passing, zero failures. Verify before you start and before you finish:
      PYTHONPATH=src .venv/bin/python -m pytest
  A count below 671 means tests were deleted rather than replaced. Find out which and why.
- Evidence is a command and its output, never a claim. Round 1 recorded a criterion as
  passed by reading a status that could not fail; that is the standard you are held against.

WHEN YOU FINISH: append a completion entry to tasks/CROSS-LANE.md naming the files you
wrote, the test count before and after, and anything you decided that the lane document left
open. Lane O cannot verify your work without it.

If something in your lane document is wrong or impossible, say so plainly and record it
rather than working around it silently.
```

---

## Lane K — Volatility baseline threshold

```text
[SHARED PREAMBLE HERE]

YOUR LANE: K — Volatility baseline threshold.
Your task document is tasks/lanes/lane-k-volatility-threshold.md. Follow it.

You implement decision 0013: lower the self-built baseline threshold from 20 sessions to 10,
and publish anything computed on fewer than 20 sessions as PROVISIONAL.

THE TRAP, AND IT IS THE WHOLE TASK. Lowering the constant is a two-line change. That is not
the job. A percentile over 10 observations resolves only to the nearest tenth — "IV rank 80"
means "second highest of ten" and nothing finer. If a 10-session reading is published looking
identical to a 20-session one, you will have turned a deliberate, accepted trade-off into a
silent misrepresentation. That is the failure this project has already corrected twice. The
provisional marking is the deliverable; the constant is the trivia.

Note that ONE constant gates THREE legs, not one: iv_rank, put/call volume percentile, and
put/call open-interest percentile. A test covering only iv_rank has tested a third of the work.

COORDINATION: task K2 needs a field on a model in src/briefing_app/dashboard/models.py, which
LANE L OWNS. Propose the field names and semantics in tasks/CROSS-LANE.md and let Lane L add
them. Follow the Lane G <-> Lane H "RunHealth" exchange in that file as the precedent — it
worked because the shape was agreed in writing before either side built against it. Do not
edit models.py and do not read Lane L's in-progress code. If Lane L has not started yet, post
the proposal and get on with K1, K3, K4 and K5.

Your live request allowance is ZERO. Fixture mode only.
```

---

## Lane L — Report split

```text
[SHARED PREAMBLE HERE]

YOUR LANE: L — Report split: supported and contradicted theses.
Your task document is tasks/lanes/lane-l-report-split.md. Follow it.

You implement decision 0015: the single ranked ideas table becomes two clearly headed
sections — theses the data supports, ranked as now, and theses the data contradicts, listed
with the data's own reading.

CONTEXT YOU MUST NOT MISREAD. Nine of sixteen rows currently score exactly 0.0. This is NOT a
bug. The grade measures how far the evidence supports the direction declared for that name in
config/universe.example.yaml, and for those nine the composite signal disagrees with the
declared thesis. Decision 0011 calls this "the tool falsifying your declared theses, and
arguably the most valuable thing it does". Your job is to make it legible. Your job is NOT to
make those rows score differently.

THE HARD CONSTRAINT: this is presentation only. src/briefing_app/dashboard/grading.py is
locked for the whole round. Your own done-check is that `git diff --stat --
src/briefing_app/dashboard/grading.py` is empty when you finish.

DO NOT BREAK THESE. Three criteria verified in round 2 are pinned by named tests that pass
today. After your re-layout each must still hold, by the same test or a strictly stronger
replacement — never by deleting one:
  - conviction and certainty legible as two labelled measurements
  - declared thesis shown beside the data's reading, disagreement marked
  - ordering by conviction, pinned by a test with MORE THAN ONE row
Your lane document names each test.

Assert that every published idea lands in exactly one section. A row silently dropped by a
partition bug is the worst outcome here, and it is invisible on a page you already expect to
look different.

COORDINATION: Lane K will propose a provisional-baseline field for you to add to
src/briefing_app/dashboard/models.py. Confirm it in tasks/CROSS-LANE.md and add it. models.py
is extra="forbid" — that is deliberate, do not relax it.

Your live request allowance is ZERO. Fixture mode only.
```

---

## Lane M — Vendor consistency

```text
[SHARED PREAMBLE HERE]

YOUR LANE: M — Vendor consistency: measure the gap before permitting a splice.
Your task document is tasks/lanes/lane-m-vendor-consistency.md. Follow it.

You implement decision 0014. Every stored iv_atm, pc_ratio_vol and pc_ratio_oi in this project
came from CBOE, captured intraday. Any Alpha Vantage historical chain is the session close. A
percentile is a ranking within ONE series, so splicing two vendors answers a comparison nobody
made — and the answer looks exactly as confident as a correct one.

READ THIS BEFORE YOU PLAN YOUR DAY, IT WILL SAVE YOU ONE. The owner chose "measure the
difference first" AND chose not to pay for Alpha Vantage premium. The implied-volatility half
of the measurement NEEDS a paid key: Alpha Vantage HISTORICAL_OPTIONS is not on the free tier,
it answers HTTP 200 with a sample payload that this project's own validation classifies as
`synthetic`, and those requests are spent and wasted.

That does NOT make this lane empty. Two things are executable today and they are the lane:
  1. The put/call half is measurable FREE, now. MarketData.app serves genuine past-dated
     chains keyless with real volume and openInterest — Lane I verified 1,336 contracts across
     10 expirations for AAPL. Compare against the CBOE-derived values already stored for
     2026-09-03, 09-06 and 09-07. Note AAPL is the only keyless symbol; SPY, QQQ and CRWV
     return 401. A one-symbol comparison honestly described beats a broader one you cannot make.
  2. The implied-volatility half gets written up UNEXECUTED, precise enough to run in ten
     minutes on a paid key, with its decision rule fixed BEFORE any data arrives.

If you find yourself about to send an Alpha Vantage HISTORICAL_OPTIONS request to "just check",
stop. That is the one thing this lane is forbidden to do.

THE CONSTRAINT THAT MAKES IT A MEASUREMENT: compute the MarketData.app side through EXACTLY
the functions the live path uses — the normaliser plus options_math.py. Not an equivalent
calculation. Write your own ratio arithmetic and you will be measuring your arithmetic against
the live path's, not one vendor against another, and the number will be worthless in a way
that is invisible. Read tests/test_backfill.py::test_backfill_reproduces_a_row_the_live_path_stored
before writing yours.

Your Alpha Vantage allowance is ZERO. MarketData.app keyless probes are permitted and are not
budget-tracked. Verify at the end that today's counter in data/provider_budget/alpha_vantage/
did not move.
```

---

## Lane N — Live-run budget ledger

```text
[SHARED PREAMBLE HERE]

YOUR LANE: N — Live-run budget ledger.
Your task document is tasks/lanes/lane-n-live-budget.md. Follow it.

You implement decision 0016: lanes may make live provider requests, but only inside a written
allowance that is CHECKED BEFORE SPENDING against the recorded daily counters in
data/provider_budget/<provider>/.

WHY THIS IS NOT BUREAUCRACY. The Alpha Vantage free allowance is 25 requests a day, shared by
every lane and by the daily briefing itself. Several lanes can each respect an individual
limit and still collectively drain the pot. A drained pot means that day's real briefing runs
degraded — which is precisely the failure that produced the silent-success bug round 2 existed
to fix. Look at data/provider_budget/alpha_vantage/: the counters stop at 2026-09-06, and the
2026-09-07 run reached no provider at all while reporting `succeeded`.

An allowance that is a convention is not an allowance. Build the ledger so a claim is a real
step.

DO NOT INVENT A SECOND POLICY. src/briefing_app/backfill.py already implements a live-run-first
reservation: hold back the full allowance until today's run has finished, then all but a small
remainder. Read it and be consistent with it. Two reservation rules that disagree are worse
than one imperfect rule. You do not own backfill.py — Lane M does — so read it, do not change it.

TEST THE CASE THAT ACTUALLY HAPPENED: no counter file for today. That is the 2026-09-07 shape,
and it must NOT be read as "25 available and all is well". Also cover: daily run not yet done,
allowance already fully claimed by other lanes, and a request larger than what remains. Use
temporary data roots with fabricated counter files — spend nothing.

Your live request allowance is ZERO. You build the ledger; you must not be its first spender.
```

---

## Lane O — Verification and integration (runs last)

```text
[SHARED PREAMBLE HERE]

YOUR LANE: O — Live verification and integration.
Your task document is tasks/lanes/lane-o-verification.md. Follow it.

DO NOT START until Lanes K, L, M and N have all reported completion in tasks/CROSS-LANE.md.
Check that first. If any is missing, stop and say which.

WHY THIS LANE HAS THE SHAPE IT HAS. Round 1's RESULTS.md recorded "live run clean" as PASSED,
citing status=succeeded, failures=0, diagnostics=0 on the run that reached no provider at all
and wrote no raw cache. The verification was reading a status that could not fail. A criterion
is not met because a lane said so; it is met because a named command produced named output.
Where you cannot produce the output, record the criterion as OPEN and say exactly what is
missing — round 2 did that correctly and it is why round 3 could be planned honestly.

YOUR ONE LIVE RUN. You are authorised exactly one full daily run, on a day the owner names.
Before spending it, run `PYTHONPATH=src .venv/bin/python ops/live_budget.py --json` and claim
it in tasks/BUDGET-LEDGER.md. If the verdict is no, STOP AND WAIT. Spending anyway produces
the degraded run you are trying to measure, which makes the measurement meaningless as well
as harmful.

THE HALF-CRITERION PEOPLE GET WRONG. Item 9 has two halves and BOTH must hold: a run that
reached no providers reports `partial` and names them, AND a healthy run still reports
`succeeded`. If every run is `partial`, the status carries as little information as
`succeeded` did before, and the criterion has FAILED even though the banner appears.
`partial` is the expected and correct result for the current data situation — read it against
items 9 and 10, not as a failed run.

ONE CRITERION YOU CANNOT CLOSE TODAY, AND MUST NOT PRETEND TO. Item 21 needs about 7 more
weekday runs after Lane K lands, because the store holds 3 sessions and the new threshold is
10. Track TWO numbers, not one: sessions stored, and weekday runs that actually happened.
There was no daily run on 2026-09-08. If those two diverge, item 21 is blocked on the run
cadence, not on the code — say so plainly rather than leaving it open with no stated cause.

Finally: restate definition-of-done items 4, 7 and 15 in tasks/README.md so the plan matches
what was actually decided, and resolve every open entry in tasks/CROSS-LANE.md by appending a
resolution — never by editing the original.
```

---

## What "finished" means

Round 3 closes when `tasks/RESULTS.md` carries a row per criterion 16–21 with a command and
its output as evidence, and items 2 and 9 are re-verified on a real run.

**Two criteria will still be open on the day the code lands, by design:**

- **Item 21** — needs ~7 more weekday runs for the volatility baseline to reach 10 sessions.
- **Item 20** — "no lane spent an unclaimed request" can only be confirmed at the end.

That is expected. A round that reports every criterion green on the day it ships is the
pattern this project has twice found to be wrong.
