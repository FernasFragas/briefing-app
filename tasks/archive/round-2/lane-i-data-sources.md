# Lane I — Free sources for historical option chains

**Implements:** D12, which is **OPEN**. This lane produces the evidence that closes it.
**Depends on:** nothing. Start immediately — it gates Lane J.
**Deliverable:** a written recommendation, not code.

## Owns — write only these

```
docs/research/alternatives/historical-options-sources.md    (new)
```

## Must not touch

Any source file. This lane researches and reports. If it concludes that a provider should
be wired, that is a **new** task for a later lane, not this one.

---

## What is actually needed — be precise, or the answer will be useless

The backfill needs, for **each (ticker, past trading date)** pair, enough of a historical
option chain to compute the five values `build_backfill_snapshot_row` stores
(`backfill.py:258`, `:340`):

| Field | Derived from |
|---|---|
| `iv_atm` | at-the-money implied volatility, nearest weekly expiry |
| `expected_move_1w` | weekly straddle as a percentage |
| `expected_move_1m` | monthly straddle as a percentage |
| `pc_ratio_vol` | put/call **volume** ratio across the chain |
| `pc_ratio_oi` | put/call **open interest** ratio across the chain |

So the minimum viable record is a **full option chain as it stood on a past date**, with
per-contract strike, expiry, type, implied volatility, volume and open interest, plus the
underlying spot for that date.

**Scope:** 18 United States tickers, 20 trading sessions (2026-08-10 to 2026-09-07). The
exact list is printed by `PYTHONPATH=src .venv/bin/python -m briefing_app.cli backfill-iv --dry-run`.

> ### The distinction that decides this entire task
>
> **A live chain is not a historical chain.** Most free options data — including CBOE and
> Tradier, both already known to this project — returns the chain **as of now**. That is
> useless for backfilling 2026-08-10, and confusing the two is the most likely way this
> research goes wrong. Every candidate must be assessed on whether it serves a **past
> date**, and you must state which endpoint and parameter does it.
>
> Alpha Vantage `HISTORICAL_OPTIONS` is currently the *only* wired source that does.

---

## Read these first — do not redo work already done

`docs/research/alternatives/pa2-iv-history-and-chain-failover.md` already covers much of this ground.
Its conclusions, which you should treat as findings to build on rather than to repeat:

- **PA2(a) rejected paid IV-history vendors** (ORATS, Market Chameleon) in favour of the
  20-session self-build, on the grounds that a subscription was not defensible to remove a
  20-session wait on a leg weighted 0.10. It records decision **A5: revisit only if the
  warm-up proves unacceptable in practice.**
  **That condition has now been met** — the warm-up has 3 of 20 sessions after five days,
  the free allowance implies 14 more days, and the product produces almost nothing
  meanwhile. This lane *is* the A5 revisit. Say so in your document.
- **PA2(b) already adopted Tradier sandbox** as a live-chain failover: free sandbox token,
  no funded account, 15-minute delayed chains, **Greeks and implied volatility included**.
  The open question for you is narrow and specific: **does Tradier expose chains for a past
  date, or only current?** If it does, it is very likely the answer.
- **Polygon.io was left as "monitor — free tier options entitlement not verified".** That is
  an unresolved lead directly relevant here. Resolve it.
- **OpenBB was rejected as a source** — it is a normalisation layer over other providers.
  Do not re-propose it.

---

## Tasks

- [ ] **I1 — Check `https://api.quiverquant.com`, as the owner specifically asked**

  Establish plainly whether it serves historical option chains with the per-contract fields
  listed above, and on what free terms.

  Context you should have: this project already knows Quiver as a **political-flow**
  candidate — `QUIVER_API_KEY` is listed in configuration (`config.py:55`) and was left
  empty because Financial Modeling Prep already covers congressional trading. Quiver's
  published focus is alternative data (congressional trading, retail forum activity,
  government contracts, insider filings, patents).

  **Report what you find, not what you expect.** If it does not serve option chains, say so
  in one line with the evidence and move on — a clear negative is a complete answer to the
  question that was asked, and the owner asked it explicitly.

- [ ] **I2 — Survey the realistic free candidates for historical chains**

  At minimum resolve: **Tradier** (past-date endpoint — the highest-value question here),
  **Polygon.io** (free-tier options entitlement, explicitly left unverified by PA2),
  **Databento**, **Intrinio**, **MarketData.app**, **ORATS** free tier, **Dolt / open
  datasets** of historical option chains, and anything else you find.

  For each, one row:

  | Provider | Past-date chains? | IV / volume / open interest? | Free-tier limit | Coverage of the 18 names | Credential needed | Verdict |

  **Verify rather than repeat documentation.** A provider's marketing page is not evidence.
  Where a free credential can be obtained without a funded account or a payment method,
  obtain one and make a real request for one ticker on one past date, then record the actual
  response. Where it cannot, say that the claim is unverified and why.

  **Do not spend Alpha Vantage quota.** It is 25 requests per day, shared with the live run
  and with Lane J's correctness test. Point `BRIEFING_DATA_DIR` at the scratchpad for any
  probing so the shared budget counters are not disturbed.

- [ ] **I3 — Also evaluate the option of not backfilling at all**

  A fair comparison needs the do-nothing baseline. The alternatives the owner declined to
  choose between are on the table and should be costed against whatever you find:

  | Option | Cost | Time to a usable product |
  |---|---|---|
  | Alpha Vantage premium, one month | ~$50, cancellable | minutes |
  | Alpha Vantage free, run daily | free | 14 days, if no day is missed |
  | Reduced ticker set on the free tier | free | ~5 days, partial coverage |
  | A free source you find | free | your estimate |

  Note the competition honestly: the daily live run and the backfill draw on the **same** 25
  requests per day, so 14 days is optimistic rather than expected.

- [ ] **I4 — Write the recommendation**

  `docs/research/alternatives/historical-options-sources.md`, following the house style of the other
  memos in that directory: the premise, what was probed and what actually answered, a table,
  and a single clear recommendation with its reasoning.

  End with a plain statement of what the owner should decide, because D12 stays open until
  they do. If the honest answer is "no free source serves historical chains and the fifty
  dollars is the cheapest path", **say that** — a negative result that closes a decision is
  worth more than a hedge.

---

## Verify

There is no test suite for a research task. The standard is instead:

- Every claim is either backed by a request you actually made and recorded, or is explicitly
  labelled unverified with the reason.
- The Quiver question is answered directly, because it was asked directly.
- Someone reading only your document can make the funding decision without re-researching.

## Handoff

Report to the owner and to Lane J: the recommended source, or the recommendation to pay, or
the recommendation to wait. **Lane J cannot execute a full backfill until this lands.**
