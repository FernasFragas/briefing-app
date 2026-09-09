# 0002 — Grading scale: ALIGN — drop the probability term entirely

| | |
|---|---|
| **Status** | Accepted. Supersedes HANDOFF N6, N7 and N8. |
| **Date** | 2026-09-07 |
| **Round** | 1 |
| **Original identifier** | `D2` — cited by that name throughout the task documents |

---

The grade becomes conviction alone: `100 x alignment`, for both the directional and the
neutral branch. The thesis probability is still computed and still **printed** beside the
grade as context; it is no longer an input to the score.

**The evidence this was taken on** (all 18 rows of the 2026-09-06 run; the recomputation
reproduced 18 of 18 published grades exactly before any variant was projected):

| Scale | directional range | neutral range | gap at the top |
|---|---|---|---|
| Today | 11.5 – 81.0 | **39.8** – 75.6 | +5.4 |
| N7 as filed | 5.1 – 81.0 | **39.8** – 75.6 | +5.4 |
| N8 as filed | 5.1 – 81.0 | 0.0 – 37.3 | **+43.7** |
| N8b (N8 + rebalanced neutral weights) | 5.1 – 81.0 | 0.0 – 68.4 | +12.6 |
| **ALIGN (chosen)** | 5.1 – 81.0 | 0.0 – 81.0 | **+0.0** |

Two findings drove it, neither recorded in `HANDOFF.md` before 2026-09-07:

- **`P` is inert for directional rows.** Across every directional row it spans
  0.453–0.504 — a flat ~10-point bonus that distinguishes nothing.
- **`P` is a tautology for neutral rows.** JPM's own composite signal is 0.208, *past* the
  0.15 neutral band, so its alignment is 0.000 — its signal contradicts its stated thesis.
  It still scored 41.0 (`D`), because `0.60 x 0.683 = 41` points are paid for the
  definition of the band. AMZN is identical. Under ALIGN both correctly score 0.0.
- **N8 as filed inverts the asymmetry rather than removing it.** It strips 41 points from
  neutral rows while leaving their alignment weight at 0.40, so neutral tops out at 37.3
  against directional's 81.0. This is not mentioned in the N8 write-up and is why N8 was
  not chosen.

**This supersedes `HANDOFF.md` N6, N7 and N8.** N6 stays closed. N7 and N8 are **withdrawn,
not deferred**: ALIGN subsumes N7 (the directional probability weight becomes irrelevant
when there is no probability term) and replaces N8's remedy with a simpler one.
