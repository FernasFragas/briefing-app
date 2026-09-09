# Handoff — 2026-09-03 → next session

Transient working document. Delete it once its contents are folded into
`docs/archive/provider-alternatives-wiring-tasks.md` and `tasks/`.

**Baseline after release round 2: 671 tests passing, zero failures** (verified 2026-09-08,
full suite run, exit 0). Earlier figures in this file — 517, 520, 535, 540, 569, 611, 641,
649 — are historical. Verify before changing anything:

```bash
PYTHONPATH=src .venv/bin/python -m pytest        # expect 671 passed
```

## Release round 2 — 2026-09-08

Lanes G–J are complete; results and evidence are in `tasks/RESULTS.md`, decisions
in `docs/architecture/decisions/` (D9–D12). What a next session most needs to know:

- **A run that reaches no providers now reports `partial`.** All 36 per-ticker recording
  points carry a severity (`docs/architecture/RUN-HEALTH.md`); a warm-up baseline is deliberately
  `normal` and must stay that way, or `partial` becomes the new uninformative constant.
- **Round 1's "live run clean" verification was invalid** and is withdrawn in `RESULTS.md`.
  It read a status that could not fail.
- **Two premises died in round 2.** Alpha Vantage `HISTORICAL_OPTIONS` is not on the free
  tier (it returns a `synthetic` sample payload), so "wait 14 days" was never an option.
  And stored live option metrics come from **CBOE** while the backfill reads **Alpha
  Vantage**, so any spliced IV rank compares two vendors; the backfill now refuses to write
  on a vendor mismatch.
- **D12 is still open** and is the only thing blocking a visibly better product. The
  research that informs it is `docs/research/alternatives/historical-options-sources.md`.
- **The daily run is owner-operated**, not scheduled; the `launchd` install was declined so
  the shared 25/day Alpha Vantage allowance stays under manual control.

## Current release pass — 2026-09-07

This section supersedes the older N-queue notes below where they conflict. The eight
owner decisions are recorded in `docs/architecture/decisions/`; do not re-litigate them from
the stale history in this file.

Implemented in this pass:

- **N6 remains closed. N7 and N8 are withdrawn, not deferred.** D2 chose ALIGN:
  `grade_score = 100 * alignment - penalties`. Thesis probability is display context
  only. N7 moved only the directional side and left the neutral tautology in place; N8 as
  filed inverted the asymmetry by stripping neutral probability while leaving neutral
  alignment under-weighted. ALIGN replaces both.
- **Tier ceilings are now displayed-letter caps.** `grade_score` keeps full 0-100
  resolution for ranking. Tier B cannot display above `B+`; Tier C cannot display above
  `C`.
- **Ideas order is now documented order.** Rows sort by status bucket, then numeric grade
  descending, then ticker. Component set is shown on the row but no longer groups the sort.
- **SPY and QQQ moved to market context.** Index/fund rows are identified through
  `Candidate.is_index_or_etf`, not ticker pattern matching.
- **Fixture snapshot contamination is blocked and purged.** `daily_snapshot` writes are
  refused unless the parent `briefing_run.details.data_mode` is `live`. Local
  `run_id = 2` fixture rows were backed up to
  `data/briefing.sqlite3.backup-20260907-before-fixture-purge` and deleted; verification
  returned `0`.
- **IV backfill command exists.** `briefing_app.cli backfill-iv --dry-run` plans 18
  gate-accepted US tickers x 20 sessions = 360 pairs on 2026-09-07, with 34 already
  stored and 326 remaining on the local database.
- **Inferred catalysts may rank but not anchor event trades.** Event-directional and
  premium event structures still require confirmed dates; watchlist, positional long,
  borrow-dependent short and skew structures carry an inferred-date warning instead.
- **EU names are inactive.** `RHM.DE`, `LDO.MI`, `ASML.AS` and `SIE.DE` are skipped before
  gate evaluation while free EU options coverage remains deferred.
- **API auth fails closed.** Mutating endpoints require a bearer token even when
  `APP_RUN_TOKEN` is unset; a persisted local token is generated under `data/ops/`.
- **Local ops path is launchd.** n8n is retained as optional/manual. The local job script
  runs the daily pipeline, publishes static artifacts, and records `data/ops/last-run.json`.
  The three-consecutive-weekday unattended-run evidence still requires wall-clock time.
- **N5 was stale.** `providers/normalizers.py::parse_datetime` already wraps invalid input
  as `NormalizationError`; no code change was needed in this pass.

