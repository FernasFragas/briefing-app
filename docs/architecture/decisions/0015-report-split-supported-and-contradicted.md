# 0015 — Report layout: split the ideas table into supported and contradicted theses

| | |
|---|---|
| **Status** | Accepted. Closes the consequence 0011 left open. |
| **Date** | 2026-09-08 |
| **Round** | 3 |
| **Original identifier** | `D15` — cited by that name throughout the task documents |

---

**The single ranked table becomes two clearly headed sections:** theses the data supports,
ranked as now; and theses the data contradicts, listed with the data's own reading.

This closes the consequence D11 explicitly left open. Nine of sixteen rows score exactly
0.0 because the composite signal disagrees with the direction declared for that name in
`config/universe.example.yaml`. That is correct behaviour and D11 chose to make it visible,
but it left more than half the table carrying no ranking information, with "mildly
unsupported" and "the data says the opposite" rendering identically.

**Binding constraints on Lane L — all three are load-bearing:**
- **No grade changes.** D11's prohibition stands and is now enforced structurally:
  `dashboard/grading.py` is owned by no lane this round. This is presentation only.
- **Ordering by conviction is preserved inside the supported section**, still pinned by a
  multi-row test (definition-of-done item 3).
- **The conviction/certainty legend (item 11) and the thesis-versus-data marking (item 12)
  survive the re-layout.** They were verified by named tests in round 2; those tests must
  still pass or be replaced by strictly stronger ones.

**The costs the owner accepted:** the single sorted ladder that round 1 worked to establish
is gone; a name that moves between sections from one day to the next may read as
instability; and it is a further change to a report layout Lane H only just finished.

**Rejected:** ordering the tied block by the magnitude of its disagreement (keeps one
ladder, but puts two similar-looking numbers side by side and leaves nine dead rows in the
main table); leaving it as it is (defensible, but the cost is met every morning).
