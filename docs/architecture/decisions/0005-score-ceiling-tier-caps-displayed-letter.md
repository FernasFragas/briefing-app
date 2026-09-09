# 0005 — Score ceiling: re-cut the grade letters against the reachable range

| | |
|---|---|
| **Status** | Accepted. Its open consequence — score and letter disagreeing on ordering — was carried into [0010](0010-conviction-and-certainty-as-two-measurements.md). |
| **Date** | 2026-09-07 |
| **Round** | 1 |
| **Original identifier** | `D5` — cited by that name throughout the task documents |

---

No row can currently reach the top confidence tier, because the sentiment component is
`aggregator` quality by construction, so every score is clamped at 81 and the top fifth of
the scale is dead. Under ALIGN three of the best rows tie at exactly 81.0.

**Explicitly rejected:** relabelling the sentiment component's source quality to unlock
Tier A. Adjusting a data-quality label to obtain better-looking grades is the change
`HANDOFF.md` warns against most directly, and it makes every future inconvenient label
negotiable.

> ### Refinement found while planning — Lane A must confirm or reject it
>
> The obvious reading of D5 — rescale the letter bands by 0.81 — **is wrong, and breaks the
> tier system.** Measured on the real rows: three Tier B rows would read `A+` and the
> Tier C row SPY would read `B`. That is precisely what the ceiling exists to prevent.
>
> The mechanism that satisfies D5's intent is different: **make the tier cap the displayed
> letter rather than clamp the score.** The score then keeps its full resolution for
> ranking — ORCL 93.1, AMAT 84.5, INTC 83.6 instead of three rows tied at 81.0 — while a
> Tier B row still cannot *display* above `B+` and a Tier C row still cannot display above
> `C`. Under it the existing letter bands may need no re-cut at all.
>
> One consequence to check: the score column and the letter column can then disagree on
> ordering (a Tier C row scoring 79.0 displays `C` while a Tier B row scoring 64.6 displays
> `B+`). After D6 removes SPY and QQQ from the table, every remaining row on the last run
> is Tier B and shares one cap, so the conflict does not arise today — but Lane A must
> decide what happens when it does.
>
> **Lane A owns this call.** Implement it, or reject it in writing in `CROSS-LANE.md`.
