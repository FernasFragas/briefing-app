# 0011 — Show the declared thesis and the data's reading side by side

| | |
|---|---|
| **Status** | Accepted. Its open consequence — nine rows tied at 0.0 — was closed by [0015](0015-report-split-supported-and-contradicted.md). |
| **Date** | 2026-09-07 |
| **Round** | 2 |
| **Original identifier** | `D11` — cited by that name throughout the task documents |

---

**Decision: the report displays both the direction declared in the universe configuration
and what the composite signal actually reads, as separate visible facts.**

**The mechanism, which is not a bug.** A watchlist setup takes
`direction=evaluation.candidate.direction` (`strategy/engine.py:1210`) — the direction
**declared in `config/universe.example.yaml`**, not the model's own read. GOOGL is declared
`long` there with the thesis "Regulatory decision event directional"; its composite signal
reads `neutral` at −0.094. The round-1 grading change scores support for the *stated*
direction, so it correctly returns 0.0.

Nine of sixteen rows are in this state. The previous scale paid them between 10 and 41
points and hid it. **This is the tool falsifying your declared theses, and it is arguably
the most valuable thing it does.**

Rejected: letting the composite score set the direction. It is circular — the grade would
measure the signal against a direction derived from that same signal, agree with itself by
construction, and could never tell you a thesis is wrong.

> **Open consequence, explicitly accepted and NOT closed by this decision.** Making the
> disagreement visible does not restore ranking: nine of sixteen rows still score exactly
> 0.0 with no ordering among them, so more than half the table carries no ranking
> information and "mildly unsupported" is indistinguishable from "the data says the
> opposite". The owner chose presentation over a further scale change. **Lane H must not
> quietly fix this by changing the grade**; it may only make the disagreement visible.
> If the tied block proves unreadable in practice, that is a new decision, not a lane call.