Verification in this pass:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q       # 641 collected, passed
PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv --dry-run
PYTHONPATH=src .venv/bin/python ops/status.py --json   # simulated failure surfaces
```

---

## 1. State as of 2026-09-03 (after P4, P5, Q0, the config update, N1 and N4)

### Wired and verified live

| Leg | Chain | Note |
|---|---|---|
| Insider `S_I` | `[sec_edgar, alpha_vantage, fmp]` | Form 4 from the primary record; 10b5-1 / exercises / tax withholding excluded |
| Borrow `S_O` | `[finra]` | Daily short **volume** only, labelled as a proxy on its own field |
| Macro `S_M` | `[fred, fmp]` | FRED primary. Aged by **release date**; current sector exposures verified with 10 cached FRED factor readings |
| **Macro calendar** | **`[fred]`** | **New.** `release/dates`, US only, no consensus estimate. Daily and weekly releases excluded as routine postings, by name. Feeds event risk and the dated table, not the score |
| IV rank + P/C percentiles `S_O` | self-built from `daily_snapshot` | 20-session warm-up, withheld and reported below that |
| Options chain `S_O` | `[cboe, alpha_vantage]` | CBOE carries the live path; AV options remain a metered fallback with no proven free-plan failover |
| Political flow `S_S` | `[fmp senate_latest, fmp house_latest]` | Two market-wide requests per run, locally filtered; capped +/-0.05 overlay |
| Retail momentum `S_S` | `[apewisdom]` | Keyless all-stocks attention feed; `mentions - mentions_24h_ago`, not sentiment |
| **News `S_S`** | **`[finnhub, alpha_vantage, fmp]`** + shortlist | Finnhub does not score its own news, so tone is a local lexicon read labelled `local tone`; ~44-50% of articles measurable. **N4b:** names in `providers.news_alpha_vantage_shortlist` (`DE, ORCL, AVGO, PLTR`) put Alpha Vantage first instead — vendor scoring and relevance bought only for the decision shortlist (`pipeline._news_provider_order`) |
| **Earnings** | **`[fmp, alpha_vantage]`** | **N4a, reordered 2026-09-03.** AV was first and `EARNINGS_CALENDAR` is the one function that refuses; its `malformed` status is not memoised, so it re-spent the budget per ticker every run |
| **Analyst `S_S`** | **`[fmp, finnhub]`** | **New.** Fallback, not a merge. **US names only** — Finnhub's free tier is US-only |
| **Price history** | **`[fmp, twelve_data, alpha_vantage]`** | **New.** Twelve Data backs up the six FMP-gated US symbols; EU names remain paid-plan gated |

`LIVE_UNSCORABLE_LEGS` = `executive_tone`, `risk_reversal_history`.

### Grading and tier behaviour — amended 2026-09-04 → 09-06 by G1–G5

This subsection supersedes what N1 records about tiers and what N2's ceiling table says
about directional setups. The reasoning in both still stands; the behaviour has moved.

| What | Before | Now |
|---|---|---|
| Grade formula | **band-dependent already** — not a G-change; the earlier one-split `0.60 / 0.40` figures in this file predate it | `0.20 * P + 0.80 * alignment` for `above spot` / `below spot`, `0.60 / 0.40` for every other band (`_effective_weights`). G1 documented it; it was in force on the 2026-09-04 run |
| `alignment()` directional branch | raw `\|S_CTE\|` (max 0.317 observed) against a neutral branch returning up to 1.0 | `min(1, \|S_CTE\| / DIRECTIONAL_FULL_CONVICTION)`, `DIRECTIONAL_FULL_CONVICTION = 0.35` — both branches now in 0…1 |
| `REQUIRED_COMPONENTS[V]`, `[E]` | `{S_O, S_M}` | **`{S_O, S_M, S_S}`** |
| `S_S` completeness | `all(s.available for s in sub_scores)` | weighted **base** legs only — `executive_tone` (weight 0.00) and the `political_flow` overlay no longer count |
| Published on `TradingIdeaRow` | — | **`direction`**, and a components-scored count in the HTML ideas table |

**Projected tier spread on the 2026-09-04 published rows: 13 A, 6 B, 2 C** (was 21 of 21

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
Tier A under the old required set). The six B rows are the names whose `retail_momentum`
leg did not read — COST, FDX, GM, JPM, LMT, XOM. **No grade is clamped by its tier ceiling
except QQQ and SPY**, which clamp from 67.89 and 59.19 to the Tier C ceiling of 57.00.

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

**QQQ and SPY are now Tier C, and therefore never tradeable.** `ConfidenceTier.C.is_tradeable`
is false. This arrived by composition rather than by decision: an index has no issuer, so it
has no analyst leg (PC3, an earlier declared policy), so `S_S` is structurally `unavailable`,
so it fails a required set that now contains `S_S`. Defensible, but nobody chose it — **an
index exemption from the required set is open.**

**Read the tier counts as a projection, not a measurement.** They are computed *onto* the
2026-09-04 published rows, which were produced by the pre-fix code; the grade values quoted
(67.89, 59.19) are that run's own published numbers and the ceiling is a constant, but no
live run has yet been made under the new behaviour. One is being done separately.

### Credentials — all set except Quiver

```
ALPHA_VANTAGE_API_KEY  SET, LIVE — see Q6. Probed 2026-09-02: 6 of 7 functions answer
FMP_API_KEY            SET
FRED_API_KEY           SET, wired, verified
FINNHUB_API_KEY        SET, wired, verified live 2026-09-01
TWELVE_DATA_API_KEY    SET, wired, verified for the six US gated symbols
QUIVER_API_KEY         EMPTY (optional; FMP covers political flow)
```

### Probe results, 2026-09-01 — through the shipping client, not curl

| Ticker | Endpoint | Result |
|---|---|---|
| NVDA | `company-news` | ✅ HTTP 200, **247 rows**, all normalized, 124 scored |
| NVDA | `stock/recommendation` | ✅ HTTP 200, **4 monthly rows** |
| RHM.DE | both | ⛔ refused **before the request**, on the US-only rule |

### Probe results, 2026-08-31 — still current

**Finnhub free tier:** `stock/price-target` 403, `stock/transcripts/list` 403 (settles
PA10), `news-sentiment` 403 (which is why news needs local scoring), `RHM.DE` 403
(free tier is US-only).

**Twelve Data free tier — settles A1 and half of A2:**

```
AVGO ORCL MU QQQ CRWV AMAT   ✅ all six FMP-gated symbols resolve
RHM.DE / LDO.MI              ❌ 404 "available starting with the Grow/Venture plan"
```

---

## 2. Work queue

Nothing is blocked on a signup. P1–P5 are done; **the next steps are below**, then the
history.

### ▶ Next — in this order

**N6. Give a directional thesis a probability that actually varies. — ❌ CLOSED, remedy
disproved 2026-09-06.** `docs/research/alternatives/directional-probability.md`.

The premise held and was **stronger** than filed: directional `P` measured a spread of
**0.0490** across 12 rows on 2026-09-04, and on every `measured_sigma` row it is *exactly*
`0.5000`. It carries no information.

The proposed fix does not exist and cannot be built cheaply. **`strategy.models.Setup` has
no target field** — it carries `range_low`/`range_high` (the measured ±1σ edges), an
optional `Invalidation`, and the scenario table. Nothing in `src/` computes a price target,
so "probability of reaching the target" would first require inventing a target rule, which
is a product decision rather than a grading fix.

Six alternatives were computed on real data across two runs and all rejected. The reason is
structural and is why this is closed rather than deferred: **a distribution centred on spot
cannot express direction.** Two worth naming so they are not re-tried — `rr_25d` is a real
market-implied tilt but already feeds `sub_scores["skew"]` inside `S_O` and therefore
`S_CTE`, so using it as `P` double-counts the same evidence on both sides of the formula;
and repairing `_fraction_above_spot` to the exact lognormal would *shrink* the spread to
0.0155 and make `P` a monotone function of sigma alone. Correct, and strictly worse as a
grading input.

**N7. Set `directional_probability_weight = 0.0`. — FILED, not applied (decision,
2026-09-06).** The honest response to a term measured at spread 0.049: stop paying it
weight. Directional raw becomes `100 * alignment`, the range widens to 0–90.5, the
strongest directional row takes rank 1, and a row whose `S_CTE` contradicts its own
direction correctly scores 0. It is free — `directional_probability_weight` is already a
config field (`config.py:153`) and `_effective_weights` already returns `(w, 1-w)`. The
only work is updating the tests that assert the current directional raw. Deliberately not
applied: the owner chose to keep the ladder stable while N8 is open, since both change the
same scale and doing them together would make neither measurable. Print `P(above spot)` as
context if it is wanted in the report — it is a fact about the distribution, just not one
that should grade anything.

**N8. The neutral base-rate floor — the actual defect. — OPEN, and now the top of this
queue.** The head start is not that directional rows are underpaid; it is that **neutral
rows are paid `0.60 * 0.683 = 41` points for the *definition* of the band they are measured
over.** That is a tautology, not evidence. Four rows on 2026-09-04 (AMZN, FDX, JPM, XOM)
sit at 40.97–43.06 on alignment **0.000** — scoring in the 40s having demonstrated nothing.

The fix is to score **excess over the null model**: `(P - P_null) / (1 - P_null)`, where
`P_null` is what the measured-sigma lognormal already implies for that same band. Measured,
it is the best result of anything tested — interleaving jumps to 52/108 and 62/108, and
every `measured_sigma` neutral row correctly collapses to excess `0.000`, because with no
chain the table contains no information and this says so instead of paying 41 points for it.

**Do not fold this into N7.** It is a re-scaling of the whole grade: at 0.60 weight the top
score is 53.18 and 19 of 21 rows land `F`, so `_LETTER_BANDS` and `_TIER_CEILINGS` were cut
against the old scale and would need re-cutting with it. It also needs `_fraction_above_spot`
repaired first — the two `measured_sigma` directional rows leak excess 0.0129/0.0158, which
is exactly that interpolation artefact. Own task, own before/after ladder, own live run.

**G1–G5. The grading audit — ✅ Done 2026-09-04 → 09-06.** Trigger: a readiness audit of
live run `daily-2026-09-04-de8fa872` found the grade column ranked by *setup type*, not by
quality. All nine `within 1 sigma` rows scored 40.97–83.82; all twelve `above spot` rows
scored 5.68–34.75. Empty corridor between them, zero overlap, and the single `TRADEABLE`
idea (ORCL, 34.75) graded `F`. The audit's own numbering runs `G1`–`G5`; only the items
that changed behaviour or a premise are recorded below.

- **G1 — diagnosed, and there was no defect.** The opening claim, that grades could not be
  recomputed from published fields, **was wrong, and the error was in the analysis rather
  than in the code.** `compute_grade` already used a band-dependent split via
  `_effective_weights()` — `0.20 * P + 0.80 * alignment` for `above spot` / `below spot`,
  `0.60 / 0.40` otherwise. It is written down in `docs/product/SPEC-graded-ideas-report.md` and was
  already pinned by a test. Reconciled against the correct split, **19 of the 21 published
  rows recompute to diff 0.00**. Recorded as a corrected premise, not as a fix.
  *An ergonomics wrinkle, not a gap:* a row carrying `crowding_penalty` reconciles only if
  you supply the penalty's magnitude, `crowding_penalty_scale * (1 - confidence_multiplier)`.
  `grade_penalties` names the penalty but never its size. `confidence_multiplier` **is**
  published — at `per_ticker_sections[].gate.confidence_multiplier`, on every section — so
  T9's "recomputes from fields present in the same document" does hold; verified on the
  2026-09-06 live run, where **18 of 18 rows reconciled to diff 0.00 including AAPL's
  crowding penalty**. What it is not is *row-local*: a reader of the ideas table alone must
  cross-reference the per-ticker section. Publishing the penalty magnitude on the row would
  close that.
- **G2 — the real defect.** `alignment()` returned values on **incompatible scales**: `1.0`
  for a neutral setup sitting inside the band, versus `|S_CTE|` — observed max **0.317** —
  for a directional one, feeding a term worth 40 points for neutral and 80 for directional.
  Both branches now return conviction units in 0…1. This, not the bands, is what produced
  the empty corridor.
- **G2b — the denominator.** Dividing the directional branch by `NEUTRAL_BAND` (0.15)
  over-corrected into saturation: every row past the band edge scored identically, because
  `NEUTRAL_BAND` marks the point of *minimum* directional conviction, not maximum.
  `DIRECTIONAL_FULL_CONVICTION = 0.35` replaced it — the smallest denominator above the
  largest observed `|S_CTE|` (0.317, ORCL), so no live row clips. 0.25 and 0.30 were both
  tested and rejected: the strongest row still saturated at each.
- **Auditability — `direction` is now published** on `TradingIdeaRow` and rendered as its
  own HTML column. It is needed because `alignment()` branches on **direction** while
  `_effective_weights()` branches on **band**, and for a `beyond +/-1 sigma` band the
  direction is not implied: a skew structure and a neutral straddle published identical
  fields and graded differently, and neither row could be checked.
- **G3 — mixed formulas made visible.** The 21 rows were scored on different component
  sets — 11 names on four components, 8 on three, and QQQ and SPY on **two** (55% macro,
  45% options after renormalization) — then sorted into one column with no marker. The
  ideas table now renders a scored-components count beside the grade, flagged when it falls
  below `THIN_COMPONENT_COUNT`.
- **G5 — the tier badge earns its place.** `REQUIRED_COMPONENTS` for `V` and `E` gained
  `S_S` (was `{S_O, S_M}`). Before that, 21 of 21 rows were Tier A, the ceiling never bound,
  and the badge beside each grade carried no information — the open decision N1 recorded.
- **The fix that made G5 work, and the reason to remember it.** As first applied, G5
  produced **19 Tier B and 2 Tier C, with nothing reaching A** — "always A" simply became
  "always B". The cause was in `components/sentiment.py`, not in the tier logic: it judged
  completeness with `all(s.available for s in sub_scores)`, which counted `executive_tone`
  (declared permanently `n/a`, weight **0.00**) and `political_flow` (a capped overlay, not
  a base leg). So `S_S` could never read `verified` for any name on any run, and **a
  required component that can never be verified caps the whole universe by construction.**
  Completeness is now judged on weighted base legs only. Projected result: **13 A, 6 B,

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
  2 C** — see §1.

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

**N1. Re-run live, then preflight `--deep`. — ✅ Done 2026-09-03.**

Live run `daily-2026-09-03-c7e82663` (14:02–14:07 UTC) finished `succeeded` on the
current 14-sector config: **23 scored, 4 tradeable, 19 watchlist, 0 failures, 0
diagnostics**. Preflight regenerated at `2026-09-03T13:10:58` (`output/preflight/latest.json`).
The earlier 14:01 attempt `daily-2026-09-03-74970df5` came back `partial` with 23 failures
and is superseded by the 14:02 run; `daily-2026-09-03-fb78f201` (13:05) is the pre-N4
run and differs only in matrix size.

**This supersedes every live number written before it.** `POST-P3-DECISIONS.md` and
`docs/archive/still-failing.md` still describe the 4-sector config and the
2026-09-02 run; treat their live counts as historical, not current.

Three results that were not predicted and matter more than the refreshed letters:

- **The confidence tier stopped discriminating: 23 of 23 names are Tier A** (was 5 A /
  4 B / 15 C). This is mechanically correct, not a bug — `REQUIRED_COMPONENTS` for the
  enabled classes `V` and `E` is `{S_O, S_M}` (`models/scoring.py:33`), `_confidence_tier`
  floors only on the *required* set (`scoring.py:529`), and P4/P5 plus the sector-exposure
  rows made `S_M` `verified` for every name while `S_O` already was. `S_S` is `partial`
  and `S_I`/`S_F` are `unavailable` on most names, and none of that reaches the tier.
  **Consequence: the tier ceiling in `grading.py` no longer caps any row**, so the tier
  badge beside each grade now carries no information. Worth a deliberate decision — either
  widen the required set for `V`/`E`, or let the grade carry the confidence signal alone.
  **Decided 2026-09-06 by G5: widen it.** `REQUIRED_COMPONENTS[V]` and `[E]` are now
  `{S_O, S_M, S_S}`, and the projected spread is 13 A / 6 B / 2 C. The `scoring.py:33`

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
  line reference above is stale; the set now sits at `models/scoring.py:39`.
- **Grade and tradeability are anti-correlated.** All four `TRADEABLE` rows grade `D` or
  `F` (ORCL 41.03 `D`, DE 39.46 `D`, AVGO 36.74 `D`, PLTR 27.93 `F`), while all six `A`/`B+`
  rows are `WATCHLIST`, every one blocked on `iv rank unavailable: no IV rank history for
  this name` (MSFT 84.49 `A`, then FDX, XOM, JPM, QQQ, SPY). The table sorts by
  `grade_score` descending, so **the top of the graded report is currently its least
  actionable part.** Not a defect in either mechanism; the report just does not yet say
  which of the two orderings the reader should act on.
- **Persistence works now, and the warm-up clock has started.** The run recorded
  `storage_run_id: 1`, and the self-built baselines report `0 of 20 sessions stored`
  rather than the old `no database is configured`. So `PC1-LIVE-11` / `PC1-RAW-14` are
  closed as an *operational* blocker; what remains is elapsed time — roughly 20 trading
  sessions from 2026-09-03, so **early October** before `iv_rank` and the put/call
  percentiles exist. That single dependency is what holds the six best-graded names out
  of tradeable status today.

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

**N2. Fix the `P(thesis band)` defect (Q5) — ✅ Done, and live-verified 2026-09-03.**
Directional setup types now use `above spot` / `below spot` probability rather than the
one-sigma tail. N1 confirms the fix on live data: the graded population now spans
`A` 84.49 down to `F` 22.22 (1 A, 5 B+, 8 D, 9 F), where the pre-fix live run topped out
at `B+` and the pre-fix fixture run produced nothing above `D`.

*Independently verified 2026-09-02.* Best achievable grade — perfect alignment, no
penalties, Tier A, symmetric normal scenario table:

| Setup family | Band | P | Ceiling |
|---|---|---|---|
| Iron condor | `within 1 sigma` | 0.683 | 80.96 `B+` |
| **Directional** (all six types) | `above`/`below spot` | 0.500 | **70.00 `B`** — was 49.52 `D` |
| Straddle / calendar / skew | `outside 1 sigma` | 0.317 | 59.04 `C+` |

> **The directional row is superseded by G2/G2b (2026-09-06).** It was computed under the
> old `0.60 / 0.40` split with `alignment = |S_CTE|`. Under `0.20 * P + 0.80 * alignment`
> with the conviction-unit branch, a perfectly aligned directional setup ceilings at
> `100 * (0.20 * 0.500 + 0.80 * 1.0)` = **90.00 `A+`**, and "perfect" now means
> `|S_CTE| >= 0.35` rather than `|S_CTE| >= 0.15`. The other two rows are computed on the
> neutral branch, which G2 did not touch, and still hold.

A fixture run before the fix gave 9 `D` / 15 `F`; after it, **24 `D` and no `F` at all**.
The whole live population is covered: all 24 names are `watchlist_no_trade` (23) or
`event_directional_vertical` (1), both on the fixed path.

**Residual, not yet decided.** `long_premium_straddle`, `long_premium_calendar` and
`skew_structure` still read `1 - P(within 1 sigma)` and so cap at `C+`, 22 points below a
condor. That is the same conflation in smaller form — a straddle's thesis is *genuinely*
~32% likely, but likelihood is not value, and a straddle priced at 20% against a 32% chance
is a good trade the grade cannot see. **None of these three types occurs in the live run**,
so it is theoretical today and becomes real the moment the strategy engine emits one.

**N3. Answer Q1 / Q1b / Q3 / Q4 — ✅ Done 2026-09-02.** All four are implemented under
the redistribute-weight principle from `POST-P3-DECISIONS.md` §5. Details in §3 below and
in that memo's §5. Suite is **535 passing** (was 522). What changed, in one line each:

- **Q1** — `executive_tone` carries a permanent `n/a` reason naming the 402/403 that make
  it unsourceable, its 0.35 still redistributes, and `S_S` now discloses on every run that
  it has no first-party issuer voice.
- **Q1b** — the institutional leg's parts carry explicit weights (`ratings` 0.35,
  `revisions` 0.25, `price_target` 0.15, `news` 0.25) instead of an unweighted mean, and
  the news part is **capped at its own 0.25**. News is 0.25 of the leg whether it sits
  beside three analyst parts or one, so its 17.3% → 69.2% swing is gone.
- **Q3** — `retail_momentum` is capped at its nominal **0.20**; `institutional` absorbs
  the rest, so `executive_tone`'s absence no longer promotes it to 0.308.
- **Q4** — `S_F` is declared permanently `n/a` in `DECLARED_UNSCORABLE_COMPONENTS`, both
  run modes report the same reason, `providers.institutional` is `[]`, and the two S_F
  preflight probes and the live ownership fetch are gone (they cost AV quota for a
  component nothing consumed).

**One shared mechanism carries Q1b and Q3.** `SubScore.max_weight` is a ceiling on the
share re-normalization may hand a leg, honoured in `combine_sub_scores`, and it is used at
both levels — parts inside the institutional leg, legs inside `S_S`. Its third rule is the
one to know: **a capped leg needs an uncapped one to absorb what re-normalization frees, so
a component made only of capped legs is `n/a`.** That is what makes "retail is never the
thesis" and "the lexicon does not stand in for analyst coverage" arithmetic rather than
prose. Two behaviours follow that were not separately decided:

- a name whose only sentiment inputs are news and retail now scores `S_S` `n/a` rather
  than a lexicon-and-mentions number. `S_S` is not required for `V`/`E`, so this drops
  0.20 of weight and redistributes; it does not floor a tier.
- the `political_flow` overlay is no longer applied when no base leg scored. It was
  reachable before and would have made `S_S` = ±0.05 off a congressional disclosure alone.

**Measured 2026-09-03 by N1.** `S_M` moved as expected: `verified` for all 23 scored
names, which is what collapsed the tier spread to 23 A (see N1). `S_S` is `partial` on
every name — the `max_weight` caps and the permanent `executive_tone` `n/a` are visible
in the live output rather than only in the arithmetic. No name scored `S_S` as `n/a`
outright in this run, so the "capped legs only" path did not fire live.

**N4. Act on Q6 — which legs AV should carry. — ✅ Done 2026-09-03.** Plan and evidence:
**`docs/research/alternatives/q6-alpha-vantage-allocation.md`**.

The constraint that shapes it: **AV allows 25 requests/day and the universe is 24 tickers**,
so AV can carry **at most one per-ticker leg**, and whichever leg the pipeline reaches first
takes the budget regardless of merit.

- **N4a** — `earnings: [fmp, alpha_vantage]` is now in config and defaults. N1 verified
  the falsifiable prediction from the other side: after live + deep preflight, AV had
  `earnings_calendar: 1`, from deep preflight only, not ~24 from the live run.
- **N4b** — AV news now requests `limit=1000`. Same-ticker probe, NVDA on 2026-09-03:
  Finnhub returned 250 rows / 111 locally scored; AV returned 1000 rows / 1000 scored
  with relevance fields. Decision: **C, hybrid shortlist**, not universal AV-first.
  Current shortlist is seeded from N1 tradeable names: `DE`, `ORCL`, `AVGO`, `PLTR`;
  refresh policy is Phase C in `docs/archive/provider-alternatives-wiring-tasks.md`.
- **N4c** — unchanged by design. `insider`, `institutional`, `prices`, and `options`
  should not take the AV slot; the reasons in the Q6 memo still stand.

**N5. Harden `parse_datetime`** the way `parse_date` now is — same three lines, still
exposed. **Confirmed still open 2026-09-03:** `providers/normalizers.py:2665` calls
`datetime.fromisoformat(text)` bare, so an unparseable timestamp raises `ValueError`
rather than `NormalizationError` and fails the whole ticker instead of degrading one leg.
`parse_date`, directly below it at :2669, is the hardened shape to copy. Small; do it
whenever. ~~**This is now the only open item in the N-queue.**~~ **No longer true as of
2026-09-06:** N6 is open and sits above it.

**Deliberately not next:** `S_F` (Q4). It is 0.10 of the US formula and a project — filer
universe, migration, two-quarter diff — while N1–N4 are hours and touch every row.

---

### History

### P1 — `political_flow` + `retail_momentum` (I12 / PB6) — ✅ Done 2026-09-01

Evidence: `docs/research/alternatives/pa6-political-and-retail.md`.

### P2 — Finnhub news + analyst (I6, I9, I11 / PB3, PB9-analyst) — ✅ Done 2026-09-01

Full evidence: `docs/research/alternatives/pb3-finnhub-news-and-analyst.md`. In short:

- `providers/finnhub.py` — `company_news` and `recommendation_trends`. Free tier is a
  **rate limit** (60/min), not a daily allowance, so the budget policy paces at 1.05s and
  declares `daily_requests=None`.
- **US-only is enforced before the request.** An exchange suffix longer than one character
  is refused without spending quota, and the refusal is raised directly rather than
  returned through `_response`, so a symbol boundary is never memoised as an endpoint plan
  gate. `BRK.B` is deliberately not caught by that rule.
- `providers/news_tone.py` — the local lexicon standing in for the scored feed AV used to
  supply. Alpha Vantage's scale and bands, so a mid-chain fallback does not change what a
  score means. **An unmatched headline scores `None`, never `0.0`.**
- Analyst is a **fallback, not a merge**: both feeds report the same buy/hold/sell counts,
  so running both would double-weight one quarter's consensus.

**What this did not close:** price targets (FMP only), `executive_tone` (403), and EU
analyst/news (no free source).

### P3 — Twelve Data for the six gated symbols (I8, I13 / PB4) — ✅ Done 2026-09-02

All six resolve and the chain is now `prices: [fmp, twelve_data, alpha_vantage]`. This
lifts CRWV and AMAT off the Tier C floor they sat on for want of price history — no price
history meant no realized vol, no measured sigma, and a universal Tier C floor.

Implementation: `providers/twelve_data.py`, `normalize_twelve_data_time_series`, registry
entry `twelve_data.time_series`, `RequestBudget` policy, and the live `_price_bars`
fallback branch. Verified with focused client/normalizer/preflight/orchestration tests.

### P4 — Macro calendar — ✅ Done 2026-09-02

Evidence: `docs/research/alternatives/p4-macro-calendar.md`. `macro_calendar` is built from FRED
`release/dates` via the same join the ageing fix uses, asked forwards instead of backwards.
Closes the coverage-matrix row that had **never** had a source.

Four things the ticket did not anticipate, all found by probing through the shipping
client rather than reasoning about the endpoint:

- **A routine posting is not a catalyst.** Nine of the eleven mapped series sit on releases
  that publish daily (H.15, Interest Rate Spreads, ICE BofA) or weekly (H.10 FX, Spot
  Prices, NYMEX Nat Gas). `build_fred_macro_calendar` drops any release publishing weekly
  or more often and records the cadence as a diagnostic. Live on 2026-09-02 the window held
  two entries — CPI on 09-11, GDP on 09-30 — and `event_risk` came out at 0.47.
  **The threshold moved once already.** It first cut below 7 days, on the theory that
  weekly jobless claims are a catalyst; P5's three weekly releases land on exactly 7 and
  slipped through, putting 16 rows in the calendar and pegging `event_risk` at 1.0. Every
  weekly release this app maps is a *price posting*, which carries no information at
  publication. Cadence is only a proxy for that and cannot tell the two apart at 7 days —
  so a genuine weekly statistical release would now be dropped too. Revisit with a named
  exception list the first time one is mapped.
- **An empty forward window is an answer, not a failure.** A monthly release has no date in
  most 30-day windows; FRED answers `{"count": 0, "release_dates": []}`, which
  `validate_payload` scored as a missing required path. The forward call now requires
  `realtime_start` — echoed by every real response, absent from FRED's error body — so
  nothing scheduled no longer logs as a provider outage while a real failure still raises.
- **`release/dates` now answers two questions**, so it is asked twice per release and needs
  two cache slots (`<release_id>` and `<release_id>_upcoming`). The historical window still
  stops at the run date: a future release date reaching back into the ageing join would
  stamp a published reading with a publication that has not happened.
- **No consensus estimate.** FRED publishes a schedule, not a survey, so the calendar adds
  nothing to `S_M`'s score. The readings path still does all the scoring.

FRED also gained a `RequestBudget` policy: no daily cap (FRED publishes none) and 0.5s
pacing, which matters more now the calendar doubles the `release/dates` calls.

### P5 — Map the seven unmapped macro factors — ✅ Done 2026-09-02

`real_yields`, `credit_spreads`, `dollar`, `brent`, `wti`, `copper` and `natural_gas` now
map to `DFII10`, `BAMLH0A0HYM2`, `DTWEXBGS`, `DCOILBRENTEU`, `DCOILWTICO`, `PCOPPUSDM` and
`DHHNGSP`. Landed the same day by a parallel session, and `tests/test_pipeline.py` gained a
coverage test asserting every declared sector sensitivity has both a mapped series and a
factor bucket, so the gap cannot silently reopen. All seven score through
`release_change_reading`. Their releases are 18, 209, 17, 212 (brent and wti share it),
365 and 342 — and all but 365 are excluded from the calendar as routine postings, so those
factors score in `S_M` and never appear as dated events. `copper` is load-bearing evidence
for the release-date join: `PCOPPUSDM`'s newest period is 63 days old against a 45-day
bound and scores **only** because it is aged from its 2026-08-17 publication.

### Deferred, each with a written reason

- **`S_F` / 13F** — blocked by design, not wiring. `docs/research/alternatives/pb1-13f-blocker.md`.
- **FCA / EU sources** — `pb5-fca-deferred.md`, `pa5-eu-sources.md`.
- **CBOE failover (Tradier)** — redundancy for a source that has not failed.
- **Phase C** — `PC1` is regenerated in `docs/archive/still-failing.md` from the
  2026-09-03 deep preflight plus live run `daily-2026-09-03-c7e82663`. `PC2`-`PC4`
  executed on the same day; the remaining open rows are `PC1-LIVE-12`, the data-state
  decisions, EU manual/browser captures, and the narrowed QQQ symbol gate.

---

## 3. Questions for you

> **These are answered.** `docs/archive/POST-P3-DECISIONS.md` works through Q1–Q6 against live
> output and recommends an order. The sections below are kept because they carry the
> reasoning and the constraints; where the memo has decided something, it says so inline.
> **Q1, Q1b, Q3 and Q4 closed 2026-09-02 (N3)** — each carries its answer inline below.

**Q0 — closed 2026-09-02.** The scheduled Alpha Vantage
`HISTORICAL_PUT_CALL_RATIO` path was dropped instead of guarded. It contributed nothing to
the live score because option-derived put/call baselines are self-built from persisted
CBOE snapshots, and it was the path spending the AV daily budget. The realtime endpoint
has no top-level date sentinel and remains registered only as its own path.

**Hardened as well as dropped, 2026-09-02.** Dropping the caller removes the one path that
reached the sentinel; it does not stop the next provider sending one. `parse_date` now
raises `NormalizationError` — which every normalizer is already called inside — instead of
the bare `ValueError` `fromisoformat` throws, so an unparseable date degrades one leg into
a recorded issue rather than failing the ticker. Absent dates (`None`, `""`) still resolve
to today, because every caller's `if not as_of: continue` guard depends on that.
`NormalizationError` subclasses `ValueError`, so the change is additive.

The guards already in the file do **not** cover this: they test for a *missing* date, and
`"latest"`, `"N/A"`, `"-"` and `"0000-00-00"` are all truthy strings that pass them. Three
tests pin it. **`parse_datetime` still has the same exposure** and is called directly by
several normalizers (`normalize_fmp_economic_calendar` among them) — same three-line
treatment, not yet applied.

**Q1 — answered 2026-09-02: redistribute, and say so.** `executive_tone` is recorded
permanently `n/a` with a reason that names the 402/403 rather than reading as a reading
that did not arrive (`sentiment.EXECUTIVE_TONE_NA_REASON`), its 0.35 still redistributes,
and `S_S` appends a diagnostic on every run stating it has no first-party issuer voice.
The parameter stays: the leg is declined, not deleted, and one transcript source reverses
it. Original question below.

**Q1 — `executive_tone` (0.35 of `S_S`). Definitively unsourceable on free tiers.**
FMP transcripts 402, Finnhub transcripts 403. Per PC3 it should be recorded permanently
`n/a`. That leaves a third of `S_S` structurally absent, so: **redistribute its weight
across the surviving legs, or shrink `S_S`'s confidence instead?** These give different
scores from the same data. Current code silently redistributes — which was never a decision,
just the default. *(A3 + A4, and it blocks PC3.)*

**Q1b — answered 2026-09-02: no haircut; fix the share instead.** The institutional
leg's parts now carry explicit weights — `ratings` 0.35, `revisions` 0.25, `price_target`
0.15, `news` 0.25 — and the news part is capped at its own 0.25 by `SubScore.max_weight`.
So news is 0.25 of the leg regardless of how many analyst parts scored, and because a
capped part needs an uncapped one to absorb the rest, **news alone does not constitute the
leg**: with no analyst part the leg is `n/a` rather than a half-measured lexicon read at
full weight. The lexicon's coverage is unchanged; what changed is that its influence no
longer rises as corroboration falls. Original question below.

**Q1b — new, and the same shape.** The news leg is now scored by a **lexicon**, not by a
vendor. Its measured coverage is ~50% of articles; the other half are excluded from the
mean rather than counted neutral. Should the news read carry **full weight inside the
institutional leg, or a confidence haircut** reflecting that it is a local approximation?
The code currently gives it full weight, which — like Q1 — is a default, not a decision.

**Q2 — EU names.** `RHM.DE` and `LDO.MI` are **permanently Tier C**: no options chain
exists at any price on a free tier (PA5 is a structural reject), Twelve Data gates both
behind paid plans, and Finnhub's free tier refuses them too — so they now have no news and
no analyst redundancy either. They will appear every day as watchlist rows with a named
reason. **Keep them as context, or drop them from the universe?** *(A2. The US half
evaporated — all six gated US symbols resolve on Twelve Data.)*

**Q3 — answered 2026-09-02: capped at its nominal 0.20.** `retail_momentum` carries
`max_weight=0.20`, `institutional` absorbs the remainder, and redistribution stays the
rule everywhere else. Retail alone can no longer carry `S_S` — with nothing uncapped to
absorb the freed weight the component is `n/a`, which is the arithmetic form of the rule
this module already stated in prose: retail is the 20 percent leg and never the thesis.
Original question below.

**Q3 — Retail momentum weight.** ApeWisdom gives mention counts, not sentiment; the signal
is noisy and gameable. **Cap it below its nominal 0.20, or let it score at full weight?**
*(A7.)*

**Q4 — answered 2026-09-02: declared permanently `n/a`.** `S_F` is in
`pipeline.DECLARED_UNSCORABLE_COMPONENTS` — a separate list from `LIVE_UNSCORABLE_LEGS`,
because this is a source that exists and was declined rather than one that does not exist.
Both run modes build the same `n/a` component with the same reason, `_refuse_fabricated_legs`
rejects a fixture that scores it, `providers.institutional` is `[]`, and the live ownership
fetch plus the two `S_F` preflight probes are removed — they were spending Alpha Vantage's
metered budget on a component nothing consumed. **The cost is stated, not hidden:** `S_F`
is in the required set for classes `P` and `S`, so both are pinned to Tier C while this
stands; `enabled_expression_classes` is `[V, E]`, so the shipped universe is unaffected.
A test pins that pairing so enabling `P` cannot quietly inherit it. Original question below.

**Q4 — `S_F` (institutional, 0.10 of the US formula).** Closing it needs a curated filer
universe, a new table plus migration, and a two-quarter diff — a project, not a ticket.
**Invest in that, or declare `S_F` permanently `n/a` and redistribute?** Routing it through
an aggregator was already rejected: EDGAR is the primary record and an aggregator would
downgrade source quality on the one component whose value is reading the original filing.

**Q5 — Grade bands. Answered in `docs/archive/POST-P3-DECISIONS.md`: leave the edges alone.**
The "9 D / 15 F, nothing above D" figure was the *fixture* run and is superseded — live run
`daily-2026-09-03-c7e82663` spans `A` 84.49 down to `F` 22.22. Confidence tier no longer
discriminates on that run (23 of 23 scored names are Tier A), so the grade now carries the
ranking signal.

The reason not to re-tune was the important part: the grade was close to a relabelling of
"is this thesis directional or not". `thesis_probability` reproduced the geometry of the
sigma bands rather than anything name-specific — `within 1 sigma` scored ~0.683 and
`beyond +1 sigma` ~0.159 *by construction*, matching the textbook normal to three decimals.
With `raw = 100 × (0.60 × P + 0.40 × alignment)`, a directional setup with **perfect**
alignment, zero penalties and Tier A topped out at **49.52**, while `C` starts at 50.

**Answered 2026-09-02:** keep the letter bands and change the input. Directional setup
types now read `probability_above_spot` / `probability_below_spot`: same-side tail mass
plus the favorable share of the central band. A textbook directional setup now reads
`P≈0.50`; with perfect alignment its raw grade is `70.0`, so directionality no longer caps
the row below `C`.

*(Note: `POST-P3-DECISIONS.md` §2 writes the formula as `100 × (probability × alignment)`.
It is a weighted **sum**, not a product — `grading.py` uses
`probability_weight * P + alignment_weight * alignment`. The historical arithmetic above
uses the code.)*

**Q6 — Alpha Vantage. The premise this question rested on is withdrawn.** AV is **not**
refusing every function. Probed through the shipping client on 2026-09-02, one ticker
(AAPL), after the daily quota reset:

| Function | Result |
|---|---|
| `GLOBAL_QUOTE` | ✅ HTTP 200 |
| `NEWS_SENTIMENT` | ✅ 50 articles, **all 50 vendor-scored**, with per-ticker relevance |
| `INSIDER_TRANSACTIONS` | ✅ 7,146 rows |
| `INSTITUTIONAL_HOLDINGS` | ✅ 6,479 holdings |
| `TIME_SERIES_DAILY` | ✅ 100 bars, newest 2026-09-01 |
| `REALTIME_PUT_CALL_RATIO` | ✅ full chain 0.52, and it **normalizes cleanly** |
| `EARNINGS_CALENDAR` | ⛔ the only refusal — a CSV body with no row wider than one character per column, caught by `validate_text_data_payload` |

**The daily quota does reset.** That was never verified before and the docs said so; it
had, by the time of this probe.

So the question is no longer "demote or drop". It is **which legs should AV now carry**,
and two of them are decisions with real consequences:

- **News.** `providers/news_tone.py` exists because AV's scored feed was believed dead, and
  it measures ~50% of articles with a local lexicon. AV scored **100%** of the sample, with
  per-ticker relevance the lexicon cannot produce. That is Q1b's premise reversed: the
  haircut question becomes whether to use the lexicon at all.
- **Institutional.** `S_F` was deferred as a project (Q4) partly because AV was dead.
  `INSTITUTIONAL_HOLDINGS` answers with 6,479 holder rows. This does **not** close `S_F` —
  `pb1-13f-blocker.md` rejects an aggregator on source-quality grounds, and that objection
  is unaffected by the endpoint working — but Q4 should be re-read knowing the data is
  reachable.

Nothing was rewired. The chains are unchanged pending this decision.

**Plan: `docs/research/alternatives/q6-alpha-vantage-allocation.md`** (see N4 above). Two corrections
to this section from that work: the news comparison omits article counts and is not the
one-sided case it reads as, and the free tier's **25 requests/day against 24 tickers** means
adopting any per-ticker AV leg consumes essentially the whole budget.

---

## 4. Things a fresh session will not infer from the repo

1. **Two unrelated wave numberings.** `tasks/` uses **Stages 1–5** (`T1`–`T9`, the graded
   report — complete). `docs/archive/provider-alternatives-implementation.md` uses **Waves 0–3**
   (`I0`–`I16`, provider wiring). A bare "Wave N" always means the latter. Both files carry
   a note saying so.

2. **The repo's own doctrine is "verify the premise before building."** It paid off
   repeatedly and should not be skipped:
   - PB1's ticket said EDGAR's code "already exists and passes tests". **Both normalizers
     were scaffolding** — 19 helpers referenced, none defined, zero tests. They imported
     cleanly because Python resolves names at call time.
   - PA2 and PA7 closed on **disproof** — the gap was an unsupplied argument, not a missing
     vendor.
   - PA6 found the political leg served by a provider already keyed.
   - PB5's ticket said "the loaders are already written." They aren't — that referred to the
     manual EU loaders, not FCA.
   - **PB3 (2026-09-01):** probing through the *shipping client* rather than `curl` is what
     caught the lexicon's real defect — headlines are written in the past tense, and a
     present-tense-only lexicon scored "Stock Tumbled" as unmeasurable. Coverage went 47% →
     50% once the inflections were added. A `curl` probe would have proved the entitlement
     and missed the bug entirely.

3. **The fixture path lies about coverage.** Fixture `S_S` reports `available=True` with all
   three legs present and `na_reason=None`, including the ones with no live source. Any
   claim about leg coverage must be checked against a hand-built `ComponentResult` or a live
   run — never a fixture run. `LIVE_UNSCORABLE_LEGS` plus `_refuse_fabricated_legs` exist to
   catch exactly this; keep them current when a leg gains a source.

4. **A refusal is never cached, and a cached payload is not evidence.** 47 files under
   `data/raw/alpha_vantage/` were once refusals wearing HTTP 200, and were purged. The
   directory now holds **25 genuine payloads**, so the rule cuts both ways and matters more,
   not less: entitlement is proven only by a probe whose validation passed on the run that
   wrote it — and *non*-entitlement is proven the same way. Reading "AV refuses everything"
   off one exhausted-quota probe is what produced the withdrawn Q6 premise.

5. **FMP's 402 has four meanings** — endpoint gate, symbol gate, parameter gate, and an
   exhausted quota wearing plan-gate language. `provider_validation.py` classifies them;
   never memoise a bare 402 as an endpoint-level gate.

6. **A symbol boundary is not an endpoint gate.** Finnhub answers 403 both for a premium
   endpoint and for a non-US symbol. Memoising the second as the first would retire
   `company_news` for the whole universe on the first EU ticker. `FinnhubClient` raises the
   symbol refusal directly, never through `_response`, so it can never reach the plan-gate
   memo.

7. **One endpoint can answer two questions, and the raw cache keys on the target.**
   `fred.release_dates` is asked backwards (which release carried this reading) and
   forwards (what is scheduled next) for the same release on the same run date. The
   `window` argument gives the forward call its own slot; without it the second write
   overwrites the first and the ageing join silently reads a file of future dates. Any
   future two-window endpoint needs the same treatment.

8. **Two off-by-one traps already hit and fixed** — don't reintroduce them:
   - A macro reading is dated by the **period it measures**, not its release. Ageing from
     the period start made a two-week-old CPI print read as two months stale.
   - The release carrying a period is the first one after that period **ends**. Matching on
     "first release after the period start" is off by exactly one release and looks correct.

9. **A required component must be *capable* of reading `verified`, or it caps the whole
   universe.** Adding `S_S` to `REQUIRED_COMPONENTS` (G5) was correct and did nothing,
   because `S_S` judged its own completeness over legs that can never be available:
   `executive_tone` is permanently `n/a` at weight 0.00, and `political_flow` is a capped
   overlay rather than a base leg. The result was 19 Tier B and nothing above it — a
   constant tier again, one letter lower. **Before putting a component in a required set,
   check that some real run can make it `verified`.** Completeness is now judged over
   weighted base legs only (`components/sentiment.py`).

10. **The grade's two halves key off different fields, and both are needed to recompute a
    row.** `_effective_weights()` branches on the **thesis band**; `alignment()` branches on
    the **direction**. They agree for `above spot` / `below spot` / `within 1 sigma` and
    diverge for `beyond +/-1 sigma`, where a LONG skew structure takes the *neutral*
    `0.60 / 0.40` split but the *directional* alignment branch. That is why `direction` is
    published on `TradingIdeaRow`: without it, two rows with identical published fields
    grade differently and neither can be checked. A full recompute also needs
    `confidence_multiplier`, which is published under
    `per_ticker_sections[].gate` but not on the row itself — so the document reconciles,
    the ideas table alone does not.

---

## 5. Useful commands

```bash
# Tests
PYTHONPATH=src .venv/bin/python -m pytest

