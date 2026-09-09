# Spec: Graded Trading Ideas Report

Status: **awaiting review** (Phase 1 of spec-driven workflow — do not start Plan until approved)
Author: drafted 2026-08-31
Supersedes nothing. Extends the T9 dashboard contract (`dashboard/models.py`).

## Objective

The dashboard is currently an audit artifact that opens on its workings: prior scorecard,
then market overview, then a 31-row matrix of mostly-null scores. A reader looking for
"what should I look at today" has to derive it. The last published run
(`daily-2026-08-30-beaab42f`) rendered a tactical dashboard of three `null` slots and gave
no other answer.

Build a **graded trading ideas table** as the report's headline section, plus a reworked
**per-stock analysis** section beneath it. Every idea the pipeline scored appears with a
single certainty grade, the sub-scores that produced it, and — where it is not tradeable —
the reason.

**User:** a single trader (the repo owner) reading one HTML artifact each morning, delivered
by n8n.

**Success looks like:** the reader opens `dashboard.html`, and the first thing on screen is a
ranked table that answers "which ideas are worth attention, and how sure are we" — with the
evidence still one click below it, not deleted.

### Non-goals

- No new providers, no new credentials, no scoring-model changes. This is presentation over
  data the pipeline already computes.
- No change to ticker selection. The universe stays `config/universe.yaml` +
  `watchlist.csv` + `candidates.yaml` (decided: no `--tickers` flag in this spec).
- Does not fix the empty pipeline. See Risks.

## Tech Stack

Unchanged: Python 3.14, Pydantic v2 (`extra="forbid"` on every dashboard model), Jinja2
(inline `_TEMPLATE` in `dashboard/render.py`), pytest.

## Commands

```bash
# Run the report end to end (fixture)
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --force

# Live
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --data-mode live --force

# Tests
PYTHONPATH=src .venv/bin/python -m pytest
PYTHONPATH=src .venv/bin/python -m pytest tests/test_grading.py tests/test_dashboard.py -q

# Inspect the graded table from the JSON artifact
jq -r '.trading_ideas[] | [.status,.ticker,.grade_letter,.grade_score,.headline] | @tsv' \
  output/dashboard/$(date +%F)/dashboard.json
```

## Project Structure

```
src/briefing_app/dashboard/
  grading.py     → NEW. Pure grade computation. No I/O, no provider access.
  models.py      → + TradingIdeaRow, + DashboardPayload.trading_ideas, schema v2
  build.py       → + _trading_ideas(), called from build_dashboard_payload
  render.py      → template restructured: ideas table + analysis first, detail collapsed
  guardrails.py  → grade numbers added to the authorized-number set
tests/
  test_grading.py    → NEW. Boundary tests for bands, caps, P-selection, penalties
  test_dashboard.py  → extended: payload shape, ordering, UNSCORED never graded
  test_render.py     → extended: section order, collapsed detail, empty-state
docs/
  SPEC-graded-ideas-report.md   → this file
```

## The Grade

Three certainties already exist in the codebase and disagree with each other. The grade
combines two and is **capped by the third**, so an idea built on unverified data can never
present as high-certainty.

### Inputs (all already computed — nothing new is fetched)

| Input | Source | Range |
|---|---|---|
| `P` — probability of the thesis band | `Setup.scenario_table` (`strategy/scenarios.py`) | 0..1 |
| `S_CTE` — multi-factor signal | `Setup.s_cte` / `ScoringResult` | −1..+1 |
| `tier` — data confidence | `ConfidenceTier` (`models/scoring.py:50`) | A/B/C |
| `confidence_multiplier` — gate penalty | `CandidateGateResult` (`models/gate.py:112`) | 0..1 |

### Which probability counts as "the thesis"

`ScenarioTable` exposes five sigma bands plus derived side-of-spot probabilities. The
thesis band is chosen by setup type, and the row **names the band it used** — the column is
`P(thesis band)`, never `P(profit)`:

| Setup type | Thesis band | Property |
|---|---|---|
| `SHORT_PREMIUM_IRON_CONDOR` | stays within ±1σ | `probability_in_one_sigma` |
| `LONG_PREMIUM_STRADDLE`, `LONG_PREMIUM_CALENDAR`, `SKEW_STRUCTURE` | moves beyond ±1σ | `1 − probability_in_one_sigma` |
| `EVENT_DIRECTIONAL_LONG`, `EVENT_DIRECTIONAL_VERTICAL` (long), `POSITIONAL_LONG` | above spot | `probability_above_spot` |
| `EVENT_DIRECTIONAL_PUT`, `BORROW_DEPENDENT_SHORT`, vertical (short) | below spot | `probability_below_spot` |
| `WATCHLIST_NO_TRADE` | **by `direction`** — see the amendments below | `probability_above_spot` / `probability_below_spot` / `probability_in_one_sigma` |

