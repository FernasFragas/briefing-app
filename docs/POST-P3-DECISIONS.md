# Post-P3 report, preflight, and the Q1–Q6 decisions

Run date 2026-09-02. Live mode, full universe. Written to answer HANDOFF.md §3.

> **Scope note.** This is analysis only. No file under `src/` or `config/` was changed.
> Two findings below required a working pipeline to measure, so the fix was applied to a
> throwaway copy of `src/` in a scratchpad and the repo left untouched. The fixes are
> described precisely so they can be made deliberately.

> **Supersession note, 2026-09-06.** The grading audit (`G1`–`G5`, `HANDOFF.md` §2) changed
> three things this memo states as fact. The decisions it reaches are unaffected — Q5's "do
> not re-tune the edges" and Q2's "drop them" both survive, the second more strongly than
> before — but do not quote these three lines:
>
> 1. **§2 writes the grade as `100 × (0.60 × probability + 0.40 × alignment)`.** That split
>    is now the **neutral-band** one only. `_effective_weights()` gives `above spot` and
>    `below spot` a `0.20 / 0.80` split instead (`directional_probability_weight`). That
>    setting did not exist when §2 was written — the correction noted inline there fixed
>    *sum versus product*, not the split — but it was in force by the 2026-09-04 run, whose
>    published rows reconcile only against it.
>    The consequence for the figure at the end of §2: a perfectly aligned directional setup
>    ceilings at **90.00**, not the `70.0` recorded there, and "perfectly aligned" now means
>    `|S_CTE| ≥ 0.35` (`DIRECTIONAL_FULL_CONVICTION`) rather than the raw magnitude.
> 2. **§3 states `REQUIRED_COMPONENTS[E] = {S_O, S_M}`.** It is now `{S_O, S_M, S_S}` for
>    both `V` and `E`. This *strengthens* the case §3 makes for dropping RHM.DE and LDO.MI:
>    they now fail on a second required component as well, since Finnhub's free tier is
>    US-only and neither has an EU analyst or news source.
> 3. **§5's note says "Neither floors a tier — `S_S` is not in the required set for `V` or
>    `E`".** That is no longer true, and the sentence was load-bearing. With `S_S` required,
>    the two `n/a` paths that note describes — news-plus-retail with no analyst coverage,
>    and retail alone — **do** floor a tier now. It is exactly this composition that puts
>    QQQ and SPY at Tier C: an index has no issuer, so no analyst leg, so `S_S` is
>    structurally `unavailable`, so a required component fails and `is_tradeable` is false.
>    That outcome is defensible but was never explicitly chosen; an index exemption from the
>    required set is open.

> **Supersession note, 2026-09-03.** Q1–Q6 are all decided and implemented; N1 has since
> run. **Every live count in this memo describes the 2026-09-02 4-sector config and is
> historical.** On the current config, live run `daily-2026-09-03-c7e82663` scores 23 names
> with 4 tradeable, and the tier spread this memo reports (5 A / 4 B / 15 C) is now
> **23 A / 0 B / 0 C** — see `HANDOFF.md` §2 N1 for why, and for the two consequences that
> follow. The reasoning below stands; the measurements do not.

> **Supersession note, 2026-09-02.** The Q0 blocker was closed by dropping the scheduled
> historical put/call call, and the `S_M` sector-exposure gap described below is now
> closed in `config/config.example.yaml` plus the fixed-universe `Defense` spelling
> normalization. See `docs/alternatives/still-failing.md` for the report-derived closure
> note and macro-only verifier output.

---

## 0. Before any of Q1–Q6: the post-P3 report did not exist

The first live run scored **0 of 24 tickers**. Every one failed at
`data_pull_normalize_compute` with `Invalid isoformat string: 'latest'`, and because every
ticker failed the run wrote **no dashboard at all** — `html_path`, `json_path` and
`status_path` all came back `None`. There was nothing to inspect for Q5.

Root cause, reproduced from the cached payload:

```
normalizers.py:510  _full_chain_put_call_snapshot
    as_of=parse_date(as_of) if as_of else date.today(),
```

Alpha Vantage's `historical_put_call_ratio` returns a **top-level sentinel**
`"date": "latest"` alongside real per-expiration data. `parse_date` falls through to
`datetime.fromisoformat`, and the resulting `ValueError` — not a `NormalizationError` — 
escapes `normalize_alpha_vantage_put_call_ratio` and kills the whole per-ticker stage.

