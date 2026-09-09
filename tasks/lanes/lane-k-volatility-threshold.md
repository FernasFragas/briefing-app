# Lane K — Volatility baseline threshold

**Implements:** D13. **Closes:** D12, and definition-of-done items 4 and 16/17.
**Depends on:** the round-3 baseline commit (gate). Runs in parallel with L, M, N.
**Live request allowance:** **0.** This lane is fixture-mode only. See D16.

## Owns — write only these

```
src/briefing_app/pipeline.py
src/briefing_app/config.py
config/config.example.yaml
tests/test_pipeline.py
tests/test_orchestration.py
docs/architecture/RUN-HEALTH.md
docs/architecture/VOLATILITY-BASELINE.md      (new)
```

`tests/test_orchestration.py` is yours because it asserts on the
`... baseline still building: N of M sessions stored` message you are about to reword.
`tests/test_dashboard.py` asserts on it too and belongs to **Lane L** — tell Lane L in
`CROSS-LANE.md` what the new wording is, do not edit it yourself.

## Must not touch

- `src/briefing_app/dashboard/**` — Lane L. You will need a new field to reach the report;
  **agree its name in `CROSS-LANE.md` and let Lane L add it.** Do not edit `models.py`.
- `src/briefing_app/backfill.py`, `cli.py` — Lane M.
- `src/briefing_app/dashboard/grading.py` — **owned by nobody this round**, by design
  (D15). No grade may change as a result of this lane.
- `ops/**` — Lane N.

---

## Where this actually stands

Read from the live store on 2026-09-08, before any work:

```
daily_snapshot rows:              59
distinct sessions stored:          3     (2026-09-03, 2026-09-06, 2026-09-07)
rows with iv_atm populated:       51
rows with iv_rank populated:       0
```

The constant that withholds the readings is `SELF_BUILT_SERIES_MIN_SESSIONS = 20` at
`pipeline.py:215`, consumed at `pipeline.py:2762-2775`. Read that block before you start —
**it gates three legs, not one**:

```python
for name, series in (
    ("iv_rank", iv_history),
    ("put/call volume percentile", pc_vol_history),
    ("put/call open-interest percentile", pc_oi_history),
):
    if len(series) < SELF_BUILT_SERIES_MIN_SESSIONS:
        issues.append(
            f"{name} baseline still building: {len(series)} of "
            f"{SELF_BUILT_SERIES_MIN_SESSIONS} sessions stored"
        )
        result.append(withheld)
```

At 3 sessions stored, a threshold of 20 is 17 more weekday runs away. A threshold of 10 is
**7 more weekday runs** away. That is the entire point of the change.

> ### The trap this lane exists to avoid
>
> Lowering a constant is a two-line change and would take ten minutes. **That is not the
> task.** A percentile computed over 10 observations resolves only to the nearest tenth:
> "IV rank 80" means "second highest of ten" and nothing finer. If a 10-session reading is
> published looking identical to a 20-session one, this lane will have converted a
> deliberate, accepted trade-off into a silent misrepresentation — which is the exact
> failure this project has already corrected twice (the silent `succeeded` status in D9,
> and the fixture rows in `daily_snapshot` in round 1).
>
> **The provisional marking is the deliverable. The constant is the trivia.**

---

## Tasks

- [ ] **K1 — Replace the single threshold with two, and make both configurable**

  One constant currently means two different things: "enough data to say anything at all"
  and "enough data to be trusted". Separate them.

  - `min_sessions` — the floor below which a percentile is **withheld entirely**. Set to
    **10** by D13.
  - `full_sessions` — the count at or above which a percentile is a **settled** reading.
    Stays **20**.
  - Between the two, the percentile **is computed and published, marked provisional.**

  Put both in `config.py` alongside the existing settings, surface them in
  `config/config.example.yaml` with a comment explaining what the two numbers mean and why
  they differ, and keep `SELF_BUILT_SERIES_MIN_SESSIONS` working as the default for
  `min_sessions` so nothing that imports it breaks. Lane M reads that name from `pipeline.py`
  and must not have to change.

  **Acceptance:** a test asserting all three boundaries on the same fixture — 9 sessions
  withholds, 10 sessions publishes-as-provisional, 20 sessions publishes-as-settled — for
  **each of the three gated legs**, not just `iv_rank`. The other two are the reason the
  change is worth making; a test that covers only `iv_rank` has tested a third of the work.

