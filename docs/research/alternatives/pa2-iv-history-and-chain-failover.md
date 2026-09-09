# PA2 - IV History And CBOE Failover

Research date: 2026-08-31. No cached payload under `data/raw/` is cited as entitlement evidence.

PA2 has two halves. **(a) closes on disproof — the gap was fixed by wiring, not by a vendor.
(b) stays open with one adopt candidate.**

## PA2(a) - IV history: closed, premise no longer holds

The filed premise was "no IV history, so `iv_rank` is always `None` in live mode, and the
`iv_extreme` leg (weight 0.10) never scores".

**That was true when filed and is false now.** Phase A rule 3 says to separate "no source"
from "sourced but unsupplied", and this was the second: nothing needed buying.

The pipeline already persisted `iv_atm` to `daily_snapshot` on every run
(`scoring.py:to_daily_snapshot_row`); nothing ever read it back. PB2 closed the loop:

- `StorageRepository.option_metric_history` returns the trailing `iv_atm` series.
  The pre-existing `iv_rank_history` could not do this - it reads the stored **rank**,
  which is `None` until a baseline exists, so it can never bootstrap itself.
- `LiveDataSource._stored_option_series` supplies it, and `build_options_structure` is now
  called with `iv_history=` on the live path (`pipeline.py:1371`).
- `iv_extreme` is off `LIVE_UNSCORABLE_LEGS`.

**Cost, stated plainly:** a warm-up of `SELF_BUILT_SERIES_MIN_SESSIONS` (20) sessions. Below
that the series is withheld entirely and the run reports "iv_rank baseline still building:
N of 20 sessions stored". A percentile over three points is not a weak reading, it is a
meaningless one.

**Vendors rejected against the self-build**, per the task's instruction to evaluate storage
first: buying IV history (ORATS, Market Chameleon) costs a subscription to remove a 20-session
wait, on a leg weighted 0.10. Not defensible for a self-hosted personal tool. Revisit only if
the warm-up proves unacceptable in practice - which is decision **A5**, already recorded.

## PA2(b) - CBOE failover: open, one adopt candidate

The premise holds and is unchanged: `providers.options` is `[cboe, alpha_vantage]`, and the
Alpha Vantage options fallback is not a proven free-plan failover. So the heaviest component
in the report rests on **one unauthenticated CDN path with no proven failover**.

| Candidate | Free-tier terms | Entitlement | Stability | Verdict |
|---|---|---|---|---|
| **Tradier sandbox** | Free sandbox token, no funded account required | 15-minute delayed chains; **Greeks and IV included via ORATS** | Documented brokerage API, stable versioned endpoints, no anti-bot behaviour reported | **Adopt as failover** |
| Schwab / thinkorswim | Free with a Schwab account | Options chains, but coverage described as narrower than SIP-connected providers | Developer-portal gated; account required | Monitor - the account requirement is heavier than Tradier's sandbox |
| Polygon.io | Free tier exists | Full SIP options coverage | Stable | Monitor - free tier options entitlement not verified; likely paid for chains |
| OpenBB | Free library | A normalization layer, **not a data source** - it still needs an underlying provider | n/a | Reject as a source. It solves normalization, which is not the gap |

**Adopt: Tradier sandbox as CBOE failover.**

- Base: `https://sandbox.tradier.com/v1/`
- Shape: `GET /markets/options/chains?symbol={t}&expiration={d}&greeks=true`
- Credential: `TRADIER_API_KEY` (sandbox token)
- Licensing: brokerage market data for personal use. Greeks are ORATS-derived — **confirm
  redistribution terms before any output leaves this machine.** The app is self-hosted
  personal use, which is the permissive case, but the constraint is real and is flagged here
  per Phase A acceptance.

**Not urgent.** CBOE answered every probe on 2026-08-31 (13,160 SPY contracts, and INTC/CRWV/
AMAT all resolved during the universe work). This is redundancy for a source that has not
failed, which is precisely the class of gap this document exists to close — but it ranks
below the legs that have no source at all.

## Evidence

- `iv_history=` supplied on the live path: `pipeline.py:1371`, landed 2026-08-31.
- CBOE chains with Greeks: verified 2026-08-31, `SPY.json` 13,160 contracts carrying
  `iv, delta, gamma, theta, vega, rho`. The original "CBOE has no Greeks" premise was
  already disproven before this pass.
- Tradier sandbox terms: [docs.tradier.com FAQ](https://docs.tradier.com/docs/faq),
  [Market Data](https://docs.tradier.com/docs/market-data).

Sources: [Tradier API docs](https://docs.tradier.com/), [Best Options Data APIs 2026](https://flashalpha.com/articles/best-options-data-apis-2026)
