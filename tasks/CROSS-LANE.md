# Cross-lane register

Append-only. One entry per event. Do not edit or delete another lane's entry.

**Write here instead of editing a file you do not own.** The parallel arrangement (D8) is a
convention, not a tool guarantee — an edit outside your lane silently destroys another
agent's work with no warning and no conflict marker.

## When to add an entry

1. **You need a file another lane owns.** Say which file, which task, and why. Do not edit
   it. If the lane that owns it has finished, it may make the change for you; if not, Lane F
   makes it during integration.
2. **You are rejecting a recommendation in `DECISIONS.md`.** The D5 refinement is
   explicitly Lane A's to reject. Record the reasoning; a decision reversed without a
   written reason gets reversed back later.
3. **You found something that invalidates another lane's premise.** More urgent than the
   others — say so plainly and flag the affected lane by name.
4. **You finished.** One line, so dependent lanes know.

## Entries

### Template

```
### [YYYY-MM-DD] Lane X — <one-line summary>
**Type:** file request | decision rejection | invalidated premise | completion
**Affects:** Lane Y / <file path>
**Detail:** what and why, in a few sentences.
**Resolution:** filled in when settled.
```

---

### [2026-09-07] Lane 0 — register opened
**Type:** completion
**Affects:** all lanes
**Detail:** Release plan written and decisions recorded. Lanes A–E may start once Lane 0
reports the baseline commit.
**Resolution:** —

### [2026-09-07] Round 2 — opened
**Type:** completion
**Affects:** Lanes G, H, I, J
**Detail:** Round 1 closed (`RESULTS.md`, 641 tests passing, 6 of 8 criteria met). Round 2
opened by the round-1 live run `daily-2026-09-07-f1b0d2e1`, which reported `succeeded`
while having reached no providers. Decisions D9–D12 appended to `DECISIONS.md`; D12
(backfill funding) is deliberately open pending Lane I. Round-1 files are released, so
G/H/I/J own them freshly — verified disjoint, no collisions.
**Resolution:** —

### [2026-09-07] Lane G ↔ Lane H — completeness-summary field names
**Type:** file request
**Affects:** Lane G (producer) / Lane H (consumer)
**Detail:** Lane G task G4 publishes a run completeness summary; Lane H task H3 renders it
as the run-health banner. The two must agree the field names before either builds against
them. Neither should read the other's in-progress code. **Lane G proposes, Lane H confirms
here.**
**Resolution:** — awaiting Lane G's proposal.

### [2026-09-07] Lane I → Lane J — D12 blocks backfill execution
**Type:** invalidated premise
**Affects:** Lane J task J3
**Detail:** The backfill provider is not yet chosen; D12 is open pending Lane I's research.
Lane J must **not** execute a full backfill until Lane I reports and the owner decides.
Lane J task J1 (the correctness reproduction test) is explicitly **not** blocked — it is
cheap, gates everything, and is independent of the source chosen.
**Resolution:** — awaiting Lane I.

### [2026-09-08] Lane I — research complete: no free source, recommend one paid month
**Type:** completion
**Affects:** Lane J, D12, PA2 decision A5
**Detail:** `docs/research/alternatives/historical-options-sources.md` is written and closes the
research half of D12. Findings: **Quiver serves no options data at all** — its public
OpenAPI schema (52 endpoints, HTTP 200) contains zero occurrences of `strike`, `expiration`,
`implied` or `open interest`, and options paths 404 while known paths 401. **Tradier has no
past-date chain route** — verified by unauthenticated route probe; every historical-chain
path variant returns 404 while the live chain route returns 401. **Polygon can be retired
from PA2's "monitor" list** — its IV/OI surface is an as-of-now snapshot with no date
parameter, and per-contract reconstruction at the free 5 req/min is 240+ hours for a sampled
chain. The nearest free miss, the keyless DoltHub `post-no-preference/options` dataset,
serves genuine past-dated chains with IV and greeks but has **no volume and no open-interest
columns**, so `pc_ratio_vol` and `pc_ratio_oi` are uncomputable from it; it also truncates to
4 expirations with no true weekly, and covers 16 of the 18 names.
**Recommendation: buy one month of Alpha Vantage premium ($49.99, 75 req/min, cancel
anytime — verified), backfill the 344 remaining pairs in ~5 minutes, cancel.** One
outstanding free lead the owner could test in ten minutes first: MarketData.app's documented
`/v1/options/chain/{symbol}/?date=` with `iv`/`volume`/`openInterest`; unverified because
this lane may not register accounts.
**Resolution:** — D12 stays open until the owner picks. Lane J's J1 reproduction test should
run first regardless; **do not pay until it passes**, since a paid key that cannot reproduce
a known-good row buys nothing.

