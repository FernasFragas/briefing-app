# Vendor consistency — measure before permitting a splice

Decision D14 keeps the backfill vendor guard in place. The live options provider is CBOE,
whose readings are captured intraday; a historical alternative is a session close. An IV rank
or put/call percentile is a ranking within one series, so provenance alone does not make a
mixed-vendor series comparable.

This record separates a same-day cross-vendor comparison from repeated CBOE captures of
one exchange session. It also fixes, in advance, the procedure and decision rule for the paid
implied-volatility input. It does **not** approve `--allow-vendor-splice`.

**Attribution corrected 2026-09-09 (Prompt A):** the original percentages are unchanged,
but the 55.38% / 146.34% row is **intra-CBOE capture variation**, not evidence of a vendor
definitional gap. The correction and its tests used zero live requests, including MarketData.

## M1 — measured put/call gap

**Run date:** 2026-09-09. **Scope:** AAPL only. MarketData.app serves this symbol keyless;
SPY, QQQ, and CRWV require credentials, so this is deliberately a one-symbol measurement rather
than an invented universe-wide result. No Alpha Vantage request was sent.

The original measurement used this command (historical record, **do not rerun under this
correction's zero-request allowance**):

```bash
PYTHONPATH=src .venv/bin/python ops/measure_vendor_gap.py
```

It read the stored CBOE-derived `daily_snapshot` rows and obtained chains at these two
unique successful keyless URLs (the unsuccessful weekend/holiday probes are noted below):

```text
https://api.marketdata.app/v1/options/chain/AAPL/?date=2026-09-03&dte=7
https://api.marketdata.app/v1/options/chain/AAPL/?date=2026-09-04&dte=7
```

`dte=7` asks MarketData.app for the expiry nearest the live path's weekly target; the shared
options math still selects the expiry from the normalised chain. The response hashes were,
respectively, `da2b63ff0614c1c46de5ef4750e1ea16e99da274ed3b393770f4753cfd37bd25` and
`4922f023e2a14c9aa48a0d54a13d97ff94a8e8b4ed6a6e08f06f9deb1655d3d3`.

### Session alignment

The stored row date is the briefing run date, not necessarily a US trading session. Direct
MarketData.app requests for `2026-09-06` (Sunday) and `2026-09-07` (Labor Day) both returned
HTTP 404. This is not silently papered over: the CBOE payloads used for those rows report
`data.last_trade_time = 2026-09-04T16:00:00`, so both are compared with the MarketData.app
**2026-09-04** end-of-day chain. The comparison remains labeled with each stored `snap_date`.

| Stored CBOE `snap_date` | MarketData session close | `pc_ratio_vol` CBOE | MarketData | Absolute gap | Relative gap | `pc_ratio_oi` CBOE | MarketData | Absolute gap | Relative gap |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-03 | 2026-09-03 | 0.3321239865 | 0.3024659192 | 0.0296580672 | 8.93% | 0.2537876856 | 0.2438273999 | 0.0099602857 | 3.92% |
| 2026-09-06 | 2026-09-04 | 0.3268198411 | 0.3268198411 | 0.0000000000 | 0.00% | 0.5599254702 | 0.5599254702 | 0.0000000000 | 0.00% |
| 2026-09-07 | 2026-09-04 | 0.2103317346 | 0.3268198411 | 0.1164881065 | 55.38% | 0.2272996155 | 0.5599254702 | 0.3326258547 | 146.34% |

### What these three rows actually establish

**Row 1 is the only same-day, two-vendor comparison.** CBOE's September 3 capture is
intraday (`timestamp = 2026-09-03 17:14:21`); MarketData's September 3 chain is the close.
The observed gaps are **8.93% for volume and 3.92% for open interest, for AAPL on one day**.
That is the scope of the vendor measurement. It does not establish a persistent vendor
bias, universe-wide comparability, or a definitional difference: time of capture remains
confounded with vendor. One ticker-day cannot settle those questions.

**Rows 2 and 3 are two CBOE captures of the same September 4 exchange session**, each
compared with the *same* MarketData September 4 payload. They are not two independent
session observations. The archived CBOE evidence is:

| Stored run date | CBOE payload timestamp | `data.last_trade_time` | Contracts |
|---|---|---|---:|
| 2026-09-06 | 2026-09-05 23:09:42 | 2026-09-04T16:00:00 | 3,140 |
| 2026-09-07 | 2026-09-07 20:41:05 | 2026-09-04T16:00:00 | 3,260 |

Those CBOE-derived readings disagree **with each other**. Using the later, smaller CBOE
reading as denominator (the table's convention), their differences are 55.38% in volume
and 146.34% in open interest. Because row 2's MarketData readings equal the earlier CBOE
readings, row 3's large “vendor gap” is numerically the same within-CBOE difference. It
therefore cannot isolate a vendor effect. This is **intra-CBOE delayed-chain capture
variation**; the differing contract universes corroborate that the captures are not stable.
The evidence does not identify why the delayed captures changed or disentangle all effects
of capture composition and date-dependent contract selection.

Row 2's agreement to the recorded sixteen-significant-figure precision is more plausibly
explained by **shared upstream exchange data** than by independent measurements happening
to agree. That is the working interpretation, **not verified data lineage**. Agreement of
one capture does not demonstrate independent validation or stability across later captures.

This is not peculiar to AAPL: all **18** tickers present in both the September 6 and 7 raw
directories report September 4 as their last-trade session. That verifies repeated source
sessions across the capture set, not that every ticker has AAPL's ratio discrepancy.

### Reproducibility and retained evidence

The original script did **not** save the two MarketData responses. The recorded hashes
are not replacements for those payloads. **The original MarketData side is still not
replayable from this checkout**; no original payload was found or recreated during this
zero-request correction. Do not relabel a CBOE-derived reconstruction or the small test
fixture as an original MarketData response. The table retains the original measured numbers,
with its narrower interpretation; historical replay awaits the original files.

Future authorized fetches now save the complete decoded response **by default, before
normalization or measurement**, under:

```text
data/raw/marketdata/vendor_gap/<exchange-session>/AAPL-<payload_sha256>.json
```

`--payload-dir` changes the root, not the save requirement. The bytes are canonical JSON
(`sort_keys=True`, separators `(',', ':')`, UTF-8); their SHA-256 is the reported
`payload_sha256`. Identical payloads reuse the same file; a different capture gets a new
hash filename and never overwrites an earlier capture. Each comparison reports its
`payload_path`, hash, request URL, replay/fetched mode, and CBOE raw path/hash, last-trade
session, timestamp and contract count. Two captures of one session reuse one fetched
MarketData response within the command. This fixes retention for future authorized work;
it cannot retroactively recover the missing originals.

**Exact original replay inputs and commands.** The following names use the recorded hashes;
these files are **missing, not newly fetched or verified**. After the original responses are
supplied at these paths, each command reproduces the indicated table row without networking:

```bash
# Row 1: stored September 3 against MarketData September 3
PYTHONPATH=src .venv/bin/python ops/measure_vendor_gap.py --date 2026-09-03 --payload data/raw/marketdata/vendor_gap/2026-09-03/AAPL-da2b63ff0614c1c46de5ef4750e1ea16e99da274ed3b393770f4753cfd37bd25.json
# Row 2: stored September 6 against MarketData September 4
PYTHONPATH=src .venv/bin/python ops/measure_vendor_gap.py --date 2026-09-06 --payload data/raw/marketdata/vendor_gap/2026-09-04/AAPL-4922f023e2a14c9aa48a0d54a13d97ff94a8e8b4ed6a6e08f06f9deb1655d3d3.json
# Row 3: stored September 7 against the SAME MarketData September 4 file
PYTHONPATH=src .venv/bin/python ops/measure_vendor_gap.py --date 2026-09-07 --payload data/raw/marketdata/vendor_gap/2026-09-04/AAPL-4922f023e2a14c9aa48a0d54a13d97ff94a8e8b4ed6a6e08f06f9deb1655d3d3.json
```

Check each reported `payload_sha256` against the recorded hash above; a newly obtained,
different response would be a **new measurement**, not a replay of these rows. Each replay
also reads `data/briefing.sqlite3` and
`data/raw/cboe/delayed_options_chain/<stored-run-date>/AAPL.json`. Those CBOE files are
present. The **currently executable, zero-request** evidence check is:

```bash
PYTHONPATH=src .venv/bin/python ops/measure_vendor_gap.py --cboe-only
```

Observed exit **0**: `capture_count: 3`, `distinct_exchange_sessions: 2`; the repeated-session
group has `session_date: 2026-09-04`, `snap_dates: [2026-09-06, 2026-09-07]`,
`metrics_differ: true`, `interpretation: intra_cboe_capture_variation`. It prints all three
stored CBOE ratios at full precision plus the raw paths, hashes and contract counts above.
It deliberately reports `status: cboe_only`, **not** a newly measured MarketData gap.

To verify the broader repeated-session observation from the archived files:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
root = Path('data/raw/cboe/delayed_options_chain')
first = {p.stem: json.loads(p.read_text())['data']['last_trade_time'] for p in (root/'2026-09-06').glob('*.json')}
second = {p.stem: json.loads(p.read_text())['data']['last_trade_time'] for p in (root/'2026-09-07').glob('*.json')}
common = sorted(first.keys() & second.keys())
print('common tickers:', len(common), common)
print('same September 4 session:', sum(first[t][:10] == second[t][:10] == '2026-09-04' for t in common))
print('exceptions:', [(t,first[t],second[t]) for t in common if first[t][:10] != second[t][:10] or first[t][:10] != '2026-09-04'])
PY
```

Observed exit **0**: `common tickers: 18`, `same September 4 session: 18`, `exceptions: []`.

The reporting tool now derives session identity from each CBOE payload's
`data.last_trade_time`, never from its directory date; a missing timestamp fails before a
fetch rather than guessing a session. This is measurement reporting only. Whether the
**volatility baseline** should count calendar snapshots or distinct exchange sessions is
the owner's [Prompt B decision](../../../tasks/FOLLOWUP-PROMPTS.md#prompt-b--the-session-counting-decision-brief).
No baseline query, snapshot deduplication, pipeline or grading behavior is changed here.

### Computation path

`ops/measure_vendor_gap.py` does no put/call arithmetic. It converts documented MarketData.app
field names (`optionSymbol`, `underlyingPrice`, `bid`, `ask`, `volume`, `openInterest`, and
available Greeks) to the input envelope accepted by the shipping CBOE normalizer, preserving the
provider's OCC symbols. It intentionally leaves `last_trade_time` absent: MarketData.app supplies
a chain `updated` timestamp, not a per-contract trade time, and inventing one would make the
live liquidity filter accept fabricated freshness.

The measurement then calls exactly:

```text
briefing_app.providers.normalizers.normalize_cboe_option_chain
briefing_app.options_math.build_options_structure
```

The latter selects the weekly expiry and computes both ratios; only the final capture-to-capture
absolute and relative gaps are calculated by the script. `tests/test_vendor_gap.py` uses a
recorded-shape MarketData payload fixture, wraps both functions, and fails unless both shipping
functions are invoked. It also pins the fixture's resulting volume ratio of `0.5` and
open-interest ratio of `0.75`.

The new regression was run **before** changing the tool:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_vendor_gap.py -k groups_cboe
```

Before: **2 failed**, exit 1, both `KeyError: 'session_summary'`. After: **2 passed**,
exit 0. It supplies two raw CBOE payloads, changes only the second source-session date,
and checks one versus two distinct sessions; same-session changed readings must be labeled
`intra_cboe_capture_variation` while both capture rows remain visible. It therefore cannot
pass by always returning one session or simply hiding duplicate rows.

`PYTHONPATH=src .venv/bin/python -m pytest tests/test_vendor_gap.py` reports **8 passed**,
exit 0. Further tests pin default saving before computation, byte/hash identity, preservation
of changed captures, network-free saved-payload replay, missing-session refusal, and the
offline CBOE-only mode (including repeated captures whose ratios do not differ).

**Falsifiability, re-checkable rather than historical.** The before/after run above is a
record of one past session and cannot be replayed from this checkout. The same property is
demonstrable at any time by mutation, which is the form a later reader should trust. Replace
the grouping key in `session_summary` with the pre-correction reading — group by the fetch
date rather than by the session the payload states:

```python
# ops/measure_vendor_gap.py, in session_summary()
key = (row["ticker"], row["snap_date"])          # was: row["cboe_capture"]["session_date"]
```

Then `PYTHONPATH=src .venv/bin/python -m pytest tests/test_vendor_gap.py -k groups_cboe`
fails at `assert summary["distinct_exchange_sessions"] == expected_sessions` with
`assert 2 == 1` — the mutated tool reports two captures of one September 4 session as two
independent observations, which is precisely the error this record corrects. Observed
2026-09-09: **1 failed, 1 passed**, exit 1, then **2 passed**, exit 0 once the mutation was
reverted. The second parametrised case (genuinely distinct sessions) passes in both states,
so the test discriminates rather than failing on any change. Revert the mutation afterwards;
it exists to prove the assertion has teeth, not to be kept.

## M2 — implied-volatility procedure (**UNEXECUTED**, 2026-09-09)

The 54 comparisons below are **capture comparisons**, not 54 independent exchange-session
observations: September 6 and 7 reuse the same source session. The three-row CBOE spread
also includes within-session capture variation. The precommitted rule is retained, not
relaxed; it is not a statistical guarantee about independent session-to-session variation.

**Reason unexecuted:** Alpha Vantage `HISTORICAL_OPTIONS` is paid-only. On the free key it
returns an HTTP-200 sample that this project's validation marks `synthetic`; it would spend an
Alpha Vantage request and yield no measurement. D13 declined to buy a paid key. This lane sent
**zero** Alpha Vantage requests.

When a paid key is deliberately authorized, run this exact comparison before allowing any
splice:

1. For each of `SPY, QQQ, AAPL, MSFT, META, AMZN, GOOGL, INTC, CRWV, AMAT, ORCL, LMT, XOM, MU,
   COST, JPM, FDX, GM`, read the stored CBOE `daily_snapshot.iv_atm` rows with `snap_date`
   `2026-09-03`, `2026-09-06`, and `2026-09-07`.
2. Query the paid endpoint
   `https://www.alphavantage.co/query?function=HISTORICAL_OPTIONS&symbol=<TICKER>&date=<SESSION_DATE>&apikey=<PAID_KEY>`.
   Use the source-session pairs `(2026-09-03, 2026-09-03)`, `(2026-09-06, 2026-09-04)`, and
   `(2026-09-07, 2026-09-04)`, where each pair is `(stored snap_date, option date)`. Thus there
   are 54 comparisons and 36 unique historical-chain requests; reuse each 09-04 payload for its
   two stored rows.
3. Pass every response to `build_backfill_snapshot_row` with the normal option filters, its
   endpoint URL, and fetched time; do not write the returned row. This executes the existing
   `normalize_alpha_vantage_options_chain` and `build_options_structure` path that the backfill
   uses. Compare its `iv_atm` with the stored CBOE `daily_snapshot.iv_atm` for the matching
   stored row. Reject missing, non-verified, or non-finite values rather than omitting them.
4. Record every raw value, absolute gap, stored per-ticker spread, endpoint URL, payload hash,
   and provider/as-of timestamp in this document before changing any backfill flag or command.

### Decision rule fixed before the data arrives

The splice is acceptable only if **every** one of the 54 matched readings is present and both
conditions hold for **every** reading of each ticker:

1. `abs(alpha_vantage_iv_atm - cboe_iv_atm) <= 0.0020` (no more than 0.20 volatility points); and
2. the same gap is at most **10%** of that ticker's three-row stored CBOE `iv_atm` spread
   (`max - min`). A zero or missing spread fails the rule because it offers no demonstrated
   ordering tolerance.

There is no average-pass exception: a single excess gap rules the splice out for the entire
series. A percentile is used to rank nearby observations, so an offset that is a material
fraction of the observed spread can reorder the rank even if its absolute number looks small.
The 10% cap limits the permitted gap relative to the observed three-row spread; that spread
includes capture variation and is not a pure session-to-session separation. The 0.20-point
cap prevents a large permitted offset during a wider three-capture range. For context, AAPL's stored
three-row spread is `0.0201` (2.01 volatility points), making its relative cap `0.00201`, nearly
the absolute ceiling. The rule therefore has a numerical meaning before Alpha Vantage data
arrives, rather than selecting a tolerance after observing it.

At the paid plan's documented 75 requests/minute, the 36 unique requests fit inside one minute;
ten minutes allows the response validation, computation, and record. A free key must not be
used as a trial: its synthetic payloads are invalid evidence and consume the shared daily
allowance.

## Standing conclusion

**D14 is unchanged: the splice stays refused.** The actual same-day cross-vendor evidence
is limited to AAPL on September 3: 8.93% volume and 3.92% open-interest differences, still
confounded with intraday versus closing capture. The much larger September 7 differences
do not establish a vendor definitional gap; they expose instability between CBOE captures
of the **same September 4 session**. Until that within-vendor capture stability and session
identity are understood, adding a second vendor cannot be justified as a consistent
baseline. Exact agreement of the September 6 capture with MarketData is plausibly shared
upstream data, not proof that the mixed series is safe.

Neither a single ticker-day nor an internally unstable capture series supports a
universe-wide splice. Implied-volatility consistency remains **unmeasured**, and the paid
procedure and precommitted refusal criteria above remain unchanged. No ordinary backfill
workflow may use `--allow-vendor-splice`. Prompt B owns the broader baseline-session
decision; this correction changes attribution and evidence retention, not that policy.