- [ ] **K2 — Make the provisional state a fact on the record, not a rendering choice**

  A downstream reader must be able to tell a 10-session percentile from a 20-session one
  **without recomputing it**. Carry, next to each of the three percentile readings:

  - whether it is provisional, and
  - the number of sessions it was computed over.

  Put it wherever the reading itself already travels, so it reaches `daily_snapshot`,
  the run output and `dashboard.json` by the same route the number does. Do not invent a
  parallel channel.

  > **Cross-lane, and it is the one coordination point in this lane.** The field must land
  > on a model in `dashboard/models.py`, which **Lane L owns**. Follow exactly the
  > precedent set by the Lane G ↔ Lane H `RunHealth` exchange in `CROSS-LANE.md`: **Lane K
  > proposes the names and semantics there, Lane L confirms and adds the field.** Do not
  > edit `models.py`, and do not read Lane L's in-progress code. `models.py` is
  > `extra="forbid"`, so an unagreed field will fail loudly rather than silently — which is
  > the good outcome, but only if you have not already built against it.

  **Acceptance:** the entry exists in `CROSS-LANE.md`, Lane L has confirmed it, and a test
  asserts the session count and provisional flag are present and correct on a run whose
  store holds between `min_sessions` and `full_sessions` sessions.

- [ ] **K3 — Decide, and write down, whether a provisional reading affects source quality**

  This is a judgement call and it belongs to this lane. `components/base.py` grades source
  quality on `QUALITY_NONE / AGGREGATOR / MANUAL / PRIMARY`, and the weakest link decides
  the component (`worst_quality`, `base.py:72`), which in turn drives the Tier A/B/C badge.

  The question: **does a provisional percentile degrade `S_O`'s source quality, or is it
  full quality with a marker?** Both are defensible. Degrading it makes the tier badge tell
  the truth about a weaker input; not degrading it keeps the badge measuring *provenance*
  rather than *sample size*, which is what it has meant until now, and avoids a tier change
  landing in the same release as a layout change.

  **Whichever you choose, the requirement is the same: choose deliberately and record the
  reasoning in `docs/architecture/VOLATILITY-BASELINE.md`.** What is not acceptable is discovering the
  answer by observing what the code happens to do.

  **Constraint:** if you degrade quality, verify the effect on the tier distribution and
  say what it is. A change that silently moves every row down a tier is a product change
  wearing a technical disguise, and it belongs in `CROSS-LANE.md` before it ships.

- [ ] **K4 — Keep the run-health classification honest**

  Lane G classified all 36 `issues.append` recording points as `normal` / `degraded` /
  `outage` in `pipeline.py::_issue_severity`, tabulated the result in `docs/architecture/RUN-HEALTH.md`,
  and pinned the table with a test **that fails when `pipeline.py` grows an unclassified
  recording point**. You are about to change the wording of one of those points and may add
  others.

  - `... baseline still building: N of M sessions stored` stays `normal`. D9 is explicit:
    a warm-up must not mark a run `partial`. Do not change that.
  - A **provisional** reading is also `normal`. It is a published reading, not a failure.
  - Update the table in `docs/architecture/RUN-HEALTH.md` to match whatever the messages now say, and
    confirm the pinning test still passes for the right reason.

  **Acceptance:** the run-health test passes, and `docs/architecture/RUN-HEALTH.md` describes the new
  message wording rather than the old.

- [ ] **K5 — Write `docs/architecture/VOLATILITY-BASELINE.md`**

  The reference for what these numbers mean. It must answer, for a reader who has not read
  this plan:

  1. Why three legs are gated by one rule, and which three.
  2. What "provisional" means numerically — that a percentile over `n` observations
     resolves to `1/n`, so at 10 sessions the finest distinction available is a decile.
  3. Why 10 and not 20, with D13's arithmetic: 3 sessions stored, 7 more weekday runs to
     10, 17 to 20.
  4. The honest limitation, stated once and plainly: ten sessions is about two calendar
     weeks and may not span a single volatility regime.
  5. Where the flag appears — stored row, `dashboard.json`, page — and the name of the test
     that pins each.

- [ ] **K6 — Report completion in `CROSS-LANE.md`**

  One entry, `Type: completion`, naming the files written and the test count before and
  after. Lane O cannot verify item 16 without it.

---

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_pipeline.py -q
PYTHONPATH=src .venv/bin/python -m pytest                          # expect >= 671 passed
```

Confirm the store state you are reasoning about has not moved under you:

```bash
.venv/bin/python -c "
import sqlite3; c = sqlite3.connect('data/briefing.sqlite3')
print('sessions:', c.execute('select count(distinct snap_date) from daily_snapshot').fetchone()[0])
print('iv_rank set:', c.execute('select count(*) from daily_snapshot where iv_rank is not null').fetchone()[0])
"
```

## Done when

- The three boundary cases (9 / 10 / 20) are pinned by tests for all three gated legs.
- A provisional reading is identifiable from the stored row and from `dashboard.json`
  without recomputation.
- `docs/architecture/VOLATILITY-BASELINE.md` exists and answers all six questions in K5.
- The run-health table matches the code and its pinning test passes.
- The full suite is green and no grade in `dashboard/grading.py` changed.
