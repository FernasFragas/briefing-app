# 0016 — Live runs: agents may spend, inside a stated and enforced budget

| | |
|---|---|
| **Status** | Accepted. Does not reverse the owner's standing arrangement that the daily briefing is launched by hand. |
| **Date** | 2026-09-08 |
| **Round** | 3 |
| **Original identifier** | `D16` — cited by that name throughout the task documents |

---

Lanes may make live provider requests, subject to a written per-lane allowance that is
checked against the recorded daily counters in `data/provider_budget/<provider>/` **before**
spending, exactly as Lane J's reservation already does.

**The failure this must not cause.** The Alpha Vantage free allowance is 25 requests a day,
shared by every lane and by the daily briefing itself. Several lanes can each respect an
individual limit and still collectively drain the pot, and a drained pot produces precisely
the degraded, provider-less run that round 2 existed to fix — the budget files under
`data/provider_budget/alpha_vantage/` stop at 2026-09-06 and the 2026-09-07 run reached no
provider at all.

**Therefore the allowance is a ledger, not a convention.** Lane N owns it. A lane that has
not claimed its allowance in the ledger has not been granted one, and the daily briefing's
own needs are reserved first.

Standing allowances for round 3, spendable only once Lane N's ledger exists:

| Lane | Allowance | Purpose |
|---|---|---|
| K | 0 requests | Threshold change; fixture-mode tests only. |
| L | 0 requests | Presentation; fixture-mode tests only. |
| M | 0 Alpha Vantage requests; MarketData.app keyless probes permitted | The free half of D14. MarketData.app is not budget-tracked and is not shared with the daily run. |
| N | 0 requests | Builds the ledger; must not be its first spender. |
| O | 1 full daily run, on a day the owner names | Live re-verification of definition-of-done items 2 and 9. |

**Rejected:** agents preparing commands for the owner to run by hand (safest, but every
network-dependent criterion then stalls until the owner is at the keyboard); unrestricted
agent runs (contradicts how this project is operated and reproduces the 2026-09-07 failure
by the most plausible route).

> **Note for the record.** This does not reverse the owner's standing arrangement that the
> **daily briefing** is launched by hand and not by `launchd`. That remains true; D16
> governs verification runs by lanes, which are a different thing.
