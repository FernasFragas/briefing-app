# 0007 — Universe: mark the European names inactive; fix the duplicates

| | |
|---|---|
| **Status** | Accepted. |
| **Date** | 2026-09-07 |
| **Round** | 1 |
| **Original identifier** | `D7` — cited by that name throughout the task documents |

---

- `RHM.DE`, `LDO.MI`, `ASML.AS` and `SIE.DE` are rejected every run with
  `eu_options_unavailable`. No free source covers European options and that work is
  deferred indefinitely (`docs/research/alternatives/pa5-eu-sources.md`, `pb5-fca-deferred.md`).
- They stay in the configuration behind an explicit `inactive` flag, so the intent to cover
  Europe survives in the file, and the gate skips them **without emitting a rejection**.
- `RHM.DE` and `NVDA` are each listed twice. That is a straightforward mistake.
- The universe is otherwise working as designed: 35 configured, 18 reaching the report, and
  the shortfall is the candidate gate correctly dropping names with no catalyst in the
  horizon window. **That is not a bug and no lane should "fix" it.**
