# Lane L — Report split: supported and contradicted theses

**Implements:** D15. **Closes:** the consequence D11 left open, and definition-of-done
item 18.
**Depends on:** the round-3 baseline commit (gate). Runs in parallel with K, M, N.
**Live request allowance:** **0.** This lane is fixture-mode only. See D16.

## Owns — write only these

```
src/briefing_app/dashboard/build.py
src/briefing_app/dashboard/render.py
src/briefing_app/dashboard/models.py
tests/test_dashboard.py
tests/test_render.py
docs/product/REPORT-LAYOUT.md
```

## Must not touch

- **`src/briefing_app/dashboard/grading.py` — owned by nobody this round, deliberately.**
  D11 forbids fixing the tied-zero block by changing the grade, and D15 restates it. This
  lane is presentation only. If you believe a grading change is required, **stop and write
  it in `CROSS-LANE.md`**; do not make it.
- `src/briefing_app/pipeline.py`, `config.py` — Lane K.
- `src/briefing_app/backfill.py`, `cli.py` — Lane M.
- `ops/**` — Lane N.

---

## Where this actually stands

On the last live run, 16 rows reached the ideas table. **Nine of them score exactly 0.0**,
so more than half the table carries no ranking information at all and is ordered
arbitrarily within itself.

This is not a bug and you must not treat it as one. The grade measures how far the evidence
supports **the direction declared for that name in `config/universe.example.yaml`** —
`strategy/engine.py:1210` takes `direction=evaluation.candidate.direction`. GOOGL is
declared `long` with the thesis "Regulatory decision event directional"; its composite
signal reads `neutral` at −0.094. Scoring support for the *stated* direction correctly
returns 0.0.

D11 called this "the tool falsifying your declared theses, and arguably the most valuable
thing it does", made the disagreement visible, and explicitly left one problem open:
**"mildly unsupported" and "the data says the opposite" both render as 0.0 and are
indistinguishable.** D15 closes that by layout.

---

## What D15 decided, precisely

The single ranked table becomes **two clearly headed sections**:

1. **Theses the data supports** — ranked as now, by conviction descending.
2. **Theses the data contradicts** — listed, each with the direction declared and the
   reading the composite signal actually produced.

Nothing about the grade changes. A row's section is determined by facts already published
on it (`posture` and `composite_score` reached `TradingIdeaRow` in round 2), not by a new
computation.

**The costs the owner accepted, so you do not need to re-litigate them:** the single sorted
ladder round 1 established is gone; a name may move between sections day to day; and this
is a second layout change to a report Lane H only just finished.

---

## Tasks

- [ ] **L1 — Confirm Lane K's provisional-baseline field before building anything on it**

  Lane K (D13) is lowering the volatility baseline threshold from 20 sessions to 10, and a
  percentile computed on fewer than 20 sessions must be published **marked provisional**,
  carrying the session count it was computed over. That flag has to land on a model in
  `models.py`, **which you own**.

  Lane K proposes the names and semantics in `CROSS-LANE.md`; **you confirm there and add
  the field.** Follow the Lane G ↔ Lane H `RunHealth` exchange in that file as the
  precedent — it worked, and it worked because the shape was agreed in writing before
  either side built against it. Do not read Lane K's in-progress code.

  `models.py` is `extra="forbid"`. That is deliberate: an unagreed field fails loudly. Do
  not relax it.

- [ ] **L2 — Split the ideas table into the two sections**

  Both `build.py` (which decides what is in the payload) and `render.py` (which decides how
  it reads). Requirements:

  - **Every published idea appears in exactly one section.** No row in both; no row in
    neither. Assert it — a row silently dropped by a partition bug is the worst possible
    outcome here and it is invisible on a page you are already expecting to look different.
  - The partition is derived from data already on the row. Do not recompute a grade, a
    posture or a composite score to decide a section.
  - **Ordering by conviction descending is preserved inside the supported section**, and
    stays pinned by a test with **more than one row** (definition-of-done item 3, from
    round 1 — do not weaken it).
  - The contradicted section shows, per row, the declared direction and the data's reading,
    so the disagreement is legible without cross-referencing another part of the page.
  - Section headings say what the section means in plain words. A reader who has never seen
    this report should understand "theses the data contradicts" from the heading alone.
  - `dashboard.json` reflects the split too, not only the HTML. The JSON is what
    `ops/audit_dashboard.py` reads and what any future consumer reads.