### [2026-09-08] Lane I → PA2 — decision A5 revisited and reversed on new evidence
**Type:** decision rejection
**Affects:** `docs/research/alternatives/pa2-iv-history-and-chain-failover.md` (not edited — Lane I
does not own it)
**Detail:** PA2(a) rejected paid IV history and recorded A5: "revisit only if the warm-up
proves unacceptable in practice." That condition is met (3 of 20 sessions after five days,
`iv_rank` NULL on every row, ~14 more days implied). PA2's objection was to *a subscription*
to remove a 20-session wait on a leg weighted 0.10; the recommendation here is a **one-off
$50 cancelled the same day**, and the inert weight is 0.35 not 0.10 once the `put_call`
percentile terms are counted, since they are withheld by the same 20-session rule. PA2's
reasoning is not contradicted — its premise changed. PA2 is left unedited; Lane F may add a
pointer to `historical-options-sources.md` during integration if it wants the trail closed.
**Resolution:** —

### [2026-09-08] Lane I — amendment: MarketData.app probed, `iv` null on all past-date rows
**Type:** completion
**Affects:** Lane J, D12 — amends the Lane I completion entry above
**Detail:** The first entry listed MarketData.app as an unverified documented lead. It has since
been **probed and largely resolved**, so that line is superseded. `GET
https://api.marketdata.app/v1/options/chain/AAPL/?date=2026-08-10` answers **keyless**, HTTP 203
`"s":"ok"`, with a genuine past-dated chain: `updated` = 2026-08-10T20:00:00, `underlyingPrice`
308.26, real `volume` and `openInterest` (637,984 OI across 190 contracts), a dense 2.50-point
near-money strike ladder, and — with `from`/`to` — 1,336 contracts across 10 expirations
including a true 4-DTE weekly and a 32-DTE monthly. So `pc_ratio_vol`, `pc_ratio_oi`,
`expected_move_1w` and `expected_move_1m` are all obtainable free today.
**But `iv` is null on every past-date row, along with all greeks.** Established as an endpoint
property rather than a recency cutoff by a controlled test: the same endpoint, same session
(2026-09-04), same 122 contracts returns `iv` on 122 of 122 **without** `date=` and 0 of 122
**with** it. Five historical dates tested, all uniformly null. Also: **AAPL is the only keyless
symbol** — SPY, QQQ and CRWV return 401.
Net effect: the recommendation is **unchanged** (buy one month of Alpha Vantage premium), but the
reasoning is sharper — every free source fails on `iv_atm` specifically, which is the exact field
the 20-session warm-up exists to build. One open lead remains for the owner alone: whether a
registered MarketData.app token populates `iv` on a past-date request. The boundary test predicts
it will not.
**Resolution:** — D12 still awaits the owner's choice.

### [2026-09-08] Lane G — completeness-summary field names confirmed as `RunHealth`
**Type:** completion
**Affects:** Lane H / `src/briefing_app/dashboard/models.py`
**Detail:** Closes the open "Lane G ↔ Lane H — completeness-summary field names" entry
above. Lane G produces exactly `briefing_app.dashboard.models.RunHealth`
(`models.py:147`) — no proposal of its own and no additional fields, since the model is
`extra="forbid"` and Lane H owns it:

```
components_scored: int      components_defined: int
names_scored: int           names_gated: int
providers_answered: list[str]   providers_expected: list[str]
total_provider_outage: bool
```

Semantics as produced, so the banner's arithmetic is not guessing:
- `components_defined` counts component slots the run **attempted**, excluding
  `DECLARED_UNSCORABLE_COMPONENTS` (`S_F`, permanently n/a by decision Q4). Counting a
  deliberate permanent `n/a` would leave every run one component short of complete and
  put the banner on every healthy run.
