# Directional Thesis Probability

Research date: 2026-09-06. Measurement only — no scoring code, config, or test was changed.
Evidence is the published dashboard payloads on disk; the pipeline was not run.

**Verdict: the premise holds and is stronger than filed, but the proposed remedy is
disproved. Reject all four candidate replacements.** Nothing available at grade time carries
directional information, because *both* branches of the scenario table are centred on spot by
construction. The measurable defect is on the **neutral** side, not the directional one: a
neutral row's `P` is `0.683` by definition of the band it is measured over, so the 20-42 point
head start is a tautology rather than evidence. The minimal honest change is to set
`directional_probability_weight` to `0.0` and let alignment carry the directional branch. The
neutral base-rate floor is a separate, larger decision, costed below.

---

## 1. Premise check

| Claim as filed | Verified | Finding |
|---|---|---|
| Directional `P` is `probability_above_spot` / `probability_below_spot` | ✅ | `grading._select_thesis_band` → `_above_spot_selection` / `_below_spot_selection`. The two are exact complements, so choosing the other side gains nothing. |
| It is ~0.50 for every name over a short horizon | ✅ **and worse than stated** | 2026-09-04, 12 directional rows: **0.4702-0.5192, spread 0.0490, sd 0.0108**. On the six `measured_sigma` rows it is not merely near 0.50, it is *exactly* `0.5000` to four decimals. |
| The observed span was 0.4801-0.5261 across 12 rows on 2026-09-04 | ⚠️ **numbers do not reconcile** | 2026-09-04 has 12 directional rows spanning **0.4702-0.5192**. `0.5261` is the max of `output/dashboard/2026-09-03/dashboard.json` (the 18:17 run, 14 directional rows, 0.4761-0.5261). `0.4801` appears in no run. The filed figure appears to blend two runs. **The conclusion is unaffected** — the spread is ~0.05 either way. |
| A neutral `P` varies 0.50-0.86 | ⚠️ **close, also blended** | 2026-09-04: 0.6480-0.8532. 2026-09-03 18:17: 0.5777-0.8639. 2026-09-03 19:22: 0.5877-0.7437. The 0.86 is from the 18:17 run. |
| A directional row starts 20-42 points behind | ✅ | Confirmed, and the floor is exact: a neutral row with **zero** alignment support still scores `0.60 × 0.683 = 41.0`. Four rows on 2026-09-04 (AMZN, FDX, JPM, XOM) sit at 40.97-43.06 on alignment `0.000`. |
| The fix is "probability of reaching the setup's target" | ❌ **no input exists** | `strategy.models.Setup` has no target field. It carries `range_low`/`range_high` (the measured ±1σ edges), an optional `Invalidation`, and the scenario table. Nothing in `src/` computes or stores a price target. |

**Auditor's note.** The `grade_score` values published in `output/dashboard/2026-09-04/`
were produced by the **pre-fix** grading code: they reproduce exactly as
`100 × (w·P + (1−w)·|S_CTE|)` minus penalties (ORCL: `100 × (0.20×0.4702 + 0.80×0.3169) =
34.75`, published `34.75`). Every projection in §4 recomputes the baseline with the *current*
`grading.py` rather than reading `grade_score`. Do not compare the numbers here against the
published HTML.

---

## 2. Why no scenario-table probability can carry direction

This is the load-bearing finding, and it is structural rather than a tuning problem.

**The bands are cut from the same sigma that generates the distribution.** `build_scenario_table`
takes the boundaries from `measured_range.one_sigma` / `two_sigma`, which are
`spot ± spot·adjusted_sigma_pct` (`options_math.py:543-546`), then fills them with a lognormal
CDF driven by that same `adjusted_sigma_pct`. The band masses are therefore a mathematical
constant, independent of the ticker:

| Band | `measured_probability`, all 21 rows, 2026-09-04 | spread |
|---|---|---|
| below 2 sigma | 0.0126 - 0.0218 | 0.0093 |
| 1 to 2 sigma down | 0.1368 - 0.1447 | 0.0079 |
| **within 1 sigma** | **0.6827 - 0.6852** | **0.0025** |
| 1 to 2 sigma up | 0.1252 - 0.1350 | 0.0098 |
| above 2 sigma | 0.0237 - 0.0323 | 0.0087 |

