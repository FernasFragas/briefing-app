# IV Backfill

The self-built volatility baselines use `daily_snapshot.iv_atm`, `pc_ratio_vol`, and
`pc_ratio_oi`. Live runs need 20 stored sessions before IV rank and put/call percentiles
open. The backfill command replays Alpha Vantage historical option chains into the same
storage shape so the baseline can warm up without waiting four trading weeks.

## Run It

Dry-run the plan first:

```bash
PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv --dry-run
```

Backfill the gate-accepted US names for the run date:

```bash
PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv
```

Limit scope while testing:

```bash
PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv \
  --ticker NVDA --ticker MSFT --sessions 5
```

The command is resumable. It skips any `(ticker, date)` pair whose option metrics are
already stored, reports remaining pairs, and exits cleanly when the provider budget is
spent.

Two guards stand between a dry run and a writing one, and both refuse rather than warn:

```bash
--allow-vendor-splice     # the chains come from a different vendor than the live path's
--live-run-reserve N      # requests to hold back for the daily run (default: all of them)
```

`--dry-run` reports both without sending anything. A run that cannot proceed exits with
status `blocked` and names the reason. See **Budget Reservation** and **Comparability**
below for what each is protecting.

## Request Cost

The plan as the tool reports it, `backfill-iv --dry-run` on 2026-09-08:

```text
requested_pairs:              320     (16 tickers x 20 sessions)
already_stored:                27
remaining:                    293
estimated_days_at_allowance:   12     (Alpha Vantage free tier, 25 requests/day)
budget_remaining_today:        25
spendable:                      0     (reserved for the daily run - see below)
```