Guarding that one call took the run from *0 scored / 24 failed* to **0 failures, 24 scored,
`status: succeeded`**. Everything below is measured on that run.

**This is the first thing to fix.** It is one guarded call, and it is worth a regression
test built from the real payload, which is now cached at
`data/raw/alpha_vantage/historical_put_call_ratio/2026-09-02/NVDA.json`.

---

## 1. The finding that outranks Q1–Q6: `S_M` fails for all 24 names

Not one row is `TRADEABLE`. The reason is not the grade bands and not the component
weights — it is that **the macro component does not score**, for two distinct reasons:

| Names | `blocked_reason` | Tier |
|---|---|---|
| 15 | `missing required component: S_M … no sector exposure declared` | C |
| 9 | `S_M required component degraded: status partial` | B |

**The 15.** `config/config.example.yaml` declares `components.sector_exposures` for exactly
four sectors — `Semiconductors`, `Energy`, `Financials`, `Index`. The universe declares
fourteen. A name whose sector is not in that map gets no macro direction, so `S_M` is `n/a`,
and `S_M` is a required component for every expression class. The correlation is exact:

> **Tier B ⇔ sector declared in `sector_exposures`: 24 of 24 names match.**
>
> Tier B: AMD, AVGO, INTC, MU, NVDA (Semiconductors), QQQ, SPY (Index), JPM (Financials),
> XOM (Energy). Tier C: everything else — Hardware, Semiconductor Equipment, Internet,
> Retail, AI Infrastructure, Industrials, Transport, Autos, Software, Defense.

Two of these are one string away from working. **AMAT** is declared
`Semiconductor Equipment`, not `Semiconductors`. **LMT** is declared `Defense` while
RHM.DE and LDO.MI use `Defence` — so even adding a defence row would miss LMT.

**The 9.** The declared sectors reference `real_yields`, `dollar`, `copper`,
`credit_spreads` and others that had no FRED series mapped when this run was measured, so
even a declared sector only partially scores.

**Consequence for Q5, and it is the decisive one:** this run measured a **pre-P5** macro
component. A parallel session reports that the seven missing factors (`real_yields`,
`credit_spreads`, `dollar`, `brent`, `wti`, `copper`, `natural_gas`) all probe HTTP 200 on
the free FRED key and has begun landing them. Those mappings are already in the working
tree's `fred.py`; the snapshot this run used predates them. **Any band edge tuned against
today's distribution is tuned against a macro component that is about to change.**

---

## 2. Q5 — Grade bands: **do not re-tune the edges**

Fixture (2026-09-01) gave 9 D / 15 F, everything Tier C. The live post-P3 run gives:

| Grade | Count | Tier |
|---|---|---|
| B+ | 3 | B |
| C | 5 | C |
| F | 16 | 9 C, 7 B |

P3 did real work: **9 names now reach Tier B**, which the fixture path could never show,
because a fixture run floors `S_O` to Tier C.

But the distribution was **bimodal, and the bands were not what made it bimodal**:

| `thesis_band` | Probability observed | Textbook normal |
|---|---|---|
| `within 1 sigma` | 0.6827 – 0.6834 | 0.6827 |
| `beyond +1 sigma` | 0.1578 – 0.1586 | 0.1587 |

`thesis_probability` was reproducing the geometry of the sigma bands, not anything
name-specific. A setup whose thesis was "stays within 1σ" scored ~0.68 *by construction*;
one whose thesis was "breaks beyond +1σ" scored ~0.16 *by construction*. Since
`grade_score = 100 × (0.60 × probability + 0.40 × alignment)` capped by the tier ceiling — a weighted **sum**, not a product (corrected 2026-09-02 against `grading.py`; the conclusion is unchanged, but the sum is what makes 49.52 the ceiling for a directional setup rather than 15.87), and
**`grade_penalties` is empty for all 24 rows** (no deduction is firing anywhere), the grade
was close to a relabelling of "is this thesis directional or not".

Moving band edges would have moved letters without changing the ordering. The thing to fix
was the input: a directional thesis needed side-of-spot probability rather than raw
one-sigma tail geometry.

**Implemented 2026-09-02 (N2):** leave the edges alone and change the input. Directional
setup types now use `probability_above_spot` / `probability_below_spot`, derived as
same-side tail mass plus the favorable share of the central band. A textbook directional
setup now reads `P≈0.50`, so perfect alignment produces a raw grade of `70.0` instead of
the old `49.52` ceiling.

---

## 3. Q2 — RHM.DE and LDO.MI: **drop them**