The residual 0.002-0.010 is only the lognormal's asymmetry over different sigmas. So **on the
`measured_sigma` branch every probability in the table is a universal constant**, and any
candidate built from it is constant too. On 2026-09-04 that is 6 of 21 graded rows (2 of 12
directional); on 2026-09-03 it was 11 of 23 (6 of 14).

**All cross-sectional variation comes from one quantity, and it is not direction.** Back out the
lognormal sigma that reproduces each row's implied within-1σ mass and compare it to the measured
sigma:

| Run | n | Pearson r, `implied σ / measured σ` vs `P(within 1 sigma)` |
|---|---|---|
| 2026-09-04 | 21 | **−0.9987** |
| 2026-09-03 (19:22) | 23 | **−0.9975** |

`P(within 1 sigma)` is a **variance risk premium reading in disguise** — it is a deterministic
function of how much cheaper implied vol is than trailing realized vol, and nothing else. It is
not a calibrated probability that the neutral thesis is right; it is 0.683 plus a VRP term.
That is why it "varies usefully" and why using it for a directional thesis would be a category
error (§4, C1).

**Direction cannot survive either branch.** The measured branch is centred on spot by
construction. The implied branch is risk-neutral, so its forward is also ~spot. A distribution
centred on spot assigns ~0.50 to "finishes above spot" whatever the thesis is. The directional
view lives entirely in `S_CTE`, which the alignment term already carries at 0.80 weight.
Any attempt to inject drift from `S_CTE` into the scenario table would double-count it.

**The residual variation is partly an artefact.** `_fraction_above_spot` linearly interpolates
the within-1σ band mass, so on the measured branch it returns exactly 0.5, when the exact
lognormal answer is not 0.5:

| Ticker (2026-09-04, measured branch) | sigma | published `P(above spot)` | exact lognormal | artefact |
|---|---|---|---|---|
| AMAT | 6.19% | 0.5000 | 0.4877 | +0.0124 |
| FDX | 5.41% | 0.5000 | 0.4892 | +0.0108 |
| LMT | 4.01% | 0.5000 | 0.4920 | +0.0080 |
| XOM | 3.65% | 0.5000 | 0.4927 | +0.0073 |
| GM | 3.28% | 0.5000 | 0.4935 | +0.0065 |
| JPM | 2.05% | 0.5000 | 0.4959 | +0.0041 |

Mean bias **+0.0082** on 2026-09-04, up to **+0.0276** on 2026-09-03 (CRWV, sigma 13.75%). The
whole cross-sectional spread being argued over is 0.049. So **roughly a sixth to a half of the
"variation" in `P(above spot)` is a known interpolation artefact, not a market reading.** This
is a small correctness note in its own right, filed here rather than fixed; it is *not* an
argument for repairing the interpolation, because the exact value is a monotone function of
sigma alone (`1 − N(σ/2)`), i.e. it would penalise high-vol names on a long thesis and its
spread would *shrink* to 0.0155 (§3, C0-exact).

**And the residual does not behave like signal.** Correlating `P(above spot)` against the 25-delta
risk reversal already in the evidence ledger: **r = −0.78** on 2026-09-04 (n=11) but **+0.33** on
2026-09-03 (n=12). An unstable sign across two consecutive runs is what noise looks like.

---

## 3. Every probability available at grade time, measured

Population: the 12 directional rows of `output/dashboard/2026-09-04/dashboard.json`, cross-checked
against the 14 of `dashboard-daily-2026-09-03-c7e82663.json`. Values recomputed from the published
scenario tables by importing `briefing_app.strategy.scenarios` and
`briefing_app.dashboard.grading` — no pipeline run.