- `names_gated` is names attempted after the gate (post-`max_tickers`), `names_scored`
  those with a non-null `S_CTE`.
- `providers_expected` is the **lead** provider of each consumed chain — first entry that
  is wired and credentialled. Fallbacks are excluded on purpose: a fallback behind a
  healthy lead is meant to go unused, and listing it would make
  `unanswered_providers` non-empty on every healthy run.
- `total_provider_outage` is true only when every expected provider went unanswered and
  at least one ticker pull completed.

Wired at `pipeline.py`'s `build_dashboard_payload(..., run_health=run_health)` call site;
`render.py:135` `_run_health_banner` and the three banner tests in `tests/test_render.py`
consume it unchanged. **No change is requested in any Lane H file.**
**Resolution:** settled — Lane H's shipped shape adopted as-is.

### [2026-09-08] Lane G → Lane F — `RESULTS.md` item 2 is wrong and needs replacing
**Type:** file request
**Affects:** Lane F / `tasks/RESULTS.md`
**Detail:** G5. Item 2 ("Live run clean") is marked **Passed** citing
`status=succeeded, failures=0, diagnostics=0` on `daily-2026-09-07-f1b0d2e1` — the run
that reached no provider. That verification was reading a status that could not fail:
before D9, per-ticker problems never reached `output.diagnostics`, so `_final_status`
could only ever return `succeeded` for a run that did not raise. Lane G does not own
`RESULTS.md` and has not edited it. Proposed replacement row:

> | 2. Live run clean | **Failed — verification was invalid** | Withdrawn. The original evidence (`daily-2026-09-07-f1b0d2e1`, `status=succeeded`, `failures=0`, `diagnostics=0`) was read from a status that could not fail: per-ticker problems accumulated in a local `issues` list that never reached `output.diagnostics`, so `_final_status` returned `succeeded` for a run that made zero requests to Financial Modeling Prep, Finnhub and Alpha Vantage and wrote no raw cache. Lane G (D9) closed that; re-verify against the corrected status. **`partial` is the expected and correct result** for the current data situation, and item 2's wording should be read against definition-of-done items 9 and 10 rather than requiring zero diagnostics. |

And, for the "Live Run" block below the table, the honest reading of that run under the
new rule: `status=partial`, with an `outage:` diagnostic naming the providers that were
never reached. **Lane G has not re-run it** — the owner has not authorised network spend
for this lane and Lane J needs the shared 25/day Alpha Vantage allowance. The command to
produce the replacement evidence is
`PYTHONPATH=src .venv/bin/python -m briefing_app.cli run-daily --data-mode live --force`,
then read `data/runs/<date>/<run-id>.json` for `status`, `diagnostics` and `run_health`.
**Resolution:** — awaiting Lane F.

### [2026-09-08] Lane G — finished
**Type:** completion
**Affects:** all lanes
**Detail:** D9 implemented. G1–G4 done, G5 handed to Lane F above. All 36 `issues.append`
recording points classified normal/degraded/outage; table in `docs/architecture/RUN-HEALTH.md` and
pinned by a test that fails if `pipeline.py` grows an unclassified recording point.
Degraded and outage issues are aggregated (one diagnostic naming N tickers, not N
diagnostics) into `output.diagnostics`, so the **existing** `_final_status` rule returns
`partial` — no second status rule was written. Total outage is detected and named
separately. `RunHealth` is on the run output, in `dashboard.json`, in the saved status
file and in `briefing_run.details`. Suite: **659 passed, zero failures** (baseline 649 +
10 new tests). Files written: `src/briefing_app/pipeline.py`, `tests/test_pipeline.py`,
`tests/test_orchestration.py`, `docs/architecture/RUN-HEALTH.md`, this register. No file outside the
lane was touched.
**Resolution:** —