No scenario table → `P = None` → the grade reports `n/a` with reason
`NO_SCENARIO_TABLE`. A grade is never computed from a probability that does not exist.

### Amendment, accepted 2026-08-31: `WATCHLIST_NO_TRADE` takes its band from `direction`

As first written, this spec gave `WATCHLIST_NO_TRADE` no thesis band and graded it from
`S_CTE` alone. Phase 2 disproved the premise: **24 of 24 setups are that type, and every one
carries a scenario table**, so the original rule would have discarded a probability that
exists on every row in the report.

The band is therefore selected by `Setup.direction` for that type — `long` → above spot,
`short` → below spot, `neutral` → within ±1σ. Type-based selection stays authoritative for
every other setup type; direction is the fallback, not a replacement. Tier ceilings still
apply, so this cannot promote a watchlist row into tradeable territory.

### Amendment, accepted 2026-09-02: directional setups use side-of-spot probability

The 2026-08-31 amendment picked the right source of intent for `WATCHLIST_NO_TRADE`
(`direction`) but the wrong probability for directional theses. A directional setup does
not require a one-sigma breakout to be directionally right, and reading
`probability_above_one_sigma` / `probability_below_one_sigma` as conviction mechanically
capped a textbook directional setup below `C`.

Directional setup types now read `probability_above_spot` or `probability_below_spot`.
Those are derived from the existing scenario table as same-side tail mass plus the
favorable share of the `within 1 sigma` band; when the stored band lacks bounds, the
central band is split 50/50. Neutral and volatility setups keep their existing sigma-band
definitions.

### Formula

```
directional:  alignment = min(1, |S_CTE| / DIRECTIONAL_FULL_CONVICTION)
                            if sign(S_CTE) matches the direction, else 0.0
neutral:      alignment = max(0, 1 - |S_CTE| / NEUTRAL_BAND)

raw        = 100 * (0.60 * P + 0.40 * alignment)
directional raw uses 0.20 * P + 0.80 * alignment by default

penalties  = 10  if the thesis band is in scenario_table.diverging_rows
                    (implied and measured sigma disagree)
           + 20 * (1 - confidence_multiplier)
                    (crowded consensus, estimated-catalyst-only)

score      = clamp(raw - penalties, 0, tier_ceiling)
```

Weights `0.60 / 0.40`, the directional probability weight `0.20`, and both penalty
magnitudes are config-tunable under `report.grading:`, defaulting to the values above.

The neutral case does not inherit `|S_CTE|` the way a directional one does, because a
neutral thesis — price stays inside the range — is *supported* by a signal near zero and
*contradicted* by a strong one. It is now continuous rather than binary: a row just
inside the neutral band receives only a small alignment contribution. The threshold is
the strategy engine's own `NEUTRAL_BAND`, so the report and the setup rules agree on
what "neutral" means rather than each carrying a private definition.

The two branches are normalised against different reference points on purpose. For a
neutral thesis `NEUTRAL_BAND` genuinely is where support reaches zero: past the band edge
the row has stopped being neutral. For a directional thesis it is the *opposite* end of
the scale — the point of minimum conviction, not maximum — so the directional branch is
normalised against `DIRECTIONAL_FULL_CONVICTION` (0.35, in `dashboard/grading.py`)
instead. Dividing it by `NEUTRAL_BAND` saturated alignment at `|S_CTE| >= 0.15`, and with
the 0.80 directional alignment weight every row past the band edge then scored at least
80 raw regardless of its probability. 0.35 is the smallest denominator above the largest
`|S_CTE|` observed on a live run (0.317), so no real row clips and the weak tail is
depressed as little as possible; it is a named constant so it can be re-tuned once more
runs exist.

The denominator cannot close the gap between the two branches, and is not meant to. A
directional raw score is `10 + 80 * alignment`, because `P(above spot)` sits near 0.50 by
construction and carries only 0.20 weight, while a neutral row draws 30-52 points from a
`P` that varies 0.50-0.86. Closing that head start needs a directional probability that
actually varies — probability of reaching the setup's target rather than of finishing on
one side of spot — which is a change to the scenario table, not to this constant.

`alignment` keys off `direction`, not the thesis band, so `direction` is published on
each `trading_ideas` row. For `above spot` / `below spot` / `within 1 sigma` the band
implies the direction, but `beyond +/-1 sigma` covers both a NEUTRAL straddle and a
directional skew structure; without the field those two rows publish identically and
neither grade is reproducible.