| # | Candidate | What it means | Inputs today | 09-04 range | spread | sd | coverage |
|---|---|---|---|---|---|---|---|
| **C0** | `probability_above/below_spot` *(status quo)* | Terminal price on the thesis side of spot | ✅ table property | 0.4702 - 0.5192 | **0.0490** | 0.0108 | 100% |
| C0x | C0 computed exactly, no interpolation | as above, artefact removed | ✅ pure maths | 0.4786 - 0.4941 | **0.0155** | 0.0052 | 100% |
| C1 | `probability_in_one_sigma` | Terminal price inside the ±1σ band | ✅ table property | 0.6111 - 0.9794 | **0.3683** | 0.1151 | 100% |
| C2 | `probability_above/below_one_sigma` | Terminal move **beyond 1σ in the thesis direction** | ✅ table property | 0.0133 - 0.1830 | **0.1697** | 0.0536 | 100% |
| C3 | `2 × C2`, capped | **Touching** the 1σ edge before the horizon ends (reflection approximation) | ✅ derived from C2 | 0.0266 - 0.3659 | **0.3393** | 0.1071 | 100% |
| C4 | `P(terminal not past invalidation)` | Not closing beyond the invalidation level | ⚠️ needs `Invalidation` | single row: 0.6093 | n/a | n/a | **8%** |
| C5 | `P(never touching invalidation)` | Not trading through the level intraday | ⚠️ needs `Invalidation` | single row: 0.2185 | n/a | n/a | **8%** |
| C6 | `0.5 + 10 × (C0 − 0.5)` | C0's risk-neutral tilt, amplified ×10 | ✅ derived from C0 | 0.2021 - 0.6922 | 0.4901 | 0.1079 | 100% |
| — | *probability of reaching a target* | — | ❌ **no target exists** | — | — | — | 0% |

Reference, same run, 9 neutral rows: `P(within 1 sigma)` **0.6480 - 0.8532, spread 0.2052,
mean 0.7143**.

2026-09-03 (14 directional rows) reproduces the shape: C0 spread 0.0385, C1 0.3137, C2 0.1780,
C3 0.3561, C4 coverage 4/14.

### The arithmetic that kills C2, C3 and C6

A replacement must satisfy **two** constraints, and they pull against each other:

1. **Spread** — it must vary across names, or it adds no information.
2. **Level** — its mean must be near the neutral branch's `0.60 × 0.713 ≈ 42.8` points, or the
   head start survives the change.

Under a distribution centred on spot, a directional statement is either "which side of the
centre" (level ≈ 0.50, no spread) or "how far into a tail" (real spread, level 0.02-0.37).
There is no third option. To match the neutral branch's 42.8 points, C2 (mean 0.122) would need
weight **3.5** and C3 (mean 0.244) weight **1.75**. Both are impossible. **Adopting C2 or C3
widens the gap it was meant to close.**

### Invalidation-based candidates (C4, C5) die on coverage, not on merit

They are the only candidates that are semantically *about the trade*, and their level would be
right (0.61-0.84 terminal, 0.22-0.68 touch on 2026-09-03). But an `Invalidation` is only built
for `CANDIDATE` setups; `watchlist_no_trade` rows carry `invalidation: null`, and the graded
population is almost entirely watchlist:

| Run | graded rows | directional | with an invalidation level |
|---|---|---|---|
| 2026-09-02 | 24 | 15 | **0** |
| 2026-09-03 (19:22) | 23 | 14 | 4 |
| 2026-09-04 | 21 | 12 | **1** (20 of 21 rows are `watchlist_no_trade`) |
| 2026-09-06 | 18 | 9 | **1** |

**6 of 105 graded rows across four runs.** A thesis probability defined only for ~6% of the
ladder cannot be the grade's probability term — `compute_grade` returns an *unscored* result
when the probability is missing, so 94% of rows would lose their grade entirely.

---

## 4. Projected grades, 2026-09-04

Baseline recomputed with current `grading.py` (`DIRECTIONAL_FULL_CONVICTION = 0.35`, unified
alignment). Penalties held at their published totals, since no candidate touches them. Tier
ceilings applied. "dir>neu pairs" counts the 12×9 = 108 directional/neutral pairs where the
directional row outranks the neutral one — a pure interleaving measure, higher is better.