### [2026-09-08] Lane J → Lane I / D12 — the free tier cannot serve the backfill at all
**Type:** invalidated premise
**Affects:** Lane I / D12 / `docs/architecture/decisions/`
**Detail:** D12 is framed as a choice between paying for Alpha Vantage premium, **waiting
14 days on the free allowance**, and a reduced ticker set. The middle option does not
exist. `HISTORICAL_OPTIONS` is not on the Alpha Vantage free tier: it answers HTTP 200
with a plausible sample payload that validation reports as `synthetic` — this project
already recorded it, in `docs/research/SOURCE_STATUS.md` ("Alpha Vantage premium endpoints answer
HTTP 200 with an artificial sample schema", and the summary row `realtime_options`,
`daily_adjusted`, `historical_options` → `synthetic`). Waiting produces 25 refusals a day,
indefinitely, not a slow backfill. The real D12 choice is: pay for the endpoint, find
another source, or drop the backfill. Nothing synthetic can reach the store —
`fetch_function` validates before returning — but the requests are spent, so Lane J now
stops on the first `synthetic` answer and after three consecutive failures.
**Resolution:** — for the owner, when closing D12.

### [2026-09-08] Lane J → Lane I / D12 — the backfill vendor must match the live one
**Type:** invalidated premise
**Affects:** Lane I / D12 / Lane J task J3
**Detail:** A second D12 input, found during the J1 audit. Every stored `iv_atm`,
`pc_ratio_vol` and `pc_ratio_oi` in this project came from a **CBOE** delayed chain —
`config.providers.options` is `[cboe, alpha_vantage]` and `evidence_ledger` records `CBOE
delayed options` for all 1,235 `S_O` rows. The backfill reads **Alpha Vantage** historical
chains. Same functions, different vendor, and a different time of day: the CBOE captures
are intraday (2026-09-03 17:14:21 UTC), an AV historical chain is the close. An IV rank is
a percentile of one series; splicing two vendors into it produces a confident number for a
comparison that was never made, invisibly. So a source should be judged on **consistency
with the live CBOE chain**, not only on price — a historical CBOE chain may be the cheapest
correct answer, and a cheaper non-CBOE source may not be an answer at all. Lane J now
refuses to write on a vendor mismatch unless `--allow-vendor-splice` is passed, and stamps
`chain_source` / `chain_venue` / `chain_as_of` / `live_options_provider` on every
backfilled row.
**Resolution:** — awaiting Lane I / the owner.

### [2026-09-08] Lane J — J1 audited and closed, J2 built, J3 still blocked
**Type:** completion
**Affects:** Lane F / Lane G / the owner
**Detail:** J1: the round-1 test built both sides with the backfill's own row builder, so
it proved the backfill agrees with itself, not that it reproduces a **stored live** row.
Closed with `test_backfill_reproduces_a_row_the_live_path_stored`, which builds the live
side through `scoring.to_daily_snapshot_row` with the live pipeline's argument set, stores
it, runs `run_iv_backfill` end to end into a second store, and compares stored rows: spot,
`iv_atm`, both put/call ratios, both expected moves and `rr_25d` match exactly.
`realized_vol_20d` is NULL on backfilled rows by construction (no price bars) and is now
asserted as such. J2: a live-run-first reservation — the full 25 held back until today's
live run has finished, then all but 6, both numbers taken from the recorded daily counters
in `data/provider_budget/alpha_vantage/`. J3 remains blocked on D12; no backfill request
has been sent and `--dry-run` reports `spendable: 0` under the new policy. Files touched:
`src/briefing_app/backfill.py`, `src/briefing_app/cli.py`, `tests/test_backfill.py`,
`docs/operations/IV-BACKFILL.md`. Suite: 671 passed, 0 failed.
**Resolution:** —

### [2026-09-08] Integration — round 2 closed, open register entries resolved
**Type:** completion
**Affects:** all round-2 lanes
**Detail:** Lanes G, H, I and J are complete and the suite is **671 passing, zero
failures** (verified independently at integration, exit 0). Resolving the entries left open
above, rather than editing them in place:

- *Lane G ↔ Lane H, completeness-summary field names* — **settled.** Lane H had already
  shipped the consumer, so the `RunHealth` model in `dashboard/models.py` was handed to
  Lane G as the agreed shape rather than being negotiated. Lane G produces exactly those
  fields; no field was added and `extra="forbid"` still holds.
