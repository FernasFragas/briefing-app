# Release Plan — briefing-app

Master document for the work between today's state and a shippable local daily briefing.
Lanes run **in parallel in one working tree**, partitioned by exclusive file ownership.

- **Round 1: complete.** Lanes 0 and A–F landed; see [`RESULTS.md`](RESULTS.md).
- **Round 2: complete.** Lanes G–J landed. 6 of 7 round-2 criteria met; items 4 and 15
  were blocked on D12.
- **Round 3: open.** Lanes K–O, at the bottom of this file. Start there.
- **Baseline:** **671 tests passing**, zero failures (verified 2026-09-08).
- **Last live run:** `daily-2026-09-07-f1b0d2e1` — 16 ideas, **0 tradeable**. It reported
  `succeeded` with zero diagnostics while having fetched nothing from three providers.
  **Do not treat that run as a product signal**; see D9. It has not been re-run under the
  corrected status — that is Lane O's task O2.
- **Decisions:** eight from round 1, four (D9–D12) from round 2, four (D13–D16) from
  round 3, all in [`DECISIONS.md`](../docs/architecture/decisions/). Read them before starting any lane. Do not
  re-litigate a decision inside a lane. **D12 is closed by D13** — no backfill is bought
  and none is scheduled.

```bash
PYTHONPATH=src .venv/bin/python -m pytest        # expect 671 passed at baseline
```

> **Reading order for an agent picking this up cold:** [`DECISIONS.md`](../docs/architecture/decisions/), then
> the round-3 section at the bottom of this file, then your own lane document, then
> [`CROSS-LANE.md`](CROSS-LANE.md) for what other lanes have already settled. The round-1
> and round-2 sections in between are **history** — accurate when written, superseded in
> places, and not your instructions.

---

## The working arrangement

**One checkout, one branch, exclusive file ownership.** Every lane below lists the files it
owns. No two lanes own the same file. An agent may **read** anything; it may **write** only
files its own lane lists.

> **This isolation is a convention, not a tool guarantee.** Nothing prevents an agent from
> writing outside its lane, and if one does the loss is silent — another agent's edit is
> simply gone. Before editing any file, confirm it appears in your lane's *Owns* list. If
> the work genuinely needs a file another lane owns, **stop and record it** in
> [`CROSS-LANE.md`](CROSS-LANE.md) rather than editing it.

### Files nobody owns

Off limits to every lane, for the whole of this work:

| File | Why |
|---|---|
| `HANDOFF.md` | Shared history. Updated once, by the integration pass. |
| `tasks/archive/phase-3/todo.md`, `tasks/archive/phase-3/plan.md` | Closed Phase-3 record. Historical; do not amend. |
| `tests/conftest.py` | Shared fixtures. A lane needing a new fixture defines it in its own test file. |
| `provider-alternatives-*.md` | Provider wiring history, unrelated to this work. |
| `docs/architecture/decisions/` | The decision record. Read-only once work starts. |

---

## Lane map

| Lane | Name | Blockers / decisions it closes | Depends on |
|---|---|---|---|
| **0** | [Commit the baseline](archive/round-1/lane-0-baseline.md) | Blocker 7 | — (**must finish first**) |
| **A** | [Grading scale](archive/round-1/lane-a-grading.md) | Decisions 2, 5 | Lane 0 |
| **B** | [Report presentation](archive/round-1/lane-b-report.md) | Blocker 3, decision 6 | Lane 0 |
| **C** | [Volatility history](archive/round-1/lane-c-volatility.md) | Blockers 1, 2 · decision 3 | Lane 0 |
| **D** | [Gates and universe](archive/round-1/lane-d-gates.md) | Blocker 1 · decisions 4, 7 | Lane 0 |
| **E** | [Local operations](archive/round-1/lane-e-operations.md) | Blockers 4, 5, 6 · decision 1 | Lane 0 |
| **F** | [Integration](archive/round-1/lane-f-integration.md) | Final verification | **All of A–E** |

**Lane 0 is a gate.** Nothing starts until the working tree is committed — the parallel
arrangement depends on a clean baseline to diff against, and there are currently ~2,592
uncommitted lines across 29 files plus untracked directories.

**Lanes A–E are fully parallel.** They share no files and no lane blocks another.