# Fixture run (deterministic, no keys)
PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily \
  --config config/config.example.yaml --force

# Read the graded ideas table
jq -r '.trading_ideas[] | [.grade_letter,.grade_score,.ticker,.status,.blocked_reason] | @tsv' \
  output/dashboard/$(date +%F)/dashboard.json | column -t -s$'\t'

# Which legs can the live path not score?
PYTHONPATH=src .venv/bin/python -c "
import sys; sys.path.insert(0,'src')
from briefing_app.pipeline import LIVE_UNSCORABLE_LEGS
[print(f'{k}: {v}') for k,v in LIVE_UNSCORABLE_LEGS.items()]"

# Live provider chains actually in force
PYTHONPATH=src .venv/bin/python -c "
import sys; sys.path.insert(0,'src')
from briefing_app.config import load_config
c=load_config('config/config.example.yaml')
[print(f'{l:15} {getattr(c.providers,l)}') for l in
 ('options','prices','news','earnings','macro','analyst','insider',
  'institutional','put_call','political','retail','short_interest')]"

# The dated macro calendar the live path builds (FRED, needs FRED_API_KEY)
PYTHONPATH=src .venv/bin/python -c "
import sys, os; sys.path.insert(0,'src')
from datetime import date, datetime, UTC
from briefing_app.config import load_config
from briefing_app.pipeline import LiveDataSource
from briefing_app.raw_cache import RawCache
from briefing_app.settings import AppSettings
c=load_config('config/config.example.yaml')
cal,_,_=LiveDataSource(settings=AppSettings.from_env())._macro_calendar_for_run(
    config=c, run_date=date.today(), generated_at=datetime.now(UTC),
    raw_cache=RawCache(AppSettings.from_env().data_dir))
