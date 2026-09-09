# Lane B — Report presentation

**Implements:** blocker #3 (ideas table sorted wrong), D6 (indexes to market context).
**Depends on:** Lane 0 only. Runs in parallel with A, C, D, E.

## Owns — write only these

```
src/briefing_app/dashboard/build.py
src/briefing_app/dashboard/render.py
src/briefing_app/dashboard/models.py
tests/test_dashboard.py
tests/test_render.py
docs/REPORT-LAYOUT.md            (new)
```

## Must not touch

`dashboard/grading.py` (Lane A). Lane A is changing what grades *are* at the same time as
you change how they are *ordered and shown*. That is safe only if this lane never asserts
an absolute grade value — see the constraint below.

> ### Binding constraint — build your own rows
>
> **No test in this lane may assert a grade number produced by `compute_grade`.** Lane A is
> re-scaling every grade concurrently. Construct `TradingIdeaRow` objects with explicit
> `grade_score` values you choose, and assert ordering and rendering against those. A test
> that calls the grade engine and pins its output will break through no fault of its own,
> and worse, might be "fixed" by pasting in Lane A's new numbers — which pins nothing.

---

## Tasks

- [ ] **B1 — Fix the ideas table ordering**

  `_idea_sort_key` (`build.py:491`) is:

  ```python
  return (
      _status_sort_rank(row.status),
      _component_set_rank(row),      # <-- these two
      _component_set_key(row),       # <-- rank before grade
      row.grade_score is None,
      -(row.grade_score or 0.0),
      row.ticker,
  )
  ```

  `_component_set_key` returns `f"{weight_profile}:{','.join(scored_components)}"` — an
  **alphabetical string**. Because `"US:S_M,S_O"` sorts before `"US:S_M,S_O,S_S"`, which
  sorts before `"US:S_M,S_O,S_S,S_I"`, the table is ordered **fewest components first**:
  the thinnest evidence goes to the top and the best-evidenced ideas go to the bottom.

  Measured on the 2026-09-06 run, inside the single `WATCHLIST` bucket:

  ```
  QQQ    57.0  C     <- 2 components, top of the table
  GM     48.4  D     <- 3 components
  CRWV   46.7  D
  ...
  AMZN   39.8  D
  INTC   76.6  B+    <- 4 components, nine rows down
  AMAT   75.6  B+
  ```

  Both `docs/SPEC-graded-ideas-report.md:206` and `README.md` state that rows sort by grade
  descending inside each status bucket. **The shipped behaviour contradicts both**, and no
  test catches it because the fixture used by
  `test_fixture_dashboard_build_emits_action_sorted_trading_ideas` contains exactly one row.

  Restore the documented order: **status rank, then grade descending, ungraded last, then
  ticker.** The component-set grouping was added by the G3 audit to make mixed formulas
  visible; that intent is already served by the per-row component count and component list
  rendered in the table (`render.py:284`, `:287`), which stay. Grouping the *order* by it
  was not what G3 asked for and is not what the spec says.

  **Acceptance:**
  - A test with **at least six rows spanning two status buckets and three different
    component sets** asserts grade-descending order within each bucket. This is the test
    that does not exist today and is the reason the defect shipped.
  - `TRADEABLE` still sorts above a higher-grade `WATCHLIST` row — the existing T10
    regression at `tests/test_dashboard.py:209` must still pass.
  - Ungraded (`UNSCORED`) rows still sort last.

- [ ] **B2 — Move SPY and QQQ out of the ideas table (D6)**

  Index and fund instruments stop producing `TradingIdeaRow`s and instead contribute to
  `market_overview`.

  Decide and write down **how an index is identified**. Do not pattern-match ticker
  strings. The scoring layer already knows: both names carry the structural reason

  > `S_S is structurally n/a for an index or fund: its analyst leg does not exist
  > (instrument has no issuer)…`

  so the classification exists upstream already. Find it and use it. If it turns out the
  only available signal really is a hardcoded list, say so in `docs/REPORT-LAYOUT.md` and
  put the list in one named constant, not inline.

  What they contribute to market context, at minimum: spot, implied volatility, expected
  move, and the composite score with its tier. `market_overview` currently holds a **single
  entry** ("SPY implied weekly move"), so there is room and a reason.

  **Acceptance:**
  - No `TradingIdeaRow` is emitted for an index or fund.
  - `market_overview` gains an entry per index with the fields above.
  - The rows do not silently vanish: `docs/REPORT-LAYOUT.md` records where they went and
    why, and the rendered page shows them somewhere a reader will find them.
  - The ideas table's empty state still renders "no scored ideas this run" rather than a
    blank table — removing two rows from an 18-row report must not be able to produce a
    blank one.

- [ ] **B3 — Render the probability as context, not as a grade input**

  Under D2 the grade no longer uses `P`, but the report still publishes
  `thesis_probability` and `thesis_band` and still shows them. The column heading must stop
  implying the grade was computed from them.

  The existing header text `P(thesis band)` is accurate and should stay — it was always
  careful to say what it measures. What must change is any adjacent prose or `title=`
  tooltip stating that the grade combines probability with alignment. Grep the template for
  it: `render.py:267` carries explanatory copy of exactly this kind.

  **Acceptance:** no text in the rendered page claims the grade is computed from the
  probability. `pytest tests/test_render.py -q` passes.

- [ ] **B4 — Write `docs/REPORT-LAYOUT.md`**

  Short. What the ideas table contains, what it is ordered by and why, what lives in market
  context and why indexes are there rather than in the table, and which sections are
  collapsed behind `<details>`. This is the document that stops B1 regressing in six
  months.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_dashboard.py tests/test_render.py -q
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Then generate a fixture dashboard and **open it**:

```bash
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily \
  --config config/config.example.yaml --force --no-persist
```

`--no-persist` is not optional. Lane C is repairing fixture-data contamination of the
history store at the same time; a fixture run that writes to `data/briefing.sqlite3` is the
exact bug being fixed.

## Handoff

Report to Lane F: how indexes are identified, and confirmation that the six-row ordering
test exists and fails against the old sort key.
