# Tasks: Graded Trading Ideas Report

Phase 3 of the spec-driven workflow.
Spec: `docs/SPEC-graded-ideas-report.md` · Plan: `tasks/plan.md` (both approved 2026-08-31,
including the thesis-band amendment).

**Status: complete.** All nine tasks landed 2026-08-31; the graded ideas table is live in
`dashboard.html` and `dashboard.json` (`schema.v2`). **T10 landed 2026-09-03** after the
live run showed grade and tradeability were anti-correlated. Baseline at start was 370
tests; the suite is now **460** after this work, three defect fixes, and the provider
wiring that followed.

Ordered by dependency. `T1`–`T3` are fully parallel; everything after is a queue where noted.

> **Stages here are not Waves.** This file groups `T`-tasks into **Stages 1–5**.
> `provider-alternatives-implementation.md` separately groups `I`-tickets into **Waves 0–3**
> for provider and data wiring. The two schemes are unrelated and never renumber each other:
> a bare "Wave N" always means that file.

---

## Post-09-06 amendment — the grading audit (G1–G5)

**These tasks are not reopened and their history below is left as written.** What follows
records what G1–G5 changed *underneath* T4 and T5, so a reader of those entries does not
act on a description that no longer matches the code. Full narrative and evidence:
`HANDOFF.md` §2, the `G1–G5` entry. Spec: `docs/SPEC-graded-ideas-report.md`, which is
current. Suite is **611 passing** (was 460 at close of T9, 569 at N1).

- **T4's `alignment()` signature is unchanged; its contract is not.** The entry below
  specifies "`|s_cte|` when the sign matches, else `0.0`". That was the defect. The two
  branches returned values on incompatible scales — `1.0` for a neutral setup inside the
  band against `|S_CTE|`, observed max 0.317, for a directional one — so the neutral branch
  could claim its whole alignment weight and the directional branch about a third of its
  own. **Now:** `min(1, |S_CTE| / DIRECTIONAL_FULL_CONVICTION)` with
  `DIRECTIONAL_FULL_CONVICTION = 0.35`, so both branches are conviction units in 0…1. The
  0.35 is the smallest denominator above the largest observed `|S_CTE|`; 0.25 and 0.30 were
  tested and rejected because the strongest live row still saturated at both.
- **T1's weights are no longer the only split.** T1 shipped `probability_weight: 0.60` /
  `alignment_weight: 0.40` and they still validate as a pair. A third setting,
  `directional_probability_weight: 0.20`, is selected by `_effective_weights()` for the
  `above spot` and `below spot` bands, giving `0.20 * P + 0.80 * alignment` there. It is
  deliberately outside the sum-to-1.0 validator, which governs only the neutral pair.
- **T5's row gained `direction` and the ideas table gained a components-scored count.**
  `alignment()` branches on direction while `_effective_weights()` branches on band, so for
  a `beyond +/-1 sigma` band the direction is not recoverable from the published row — a
  skew structure and a neutral straddle published identical fields and graded differently.
  Separately, rows are scored on **different component sets** (on the 2026-09-04 run: 11
  names on four, 8 on three, QQQ and SPY on two) and T5 sorted them into one column with no
  marker; the count is that marker.
- **T9's acceptance criterion is not quite met, and now that is known.** "Every grade in it
  recomputes from fields present in the same document" **holds** — verified on the
  2026-09-06 live run, 18 of 18 rows to diff 0.00. A row carrying `crowding_penalty` needs
  `confidence_multiplier` to reconcile; that is published at
  `per_ticker_sections[].gate.confidence_multiplier`, so the criterion is met at document
  level. It is not met *row-locally*: `grade_penalties` names the penalty but not its
  magnitude, so the ideas table alone is not self-checking.
- **The tier badge now carries information, which T4's ceilings assumed and did not get.**
  `REQUIRED_COMPONENTS` for `V` and `E` gained `S_S`, and `S_S` stopped judging its own
  completeness over legs that can never be available. Projected on the 2026-09-04 rows:
  13 Tier A, 6 B, 2 C, where it had been 21 of 21 Tier A with the ceiling binding nothing.

