# 0006 — Index funds: move SPY and QQQ to market context

| | |
|---|---|
| **Status** | Accepted. |
| **Date** | 2026-09-07 |
| **Round** | 1 |
| **Original identifier** | `D6` — cited by that name throughout the task documents |

---

They stop appearing as trading ideas and appear instead in the market overview as a read on
market conditions.

- An index has no issuer, so it can have no analyst coverage and no insider filings, fails
  a required-component check, and is floored at the bottom tier permanently. It occupies a
  row that can never produce a trade. Nobody chose this; it emerged from rules combining.
- The market overview currently holds a **single** line ("SPY implied weekly move"), so it
  needs the content.
- **Explicitly rejected:** exempting indexes from the components they cannot have. It would
  make them tradeable but graded on two components against four for every other row, in the
  same column, which quietly breaks comparability.