- *Lane I → Lane J, D12 blocks backfill execution* — **partly settled.** Lane I has
  reported (`docs/research/alternatives/historical-options-sources.md`) and Lane J completed J1, J2
  and J4 without spending a request. **J3 remains blocked**: D12 is a funding decision and
  the owner has not made it.

Integration also updated `README.md` (run health, the two grade scales, thesis-versus-data,
and the backfill's two new guards plus the free-tier finding), `RESULTS.md` (item 2
corrected and withdrawn, round-2 results recorded) and `HANDOFF.md` (stale 611-test
baseline corrected to 671).

**Two round-2 findings change the D12 options the owner was given**, and are recorded here
so the decision is not made against the old picture: Alpha Vantage `HISTORICAL_OPTIONS` is
not on the free tier, so "wait 14 days" does not exist; and the stored live rows are CBOE
while the backfill reads Alpha Vantage, so filling the history does not by itself produce a
comparable percentile series.
**Resolution:** round 2 closed. Remaining work is the owner's D12 decision, the live
re-verification of items 2/9, and J3.

### [2026-09-08] Round 3 — opened; D12 closed by D13
**Type:** completion
**Affects:** Lanes K, L, M, N, O — and supersedes every open round-2 entry about D12
**Detail:** The owner took four decisions on 2026-09-08 — **D13, D14, D15, D16** — appended
to `DECISIONS.md`. Round-3 lane map, file ownership and definition-of-done items 16–21 are
at the bottom of `README.md`. Baseline verified independently: **671 tests collected, suite
green.**

What changes for anyone carrying round-2 context:

- **D12 is closed. Nothing is bought and no bulk backfill is scheduled.** D13 lowers
  `SELF_BUILT_SERIES_MIN_SESSIONS` from 20 to 10 and publishes anything below 20 as
  **provisional**. Lane I's recommendation to buy one month of Alpha Vantage premium was
  read and declined. The two round-2 entries that leave D12 "awaiting the owner" are
  resolved by this.
- **D14 keeps Lane J's vendor guard and commissions a measurement.** Note the tension,
  because it is real and Lane M must not stall on it: the owner chose "measure first" *and*
  chose not to pay, and the implied-volatility half of the measurement needs a paid key,
  since Alpha Vantage `HISTORICAL_OPTIONS` answers `synthetic` on the free tier. The
  put/call half **is** measurable free today via MarketData.app's keyless past-date chain,
  which Lane I already verified serves real `volume` and `openInterest`. Lane M measures
  that half and writes the other half up unexecuted.
- **D15 splits the ideas table into supported and contradicted theses**, closing the
  consequence D11 left open. `dashboard/grading.py` is **owned by nobody this round**, so
  D11's prohibition on fixing the tied-zero block by changing a grade is enforced by
  ownership rather than by trust.
- **D16 permits lanes to make live requests inside a written, checked allowance.** Lane N
  builds the ledger. Until it exists, no lane spends. Standing allowances are in D16 and
  are 0 for every lane except O, which gets one daily run.

**One coordination point, and it is the only one:** Lane K needs a provisional-baseline
field on a model in `dashboard/models.py`, which **Lane L owns**. K proposes the names and
semantics here; L confirms here and adds the field. Same protocol as the Lane G ↔ Lane H
`RunHealth` exchange above, which worked because the shape was agreed in writing before
either side built against it.

**The gate:** the working tree is not committed. Commit it as the round-3 baseline, run the
suite, and record the commit hash and test count here before any lane starts writing.
**Resolution:** — awaiting the baseline commit.

### [2026-09-09] Round 3 — premises re-checked before any lane started
**Type:** completion
**Affects:** all round-3 lanes
**Detail:** Re-verified the numbers every round-3 lane document is written against, one day
after they were recorded. **All unchanged:** 671 tests collected, `SELF_BUILT_SERIES_MIN_SESSIONS`
still 20 at `pipeline.py:215`, 3 distinct sessions in `daily_snapshot` (2026-09-03, 09-06,
09-07), 0 rows with `iv_rank` populated. No round-3 lane has created any file yet.

