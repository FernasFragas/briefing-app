# Live-run budget ledger

## Allowance and recorded counter

D16 currently tracks the shared Alpha Vantage free allowance: **25 requests per Lisbon
day**. Its factual request counter is `data/provider_budget/alpha_vantage/YYYY-MM-DD.json`.
`ops/live_budget.py` reads that file and the claim ledger before a lane starts a live command;
it never sends a provider request and never changes the counter.

## Reservation rule

The daily briefing is served first. Until a daily run has completed *and its Alpha Vantage
counter exists*, all 25 requests are held for it. Afterwards, the same 6-request re-run floor
used by `backfill.py` remains held, and only the rest can be claimed by a lane. A missing
counter is not evidence of an untouched, healthy allowance: it is the provider-less-run shape
that D16 must not repeat. A lane arriving after the pot is committed or spent receives a `NO`
verdict and sends nothing.

## Claim before spending

Before a live request, append a unique row to [`tasks/BUDGET-LEDGER.md`](../../tasks/BUDGET-LEDGER.md)
under `## Claims`. Record the Lisbon date, lane, provider, number of requests, `kind`, and a
specific purpose. After the command, append its factual count and result under `## Outcomes`.
An unclaimed lane has no allowance. In round 3, the only positive standing allowance is Lane
O's one owner-named daily run; it is a `daily-run` claim, not permission for a second run.

## Check the claim

Run this immediately before the command that would spend the request:

```bash
PYTHONPATH=src .venv/bin/python ops/live_budget.py \
  --provider alpha_vantage --lane O --claim 2026-09-09-o-daily-1 \
  --requests 25 --daily-run --json
```

`verdict: "yes"` and exit code 0 authorise only that claimed number. `verdict: "no"` and exit
code 2 mean do not run the provider command. The JSON reports the counter's recorded spend,
the live-run reserve, whether a daily run has completed, and every same-day ledger commitment.

If the answer is no, wait for the next provider day. If the work genuinely must happen today,
hand the run to the owner; do not retry, split it into smaller requests, or invent an
unrecorded allowance.

`ops/status.py --json` includes the same Alpha Vantage position in `derived.budget` (or in
top-level `budget` when no local run-status file exists yet).

## Providers outside this ledger

MarketData.app and CBOE are keyless; FRED and SEC EDGAR have no numeric daily free allowance
to divide. They are therefore not D16 budget-tracked. Their normal client pacing and request
counters remain useful diagnostics, but they are not a shared 25-request pot. Financial
Modeling Prep, Finnhub, Twelve Data, FINRA, and ApeWisdom retain their client-level policies;
none has a round-3 cross-lane allowance in this ledger.