> **Falsified by the 2026-09-06 live run (`daily-2026-09-06-e270378b`). Actual: 16 B, 2 C —
> no row reached Tier A.** The projection assumed a `verified` `S_S` would qualify for Tier A.
> It does not: `_required_component_condition` (`scoring.py:556-563`) floors to B on
> *source quality* as well as status, and `_DEGRADED_QUALITIES` contains `aggregator`.
> `S_S` is `aggregator` by construction (`components/sentiment.py:528` — analyst signals come
> from FMP and Finnhub, and sentiment has no primary source), so **`S_S` can never qualify a
> row for Tier A**. The completeness fix worked on its own terms — `S_S` read `verified` for 5
> of 18 names, where before it could never be verified for anyone — but the quality gate binds
> first. G5 therefore still does not produce a discriminating tier: 'always A' became
> 'always B'. Open decision, see N7.
  T4's required Tier C test still passes and is still the rule the design exists to enforce.
- **Still open, and it is not a tuning problem.** A directional raw score is
  `10 + 80 * alignment`, because `P(above spot)` is pinned near 0.50 by construction and
  carries 0.20 weight while a neutral row draws 30–52 points from a `P` that varies
  0.50–0.86. Closing that 20–42 point structural head start means giving a directional
  thesis the probability of **reaching its target**, which is a `ScenarioTable` change and
  therefore outside the scope every task here was written under. Tracked as `N6` in
  `HANDOFF.md`.

> **Reverted 2026-09-06 after the live run.** `daily-2026-09-06-e270378b` returned
> **0 A / 16 B / 2 C** — the constant moved down a notch rather than becoming a spread.
> `_required_component_condition` floors on *source quality* before it reads
> `validation_status`, and `S_S` is `aggregator` by construction, so a `verified` `S_S`
> still caps its row at B; five names on that run proved it. `REQUIRED_COMPONENTS` for
> `V`/`E` is back to `{S_O, S_M}` and **the tier badge was removed from the graded ideas
> table instead** — the decision the audit originally recommended. The `sentiment.py`
> completeness fix is kept: it is correct on its own terms and `S_S` now reads `verified`
> where every weighted leg is scored. Do not re-add `S_S` to the required set without
> first changing how `S_S` reports source quality.

---

## Post-09-03 amendment

- [x] **T10 — Actionability-first ideas ordering**
  - The 2026-09-03 live run produced four `TRADEABLE` rows graded `D`/`F` and six `A`/`B+`
    rows that were all `WATCHLIST` because IV rank history was unavailable. Grade still
    measures conviction, but the headline report must be ordered by what can be acted on.
  - `_trading_ideas()` now sorts `TRADEABLE` before `WATCHLIST`, before `BLOCKED`, before
    `UNSCORED`; grade descending remains the tie-break inside each status bucket.
  - The HTML table renders `Status` before setup and grade so the action ordering is visible
    without changing the `dashboard.v2` JSON shape.
  - Required regression: a lower-grade `TRADEABLE` row sorts above a higher-grade
    `WATCHLIST` row whose blocked reason is `iv_rank_unavailable`.

---

## Stage 1 — parallel, no shared files