---

## Round 2 lane map

Opened 2026-09-07 evening. Round 1 is finished, so every file it owned is free again.

| Lane | Name | Blockers / decisions it closes | Depends on |
|---|---|---|---|
| **G** | [Run health and honest status](archive/round-2/lane-g-run-health.md) | D9 — the silent-success defect | round 1 |
| **H** | [Grade display and thesis disagreement](archive/round-2/lane-h-grade-display.md) | D10, D11 | round 1; coordinates with G |
| **I** | [Free historical options sources](archive/round-2/lane-i-data-sources.md) | D12 (**open**) — research, no code | nothing — **start first** |
| **J** | [Backfill correctness and execution](archive/round-2/lane-j-backfill-execution.md) | D3 execution | J1 now; J3 waits on Lane I |

**G, H, I and J share no files and run in parallel.** Two soft couplings, neither a file
conflict:

- **H needs G's completeness-summary field names** for the run-health banner. Agree them in
  `CROSS-LANE.md` before H builds it; do not read each other's in-progress code.
- **J3 waits on Lane I**, because the provider is not yet chosen. **J1 does not** — the
  correctness test is cheap, gates everything, and is independent of which source wins.
  Start Lane I and J1 immediately.

### What round 2 exists to fix

1. **A run that fetched nothing reported success** (D9 → Lane G). This is the bug that hides
   every other bug: a stalled scheduler, an expired credential and a healthy run are
   currently indistinguishable. Round 1's own verification of "live run clean" was fooled by
   it.
2. **Score and letter now contradict each other on screen** (D10 → Lane H) — `C (100.0)`.
   Predicted by D5, now on every row.
3. **Nine of sixteen rows score exactly zero** (D11 → Lane H) because the declared thesis
   contradicts the data. Correct behaviour, made visible rather than graded away.
4. **The backfill has never actually run** (D12 → Lanes I and J). `iv_rank` is NULL on every
   stored row.

---

## File ownership

Exhaustive. If a file is not listed, no lane may write it without recording the need in
`CROSS-LANE.md` first.

### Lane A — Grading scale
```
src/briefing_app/dashboard/grading.py
tests/test_grading.py
docs/product/SPEC-graded-ideas-report.md
```

### Lane B — Report presentation
```
src/briefing_app/dashboard/build.py
src/briefing_app/dashboard/render.py
src/briefing_app/dashboard/models.py
tests/test_dashboard.py
tests/test_render.py
docs/product/REPORT-LAYOUT.md            (new)
```

### Lane C — Volatility history
```
src/briefing_app/pipeline.py
src/briefing_app/storage.py
src/briefing_app/cli.py
src/briefing_app/backfill.py     (new)
tests/test_pipeline.py
tests/test_storage_repository.py
tests/test_backfill.py           (new)
migrations/004_*.sql             (new, if needed)
docs/operations/IV-BACKFILL.md              (new)
```

### Lane D — Gates and universe
```
src/briefing_app/strategy/engine.py
src/briefing_app/universe/gate.py
src/briefing_app/universe/loader.py
src/briefing_app/config.py
config/universe.example.yaml
config/config.example.yaml
tests/test_gate.py
tests/test_strategy_engine.py
tests/test_loader.py
docs/product/GATE-POLICY.md              (new)
```

### Lane E — Local operations
```
src/briefing_app/api.py
src/briefing_app/delivery.py
tests/test_delivery.py
ops/                             (new directory)
docs/operations/LOCAL-OPS.md                (new)
docker-compose.yml
workflows/
.env.example
```

### Lane F — Integration
```
HANDOFF.md
README.md
tasks/RESULTS.md         (new)
```

---

## File ownership — round 2

Round 1 is finished, so the files it owned are released. These four sets are disjoint from
each other; verified programmatically, no collisions.

### Lane G — Run health
```
src/briefing_app/pipeline.py
tests/test_pipeline.py
tests/test_orchestration.py
docs/architecture/RUN-HEALTH.md                              (new)
```

### Lane H — Grade display
```
src/briefing_app/dashboard/render.py
src/briefing_app/dashboard/build.py
src/briefing_app/dashboard/models.py
tests/test_dashboard.py
tests/test_render.py
docs/product/REPORT-LAYOUT.md
```

