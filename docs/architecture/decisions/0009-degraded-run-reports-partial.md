# 0009 — A degraded run must report itself as degraded

| | |
|---|---|
| **Status** | Accepted. Implemented by round-2 Lane G. |
| **Date** | 2026-09-07 |
| **Round** | 2 |
| **Original identifier** | `D9` — cited by that name throughout the task documents |

---

**Decision: escalate per-ticker problems to run-level diagnostics, which marks the run
`partial`. The report is still written and still saved, carrying a visible banner naming
what was missing.**

**The defect.** `_final_status` (`pipeline.py:2930`) is two lines:

```python
if output.failures or output.diagnostics:
    return STATUS_PARTIAL
return STATUS_SUCCEEDED
```

Per-ticker problems accumulate in a separate `issues` list with **44 recording points** —
including `no measured sigma from real closes` and `iv rank baseline still building` — and
that list **never reaches `output.diagnostics`**. Only load warnings, `setup_rules`
exceptions and pipeline exceptions do (`pipeline.py:479, 499, 500, 572, 608, 658, 679`).

**What that hid.** Run `daily-2026-09-07-f1b0d2e1` reported `succeeded`, 0 failures,
0 diagnostics. In fact:
- No provider budget file exists for 2026-09-07 for Financial Modeling Prep, Finnhub or
  Alpha Vantage — their budget records stop at 2026-09-06. **Zero requests were made.**
- No raw cache directory was written for 2026-09-07 at all.
- Every name lost its price closes, so there was no measured volatility, so the entire
  universe floored to the bottom confidence tier with **nothing tradeable**.
- The sentiment component was absent from every row; the macro component degraded to
  `partial`.

**The rejected alternatives, and why.** Hard-failing the run was rejected because it
discards the day's snapshot, and the volatility baseline being built over 14 days cannot
afford to lose sessions. Publishing nothing was rejected because silence is
indistinguishable from a scheduler that did not fire — the very failure being fixed.
Advisory-only was rejected because it leaves the misleading status in place.

> **The risk the owner accepted, which Lane G must actively manage.** If every routine
> condition escalates, `partial` becomes the new constant and carries exactly as little
> information as `succeeded` does today. **A warm-up baseline still building is normal and
> must not mark a run partial. A provider that was never reached must.** Lane G owns that
> distinction and it is the substance of the task, not a detail of it.

**One consequence for the record.** Round 1's `RESULTS.md` marks definition-of-done item 2,
"live run clean", as **Passed**, citing `status=succeeded, failures=0, diagnostics=0` on
this very run. That verification was reading a status that could not fail. Lane G must
re-verify item 2 once the status means something.