- [ ] **L3 — Do not break what round 2 verified**

  Three round-2 criteria are pinned by named tests that pass today. After the re-layout each
  must still hold, proved by the same test or by a strictly stronger replacement — never by
  deleting one:

  | Criterion | Pinning test |
  |---|---|
  | 11 — conviction and certainty legible as two labelled measurements | `tests/test_render.py::test_dashboard_html_explains_and_renders_conviction_and_certainty_separately` |
  | 12 — declared thesis shown beside the data's reading, disagreement marked | `tests/test_render.py::test_dashboard_html_marks_only_theses_that_disagree_with_the_data_reading` |
  | 3 — ordering by conviction inside a bucket | the round-1 multi-row ordering test in `tests/test_render.py` |

  If a replacement is genuinely better, say in one line in `docs/product/REPORT-LAYOUT.md` what it
  asserts that the old one did not.

  **A note on criterion 12 that will bite you.** With a whole section now meaning
  "contradicted", a per-row disagreement marker may look redundant. It is not: the marker is
  what makes a single row self-describing in `dashboard.json` and in any excerpt of the
  page. Keep it.

- [ ] **L4 — Render the provisional volatility marker**

  Once L1 is agreed and Lane K has landed, a percentile computed on 10–19 sessions must
  **look different on the page** from one computed on 20 or more, and `dashboard.json` must
  say which it is. A reader must not have to know that a release happened in order to read
  the number correctly.

  Show the session count. "Provisional — 12 of 20 sessions" is honest and costs one line;
  an unexplained asterisk is not.

- [ ] **L5 — Publish the crowding-penalty magnitude on the row**

  A carried-over ergonomics gap from the round-1 grading audit (`HANDOFF.md`, G1). A row
  carrying `crowding_penalty` only reconciles if the reader supplies the penalty's
  magnitude, `crowding_penalty_scale * (1 - confidence_multiplier)`. Today `grade_penalties`
  names the penalty but never its size, so the reader must cross-reference
  `per_ticker_sections[].gate.confidence_multiplier` in another part of the document.

  Definition-of-done item 6 ("every grade recomputes from fields present in the same
  document") does hold today — this makes it hold **row-locally**.

  **Do it without touching `grading.py`.** Both inputs are already available in `build.py`:
  `confidence_multiplier` is passed at `build.py:342` and the scale lives in the grading
  settings. Compute and publish the magnitude there.

  **Acceptance:** `PYTHONPATH=src .venv/bin/python ops/audit_dashboard.py <dashboard.json>`
  still returns `ok=true`, and a test asserts the magnitude is present and correct on a row
  that carries the penalty.

- [ ] **L6 — Update `docs/product/REPORT-LAYOUT.md`**

  Extend, do not rewrite — Lane H's round-2 content is still accurate about conviction,
  certainty and thesis marking. Add: the two sections and what puts a row in each; the
  provisional volatility marker; the crowding-penalty magnitude; and, in one short
  paragraph, **why** the split exists, so the next reader does not "fix" the tied-zero block
  by changing a grade.

- [ ] **L7 — Report completion in `CROSS-LANE.md`**

---

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_render.py tests/test_dashboard.py -q
PYTHONPATH=src .venv/bin/python -m pytest                            # expect >= 671 passed
PYTHONPATH=src .venv/bin/python ops/audit_dashboard.py output/published/latest/dashboard.json
```

The audit must still report `ok=true`. It recomputes every grade from the published
document, so it is the fastest proof that a presentation change did not become a grading
change.

## Done when

- Every published idea is in exactly one section, asserted by a test.
- Ordering inside the supported section is still pinned by a multi-row test.
- Criteria 11 and 12 still hold, by the named tests or stronger replacements.
- The provisional volatility marker renders and appears in `dashboard.json`.
- The crowding-penalty magnitude is row-local and `audit_dashboard.py` returns `ok=true`.
- `dashboard/grading.py` is byte-identical to the round-3 baseline. Check it:
  `git diff --stat -- src/briefing_app/dashboard/grading.py` must be empty.
