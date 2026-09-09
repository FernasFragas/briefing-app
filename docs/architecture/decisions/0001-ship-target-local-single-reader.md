# 0001 — Ship target: local, single reader

| | |
|---|---|
| **Status** | Accepted. |
| **Date** | 2026-09-07 |
| **Round** | 1 |
| **Original identifier** | `D1` — cited by that name throughout the task documents |

---

The application runs on the owner's own machine, for the owner alone.

**Consequences that bind the lanes:**
- No public hosting workstream. No managed database, no object storage, no cloud scheduler.
- The unauthenticated HTTP endpoints are **still fixed** (Lane E), because the failure is
  fail-open by design and would become a live quota-drain the moment the app is ever
  exposed. It is a small fix; leaving a known fail-open default in place is not.
- Scheduling is local (`launchd`), which introduces its own failure mode: the run is
  skipped whenever the machine is asleep. Lane E must make a skipped run **visible**,
  because a silently missed day stalls the volatility baseline in D3.
- The bounded LLM prose layer is low value for one reader who can read the numbers. See
  Lane E task E4 for the recommended disposition.