### Bands and tier ceilings

| Letter | Score | | Tier | Ceiling | Best possible letter |
|---|---|---|---|---|---|
| A+ | 90–100 | | A | 100 | A+ |
| A | 82–89 | | B | 81 | B+ |
| B+ | 74–81 | | C | 57 | C |
| B | 66–73 | | | | |
| C+ | 58–65 | | | | |
| C | 50–57 | | | | |
| D | 35–49 | | | | |
| F | 0–34 | | | | |

The ceilings sit on band edges deliberately: a Tier B idea can never render an "A", which
would contradict the tier badge printed beside it.

## The Ideas Table

One row per **scored** ticker, sorted by actionability first:
`TRADEABLE`, then `WATCHLIST`, then `BLOCKED`, then `UNSCORED`. Within each status bucket,
rows are sorted by `grade_score` descending, with `n/a` rows last.

### Amendment, accepted 2026-09-03: actionability outranks grade

The 2026-09-03 live run produced four `TRADEABLE` rows graded `D`/`F` and six `A`/`B+`
rows that were all `WATCHLIST` because IV rank history was still warming up. Sorting the
headline table by grade alone made the first screen the least actionable part of the
report. The grade remains the conviction score; the table order is now the execution
order. That keeps a lower-grade executable setup above a higher-grade setup that cannot be
traded today.

| Column | Source |
|---|---|
| Ticker | — |
| Status | `TRADEABLE` / `WATCHLIST` / `BLOCKED` / `UNSCORED` |
| Idea | `SetupType` humanized, or `—` when unscored |
| Grade | `A+`…`F` + numeric, or `n/a` |
| P(thesis band) | with the band named, e.g. `0.68 within ±1σ` or `0.50 above spot` |
| S_CTE | signed |
| Tier | A/B/C badge |
| Catalyst | name + date + confirmed/estimated |
| Why not tradeable | blank when TRADEABLE; else the reason |

### Status resolution

| Status | Condition | "Why not" |
|---|---|---|
| `TRADEABLE` | `decision == CANDIDATE` ∧ `setup_type.is_tradeable` ∧ `tier.is_tradeable` | — |
| `WATCHLIST` | setup exists, `decision == WATCHLIST` or `WATCHLIST_NO_TRADE` | top `RejectionCode`, humanized |
| `BLOCKED` | rules fired, every one rejected | highest-severity `SetupRejection.code` + `detail` |
| `UNSCORED` | gate-accepted but no `ScoringResult` | missing components, named |

**`UNSCORED` rows carry `grade_letter = None`.** A name that was never scored is never
graded — it is listed so its absence is visible, which is the whole point of including it.

## The Analysis Section

Reworked `per_ticker_sections`, one block per stock in the universe:

1. **Verdict line** — posture, grade, status, one sentence.
2. **Component table** — `S_M S_O S_S S_I S_F` with score, `source_quality`, and **legs
   scored vs legs defined** (e.g. `S_S 0.63 · aggregator · 1 of 3 legs`).
3. **Absent legs, named** — every leg that did not score, with its reason.
4. **Catalyst, invalidation, scenario bands.**
5. **Prose** — LLM, unchanged, still behind `assert_authorized_numbers`.

Point 3 is deliberate. `iv_extreme`, `short_borrow` and `executive_tone`
currently renormalize out of their denominators and the matrix prints
`missing_components: []`. The report is where that becomes visible. This spec does not
change the scoring behaviour — that is ticket I15/A4 in
`provider-alternatives-implementation.md` — it only stops the report from concealing it.

## Report Layout

```
Briefing Dashboard · run · date · data <fixture|live>
├─ TRADING IDEAS (graded)          ← new headline
├─ ANALYSIS (per stock)            ← reworked per_ticker_sections
├─ Market Overview
└─ <details> collapsed:
   ├─ Master Alpha Selection Matrix
   ├─ Prior Scorecard
   ├─ Conditionality Table
   ├─ Rejected At Gate
   └─ Evidence Ledger
```

Everything currently rendered stays rendered. `dashboard.json` keeps every existing field.

## Code Style

Matches the existing dashboard layer: frozen Pydantic models with `extra="forbid"`,
module docstring stating the contract, comments explaining *why* a rule exists rather than
what the line does.

