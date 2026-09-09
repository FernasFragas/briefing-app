# 0004 — Catalysts: inferred dates may score, but may not anchor an event trade

| | |
|---|---|
| **Status** | Accepted. |
| **Date** | 2026-09-07 |
| **Round** | 1 |
| **Original identifier** | `D4` — cited by that name throughout the task documents |

---

A catalyst date inferred from a company's historical reporting cadence is good enough to
justify scoring and ranking a name, and **not** good enough to structure a trade whose
payoff depends on the event landing before expiry.

- Today the rule is all-or-nothing and rejects outright. On 2026-09-06 it rejected INTC,
  which graded B+ at 76.6 and ranks joint-first under the chosen ALIGN scale.
- 8 of 26 gated names ran on inferred dates.
- The gate already records the distinction: `flags: ["estimated_catalyst_only"]`.
- Lane D must write down which setup types genuinely depend on the date. That list is a
  judgement call and belongs in `docs/product/GATE-POLICY.md`, not buried in a condition.
