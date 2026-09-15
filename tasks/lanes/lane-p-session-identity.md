# Lane P — Session identity

**Implements:** decision [0017](../../docs/architecture/decisions/0017-session-counting.md),
option **B2**. **Closes:** definition-of-done items 22–27.
**Depends on:** the round-4 baseline commit (gate).
**Live request allowance:** **0.** Everything here is offline — the raw payloads the repair
needs are already on disk.

## Owns — write only these

```
src/briefing_app/storage.py
src/briefing_app/scoring.py
src/briefing_app/pipeline.py
src/briefing_app/backfill.py
src/briefing_app/providers/normalizers.py
migrations/004_session_identity.sql          (new)
ops/repair_snapshot_sessions.py              (new)
tests/test_storage_repository.py
tests/test_scoring.py
tests/test_pipeline.py
tests/test_backfill.py
docs/architecture/VOLATILITY-BASELINE.md
```

`providers/normalizers.py` is listed because 0017 anticipated it, **but check before you
change it**: `last_trade_time` is already parsed there and already lands on the model at
`models/market_data.py:111`. The likely answer is that it needs no change at all.

## Must not touch

- `src/briefing_app/dashboard/**` — and `dashboard/grading.py` stays **locked**, as it has
  been since round 3. No grade changes.
- `docs/architecture/decisions/**` — 0017 is Accepted. Implement it; do not re-open it.
- `tasks/CROSS-LANE.md` is append-only. Never edit another entry.

---

## Why this is one lane

The change spans `storage.py`, `scoring.py`, `pipeline.py` and `backfill.py`. Splitting it
would give you sequencing, not parallelism — the column has to exist before any caller writes
it — and it would require two lanes to agree a database column's semantics in writing. When
`RunHealth` was negotiated that way in round 2 it worked, because a mismatch failed loudly on
a `extra="forbid"` model. **A mismatch here fails silently, as a wrong percentile.** That is
the exact failure 0017 exists to prevent, so the work is not partitioned.

---

## Where this actually stands

Verified offline on 2026-09-09. Read 0017 in full before starting; the essentials:

**The store holds three snapshot dates but no ticker has more than two exchange sessions.**

| Stored date | Day | Tickers | Session actually captured |
|---|---|---:|---|
| 2026-09-03 | Thursday | 23 | 21 → session 09-03; **FDX and LMT → session 09-02** |
| 2026-09-06 | Sunday | 18 | all 18 → session **09-04** |
| 2026-09-07 | Monday, Labor Day | 18 | all 18 → session **09-04** |

**4 September is counted twice for all eighteen tickers**, and the two reads disagree — for
AAPL by 146% on put/call open interest.

> ### The three things that will mislead you
>
> 1. **A calendar filter does not work.** FDX and LMT carried a stale chain on 2026-09-03,
>    an ordinary trading day, and FDX was stale again on the 09-04 capture. This is a
>    per-ticker property of the delayed feed. **Key on each chain's own `last_trade_time`,
>    never on the run date.**
> 2. **Session identity is nowhere in the database today.** `daily_snapshot` has no session
>    column; `raw`'s per-component `as_of` is the **run date**; and `evidence_ledger.as_of`
>    is the **capture timestamp**, not the session. None of the three is the field you need.
> 3. **`is_market_day` does not guard this and cannot be made to.** It is called once, at
>    `pipeline.py:628`, to decide whether to run at all, and `--force` bypasses it. Its
>    `holidays` parameter is never supplied and **no holiday calendar exists anywhere in the
>    repository** — which is why Labor Day passed as a market day. Do not try to fix this
>    problem there.

**B1 was considered and rejected**, so do not re-derive it: de-duplicating at query time by
re-reading the raw files couples published history to a file tree that is *overwritten* — the
evidence ledger holds two different `as_of` values for the 09-03 AAPL file, 14:04:14 and
17:14:21. A purged or archived raw tree would silently change published history.

---

## Tasks

- [x] **P1 — Persist the session on the row, at write time**

  A `daily_snapshot` column, written from the chain's own `data.last_trade_time`, reduced to
  the session date. Not the run date. Not the capture timestamp.

  Both write paths must set it: `pipeline.py:844` and `backfill.py:347`, which both call
  `repo.upsert_daily_snapshot`. The row is built by `scoring.to_daily_snapshot_row`, so the
  field is threaded through there rather than injected at each call site.

  Add `migrations/004_session_identity.sql`. Match the style of `003_setup_grade.sql`.
  Existing rows get NULL; P3 repairs them.

  **Acceptance:** a test asserts that a row written from a chain whose `last_trade_time` is
  2026-09-04, on a run dated 2026-09-07, stores the session as **09-04**. Write it so it
  fails against the current code first, then make it pass. A test that stores the run date
  and asserts the run date proves nothing.

