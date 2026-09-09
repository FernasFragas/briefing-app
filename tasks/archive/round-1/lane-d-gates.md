# Lane D — Gates and universe

**Implements:** D4 (catalyst rule), D7 (universe cleanup). **Closes:** part of blocker #1.
**Depends on:** Lane 0 only. Runs in parallel with A, B, C, E.

## Owns — write only these

```
src/briefing_app/strategy/engine.py
src/briefing_app/universe/gate.py
src/briefing_app/universe/loader.py
src/briefing_app/config.py
config/universe.example.yaml
config/config.example.yaml
tests/test_gate.py
tests/test_strategy_engine.py
tests/test_loader.py
docs/product/GATE-POLICY.md              (new)
```

## Must not touch

`models/gate.py` and `strategy/models.py` hold the rejection-code enums. **Adding** a code
there would be a cross-lane edit — but neither task below needs a new code, so this should
not arise. If you conclude one is needed, record it in `CROSS-LANE.md` first.

> **You own `config.py`.** Lane A deliberately leaves `ReportGradingSettings` alone so this
> lane can hold the file. Do not remove the now-unused `probability_weight`,
> `alignment_weight` or `directional_probability_weight` fields — Lane A's tests and the
> loader tests both still reference them, and a later cleanup removes them in one place.

---

## There are two different gates — know which you are editing

| Gate | Where | Decides | Rejection codes |
|---|---|---|---|
| **Candidate gate** | `universe/gate.py`, codes in `models/gate.py` | which names enter the run at all | `no_catalyst_in_horizon`, `eu_options_unavailable`, `class_not_enabled` |
| **Setup gate** | `strategy/engine.py:683`, codes in `strategy/models.py` | which setups may be traded | `catalyst_not_confirmed`, `iv_rank_unavailable`, `illiquid_chain` |

**D4 is the setup gate.** D7 is the candidate gate. They are unrelated changes that happen
to both live in this lane.

---

## Tasks

- [ ] **D1 — Inferred catalyst dates may score but may not anchor an event trade**

  `strategy/engine.py:683` currently raises `CATALYST_NOT_CONFIRMED` for any catalyst whose
  date was inferred from historical reporting cadence rather than announced. On 2026-09-06
  that rejected INTC with the detail:

  > `Foundry / product update (2026-09-15, estimated) is cadence-inferred; an event trade
  > needs an IR or exchange-sourced date`

  INTC graded B+ at 76.6 and ranks joint-first under the ALIGN scale Lane A is building.
  8 of 26 gated names ran on inferred dates.

  Under D4 the rule becomes conditional on setup type: an inferred date is sufficient to
  score, rank and watch a name, and insufficient only for a setup whose **payoff depends on
  the event landing before expiry**.

  **The judgement you must make and write down.** Which of the ten `SetupType` values
  genuinely depend on the date? The obvious reading is that the `EVENT_DIRECTIONAL_*`
  family does and `WATCHLIST_NO_TRADE` does not, but `POSITIONAL_LONG`, the premium
  structures and `SKEW_STRUCTURE` each need a deliberate answer. Put the full table in
  `docs/product/GATE-POLICY.md` with one line of reasoning each. Do not bury the list in a
  condition — it is a product rule, and the next person to read it needs the reasoning.

  The gate already records the distinction as `flags: ["estimated_catalyst_only"]`, so the
  information is available and does not need to be re-derived.

  **Acceptance:**
  - A `WATCHLIST_NO_TRADE` setup on an inferred date is no longer rejected and produces a
    graded row.
  - An `EVENT_DIRECTIONAL_VERTICAL` setup on an inferred date **is still rejected**, with
    the same code and a detail naming the dependency.
  - The rejection detail still names the date and its source, as it does today — that text
    is good and should not regress.
  - Every setup surviving on an inferred date is marked, so the report can show it. **A
    reader must never see an inferred date presented as a confirmed one.**

- [ ] **D2 — Add an `inactive` flag to universe entries**

  Four European names are rejected on every single run:

  ```
  RHM.DE   eu_options_unavailable
  LDO.MI   eu_options_unavailable
  ASML.AS  eu_options_unavailable
  SIE.DE   leverage_requires_confirmed_catalyst, eu_options_unavailable
  ```

  No free source covers European options and that work is deferred indefinitely
  (`docs/research/alternatives/pa5-eu-sources.md`, `pb5-fca-deferred.md`). `POST-P3-DECISIONS.md` §3
  already resolved to drop two of the four; that decision was never executed.

  Under D7 they stay in the file behind an explicit flag, so the intent to cover Europe
  survives, and the gate skips them **without emitting a rejection**.

  **Acceptance:**
  - A universe entry marked inactive is skipped before evaluation and appears in **neither**
    the ideas table nor `rejected_at_gate`.
  - The flag requires a reason string. An entry cannot be silently disabled — the file must
    say why, and the reason must reach `docs/product/GATE-POLICY.md`.
  - The four European names carry the flag and a reason pointing at the deferral memo.
  - `load_config()` rejects an inactive entry with no reason, at load time, naming the
    field. Follow the T1 precedent: an invalid config fails the load, not the run.

- [ ] **D3 — Remove the duplicated universe entries**

  `RHM.DE` and `NVDA` are each listed twice in `config/universe.example.yaml`. The gate
  catches it (`duplicate_ticker`), which is why it has not caused harm, but it should not
  need to.

  **Acceptance:**
  - No ticker appears twice in the shipped universe file.
  - The loader **still** rejects a duplicate — do not remove the check along with the
    duplicates. A test pins it.

- [ ] **D4 — Write `docs/product/GATE-POLICY.md`**

  The two gates and what each decides; the setup-type table from D1 with its reasoning; the
  inactive-entry policy and the current list with reasons; and one explicit note that the
  35-configured-to-18-reported shortfall is the candidate gate **working correctly** —
  names without a catalyst in the horizon window are supposed to drop out. That note exists
  to stop a future reader "fixing" it.

---

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_gate.py tests/test_strategy_engine.py \
    tests/test_loader.py -q
PYTHONPATH=src .venv/bin/python -m pytest -q
```

## Handoff

Report to Lane F: the setup-type dependency table from D1, and the expected change in
gated-name count so Lane F can tell a policy change from a regression on the live run.