### Lane I — Data-source research
```
docs/research/alternatives/historical-options-sources.md (new)
```
Research only. Lane I writes **no source file**. If it concludes a provider should be
wired, that is a new task for a later lane.

### Lane J — Backfill
```
src/briefing_app/backfill.py
src/briefing_app/cli.py
tests/test_backfill.py
docs/operations/IV-BACKFILL.md
```

`tasks/RESULTS.md` stays with Lane F. Lane G corrects item 2 there by handing the
wording over through `CROSS-LANE.md`, unless Lane F has released the file.
`README.md` is withheld from Lanes A, B and E because all three change behaviour it
describes. It is synchronised once, at the end, against what actually shipped.
Lane F may also touch any file A–E own, but **only after all five have finished**.

---

## Definition of done

The release ships when all of the following hold on one live run:

1. Full suite green (`PYTHONPATH=src .venv/bin/python -m pytest`), zero failures.
2. A live run completes `succeeded` with zero failures and zero diagnostics.
3. The ideas table is ordered by grade descending inside each status bucket, and that
   ordering is pinned by a test with more than one row.
4. The volatility baseline reads 20 of 20 stored sessions for every US name, and **no
   fixture-mode row exists in `daily_snapshot`**.
5. `SPY` and `QQQ` appear in market context, not as trading ideas.
6. Every grade in `dashboard.json` recomputes from fields present in the same document.
7. The daily run has fired unattended, on schedule, on three consecutive weekdays.
8. Every counted claim in `README.md` matches what the code actually does.

Record the evidence for each in `tasks/RESULTS.md` (Lane F).

### Round 2 additions

9. A run that reaches no providers reports **`partial`**, names them in its diagnostics, and
   renders a banner. A healthy run still reports `succeeded`. **Both halves must hold** — if
   every run is `partial`, the status is as uninformative as it is today.
10. A warm-up baseline still building does **not** mark a run partial.
11. The report shows conviction and certainty as two labelled measurements, and no reader
    can mistake `C (100.0)` for a contradiction.
12. Every row shows its declared thesis beside the data's reading, and a disagreement is
    explicitly marked.
13. D12 is closed by a written recommendation in
    `docs/research/alternatives/historical-options-sources.md`, including a direct answer on
    `api.quiverquant.com`.
14. A backfilled value reproduces a stored live value **to full precision**, proved by a
    named test.
15. After the backfill, a live run produces at least one setup that was previously rejected
    for want of a volatility rank. This is the only criterion that proves the work delivered
    anything.

---

# Round 3 — opened 2026-09-08

Round 2 is closed (`RESULTS.md`, **671 tests passing, zero failures**, verified 2026-09-08).
Round 3 exists to close the decisions that rounds 1 and 2 deliberately left open, and it
starts from four product decisions the owner took on 2026-09-08: **D13, D14, D15 and D16**
in [`DECISIONS.md`](../docs/architecture/decisions/). Read them before starting any lane. Do not re-litigate a
decision inside a lane.

**D12 is closed by D13.** The answer is not to pay and not to bulk-backfill: the volatility
baseline threshold drops from 20 sessions to 10, with anything below 20 published as
**provisional**. Every round-2 entry that treats D12 as open is superseded.

> ### Re-checked 2026-09-09, before any lane started. Every premise still holds.
>
> ```
> tests collected                     671      unchanged
> SELF_BUILT_SERIES_MIN_SESSIONS       20      unchanged (pipeline.py:215)
> distinct sessions stored              3      unchanged — 09-03, 09-06, 09-07
> rows with iv_rank populated           0      unchanged
> round-3 files created by lanes        0      no lane has started
> ```
>
> **One thing did change: there was no daily run on 2026-09-08 (Tuesday)**, so the store
> gained nothing and item 21's projection slipped a day with no work done.
>
> Read in proportion, this is **one missed weekday, not a pattern.** Runs are recorded for
> 08-30, 08-31, 09-01, 09-02, 09-03, 09-04, 09-06 and 09-07 — eight days in ten, including a
> Sunday — and today's run may still happen. Do not treat it yet as the local-scheduling
> failure D1 warned of.
>
> It still matters, because **item 21 is gated on runs happening, not on code landing.**
> Lowering the threshold to 10 shortens the wait; it does not cause the runs. Lane O task O3
> therefore reports sessions stored **and** weekday runs that occurred, so a stalled cadence
> is never mistaken for a stalled lane.
>
> Two facts that make the projection safer than it looks, both verified 2026-09-09:
> **since round 1's fixture purge, every live run has added exactly one session** (the
> missing 2026-09-04 session was removed by that purge, not lost by a leak); and **a
> degraded run still advances the baseline** — run `daily-2026-09-07-f1b0d2e1` reached none
> of Financial Modeling Prep, Finnhub or Alpha Vantage yet still stored `iv_atm` for most
> names, because the options lead is CBOE, which is keyless and free. The volatility
> baseline does not depend on the contended Alpha Vantage allowance.

