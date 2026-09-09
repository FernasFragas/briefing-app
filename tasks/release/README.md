# Release Plan — briefing-app

Master document for the work between today's state and a shippable local daily briefing.
Five lanes run **in parallel in one working tree**, partitioned by exclusive file ownership.

- **Baseline:** 611 tests passing, zero failures (verified 2026-09-07, full suite).
- **Last live run:** `daily-2026-09-06-e270378b` — 18 ideas, 1 tradeable, 0 diagnostics.
- **Decisions:** all eight settled 2026-09-07, recorded in [`DECISIONS.md`](DECISIONS.md).
  Read that file before starting any lane. Do not re-litigate a decision inside a lane.

```bash
PYTHONPATH=src .venv/bin/python -m pytest        # expect 611 passed at baseline
```

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
| `tasks/todo.md`, `tasks/plan.md` | Closed Phase-3 record. Historical; do not amend. |
| `tests/conftest.py` | Shared fixtures. A lane needing a new fixture defines it in its own test file. |
| `provider-alternatives-*.md` | Provider wiring history, unrelated to this work. |
| `tasks/release/DECISIONS.md` | The decision record. Read-only once work starts. |

---

## Lane map

| Lane | Name | Blockers / decisions it closes | Depends on |
|---|---|---|---|
| **0** | [Commit the baseline](lane-0-baseline.md) | Blocker 7 | — (**must finish first**) |
| **A** | [Grading scale](lane-a-grading.md) | Decisions 2, 5 | Lane 0 |
| **B** | [Report presentation](lane-b-report.md) | Blocker 3, decision 6 | Lane 0 |
| **C** | [Volatility history](lane-c-volatility.md) | Blockers 1, 2 · decision 3 | Lane 0 |
| **D** | [Gates and universe](lane-d-gates.md) | Blocker 1 · decisions 4, 7 | Lane 0 |
| **E** | [Local operations](lane-e-operations.md) | Blockers 4, 5, 6 · decision 1 | Lane 0 |
| **F** | [Integration](lane-f-integration.md) | Final verification | **All of A–E** |

**Lane 0 is a gate.** Nothing starts until the working tree is committed — the parallel
arrangement depends on a clean baseline to diff against, and there are currently ~2,592
uncommitted lines across 29 files plus untracked directories.

**Lanes A–E are fully parallel.** They share no files and no lane blocks another.

---

## File ownership

Exhaustive. If a file is not listed, no lane may write it without recording the need in
`CROSS-LANE.md` first.

### Lane A — Grading scale
```
src/briefing_app/dashboard/grading.py
tests/test_grading.py
docs/SPEC-graded-ideas-report.md
```

### Lane B — Report presentation
```
src/briefing_app/dashboard/build.py
src/briefing_app/dashboard/render.py
src/briefing_app/dashboard/models.py
tests/test_dashboard.py
tests/test_render.py
docs/REPORT-LAYOUT.md            (new)
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
docs/IV-BACKFILL.md              (new)
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
docs/GATE-POLICY.md              (new)
```

### Lane E — Local operations
```
src/briefing_app/api.py
src/briefing_app/delivery.py
tests/test_delivery.py
ops/                             (new directory)
docs/LOCAL-OPS.md                (new)
docker-compose.yml
workflows/
.env.example
```

### Lane F — Integration
```
HANDOFF.md
README.md
tasks/release/RESULTS.md         (new)
```
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

Record the evidence for each in `tasks/release/RESULTS.md` (Lane F).
