# Report Layout

The dashboard opens on the trading ideas table. That table contains issuer-backed names
that can produce a real trading setup or an explicit no-setup row. Index and fund
candidates are excluded from this table because baskets have no issuer, analyst coverage,
or insider filings, so their grades are not comparable with single-company ideas.

Trading ideas are ordered by execution state first, then by grade: `TRADEABLE`,
`WATCHLIST`, `BLOCKED`, `UNSCORED`; graded rows sort by `grade_score` descending inside
each status bucket; ungraded rows sort last; ticker is the final tie-breaker. Component
counts and component names remain visible in each row, but they do not group or outrank
the grade.

The table separates two measurements that should not be read as the same thing.
**Conviction** is the uncapped 0–100 measure of how strongly the evidence supports the
declared idea. **Certainty** is the data-quality letter that caps how far that conviction
can be trusted. A `100.0` conviction with `C` certainty is a high-support reading with a
low confidence ceiling, not a contradictory grade; ordering remains by conviction.

**Thesis** is the direction declared for the idea. **Data reads** is the independently
computed composite posture and score. The dashboard explicitly marks a disagreement when
the data does not support the declared direction. That is useful falsification of the
thesis, not a rendering or scoring error.

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