## Round 3 lane map

| Lane | Name | Decisions it closes | Live allowance | Depends on |
|---|---|---|---|---|
| **Gate** | Commit the round-3 baseline | — | 0 | — (**must finish first**) |
| **K** | [Volatility baseline threshold](lanes/lane-k-volatility-threshold.md) | D13 (and D12) | 0 | gate |
| **L** | [Report split](lanes/lane-l-report-split.md) | D15, and D11's open consequence | 0 | gate; coordinates with K |
| **M** | [Vendor consistency](lanes/lane-m-vendor-consistency.md) | D14 | 0 Alpha Vantage; MarketData.app permitted | gate |
| **N** | [Live-run budget ledger](lanes/lane-n-live-budget.md) | D16 | 0 | gate |
| **O** | [Verification and integration](lanes/lane-o-verification.md) | closes the round | 1 daily run | **all of K–N** |

**K, L, M and N share no files and run fully in parallel.** One soft coupling, which is not
a file conflict:

- **Lane K needs a field on a model Lane L owns** — the provisional-baseline flag and its
  session count. Agree the names in [`CROSS-LANE.md`](CROSS-LANE.md) before either builds
  against them, exactly as Lane G and Lane H agreed `RunHealth` in round 2. **K proposes,
  L confirms.** Neither reads the other's in-progress code.

### The gate

**Nothing starts until the working tree is committed.** The parallel arrangement depends on
a clean baseline to diff against: without it, "did another lane touch my file?" is
unanswerable. This is the same gate Lane 0 served in round 1 and it is not optional.

**Mostly satisfied as of 2026-09-09.** Everything under `src/`, `tests/`, `config/` and
`ops/` is committed — `94b1e7f` is the head. What remains uncommitted is documentation and
planning only:

```
 M HANDOFF.md  README.md  docs/product/SPEC-graded-ideas-report.md
 M tasks/release/{CROSS-LANE,DECISIONS,README}.md
 M workflows/*
?? docs/{IV-BACKFILL,REPORT-LAYOUT}.md  docs/research/alternatives/historical-options-sources.md
?? tasks/RESULTS.md  tasks/release/lane-{g,h,i,j,k,l,m,n,o}-*.md
```

Commit those as the round-3 baseline, run the suite, and record the commit hash and the test
count in `CROSS-LANE.md`. **The source tree is already clean, so lanes K–N can be started as
soon as that commit exists** — none of them is blocked on a code change landing first.

## File ownership — round 3

Exhaustive and verified disjoint. If a file is not listed, no lane may write it without
recording the need in `CROSS-LANE.md` first.

### Lane K — Volatility baseline threshold
```
src/briefing_app/pipeline.py
src/briefing_app/config.py
config/config.example.yaml
tests/test_pipeline.py
tests/test_orchestration.py
docs/architecture/RUN-HEALTH.md
docs/architecture/VOLATILITY-BASELINE.md      (new)
```

### Lane L — Report split
```
src/briefing_app/dashboard/build.py
src/briefing_app/dashboard/render.py
src/briefing_app/dashboard/models.py
tests/test_dashboard.py
tests/test_render.py
docs/product/REPORT-LAYOUT.md
```

### Lane M — Vendor consistency
```
src/briefing_app/backfill.py
src/briefing_app/cli.py
tests/test_backfill.py
tests/test_vendor_gap.py                        (new)
ops/measure_vendor_gap.py                       (new)
docs/operations/IV-BACKFILL.md
docs/research/alternatives/vendor-consistency.md         (new)
```