| Scenario | directional range | dir mean | neutral range | neu mean | dir>neu | best dir rank |
|---|---|---|---|---|---|---|
| **Baseline** — C0 @ 0.20 | 9.09 - 81.83 | 35.85 | 40.97 - 83.82 | 53.96 | 21/108 | 2 |
| C0 @ 0.60 | 28.21 - 64.42 | 41.09 | 40.97 - 83.82 | 53.96 | 21/108 | 3 |
| C2 @ 0.20 | 2.43 - 75.72 | 28.35 | " | 53.96 | 19/108 | 2 |
| C2 @ 0.60 | 0.00 - 46.09 | 18.67 | " | 53.96 | **4/108** | 6 |
| C3 @ 0.20 | 5.63 - 79.01 | 30.79 | " | 53.96 | 21/108 | 2 |
| C3 @ 0.60 | 0.00 - 55.97 | 25.92 | " | 53.96 | 14/108 | 4 |
| C6 @ 0.20 | 7.86 - 76.47 | 35.36 | " | 53.96 | 21/108 | 2 |
| C6 @ 0.60 | 25.12 - 58.48 | 39.61 | " | 53.96 | 18/108 | 4 |
| C1 @ 0.60 | 39.18 - 72.87 | **56.29** | " | 53.96 | **63/108** | 2 |
| **P1** — directional weight **0.00** | **0.00 - 90.53** | 33.30 | " | 53.96 | 24/108 | **1** |
| P2 — excess-over-null, both @ 0.60 | 0.00 - 36.21 | 12.53 | 0.00 - 53.18 | 17.73 | 52/108 | 2 |
| P3 — excess-over-null, both @ 0.20 | 0.00 - 72.42 | 26.36 | 0.00 - 81.13 | 24.41 | 62/108 | 2 |

**Not one of C2, C3 or C6 improves interleaving.** Every one of them either leaves it unchanged
or makes it worse, at every weight. That is the whole test and they fail it.

**C1 @ 0.60 is the only substitution that closes the gap, and its ordering is visibly wrong.**
It scores a *long* thesis by the probability the price goes **nowhere**:

```
   72.87  B  ORCL   DIR  s_cte=+0.3169 align=0.905
   69.45  B  GM     DIR  s_cte=+0.2492 align=0.712
   63.05 C+  MU     DIR  s_cte=+0.0922 align=0.263   <- outranks SPY, META on cheap options alone
   58.01 C+  META   DIR  s_cte=+0.1100 align=0.314
   56.79  C  COST   DIR  s_cte=+0.0703 align=0.201   <- outranks AMAT (align 0.340) and CRWV
   ...
   39.18  D  GOOGL  DIR  s_cte=-0.0097 align=0.000   <- S_CTE CONTRADICTS the long direction, still D
```
COST reaches C with alignment 0.201 purely because its implied vol is 0.43× its measured sigma.
GOOGL, whose `S_CTE` points the wrong way for its own long thesis, keeps a `D` instead of the `F`
it earns. **Reject.**

**P1 — remove the term** — is the only change that improves the ladder without inventing a
signal. Directional raw becomes `100 × alignment`:

```
   90.53 A+  ORCL   DIR  align=0.905   <- rank 1, was rank 2
   83.82  A  MSFT   neu  align=0.951
   71.20  B  GM     DIR  align=0.712
   67.89  B  QQQ    neu  align=0.626
   60.99 C+  INTC   DIR  align=0.610
   ...
    0.00  F  GOOGL  DIR  align=0.000   <- correctly zero
```
No ordering among directional rows changes (the removed term was a near-constant, so it was a
rank-preserving shift); the range widens from 9.09-81.83 to 0.00-90.53, the top directional row
takes rank 1, and the contradicted row falls to 0. Interleaving improves marginally, 21→24.
It does **not** close the head start — that is not a directional problem.

**Does a varying `P` justify moving 0.20/0.80 back toward 0.60/0.40? No — the evidence points the
other way.** Raising the weight helps only if the new `P` has a *higher mean* than the 0.50 it
replaces, and none does. `C0 @ 0.60` raises the directional mean (35.85 → 41.09) while *narrowing*
the range from 72.7 points to 36.2 — it buys mean at the cost of discrimination, which is the
opposite of the goal. The right direction for that constant is 0.20 → 0.00.

---

## 5. What was rejected, and why

