# Lane O — Live verification and integration

**Implements:** the close of round 3. **Closes:** definition-of-done items 2, 9, 15 and 21,
and restates items 4 and 7.
**Depends on:** **all of K, L, M and N finished.** Do not start the integration tasks before
they report completion in `CROSS-LANE.md`.
**Live request allowance:** **one full daily run, on a day the owner names.** Claim it in
`tasks/BUDGET-LEDGER.md` and check `ops/live_budget.py` first. See D16.

## Owns — write only these

```
tasks/RESULTS.md
tasks/README.md
README.md
HANDOFF.md
```

Lane O may also touch any file K, L, M or N own — **but only after all four have reported
completion**, and only to reconcile them with each other. It may not touch
`src/briefing_app/dashboard/grading.py`, which is locked for the whole of round 3 (D15).

---

## Why this lane exists in this shape

Round 1's `RESULTS.md` recorded definition-of-done item 2 as **Passed**, citing
`status=succeeded, failures=0, diagnostics=0` on run `daily-2026-09-07-f1b0d2e1` — the run
that reached **no provider at all** and wrote no raw cache. The verification was reading a
status that could not fail.

That is the standard this lane is held to. **A criterion is not met because a lane said so;
it is met because a named command produced named output.** Where you cannot produce the
output, record the criterion as open and say exactly what is missing. Round 2 did this
correctly for items 4 and 15 and it is why round 3 could be planned honestly.

---

## Tasks

- [ ] **O1 — Full suite, from a clean tree**

  ```bash
  PYTHONPATH=src .venv/bin/python -m pytest
  ```

  Baseline entering round 3 is **671 tests, zero failures** (verified 2026-09-08, exit 0).
  Record the new count and the exit code. A lower count than 671 means tests were deleted
  rather than replaced — find out which and why before recording anything as passed.

- [ ] **O2 — Re-verify items 2 and 9 on a live run**

  This is the criterion round 2 could not close because no network spend was authorised.
  D16 authorises exactly one run for this lane.

  **Before spending:**

  ```bash
  PYTHONPATH=src .venv/bin/python ops/live_budget.py --json
  ```

  Claim it in `tasks/BUDGET-LEDGER.md`. If the verdict is no, **stop and wait** —
  do not spend anyway. A drained allowance produces exactly the degraded run this criterion
  is trying to measure, which would make the measurement meaningless as well as harmful.

  ```bash
  PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --data-mode live --force
  # then read data/runs/<date>/<run-id>.json
  ```

  Record `status`, `diagnostics` and `run_health`.

  **What counts as a pass, and this is the part that is easy to get wrong.** Item 9 has two
  halves and **both must hold**:

  - A run that reached no providers reports **`partial`**, names them, and renders a banner.
  - A **healthy** run still reports `succeeded`.

  If every run is `partial`, the status carries exactly as little information as
  `succeeded` did before round 2, and the criterion has failed even though the banner
  appears. D9 says this explicitly and Lane G built the severity classification around it.

  `partial` is the **expected and correct** result for the current data situation. Do not
  treat it as a failure of the run; read it against items 9 and 10. Item 10 also holds only
  if a warm-up baseline still building did **not** contribute to the `partial` — check the
  diagnostics for that specifically, because Lane K has just changed the warm-up's wording
  and message count.

- [ ] **O3 — Track item 21 to completion: the first provisional volatility reading**

  This is the only criterion that proves round 3 delivered something a reader can see.

  Lane K lowers the threshold to 10 sessions. The store held **3** on 2026-09-08 and still
  held **3** on 2026-09-09, so this needs **about 7 more weekday runs** — it cannot be closed
  on the day the code lands, and no amount of effort in this lane changes that.

  > **Track the runs, not only the sessions, and this is not a formality.** There was **no
  > daily run on 2026-09-08**: `data/runs/` stops at 2026-09-07 and the Alpha Vantage budget
  > counters stop at 2026-09-06. A missed weekday costs a session and the clock does not
  > stop, which is exactly what D1 predicted of local scheduling and what D3 warned would
  > stall the baseline.
  >
  > So report **two** numbers each time, not one: sessions stored, and weekday runs that
  > actually happened since Lane K landed. If those diverge, item 21 is not blocked on the
  > code and saying "waiting for sessions" would be misleading — it is blocked on the run
  > cadence, and that is a different problem with a different owner. Say so plainly rather
  > than letting the criterion sit open with no stated cause.

  Set up the check and record it as an open, dated criterion with a projected close date:

  ```bash
  .venv/bin/python -c "
  import sqlite3; c = sqlite3.connect('data/briefing.sqlite3')
  print('sessions:', c.execute('select count(distinct snap_date) from daily_snapshot').fetchone()[0])
  print('iv_rank set:', c.execute('select count(*) from daily_snapshot where iv_rank is not null').fetchone()[0])
  "
  ```

  It is met when `iv_rank` is non-null on at least one row **and** a live run produces at
  least one setup that was previously rejected for want of a volatility rank. Both halves.
  A populated column with no change in output has not delivered anything.

  ```bash
  ls data/runs/                              # weekday runs that actually happened
  ls data/provider_budget/alpha_vantage/     # days on which requests were actually made
  ```

  Record it as **open with a date**, not as passed and not as failed. Round 2's handling of
  items 4 and 15 is the model.

