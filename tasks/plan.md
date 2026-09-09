# Plan: Graded Trading Ideas Report

Phase 2 of the spec-driven workflow. Spec: `docs/SPEC-graded-ideas-report.md` (approved
2026-08-31, defaults accepted). Plan approved 2026-08-31, including the thesis-band
amendment, and decomposed into Phase 3 in `tasks/todo.md`.

Status: **complete.** Approved, handed to Phase 3, and all nine tasks in `tasks/todo.md`
landed on 2026-08-31.

Three defects surfaced while building against real data, all fixed and all outside the
original plan: a fixture IV surface inconsistent with its own price bars (implied vol 7.9x
realized, which collapsed every scenario probability), a float-noise crash in
`density_from_call_prices`, and a divergence threshold that fired on an ordinary variance
risk premium. The provider work that followed is tracked in
`provider-alternatives-wiring-tasks.md`, not here.

> **Stages here are not Waves.** This plan groups components into **Stages 1–5**.
> `provider-alternatives-implementation.md` separately groups `I`-tickets into **Waves 0–3**
> for provider and data wiring. The two schemes are unrelated: a bare "Wave N" always means
> that file.

## Premises verified before planning

The repo's own rule — verify the premise before building against it. Checked on a fixture
run at `run_date=2026-08-31`, 24 scored tickers:

| Premise | Result | Consequence |
|---|---|---|
| `ComponentResult` exposes per-leg data | ✅ `sub_scores` + `weights_used` + `na_reason` | Criterion 5 needs **no scoring-layer change**. Risk retired. |
| Setups carry a `scenario_table` | ✅ **24 of 24** | `P` is available for every row. Risk retired. |
| Setup type varies | ❌ **24 of 24 are `watchlist_no_trade`** | Breaks the spec's band table. See amendment below. |
| `direction` populated on watchlist setups | ✅ `neutral: 9, long: 15` | The amendment is implementable. |
| Rejection codes are informative | ⚠️ **24 of 24 are just `tier_c`** | "Why not tradeable" needs the Tier C *cause*, not the code. |
| `S_O` present | ❌ absent for the sampled ticker | Consistent with Tier C; the ideas table must tolerate a missing component. |

## Approved spec amendment

The spec originally assigned the thesis band **by setup type**, and gave
`WATCHLIST_NO_TRADE` no band: `P = None`, grade from `S_CTE` alone. But every setup today is
`watchlist_no_trade` *and* every one carries a scenario table. Under the original spec, **all
24 rows would discard a probability that exists** and grade on half their inputs.

**Amendment:** derive the thesis band from `Setup.direction` when `setup_type` is
`WATCHLIST_NO_TRADE`:

| `direction` | Thesis band | Property |
|---|---|---|
| `long` | above spot | `probability_above_spot` |
| `short` | below spot | `probability_below_spot` |
| `neutral` | within ±1σ | `probability_in_one_sigma` |

Type-based selection stays authoritative for every other setup type; direction is the
fallback, not a replacement. A watchlist row is still capped by its tier, so this cannot
promote anything into tradeable territory — it only stops the grade being needlessly blind.

**2026-09-02 N2 correction:** directional setup types and directional watchlist fallback use
side-of-spot probability, not one-sigma tail probability. The earlier tail mapping made a
directional thesis score the geometry of a normal distribution rather than directional
conviction.

## Components

| # | Component | File | Depends on |
|---|---|---|---|
| C1 | Grading settings | `config.py` — new `ReportGradingSettings`, modelled properly (not `model_extra`) | — |
| C2 | Grade engine | `dashboard/grading.py` (new) — pure, no I/O | C1, strategy + scoring models |
| C3 | Schema | `dashboard/models.py` — `TradingIdeaRow`, `trading_ideas`, `dashboard.v2` | — |
| C4 | Idea builder | `dashboard/build.py` — `_trading_ideas()` | C2, C3 |
| C5 | Analysis rework | `dashboard/build.py` — `_ticker_section()` gains legs-scored-of-defined | C3 |
| C6 | Template | `dashboard/render.py` — ideas + analysis first, rest in `<details>` | C3, C4 |
| C7 | Prose guard | `dashboard/guardrails.py` — authorize grade numbers | C3, C4 |
| C8 | Persistence | migration `003` + `storage.py` — `grade_letter`, `grade_score` on `setup_signal` | — |

`C2` is the only component with real logic. Everything else is plumbing around it, which is
why it carries the whole unit-test burden.

## Dependency graph and order