| Option | Reason rejected |
|---|---|
| **P(reaching the target)** — the filed proposal | No target exists anywhere in `strategy/models.py`, `engine.py`, or the payload. Would require inventing a target rule (R:R multiple? 1σ edge? analyst PT?), which is a new product decision, not a grading fix — and any target cut from the measured sigma reduces to C2/C3, already measured and rejected. |
| **C2 — beyond 1σ in the thesis direction** | Spread 0.1697 is real, but mean 0.122 is 6× too low. Makes the head start worse at every weight; interleaving 19-4/108 vs baseline 21/108. |
| **C3 — touching the 1σ edge** | Best spread of the honest candidates (0.3393), still mean 0.244. Interleaving 21/108 at w=0.20 (no change) and 14/108 at w=0.60 (worse). Also rests on the reflection approximation `P(touch) ≈ 2·P(terminal beyond)`, which is exact only for driftless arithmetic Brownian motion. |
| **C4/C5 — invalidation-based** | Right semantics, right level, **6% coverage**. `compute_grade` returns an unscored row when the probability is `None`, so 94% of the ladder would lose its grade. Revisit only if the graded population stops being ~95% `watchlist_no_trade`. |
| **C1 — `P(within 1σ)` for a directional thesis** | Only candidate that closes the gap; disqualified on meaning and on observed ordering (§4). It is the iron condor's thesis, and `r = −0.999` shows it is a VRP reading. Scoring a long thesis by the odds the price stays put is not a fixable framing. |
| **C6 — amplify C0's tilt ×10** | Amplifies a residual whose sign is unstable between runs (r = −0.78 then +0.33 against `rr_25d`) and of which up to half is a known interpolation artefact. Amplifying noise by 10 produces a confident-looking number with no content. Interleaving 21/108 and 18/108 — no gain. |
| **Repairing `_fraction_above_spot` to the exact lognormal** | Would *shrink* the spread from 0.0490 to 0.0155 and make `P` a monotone decreasing function of sigma alone, penalising high-vol names on a long thesis. Correct, and strictly worse as a grading input. Worth doing for honesty of the printed table, not for the grade. |
| **`rr_25d` (25-delta risk reversal) as the directional `P`** | It *is* a genuine market-implied directional tilt and it varies (−0.0603 to +0.0779 on 2026-09-04, 20 of 21 rows). But it already feeds `sub_scores["skew"]` inside `S_O` (`options_math.py:1000`), which feeds `S_CTE`, which feeds alignment. Using it as `P` double-counts the same evidence on both sides of the formula. |
| **Injecting `S_CTE` as drift into the scenario table** | Same double-count, and it would make the scenario table — which the report presents as a market-derived distribution — a function of the app's own opinion. Would also corrupt the neutral rows and the divergence flag. |
| **An empirical base rate from realised outcomes** | The honest denominator, and it is not available. `prior_scorecard` stores only yesterday's component scores; there is no realised-outcome table in `storage.py` and no hit-rate anywhere in `src/`. Would need a new table, a settlement job, and months of history before the first reading. |

---

## 6. What it costs

**The recommended change (P1) costs nothing.** `directional_probability_weight` is already a
config field (`config.py:153`). Setting it to `0.0` needs no provider data, no scenario-table
change, no new storage. `_effective_weights` already returns `(w, 1−w)` for the directional
branch, so `100 × alignment` falls out. The only work is updating the tests that assert the
current directional raw, and the `DIRECTIONAL_FULL_CONVICTION` docstring in `grading.py:31-53`,
whose closing paragraph proposes exactly the target-probability fix this document disproves.

**The real defect costs more, and is a separate decision.** The head start is
`0.60 × 0.683 = 41` points paid to every neutral row for the *definition* of its band. Removing
it means scoring **excess over the null model** — `(P − P_null)/(1 − P_null)`, where `P_null` is
what the measured-sigma lognormal already implies for that same band. Measured (P2/P3 in §4):

- Interleaving jumps to 52/108 and 62/108, the best of anything tested.
- Every `measured_sigma` **neutral** row correctly collapses to excess `0.000` — with no chain,
  the table contains no information, and this says so instead of paying 41 points for it. The two
  `measured_sigma` *directional* rows (GM, LMT) leak excess `0.0129`/`0.0158`, which is precisely
  the §2 interpolation artefact — so `_fraction_above_spot` would have to be fixed first.
