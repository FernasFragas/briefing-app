# Lane C — Volatility history

**Implements:** D3 (backfill). **Closes:** blocker #2 (warm-up at 3 of 20, one of the three
synthetic) and the largest part of blocker #1 (almost no product).
**Depends on:** Lane 0 only. Runs in parallel with A, B, D, E.

## Owns — write only these

```
src/briefing_app/pipeline.py
src/briefing_app/storage.py
src/briefing_app/cli.py
src/briefing_app/backfill.py     (new)
tests/test_pipeline.py
tests/test_storage_repository.py
tests/test_backfill.py           (new)
migrations/004_*.sql             (new, only if C2 needs it)
docs/operations/IV-BACKFILL.md              (new)
```

## Must not touch

`options_math.py` — it computes the volatility metrics and **must be used unchanged**; that
is the whole correctness argument of this lane. `providers/alpha_vantage.py` — the client
method already exists and needs no change. If either seems to need editing, stop and record
it in `CROSS-LANE.md`.

---

## The measured state

```
daily_snapshot: 62 rows, 3 dates, iv_rank NULL on every row

  snap_date    run_id  rows  data_mode
  2026-09-03   1       23    live
  2026-09-04   2       21    FIXTURE     <-- synthetic data in the live history store
  2026-09-06   3       18    live
```

`_self_built_baselines` (`pipeline.py:~2511`) withholds the volatility rank and both
put/call percentiles until `SELF_BUILT_SERIES_MIN_SESSIONS = 20` (`pipeline.py:198`)
sessions are stored. With 3 stored — really 2, since one is fake — every one of those
metrics is withheld. On the 2026-09-06 run that produced 8 `iv_rank_unavailable` and 8
`skew_unavailable` setup rejections, the two largest causes by a wide margin.

**Do C1 before C2.** A backfill that runs into a contaminated table produces a baseline
that is part real and part synthetic, which is worse than no baseline because it looks fine.

---

## Tasks

- [ ] **C1 — Stop fixture runs writing to the history store, and purge what one already wrote**

  Run 2 was a fixture run — `data_mode: fixture`, artifacts written to a scratchpad
  directory — and it persisted 21 rows of synthetic spot and implied-volatility data into
  `daily_snapshot`. Those rows are indistinguishable from real ones and will feed the
  percentile baseline the moment it warms up.

  Two parts, both required:

  1. **Refuse the write.** The repository must not accept a `daily_snapshot` upsert from a
     run whose `data_mode` is not `live`. Make it a hard refusal at the persistence
     boundary, not a caller-side check — a caller-side check is exactly what failed here.
     Prefer refusing over adding a `data_mode` column and filtering on read: a filter still
     stores the bad data and depends on every future reader remembering to exclude it.
  2. **Purge run 2's rows**, and record in `docs/operations/IV-BACKFILL.md` what was deleted and why.
     Take a copy of `data/briefing.sqlite3` first.

  Note that `briefing_run` already records `data_mode` in its metadata JSON, so the
  information needed to identify contaminated rows exists.

  **Acceptance:**
  - A fixture-mode run persists no `daily_snapshot` row, and this is pinned by a test.
  - The refusal is loud — the run reports it as a diagnostic rather than silently skipping.
  - `select count(*) from daily_snapshot where run_id = 2` returns 0.
  - A live-mode run still persists exactly as before.

- [ ] **C2 — Build the backfill**

  New module `src/briefing_app/backfill.py`, plus a CLI entry point. It replays historical
  option chains into `daily_snapshot` so the 20-session baseline exists.

  `AlphaVantageClient.fetch_historical_options(ticker, run_date=..., option_date=...)`
  already exists (`providers/alpha_vantage.py:169`) and is registered
  (`config/source_registry.yaml:173`, `required_json_paths: ("data",)`).

  **The correctness requirement, which is the entire task.** A backfilled `iv_atm`,
  `pc_ratio_vol` or `pc_ratio_oi` must be produced by *exactly* the same code path as the
  live one. Not an equivalent calculation — the same functions in `options_math.py`, given
  a normalized chain. If the backfill computes at-the-money implied volatility even
  slightly differently (a different strike-selection rule, a different expiry choice, a
  different interpolation), the percentile silently compares two different quantities and
  reports a confident wrong answer. That failure is invisible in the output.

  **Prove it rather than asserting it:** pick a date the live path has already stored
  (2026-09-03 or 2026-09-06), run the backfill for that same date, and assert the
  backfilled values match the stored live values **to full precision**. This is the
  acceptance test. If they do not match, the backfill is wrong and the difference must be
  understood before proceeding — not tolerated.

  **Budget and resumability.** Roughly 360 requests for 18 tickers x 20 sessions, against
  an Alpha Vantage free allowance of 25 per day. The owner has not committed to a paid
  plan, so:
  - The backfill must be **resumable**: re-running it skips (ticker, date) pairs already
    stored and continues where the budget ran out.
  - It must respect the existing `RequestBudget` rather than bypassing it. Spending the
    daily allowance here starves the live run, which needs the same key.
  - It must **report progress** — how many (ticker, date) pairs are stored, how many
    remain, and how many days at the current allowance that implies.
  - Prefer a `--dry-run` that reports the plan and spends nothing.

  **Acceptance:**
  - Backfilling an already-stored live date reproduces the stored values exactly.
  - Interrupting and re-running resumes without duplicating requests.
  - A run that exhausts the budget exits cleanly with a progress report, not an exception.
  - Backfilled rows are marked as backfilled and distinguishable from live rows, so C1's
    contamination problem cannot recur in a new form.

- [ ] **C3 — Verify the baseline actually opens**

  Once enough sessions are stored, `_self_built_baselines` must stop withholding and
  `iv_rank` must become non-null.

  **Acceptance:**
  - A test with 20 stored sessions produces a non-null `iv_rank`, and with 19 does not.
  - The withheld-state message still names the count (`"N of 20 sessions stored"`) — it is
    the only visible progress indicator the owner has.
  - After a real backfill: `select count(*) from daily_snapshot where iv_rank is not null`
    is greater than zero.

- [ ] **C4 — Write `docs/operations/IV-BACKFILL.md`**

  How to run it, how to resume it, what it costs in requests and days at the free
  allowance, the C1 purge record, and — most importantly — **the argument for why a
  backfilled reading is comparable to a live one**, with the reproduction test named. A
  future reader must be able to check that claim rather than trust it.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_backfill.py tests/test_pipeline.py \
    tests/test_storage_repository.py -q
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv --dry-run
```

Back up `data/briefing.sqlite3` before any run that writes.

## Handoff

Report to Lane F: sessions stored per ticker, the reproduction test result (backfilled vs
stored live values), and how many days of free allowance remain to complete the backfill.