**The gate is now mostly satisfied.** `src/`, `tests/`, `config/` and `ops/` are committed at
`94b1e7f`; only documentation and planning files remain uncommitted. Lanes K–N can start as
soon as that commit is made — none is blocked on code landing first.

Three findings about the run cadence that item 21 depends on, stated in proportion:

1. **The cadence has been good, and 2026-09-08 (Tuesday) is the first missed weekday.**
   Runs are recorded for 08-30, 08-31, 09-01, 09-02, 09-03, 09-04, 09-06 and 09-07 — eight
   days in ten, including a Sunday. Only 09-05 (Saturday) and 09-08 are absent, and today's
   run may still happen. This is **one missed day, not a pattern**, and it should not be
   read as the local-scheduling failure D1 warned about until it repeats. It is still a day
   the baseline did not advance, which is why O3 now tracks it.
2. **The 09-04 gap is explained and is not an ongoing leak.** There is a live run for
   2026-09-04 (`daily-2026-09-04-de8fa872`, `succeeded`) but no session for it in
   `daily_snapshot`. Its rows were removed by round 1's fixture purge — `RESULTS.md` records
   `select count(*) from daily_snapshot where run_id = 2` returning 0. **Since the purge,
   every live run has added exactly one session**, so D13's projection of one session per
   weekday run holds and nothing needs re-deriving.
3. **A degraded run still advances the baseline, which makes item 21 more robust than it
   looks.** Run `daily-2026-09-07-f1b0d2e1` reached none of Financial Modeling Prep, Finnhub
   or Alpha Vantage, and still stored `iv_atm` for most names — because the options lead is
   **CBOE, which is keyless and free** and was unaffected. So the sessions that fill the
   volatility baseline do not depend on the contended Alpha Vantage allowance, and Lane N's
   budget work and Lane O's item 21 are less coupled than they first appear.

**Net effect on the plans: none of the arithmetic changes.** D13's "7 more weekday runs"
stands, provided a run happens on each. Lane O task O3 now reports sessions stored **and**
weekday runs that occurred, so a stalled cadence is never mistaken for a stalled lane.
**Resolution:** — surfaced to the owner 2026-09-09.

### [2026-09-09] Documentation reorganised — read this before opening any path from memory
**Type:** invalidated premise
**Affects:** every lane, and any session carrying paths from before 2026-09-09
**Detail:** The documentation was split by audience. **If you remember a document's path,
it has probably changed.** The full suite was re-run after the move: **671 passed, zero
failures**, and an automated link check reports **0 broken links** across 85 markdown files.

- `docs/` is now **for people to read**: `product/`, `architecture/`, `research/`,
  `operations/`, `archive/`. Map at [`docs/README.md`](../docs/README.md).
- `tasks/` is now **only work an agent executes**: `tasks/README.md`, `tasks/lanes/`,
  `CROSS-LANE.md`, `RESULTS.md`, and `tasks/archive/` for closed rounds. The
  `tasks/release/` directory is gone.
- **`DECISIONS.md` no longer exists as one file.** It is split into sixteen records at
  [`docs/architecture/decisions/`](../docs/architecture/decisions/), one per decision,
  each carrying its status and what supersedes it. **Numbering follows the original `D`
  numbers** — `D13` is `0013` — so every existing citation still resolves. Index and
  status table at `decisions/README.md`.
- Superseded documents moved to `docs/archive/`, each explained in `docs/archive/README.md`.
  Nothing there is current.
- `HANDOFF.md` was reduced from 892 lines to an onboarding page holding only what a fresh
  session cannot infer from the code. The full original is preserved at
  `docs/archive/handoff-2026-09-03-full.md`.

Every reference was rewritten in one pass: 300 substitutions across 58 files, including 20
in `src/` and `config/` (for example `pipeline.py`'s pointer to `RUN-HEALTH.md` and
`universe.example.yaml`'s pointers to the European-source studies). Lane ownership blocks
were rewritten with the rest and re-verified **disjoint, no collisions**; every owned file
either exists or is one the lane is due to create.

`trading ideas.md` and `trader analysis v2.md` were deliberately **not** moved — both are
in `.gitignore`, and relocating them into a tracked directory would have committed private
material.
**Resolution:** settled — no lane action required beyond using the new paths.