They are weaker than HANDOFF describes. They do not appear as watchlist rows with a named
reason — **they never reach scoring at all.** Both are stopped at the gate:

```
RHM.DE   decision: watchlist   reason_codes: ['eu_options_unavailable']
LDO.MI   decision: watchlist   reason_codes: ['eu_options_unavailable']
```

The structural case is closed, not merely unfunded:

- Both are `expression_class: E`. `REQUIRED_COMPONENTS[E] = {S_O, S_M}` and `S_O` is `n/a`
  with no Eurex capture — a required component that no free source can supply.
- `ConfidenceTier.C.size_fraction` is `0.0`. A Tier C name is never executable, by design.
- Even past the gate they would be near-uninformative. EU weights renormalize around the
  missing `S_O` (0.30), and `S_F` and `S_I` have no live EU source either, so the score
  collapses toward `S_M` — which is market-wide. Two defence names sharing one macro read
  would score nearly identically regardless of company facts.
- They share **one identical catalyst**: `2026-09-18`, status `estimated`, "European defence
  budget cycle update". One thesis, two rows.
- `RHM.DE` is declared in *both* `universe.example.yaml` and `candidates.example.yaml`, and
  the run rejected the second copy as `duplicate_ticker`.

**Recommendation:** drop both from the scored universe. The same argument already applies to
`ASML.AS` and `SIE.DE`, which were gate-rejected on the same code this run. Keep the
rearmament thesis as a written note if it is worth tracking; it is not costing quota today,
but it occupies gate rows and implies a coverage that does not exist.

---

## 4. Q6 — Alpha Vantage: **the premise is false**

`docs/SOURCE_STATUS.md` says "Alpha Vantage refuses every function." **That is no longer
true.** Today, on the same key:

| Metric | Value |
|---|---|
| Requests spent | 25 / 25 |
| Refusals | **0** |
| Valid payloads | 24 × `historical_put_call_ratio`, 1 × `symbol_search` |

No payload carried a `Note`, `Information` or `Error Message` key. The data is real — NVDA
returned a full-chain put/call of 0.74 across 22 expirations. The shallow preflight agrees:
`symbol_search` reports `ok`, and every other AV endpoint reports `registered`, meaning
*unprobed*, not *refused*.

So neither option in Q6 is right as posed:

- **"Remove it from the chains entirely" is not available.** `quotes: [alpha_vantage]` and
  `put_call: [alpha_vantage]` are **sole-sourced**. Removing AV empties them.
- **"Demote it to last everywhere" is a no-op** on exactly those two chains, since it is
  already the only entry.

The real constraint is **capacity, not entitlement**. The free tier allows 25 requests/day;
`put_call` alone is one request per ticker and consumed all 25 on a 24-name universe. AV
cannot cover a single full run of a per-ticker endpoint, however healthy the key is.

**Recommendation:** neither demote nor remove.
1. Guard the `"latest"` sentinel first — AV *working* is what broke the pipeline.
2. Re-probe with `preflight --deep` to find out what the key is now entitled to, and
   correct `SOURCE_STATUS.md`, which is actively misleading.
3. Keep AV **last** where a real alternative exists (`prices`, `news`, `insider`) and
   **first only where it is the sole source**, accepting that `put_call` will cover ~25
   names/day until the budget or the plan changes.

---

## 5. Q1 / Q1b / Q3 / Q4 under the chosen principle

> **Implemented 2026-09-02 (N3).** All four recommendations below are in the working tree.
> The one thing the implementation added to them is a shared mechanism: `SubScore.max_weight`,
> a ceiling on the share re-normalization may hand a leg, honoured in `combine_sub_scores`
> and used at both levels — the parts inside the institutional leg (Q1b) and the legs
> inside `S_S` (Q3). Its consequence is the part worth reading: **a capped leg needs an
> uncapped one to absorb what re-normalization frees, so a component built only of capped
> legs is `n/a`.** That is what turns "news does not stand in for analyst coverage" and
> "retail is never the thesis" into arithmetic instead of prose, and it is why two cases
> that used to produce a number now produce `n/a`: news-plus-retail with no analyst
> coverage, and retail alone. Neither floors a tier — `S_S` is not in the required set for
> `V` or `E` — so both simply drop 0.20 of weight and redistribute.
>
> **Reversed 2026-09-06 (G5).** `S_S` **is** now in the required set for `V` and `E`, so
> both of those `n/a` paths floor a tier rather than redistributing quietly. They are also
> not hypothetical any more: the index rule (PC3) makes `S_S` structurally `unavailable`
> for QQQ and SPY, which lands both at Tier C and therefore outside `is_tradeable`. See the
> supersession note at the top of this file.
>
> Every number in this section is still the **arithmetic**, not a re-measured
> distribution: N1 has not run.

