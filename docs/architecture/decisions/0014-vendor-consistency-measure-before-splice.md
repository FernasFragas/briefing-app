# 0014 — Vendor consistency: measure the gap before permitting any splice

| | |
|---|---|
| **Status** | Accepted. Keeps the vendor guard built for 0003; commissions a measurement. |
| **Date** | 2026-09-08 |
| **Round** | 3 |
| **Original identifier** | `D14` — cited by that name throughout the task documents |

---

**The standing rule stays "refuse", and it stays in force until a measurement exists.**
Lane J's guard is kept: the backfill refuses to write when the source vendor differs from
the live options vendor unless `--allow-vendor-splice` is passed explicitly. What changes
is that the refusal is no longer the end of the argument — a measurement is commissioned so
the rule can eventually be decided on a number instead of on principle.

**Why this is not a theoretical concern.** `config.providers.options` is
`[cboe, alpha_vantage]`. Every stored `iv_atm`, `pc_ratio_vol` and `pc_ratio_oi` in the
project came from CBOE, captured intraday — 2026-09-03 at 17:14:21 UTC, for instance. An
Alpha Vantage historical chain is the session close. A percentile is a ranking *within one
series*; splicing two vendors' readings into it answers a comparison nobody made, and the
answer looks exactly as confident as a correct one.

> ### The tension the owner should see stated plainly
>
> D13 declines to pay, and the implied-volatility half of this measurement **needs a paid
> key**: Alpha Vantage `HISTORICAL_OPTIONS` is not on the free tier — it answers HTTP 200
> with a sample payload that this project's own validation classifies as `synthetic`
> (`docs/research/SOURCE_STATUS.md`). So the full measurement cannot be executed today.
>
> **This does not make the decision empty, and Lane M must not treat it as such.** Two
> things are executable now:
>
> 1. **The put/call half can be measured for free, today.** MarketData.app serves genuine
>    past-dated chains keyless with real `volume` and `openInterest`
>    (verified by Lane I: 1,336 contracts across 10 expirations for AAPL). So
>    `pc_ratio_vol` and `pc_ratio_oi` computed from a MarketData.app past-date chain can be
>    compared directly against the CBOE-derived values already stored for 2026-09-03,
>    2026-09-06 and 2026-09-07. That is a real cross-vendor gap on two of the three gated
>    legs, at zero cost. Its `iv` field is null on past dates, so it cannot measure the
>    third.
> 2. **The implied-volatility half is written up and left unexecuted**, as a procedure
>    precise enough that whoever holds a paid key can run it in ten minutes and get a
>    number.
>
> Until a measured gap exists, `--allow-vendor-splice` stays undocumented in the ordinary
> workflow and no bulk backfill runs.

**Rejected:** permitting the splice with a stamped provenance field and a report caveat.
The self-healing argument for it is real — the window purifies after ~20 further weekday
runs — but that is the same wait the splice was meant to avoid, so it accepts a
known-suspect number in exchange for nothing.