That 12-day figure is arithmetic, not a forecast, and **on the current free key it is
academic**: `HISTORICAL_OPTIONS` is not on the Alpha Vantage free tier. It answers HTTP
200 with a plausible sample payload, which validation reports as `synthetic`
(`docs/research/SOURCE_STATUS.md` — "Alpha Vantage premium endpoints answer HTTP 200 with an
artificial sample schema"). Waiting out the allowance therefore does not eventually
produce the backfill; it produces 25 refusals a day, indefinitely. **D12 is not a choice
between paying and waiting — waiting yields nothing.** It is: pay for the endpoint, find
another source, or drop the backfill.

Sample data cannot reach the store: `fetch_function` validates before it returns and
raises on `synthetic`, so nothing is written. The requests are still spent, which is why
the run now stops on the first `synthetic` answer, and after three consecutive failures of
any kind — `providers/base.py` parks a repeating refusal only for `malformed`, so nothing
else would have stopped it.

## Budget Reservation

The daily run and the backfill draw on **one** Alpha Vantage allowance. Whatever the
backfill spends first, the live run cannot spend later — and a live run that reaches no
provider is a worse outcome than a baseline that warms up slowly.

**Policy: the live run is paid first. The backfill spends only what is left after it.**

| Situation | Held back | Backfill may spend |
|---|---|---|
| Plan has no daily ceiling (`ALPHA_VANTAGE_PLAN=paid`) | nothing | everything |
| `--cache-only` replay | nothing | it sends no requests at all |
| Today's live run has **not** finished | the full allowance, 25 | nothing |
| Today's live run **has** finished | 6 | whatever remains, less 6 |

Both numbers are measured, not chosen for roundness. The live run's own counters in
`data/provider_budget/alpha_vantage/` record what it actually spent per day:

```text
2026-08-30:  6
2026-09-02: 25   <- ceiling
2026-09-03: 25   <- ceiling
2026-09-04:  4
2026-09-06:  2
```

It reached the ceiling on two of the five days recorded, and nothing tells you in advance
which kind of day today is. Reserving less than the observed peak is a guess whose cost,
when wrong, is exactly the provider-less run this reservation exists to prevent — so
before the live run has finished, the backfill's share is **zero**. Once the run has
finished, its requests are already spent and what remains is genuinely spare; 6 stays back
because 6 is the largest spend by a run that did *not* hit the ceiling, so a re-run still
reaches its providers.

"Has finished" means a `briefing_run` row for the run date whose `run_type` is not
`iv_backfill`, whose status is `succeeded` or `partial`, and which has a `finished_at`.

Override with `--live-run-reserve N`, or with `BACKFILL_LIVE_RUN_RESERVE` and
`BACKFILL_COMPLETED_RUN_RESERVE`. The reservation is reported in every result and every
dry run under `reservation`, so the plan states its own constraint instead of hiding it.

A backfill with nothing spendable exits `blocked` without sending a request. On the free
plan that is the intended outcome, not a failure to work around.

Tests: `test_reservation_holds_the_whole_allowance_before_the_live_run_has_finished`,
`test_backfill_sends_nothing_while_the_allowance_is_reserved`,
`test_backfill_spends_only_what_is_spare_once_the_live_run_has_finished`,
`test_an_unmetered_plan_reserves_nothing`, `test_cache_only_replay_reserves_nothing`,
`test_repeated_failures_stop_the_run_before_they_spend_the_allowance`.

## Comparability — the J1 audit

A backfilled reading is comparable to a live one only if both are computed by the same
code path, from the same kind of input. Round 1 claimed the first half. This is the audit
of that claim, and what it now rests on.

### What the round-1 test actually proved

`tests/test_backfill.py::test_backfilled_metrics_reproduce_stored_live_metrics_to_full_precision`
builds both sides with `backfill.snapshot_row_from_structure` and feeds both the same
payload. It is a real test — it pins the normalizer and `build_options_structure` — but
what it proves is that **the backfill agrees with itself**. Two things it cannot see:

1. The live pipeline does not use that function. It stores rows through
   `scoring.to_daily_snapshot_row` (`pipeline.py:647`). Those are two copies of one field
   mapping, in two files. Either could drift and no test would notice.
2. The live pipeline's `build_options_structure` call passes four arguments the backfill
   never passes — `price_bars`, `expression_class`, `event_multiplier`, and the stored
   histories. "Same function" is not "same call".

So the round-1 test was necessary and not sufficient. The gap is closed rather than
argued away.

### What is proved now

| Claim | Test |
|---|---|
| A row the **live path stored** is reproduced by a real `run_iv_backfill`, exactly | `test_backfill_reproduces_a_row_the_live_path_stored` |
| The live and backfill row builders agree field for field | `test_live_and_backfill_row_builders_agree_field_for_field` |
| The backfill agrees with itself across normalization | `test_backfilled_metrics_reproduce_stored_live_metrics_to_full_precision` |

The first builds the live side the way `pipeline.py` builds it — live row builder, live
argument set, live histories, `event_multiplier` 1.35, real price bars — stores it through
`StorageRepository`, then runs the backfill end to end into a second store and compares
the two **stored** rows. `spot`, `iv_atm`, `pc_ratio_vol`, `pc_ratio_oi`,
`expected_move_1w`, `expected_move_1m` and `rr_25d` match exactly. None of the live-only
arguments moves a stored chain metric: they feed the measured sigma range and the score.

**Verdict: for the three series the self-built baseline is a percentile of, the code path
is the same and the numbers reproduce.** The path is unchanged:

```text
normalize_alpha_vantage_options_chain
build_options_structure
snapshot_row_from_structure
StorageRepository.upsert_daily_snapshot
```

### Two things that do not reproduce, both deliberate

**`realized_vol_20d` is NULL on backfilled rows.** It needs price bars and a historical
option chain carries none. It is not one of the three baseline series, so nothing that
gates a setup depends on it — but the reproduction test asserts the NULL so no one later
reads it as a bug.

**The vendor differs, and this is the finding that matters most.** Every stored `iv_atm`,
`pc_ratio_vol` and `pc_ratio_oi` in this project was computed from a **CBOE** delayed
chain: `config.providers.options` is `[cboe, alpha_vantage]`, and the evidence ledger
records `CBOE delayed options` for all 1,235 `S_O` rows. The backfill reads **Alpha
Vantage** historical chains. The functions are the same; the quotes are not, and neither
is the time of day — the CBOE captures are intraday (2026-09-03 17:14:21 UTC), while an
Alpha Vantage historical chain is the session's close.

An IV rank is a percentile of *one* series. A series whose old points are one vendor's
intraday chain and whose new points are another's close is not one series, and D3's whole
warning is that this failure is invisible in the output.

So the backfill now **refuses to write** when its provider differs from
`config.providers.options[0]`, and says why. `--allow-vendor-splice` overrides it, for
whoever has accepted the consequence. Every backfilled row also carries its own
provenance — `raw.backfill.chain_source`, `chain_venue`, `chain_as_of`,
`live_options_provider` — so a mixed series can be separated after the fact. A live row
records its chain source only in `evidence_ledger`.

This is an input to D12, not a conclusion about it: the cheapest resolution may be a
historical **CBOE** chain rather than a different vendor at any price.

## Fixture Contamination Purge

The local database contained one fixture run in the live history table:

```text
snap_date    run_id  rows  data_mode
2026-09-04   2       21    fixture
```

Those rows are synthetic and must not feed the self-built percentile baseline. Before
purging local data, take a copy:

```bash
cp data/briefing.sqlite3 "data/briefing.sqlite3.backup-$(date +%Y%m%d-%H%M%S)"
```

Then delete the contaminated rows:

```bash
sqlite3 data/briefing.sqlite3 \
  "delete from daily_snapshot where run_id = 2;"
```

Verify:

```bash
sqlite3 data/briefing.sqlite3 \
  "select count(*) from daily_snapshot where run_id = 2;"
```

The expected result is `0`.

The code now refuses any `daily_snapshot` write whose parent `briefing_run.details.data_mode`
is not `live`. Fixture attempts are reported as diagnostics instead of silently entering
the history store.

## Execution — J3, not yet run

> **Placeholder. Nothing below is measured yet.** D12 is open: the owner has not chosen
> between paying for Alpha Vantage premium, a free alternative from Lane I's research, or
> a reduced ticker set. No real backfill request has ever been sent, and
> `select count(*) from daily_snapshot where iv_rank is not null` still returns 0.

Fill in once J3 runs:

- **D12 outcome, and the source actually used** —
- **Was the vendor splice accepted, or avoided by choosing a CBOE-consistent source?** —
- **Real cost in requests** — against the 293 remaining pairs estimated
- **Real elapsed time** — against the 12-day estimate
- **Did a name reach 20 stored sessions and open its baseline?** —
- **Did a live run afterwards produce a setup previously rejected `iv_rank_unavailable`?**
  — the only line that proves the work delivered anything.

Before any writing run:

```bash
cp data/briefing.sqlite3 "data/briefing.sqlite3.backup-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv --dry-run
```
