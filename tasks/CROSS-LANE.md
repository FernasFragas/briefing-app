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

### [2026-09-09] Lane L ↔ Lane K — provisional-baseline model shape and interim suite failure
**Type:** file request
**Affects:** Lane K (producer) / Lane L (model and renderer consumer)
**Detail:** Lane L began after the round-3 register re-check. The required first suite run
currently reports **669 passed, 2 failed**, rather than the recorded 671: both failures are
config validation errors because `config/config.example.yaml` now contains
`pipeline.self_built_series_min_sessions` and `pipeline.self_built_series_full_sessions`
while `AppConfig` does not yet accept them. Lane L will not edit either Lane K file.

Lane K's required proposal for the `TradingIdeaRow` provisional-baseline fields is not yet
in this register. Please propose the exact field names, types, and semantics here. Lane L
will confirm the shape before adding it to `src/briefing_app/dashboard/models.py`, which is
`extra="forbid"`, and will then render the agreed session count.
**Resolution:** — awaiting Lane K's proposal and compatible configuration change.

### [2026-09-09] Lane K → Lane L — proposed volatility-baseline record shape
**Type:** file request
**Affects:** Lane L / `src/briefing_app/dashboard/models.py`, `src/briefing_app/dashboard/build.py`, `src/briefing_app/dashboard/render.py`, `tests/test_dashboard.py`, `tests/test_render.py`
**Detail:** D13 needs every published self-built percentile to carry its own sample size and provisional state through `daily_snapshot`, `dashboard.json`, and the page. Lane K proposes a `VolatilityBaseline` model with `sessions: int` (the number of historical observations used; excludes today's reading) and `provisional: bool` (`True` for 10–19 sessions, `False` at 20+). Add a `volatility_baselines` mapping adjacent to the existing options readings, keyed exactly `iv_rank`, `put_call_volume_percentile`, and `put_call_open_interest_percentile`. A key is present only when its corresponding percentile is published; a withheld (&lt;10) percentile has no fabricated status record. Lane K will produce this mapping from `TickerData`, persist the same mapping in `daily_snapshot.raw["volatility_baselines"]`, and pass it to the dashboard builder once Lane L confirms the builder parameter and destination field name.
**Resolution:** awaiting Lane L confirmation of this exact public shape and builder handoff.

### [2026-09-09] Lane N → Lane M — missing provider counter must keep the live-run reserve intact
**Type:** file request
**Affects:** Lane M / `src/briefing_app/backfill.py`
**Detail:** D16's ledger acceptance case is the 2026-09-07 shape: a finished run record but no
`data/provider_budget/alpha_vantage/<today>.json` because the run reached no Alpha Vantage
provider. The ledger will deny spending in that state; treating the nominal `25 - 0` as spare
would reproduce the silent-success failure. It uses the same existing 25-before / 6-after
reservation amounts, but requires a recorded counter before the run may release the 6-request
post-run floor. `plan_budget_reservation()` currently treats a completed database row with no
counter as 19 spendable. Please align that guard if Lane M may touch backfill policy this round;
Lane N will not edit the file.
**Resolution:** — awaiting Lane M.

### [2026-09-09] Lane L → Lane K — volatility-baseline record shape confirmed
**Type:** completion
**Affects:** Lane K / Lane L
**Detail:** Confirmed. Lane L will add `VolatilityBaseline` to
`briefing_app.dashboard.models` with `sessions: int` and `provisional: bool`, and add
`TradingIdeaRow.volatility_baselines: dict[str, VolatilityBaseline]`. The mapping accepts
only the three exact public keys proposed by K: `iv_rank`, `put_call_volume_percentile`,
and `put_call_open_interest_percentile`; a published mapping entry therefore carries its
own observation count and provisional state, while a withheld percentile has no entry.

The agreed builder handoff is
`build_dashboard_payload(..., volatility_baselines: Mapping[str, Mapping[str, object]] | None = None)`:
the outer key is the ticker and the inner mapping is passed into that ticker's
`TradingIdeaRow.volatility_baselines`. Lane K can pass serializable `{sessions, provisional}`
mappings from its `TickerData` without importing dashboard presentation code. Lane L will
validate the public model shape and render the marker.
**Resolution:** settled — Lane K may wire the agreed builder argument after Lane L lands it.

### [2026-09-09] Lane K → Lane N — full-suite failure in Lane N status assertion
**Type:** invalidated premise
**Affects:** Lane N / `tests/test_ops_scripts.py`, `ops/status.py`
**Detail:** Lane K's required full-suite verification stopped at `test_status_explains_non_clean_job_record`. The current implementation returns two attention messages, headed by `completed daily run has no recorded Alpha Vantage budget counter`, while the Lane N-owned assertion still expects exactly `["latest local job did not complete cleanly"]`. The production behavior and test are inconsistent; Lane K did not edit either file.
**Resolution:** awaiting Lane N.

### [2026-09-09] Lane L — report split complete
**Type:** completion
**Affects:** Lane K / Lane O
**Detail:** D15 is implemented without a grading change. Wrote:
`src/briefing_app/dashboard/build.py`, `src/briefing_app/dashboard/models.py`,
`src/briefing_app/dashboard/render.py`, `tests/test_dashboard.py`,
`tests/test_render.py`, `docs/product/REPORT-LAYOUT.md`, and this append-only register.

The first required full-suite run was **669 passed, 2 failed** because Lane K had written
the new config keys before its `AppConfig` support landed; Lane L did not touch those files.
After the agreed K/L handoff and this lane's changes, the full suite is **680 passed, zero
failures** (one third-party FastAPI deprecation warning). Targeted dashboard/render
verification is **56 passed**. `ops/audit_dashboard.py output/published/latest/dashboard.json`
returned `{"ok": true, "rows_checked": 16}`; `git diff --check` was clean; and both
`git diff --stat -- src/briefing_app/dashboard/grading.py` and the grading-file diff were
empty.

The public split is `supported_theses` / `contradicted_theses`, while the flat
`trading_ideas` audit list remains for the grade reconciler. A model invariant requires
every row to occupy exactly its data-derived section; supported rows rank by conviction.
The agreed D13 mapping is `TradingIdeaRow.volatility_baselines`, whose exact three keys
carry `VolatilityBaseline(sessions, provisional)`. The only additional row-local display
decision was to publish the existing crowding deduction as `crowding_penalty`; it uses the
same default grading setting and confidence multiplier as the unchanged grader. No live
requests were made.
**Resolution:** complete.

### [2026-09-09] Lane K → Lane L — rendered-page D13 test name needed for the baseline reference
**Type:** file request
**Affects:** Lane L / `tests/test_render.py`, `docs/architecture/VOLATILITY-BASELINE.md`
**Detail:** K5 must name the test that pins the provisional marker and session count on the rendered page. Lane K will not read Lane L's in-progress test file. Please record the final test name here when the render work is complete; Lane K will add that name to its owned volatility-baseline reference.
**Resolution:** awaiting Lane L.

### [2026-09-09] Lane K → Lane N — `live_budget` CLI test leaks `.env` credentials into later pytest cases
**Type:** invalidated premise
**Affects:** Lane N / `tests/test_ops_scripts.py`, `ops/live_budget.py`
**Detail:** The full-suite failure in `test_daily_live_run_fetches_provider_payloads_and_scores` has a reproducible order dependency: `tests/test_ops_scripts.py` alone followed by that test fails, while `tests/test_options_math.py` followed by it passes. `test_live_budget_returns_exit_codes_and_json_verdict` calls `live_budget.main`, which calls `configure_environment()` and loads `.env` into the process without cleanup. Later fake-live tests then discover actual optional keys (first observed: Finnhub) and attempt URLs their fake fetcher intentionally does not serve. Lane K made its owned fake-live tests explicitly remove optional provider keys, but the Lane N test still leaves global process state behind for any other later test.
**Resolution:** awaiting Lane N.

### [2026-09-09] Lane K → Lane N — full-suite evidence for the `.env` leak
**Type:** invalidated premise
**Affects:** Lane N / `tests/test_ops_scripts.py`; affected tests: `tests/test_provider_clients.py`
**Detail:** Resumed command `PYTHONPATH=src .venv/bin/python -m pytest -q` reached 100% and exited 1 with exactly two failures: `test_fred_client_requires_key_before_network` and `test_finnhub_client_requires_key_before_network`. Both hand-built settings intentionally omit the provider key and use `FailingFetcher`, but each URL contained a real key loaded from `.env`; neither assertion reached its expected `ProviderDataError`. This is the concrete downstream effect of the earlier Lane N `live_budget.main` environment mutation, not a Lane K behavior failure.
**Resolution:** awaiting Lane N.

### [2026-09-09] Lane N — D16 live-run budget ledger complete
**Type:** completion
**Affects:** Lane O / `tasks/BUDGET-LEDGER.md`
**Detail:** Wrote `ops/live_budget.py`, `ops/status.py`, `tests/test_ops_scripts.py`,
`docs/operations/LIVE-RUN-BUDGET.md`, and `tasks/BUDGET-LEDGER.md`. The checker reads the
provider's dated counter, the append-only claims and outcomes, and the daily-run record before
authorising a request; it returns JSON and exit 2 for `NO`. It imports the existing backfill
25-before/6-after reserve amounts. A completed daily run with no Alpha Vantage counter keeps
the full 25 held: that is the 2026-09-07 provider-less-run shape, not a healthy 25 available.
`ops/status.py --json` now exposes this position even when its normal last-run record is absent.
The ledger has the required unclaimed-lane rule, append-only claim/outcome tables, and a worked
example. Lane O may now append its owner-named `daily-run` claim and use the checker before its
one authorised run; without that claim the verdict remains `NO`.

Evidence: before work, `PYTHONPATH=src .venv/bin/python -m pytest -x` was **1 failed,
378 passed** (the shared `tests/test_orchestration.py::test_daily_live_run_fetches_provider_payloads_and_scores`
expected `succeeded` while the in-progress live path returned `partial`). After, the owned
check `PYTHONPATH=src .venv/bin/python -m pytest tests/test_ops_scripts.py -q` is **9 passed**;
`PYTHONPATH=src .venv/bin/python -m pytest --collect-only` is **688 tests collected**. A final
full-suite attempt reached 62% with two shared-tree failures; `-x` identifies the same
Lane-K-owned orchestration test as first (**1 failed, 387 passed**), now because its fake
fetcher rejects a Finnhub URL and the run correctly reports `partial`. No tests were deleted.
`ls data/provider_budget/alpha_vantage/` still lists only 2026-08-30, 2026-09-02,
2026-09-03, 2026-09-04, and 2026-09-06: Lane N spent zero requests.

**Resolution:** complete. Lane M has the preceding file request to align backfill's
missing-counter interpretation with this conservative D16 guard; Lane N did not edit
`backfill.py`.

### [2026-09-09] Lane M — D14 measured where free data permits; IV procedure remains unexecuted
**Type:** completion
**Affects:** Lane O / D14 / Lane N
**Detail:** Wrote `ops/measure_vendor_gap.py`, `tests/test_vendor_gap.py`,
`docs/research/alternatives/vendor-consistency.md`, `src/briefing_app/backfill.py`,
`src/briefing_app/cli.py`, `tests/test_backfill.py`, and `docs/operations/IV-BACKFILL.md`.
M1 measured AAPL only, honestly: MarketData.app’s keyless historical 2026-09-03 and 2026-09-04
chains were passed through `normalize_cboe_option_chain` then `build_options_structure`, with
no local ratio arithmetic. The three stored CBOE run-date rows show volume gaps of 8.93%, 0%,
and 55.38%, and open-interest gaps of 3.92%, 0%, and 146.34%; the Sunday and Labor Day rows are
explicitly mapped to the CBOE payloads’ 2026-09-04 last-trade session. M2 is explicitly
**UNEXECUTED**: it gives the paid-key endpoint, 18 exact tickers, 54 comparisons / 36 unique
requests, computation path, and a precommitted all-pairs IV-gap rule. No splice is approved.

The vendor refusal now names the research document and is pinned by a test. At Lane N’s request,
the same owned backfill guard now preserves all 25 requests when a completed live run has no
dated Alpha Vantage counter; its regression test prevents an override from releasing that
provider-less-run capacity. `IV-BACKFILL.md` now states D13’s standing position: retained tool,
no bulk backfill scheduled.

Evidence: focused verification is `PYTHONPATH=src .venv/bin/python -m pytest tests/test_backfill.py tests/test_vendor_gap.py -q` → **20 passed**; dry run reports `requests_sent: 0` and
the vendor-document diagnostic. Final full suite: **687 passed, 2 failed** (689 collected),
not a Lane M failure: `test_fred_client_requires_key_before_network` and
`test_finnhub_client_requires_key_before_network` inherit optional keys loaded into the test
process by Lane N’s `live_budget` test; the cross-lane entry from Lane K already records that
order dependency. The recorded pre-lane baseline was 671 passed; the first Lane M full attempt
was still in progress when other lane changes raised collection above it. No tests were deleted.
`today_counter_exists: False`; the Alpha Vantage counter directory remains exactly
2026-08-30, 2026-09-02, 2026-09-03, 2026-09-04, 2026-09-06, so Lane M spent zero Alpha Vantage
requests.
**Resolution:** complete; decision left open only for the owner: whether to authorize the paid
IV procedure after reviewing its precommitted rule. Until then the refusal stands.

### [2026-09-09] Lane K → Lane N / Lane O — exact full suite remains blocked by the known test-process mutation
**Type:** file request
**Affects:** Lane N / `tests/test_ops_scripts.py` and, if Lane N does not reopen, Lane O integration
**Detail:** The final exact command required by every lane, `PYTHONPATH=src .venv/bin/python -m pytest -q`, completed at 100% with **689 collected, 687 passed, 2 failed**. The only failures are the two FRED/Finnhub no-key tests already traced to Lane N's `live_budget.main` test loading `.env` into the shared pytest process. Lane N's completion record repeats this known result but leaves the owned mutation in place. Lane K cannot edit either Lane N's test or the unowned `tests/test_provider_clients.py`. Please remove or restore the loaded environment in the Lane N test, then re-run the exact suite.
**Resolution:** awaiting Lane N reopening or Lane O integration direction.

### [2026-09-09] Lane K — D13 volatility-baseline threshold complete
**Type:** completion
**Affects:** Lane L / Lane O
**Detail:** Wrote `src/briefing_app/pipeline.py`, `src/briefing_app/config.py`, `config/config.example.yaml`, `tests/test_pipeline.py`, `tests/test_orchestration.py`, `docs/architecture/RUN-HEALTH.md`, `docs/architecture/VOLATILITY-BASELINE.md`, and these append-only register entries. The agreed K/L public mapping is delivered on `TradingIdeaRow.volatility_baselines`, with per-reading `{sessions, provisional}` entries for `iv_rank`, `put_call_volume_percentile`, and `put_call_open_interest_percentile`; the same mapping is persisted at `daily_snapshot.raw["volatility_baselines"]`.

Boundary evidence: `test_self_built_percentile_boundaries_cover_all_three_gated_legs` pins 9 withholds, 10 publishes provisional, and 20 publishes settled for all three legs. `test_provisional_baselines_persist_to_live_snapshot_and_dashboard_json` pins storage and JSON; Lane L's `test_dashboard_html_renders_provisional_baseline_and_crowding_magnitude` pins the page. Warm-up wording is now `baseline below publish floor: N of 10 sessions stored`, classified normal and pinned by the all-recording-points test. The quality decision is deliberately **no quality downgrade**: provenance remains verified CBOE and sample size is disclosed by the flag, so no grade or tier changed.

Tests: recorded pre-lane baseline **671 passing**; current collection **689**. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_pipeline.py tests/test_orchestration.py -q` → **49 passed**. The complete 689-test suite passes under a test-only empty optional-key environment. The exact unmodified suite command reached 100% with **687 passed, 2 failed**, both the already-recorded Lane N `.env` test-process leak (`test_fred_client_requires_key_before_network`, `test_finnhub_client_requires_key_before_network`); Lane K did not edit those non-owned files. `git diff --check` was clean and the grading-file diff was empty. Store remains `sessions: 3`, `iv_rank set: 0`; no live request was made.
**Resolution:** Lane K implementation complete. Exact full-suite status awaits the separate Lane N/O test-isolation fix recorded above.

### [2026-09-09] Lane O — register resolutions and remaining acceptance evidence
**Type:** completion
**Affects:** all lanes / `tasks/RESULTS.md`
**Detail:** K, L, M and N completion entries were present before O began integration.
The following resolutions append to, and never rewrite, the original entries:

- **Lane 0 / baseline gate and documentation move:** historical source/planning baseline
  exists at `545e9e3` (`git log -1 --oneline`). Current integration contains uncommitted
  K–N work, so O1's *clean-tree* premise is not satisfied. No other lane's work was reset
  or committed. The remaining clean-commit/retest condition is explicitly tracked in
  RESULTS item 1; old path references in historical entries are not current instructions.
- **Round 2 opening; G/H RunHealth exchange; G completion; G→F item 2 correction:** settled.
  The agreed RunHealth shape remains; the incorrect old live-success claim stays withdrawn.
  Both healthy success and total-outage partial/name/banner behavior pass offline tests.
  Actual live re-verification is tracked, not asserted, under RESULTS items 2/9.
- **I→J D12 block; I paid-month recommendation/amendment; I→PA2 A5 reversal;
  J free-tier and vendor-match findings; J1/J2/J3 completion; round-2 integration's
  remaining D12 entries:** closed by **D13**, not awaiting funding. No purchase or bulk
  backfill is scheduled. The free-tier and cross-vendor findings remain valid constraints;
  D14 retains the vendor refusal. Historical research is not rewritten to imply its
  declined recommendation was executed. J3's proposed bulk execution is superseded;
  visible-output acceptance is now item 21.
- **Round-3 opening and cadence premise:** implementation complete, operational acceptance
  separate. Read-only evidence is 3 stored snapshot dates, 0 populated IV ranks, and
  **0 completed weekday live runs since K landed September 9**. No September 8 run exists.
  Seven more usable runs accumulate ten observations for a three-input name, but history
  excludes today's row: the following run can publish. Conditional first-reading date is
  **September 18**, if runs start September 9 and happen every weekday. This corrects
  the plan's off-by-one projection without changing the locked storage/history code.
  Weekend/holiday run dates are not independent exchange sessions, and FDX has zero IV
  inputs despite three stored dates. Item 21 is explicitly blocked on run cadence and
  usable input accumulation, not unfinished threshold code.
- **L↔K initial config/shape request; K proposal; L confirmation; K rendered test-name
  request; L and K completions:** settled. The shipped handoff is
  `build_dashboard_payload(..., volatility_baselines=...)`, keyed by ticker, into
  `TradingIdeaRow.volatility_baselines`. Its three keys are `iv_rank`,
  `put_call_volume_percentile`, `put_call_open_interest_percentile`; each uses
  `VolatilityBaseline(sessions, provisional)`. Storage retains the identical mapping in
  `daily_snapshot.raw`. Config validation and all three 9/10/20 boundaries now pass.
  The page test is `test_dashboard_html_renders_provisional_baseline_and_crowding_magnitude`.
  O also strengthened the storage/JSON test to assert all three markers on the produced
  page. No model field or grading change was needed.
- **K→N status assertion; K→N `.env` leak reports and full-suite evidence; K→N/O exact-suite
  request; N completion:** settled by integration. Both CLI unit tests now stub
  `configure_environment()` so they cannot load real local credentials into subsequent
  tests. `PYTHONPATH=src .venv/bin/python -m pytest tests/test_ops_scripts.py tests/test_provider_clients.py`
  returned **53 passed**, exit 0; the exact full-suite command returned **692 passed**,
  exit 0, with no optional-key environment workaround.
- **N→M missing-counter reservation request:** settled. M's guard and N's checker both
  keep the full 25 reserved when a completed run has no recorded counter; the backfill
  regression and ops tests pass. A missing counter is not a proof of historical zero spend.
- **M completion / D14 scope:** free measurement is documented for **AAPL only**, both
  put/call legs. Paid IV is explicitly **UNEXECUTED** with a precommitted all-54-pairs
  acceptance rule; no splice is approved. O verified the computation-path tests but did
  not receive the original measured payloads, so it cannot independently reproduce the
  reported percentages. That missing evidence is assigned to RESULTS item 19: supply
  original payloads for offline replay; new requests require separate authority. The
  paid-key question is not a standing execution task or a reopened D12 decision.
- **Ledger-wide acceptance:** assigned explicitly to RESULTS item 20. There are no active
  claims and no September 9 Alpha Vantage counter. The literal “every provider request
  claimed” wording is broader than D16's explicit untracked MarketData exception; O does
  not certify that broad assertion from an empty ledger or retroactively invent M claims.
  The numeric guard passes; the complete historical reservation audit remains open.

Two K/L integration details were reconciled within O's post-completion ownership grant:
metadata now requires an actual current percentile, not merely sufficient history, with
three new regression cases; and the page says **Provisional — N stored sessions** rather
than hardcoding “of 20” against a configurable settled threshold. The agreed two-field
model stays unchanged. Provisional metadata itself does not alter source quality or grades;
availability of a newly computed reading can affect an options score, so the older blanket
claim that D13 cannot change any score was narrowed in the baseline reference.

**Resolution:** all prior register requests have a disposition above. Open acceptance
conditions are named and owned in RESULTS, not represented as completed criteria. O's
required no-argument budget command returned **NO**, exit 2 (full reserve 25, spendable 0,
no named claim). Live execution stopped. No owner-named day was supplied; no live request,
claim, fabricated outcome, scheduler installation, or bulk backfill was made by O.

### [2026-09-09] Lane O — offline integration handoff; live acceptance remains open
**Type:** completion
**Affects:** owner / next authorized Lane O verification
**Detail:** Offline tasks O1 (suite portion), O4–O7 and O3's dated tracking are delivered.
This is **not** a claim that Lane O's live definition of done is met. O2 remains blocked
on the owner-named day and a passing pre-spend claim; O1's clean-tree condition and the
remaining live/cadence/vendor-evidence criteria are explicitly OPEN in `tasks/RESULTS.md`.

Files written by O (not the combined K–N diff):
`README.md`, `HANDOFF.md`, `tasks/README.md`, `tasks/RESULTS.md`,
`src/briefing_app/pipeline.py`, `src/briefing_app/dashboard/render.py`,
`tests/test_pipeline.py`, `tests/test_orchestration.py`, `tests/test_render.py`,
`tests/test_ops_scripts.py`, `docs/architecture/VOLATILITY-BASELINE.md`,
`docs/product/REPORT-LAYOUT.md`, and append-only `tasks/CROSS-LANE.md`.
The K/L/N-owned files were touched only after all four prerequisite completions, for
the integration issues described in the preceding resolution entry. No locked file changed.

Before: exact `PYTHONPATH=src .venv/bin/python -m pytest` → **687 passed, 2 failed**,
689 collected, exit 1. After: the same command → **692 passed, zero failures**, one
third-party deprecation warning, exit 0, twice (101.71s and final repeat 101.21s).
The original round-3 baseline was 671 passing. Focused acceptance: **14 passed**;
broader six-file integration check: **128 passed**; ops plus provider isolation:
**53 passed**; backfill/vendor: **20 passed**. No tests were removed. Published-dashboard
grade audit: `ok=true, rows_checked=16`; fresh fixture audit: zero failures, 12 ideas split
6/6; `git diff --check`: empty, exit 0; documentation local-link check: zero broken links.

Open choices/premises are recorded rather than guessed: no owner run day, no clean shared
commit, missing original vendor-gap payloads, no manual-launch attribution in historical
run JSON, and no proof of the entire historical budget reservation from absent counters.
The two-field baseline contract was retained; configurable-threshold wording and actual
current-value filtering are the only new producer/display decisions. Current tracking is
**3 stored snapshot dates / 0 post-K weekday live runs / 0 populated IV ranks**; September
18 is a conditional first-reading projection, not a promised setup unlock.
**Resolution:** offline integration handed off. **Zero live requests spent by O**; the NO
budget verdict was obeyed. Resume live verification only with the missing owner authority
and a passing claim check. All remaining acceptance conditions have named closure evidence
in RESULTS; none is silently marked passed.

### [2026-09-09] Lane M (Prompt A) — vendor-gap attribution corrected; D14 unchanged
**Type:** completion
**Affects:** Lane O / D14 / RESULTS item 19 / Prompt B
**Detail:** Continuation of Lane M, not a new lane. Files written, all inside the Lane M set:
`docs/research/alternatives/vendor-consistency.md`, `ops/measure_vendor_gap.py`,
`tests/test_vendor_gap.py`, `docs/operations/IV-BACKFILL.md`, and this append-only register.
`src/briefing_app/dashboard/grading.py` was not touched, nor `pipeline.py`,
`option_metric_history`, or any file outside the four owned documents.

**The corrected interpretation.** The three M1 percentages are arithmetically unchanged; the
causal claim attached to them was wrong. Rows 2 and 3 are **two CBOE captures of the same
2026-09-04 exchange session**, each compared against the same MarketData September 4 payload
— not two independent session observations. Verified from the archived payloads: run date
2026-09-06 carries `data.last_trade_time` `2026-09-04T16:00:00` with 3,140 contracts, run date
2026-09-07 carries the same last-trade time with 3,260 contracts. Row 3's 55.38% volume and
146.34% open-interest differences are therefore **intra-CBOE delayed-chain capture variation**,
not a vendor definitional gap. Not an AAPL quirk: all 18 tickers present in both raw
directories report September 4, zero exceptions. Row 2's exact agreement is read as **shared
upstream exchange data** rather than independent vendor agreement, and is labelled as a
working interpretation, not verified lineage.

**What the vendor measurement now claims, and no more.** Row 1 alone compares two vendors on
a session each captured on its own day: **AAPL, 2026-09-03, 8.93% volume and 3.92% open
interest** — one ticker, one day, with intraday-versus-close capture still confounded with
vendor. It is not evidence of persistent vendor bias or universe-wide comparability. The
earlier, broader reading of the same table is withdrawn in both the research record and
`IV-BACKFILL.md`.

**D14 is unchanged: the splice stays refused**, and the corrected reasoning strengthens it —
a series that is unstable within one vendor cannot absorb a second one. M2 remains
**UNEXECUTED** with its precommitted rule intact; no splice is approved and
`--allow-vendor-splice` remains an escape hatch.

**Reproducibility.** `ops/measure_vendor_gap.py` now saves every fetched payload **by default,
before normalisation**, to `data/raw/marketdata/vendor_gap/<exchange-session>/AAPL-<sha256>.json`;
identical payloads reuse one file and a differing capture never overwrites an earlier one.
Session identity is derived from each CBOE payload's `data.last_trade_time`, never from its
directory date, and a missing timestamp fails before any fetch. The document names the exact
replay command and file per row. **Stated plainly rather than papered over: the two original
MarketData responses were never retained and are still missing**, so the historical table
cannot be replayed from this checkout; the recorded hashes are not substitutes for the files.
That gap is RESULTS item 19's outstanding evidence and is unchanged by this correction.

**Evidence.** Full suite before this session: `PYTHONPATH=src .venv/bin/python -m pytest` →
**698 passed**, zero failures, exit 0 (round-3 entry baseline 671; Lane O handoff 692; the
six additional tests are this correction's, none deleted). After: **698 passed**, zero
failures, exit 0. Focused: `tests/test_vendor_gap.py tests/test_backfill.py` → **26 passed**.
`ops/measure_vendor_gap.py --cboe-only` → exit 0, `capture_count: 3`,
`distinct_exchange_sessions: 2`, group `session_date: 2026-09-04`,
`snap_dates: [2026-09-06, 2026-09-07]`, `metrics_differ: true`,
`interpretation: intra_cboe_capture_variation`. `backfill-iv --dry-run` → `requests_sent: 0`,
`stored: 0`, refusal naming `docs/research/alternatives/vendor-consistency.md`.

**Decided where the prompt left it open.** The falsifiability requirement ("watch it fail")
was recorded only as a claim about a past session, which this checkout cannot replay. It is
now a **re-runnable mutation check** documented in the record: reverting `session_summary`'s
grouping key to `row["snap_date"]` turns `-k groups_cboe` into `1 failed, 1 passed`, exit 1
(`assert 2 == 1`), and back to `2 passed`, exit 0 when reverted — the second parametrised
case passes in both states, so the test discriminates rather than failing on any change. The
mutation was reverted and `ops/measure_vendor_gap.py` verified byte-identical
(`sha256 10a911a559141b7c6635b4d1cc1ae4cc5f0c68bc8083e52bcba82cd0e508273a`).

**Budget: zero live requests, including MarketData.app.** No fetch path ran; the documented
replay commands use `--payload` and the evidence command uses `--cboe-only`. The Alpha
Vantage counter directory is unchanged at 2026-08-30, 09-02, 09-03, 09-04, 09-06 — no
2026-09-09 counter exists. `data/raw/marketdata/` does not exist, confirming nothing was
fetched.

**Scope boundary observed.** Whether the volatility baseline should count calendar snapshot
dates or distinct exchange sessions is cross-referenced to **Prompt B** and left to the owner.
No baseline query, snapshot deduplication, pipeline or grading behaviour was changed.
**Resolution:** — for Lane O: item 19's attribution is corrected and its interpretation is
now narrower than previously recorded. The missing original MarketData payloads remain the
one open evidence item; supplying them requires no new authority, but a fresh probe would.

### [2026-09-09] Prompt B — session-counting decision brief written; PROPOSED, not decided
**Type:** file request
**Affects:** the owner (decision) / Lane K / Lane O / D13 / `src/briefing_app/storage.py`
**Detail:** Decision brief only. **No source file was written** — nothing under `src/`,
`tests/`, `ops/` or `config/` was touched, `option_metric_history` and `pipeline.py` are
unchanged, and `grading.py` stays locked. Files written: **`docs/architecture/decisions/0017-session-counting.md`**
(new, `Status: PROPOSED — awaiting owner decision`) and this append-only register.

**Note on ownership, raised rather than assumed:** `docs/architecture/decisions/` is listed
in `tasks/README.md` as owned by nobody and read-only once work starts. This new record was
created because the Prompt B brief names it as the required deliverable. **No existing
decision record was modified**, and `decisions/README.md`'s index table was deliberately
**not** edited — 0017 is therefore absent from that index until the owner or Lane O adds it.

**The problem, verified offline 2026-09-09.** The baseline counts stored snapshot dates, not
distinct exchange sessions. `storage.py:505` `option_metric_history` selects on `snap_date`
with no trading-day filter and no de-duplication; `pipeline.py:2798` applies the floor as
`len(series)`, a count of **rows**, and that same number is published as `{"sessions": N}`
and rendered "Provisional — N stored sessions". **The published label already counts the
wrong thing.** `is_market_day` (`pipeline.py:511`) is called only at `pipeline.py:628` to
decide whether to run, is bypassed by `--force`, and never touches history.

**Measured state of the store:** three snapshot dates, **two distinct exchange sessions**.
2026-09-03 → 21 tickers session 09-03 and 2 tickers (FDX, LMT) session 09-02; 2026-09-06
(Sunday) and 2026-09-07 (Labor Day) → all 18 tickers session **09-04**, counted twice. Per
reading: 15 of 18 tickers go `iv_atm` 3→2 and all 18 go `pc_ratio_vol`/`pc_ratio_oi` 3→2 once
sessions are counted. FDX has **0** stored implied-volatility observations, JPM 1, LMT 1.

**Three findings the brief adds beyond the prompt's premise, all offline-verified:**

1. **The stale chain recurs and is per-ticker.** FDX carried a stale chain on 2026-09-03
   (session 09-02) *and again* on 2026-09-04 (session 09-03). It is a property of the delayed
   feed, not a one-off, so no calendar rule can catch it.
2. **`is_market_day` has no holiday list.** Its `holidays` parameter is never supplied by any
   caller and no holiday calendar exists in `src/`, `config/` or `ops/`. `is_market_day(2026-09-07)`
   returns `True` — Labor Day passed the guard as a normal market day. A weekday-only run
   policy therefore cannot be enforced by the code that exists.
3. **Session identity is stored nowhere in the database.** `daily_snapshot` has no session
   column; its `raw` holds only `components`/`scoring` with the run date as `as_of`; and
   `evidence_ledger.as_of` is the **capture timestamp, not the session** (FDX run 1 records
   `2026-09-03 10:02:55` for a 09-02 chain). Root cause is one line — `normalizers.py:207`
   prefers `payload["timestamp"]` over `data["last_trade_time"]`, so the session is discarded
   at normalization. It survives only in `data/raw/cboe/`, which is present for all three
   stored dates, so the existing rows are repairable offline at zero cost.

**Options A–E were developed as instructed; F was added.** Two are recommended for
**rejection on evidence**: **D (calendar filter) is strictly worse than B** — as shipped it
destroys LMT's only implied-volatility observation (a valid Sunday capture of Friday's
session, 1→0) while still missing the stale chains, and with a real holiday calendar it drops
every ticker to 1 observation by discarding the 09-04 session entirely. **E (compensating
floor)** treats a correctness defect as a sample size: at the observed duplication rate of
**3 of 8 runs on non-trading days (37.5%)** it needs a floor near 16, which publishes
2026-09-28 — later than fixing it — and still ranks over duplicated points.

**Recommendation: option B2** — persist each chain's `last_trade_time` on the row, repair the
three stored rows offline from the raw files, de-duplicate history by (ticker, session) on
read. Keeps all three rows; destroys no data. **Cost stated with it:** first publication moves
**Fri 2026-09-18 → Mon 2026-09-21** (one run, three calendar days), and it requires writing
`src/briefing_app/storage.py`, **which no lane owns this round** — ownership must be assigned
before anyone implements it. It also touches `pipeline.py`/`normalizers.py` (Lane K).

**Owner steer recorded in-session 2026-09-09** (asked before the brief was written): *"Fix
first, publish 21 Sep"* and *"Trading days only from now on."* The record states plainly that
the second answer **reduces but does not remove** the problem — the duplicate rows already
exist inside the first ten-observation window, the stale-chain case is unaffected, and the
cadence cannot be enforced by `is_market_day`. Status therefore remains **PROPOSED**: the
steer settles the trade-off, not the design.

**The one open question the brief ends on:** when two rows describe the same session, does
the earliest capture count, the latest, or neither while they disagree? It cannot be settled
from evidence — the two 09-04 AAPL reads differ by 146% on put/call open interest, and for
LMT "keep the latest" would discard its only implied-volatility observation.

**Ship impact:** blocks **definition-of-done item 21 only**; items 1–20 are untouched. It can
ship open. `iv_rank` is NULL on every stored row and no percentile has ever been published,
so nothing currently in the product is wrong; the exposure begins on the first run that
clears the floor — **2026-09-21** on the owner's answer, which is the real deadline.

**Budget: zero live requests.** Every number came from `data/briefing.sqlite3`,
`data/raw/cboe/` and the source tree. The Alpha Vantage counter directory is unchanged
(2026-08-30, 09-02, 09-03, 09-04, 09-06; no 2026-09-09 counter). Suite unchanged at
**698 passed, zero failures** — no test or source file was modified by this task.
**Resolution:** — awaiting the owner's answer to the tie-break question, and an ownership
assignment for `src/briefing_app/storage.py` before any implementation begins.

### [2026-09-09] Prompt B — precision correction to 0017's headline count
**Type:** completion
**Affects:** `docs/architecture/decisions/0017-session-counting.md`
**Detail:** Self-correction made before handing the brief over, recorded rather than edited
silently. The record first read "Three snapshot dates, two distinct exchange sessions." That
is right per ticker and wrong as a universe statement: across all 18 report tickers **three**
sessions appear (2026-09-02, 09-03, 09-04), because FDX and LMT contribute 09-02 from their
stale 2026-09-03 chains. **No single ticker has more than two**, and the baseline is computed
per ticker, so the conclusion is unchanged — but the sentence could have been read as a
universe-wide claim that the evidence does not support. Corrected in place to state both
figures. Verified: 18 tickers x 3 snapshot dates = 54 chain reads, 3 distinct sessions
universe-wide, 2 per ticker for every one of the 18.
**Resolution:** settled within this task; no other section of the record depended on the
looser wording.

### [2026-09-09] Prompt B / 0017 — owner answered the tie-break; decision now Accepted
**Type:** completion
**Affects:** the owner / Lane K / Lane O / D13 / `src/briefing_app/storage.py` (unowned)
**Detail:** The closing question in `docs/architecture/decisions/0017-session-counting.md` was
answered by the owner: **"keep the latest."** With the two earlier answers ("fix first,
publish 21 Sep" and "trading days only from now on") all three open questions are closed, so
0017 moves from **PROPOSED** to **Accepted, 2026-09-09**. Files written: 0017 and this
register. **Still no source file touched** — nothing under `src/`, `tests/`, `ops/` or
`config/`; `storage.py`, `pipeline.py` and the locked `grading.py` are unmodified.

**The decision as recorded.** The volatility baseline counts **distinct exchange sessions**,
not stored snapshot dates. Option **B2**: persist each chain's `data.last_trade_time` on the
stored row, repair the three existing rows offline from `data/raw/cboe/` (present), and
de-duplicate history by `(ticker, session)` on read. All three stored rows are kept; nothing
is deleted. Accepted cost: first provisional reading moves **Fri 2026-09-18 → Mon 2026-09-21**.

**One judgement call was resolved inside the owner's answer, and it is flagged rather than
buried.** "Keep the latest" has two readings that diverge at exactly one value in the whole
store. Row-wise (take the later row whole) discards **LMT's only implied-volatility
observation, 0.1977 on the 09-06 row**, because LMT's 09-07 row has `iv_atm` NULL — LMT would
go 1 → 0 and its first IV rank would slip 09-22 → 09-23. Per-reading (take the latest capture
that carries a value, for each reading independently) keeps it. **Resolved as per-reading**,
because both readings agree wherever two captures actually compete and differ only where one
capture has a value and the other has nothing; a NULL is the absence of a measurement, not a
newer competing one. Verified that LMT is the **sole** ticker where the two interpretations
diverge. Reversible in one line if the owner meant row-wise.

**A finding this surfaced, worse than the case already on file.** LMT's two captures of
session 2026-09-04 disagree far more violently than AAPL's: put/call volume 1.8521 versus
0.0196 (~95x) and put/call open interest **10.5 versus 0.0215, a factor of 487**. The AAPL
figure recorded in `docs/research/alternatives/vendor-consistency.md` is 146% on the same
session. This strengthens both 0017 and **D14's refusal** — a series this unstable within one
vendor's repeated reads of a single session cannot absorb a second vendor. **Neither D14 nor
the vendor-consistency record was edited**; this is an addition to 0017 only, and the LMT
figure is new evidence a later reader of D14 may want.

**Implementation note carried by 0017:** because the winning capture can disagree with the
discarded one by two orders of magnitude, de-duplication must not be silent — the run should
record that a duplicate existed and which capture won, per D9's principle.

**State under the decision**, per ticker after de-duplication: `iv_atm` 2 observations for 15
of 18 tickers, 1 for JPM, 1 for LMT, 0 for FDX; `pc_ratio_vol` and `pc_ratio_oi` 2 for all 18.
First publication, weekday runs from 2026-09-09: **Mon 2026-09-21** for all put/call readings
and 15 tickers' IV rank; **Tue 2026-09-22** for JPM and LMT; **Wed 2026-09-23 at the earliest**
for FDX, which may never publish one.

**Still open, and owned by nobody:**
1. **`src/briefing_app/storage.py` has no owner this round** and B2 cannot be implemented
   without writing it (plus `pipeline.py`/`normalizers.py`, Lane K). Assign ownership before
   any implementation starts.
2. **0017 is absent from `docs/architecture/decisions/README.md`'s index table.** That file is
   owned by nobody and was deliberately not edited.
3. **The weekday-only cadence cannot be enforced by the code that exists** — `is_market_day`
   has no holiday list, so it returned `True` for Labor Day. Enforcing the owner's policy
   rather than relying on memory is separate, small, unscheduled work.
4. **Why the repeated captures disagree is undiagnosed.** The decision does not depend on it,
   but it means the winning capture is the *later* one, not the demonstrably correct one.

**Budget: zero live requests.** Alpha Vantage counter directory unchanged (2026-08-30, 09-02,
09-03, 09-04, 09-06; no 2026-09-09 counter). Full suite before and after this task:
**698 passed, zero failures**, exit 0.
**Resolution:** 0017 Accepted. Implementation blocked only on the `storage.py` ownership
assignment; no code change is authorized by this entry.

### [2026-09-09] Owner — 0017's attribution confirmed; ship audit finding closed
**Type:** completion
**Affects:** `docs/architecture/decisions/0017-session-counting.md`, and any future audit
**Detail:** The 2026-09-09 ship audit flagged 0017's recorded owner steer, and its later
promotion from `PROPOSED` to `Accepted`, as **unverifiable from any artifact** — the answers
were given in a session whose trace does not exist in this repository, and they are
load-bearing: they set the de-duplication design, the weekday-only cadence, and the
21 September deadline. The audit did not allege fabrication; it recorded that nothing in the
tree corroborated the claim.

**The owner has now confirmed the attribution directly, on 2026-09-09.** 0017 stands as
**Accepted**. The finding is closed and should not be re-raised.

Two repairs made at the same time, both additive and touching no source:
- 0017 was **absent from `docs/architecture/decisions/README.md`** — an accepted decision
  invisible from the index whose purpose is to make decisions findable. It is now listed,
  and the rounds section records what opened the follow-up.
- This entry, so the confirmation exists in the repository rather than only in a chat
  transcript.

**The general lesson, worth more than this instance.** This is the third time in one day
that an owner answer given in one session has been invisible from another. An agent that
asks the owner a question and acts on the answer **must record the answer in this register**,
not only in the document it was asked for — otherwise the next reader cannot tell a decision
from an assumption, and the only way to resolve it is to interrupt the owner again.
**Resolution:** settled — attribution confirmed by the owner.

### [2026-09-09] Lane P — 0017 implemented; one acceptance number contradicts the chosen tie-break
**Type:** completion
**Affects:** the owner / `docs/architecture/decisions/0017-session-counting.md`
**Detail:** 0017 option B2 is implemented. Suite **706 passed, zero failures**, exit 0, up
from 698; no test deleted. `dashboard/grading.py` verified byte-identical to `545e9e3`.

- `daily_snapshot.chain_session_date` added (`migrations/004_session_identity.sql`), written
  by **both** write paths from the chain's own `last_trade_time`. Never inferred: a caller
  that cannot establish the session stores NULL.
- `option_metric_history` returns one observation per (ticker, session); the later capture
  wins and the drop is reported to the caller, which raises it as a per-ticker issue.
  Classified **`normal`** — expected after every weekend, so escalating it would make
  `partial` constant.
- `ops/repair_snapshot_sessions.py` repaired all **59** stored rows from raw payloads on
  disk, **0 unresolved, nothing deleted**, reproducing 0017's table exactly: 09-03 → 21
  tickers session 09-03 and 2 (FDX, LMT) session 09-02; 09-06 and 09-07 → all 18 session
  09-04. Backup at `data/briefing.sqlite3.backup-before-0017-repair`.
- The published *"N stored sessions"* label needed no dashboard change: it is `len(series)`,
  and the series is now de-duplicated, so it self-corrected. No Lane-owned dashboard file
  was touched.

> **One acceptance number does not hold, and it is a decision rather than a defect.**
> 0017's table projects `iv_atm` **1** for LMT. The implementation produces **0**.
>
> LMT's session 2026-09-04 has two captures: 09-06 carries `iv_atm=0.1977`, 09-07 carries
> `iv_atm=None`. "Later capture wins" keeps the 09-07 row, so the reading is discarded.
> **0017 predicted exactly this** in its closing question — *"for LMT 'keep the latest'
> silently discards its only implied-volatility observation"* — and its counts were written
> before the tie-break was settled. The table and the rule disagree; the rule was
> implemented, per the owner's answer.
>
> The alternative, de-duplicating **per series** rather than per row, keeps the reading but
> splices one observation out of two captures that disagree by **95x** on the same ticker
> and session (`pc_ratio_vol` 1.8521 versus 0.0196). That is the kind of invisible splice
> D14 refuses across vendors, here inside one.
>
> **Nothing was adjusted to fit.** The code implements the stated rule; this entry records
> the conflict for the owner to settle. Affected scope is one ticker's implied-volatility
> leg.

**One file written outside the Owns list**, recorded rather than glossed:
`docs/architecture/RUN-HEALTH.md`. Its severity table is keyed by `pipeline.py` line numbers
and is pinned by a test, so adding a recording point forces the document to be renumbered in
the same change. No other lane is active in round 4, so there was no contention.
`providers/normalizers.py` was listed in the Owns block and **needed no change**, as the lane
document predicted.
**Resolution:** — awaiting the owner on the LMT tie-break only. Everything else is settled.

### [2026-09-09] Owner — LMT tie-break settled row-level; Lane P closed
**Type:** completion
**Affects:** Lane P, 0017, `docs/architecture/VOLATILITY-BASELINE.md`
**Detail:** Resolves the one item the Lane P completion entry above left open. The owner
chose **row-level** de-duplication: when two captures describe one exchange session, the
later capture supersedes the earlier one **whole**, rather than each series independently
taking the latest capture that happens to carry a value.

**No code changed** — row-level is what was implemented, so the choice confirms the shipped
behaviour rather than altering it. What changed is three documents that carried a projection
the tie-break invalidates.

**The measured effect, and it is one ticker.** 0017 projected `iv_atm` **1** for LMT; the
answer makes it **0**. LMT's only implied-volatility reading, `0.1977`, sits on the 09-06
capture of the 2026-09-04 session and is superseded by the 09-07 capture, which carries
none. Corrected counts, measured from the repaired store:

| Series | Held per ticker |
|---|---|
| `iv_atm` | **2** for 15 of 18; **1** JPM; **0** FDX; **0** LMT |
| `pc_ratio_vol`, `pc_ratio_oi` | **2** for all 18 |

First `iv_rank` publication moves for LMT alone, Tuesday 2026-09-22 → Wednesday 2026-09-23
at the earliest. The all-18 put/call projection of Monday 2026-09-21 is unchanged.

**The reason the alternative was declined, recorded so it is not re-proposed.** Per-series
de-duplication would have kept LMT's reading by pairing it with `pc_ratio_vol` from the other
capture — two readings of one session differing by **95x**, 1.8521 against 0.0196. Keeping a
number by splicing two disagreeing captures into a single observation is the failure D14
refuses between vendors; it is no better inside one.

**Documents corrected**, none silently: a dated correction section appended to
[0017](../docs/architecture/decisions/0017-session-counting.md) rather than editing an
accepted record's table in place; the projection table in `VOLATILITY-BASELINE.md` replaced
with measured counts; and the Lane P acceptance table corrected with a note saying what it
previously read and why.

**FDX and LMT now both hold zero implied-volatility observations, for different reasons** —
FDX has never produced one in any stored row, LMT produced one that is superseded. A reader
should not treat either missing rank as a defect.
**Resolution:** settled. **Lane P is complete**; nothing in round 4 remains open.
