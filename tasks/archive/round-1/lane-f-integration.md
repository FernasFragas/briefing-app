# Lane F — Integration

**Runs last.** Starts only when Lanes A, B, C, D and E have all reported complete.

## Owns — write only these

```
HANDOFF.md
README.md
tasks/RESULTS.md         (new)
```

After all five lanes have finished, Lane F may also edit any file they owned — the
ownership rule exists to prevent concurrent writes, and there is no longer any concurrency.

---

## Why this lane exists

Each of A–E is verified against the fixture suite in isolation. Three things can only be
checked once they are together:

- **The lanes interact through data, not through files.** Lane C's backfill changes which
  setups pass the gate; Lane D's catalyst change adds names; both change the population
  Lane A's grade bands were cut against. No file conflict, but a real interaction.
- **`README.md` describes behaviour three lanes changed**, which is why it was withheld
  from all of them.
- **The definition of done is a property of one live run**, not of five test suites.

---

## Tasks

- [ ] **F1 — Full suite, then one live run**

  ```bash
  PYTHONPATH=src .venv/bin/python -m pytest        # zero failures, no exceptions
  PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --data-mode live --force
  ```

  The run must finish `succeeded` with zero failures and zero diagnostics. Record the run
  id in `RESULTS.md`.

- [ ] **F2 — Re-check the grade bands against the new population**

  Lane A cut the letter bands against the 18 rows of the 2026-09-06 run, because that was
  the only evidence available at the time. By the time this lane runs, Lane C has opened up
  the volatility metrics and Lane D has admitted names previously rejected on inferred
  catalyst dates. **The score distribution is not the one Lane A calibrated against.**

  Recompute the letter distribution on the F1 run. The bands are correct if they
  discriminate — a distribution that is 80% `F`, or 80% one letter, is not a scale.

  This is a calibration, not a redesign. If the bands need moving, move them and say so in
  `RESULTS.md`. If Lane A's cut still holds, record that too — it is worth knowing.

  **Acceptance:** the letter distribution on the F1 run is recorded, and the bands either
  stand or are moved with the new distribution as the reason.

- [ ] **F3 — Verify the definition of done, item by item**

  From `README.md` in this directory. Each needs evidence in `RESULTS.md`, not an assertion:

  | # | Check | How |
  |---|---|---|
  | 1 | Suite green | `pytest` output, test count |
  | 2 | Live run clean | run id, status, failure and diagnostic counts |
  | 3 | Ordering correct in each bucket | `jq` the ideas table and read it |
  | 4 | 20 of 20 sessions, no fixture rows | query `daily_snapshot` |
  | 5 | Indexes in market context | `jq` both sections |
  | 6 | Grades recompute from the document | see F4 |
  | 7 | Three unattended runs | `briefing_run` rows, from Lane E |
  | 8 | README claims match behaviour | see F5 |

- [ ] **F4 — Prove every grade recomputes from the published document**

  This has been an acceptance criterion since T9 and it is the property that makes the
  report auditable: a reader must be able to recompute any grade from fields present in the
  same document.

  Under ALIGN this gets **easier**, since the grade is `100 x alignment` less penalties,
  and `alignment` derives from `s_cte` and `direction`, both published on the row.

  One known wrinkle survives from T9 and should be closed now that the formula is simpler:
  a row carrying `crowding_penalty` needs `confidence_multiplier` to reconcile, and that is
  published at `per_ticker_sections[].gate.confidence_multiplier` rather than on the row.
  The document reconciles; the **row** does not. Publishing the penalty magnitude on the
  row closes it — a small change, and this is the right moment.

  **Acceptance:** a script recomputes every row's grade from `dashboard.json` alone and
  matches to 0.00. Commit the script; it is the audit tool for every future run.

- [ ] **F5 — Make `README.md` true**

  Withheld from every other lane because three of them changed what it describes. Check at
  least:

  | Claim | Changed by |
  |---|---|
  | "The grade combines the probability of the setup's own thesis band with how well `S_CTE` supports it" | Lane A — **no longer true**, the probability is context only |
  | "capped by the confidence tier: Tier A can reach `A+`, Tier B stops at `B+`, Tier C stops at `C`" | Lane A — verify against the mechanism actually chosen |
  | "Grade descending is the tie-break inside each status bucket" | Lane B — was **false before** this work; confirm it is true now |
  | "Ollama Cloud for bounded LLM prose" | Lane E — use the wording Lane E supplies |
  | The `jq` recipe for reading `trading_ideas` | Lane B — verify it still runs and returns rows |
  | Deployment sections describing hosted operation | D1 — the shipped answer is local; keep hosting as an option but stop presenting it as the plan |

  Run every command in the README. A command that does not run is a claim that is not true.

- [ ] **F6 — Fold this work into `HANDOFF.md`**

  `HANDOFF.md` is the running record and was frozen for the duration. Update it now:

  - **N6, N7 and N8 are closed.** N6 stays closed as it was. **N7 and N8 are withdrawn, not
    deferred** — D2 supersedes both. Record why, with the measurement: N7 changes exactly
    one letter across eighteen rows and leaves the neutral floor at 39.8; N8 as filed
    inverts the asymmetry rather than removing it, giving directional rows a 43.7-point
    advantage at the top. Neither is worth reviving, and a future reader who finds them
    listed as open work will otherwise waste a day on them.
  - **N5 (`parse_datetime` hardening) is already done — close it.** `HANDOFF.md` records it
    as the last open item in the N-queue, describing `providers/normalizers.py` as still
    calling `datetime.fromisoformat` bare. Verified 2026-09-07: `parse_datetime`
    (`normalizers.py:2650`) wraps the call and raises `NormalizationError`, exactly matching
    the `parse_date` shape the note said to copy. The fix landed in the uncommitted work and
    the note was never updated. Close it, and record that it was found stale rather than
    fixed here — the point is that `HANDOFF.md` drifted, which is worth knowing.

    **While closing it, re-check the other N-queue items the same way.** N5 was stale, so
    others may be. Verify against the code before carrying anything forward as open.
  - Add the eight decisions from `DECISIONS.md` by reference, not by copying them.
  - Correct the baseline test count and the live-run figures.

- [ ] **F7 — Write `tasks/RESULTS.md`**

  Evidence for each definition-of-done item, the final letter distribution, the F4 audit
  script's output, and anything a lane deliberately left undone. That last part matters
  most: an honest list of what was **not** finished is more useful than a clean-looking
  report that quietly omits it.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --data-mode live --force
jq -r '.trading_ideas[] | [.status, .ticker, .grade_letter, (.grade_score|tostring)] | @tsv' \
  output/dashboard/$(date +%F)/dashboard.json | column -t
```
