# Lane G — Run health and honest status

**Implements:** D9. **Closes:** the silent-success defect.
**Depends on:** round 1 complete (it is — `RESULTS.md` exists). Runs in parallel with H, I, J.

## Owns — write only these

```
src/briefing_app/pipeline.py
tests/test_pipeline.py
tests/test_orchestration.py
docs/architecture/RUN-HEALTH.md               (new)
```

## Must not touch

`storage.py` — `finish_briefing_run` already accepts a status and needs no change.
`backfill.py` and `cli.py` (Lane J). `dashboard/` (Lane H).

---

## The defect, precisely

`_final_status` (`pipeline.py:2930`):

```python
def _final_status(output: PipelineRunOutput) -> str:
    if output.failures or output.diagnostics:
        return STATUS_PARTIAL
    return STATUS_SUCCEEDED
```

The rule itself is fine. The problem is what reaches `output.diagnostics`: only load
warnings and errors (`:499`, `:500`), a `setup_rules` exception (`:608`), and a pipeline
exception (`:679`). Meanwhile per-ticker problems accumulate in a local `issues` list with
**44 recording points** (`grep -n "issues.append" src/briefing_app/pipeline.py`) and are
never escalated.

Consequence, on run `daily-2026-09-07-f1b0d2e1`: zero requests to three providers, no raw
cache written, every name stripped of price closes and sentiment, whole universe floored to
the bottom tier, nothing tradeable — reported `succeeded`, 0 failures, 0 diagnostics.

Confirm it yourself before changing anything:

```bash
ls data/provider_budget/fmp/          # stops at 2026-09-06
ls data/raw/2026-09-07/               # does not exist
```

---

## Tasks

- [ ] **G1 — Classify issues by severity. This is the whole task, not a preliminary.**

  D9 records the risk the owner accepted: escalate everything and `partial` becomes the new
  constant, carrying exactly as little information as `succeeded` does today. You must
  prevent that.

  Go through all 44 recording points and assign each to a severity. The dividing line:

  | Severity | Meaning | Marks the run |
  |---|---|---|
  | **normal** | An expected condition of a healthy system | no |
  | **degraded** | Real data is missing and the output is weaker for it | **partial** |
  | **outage** | A source that should have answered was never reached | **partial**, prominently |

  Worked examples, so the line is not ambiguous:
  - `iv rank baseline still building: 3 of 20 sessions stored` → **normal.** This is the
    warm-up working as designed and will be true every day for two weeks. It must not mark
    a run partial.
  - `no measured sigma from real closes` → **degraded.** Price history genuinely failed and
    every downstream number is worse.
  - A provider with no budget record for the run date → **outage.**

  Do not guess at a rule and apply it in bulk. Each of the 44 needs a deliberate answer,
  and the table belongs in `docs/architecture/RUN-HEALTH.md` where it can be argued with.

  **Acceptance:** every recording point has a severity; the table is in the document; a
  test asserts that a warm-up-only run is `succeeded` and a missing-prices run is `partial`.

- [ ] **G2 — Escalate degraded and outage issues to run diagnostics**

  Per-ticker issues at `degraded` or `outage` reach `output.diagnostics`, which makes
  `_final_status` return `partial` through the rule that already exists. Do not write a
  second status rule.

  Aggregate rather than flooding: eighteen names each missing prices is **one** diagnostic
  naming the eighteen, not eighteen diagnostics. A diagnostics list nobody can read is the
  same failure in a new costume.

  **Acceptance:**
  - A run with no reachable providers reports `partial` with a diagnostic naming them.
  - A fully healthy run still reports `succeeded` — verify this, or you have simply moved
    the constant.
  - Diagnostics are aggregated, not one per ticker per issue.

- [ ] **G3 — Detect the total-outage case explicitly**

  The 09-07 signature is distinctive and worth naming on its own: **no budget record and no
  raw cache entry for the run date, for providers that should have been called.** That is
  categorically different from partial degradation and should say so.

  This does not fail the run — D9 chose to keep the data — but it must be unmissable in the
  diagnostics and in the report banner Lane H renders.

  **Acceptance:** a run where no provider was reached produces a distinct, clearly worded
  diagnostic; a run where one of five providers failed does not produce it.

- [ ] **G4 — Publish a completeness summary on the run output**

  So the banner Lane H renders has something to read, and so "was today's run any good?" is
  answerable without opening the report. At minimum: components scored out of components
  defined, names scored out of names gated, and which providers answered.

  **Coordinate with Lane H on the field names before you build it** — Lane H consumes this
  and owns the rendering. Agree the shape in `CROSS-LANE.md` rather than each guessing.

  **Acceptance:** the summary is on the run output and in the saved status file; Lane H has
  confirmed the field names in `CROSS-LANE.md`.

- [ ] **G5 — Re-verify definition-of-done item 2**

  Round 1's `RESULTS.md` marks "live run clean" as **Passed**, citing
  `status=succeeded, failures=0, diagnostics=0` on the very run that had fetched nothing.
  That verification was reading a status that could not fail.

  Once G1–G3 land, re-run and record the truthful status. **Expect `partial`** — that is
  the correct answer for the current data situation, and recording it honestly is the point
  of this lane.

  **Acceptance:** `RESULTS.md` item 2 is corrected, with the reason it was wrong. (Note
  `RESULTS.md` belongs to Lane F — hand the wording over via `CROSS-LANE.md` rather than
  editing it, unless Lane F has finished and released the file.)

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_pipeline.py tests/test_orchestration.py -q
PYTHONPATH=src .venv/bin/python -m pytest -q        # expect 641+ passing, zero failures
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --data-mode live --force
```

The live run should now report `partial`, and the diagnostics should name exactly what is
missing. If it still reports `succeeded`, this lane has not worked.

## Handoff

Report to Lane H: the completeness-summary field names. Report to the owner: the severity
table, and the honest status of the first run under the new rule.
