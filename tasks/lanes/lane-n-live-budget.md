# Lane N — Live-run budget ledger

**Implements:** D16. **Closes:** definition-of-done item 20.
**Depends on:** the round-3 baseline commit (gate). Runs in parallel with K, L, M.
**Live request allowance:** **0.** This lane builds the ledger and must not be its first
spender. Everything here is testable against recorded counter files and temporary
directories.

## Owns — write only these

```
ops/live_budget.py                    (new)
ops/status.py
tests/test_ops_scripts.py
docs/operations/LIVE-RUN-BUDGET.md               (new)
tasks/BUDGET-LEDGER.md        (new)
```

## Must not touch

- `src/briefing_app/**` — every source file belongs to K, L or M this round. If enforcement
  genuinely needs a change inside the application rather than in `ops/`, **that is a
  `CROSS-LANE.md` entry**, not an edit. Design so it does not.
- `ops/measure_vendor_gap.py` — Lane M.
- `ops/run_daily.py`, `ops/install_launchd.py`, `ops/serve_api.py`, `ops/audit_dashboard.py`
  — nobody owns them this round. Read them; do not write them.

---

## Where this actually stands

The Alpha Vantage free allowance is **25 requests per day**, shared by every lane and by the
daily briefing itself. The recorded counters live in `data/provider_budget/<provider>/`, one
JSON file per day:

```
data/provider_budget/alpha_vantage/2026-08-30.json
data/provider_budget/alpha_vantage/2026-09-02.json
data/provider_budget/alpha_vantage/2026-09-03.json
data/provider_budget/alpha_vantage/2026-09-04.json
data/provider_budget/alpha_vantage/2026-09-06.json
```

**Read that list again — it stops at 2026-09-06.** There is no file for 2026-09-07, because
the 2026-09-07 run reached no provider at all and made zero requests, and reported
`succeeded` while doing so. That run is the reason round 2 existed. A drained allowance is
one of the most plausible ways to reproduce it.

D16 permits lanes to spend, **inside a written allowance checked before spending**. The risk
the owner accepted, and that this lane exists to manage:

> Several lanes can each respect an individual limit and still collectively drain the pot.
> A drained pot means that day's real briefing runs degraded. **An allowance that is a
> convention is not an allowance.**

Standing allowances for round 3, from D16:

| Lane | Allowance |
|---|---|
| K | 0 requests |
| L | 0 requests |
| M | 0 Alpha Vantage requests; MarketData.app keyless probes permitted |
| N | 0 requests |
| O | 1 full daily run, on a day the owner names |

---

## Tasks

- [ ] **N1 — Define the ledger, and make claiming it a real step**

  `tasks/BUDGET-LEDGER.md`: append-only, one row per claim, in the style of
  `CROSS-LANE.md` — that file works and agents already follow it.

  Each claim records: date, lane, provider, requests claimed, purpose, and the outcome once
  spent. **A lane that has not claimed has not been granted anything**, and that sentence
  belongs at the top of the file where it cannot be missed.

  Include a filled-in worked example, not just a template. An empty template gets filled in
  wrongly; a worked example gets copied correctly.

- [ ] **N2 — `ops/live_budget.py`: answer "may I spend N requests right now?"**

  A small command, in the style of the existing `ops/status.py`, that reads the recorded
  counters and the ledger and answers before anything is spent. It must report:

  - Today's recorded spend for the provider, and what remains of the 25.
  - **The daily briefing's reservation, subtracted first.** The briefing's needs come before
    any lane's. Lane J already established this policy for the backfill — a live-run-first
    reservation, holding back the full allowance until today's run has finished, then all
    but a small remainder. **Read `src/briefing_app/backfill.py` for how it is done today
    and be consistent with it.** Do not invent a second, differently-shaped policy; two
    reservation rules that disagree are worse than one imperfect rule.
  - Whether today's daily run has already happened, since that changes the answer entirely.
  - Claims already recorded in the ledger for today, and the total they commit.
  - A clear verdict and a **non-zero exit code when the answer is no**, so it can gate a
    command rather than merely inform a reader.

  Support `--json`, matching `ops/status.py`.

  **Acceptance:** tested against temporary data roots with fabricated counter files —
  no allowance spent, no network. Cover at least: no counter file for today (which is the
  2026-09-07 case and must **not** be read as "25 available and all is well"); daily run not
  yet done; allowance already fully claimed by other lanes; and a request larger than what
  remains.

- [ ] **N3 — Surface it in `ops/status.py`**

  `status.py` is what a person actually runs to ask "is this thing healthy". It already
  reports missing runs and error states. Add the budget position: today's spend, what
  remains, whether the daily run's reservation is intact.

  Keep its existing contract — it returns non-zero on a problem and supports `--json`, and
  round 1 verified both. Do not change what it already reports; add to it.

- [ ] **N4 — Write `docs/operations/LIVE-RUN-BUDGET.md`**

  Short and operational. It must answer:

  1. What the allowance is, per provider, and where the recorded counters live.
  2. The reservation rule, in one paragraph: why the daily briefing is served first, and
     what happens to a lane that arrives after the pot is empty.
  3. How to claim: the exact ledger row to append, before spending.
  4. How to check: the exact `ops/live_budget.py` invocation and how to read the verdict.
  5. **What a lane does when the answer is no** — wait for tomorrow, or hand the run to the
     owner. Say which, so nobody improvises.
  6. Which providers are *not* budget-tracked and why they are outside this scheme
     (MarketData.app keyless, CBOE, FRED, SEC EDGAR).

- [ ] **N5 — Report completion in `CROSS-LANE.md`**

  Lane O cannot spend its one authorised run until the ledger exists. Say so in the entry.

---

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_ops_scripts.py -q
PYTHONPATH=src .venv/bin/python -m pytest                    # expect >= 671 passed
PYTHONPATH=src .venv/bin/python ops/live_budget.py --json
PYTHONPATH=src .venv/bin/python ops/status.py --json
```

Exercise the no-counter-file case explicitly, since it is the real 2026-09-07 shape:

```bash
BRIEFING_DATA_DIR=$(mktemp -d) PYTHONPATH=src .venv/bin/python ops/live_budget.py --json
```

## Done when

- `tasks/BUDGET-LEDGER.md` exists, states that an unclaimed lane has no allowance,
  and carries a worked example.
- `ops/live_budget.py` answers before spending, reserves the daily run first, exits non-zero
  when the answer is no, and is tested against fabricated counters with no network.
- Its reservation policy matches `backfill.py`'s rather than competing with it.
- `ops/status.py` reports the budget position and keeps its existing contract.
- `docs/operations/LIVE-RUN-BUDGET.md` answers all six questions in N4.
- This lane spent nothing: `ls data/provider_budget/alpha_vantage/` shows today's counter
  unchanged.