```
Stage 1  (parallel — no shared files)
  C1 config settings ──┐
  C3 schema ───────────┤
  C8 migration 003 ────┘        independent; storage tests are self-contained

Stage 2  (needs C1)
  C2 grade engine + tests/test_grading.py    ← the substance; land it alone

Stage 3  (both edit build.py — sequence them)
  C4 idea builder    (needs C2, C3)
  C5 analysis rework (needs C3)

Stage 4  (parallel — different files, both need C3/C4)
  C6 template
  C7 prose guard

Stage 5
  Documentation + regenerate a sample artifact
```

Critical path: **C1 → C2 → C4 → C6**. C5, C7 and C8 hang off it without extending it.

Only Stage 3 is a genuine bottleneck, and only because `build.py` is one file. C4 first — it
is what the report is for.

## Verification checkpoints

Between waves, not just at the end:

| After | Check | Pass condition |
|---|---|---|
| C2 | `pytest tests/test_grading.py` | Every band boundary and tier ceiling asserted; **Tier C + P=0.95 → no better than C** |
| C4 | fixture run, inspect JSON | 24 `trading_ideas` rows, each with a grade or explicit `UNSCORED`; none graded above its tier ceiling |
| C5 | synthetic component render test | Each component shows legs-scored-of-defined; fixture-mode output states that counts describe the fixture, not live sourcing |
| C6 | open `dashboard.html` | Ideas table is first in DOM; every prior section still present, inside `<details>` |
| C7 | `pytest tests/test_dashboard.py` | Prose citing a real grade passes; invented grade fails |
| C8 | `pytest tests/test_storage_repository.py` | Grades round-trip; upsert still idempotent |
| Final | `pytest` | **370 existing + new tests green** |

## Risks

**R1 — Fixture mode fabricated legs that did not score live at the time.** Verified:
fixture `S_S`
reports `available=True`, `score=0.8`, legs `['institutional','executive_tone',
'retail_momentum']`, `na_reason=None`. Live, `executive_tone` and `retail_momentum` had no
source at all. So criterion 5 would read "3 of 3" in fixture mode and be **wrong**.
→ *Mitigation:* verify C5 against a hand-built `ComponentResult` with absent legs, not
against a fixture run. Note in the analysis section that leg counts under
`data_mode: fixture` describe the fixture, not the sourcing. This is the report surfacing
the problem the fixture path conceals — it must not inherit the concealment.

**R2 — "Why not tradeable" is uniformly `tier_c` today.** All 24 rejections carry that one
code, which tells the reader nothing they cannot see from the tier badge beside it.
→ *Mitigation:* C4 resolves the column from the Tier C *cause* — `missing_required` on the
`ScoringResult`, plus the universal-floor reason — and falls back to the raw code only when
no cause is recorded.

**R3 — `extra="forbid"` on a v2 schema.** Any consumer constructing a `DashboardPayload`
with the old field set still works (new field is defaulted), but anything asserting an exact
key set breaks.
→ *Mitigation:* grep `test_dashboard.py`, `test_render.py`, `delivery.py` and `storage.py`
for exact-shape assertions during C3, before writing the model.

**R4 — The pipeline yields nothing tradeable.** 24 of 24 Tier C, 0 tradeable, and that is
the state this report will ship against.
→ *Mitigation:* none needed, and none attempted. It is the spec's stated risk and the
reason the `BLOCKED`/`UNSCORED` statuses exist. **No checkpoint may require a `TRADEABLE`
row to exist** — a plan that verifies against one would be untestable until the provider
wiring lands: **I2** (Wave 0) and **I14** (Wave 2) in
`provider-alternatives-implementation.md`.

**R5 — Grade ordering inside `build.py`.** Prose generation must run after grading, or C7
cannot authorize the grade numbers it needs to permit.
→ *Mitigation:* C4 computes grades before the prose step; assert the ordering in a test.

## Out of scope

Restated so it does not drift in: no provider work, no new credentials, no change to ticker
selection, no change to scoring or `ScenarioTable`, and no fix for the silent
renormalization itself (that stays I15/A4). This report *reveals* the hollow legs; it does
not repair them.

## Decisions carried into Phase 3

1. The thesis-band amendment above is accepted and belongs in C2/T4.
2. The fixture-leg disclosure is a section-level note under `data_mode: fixture`, plus a
   synthetic-component test that proves absent live legs render correctly. This belongs in
   C5/T6.
3. `tasks/todo.md` is the active Phase 3 task list; this file remains the rationale,
   dependency map, and risk register.
