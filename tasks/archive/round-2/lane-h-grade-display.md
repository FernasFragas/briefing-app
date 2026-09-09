# Lane H — Grade display and thesis disagreement

**Implements:** D10 (conviction and certainty), D11 (declared thesis beside the data).
**Depends on:** round 1 complete. Runs in parallel with G, I, J.
**Coordinates with:** Lane G, on the completeness-summary field names for the run banner.

## Owns — write only these

```
src/briefing_app/dashboard/render.py
src/briefing_app/dashboard/build.py
src/briefing_app/dashboard/models.py
tests/test_dashboard.py
tests/test_render.py
docs/product/REPORT-LAYOUT.md
```

## Must not touch

`dashboard/grading.py`. **This matters more than usual here** — see the boundary below.
`pipeline.py` (Lane G).

> ### Boundary — you may change what is shown, not what is scored
>
> D11 accepted a known consequence: nine of sixteen rows score exactly 0.0 and cannot be
> ranked against each other. The owner chose to make the disagreement **visible** rather
> than to change the grade again.
>
> **Do not "fix" the tied zeros by touching the score.** Not by adding a tiebreaker into
> the grade, not by making contradiction score negative, not by rescaling. If the tied
> block turns out to be unreadable, say so in `CROSS-LANE.md` and let the owner decide —
> that is a new product decision, not a lane call.

---

## Task H1 — Conviction and certainty as two labelled measurements (D10)

Today `render.py:293` renders the letter with the score in parentheses, producing `C
(100.0)` — the highest possible score beside the lowest grade letter. Both numbers are
correct; the presentation makes them look like a contradiction.

They are two different measurements and must be shown as such:

| Shown | Is | Comes from | Range |
|---|---|---|---|
| **Conviction** | how strongly the evidence supports the idea | `100 x alignment`, less penalties | 0–100, uncapped |
| **Certainty** | how far data quality lets that conviction be trusted | the confidence tier, capping the letter | letter, capped per tier |

Requirements:
- Two distinct columns or two clearly distinct visual elements. Not one value in
  parentheses after the other.
- A short legend on the page saying what each means, in plain words. A reader who has never
  seen the report must be able to work out why a row can read 100 and `C` at once.
- The sort stays on conviction, which is what round 1 fixed. The certainty column must not
  reintroduce a hidden sort key.

**Acceptance:**
- A row with conviction 100.0 and tier C renders both, with neither presented as the grade.
- The legend text exists and names both scales.
- A test asserts the ideas table is still ordered by conviction descending within each
  status bucket — the round-1 six-row ordering test must still pass.

## Task H2 — Show the declared thesis beside the data's reading (D11)

`TradingIdeaRow` publishes `direction`, which comes from the universe configuration via
`strategy/engine.py:1210` — it is **your declared hypothesis**, not the model's read. The
model's read lives on the scoring result as `posture` and `s_cte`.

Publish and render both, so the disagreement is a visible fact rather than something a
reader must infer from a score of zero:

```
Ticker  Thesis   Data reads          Conviction  Certainty
GOOGL   long     neutral (-0.094)          0.0   C
INTC    long     moderate_bullish (+0.465) 100.0  C
```

Requirements:
- Add the composite reading to `TradingIdeaRow` — at minimum the posture and the composite
  score. `build.py` already has the scoring result to hand.
- Render thesis and data reading as adjacent columns.
- **Mark the disagreement explicitly.** A reader should not have to compare `long` against
  `neutral (-0.094)` and work out the implication. Nine of sixteen rows are in this state;
  it is the report's most common condition and deserves a plain-language marker.
- `docs/product/REPORT-LAYOUT.md` explains what the two columns mean and why a disagreement is
  informative rather than an error — otherwise it reads as a bug.

**Acceptance:**
- Both values are on `TradingIdeaRow` and in `dashboard.json`.
- A row whose thesis contradicts its data reading is visibly marked as such.
- A test builds one agreeing row and one contradicting row and asserts the marker appears
  on exactly one of them.
- The grade is unchanged by this task. Verify: grades before and after are identical.

## Task H3 — Render the run-health banner (D9, consumed from Lane G)

Lane G is escalating degraded conditions to run-level diagnostics and publishing a
completeness summary. The report must show it, or the escalation changes nothing a reader
sees.

**Agree the field names with Lane G in `CROSS-LANE.md` before building this.** Do not guess
at the shape and do not read Lane G's in-progress code.

Requirements:
- When a run is `partial`, a banner at the **top** of the report names what was missing.
  Not in a collapsed section — the point is that it cannot be missed.
- The total-outage case Lane G detects (no provider reached at all) is worded distinctly
  and unmistakably. A report built on nothing must say so in terms the reader cannot
  misread as a normal caveat.
- A healthy run shows no banner. A banner that is always present is wallpaper.

**Acceptance:**
- A partial run renders the banner with the missing items named.
- A total-outage run renders the distinct, stronger wording.
- A clean run renders nothing.

## Task H4 — Update `docs/product/REPORT-LAYOUT.md`

Round 1 created this file. Extend it with: the two grade scales and why there are two; the
thesis-versus-data columns and why disagreement is a feature; and the banner states. Keep
it short — it exists so the next reader does not mistake any of these for defects.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_dashboard.py tests/test_render.py -q
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily \
  --config config/config.example.yaml --force --no-persist
```

`--no-persist` is required. A fixture run must never write to the history store — round 1
added a refusal for exactly this, and it should not be tested by accident.

Then open the generated page and read it as a stranger would. If you cannot tell at a
glance why GOOGL scores zero, H2 is not finished.

## Handoff

Report to the owner: whether the tied block of nine zero-scoring rows is readable in
practice once the disagreement is marked. That is the open question D11 deliberately left
unresolved, and your rendering is the evidence for deciding it.
