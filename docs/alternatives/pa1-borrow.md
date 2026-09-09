# PA1 - Borrow Leg Of S_O (`short_borrow`, weight 0.05)

Research date: 2026-08-31.

Scope: `provider-alternatives-wiring-tasks.md` PA1. The task asks which of three distinct
data types the leg can ever score on. This note answers that and hands the wiring half to
PB1, per Phase A rule 3 ("separate 'no source' from 'sourced but unsupplied'"). No cached
payload under `data/raw/` is cited as entitlement evidence.

## Premise check

The filed premise was **half right**, and the half that was wrong changes the wiring.

| Claim in the task | Verified | Finding |
|---|---|---|
| `short_borrow` never scores | ✅ | `LIVE_UNSCORABLE_LEGS` carried `short_borrow` with the reason "nothing constructs a `ShortBorrowSnapshot` on the live path". |
| FINRA client exists but is unwired | ✅ | `providers/finra.py` and `normalize_finra_short_volume` existed and passed tests; `pipeline.py` had zero references. |
| FINRA carries short **volume** only | ✅ | `normalize_finra_short_volume` sets `short_volume` / `total_volume` and nothing else. |
| Wiring FINRA makes the leg score | ⚠️ **Not as the model stood** | `short_borrow_metrics` scored only `short_interest_pct_float`, `days_to_cover`, `borrow_fee_pct` and `utilization_pct`. FINRA supplies **none** of them. |

That last row is the finding. A FINRA snapshot would have passed `verified=True` and then
returned `score=None` with "verified but had no numeric fields" — wired, and still silent.

## The three data types, kept apart

| Type | What it measures | Free source | Verdict |
|---|---|---|---|
| **Daily short volume** | Share of a session's *volume* that printed short. Typically 0.45–0.55 on a liquid US name, much of it market-maker hedging. | **FINRA CNMS consolidated file** — `cdn.finra.org/equity/regsho/daily`, no key, no quota, `ok` on the 2026-08-31 preflight. | **Adopt.** The only one with a free feed. |
| **Short interest / days-to-cover** | Share of *float* held short, and cover time. Typically 0.01–0.10 of float. Bi-weekly. | FINRA publishes equity short interest separately from the daily RegSHO file; exchange files and SEC Reg SHO threshold lists also exist. Not probed in this pass. | **Monitor.** Plausible but unproven — needs its own probe before adoption. |
| **Borrow fee / utilization** | Cost and scarcity of borrow. | None found. S3, Ortex and IBKR all gate this behind paid plans. | **Reject — permanently `n/a`.** Spec a paid tier only if the leg ever justifies one. |

**These are not interchangeable.** Writing a 0.65 short-*volume* ratio into
`short_interest_pct_float` would clamp `0.65/30` — or, read as a percentage, `65/30` → 1.0,
maximum squeeze risk on a completely ordinary tape. Conflating them is the failure mode this
note exists to prevent.

## Verdict

**Adopt FINRA daily short volume as a labelled flow proxy. Score it on its own field.**

`ShortBorrowSnapshot` gained a distinct `short_volume_ratio` (0..1), scored against its own
baseline rather than borrowed scaling:

```
contribution = clamp((ratio - SHORT_VOLUME_RATIO_BASELINE) / SHORT_VOLUME_RATIO_SPAN, 0, 1)
               baseline 0.50, span 0.30
```

Only the excess over baseline carries signal, and a ratio at or below baseline contributes
0 rather than a negative: this leg measures squeeze risk, not bullishness. Whenever the
ratio is used, `ShortBorrowMetrics.diagnostics` carries "short_volume_ratio is a daily
short-VOLUME flow proxy, not short interest and not a borrow fee", so the label travels with
the number into the evidence ledger.

The other two legs stay absent, and honestly so: short interest is unprobed, borrow fee has
no free source.

## Evidence

- FINRA CNMS reachable and validating: 2026-08-31 preflight, `finra.short_sale_volume` `ok`.
- Client and normalizer verified present and unreferenced by `pipeline.py` on 2026-08-31
  (`grep -c finra src/briefing_app/pipeline.py` → 0 before this work).
- Scoring gap verified by reading `short_borrow_metrics` in `options_math.py`: the four
  scored inputs are named there and FINRA supplies none of them.

## Handed to PB1

Wiring only, no vendor: FINRA client into `LiveDataSource._short_borrow`, walking back up to
`FINRA_LOOKBACK_SESSIONS` sessions because the consolidated file lands T+1. Landed
2026-08-31; `short_borrow` is off `LIVE_UNSCORABLE_LEGS`.

## Open

- **Short interest / days-to-cover needs a probe.** If FINRA's bi-weekly file is fetchable
  on the same unauthenticated host, it would upgrade this leg from a volume proxy to the
  real quantity. That probe belongs to Phase C (PC1/PC2), not to a re-run of PA1.
- The 0.50 baseline and 0.30 span are reasoned defaults, not calibrated ones. They should be
  revisited once `call_log` has enough resolved outcomes to test them (T12).
