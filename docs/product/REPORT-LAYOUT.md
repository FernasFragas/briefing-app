# Report Layout

The dashboard opens on the trading ideas table. That table contains issuer-backed names
that can produce a real trading setup or an explicit no-setup row. Index and fund
candidates are excluded from this table because baskets have no issuer, analyst coverage,
or insider filings, so their grades are not comparable with single-company ideas.

The flat `trading_ideas` audit list is ordered by execution state first, then by grade:
`TRADEABLE`, `WATCHLIST`, `BLOCKED`, `UNSCORED`; graded rows sort by `grade_score`
descending inside each status bucket; ungraded rows sort last; ticker is the final
tie-breaker. Component counts and component names remain visible in each row, but they do
not group or outrank the grade.

The table separates two measurements that should not be read as the same thing.
**Conviction** is the uncapped 0–100 measure of how strongly the evidence supports the
declared idea. **Certainty** is the data-quality letter that caps how far that conviction
can be trusted. A `100.0` conviction with `C` certainty is a high-support reading with a
low confidence ceiling, not a contradictory grade; ordering remains by conviction.

**Thesis** is the direction declared for the idea. **Data reads** is the independently
computed composite posture and score. The dashboard explicitly marks a disagreement when
the data does not support the declared direction. That is useful falsification of the
thesis, not a rendering or scoring error.

## Supported and contradicted theses

The reader-facing table has two headed sections and the JSON has matching
`supported_theses` and `contradicted_theses` arrays. Every row remains in the flat audit
list and exactly one of those arrays. **Theses the data supports** contains rows whose
published composite posture supports their declared direction; it is ranked by conviction
descending. **Theses the data contradicts** contains the remaining declared-direction
disagreements and retains the per-row Thesis, Data reads, and disagreement marker, so an
excerpt remains self-describing.

The split exists because zero conviction is meaningful: it says the evidence does not
support the declared direction, not that the calculation failed. Separating those rows
makes a falsified thesis legible without changing any grade.

## Volatility-baseline and penalty details

When a self-built percentile is available, its row-level `volatility_baselines` entry
names the reading and carries `sessions` plus `provisional`. A 10--19-session reading
renders as, for example, **Provisional — 12 stored sessions**; at the default settled
threshold of 20 it renders as settled. The page uses the producer's flag rather than
hardcoding a denominator that could contradict a configured threshold. A withheld or
currently unavailable percentile has no invented baseline entry.

Rows that carry `crowding_penalty` publish its point magnitude beside the penalty name and
as `crowding_penalty` in JSON. This makes the deduction readable from the row itself rather
than requiring a lookup of the gate confidence multiplier elsewhere in the document.

When the root `run_health` summary says the run is incomplete, a banner appears above the
table with component and name coverage plus providers that did not answer. A total provider
outage uses stronger wording: the report was built without live provider data and must not
be treated as a normal daily briefing. Healthy runs, and older payloads with no
`run_health`, show no banner.

Index and fund candidates are identified through `Candidate.is_index_or_etf`, which is
derived from permitted instruments: `etf` is present and `shares` is absent. The report
does not pattern-match ticker strings. Those candidates move to Market Overview with a
card per ticker showing spot, implied volatility, expected move, composite score, and
tier when those values were available to the dashboard builder.

The first-level sections visible without expanding anything are Trading Ideas, Analysis /
Per-Stock, and Market Overview. Diagnostic sections are collapsed behind `<details>`:
Master Alpha Selection Matrix, Prior Scorecard, Tactical Execution Dashboard,
Conditionality Table, Rejected At Gate, and Evidence Ledger.