- [x] **T1 — Grading settings in config**
  - Add a `ReportGradingSettings` model and a `report.grading:` block: `probability_weight:
    0.60`, `alignment_weight: 0.40`, `divergence_penalty: 10.0`, `crowding_penalty_scale:
    20.0`. Model it properly on `AppConfig`, **not** via `model_extra` — the mistake I0
    documents for the `providers:` block.
  - Weights must validate: both in `[0, 1]`, and sum to 1.0 within tolerance; an invalid
    block fails **config load**, not the run.
  - Acceptance: `load_config()` exposes the block with the defaults above; a config with
    `probability_weight: 0.9, alignment_weight: 0.4` raises at load with a message naming
    the field.
  - Verify: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_loader.py -q` plus a new
    case asserting the load-time rejection.
  - Files: `src/briefing_app/config.py`, `config/config.example.yaml`, `tests/test_loader.py`

- [x] **T2 — Dashboard schema v2**
  - Add `TradingIdeaRow` per the spec's snippet and
    `DashboardPayload.trading_ideas: list[TradingIdeaRow]`. Bump `schema_version` to
    `dashboard.v2`.
  - **Do the R3 grep first**: `rg -n 'schema_version|dashboard\.v1|model_dump\(\)' tests/
    src/briefing_app/delivery.py src/briefing_app/storage.py` and fix any exact-shape
    assertion before adding the field. `extra="forbid"` makes a stale key set a hard error.
  - Acceptance: an old-shape construction still succeeds (new field defaults to `[]`);
    `audit_json()` emits `trading_ideas`; `counts` gains no key it cannot compute.
  - Verify: `pytest tests/test_dashboard.py tests/test_render.py tests/test_delivery.py -q`
  - Files: `src/briefing_app/dashboard/models.py`, `tests/test_dashboard.py`

- [x] **T3 — Persist grades on `setup_signal`**
  - Migration `migrations/003_setup_grade.sql`: `ALTER TABLE setup_signal ADD COLUMN
    grade_letter TEXT, ADD COLUMN grade_score NUMERIC`. Dedicated columns rather than the
    existing `details` JSONB, so a future T12 calibration can group by grade in SQL.
  - Mirror both columns on the SQLAlchemy `setup_signal` Table in `storage.py` — the file
    keeps its own definition in sync with `migrations/` by hand.
  - Acceptance: `upsert_setup_signal` round-trips both fields and stays idempotent on the
    `(run_id, ticker, setup_type, horizon)` natural key; a `NULL` grade is legal.
  - Verify: `pytest tests/test_storage_repository.py -q`
  - Files: `migrations/003_setup_grade.sql`, `src/briefing_app/storage.py`,
    `tests/test_storage_repository.py`

---

## Stage 2 — the substance

- [x] **T4 — Grade engine** *(needs T1)*
  - New `dashboard/grading.py`. Pure functions, no I/O, no provider access:
    - `thesis_band(setup) -> (label: str, probability: float | None)` — by `setup_type` per
      the spec table; **for `WATCHLIST_NO_TRADE`, fall back to `setup.direction`**
      (long → `probability_above_spot`, short → `probability_below_spot`,
      neutral → `probability_in_one_sigma`). This amendment is the reason the task exists:
      24 of 24 setups are currently that type and all carry a scenario table.
      Updated 2026-09-02 for N2: directional grades use side-of-spot probability, not the
      one-sigma tail.
    - `alignment(s_cte, direction) -> float` — `|s_cte|` when the sign matches, else `0.0`.
    - `compute_grade(...) -> GradeResult(score, letter, penalties: list[str])`.
  - Bands `A+ 90 / A 82 / B+ 74 / B 66 / C+ 58 / C 50 / D 35 / F 0`; ceilings
    `A → 100, B → 81, C → 57`. Penalties: `divergence_penalty` when the thesis band is in
    `scenario_table.diverging_rows`; `crowding_penalty_scale * (1 - confidence_multiplier)`.
  - `probability is None` → `GradeResult` with `score=None`, `letter=None` and a reason.
    Never a grade from an absent probability.
  - Acceptance: every band boundary asserted on both sides (34/35, 49/50, 57/58, 65/66,
    73/74, 81/82, 89/90); all three ceilings; all 10 `SetupType` values mapped; both
    penalties; direction fallback covered for all three directions.
  - **Required test:** a Tier C input with `P = 0.95` and `S_CTE = +0.9` grades no better
    than `C`. This is the single rule the design exists to enforce.
  - Verify: `pytest tests/test_grading.py -q`
  - Files: `src/briefing_app/dashboard/grading.py`, `tests/test_grading.py`

---

## Stage 3 — `build.py` queue (same file, land in order)

- [x] **T5 — Trading ideas builder** *(needs T2, T4)*
  - `_trading_ideas(...)` in `build.py`, called from `build_dashboard_payload`. One row per
    ticker present in score/setup inputs, plus gate-accepted names that did not produce a
    score; gate-only rejects stay in `rejected_at_gate`.
  - Status resolution per the spec: `TRADEABLE` / `WATCHLIST` / `BLOCKED` / `UNSCORED`.
    **`UNSCORED` rows carry `grade_letter = None`** — a name never scored is never graded.
  - **R2 mitigation:** `blocked_reason` resolves from the *cause*, not the code. All 24
    rejections today are the bare code `tier_c`, which repeats the tier badge and says
    nothing. Read `ScoringResult.missing_required` and the universal-floor reason first;
    fall back to the raw `RejectionCode` only when no cause is recorded.
  - Sort by `grade_score` descending, ungraded rows last.
  - **R5:** grades must be computed *before* the prose step so T8 can authorize them.
  - Acceptance: a fixture run emits 24 rows; no row's score exceeds its tier ceiling; every
    non-`TRADEABLE` row has a non-empty `blocked_reason`; ordering holds.
  - Verify: `pytest tests/test_dashboard.py -q`, then
    `PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --config
    config/config.example.yaml --force --no-persist`
  - Files: `src/briefing_app/dashboard/build.py`, `tests/test_dashboard.py`

- [x] **T6 — Analysis section rework** *(needs T2; after T5 — same file)*
  - `_ticker_section()` gains, per component: score, `source_quality`, and **legs scored of
    legs defined**, derived from `ComponentResult.sub_scores` against `weights_used`. Every
    absent leg named with its reason from `na_reason` / `diagnostics`.
  - **R1 — this could not be verified on a fixture run at the time.** Fixture `S_S` reports
    `available=True`, all three legs present, `na_reason=None`, including `executive_tone`
    and `retail_momentum`, which had no live source at all. A fixture check would read
    "3 of 3" and be wrong.
  - Acceptance: verified against a **hand-built `ComponentResult`** with two absent legs,
    which must render "1 of 3" and name both absentees. Under `data_mode: fixture` the
    section states that leg counts describe the fixture, not the sourcing.
  - Verify: `pytest tests/test_dashboard.py -q` with the synthetic-component case
  - Files: `src/briefing_app/dashboard/build.py`, `tests/test_dashboard.py`

---

## Stage 4 — parallel, different files

- [x] **T7 — Template restructure** *(needs T2, T5)*
  - Reorder `_TEMPLATE`: trading ideas table, then analysis, then market overview; wrap
    matrix, prior scorecard, conditionality, rejected-at-gate and evidence ledger in
    `<details>`. No section deleted.
  - Empty state renders "no scored ideas this run", never a blank table.
  - Wide table scrolls in its own container; the page body must not scroll horizontally.
  - Acceptance: ideas table precedes every other section in DOM order; all seven prior
    sections still present; grade and tier render adjacent per row.
  - Verify: `pytest tests/test_render.py -q`, then open the generated
    `output/dashboard/<date>/dashboard.html`
  - Files: `src/briefing_app/dashboard/render.py`, `tests/test_render.py`

- [x] **T8 — Authorize grades in prose** *(needs T5)*
  - `collect_authorized_numbers()` walks the prompt context recursively, so this is a
    **wiring** task: include the graded rows in the context handed to the prose prompt, so
    a grade the pipeline computed is authorized and one the model invents is not.
  - Acceptance: prose citing a real `grade_score` passes `assert_authorized_numbers`; prose
    citing a grade absent from the payload raises `NumberViolation`.
  - Verify: `pytest tests/test_dashboard.py -q`
  - Files: `src/briefing_app/dashboard/prompts.py`,
    `src/briefing_app/dashboard/guardrails.py`, `tests/test_dashboard.py`

---

## Stage 5 — close out

- [x] **T9 — Documentation and sample artifact**
  - `README.md`: the `jq` recipe from the spec for reading `trading_ideas`.
  - `docs/SPEC-graded-ideas-report.md`: record the thesis-band amendment as accepted, so the
    spec matches what was built.
  - Regenerate one fixture dashboard and confirm it opens on the graded table.
  - Acceptance: full suite green; a fresh `dashboard.json` validates as `dashboard.v2`;
    every grade in it recomputes from fields present in the same document.
  - Verify: `PYTHONPATH=src .venv/bin/python -m pytest` — **370 + new, zero failures**
  - Files: `README.md`, `docs/SPEC-graded-ideas-report.md`

---

## Standing constraints

- No checkpoint may require a `TRADEABLE` row to exist. There are 0 today, and there will be
  0 until the provider wiring in `provider-alternatives-implementation.md` lands — **I2**
  (Wave 0, SEC EDGAR into `S_I`/`S_F`) and **I14** (Wave 2, self-built `iv_history`). A test
  that needs one is untestable by construction.
- No task touches provider code, scoring logic, `ScenarioTable`, or ticker selection.
- The silent renormalization stays unfixed (I15/A4). This work makes it **visible**; it does
  not repair it.

**Added 2026-09-06 by the grading audit:**

- **The grade formula is band-dependent and must be stated as such.** Any recomputation,
  ceiling table or worked example has to name which split it used —
  `0.20 * P + 0.80 * alignment` for `above spot` / `below spot`, `0.60 / 0.40` otherwise.
  Every historical figure in this repo written as a single `0.60 / 0.40` formula predates
  that and is a neutral-band figure whether or not it says so.
- **`alignment()`'s two branches must reach the same floor and ceiling.** They are measured
  against different reference points — `DIRECTIONAL_FULL_CONVICTION` for a directional
  thesis, `NEUTRAL_BAND` for a neutral one — and that is deliberate, but both must land in
  0…1 or the grade sorts by setup type instead of by quality. That is precisely the defect
  G2 fixed.
- **Nothing may enter a required set that cannot read `verified` on a real run.** A
  required component that is structurally incapable of full status caps the entire universe
  one tier down and looks exactly like a working tier.
- **The `ScenarioTable` exclusion above is now the binding constraint, not a convenience.**
  The remaining directional/neutral asymmetry can only be closed inside
  `strategy/scenarios.py`, so it is new work (`N6` in `HANDOFF.md`) rather than an
  amendment here.
