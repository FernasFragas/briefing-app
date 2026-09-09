# Lane A — Grading scale

**Implements:** D2 (ALIGN), D5 (score ceiling).
**Depends on:** Lane 0 only. Runs in parallel with B, C, D, E.

## Owns — write only these

```
src/briefing_app/dashboard/grading.py
tests/test_grading.py
docs/SPEC-graded-ideas-report.md
```

## Must not touch

`dashboard/build.py` and `dashboard/render.py` (Lane B) — even though they consume grades.
`config.py` (Lane D). If a change here requires either, record it in `CROSS-LANE.md`.

> **Note on `ReportGradingSettings`.** Under ALIGN, `probability_weight`,
> `alignment_weight` and `directional_probability_weight` all stop being read. **Leave the
> config fields in place and simply stop consulting them.** Removing them means editing
> `config.py`, which Lane D owns, and would break the loader tests Lane D also owns. Note
> the fields as unused in the spec; a later cleanup can remove them in one place.

---

## Background you need before editing

`compute_grade` (`grading.py:178`) currently computes:

```
raw   = 100 * (probability_weight * P + alignment_weight * alignment)
grade = min(max(raw - penalties, 0), tier_ceiling)
```

with weights selected by band: `0.20 / 0.80` for `above spot` and `below spot`,
`0.60 / 0.40` otherwise (`_effective_weights`, line 268).

D2 removes the probability term. D5 addresses the ceiling. Read `DECISIONS.md` for the
measured evidence — in particular the refinement under D5, which **this lane owns and must
either implement or reject in writing.**

---

## Tasks

- [ ] **A1 — Grade on alignment alone**

  `raw = 100 * alignment`, for both branches. The probability term is gone.

  `alignment()` itself is **unchanged** — both branches already return conviction units in
  0…1 and that work (G2/G2b) was correct. Do not touch `DIRECTIONAL_FULL_CONVICTION`.

  Keep computing and returning `thesis_probability` and `thesis_band` on `GradeResult`: the
  report still prints them as context. Only their contribution to `score` is removed.
  `probability_weight` and `alignment_weight` on `GradeResult` should report what was
  actually applied (0.0 and 1.0), not what config says.

  **A missing probability must no longer produce an unscored result.** Today
  `compute_grade` returns `score=None` when `thesis.probability is None`, because the
  report named `P(thesis band)` as an input. Under ALIGN it is not an input, so a row with
  a usable `S_CTE` and no scenario table **can and should** be graded. A missing `s_cte`
  still produces `score=None` — that has not changed.

  **Acceptance:**
  - `compute_grade` with `P = 0.95, S_CTE = 0.0, direction = long` scores 0.0, not 19.0.
  - A setup with `scenario_table = None` and a usable `S_CTE` returns a real score, and its
    `reasons` records that no probability was available for display.
  - A setup with `s_cte = None` still returns `score=None` with reason `NO_S_CTE`.
  - Every one of the ten `SetupType` values still maps to a thesis band for display.

- [ ] **A2 — Decide the ceiling mechanism (D5), then implement it**

  Read the refinement block under D5 in `DECISIONS.md` first. The measured position:

  | Row | Tier | raw under ALIGN | clamped today |
  |---|---|---|---|
  | ORCL | B | 93.1 | 81.0 |
  | AMAT | B | 84.5 | 81.0 |
  | INTC | B | 83.6 | 81.0 |
  | SPY | C | 79.0 | 57.0 |
  | MSFT | B | 64.6 | 64.6 |

  Scaling the letter bands by 0.81 **is measurably wrong**: it makes ORCL, AMAT and INTC
  read `A+` while all three are Tier B, and makes SPY read `B` while it is Tier C. That is
  the exact outcome `_TIER_CEILINGS` exists to prevent.

  The recommended mechanism is a **letter cap**: stop clamping the score, and cap the
  *displayed letter* instead — Tier A uncapped, Tier B at `B+`, Tier C at `C`. The score
  keeps full resolution so ranking works (93.1 / 84.5 / 83.6 rather than a three-way tie),
  and no Tier B row can present as an `A`.

  Whichever you choose, these properties are **binding** and must each have a test:
  - A Tier C row cannot display a letter above `C`. This is the single rule the design
    exists to enforce and it predates this lane.
  - A Tier B row cannot display a letter above `B+`.
  - Two rows with different conviction do not produce the same score.

  Then decide whether the letter bands still need re-cutting. Under the letter-cap
  mechanism the score range returns to 0–100 and the existing bands
  (`A+ 90 / A 82 / B+ 74 / B 66 / C+ 58 / C 50 / D 35 / F 0`) may need no change at all —
  verify against the real rows rather than assuming.

  **Known consequence to resolve and write down:** under a letter cap the score column and
  the letter column can disagree on ordering — SPY at 79.0 displays `C` while MSFT at 64.6
  displays `B+`. After D6 removes SPY and QQQ from the ideas table every remaining row on
  the 2026-09-06 run is Tier B and shares one cap, so it does not arise today. Decide what
  should happen when it does, and record the decision in the spec.

  **Acceptance:** the three binding properties above each have a test; the chosen mechanism
  and the ordering consequence are both written into
  `docs/SPEC-graded-ideas-report.md`.

- [ ] **A3 — Re-pin every test that asserts an old grade number**

  `tests/test_grading.py` pins band boundaries on both sides (34/35, 49/50, 57/58, 65/66,
  73/74, 81/82, 89/90), all three ceilings, all ten setup types, and both penalties. Every
  assertion resting on the probability term needs recomputing by hand — not by running the
  code and pasting the output, which pins the bug rather than the intent.

  Add a regression test for each finding in D2, using the real values:
  - A neutral row with `s_cte = 0.208` (past the 0.15 band) scores **0.0**. It used to
    score 41.0. This is JPM, and it is the defect the whole decision was taken on.
  - A directional row with `P = 0.95` gets no benefit from `P` at all.

  **Acceptance:** `pytest tests/test_grading.py -q` passes, and the JPM case is present by
  name in a test docstring so the reason survives.

- [ ] **A4 — Update the specification**

  `docs/SPEC-graded-ideas-report.md` is the authoritative description and is currently
  wrong in three ways once A1 lands:
  - The grade formula and both weight splits.
  - The stated principle that the grade is *never* inferred from `S_CTE` alone, "because
    the report names `P(thesis band)` as an input". **D2 reverses this deliberately.**
    Record it as a reversal with its reason, not as a silent edit — a future reader must be
    able to see the principle was considered and overturned on evidence.
  - The band and ceiling tables, per A2.

  Also record that `probability_weight`, `alignment_weight` and
  `directional_probability_weight` remain in config but are no longer read.

  **Acceptance:** an engineer reading only the spec can recompute any grade in
  `dashboard.json` and reach the published number.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_grading.py -q
PYTHONPATH=src .venv/bin/python -m pytest -q        # nothing else may break
```

Lane B owns the report and will re-verify that grades render and sort correctly. **Do not
run a live run from this lane** — Lane F does that once, after every lane has landed.

## Handoff

Report to Lane F: the chosen ceiling mechanism, the final band table, and whether any test
outside `tests/test_grading.py` failed as a result of this lane (it should not — if one
did, that is a coupling Lane B needs to know about).
