# Volatility baseline — publication threshold and confidence marker

**Implements D13.** The IV and put/call percentile signals are calculated from this
application's own stored CBOE option snapshots. No purchased history and no cross-vendor
splice is involved.

## One rule, three readings

The same self-built-history rule gates these three percentile readings:

- `iv_rank` — the current at-the-money implied volatility against its stored history;
- `put_call_volume_percentile` — the current put/call volume ratio against its stored
  history; and
- `put_call_open_interest_percentile` — the current put/call open-interest ratio against
  its stored history.

Each source snapshot can supply all three raw inputs, but a missing input is counted only
for its own reading. The published metadata is therefore per reading, not a single ticker
wide claim about the options component.

## Thresholds and what provisional means

`pipeline.self_built_series_min_sessions` is the publication floor: **10** stored sessions.
Below it the percentile is withheld, with the normal run-health notice `baseline below
publish floor: N of 10 sessions stored`.

`pipeline.self_built_series_full_sessions` is the settled threshold: **20** stored
sessions. At 10 through 19 sessions a percentile is calculated and published as
**provisional**; at 20 or more it is published as settled.

A percentile over *n* observations can distinguish increments no finer than `1/n`. At ten
sessions, its finest distinction is a decile: an IV rank of 80 means eight of the ten prior
observations are at or below the current reading, not a finer precision estimate. Ten sessions are
roughly two calendar weeks and may not span even one volatility regime. The marker is the
means by which the report states that limitation rather than hiding it.

## Why ten, not twenty

D13 was made with three stored sessions. Requiring twenty would leave seventeen weekday
runs to accumulate twenty observations; publishing at ten leaves seven to accumulate ten.
History excludes today's snapshot, so the first percentile is available on the following
run, provided that ticker has ten non-null prior inputs. The owner accepted the smaller
sample to restore the three options legs earlier, while requiring that every 10–19-session
result show its limitation.

## Sessions, not stored rows (0017)

**A "session" here is an exchange session, not a run date, and the two are not the same.**
`snap_date` records the day the briefing ran; the reading it stores belongs to whatever
session the option chain actually describes.

Three ways they diverge, all observed in this store:

- A **weekend** run serves the previous session's chain. 2026-09-06 was a Sunday.
- A **holiday** run does the same. 2026-09-07 was Labor Day, and `is_market_day` let it
  through because its `holidays` parameter is never supplied and no holiday calendar
  exists in the repository.
- A **stale per-ticker chain on an ordinary trading day.** On 2026-09-03, a normal
  Thursday, FDX and LMT carried chains whose last trade was 2026-09-02. This is why a
  calendar filter cannot fix the problem and the rule keys on each chain's own
  `last_trade_time`.

Every row therefore carries `chain_session_date`, written from the chain's
`last_trade_time` at write time by both the live path and the backfill. It is **never**
inferred from the run date: a caller that cannot establish the session stores `NULL`, and
rows with an unknown session are each counted separately, because absence is not evidence
that two rows describe the same day.

`option_metric_history` returns **at most one observation per (ticker, session)**.

### The tie-break is a tie-break, not a correctness argument

When two rows share a session, **the later capture wins.** The owner settled this on
2026-09-09.

**It is not a claim that the later reading is right.** Why repeated captures of one session
disagree is undiagnosed, and they can disagree enormously: the two stored reads of the
2026-09-04 session differ by **146%** on AAPL's put/call open interest
(`docs/research/alternatives/vendor-consistency.md`). Both rows are kept, so the discarded
reading stays auditable, and every run records that a duplicate existed and which capture
won. The condition is classified `normal` — expected after every weekend, so escalating it
would make `partial` constant, which is the failure D9 warns about.

### What this costs, and when the first reading lands

De-duplication removes observations that were being counted, so first publication moves out
by one run. Projected, and it is a projection:

Measured after the repair, under the row-level rule:

| Reading | Observations held | First publication |
|---|---|---|
| Both put/call percentiles, all 18 tickers | 2 | run 9 — **Mon 2026-09-21** |
| `iv_rank`, 15 of 18 tickers | 2 | run 9 — **Mon 2026-09-21** |
| `iv_rank`, JPM | 1 | run 10 — Tue 2026-09-22 |
| `iv_rank`, FDX and LMT | 0 | run 11 — Wed 2026-09-23 at the earliest |

**FDX and LMT hold zero implied-volatility observations, for different reasons.** FDX has
never produced one in any stored row. LMT produced one — `iv_atm = 0.1977` on the 2026-09-06
capture of the 09-04 session — and it is superseded by the 09-07 capture of that same
session, which carries none. That is the row-level tie-break working as chosen, not a bug:
an observation is one capture's readings taken together, so a later capture replaces an
earlier one whole rather than being merged with it field by field.

The alternative was considered and declined. Merging per field would have kept LMT's reading
by combining it with `pc_ratio_vol` from the other capture — two readings of one session that
differ by **95x** (1.8521 against 0.0196). Keeping a number by splicing two disagreeing
captures into one observation is the failure D14 refuses between vendors; it is no better
inside one.

Read a missing rank for these two names as that, not as a defect.

Every date above assumes a run on every weekday. A missed day moves them all by one.

## Where the fact travels

For every published reading, the record is `{ "sessions": N, "provisional": bool }`.
It is keyed by `iv_rank`, `put_call_volume_percentile`, or
`put_call_open_interest_percentile` in:

- `daily_snapshot.raw["volatility_baselines"]` — the stored row;
- `TradingIdeaRow.volatility_baselines` — and therefore `dashboard.json`; and
- the rendered trading-ideas page, where a provisional result carries its session count.

Withheld readings and readings with a missing current input have no invented metadata
entry: no calculation happened, so there is no sample count to represent as a published
percentile. The page displays `Provisional — N stored sessions`, using the producer's
flag so a configured settled threshold cannot conflict with a hardcoded denominator.

`test_self_built_percentile_boundaries_cover_all_three_gated_legs` pins the 9 / 10 / 20
boundaries and the per-leg metadata.
`test_provisional_baselines_persist_to_live_snapshot_and_dashboard_json` pins both the
stored row and `dashboard.json`; `test_dashboard_html_renders_provisional_baseline_and_crowding_magnitude`
pins the rendered-page marker and its session count.

## Source quality decision

Provisional self-built percentiles retain the `S_O` source quality of their verified CBOE
snapshots. Source quality measures **provenance**; the provisional flag measures **sample
size**. Downgrading the quality would overload a provenance badge with a statistical
confidence claim, silently alter tier distribution in the same release, and make a fully
verified CBOE capture look less authentic than it is. The explicit marker is the honest
sample-size disclosure. The flag itself changes no grade or confidence tier; making a
previously unavailable percentile computable can change an options score. The grading
formula remains unchanged.
