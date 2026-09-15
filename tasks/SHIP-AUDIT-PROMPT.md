# Ship-readiness audit prompt

For a **fresh session with no stake in the work**. One auditor, not several — a verdict needs
one consistent judgement, and splitting it produces five partial opinions nobody can combine.

**Do not run this in a session that implemented any lane.** The whole value is independence.

---

## The prompt

```text
You are auditing /Users/fernando/personal-projects/briefing-app to answer two SEPARATE
questions. Do not merge them — they have different answers.

  Q1. Is the planned work actually implemented, as specified?
  Q2. Is the application ready to ship?

You are not here to help finish it. You are here to find out what is true. Do not fix
anything, do not complete anything, do not commit anything. If you are tempted to make a
change so a check passes, that is exactly the finding you should be reporting instead.

=== THE STANDARD YOU ARE HOLDING THIS TO ===

This project has failed the same way twice, and both times a report said "passed":

1. Round 1 recorded criterion 2 "live run clean" as PASSED, citing status=succeeded,
   failures=0, diagnostics=0 — on a run that reached NO PROVIDER AT ALL and wrote no raw
   cache. Per-ticker problems accumulated in a list that never reached output.diagnostics,
   so the status could not fail. The verification was reading a value that had no way to
   say no.
2. A round-1 correctness test built both sides of its comparison with the same function, so
   it proved the code agreed with itself rather than that it reproduced a stored live value.

So: EVIDENCE IS A COMMAND AND ITS OUTPUT, and for every "passed" you must additionally ask
"could this check have failed?" A green test whose assertion cannot fail is worse than no
test, because it manufactures confidence. Name any you find.

=== WHAT YOU MAY NOT TRUST ===

tasks/RESULTS.md, tasks/CROSS-LANE.md and HANDOFF.md are the artifacts UNDER AUDIT. Read
them to learn what was CLAIMED, then verify each claim against primary sources:

  - the source and test code itself
  - the SQLite store at data/briefing.sqlite3
  - run records under data/runs/
  - provider counters under data/provider_budget/
  - published artifacts under output/
  - git history and the working tree

A lane's own completion entry is a claim, not evidence. Lane O's report is also a claim,
including the parts where it declined to certify something — verify those too, in both
directions: it may have been too harsh as easily as too lenient.

=== SCOPE: WHAT WAS SUPPOSED TO HAPPEN ===

Read, in this order:
  1. docs/architecture/decisions/README.md — the sixteen binding decisions
  2. tasks/README.md — the definition of done, items 1-21, including the round-3
     restatements of items 4, 7 and 15
  3. tasks/lanes/*.md — the five lane specifications, K through O
  4. THEN tasks/RESULTS.md and tasks/CROSS-LANE.md, as claims to test

Round 3 implemented decisions 0013 (volatility threshold 20 -> 10 with provisional
marking), 0014 (vendor consistency, measure before splice), 0015 (report split into
supported and contradicted theses) and 0016 (live-run budget ledger).

=== Q1: IS IT IMPLEMENTED? ===

For EACH definition-of-done item 16 through 21, plus items 1, 2, 4, 7, 9 and 10, determine
independently: MET / NOT MET / CANNOT BE DETERMINED, with the command and output that
settles it. Where you say MET, state what would have made it fail.

Specific things to verify rather than assume:

  - The threshold change gates THREE legs (iv_rank, put/call volume percentile, put/call
    open-interest percentile), not one. Confirm all three are covered at all three
    boundaries (9 withholds, 10 publishes provisional, 20 settles). A test covering only
    iv_rank means a third of the work is unverified.
  - A provisional reading must be distinguishable from a settled one in the STORED ROW, in
    dashboard.json AND on the rendered page. Check all three, not one.
  - src/briefing_app/dashboard/grading.py was locked for the whole round: no grade may have
    changed. Verify with git diff against the round-3 baseline commit, not by reading a
    claim that it is unchanged.
  - Every published idea must appear in exactly one report section — not zero, not two.
  - The report must still show conviction and certainty as two labelled measurements, and
    still mark a thesis that disagrees with the data. These were verified in round 2; check
    they survived the re-layout rather than being quietly dropped.

=== KNOWN SOFT SPOTS — PROBE THESE HARDEST ===

These are where the reports themselves admit uncertainty. Your job is to say whether the
admission is calibrated.

  a. THE TREE IS NOT COMMITTED. Lane O reports the integration tree dirty at HEAD 545e9e3.
     Establish exactly what is uncommitted, whether the passing suite depends on
     uncommitted work, and whether any lane wrote outside its declared file ownership.
     That last one is the failure the whole parallel arrangement is exposed to and nothing
     enforces it. Check it by mapping every changed file to its owning lane.

  b. THE SUITE INITIALLY FAILED, THEN PASSED. The exact documented command first exited 1
     with 2 failures (test_fred_client_requires_key_before_network,
     test_finnhub_client_requires_key_before_network) because CLI unit tests loaded the
     checkout's .env into the shared pytest process, handing real credentials to tests that
     assert a client refuses to work WITHOUT credentials. The fix stubs
     configure_environment in tests/test_ops_scripts.py. Determine whether that is genuine
     test isolation or a mask. The decisive question: do those two victim tests still FAIL
     if the leak is reintroduced? If they cannot fail either way, they are dead assertions.
     Also check no other test in the suite depends on ambient credentials.

  c. ITEM 19 WAS NOT INDEPENDENTLY REPLAYED. Lane M reports measured put/call vendor gaps
     (AAPL volume 8.93% / 0% / 55.38%, open interest 3.92% / 0% / 146.34%) but did not
     retain the payloads, so Lane O could not reproduce them. Reading a table is not
     measurement. Establish whether the numbers can be reproduced from anything in the
     repository. If they cannot, say plainly that this criterion rests on an unverifiable
     report — and note that a 146% gap, if real, is enormous and argues the vendor splice
     must stay refused.

  d. ITEM 20 CANNOT BE PROVEN FROM AN EMPTY LEDGER. "No lane spent an unclaimed request"
     is being certified against a ledger with no entries and missing daily counters. Absence
     of a counter is not proof of zero spend. Reconcile what you can from
     data/provider_budget/ and state precisely what remains unprovable.

  e. ITEM 7 PROVES RUNS, NOT MANUAL LAUNCHES. Run records exist for several weekdays but
     carry no launch provenance. Say whether the criterion as restated is satisfiable from
     the artifacts at all.

=== Q2: IS IT READY TO SHIP? ===

Separate question, and do not let a high implementation score answer it.

State clearly which open items are BLOCKING and which are merely INCOMPLETE, and justify
the split. Consider at minimum:

  - Has any live run happened under the corrected run-health status? The budget verdict was
    NO and Lane O sent zero requests, so item 2/9 may never have been exercised against
    reality.
  - Does the product currently DO anything it could not do before round 3? Item 21 exists
    precisely to answer that, and it is the only criterion that proves the round delivered
    a visible difference. Check the store: how many snapshot dates, how many non-null
    iv_ranks, how many live runs since the threshold change landed.
  - Would a reader opening today's report see a provisional volatility rank? If not, the
    headline feature of round 3 is shipped but inert.

=== BUDGET — BINDING ===

Make NO live provider requests. The Alpha Vantage free allowance is 25/day and shared with
the daily briefing; the current budget verdict is NO. Everything in this audit is doable
offline against the repository, the store and recorded artifacts. If you believe a live run
is required to settle something, say so and stop — do not spend.

=== OUTPUT ===

Produce a report with exactly these parts. Do not write it into tasks/RESULTS.md or any
other tracked file unless the owner asks — you are auditing that file, not editing it.

  1. VERDICT, in two lines: is the plan implemented? is it shippable? Yes / No / Qualified.
  2. A table: item, claimed status, YOUR finding, the command and output that settles it.
  3. DISCREPANCIES — every place your finding differs from what RESULTS.md claims, in
     either direction. If there are none, say so explicitly; that is a meaningful result.
  4. EVIDENCE THAT CANNOT FAIL — any check, test or criterion that would pass regardless of
     whether the underlying behaviour works. Name each one.
  5. BLOCKING vs INCOMPLETE — what must be true before shipping, and what can ship open.
  6. THE SHORTEST PATH TO SHIPPABLE — ordered, with who must do each step and whether it
     needs the owner (a live run, a commit, an authorisation) or can be done by an agent.

Be concise and specific. If something is fine, one line. Spend your words on what is wrong,
what is unprovable, and what is claimed more confidently than the evidence supports.
```

---

## What an auditor will almost certainly find

Recorded here so the audit can be checked against a prediction rather than graded on its own
say-so. From the state as of 2026-09-09:

| | |
|---|---|
| Suite | 692 passing, zero failures, up from a 671 baseline. No test deletions |
| Working tree | **Uncommitted.** HEAD is `545e9e3`; all of K–N's work is unstaged |
| Store | **3 snapshot dates, 0 non-null `iv_rank`, no live run since 2026-09-07** |
| Live acceptance | **Never exercised.** Budget verdict NO, zero requests sent |

So the likely verdict is **implemented but not shippable**: the code is in and tested
offline, and the one criterion that proves round 3 delivered a visible difference — item 21
— has not moved at all and cannot move without roughly seven more weekday runs.

If the audit comes back saying everything passed, that is itself the finding worth chasing.