- [ ] **O4 — Restate the definition-of-done items that round 3 changed**

  In `tasks/README.md`, which you own. Three items no longer describe what is being
  built, and leaving them is how a plan quietly stops matching the product:

  - **Item 4** says "20 of 20 stored sessions for every US name". D13 changed the threshold
    to 10 with a provisional band. Restate it against the two thresholds, keeping the
    second half — **no fixture-mode row in `daily_snapshot`** — unchanged and still
    verified.
  - **Item 7** says "the daily run has fired unattended, on schedule, on three consecutive
    weekdays". The owner declined the `launchd` scheduler and runs the briefing by hand, to
    keep the shared allowance under manual control. Restate it as owner-operated: three
    weekday runs recorded, launched by hand. **This is a scope decision already taken, not a
    gap being papered over** — say which it is, in the file.
  - **Item 15** becomes item 21 and is restated against the 10-session threshold (O3).

- [ ] **O5 — Record round 3 in `RESULTS.md`**

  Same table shape as rounds 1 and 2: item, status, evidence. Evidence is a command and its
  output, not a claim. Every item introduced by round 3 (16 to 21) gets a row, and items 2,
  4, 9 and 7 get corrected rows.

  Where a criterion is open, say what is missing and what would close it.

- [ ] **O6 — Synchronise `README.md` and `HANDOFF.md`**

  Definition-of-done item 8: every counted claim in `README.md` matches what the code
  actually does. Round 3 changes at least four things a reader is told:

  - The volatility baseline threshold and what "provisional" means.
  - The ideas table is now two sections, not one ranked list.
  - The backfill exists but is **not** the plan for filling the baseline, and why.
  - Live runs by agents are budget-governed, with a ledger.

  `HANDOFF.md`: correct the test-count baseline, record the round-3 decisions D13 to D16 by
  reference (do not restate them — `DECISIONS.md` is the record), and close out the
  volatility-warm-up thread that has been open since D3. Do not amend `tasks/archive/phase-3/todo.md` or
  `tasks/archive/phase-3/plan.md`; they are the closed Phase-3 record.

- [ ] **O7 — Resolve every open entry in `CROSS-LANE.md`**

  Round 2's integration pass resolved its open entries by appending a resolution entry
  rather than editing the originals. Do the same. Pay particular attention to:

  - The Lane K ↔ Lane L field-name exchange — confirm what actually shipped.
  - Lane M's statement of which half of D14 it measured, so item 19 is not recorded as more
    complete than it is.
  - The two round-2 entries left open against D12: **D12 is closed by D13** and they should
    be marked so.

---

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest
PYTHONPATH=src .venv/bin/python ops/audit_dashboard.py output/published/latest/dashboard.json
PYTHONPATH=src .venv/bin/python ops/status.py --json
PYTHONPATH=src .venv/bin/python ops/live_budget.py --json
```

## Done when

- The suite is green and the count is recorded, with any drop from 671 explained.
- Items 2 and 9 are verified on a real run, with both halves of item 9 addressed.
- Items 4, 7 and 15/21 are restated in `tasks/README.md` to match what was decided.
- `RESULTS.md` carries a row per round-3 criterion, with commands and output as evidence.
- `README.md` and `HANDOFF.md` describe the shipped behaviour.
- No `CROSS-LANE.md` entry is left without a resolution.
- Exactly one live run was spent by this lane, and it was claimed in the ledger first.
