# Lane M — Vendor consistency: measure the gap before permitting a splice

**Implements:** D14. **Closes:** definition-of-done item 19.
**Depends on:** the round-3 baseline commit (gate). Runs in parallel with K, L, N.
**Live request allowance:** **0 Alpha Vantage requests.** MarketData.app keyless probes are
permitted and are not budget-tracked. See D16, and read the budget rule below before your
first request.

## Owns — write only these

```
src/briefing_app/backfill.py
src/briefing_app/cli.py
tests/test_backfill.py
tests/test_vendor_gap.py                        (new)
ops/measure_vendor_gap.py                       (new)
docs/operations/IV-BACKFILL.md
docs/research/alternatives/vendor-consistency.md         (new)
```

## Must not touch

- `src/briefing_app/pipeline.py`, `config.py` — Lane K. Read
  `SELF_BUILT_SERIES_MIN_SESSIONS` from it as you do today; **do not change it**, and note
  that Lane K is making it configurable — your import must keep working, and if it does not,
  that is a `CROSS-LANE.md` entry, not an edit.
- `src/briefing_app/dashboard/**` — Lane L.
- `ops/status.py`, `ops/live_budget.py`, `tests/test_ops_scripts.py` — Lane N. Your script
  is `ops/measure_vendor_gap.py` and its tests live in `tests/test_vendor_gap.py`.
- `src/briefing_app/storage.py` — nobody owns it this round. Read it; do not write it.

---

## Where this actually stands, and why this lane is not obviously possible

Round 2 established the problem. `config.providers.options` is `[cboe, alpha_vantage]`, and
**every stored `iv_atm`, `pc_ratio_vol` and `pc_ratio_oi` in this project came from CBOE**,
captured intraday — the evidence ledger records `CBOE delayed options` for all 1,235 `S_O`
rows, and the 2026-09-03 capture is stamped 17:14:21 UTC. An Alpha Vantage historical chain
is the **session close**.

A percentile is a ranking *within one series*. Splice two vendors' readings into it and you
get a confident answer to a comparison nobody made, and it looks exactly like a correct one.
Lane J built the guard that refuses this; D14 keeps it.

> ### The tension in this lane, stated up front so you do not waste a day discovering it
>
> The owner chose **"measure the difference first, then decide"** — and, separately, chose
> **not to pay** for Alpha Vantage premium (D13).
>
> **The implied-volatility half of the measurement needs a paid key.** Alpha Vantage
> `HISTORICAL_OPTIONS` is not on the free tier: it answers HTTP 200 with a sample payload
> that this project's own validation classifies as `synthetic` (`docs/research/SOURCE_STATUS.md`, and
> the Lane J entry in `CROSS-LANE.md`). Requests against it are **spent and wasted**.
>
> **This does not make the lane empty, and it is not a reason to stop.** Two things are
> executable today and they are the lane:
>
> - **The put/call half can be measured for free, now** (M1). That is two of the three
>   gated legs, on real data, at zero cost.
> - **The implied-volatility half is written up and left unexecuted** (M2), precise enough
>   that whoever holds a paid key runs it in ten minutes.
>
> If you find yourself about to send an Alpha Vantage `HISTORICAL_OPTIONS` request to "just
> check", stop. That is the one thing this lane is forbidden to do.

---

## Tasks

- [ ] **M1 — Measure the cross-vendor gap on put/call ratios, for free**

  Lane I verified that MarketData.app serves genuine past-dated option chains **keyless**,
  with real `volume` and `openInterest` — 1,336 contracts across 10 expirations for AAPL,
  including a true weekly and a monthly, HTTP 203 with `"s":"ok"`:

  ```
  GET https://api.marketdata.app/v1/options/chain/AAPL/?date=2026-08-10
  GET https://api.marketdata.app/v1/options/chain/AAPL/?date=<d>&from=<d1>&to=<d2>
  ```

  Two limits Lane I established, both of which shape this task:
  - **`iv` is null on every past-date row**, along with all greeks. Proved to be a property
    of the endpoint rather than a recency cutoff: the same endpoint, same session, same 122
    contracts returns `iv` on 122 of 122 **without** `date=` and 0 of 122 **with** it. So
    this source cannot measure the implied-volatility gap. It can measure the other two.
  - **AAPL is the only keyless symbol.** SPY, QQQ and CRWV return 401. Plan the measurement
    around that; a one-symbol comparison is a real measurement, and saying so honestly is
    better than a broader one you cannot make.

  **The measurement.** For each date where CBOE-derived rows already exist —
  `2026-09-03`, `2026-09-06`, `2026-09-07` — compute `pc_ratio_vol` and `pc_ratio_oi` from
  the MarketData.app past-date chain and compare against the values stored in
  `daily_snapshot`.

  **The single most important constraint, and the whole reason this is a measurement rather
  than an anecdote:** compute the MarketData.app side through **exactly the same functions**
  the live path uses — the normaliser plus `options_math.py` — given a normalised chain. Not
  an equivalent calculation. If you write your own ratio arithmetic you will be measuring
  your arithmetic against the live path's, not one vendor against another, and the number
  will be worthless in a way that is invisible. This is the same trap D3 named and Lane J's
  `test_backfill_reproduces_a_row_the_live_path_stored` exists to catch; read that test
  before writing this one.

  Report, in `docs/research/alternatives/vendor-consistency.md`: per ticker and date, both vendors'
  values, the absolute and relative gap, and the exact requests that produced them.

  **Acceptance:** a real number for the gap on at least one ticker across at least two
  dates, reproducible from the recorded requests; `ops/measure_vendor_gap.py` runs it; and
  `tests/test_vendor_gap.py` pins the computation path against a recorded fixture payload so
  the script cannot silently drift onto its own arithmetic.