- The whole ladder compresses downward: at 0.60 weight the top score is 53.18 and **19 of 21 rows
  are `F`** (1 `C`, 1 `D`). The `_LETTER_BANDS` boundaries and `_TIER_CEILINGS` were cut against
  the current scale and would need re-cutting with it.
- It also states plainly what the neutral `P` has been measuring all along — VRP — which may or
  may not be what the report wants a *grade* to say.

That is a re-scaling of the whole grade, not a term swap. It should be its own task with its own
before/after ladder, not folded into a directional-probability fix.

---

## 7. Recommendation

1. **Close the search for a directional replacement probability.** Four candidates were computed
   on real data across two runs; none passes. The reason is structural — a distribution centred
   on spot cannot express direction — so this is not worth re-deriving later.
2. **Set `directional_probability_weight = 0.0`.** Free, needs no new data, removes a constant
   that currently reads as evidence. Directional raw becomes `100 × alignment`, the range widens
   to 0-90.5, the strongest directional row takes rank 1, and a row whose `S_CTE` contradicts its
   own direction correctly scores 0. Print `P(above spot)` in the report as context if it is
   wanted there — it is a fact about the distribution, just not one that grades anything.
3. **Correct `grading.py`'s standing docstring.** Lines 50-53 name the target-probability change
   as "the fix". It is not available and, if it were, §3's arithmetic shows a tail probability
   makes the gap worse. Leaving that note in place invites a future agent to repeat this search.
4. **File the neutral base-rate floor as the actual open defect**, with §6's excess-over-null
   measurement as the starting evidence. Do not bundle it with (2).

Do **not** adopt C1, C2, C3 or C6. Revisit C4/C5 only if invalidation coverage rises above ~90%
of graded rows.

---

## What was not verified

- **Only two runs, and one universe.** 2026-09-04 (21 rows) and 2026-09-03 (23 rows), all
  US large-cap, all Tier A, 12 of 12 directional rows long. **No `below spot` row exists in any
  published run**, so the short branch of `_select_thesis_band` is verified by symmetry
  (`probability_below_spot = 1 − probability_above_spot`) rather than by observation.
- **20 of 21 rows on 2026-09-04 are `watchlist_no_trade`.** Every conclusion about invalidation
  coverage is a conclusion about *this* population. A run dominated by `CANDIDATE` setups would
  make C4/C5 available, and their spreads were measured on 4 rows only (2026-09-03: terminal
  0.6333-0.8417, touch 0.2666-0.6835). Four rows is an indication, not a measurement.
- **The C4/C5 CDF is interpolated, not exact.** The published payload gives band masses at four
  edges only, so `P(terminal past level)` was computed by linear interpolation between them —
  the same approximation §2 criticises in `_fraction_above_spot`. A real implementation would
  evaluate `options_math.probability_below` against the fitted `ImpliedDistribution` directly.
  Since C4/C5 are rejected on coverage, this was not tightened.
- **C3's `2 × P(terminal beyond)`** is the reflection-principle first-passage identity, exact only
  for driftless arithmetic Brownian motion. Under the lognormal actually used it is an
  approximation of unquantified error. Since C3 fails on level regardless, the error was not
  bounded.
- **The `rr_25d` correlation is 11-12 rows per run** and flips sign between them. That is enough
  to show the residual is not stable signal; it is not enough to characterise what it *is*.
- **Grade projections hold penalties fixed** at their published totals. `divergence_penalty`
  depends on `_thesis_diverges(table, thesis.row_labels)`, and C1/C2/C3 would change
  `row_labels`, so a real implementation could fire the penalty on different rows. Two rows on
  2026-09-04 (AVGO, COST) currently carry it.
- **The `_TIER_CEILINGS` and `_LETTER_BANDS` interaction was checked only for clipping**, not
  re-tuned. Every projection keeps the current boundaries; P2/P3 in particular would need new
  ones, and no proposal for them is made here.
- **Nothing was verified about whether the grade *should* rank directional and neutral rows on one
  scale at all.** `P(within 1σ)` and `P(above spot)` are base rates of genuinely different events.
  Publishing one ladder over both may be the deeper error, and this document assumes rather than
  tests that a single ladder is wanted.
