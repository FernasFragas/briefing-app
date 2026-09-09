# PB1 (13F half) - Blocked By Design, Not By Wiring

Date: 2026-08-31.

Scope: the S_F half of PB1, filed as "wire SEC EDGAR 13F into `_ownership_changes`". The
Form 4 half of PB1 landed the same day; this half cannot land the same way.

**Verdict: not a wiring task. It needs a filer universe and a two-quarter diff, neither of
which exists. Recorded here so it is not repeatedly reopened as cleanup.**

## Premise check

| Claim | Verified | Finding |
|---|---|---|
| An EDGAR 13F normalizer exists | ⚠️ Partly | `normalize_sec_13f_information_table_snapshot` existed but was **non-functional**: it called 19 helpers, none of which were defined, and had no tests. The helper layer was written on 2026-08-31 for the Form 4 path and the two 13F helpers were completed with it, so the function now runs. |
| The pipeline never calls it | ✅ | `_ownership_changes` had no `sec_edgar` branch. |
| Wiring it would give S_F a working source | ❌ | Two independent blockers below. |

## Blocker 1 - EDGAR indexes filings by filer, not by holding

`company_submissions` answers "what did this filer file". There is no endpoint answering
"who holds NVDA". A 13F information table is only reachable once you already know **which
manager's** filing to open, so the S_F path needs a filer universe - a maintained list of
CIKs worth polling - before a single request can be made.

That list is a research and curation decision (which cohorts: active, passive, sovereign?
how many? refreshed how often?), not a wiring detail. It also multiplies request volume:
one filing per manager per quarter, per cohort.

## Blocker 2 - the component scores deltas; the filing carries a snapshot

`S_F` is specified as "US 13F active/passive/sovereign **cohort deltas**". An information
table is a position snapshot, and the normalizer says so in its own docstring:

> Official EDGAR information tables are holdings snapshots. They do not carry issuer-level
> deltas [...] this normalizer leaves `shares_delta` and `percent_delta` as `None` rather
> than inventing changes from a single filing.

So even with a filer list, one quarter produces no score. Deltas need **two consecutive
quarters per filer**, persisted and diffed - a store and a backfill, not a fetch.

## What would unblock it

In dependency order:

1. **Decide the filer universe.** A named, version-controlled list of manager CIKs by
   cohort, with a documented selection rule. This is the actual open question.
2. **Persist holdings per (filer, issuer, quarter).** `daily_snapshot` is the wrong shape;
   this needs its own table, and therefore a migration.
3. **Diff consecutive quarters** into the existing `OwnershipChange` model, which already
   carries `shares_delta` and `percent_delta`.
4. Only then wire `_ownership_changes`.

Steps 1-3 are the work. Step 4 is the part the ticket described.

## Interim position

`S_F` has no live source: Alpha Vantage is refusing and FMP `institutional_ownership` is
`paywalled`. It degrades to `n/a` with a named reason and re-weights, which is the correct
behaviour - it is not silently scored as zero.

**Do not route S_F through an aggregator to close this faster.** PA6 already settled that:
EDGAR is the primary record, and substituting an aggregator downgrades source quality on a
component whose whole value is that it reads the original filing. The honest state is a
declared `n/a` until the filer universe exists.
