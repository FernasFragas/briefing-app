# Lane J — Backfill correctness and execution

**Implements:** the execution half of D3. **Blocked on:** D12, which Lane I is resolving.
**Depends on:** round 1 complete. Runs in parallel with G, H, I.

## Owns — write only these

```
src/briefing_app/backfill.py
src/briefing_app/cli.py
tests/test_backfill.py
docs/operations/IV-BACKFILL.md
```

## Must not touch

`pipeline.py` (Lane G) — read `SELF_BUILT_SERIES_MIN_SESSIONS` from it, do not change it.
`storage.py`. `dashboard/` (Lane H).

---

## Where this actually stands

Round 1 built the tool and it works. Its own dry run, 2026-09-07:

```
requested_pairs:              360     (18 tickers x 20 sessions)
already_stored:                16
remaining:                    344
estimated_days_at_allowance:   14     (Alpha Vantage free tier, 25 requests/day)
budget_remaining_today:        25
failed:                         0
```

What has **not** happened: a single real backfill request, and the correctness check that
must precede one. `iv_rank` is NULL on all stored rows.

> ### J1 comes first, and it is cheap
>
> D12 is open and Lane I may yet change which provider is used — but **the correctness test
> does not depend on the answer.** It costs a handful of requests, it gates everything else,
> and if it fails, no amount of budget or provider choice matters. Do it now, before Lane I
> reports.

---

## Tasks

- [ ] **J1 — Prove a backfilled reading equals a live one. Do this before anything else.**

  This is the whole correctness argument for the lane, and D3 was explicit that it is the
  task rather than a check on it.

  A backfilled `iv_atm`, `pc_ratio_vol` or `pc_ratio_oi` must be produced by **exactly** the
  same code path as a live one. Not an equivalent calculation — the same functions in
  `options_math.py`, given a normalised chain. A different strike-selection rule, a
  different expiry choice or a different interpolation produces a percentile that compares
  two different quantities and reports a confident, wrong answer. **That failure is
  invisible in the output**, which is why it must be proved rather than assumed.

  **The test:** pick a date the live path has already stored — `2026-09-03` or `2026-09-06`
  both have rows in `daily_snapshot` — run the backfill for that same (ticker, date), and
  assert the backfilled values match the stored live values **to full precision**.

  ```bash
  .venv/bin/python -c "
  import sqlite3; c=sqlite3.connect('data/briefing.sqlite3')
  print([d[0] for d in c.execute('select * from daily_snapshot limit 1').description])
  for r in c.execute(\"select ticker, snap_date, iv_atm, pc_ratio_vol, pc_ratio_oi \
  from daily_snapshot where snap_date='2026-09-06' limit 5\"): print(r)
  "
  ```

  **If the values do not match, stop.** Do not tolerate a small difference and do not adjust
  the expected value to fit. Understand the difference first and record it. A backfill that
  is subtly wrong is worse than no backfill, because the store then looks full.

  **Acceptance:** an automated test in `tests/test_backfill.py` reproduces a stored live row
  from a backfill run and asserts exact equality; it is named so its purpose is obvious; and
  `docs/operations/IV-BACKFILL.md` names it as the evidence for the comparability claim.

- [ ] **J2 — Make sure the backfill cannot starve the daily run**

  Both draw on the same Alpha Vantage allowance of 25 requests per day. If the backfill runs
  first and spends all 25, the live run gets nothing — which produces exactly the degraded,
  provider-less run that Lane G is fixing the reporting of. Fixing the symptom in Lane G
  while creating the cause here would be a poor outcome.

  Decide and implement a reservation: the daily run's needs come first, and the backfill
  consumes only what is genuinely spare. Write the policy down.

  **Acceptance:** a backfill run cannot reduce the live run's available allowance below what
  it needs; the reservation is tested; the policy is stated in `docs/operations/IV-BACKFILL.md`.

- [ ] **J3 — Execute, once D12 is closed**

  **Do not start this until Lane I reports and the owner has chosen.** The execution differs
  by outcome:

  | If D12 resolves to | Then |
  |---|---|
  | A free source Lane I found | Wire it, re-run J1 against **that** source, then execute |
  | Alpha Vantage premium | Execute in one pass; J1 must have passed first |
  | Alpha Vantage free, daily | Schedule it alongside the daily run under J2's reservation |
  | Reduced ticker set | Agree the list with the owner, then execute for those names |

  In every case, run with `--dry-run` first and record the plan.

  **Acceptance:**
  - `select count(*) from daily_snapshot where iv_rank is not null` returns greater than
    zero.
  - At least one name reaches 20 stored sessions and its baseline opens — the withheld
    message stops appearing for it.
  - A live run after the backfill produces at least one setup that was previously rejected
    with `iv_rank_unavailable`. **That is the actual point of all of this**, and it is the
    only acceptance criterion that proves the work delivered anything.

- [ ] **J4 — Update `docs/operations/IV-BACKFILL.md`**

  Round 1 created it. Add: the J1 reproduction evidence, the J2 reservation policy, the D12
  outcome and which source was used, and the real observed cost in requests and elapsed
  time versus the 14-day estimate.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_backfill.py -q
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv --dry-run
```

Back up `data/briefing.sqlite3` before any writing run. Round 1 set the precedent and the
backup it took is still there:
`data/briefing.sqlite3.backup-20260907-before-fixture-purge`.

## Handoff

Report to the owner: the J1 result (this is the one that matters), the reservation policy,
and — after execution — whether any previously blocked setup became available.
