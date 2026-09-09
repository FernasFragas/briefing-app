# PA7 - Put/Call Percentile History

Research date: 2026-08-31.

**Closed. The premise was narrowed once already, and the remaining gap was filled by storage
rather than by a vendor.** Phase A rule 3: this was "sourced but unsupplied", not "no source".

## Premise check

| Claim | Verified | Finding |
|---|---|---|
| The P/C **level** comes from the CBOE chain, not from Alpha Vantage | ✅ | `options_math.py` sums put/call volume and OI from the quotes. Unaffected by any provider outage. |
| Only the **percentile history** came from AV | ✅ at filing, now removed | The live path used `_put_call_history` before Q0. It now passes only the stored `pc_ratio_vol` and `pc_ratio_oi` series into `build_options_structure`. |
| The AV P/C entitlement had never been tested with a key | ✅ at filing, now irrelevant | `historical_put_call_ratio` is no longer in the provider chain, source registry, or Alpha Vantage client. |
| The percentile terms have no live feed | ❌ **now false** | PB7 supplied a self-built series. |

## What closed it

The same mechanism as PA2(a), which is why the task said to evaluate them together. The
pipeline already persisted `pc_ratio_vol` and `pc_ratio_oi` to `daily_snapshot` every run;
nothing read them back.

`build_options_structure` is now called with the stored series only:

```python
pc_ratio_vol_history=stored_pc_vol,
pc_ratio_oi_history=stored_pc_oi,
```

There is no provider-first path for P/C history anymore. The 0.25-weight `put_call` leg no
longer depends on an Alpha Vantage entitlement nobody has verified, and the same 20-session
warm-up applies, with the same explicit "baseline still building: N of 20 sessions stored"
message.

## The deep probe: removed from the queue

The task made PA7 conditional on one deep AV probe with a key, blocked behind PB8 metering.
That stopped being worth doing after Q0. `HISTORICAL_PUT_CALL_RATIO` returns a top-level
`"date": "latest"` sentinel, contributes nothing the CBOE-derived stored series does not
already provide, and costs one Alpha Vantage daily request per ticker.

The source registry and Alpha Vantage client no longer expose the historical endpoint.
`REALTIME_PUT_CALL_RATIO` remains a separately registered endpoint, but the live `S_O`
put/call level still comes from the CBOE chain.

## Alternatives considered and not adopted

| Candidate | Why not |
|---|---|
| CBOE published P/C CSVs | Market-wide totals, not per-symbol. The leg is scored per ticker, so this cannot substitute. Would be a *market context* input, which is a different feature. |
| Buying P/C history | Same argument as PA2(a): a subscription to skip a 20-session wait on data the app already generates. |

## Evidence

- Self-built P/C history wired through `_stored_option_series` and
  `build_options_structure`, landed 2026-08-31 and made sole path on 2026-09-02.
- Warm-up enforced and tested: `SELF_BUILT_SERIES_MIN_SESSIONS = 20`, covered by
  `test_self_built_series_is_withheld_until_the_warm_up_completes`.
- `before_date` is exclusive, so today's snapshot is not part of the history today's reading
  is ranked against — covered by `test_todays_snapshot_is_excluded_from_its_own_baseline`.
