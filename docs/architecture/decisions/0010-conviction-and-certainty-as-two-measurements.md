# 0010 — Show conviction and certainty as two labelled measurements

| | |
|---|---|
| **Status** | Accepted. Implemented by round-2 Lane H. |
| **Date** | 2026-09-07 |
| **Round** | 2 |
| **Original identifier** | `D10` — cited by that name throughout the task documents |

---

**Decision: the report shows both the score and the letter, explicitly labelled as
different things — the score is *conviction* (how strongly the evidence supports the idea),
the letter is *certainty* (how far data quality lets that conviction be trusted).**

Since round 1 adopted the letter-cap mechanism, the score is no longer clamped by the
confidence tier but the letter still is. INTC therefore renders as `C (100.0)` — the
highest possible score beside the lowest grade letter. This was predicted in D5 and flagged
as Lane A's to resolve; it has now arrived on every row.

Rejected: showing the score alone (loses the tier warning that the letter carries — a
reader seeing 100.0 would not know every row was bottom-tier because prices were missing);
showing the letter alone (the table would sort by a value the reader cannot see, which is
the defect round 1 just fixed); re-clamping the score (undoes the letter-cap change and
restores the ties it was adopted to break).

**The cost the owner accepted:** two scales for the reader to hold at once. Lane H's job is
to make that legible rather than contradictory.