You chose **redistribute weight** rather than shrink confidence. These are the consequences,
measured rather than assumed. `combine_sub_scores` renormalizes over available legs, so with
`executive_tone` (0.35) permanently `n/a`:

| Leg | Nominal | Actual after redistribution | Change |
|---|---|---|---|
| `institutional` (news + analyst) | 0.45 | **0.692** | +54% |
| `retail_momentum` (ApeWisdom) | 0.20 | **0.308** | +54% |

**Q1 — `executive_tone`.** Record it permanently `n/a` and let redistribution stand. The
disclosure text already names the dropped leg on every run, so the re-weighting is not
silent. Worth stating plainly in the docs: `S_S` is now **entirely proxy data** — a local
lexicon and a mention counter, with no vendor-scored input at all.

**Q1b — the news lexicon.** Its weight is not fixed and that is the real problem. The
institutional leg is an **unweighted mean of up to four parts** (`ratings`, `revisions`,
`price_target`, `news`). So news is `1/N` of 0.692:

| Parts scoring | News share of `S_S` |
|---|---|
| 4 | 17.3% |
| 1 (news only) | **69.2%** |

The lexicon's influence is **highest exactly where analyst coverage is thinnest** — which is
backwards, since those are the names where it is least corroborated. Measured coverage on
today's live Finnhub payloads, 24 tickers, 2,432 articles:

> **48.5% overall**, consistent with the documented ~50% — but ranging **33.3% (GM) to
> 68.5% (AMD)** per ticker.

Under redistribution the honest mitigation is not a weight haircut but making the leg's
share stable: give the parts explicit weights instead of an unweighted mean, so news cannot
silently become two-thirds of sentiment.

**Q3 — retail momentum.** Redistribution is what makes this urgent: the noisiest, most
gameable leg is the one that gains most from `executive_tone`'s absence, rising to **0.308**.
The score is `clamp(delta / max(mentions, prior, 10))`, so the floor of 10 means a name going
from 0 to 10 mentions scores **+1.0, maximum bullish**, on ten Reddit posts. That is ~31% of
`S_S` from attention noise. **Cap it at its nominal 0.20** and let `institutional` absorb the
remainder — this keeps redistribution as the rule while refusing to let it promote the one
leg that measures attention rather than sentiment.

**Q4 — `S_F`.** Declare it permanently `n/a`. It is 0.10 of the US formula and 0.05 of EU;
under redistribution the cost of dropping it is small and already handled. A curated filer
universe, a new table, a migration and a two-quarter diff was not justified by 0.10
weight while `S_M` - weight 0.30 - did not score for 15 of 24 names. The sector-exposure
fix removes that macro deferral; revisit `S_F` from the current `PC1-LIVE-03` evidence
row instead.

---

## 6. Ordered by value

1. **Closed:** drop the scheduled historical put/call call that exposed the `"latest"`
   sentinel and spent the AV daily budget.
2. **Closed:** declare the missing `sector_exposures`, including `Semiconductor Equipment`,
   and normalize `Defense` spelling.
3. **Closed:** land P4/P5 so declared sectors stop scoring `partial`.
4. **Correct `SOURCE_STATUS.md`** — Alpha Vantage is up, and the doc says otherwise.
5. **Drop RHM.DE, LDO.MI** (and revisit ASML.AS, SIE.DE); de-duplicate RHM.DE and NVDA
   across the two config files.
6. **Closed 2026-09-02:** `retail_momentum` is capped at 0.20 and the institutional leg
   carries explicit part weights with the news part capped at 0.25 of the leg.
7. **Closed 2026-09-02:** `S_F` declared permanently `n/a`; the live ownership fetch and
   its two preflight probes are removed, so nothing spends metered quota on it.
8. **Closed 2026-09-02:** leave the grade bands alone; fix `P(thesis band)` by making
   directional setups use side-of-spot probability.

## What was not verified

- The seven FRED factor probes are **another session's results**, quoted as reported, not
  re-run here.
- Lexicon coverage is one day's Finnhub payloads for 24 US tickers.
- `preflight --deep` was **not** run: Alpha Vantage's budget was already 25/25 by the time
  the pipeline finished, so a deep probe today would have measured an exhausted key rather
  than the key's entitlements. Run it first thing tomorrow.
