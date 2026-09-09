# Gate Policy

The application has two gates.

The candidate gate runs in `src/briefing_app/universe/gate.py` before any provider pull. It
decides which configured names enter the run at all. Candidate rows can be accepted for
scoring, moved to the rejected-at-gate table, or skipped before evaluation when the
universe entry is explicitly inactive.

The setup gate runs in `src/briefing_app/strategy/engine.py` after scoring. It decides
which scored names can become executable setups. A name can still produce a graded
watchlist row when no executable setup is allowed.

## Inferred Catalyst Dates

An inferred catalyst date can justify scoring, ranking, and watching a name. It cannot
anchor a setup whose payoff depends on the event landing before expiry.

| Setup type | Confirmed date required? | Reason |
|---|---:|---|
| `short_premium_iron_condor` | Yes | The volatility sale relies on modeled event risk resolving inside the sold expiry. |
| `long_premium_straddle` | Yes | The long premium expression pays for the event move and needs the event inside the owned expiry. |
| `long_premium_calendar` | Yes | The structure is chosen from the event's position versus front expiry, so the date is load-bearing. |
| `skew_structure` | No | The trade is keyed to skew versus tails; the catalyst is context, not the timing anchor. |
| `event_directional_long` | Yes | Directional event payoff depends on the named event arriving before expiry. |
| `event_directional_put` | Yes | Directional event payoff depends on the named event arriving before expiry. |
| `event_directional_vertical` | Yes | The defined-risk event expression is still an event trade with date-dependent payoff. |
| `positional_long` | No | The thesis is multi-week ownership, insider, and sentiment alignment rather than exact event timing. |
| `borrow_dependent_short` | No | The setup is borrow and thesis dependent; the event date informs the horizon but is not the payoff anchor. |
| `watchlist_no_trade` | No | No trade is emitted, so an inferred date can be shown as long as it is clearly marked. |

Every setup that survives on an inferred date must carry an inferred-date warning. The
warning must name the catalyst date and source so the report never presents a cadence
estimate as an announced date.

## Inactive Universe Entries

Universe entries can set `inactive: true` only with a non-empty `inactive_reason`. An
inactive ticker is skipped before candidate-gate evaluation and must appear in neither the
ideas table nor `rejected_at_gate`.

Current inactive tickers:

| Ticker | Reason |
|---|---|
| `RHM.DE` | EU coverage deferred: no free EU per-strike option chain or national OAM automation is available; see `docs/alternatives/pa5-eu-sources.md` and `docs/alternatives/pb5-fca-deferred.md`. |
| `LDO.MI` | EU coverage deferred: no free EU per-strike option chain or national OAM automation is available; see `docs/alternatives/pa5-eu-sources.md` and `docs/alternatives/pb5-fca-deferred.md`. |
| `ASML.AS` | EU coverage deferred: no free EU per-strike option chain or national OAM automation is available; see `docs/alternatives/pa5-eu-sources.md` and `docs/alternatives/pb5-fca-deferred.md`. |
| `SIE.DE` | EU coverage deferred: no free EU per-strike option chain or national OAM automation is available; see `docs/alternatives/pa5-eu-sources.md` and `docs/alternatives/pb5-fca-deferred.md`. |

The historical 35-configured-to-18-reported shortfall is not a bug. Names with no catalyst
inside the configured horizon are supposed to drop out at the candidate gate; widening the
horizon or fabricating catalysts to increase the reported count would be a policy
regression.