```python
class TradingIdeaRow(BaseModel):
    """One graded idea. Python computes the grade; the LLM layer may format it, never alter it.

    `grade_letter` is `None` for an unscored name: a ticker that never produced a
    `ScoringResult` is listed so its absence is visible, not graded on partial data.
    """

    model_config = ConfigDict(extra="forbid")

    ticker: str
    setup_type: str | None = None
    direction: str | None = None            # the direction `alignment` branched on
    grade_letter: str | None = None
    grade_score: float | None = None
    thesis_probability: float | None = None
    thesis_band: str | None = None          # names the band P was read from
    s_cte: float | None = None
    tier: str | None = None
    status: str                              # TRADEABLE | WATCHLIST | BLOCKED | UNSCORED
    catalyst: dict[str, Any] | None = None
    blocked_reason: str | None = None
    grade_penalties: list[str] = Field(default_factory=list)
    headline: str = ""
```

## Testing Strategy

pytest, in `tests/`, no network. Fixture-driven, consistent with the existing suite.

| Level | Coverage |
|---|---|
| Unit — `test_grading.py` | Every band boundary (34/35, 49/50, 57/58, 65/66, 73/74, 81/82, 89/90); each tier ceiling; P-selection for all 10 `SetupType` values; alignment sign logic; both penalties; `P is None` → `n/a` |
| Contract — `test_dashboard.py` | `trading_ideas` present and action-sorted; `UNSCORED` always ungraded; `schema_version == "dashboard.v2"`; every existing section still populated |
| Render — `test_render.py` | Ideas table first in DOM order; detail sections inside `<details>`; empty-state renders "no scored ideas" not a blank table |
| Guard — `test_dashboard.py` | Prose citing a grade passes `assert_authorized_numbers`; prose inventing one fails |

**Required:** a test asserting a Tier C idea with `P = 0.95` grades no higher than `C`.
That is the single rule the whole design exists to enforce.

## Boundaries

- **Always:** run the full suite before commit; keep every existing `dashboard.json` field;
  compute grades in Python only; keep `extra="forbid"` on new models; name the thesis band
  wherever a probability is shown.
- **Ask first:** changing grade weights or penalty magnitudes from the defaults above;
  adding a storage migration to persist grades; removing any currently-rendered section;
  changing `ScenarioTable` or any scoring model.
- **Never:** let the LLM produce or modify a grade; grade an `UNSCORED` name; show a
  probability without naming its band; delete the evidence ledger from the HTML; commit
  secrets or `.env`.

## Success Criteria

1. `dashboard.html` opens on the graded ideas table; no scrolling needed to reach it.
2. Every gate-accepted ticker appears exactly once, with a grade or an explicit `UNSCORED`.
3. A Tier C name never renders above a `C`, at any probability. Enforced by test.
4. `TRADEABLE` rows render before `WATCHLIST`, `BLOCKED`, and `UNSCORED` rows even when a
   later watchlist row has a higher grade.
5. Every non-`TRADEABLE` row states why, drawn from `RejectionCode` — never blank.
6. Each component in the analysis section shows legs-scored-of-legs-defined, so a
   partially-sourced `S_S` is visible as such.
7. `dashboard.json` validates as `dashboard.v2`, retains all v1 fields, and every grade in
   it recomputes from fields present in the same document.
8. `pytest` green; the 370 existing tests still pass.
9. On the current fixture run the table renders a row per scored ticker — today 24, all
   Tier C / WATCHLIST — rather than the three `null` slots of the tactical dashboard.

## Risks

**The pipeline emits 0 tradeable setups.** This spec makes that legible instead of invisible
— the `BLOCKED` and `UNSCORED` statuses exist precisely to say so — but presentation cannot
manufacture ideas. Expect a table of `WATCHLIST` and `UNSCORED` rows until the provider
wiring in `provider-alternatives-implementation.md` lands — **I2** (Wave 0, SEC EDGAR →
`S_I`/`S_F`) and **I14** (Wave 2, self-built IV history). That is the correct outcome, not a
defect in this work.

**Grades over hollow components.** `S_S` scores on 1 of 3 legs today. The grade will look
precise while resting on a renormalized denominator. Criterion 5 is the mitigation: the
number is shown next to how much of it is real. The underlying fix is I15/A4.

## Open Questions

1. **Weights.** `0.60 · P + 0.40 · alignment` — probability-led. Reasonable, or should the
   multi-factor score lead?
2. **Persist grades?** Adding `grade_letter`/`grade_score` to `setup_signal` (migration
   `003`) would let the future T12 calibration ask "do B+ ideas resolve better than C?" —
   which is the question that makes the grade worth having. Recommend yes; it is a
   migration, so it needs approval.
3. **Divergence penalty of 10** — when implied and measured sigma disagree, is a 10-point
   deduction plus a visible flag the right weight, or should divergence cap the grade?