- [ ] **M2 — Write the implied-volatility procedure, and do not execute it**

  A procedure precise enough to run in ten minutes on a paid key, with no judgement left to
  the runner. It must state:

  - The exact endpoint, parameters and tickers.
  - The exact dates — the three where CBOE rows already exist.
  - The exact comparison: which stored column against which computed value, and through
    which functions (the same constraint as M1).
  - **The decision rule, written before the data arrives.** What measured gap would make a
    splice acceptable, and what gap would rule it out. Deciding this afterwards is how a
    measurement becomes a rationalisation. Justify the threshold in terms of what an
    `iv_rank` percentile is used for — if the gap is a large fraction of the spread of
    stored `iv_atm` values, the splice reorders the percentile and is not acceptable.
  - The cost: number of requests, and the fact that Alpha Vantage free answers `synthetic`
    so the procedure requires a paid key and cannot be trialled on a free one.

  Mark the section **UNEXECUTED** in the document, with the date and the reason, so nobody
  later mistakes a plan for a result.

- [ ] **M3 — Keep the refusal, and make it explain itself**

  D14 keeps Lane J's guard: the backfill refuses to write when the source vendor differs
  from the live options vendor unless `--allow-vendor-splice` is passed. Keep it, keep the
  `chain_source` / `chain_venue` / `chain_as_of` / `live_options_provider` stamps, and:

  - Make the refusal message **name `docs/research/alternatives/vendor-consistency.md`**, so the
    person who hits it finds the reasoning rather than guessing at the flag.
  - `--allow-vendor-splice` stays out of the ordinary documented workflow. Until a measured
    gap and a decision exist, it is an escape hatch, not an option.
  - Keep the two safety stops Lane J added: stop on the first `synthetic` answer, and after
    three consecutive failures of any kind. Do not soften either — they are what stops a
    free-tier key burning 25 requests a day on refusals.

  **Acceptance:** a test asserts the refusal fires on a vendor mismatch and that its message
  names the document.

- [ ] **M4 — Record the standing position in `docs/operations/IV-BACKFILL.md`**

  The backfill's own reference must not still describe a bulk Alpha Vantage backfill as the
  plan — **D13 declined it.** State the current position in one short section near the top:
  the baseline is being filled by waiting at a threshold of 10 sessions (Lane K), the
  backfill tool is retained and correct but **not scheduled to run**, and it is gated on a
  measured vendor gap that does not yet exist for implied volatility.

  Link `docs/architecture/VOLATILITY-BASELINE.md` (Lane K) and `docs/research/alternatives/vendor-consistency.md`.
  If Lane K has not landed yet, link it anyway — a forward link to a file arriving this round
  is better than a stale plan.

- [ ] **M5 — Report completion in `CROSS-LANE.md`**

  State plainly which half of D14 you measured and which you did not, so Lane O does not
  record item 19 as more complete than it is.

---

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_backfill.py tests/test_vendor_gap.py -q
PYTHONPATH=src .venv/bin/python -m pytest                          # expect >= 671 passed
PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv --dry-run
```

The dry run must still send no provider request and write no row — its own diagnostic says
so. Confirm that line still appears.

Check what the store actually holds before comparing anything against it:

```bash
.venv/bin/python -c "
import sqlite3; c = sqlite3.connect('data/briefing.sqlite3')
for r in c.execute(\"select ticker, snap_date, iv_atm, pc_ratio_vol, pc_ratio_oi \
from daily_snapshot where ticker='AAPL' order by snap_date\"): print(r)
"
```

## Done when

- A measured put/call gap exists in `docs/research/alternatives/vendor-consistency.md`, with the
  requests that produced it and the code path used.
- The implied-volatility procedure is written, has a decision rule fixed in advance, and is
  clearly marked UNEXECUTED with the reason.
- The vendor guard still refuses, and its message points at the document.
- `docs/operations/IV-BACKFILL.md` no longer presents a bulk Alpha Vantage backfill as the plan.
- Zero Alpha Vantage requests were spent by this lane. Verify:
  `ls data/provider_budget/alpha_vantage/` and confirm today's counter did not move.