- [x] **P2 — De-duplicate on read, later capture wins, and say so**

  `option_metric_history` returns at most one observation per (ticker, exchange session).

  **The tie-break is settled and is not yours to revisit: the later capture wins.** The owner
  answered this on 2026-09-09.

  **But it must not be silent.** Per D9's principle, the run records that a duplicate existed
  and which capture won. This matters more than it sounds: for AAPL the two 09-04 reads differ
  by 146% on put/call open interest, so a silent choice hides a two-order-of-magnitude
  decision. Classify the new message in `_issue_severity` — it is **`normal`**, not degraded;
  a duplicate is expected after a weekend and must not mark a run `partial`.

  **State honestly, in the docstring and in `VOLATILITY-BASELINE.md`, that "later wins" is a
  tie-break and not a correctness argument.** Why the repeated captures disagree is
  undiagnosed. The later capture is not demonstrably the right one, and nothing you write
  should imply it is.

  **Acceptance:** a test with two stored rows sharing one session asserts the history returns
  one observation, that it is the later capture's value, and that the run recorded the
  duplicate. A second test asserts a duplicate alone leaves the run `succeeded`.

- [x] **P3 — Repair the three stored rows, offline**

  `ops/repair_snapshot_sessions.py`, reading the sessions from
  `data/raw/cboe/delayed_options_chain/<run-date>/<TICKER>.json`, which are all present.

  **Nothing is deleted.** 0017 keeps all three rows deliberately: the duplicate is resolved on
  read, so the underlying evidence stays auditable — and `vendor-consistency.md` currently
  depends on both 09-04 reads existing.

  Support `--dry-run`, and make it refuse to write a session it cannot read from a payload
  rather than inferring one from the snapshot date. Inferring is the whole bug.

  **Acceptance — the numbers are given, so this is checkable, not a matter of opinion.** After
  the repair, per-ticker observation counts must be exactly:

  | Series | Expected after repair |
  |---|---|
  | `iv_atm` | **2** for 15 of 18 tickers; **1** JPM; **0** FDX; **0** LMT |
  | `pc_ratio_vol`, `pc_ratio_oi` | **2** for all 18 tickers |

  > **Corrected 2026-09-09.** This table first read `1` for LMT, inherited from 0017's
  > projection, which was written before its tie-break question was answered. Under the
  > row-level rule the owner chose, LMT's only implied-volatility reading is on the
  > superseded capture of the 2026-09-04 session, so it is **0**. See the correction
  > appended to 0017.

  If your repair produces different counts, it is wrong — stop and find out why rather than
  adjusting the expectation. Note that LMT's only implied-volatility reading sits on the
  09-06 capture of the 09-04 session, which the row-level rule supersedes — the row is kept
  in the store and stays auditable, but it is not an observation the history counts.

- [x] **P4 — Make the published label true**

  The page prints *"Provisional — N stored sessions"*. After this lane, N must count
  **distinct exchange sessions**. Today the label is false whenever a weekend, holiday or
  stale chain sits in the window — which is the reader-facing harm 0017 was written about.

  The dashboard is **not yours**. If the count is computed in `dashboard/`, record what you
  need in `CROSS-LANE.md` rather than editing it. If it flows from the history this lane
  returns, it corrects itself — verify which, and say so.

- [x] **P5 — Update `docs/architecture/VOLATILITY-BASELINE.md`**

  It currently documents the limitation and states that no code enforces it. That sentence
  becomes wrong when you land. Replace it with: what a session is, how it is derived, the
  tie-break and its honest status, and the FDX and LMT stale-chain cases as worked examples.

  Record the projection, and mark it as a projection: first provisional rank on **run 9,
  Monday 2026-09-21**; JPM and LMT implied volatility run 10, Tuesday 09-22; FDX run 11,
  Wednesday 09-23 **at the earliest and possibly never**.

- [x] **P6 — Report completion in `CROSS-LANE.md`**

  Name the files, the test count before and after, the repaired per-ticker counts, and
  anything you found that 0017 did not anticipate.

---

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest                     # expect >= 698 passed
PYTHONPATH=src .venv/bin/python ops/repair_snapshot_sessions.py --dry-run
.venv/bin/python -c "
import sqlite3; c = sqlite3.connect('data/briefing.sqlite3')
for r in c.execute('''select ticker, count(distinct chain_session_date)
                      from daily_snapshot where iv_atm is not null
                      group by ticker order by 2 desc, ticker'''): print(r)
"
```

Adjust the column name to whatever you chose. The point of the third command is that the
counts must match the P3 table.

## Done when

- Both write paths persist the chain's own session; a test pins the 09-07-run/09-04-session case.
- History returns one observation per (ticker, session), later capture wins, duplicate recorded.
- A duplicate alone does not mark a run `partial`.
- The repair produces exactly the counts in P3, and deletes nothing.
- `VOLATILITY-BASELINE.md` no longer says the limitation is unenforced, and states plainly
  that the tie-break is a tie-break.
- The full suite is green and `dashboard/grading.py` is unchanged.