[print(e.event_date.date(), e.name) for e in cal.events]
[print('  -', d.code, d.detail) for d in cal.diagnostics]"

# What the news lexicon makes of a headline
PYTHONPATH=src .venv/bin/python -c "
import sys; sys.path.insert(0,'src')
from briefing_app.providers.news_tone import score_article_tone, tone_label
h='Chipmaker beats estimates and raises guidance'
s=score_article_tone(h); print(h, '->', s, tone_label(s))"
```

## 6. Map of the documents

| File | What it is |
|---|---|
| `docs/archive/provider-alternatives-wiring-tasks.md` | The audit, coverage matrix and research verdicts — the **why**. Start here |
| `docs/archive/provider-alternatives-implementation.md` | Tickets `I0`–`I16` with status — the **how** |
| `docs/research/alternatives/*.md` | 17 files: PA1–PA10 verdicts, two deferral notes, the PB3 and P4 outcome notes, and `still-failing.md` (PC1) |
| `docs/research/SOURCE_STATUS.md` | Endpoint statuses. Header and active summary table are regenerated from the 2026-09-03T13:10:58 credentialed deep preflight over 50 endpoints; historical banners below explain the 08-31 / 09-02 changes |
| `docs/archive/POST-P3-DECISIONS.md` | **Answers Q1–Q6** from live output, with a recommended order. Read it before acting on §3 |
| `docs/archive/still-failing.md` | `PC1`: regenerated from deep preflight `2026-09-03T13:10:58` plus live run `daily-2026-09-03-c7e82663` |
| `docs/research/alternatives/q6-alpha-vantage-allocation.md` | **N4 plan**: which legs AV should carry, given 25 requests/day against 24 tickers |
| `docs/product/SPEC-graded-ideas-report.md` | Spec for the graded report — built and shipped, and **current**: it carries the G1–G5 amendments (band-dependent weights, `DIRECTIONAL_FULL_CONVICTION`, the published `direction` field) |
| `tasks/archive/phase-3/plan.md`, `tasks/archive/phase-3/todo.md` | The graded report's plan and task list — complete. `todo.md` carries a post-09-06 amendment recording what G1–G5 changed under T4 and T5 |
| `docs/archive/implementation-tasks.md` | The original T0–T14 build plan. **Partly stale**: T13/T14 overlap the newer provider docs, and it still asserts the AV quota resets at UTC midnight, which was withdrawn |