### Lane N — Live-run budget ledger
```
ops/live_budget.py                    (new)
ops/status.py
tests/test_ops_scripts.py
docs/operations/LIVE-RUN-BUDGET.md               (new)
tasks/BUDGET-LEDGER.md        (new)
```

### Lane O — Verification and integration
```
tasks/RESULTS.md
tasks/README.md
README.md
HANDOFF.md
```

Lane O may also touch any file K–N own, **but only after all four have finished.**

### Files nobody owns in round 3

Off limits to every lane, for the whole round:

| File | Why |
|---|---|
| `src/briefing_app/dashboard/grading.py` | **Locked by D15.** D11 forbids resolving the tied-zero block by changing a grade; locking the file enforces it rather than trusting it. |
| `src/briefing_app/storage.py` | Read by three lanes, owned by none. A schema change is a `CROSS-LANE.md` entry. |
| `src/briefing_app/strategy/engine.py` | Round 3 changes no gate and no setup rule. |
| `tests/conftest.py` | Shared fixtures. A lane needing a new one defines it in its own test file. |
| `docs/architecture/decisions/` | The decision record. Read-only once work starts. |
| `tasks/CROSS-LANE.md` | Append-only. Never edit or delete another lane's entry. |
| `tasks/archive/phase-3/todo.md`, `tasks/archive/phase-3/plan.md` | Closed Phase-3 record. Historical; do not amend. |
| `ops/run_daily.py`, `ops/install_launchd.py`, `ops/serve_api.py`, `ops/audit_dashboard.py` | Working operational scripts, unrelated to this round. |

## Definition of done — round 3

Items 1 to 15 stand, with three restatements below. Round 3 adds items 16 to 21.

16. `iv_rank`, the put/call volume percentile and the put/call open-interest percentile all
    publish at **10** stored sessions and are withheld below it. All three boundaries — 9
    withholds, 10 publishes, 20 settles — are pinned by tests, **for each of the three
    legs**.
17. A percentile computed on fewer than 20 sessions is marked **provisional**, carrying the
    session count it was computed over, in the stored row, in `dashboard.json` **and** on
    the rendered page. Each of the three is pinned by a test.
18. The ideas table renders **two headed sections** — theses the data supports, and theses
    the data contradicts — with every published idea in exactly one of them, asserted by a
    test. Ordering by conviction inside the supported section is still pinned by a
    multi-row test, and items 11 and 12 still hold.
19. A **measured** cross-vendor gap for `pc_ratio_vol` and `pc_ratio_oi` is recorded in
    `docs/research/alternatives/vendor-consistency.md`, with the requests that produced it and the
    code path used. The implied-volatility procedure is written, carries a decision rule
    fixed in advance, and is explicitly marked **unexecuted**, with the reason.
20. No lane spent a provider request that was not claimed in
    `tasks/BUDGET-LEDGER.md` first, and the daily briefing's reservation held on
    every day of round 3.
21. **The one criterion that proves round 3 delivered something visible.** Once 10 sessions
    are stored, a live run produces at least one setup that was previously rejected for
    want of a volatility rank. Expected about 7 weekday runs after Lane K lands, so it
    closes after the code does; record it as open with a date until it is met.

### Restatements

- **Item 4** — "the volatility baseline reads 20 of 20 stored sessions for every US name"
  is replaced by: readings publish at 10 sessions and are marked provisional below 20, per
  item 16 and item 17. The second half is unchanged and still required: **no fixture-mode
  row exists in `daily_snapshot`.**
- **Item 7** — "the daily run has fired unattended, on schedule, on three consecutive
  weekdays" is replaced by: **three weekday runs recorded, launched by hand.** The owner
  declined the `launchd` scheduler in order to keep the shared 25-request allowance under
  manual control. This is a scope decision that was taken, not a gap that was tolerated.
- **Item 15** is superseded by item 21, restated against the 10-session threshold.

Record the evidence for each in `tasks/RESULTS.md` (Lane O). **Evidence is a command
and its output.** Round 1 recorded item 2 as passed on a status that could not fail; that is
the standard this round is held against.
